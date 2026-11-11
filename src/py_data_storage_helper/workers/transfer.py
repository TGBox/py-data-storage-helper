import datetime
from typing import Tuple
import os
import time
import hashlib
import shutil
from typing import Dict, List, Optional, Any
from PySide6.QtCore import QThread, Signal

from ..core.utils import to_long_path
from ..core.windows import WindowsPowerManager, PhysicalDiskResolver
from ..core.database import DatabaseManager
from ..core.plan import StoragePlan


class SingleFileTransferWorker(QThread):
    sig_file_progress = Signal(str, str, 'qint64', 'qint64', float)
    sig_file_completed = Signal(str, str, str, 'qint64', str)

    def __init__(self, op: Dict[str, Any], conflict_strategy: str = "VERSION", verify_checksum: bool = True, preserve_timestamps: bool = True):
        super().__init__()
        self.op = op
        self.conflict_strategy = conflict_strategy
        self.verify_checksum = verify_checksum
        self.preserve_timestamps = preserve_timestamps
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        op_id = self.op.get("op_id", "op_0")
        src_vol = self.op.get("source_volume", "C:")
        src_rel = self.op.get("source_path", "")
        tgt_vol = self.op.get("target_volume", "D:")
        tgt_rel = self.op.get("target_path", "")

        src_full = os.path.join(src_vol, src_rel)
        tgt_full = os.path.join(tgt_vol, tgt_rel)
        fname = os.path.basename(src_full)

        long_src = to_long_path(src_full)
        long_tgt = to_long_path(tgt_full)

        if not os.path.exists(long_src):
            self.sig_file_completed.emit(op_id, "FAILED", "Quelldatei nicht gefunden", 0, "")
            return

        try:
            total_size = os.path.getsize(long_src)
            tgt_dir = os.path.dirname(long_tgt)
            if tgt_dir:
                os.makedirs(tgt_dir, exist_ok=True)

            if os.path.exists(long_tgt):
                if self.conflict_strategy == "SKIP":
                    self.sig_file_completed.emit(op_id, "SKIPPED", "Datei existiert bereits am Ziel", total_size, "")
                    return
                elif self.conflict_strategy == "VERSION":
                    base, ext = os.path.splitext(long_tgt)
                    long_tgt = f"{base}_kopie_{int(time.time()) % 1000}{ext}"

            part_path = long_tgt + ".stpart"
            chunk_size = 1024 * 1024
            copied_bytes = 0
            hasher_src = hashlib.sha256() if self.verify_checksum else None
            start_t = time.time()

            with open(long_src, "rb") as f_in, open(part_path, "wb") as f_out:
                while True:
                    if self._cancelled:
                        break
                    chunk = f_in.read(chunk_size)
                    if not chunk:
                        break
                    f_out.write(chunk)
                    if hasher_src:
                        hasher_src.update(chunk)
                    copied_bytes += len(chunk)

                    el = max(0.001, time.time() - start_t)
                    spd = copied_bytes / el
                    self.sig_file_progress.emit(op_id, fname, copied_bytes, total_size, spd)

            if self._cancelled:
                if os.path.exists(part_path):
                    os.remove(part_path)
                self.sig_file_completed.emit(op_id, "CANCELLED", "Abbruch durch Benutzer", copied_bytes, "")
                return

            if os.path.exists(long_tgt):
                os.remove(long_tgt)
            os.rename(part_path, long_tgt)

            if self.preserve_timestamps:
                st = os.stat(long_src)
                os.utime(long_tgt, (st.st_atime, st.st_mtime))

            if self.op.get("type") == "MOVE":
                try:
                    os.remove(long_src)
                except Exception:
                    pass

            chk = hasher_src.hexdigest() if hasher_src else ""
            self.sig_file_completed.emit(op_id, "SUCCESS", "Erfolgreich übertragen", total_size, chk)

        except Exception as ex:
            self.sig_file_completed.emit(op_id, "FAILED", str(ex), 0, "")



