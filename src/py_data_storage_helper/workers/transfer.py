import datetime
import time
from typing import Dict, List, Optional, Any, Tuple
from PySide6.QtCore import QThread, Signal

from ..core.file_ops import run_operation, OpResult
from ..core.windows import WindowsPowerManager, PhysicalDiskResolver
from ..core.database import DatabaseManager
from ..core.plan import StoragePlan


class SingleFileTransferWorker(QThread):
    """Führt genau eine Plan-Operation aus (Einzeldatei, Ordner oder Dateiliste).

    Ergebnis und Fortschritt liegen in self.result / self.stats und werden vom Koordinator abgefragt.
    """
    sig_file_progress = Signal(str, str, 'qint64', 'qint64', float)
    sig_file_completed = Signal(str, str, str, 'qint64', str)

    def __init__(self, op: Dict[str, Any], conflict_strategy: str = "VERSION", verify_checksum: bool = True, preserve_timestamps: bool = True):
        super().__init__()
        self.op = op
        self.conflict_strategy = conflict_strategy
        self.verify_checksum = verify_checksum
        self.preserve_timestamps = preserve_timestamps
        self._cancelled = False
        self.result: Optional[OpResult] = None
        self.stats: Dict[str, Any] = {"name": "", "cur_bytes": 0, "total_bytes": op.get("size", 0), "speed": 0.0}

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        op_id = self.op.get("op_id", "op_0")
        start_t = time.time()

        def on_progress(name: str, done: int, total: int) -> None:
            elapsed = max(0.001, time.time() - start_t)
            self.stats = {"name": name, "cur_bytes": done, "total_bytes": total, "speed": done / elapsed}

        try:
            result = run_operation(
                self.op,
                conflict_strategy=self.conflict_strategy,
                verify=self.verify_checksum,
                preserve_timestamps=self.preserve_timestamps,
                progress_cb=on_progress,
                cancel_cb=lambda: self._cancelled,
            )
        except Exception as ex:
            result = OpResult("FAILED", str(ex))

        self.result = result
        self.sig_file_completed.emit(op_id, result.status, result.message, result.bytes_done, result.checksum)



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
        self.active_worker_disks: Dict[str, Tuple[str, str]] = {}
        self.spindle_allocations: Dict[str, int] = {}
        self.db_volumes = self.db.get_volumes()

    def cancel(self) -> None:
        self._cancelled = True
        for w in list(self.active_workers.values()):
            w.cancel()

    def toggle_pause(self) -> bool:
        self._paused = not self._paused
        return self._paused

    def _resolve_spindles(self, op: Dict[str, Any]) -> Tuple[Tuple[str, str, bool], Tuple[str, str, bool]]:
        src_info = PhysicalDiskResolver.get_physical_disk_info(op.get("source_volume") or "?", self.db_volumes)
        tgt_info = PhysicalDiskResolver.get_physical_disk_info(op.get("target_volume") or "?", self.db_volumes)
        return src_info, tgt_info

    def _max_streams(self, is_ssd: bool) -> int:
        return self.ssd_concurrency if is_ssd else (1 if self.strict_hdd_lock else self.ssd_concurrency)

    def _finalize_worker(self, op_id: str, worker: SingleFileTransferWorker) -> OpResult:
        """Wartet auf den Worker, gibt Spindeln frei, schreibt das Journal und meldet den Status."""
        worker.wait()
        result = worker.result or OpResult("FAILED", "Worker ohne Ergebnis beendet")

        for disk in set(self.active_worker_disks.pop(op_id, ())):
            self.spindle_allocations[disk] = max(0, self.spindle_allocations.get(disk, 1) - 1)

        if result.journal:
            try:
                self.db.log_operations_batch(result.journal)
                self.db.apply_transfers_to_index(result.journal)
            except Exception as ex:
                self.sig_log.emit(f"Journal konnte nicht geschrieben werden: {ex}")

        worker.op["status"] = result.status
        self.sig_item_completed.emit(op_id, result.status, result.message)
        return result

    def run(self) -> None:
        WindowsPowerManager.prevent_sleep()
        # Bereits erfolgreich ausgeführte Operationen nicht noch einmal anfassen.
        ops = [op for op in self.plan.operations if op.get("status") != "SUCCESS"]
        for op in ops:
            op["status"] = "PENDING"

        total_ops = len(ops)
        total_bytes = sum(o.get("size", 0) for o in ops)
        counters = {"completed": 0, "success": 0, "failed": 0, "bytes": 0}
        start_time = time.time()
        pending_ops = list(ops)

        def account(result: OpResult) -> None:
            counters["completed"] += 1
            counters["bytes"] += result.bytes_done
            if result.status == "SUCCESS":
                counters["success"] += 1
            elif result.status != "SKIPPED":
                counters["failed"] += 1

        try:
            while (pending_ops or self.active_workers) and not self._cancelled:
                while self._paused and not self._cancelled:
                    time.sleep(0.2)

                for op_id, worker in list(self.active_workers.items()):
                    if worker.isFinished():
                        del self.active_workers[op_id]
                        account(self._finalize_worker(op_id, worker))

                idx = 0
                while idx < len(pending_ops) and not self._cancelled:
                    op_candidate = pending_ops[idx]
                    src_info, tgt_info = self._resolve_spindles(op_candidate)
                    src_disk, _, src_ssd = src_info
                    tgt_disk, _, tgt_ssd = tgt_info

                    src_free = self.spindle_allocations.get(src_disk, 0) < self._max_streams(src_ssd)
                    tgt_free = self.spindle_allocations.get(tgt_disk, 0) < self._max_streams(tgt_ssd)

                    if src_free and tgt_free:
                        op_to_start = pending_ops.pop(idx)
                        op_id = op_to_start.get("op_id") or f"op_{id(op_to_start)}"
                        op_to_start["status"] = "IN_PROGRESS"

                        for disk in {src_disk, tgt_disk}:
                            self.spindle_allocations[disk] = self.spindle_allocations.get(disk, 0) + 1

                        worker = SingleFileTransferWorker(
                            op=op_to_start,
                            conflict_strategy=self.conflict_strategy,
                            verify_checksum=self.verify_checksum,
                            preserve_timestamps=self.preserve_timestamps
                        )
                        self.active_workers[op_id] = worker
                        self.active_worker_disks[op_id] = (src_disk, tgt_disk)
                        worker.start()
                    else:
                        idx += 1

                time.sleep(0.1)

                streams: List[Dict[str, Any]] = []
                for op_id, worker in list(self.active_workers.items()):
                    s = dict(worker.stats)
                    src_disk, tgt_disk = self.active_worker_disks.get(op_id, ("", ""))
                    s.update({
                        "op_id": op_id, "src_disk": src_disk, "tgt_disk": tgt_disk,
                        "pct": int((s["cur_bytes"] / max(1, s["total_bytes"])) * 100)
                    })
                    streams.append(s)

                overall_done_bytes = counters["bytes"] + sum(s["cur_bytes"] for s in streams)
                elapsed = max(0.01, time.time() - start_time)
                combined_speed = sum(s["speed"] for s in streams)
                if combined_speed <= 0:
                    combined_speed = overall_done_bytes / elapsed

                remaining_bytes = max(0, total_bytes - overall_done_bytes)
                eta_sec = int(remaining_bytes / max(1.0, combined_speed))
                eta_str = str(datetime.timedelta(seconds=eta_sec))

                self.sig_overall_progress.emit(
                    counters["completed"], total_ops, overall_done_bytes, total_bytes, combined_speed, eta_str
                )
                self.sig_active_streams.emit(streams)

                spindle_telem = {}
                for v in (self.db_volumes or []):
                    p_id, p_name, is_ssd = PhysicalDiskResolver.get_physical_disk_info(v["letter"], self.db_volumes)
                    spindle_telem[p_id] = {
                        "name": p_name, "letter": v["letter"], "active": self.spindle_allocations.get(p_id, 0),
                        "max": self._max_streams(is_ssd), "is_ssd": is_ssd
                    }
                self.sig_spindle_telemetry.emit(spindle_telem)

            # Abbruch oder Ende: laufende Worker sauber beenden, damit bereits verschobene Dateien im Journal landen.
            for worker in list(self.active_workers.values()):
                worker.cancel()
            for op_id, worker in list(self.active_workers.items()):
                del self.active_workers[op_id]
                account(self._finalize_worker(op_id, worker))
        finally:
            WindowsPowerManager.allow_sleep()

        summary = {
            "total_ops": total_ops, "success_count": counters["success"], "failed_count": counters["failed"],
            "total_bytes": counters["bytes"], "cancelled": self._cancelled
        }
        self.sig_finished.emit(summary)


TransferWorkerThread = SpindleAwareTransferCoordinator
