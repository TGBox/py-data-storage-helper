import os
import time
from typing import List, Tuple
from PySide6.QtCore import QThread, Signal

from ..core.utils import to_long_path, strip_long_path_prefix, is_junction_or_symlink
from ..core.windows import WindowsPowerManager
from ..core.drive_detector import DriveDetector


class IndexerWorker(QThread):
    sig_progress = Signal(int, 'qint64', str)
    sig_batch_ready = Signal(list)
    sig_finished = Signal(dict)
    sig_error = Signal(str)

    def __init__(self, volume_id: str, root_path: str):
        super().__init__()
        self.volume_id = volume_id
        self.root_path = root_path
        self._is_cancelled = False
        self.batch_size = 2000

    def cancel(self) -> None:
        self._is_cancelled = True

    def run(self) -> None:
        WindowsPowerManager.prevent_sleep()
        start_time = time.time()
        file_count = 0
        total_size = 0
        batch: List[Tuple] = []
        stack = [self.root_path]

        try:
            while stack and not self._is_cancelled:
                current_dir = stack.pop()
                if is_junction_or_symlink(current_dir) and current_dir != self.root_path:
                    continue

                long_dir_path = to_long_path(current_dir)
                try:
                    with os.scandir(long_dir_path) as it:
                        for entry in it:
                            if self._is_cancelled:
                                break
                            entry_name = entry.name
                            full_path = os.path.join(current_dir, entry_name)
                            try:
                                if entry.is_dir(follow_symlinks=False):
                                    if not is_junction_or_symlink(full_path):
                                        stack.append(full_path)
                                elif entry.is_file(follow_symlinks=False):
                                    stat_info = entry.stat(follow_symlinks=False)
                                    file_size = stat_info.st_size
                                    mtime = stat_info.st_mtime
                                    ctime = stat_info.st_ctime
                                    ext = os.path.splitext(entry_name)[1].lower()
                                    cat = DriveDetector.categorize_extension(ext)
                                    rel_path = os.path.relpath(full_path, self.root_path)

                                    batch.append((
                                        self.volume_id, rel_path, entry_name, ext,
                                        file_size, mtime, ctime, 0, cat
                                    ))
                                    file_count += 1
                                    total_size += file_size

                                    if len(batch) >= self.batch_size:
                                        self.sig_batch_ready.emit(list(batch))
                                        batch.clear()
                                        self.sig_progress.emit(file_count, total_size, strip_long_path_prefix(full_path))
                            except (PermissionError, FileNotFoundError, OSError):
                                continue
                except (PermissionError, FileNotFoundError, OSError):
                    continue

                if file_count % 500 == 0:
                    self.sig_progress.emit(file_count, total_size, strip_long_path_prefix(current_dir))

            if batch and not self._is_cancelled:
                self.sig_batch_ready.emit(list(batch))
                batch.clear()

            elapsed = max(0.01, time.time() - start_time)
            summary = {
                "file_count": file_count,
                "total_size": total_size,
                "elapsed_seconds": elapsed,
                "cancelled": self._is_cancelled
            }
            self.sig_finished.emit(summary)
        except Exception as ex:
            self.sig_error.emit(str(ex))
        finally:
            WindowsPowerManager.allow_sleep()

