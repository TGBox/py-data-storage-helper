import re
import os
import hashlib
import difflib
from typing import List, Dict, Optional, Any
from PySide6.QtCore import QThread, Signal

from ..core.database import DatabaseManager
from ..core.windows import WindowsPowerManager
from ..core.utils import to_long_path, format_bytes


class DuplicateFinderWorker(QThread):
    sig_progress = Signal(str, int, int)
    sig_duplicate_group = Signal(dict)
    sig_finished = Signal(list, int)
    sig_error = Signal(str)

    def __init__(self, db: DatabaseManager, mode: str = "EXACT", volume_id: Optional[str] = None,
                 min_size: int = 1024, category: Optional[str] = None, fuzzy_threshold: float = 0.85):
        super().__init__()
        self.db = db
        self.mode = mode
        self.volume_id = volume_id
        self.min_size = min_size
        self.category = category
        self.fuzzy_threshold = fuzzy_threshold
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def calculate_sample_hash(self, file_path: str) -> str:
        long_p = to_long_path(file_path)
        hasher = hashlib.sha256()
        try:
            file_size = os.path.getsize(long_p)
            with open(long_p, "rb") as f:
                if file_size <= 8192:
                    hasher.update(f.read())
                else:
                    hasher.update(f.read(4096))
                    f.seek(file_size - 4096)
                    hasher.update(f.read(4096))
            return hasher.hexdigest()
        except Exception:
            return ""

    def calculate_full_hash(self, file_path: str) -> str:
        long_p = to_long_path(file_path)
        hasher = hashlib.sha256()
        try:
            with open(long_p, "rb") as f:
                while chunk := f.read(65536):
                    if self._cancelled:
                        return ""
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return ""

    def run(self) -> None:
        WindowsPowerManager.prevent_sleep()
        found_groups: List[Dict[str, Any]] = []
        total_wasted_bytes = 0

        try:
            if self.mode == "EXACT":
                size_clusters = self.db.get_size_duplicate_candidates(self.volume_id, self.min_size, self.category)
                total_clusters = len(size_clusters)

                for idx, size in enumerate(size_clusters):
                    if self._cancelled:
                        break
                    self.sig_progress.emit(f"Sample-Prüfung ({format_bytes(size)})", idx + 1, total_clusters)
                    file_records = self.db.get_files_by_size(size, self.volume_id)

                    sample_buckets: Dict[str, List[Dict[str, Any]]] = {}
                    for rec in file_records:
                        if self._cancelled:
                            break
                        full_abs = os.path.join(rec["volume_letter"], rec["path"])
                        shash = self.calculate_sample_hash(full_abs)
                        if shash:
                            rec["abs_path"] = full_abs
                            sample_buckets.setdefault(shash, []).append(rec)

                    for s_hash, candidates in sample_buckets.items():
                        if len(candidates) < 2 or self._cancelled:
                            continue
                        full_buckets: Dict[str, List[Dict[str, Any]]] = {}
                        for cand in candidates:
                            f_hash = self.calculate_full_hash(cand["abs_path"])
                            if f_hash:
                                full_buckets.setdefault(f_hash, []).append(cand)

                        for final_hash, dup_files in full_buckets.items():
                            if len(dup_files) > 1:
                                wasted = size * (len(dup_files) - 1)
                                total_wasted_bytes += wasted
                                grp = {
                                    "type": "EXACT",
                                    "size": size,
                                    "hash": final_hash,
                                    "wasted_bytes": wasted,
                                    "files": dup_files
                                }
                                found_groups.append(grp)
                                self.sig_duplicate_group.emit(grp)
            else:
                self.sig_progress.emit("Lade Dateien für Fuzzy-Analyse...", 0, 100)
                files = self.db.get_all_files_for_fuzzy(self.volume_id, self.category, limit=2500)
                total_f = len(files)
                visited = set()

                for i in range(total_f):
                    if self._cancelled:
                        break
                    if i in visited:
                        continue

                    f_a = files[i]
                    name_a_clean = re.sub(r'[\W_]+', '', os.path.splitext(f_a["name"])[0].lower())
                    cluster = [f_a]

                    for j in range(i + 1, total_f):
                        if j in visited or self._cancelled:
                            continue
                        f_b = files[j]
                        if f_a["extension"] != f_b["extension"]:
                            continue

                        name_b_clean = re.sub(r'[\W_]+', '', os.path.splitext(f_b["name"])[0].lower())
                        ratio = difflib.SequenceMatcher(None, name_a_clean, name_b_clean).ratio()

                        if ratio >= self.fuzzy_threshold:
                            cluster.append(f_b)
                            visited.add(j)

                    if len(cluster) > 1:
                        visited.add(i)
                        wasted = sum(x["size"] for x in cluster[1:])
                        total_wasted_bytes += wasted
                        grp = {
                            "type": "FUZZY",
                            "size": f_a["size"],
                            "hash": f"FUZZY_{f_a['name']}",
                            "wasted_bytes": wasted,
                            "files": cluster
                        }
                        found_groups.append(grp)
                        self.sig_duplicate_group.emit(grp)

            self.sig_finished.emit(found_groups, total_wasted_bytes)
        except Exception as ex:
            self.sig_error.emit(str(ex))
        finally:
            WindowsPowerManager.allow_sleep()