class SpindleAwareTransferCoordinator(QThread):
    sig_overall_progress = Signal(int, int, 'qint64', 'qint64', float, str)
    sig_active_streams = Signal(list)
    sig_spindle_telemetry = Signal(dict)
    sig_item_completed = Signal(str, str, str)
    sig_file_progress = Signal(str, 'qint64', 'qint64')
    sig_log = Signal(str)
    sig_finished = Signal(dict)

    def __init__(self, plan: StoragePlan, db: DatabaseManager, conflict_strategy: str = "VERSION",
                 verify_checksum: bool = True, preserve_timestamps: bool = True,
                 ssd_concurrency: int = 3, strict_hdd_lock: bool = True):
        super().__init__()
        self.plan = plan
        self.db = db
        self.conflict_strategy = conflict_strategy
        self.verify_checksum = verify_checksum
        self.preserve_timestamps = preserve_timestamps
        self.ssd_concurrency = ssd_concurrency
        self.strict_hdd_lock = strict_hdd_lock

        self._cancelled = False
        self._paused = False
        self.active_workers: Dict[str, SingleFileTransferWorker] = {}
        self.active_worker_stats: Dict[str, Dict[str, Any]] = {}
        self.spindle_allocations: Dict[str, int] = {}
        self.db_volumes = self.db.get_volumes()

    def cancel(self) -> None:
        self._cancelled = True
        for w in self.active_workers.values():
            w.cancel()

    def toggle_pause(self) -> bool:
        self._paused = not self._paused
        return self._paused

    def _resolve_spindles(self, op: Dict[str, Any]) -> Tuple[Tuple[str, str, bool], Tuple[str, str, bool]]:
        src_vol = op.get("source_volume", "C:")
        tgt_vol = op.get("target_volume", "D:")
        src_info = PhysicalDiskResolver.get_physical_disk_info(src_vol, self.db_volumes)
        tgt_info = PhysicalDiskResolver.get_physical_disk_info(tgt_vol, self.db_volumes)
        return src_info, tgt_info

    def run(self) -> None:
        WindowsPowerManager.prevent_sleep()
        ops = self.plan.operations
        total_ops = len(ops)
        total_bytes = sum(o.get("size", 0) for o in ops)
        completed_ops_count = 0
        transferred_total_bytes = 0
        success_count = 0
        failed_count = 0
        start_time = time.time()

        pending_ops = [op for op in ops]
        active_finished_events: List[Tuple[str, str, str, int, str]] = []

        while (pending_ops or self.active_workers) and not self._cancelled:
            while self._paused and not self._cancelled:
                time.sleep(0.2)

            while active_finished_events:
                ev_op_id, status, msg, actual_sz, chk = active_finished_events.pop(0)
                completed_ops_count += 1
                if status == "SUCCESS":
                    success_count += 1
                    transferred_total_bytes += actual_sz
                elif status == "SKIPPED":
                    pass
                else:
                    failed_count += 1

                if ev_op_id in self.active_workers:
                    worker = self.active_workers.pop(ev_op_id)
                    src_info, tgt_info = self._resolve_spindles(worker.op)
                    src_disk = src_info[0]
                    tgt_disk = tgt_info[0]
                    self.spindle_allocations[src_disk] = max(0, self.spindle_allocations.get(src_disk, 1) - 1)
                    self.spindle_allocations[tgt_disk] = max(0, self.spindle_allocations.get(tgt_disk, 1) - 1)
                    if ev_op_id in self.active_worker_stats:
                        del self.active_worker_stats[ev_op_id]
                    worker.wait(500)
                    worker.deleteLater()

                self.sig_item_completed.emit(ev_op_id, status, msg)

            idx = 0
            while idx < len(pending_ops) and not self._cancelled:
                op_candidate = pending_ops[idx]
                src_info, tgt_info = self._resolve_spindles(op_candidate)
                src_disk, _, src_ssd = src_info
                tgt_disk, _, tgt_ssd = tgt_info

                src_max = self.ssd_concurrency if src_ssd else (1 if self.strict_hdd_lock else self.ssd_concurrency)
                tgt_max = self.ssd_concurrency if tgt_ssd else (1 if self.strict_hdd_lock else self.ssd_concurrency)
                src_curr = self.spindle_allocations.get(src_disk, 0)
                tgt_curr = self.spindle_allocations.get(tgt_disk, 0)

                if (src_curr < src_max) and (tgt_curr < tgt_max):
                    op_to_start = pending_ops.pop(idx)
                    op_id = op_to_start.get("op_id", f"op_{len(self.active_workers)}")
                    op_to_start["status"] = "IN_PROGRESS"

                    self.spindle_allocations[src_disk] = src_curr + 1
                    self.spindle_allocations[tgt_disk] = tgt_curr + 1

                    worker = SingleFileTransferWorker(
                        op=op_to_start,
                        conflict_strategy=self.conflict_strategy,
                        verify_checksum=self.verify_checksum,
                        preserve_timestamps=self.preserve_timestamps
                    )

                    def make_progress_handler(w_op_id, w_src_d, w_tgt_d):
                        def on_prog(oid, fname, cur_b, tot_b, spd):
                            self.active_worker_stats[w_op_id] = {
                                "op_id": w_op_id, "name": fname, "src_disk": w_src_d, "tgt_disk": w_tgt_d,
                                "cur_bytes": cur_b, "total_bytes": tot_b, "speed": spd,
                                "pct": int((cur_b / max(1, tot_b)) * 100)
                            }
                            self.sig_file_progress.emit(fname, cur_b, tot_b)
                        return on_prog

                    def make_complete_handler(w_op_id):
                        def on_comp(oid, status, msg, sz, chk):
                            active_finished_events.append((w_op_id, status, msg, sz, chk))
                        return on_comp

                    worker.sig_file_progress.connect(make_progress_handler(op_id, src_disk, tgt_disk))
                    worker.sig_file_completed.connect(make_complete_handler(op_id))
                    self.active_workers[op_id] = worker
                    worker.start()
                else:
                    idx += 1

            time.sleep(0.08)

            current_active_bytes = sum(s.get("cur_bytes", 0) for s in self.active_worker_stats.values())
            overall_done_bytes = transferred_total_bytes + current_active_bytes
            elapsed = max(0.01, time.time() - start_time)
            combined_speed = sum(s.get("speed", 0.0) for s in self.active_worker_stats.values())
            if combined_speed <= 0:
                combined_speed = overall_done_bytes / elapsed

            remaining_bytes = max(0, total_bytes - overall_done_bytes)
            eta_sec = int(remaining_bytes / max(1.0, combined_speed))
            eta_str = str(datetime.timedelta(seconds=eta_sec))

            self.sig_overall_progress.emit(
                completed_ops_count, total_ops, overall_done_bytes, total_bytes, combined_speed, eta_str
            )
            self.sig_active_streams.emit(list(self.active_worker_stats.values()))

            spindle_telem = {}
            for v in (self.db_volumes or []):
                p_id, p_name, is_ssd = PhysicalDiskResolver.get_physical_disk_info(v["letter"], self.db_volumes)
                max_s = self.ssd_concurrency if is_ssd else (1 if self.strict_hdd_lock else self.ssd_concurrency)
                spindle_telem[p_id] = {
                    "name": p_name, "letter": v["letter"], "active": self.spindle_allocations.get(p_id, 0),
                    "max": max_s, "is_ssd": is_ssd
                }
            self.sig_spindle_telemetry.emit(spindle_telem)

        for w in list(self.active_workers.values()):
            w.cancel()
            w.wait(1000)

        WindowsPowerManager.allow_sleep()
        summary = {
            "total_ops": total_ops, "success_count": success_count, "failed_count": failed_count,
            "total_bytes": transferred_total_bytes, "cancelled": self._cancelled
        }
        self.sig_finished.emit(summary)


TransferWorkerThread = SpindleAwareTransferCoordinator
