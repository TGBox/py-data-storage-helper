import os
import sys
import subprocess
from typing import Dict, Any
from PySide6.QtCore import QThread, Signal

from ..core.windows import WindowsPowerManager


class DefragWorker(QThread):
    sig_log_line = Signal(str)
    sig_progress = Signal(int, str)
    sig_finished = Signal(bool, str)

    def __init__(self, drive_letter: str, analyze_only: bool = False):
        super().__init__()
        self.drive_letter = drive_letter.strip("\\")
        self.analyze_only = analyze_only
        self.process: Optional[subprocess.Popen] = None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass

    def run(self) -> None:
        WindowsPowerManager.prevent_sleep()
        flags = "/A" if self.analyze_only else "/U /V"
        cmd = f"defrag.exe {self.drive_letter} {flags}"
        self.sig_log_line.emit(f"Führe Windows Defrag aus: {cmd}\n")

        if platform.system() != "Windows":
            for p in range(1, 101, 10):
                if self._cancelled:
                    break
                time.sleep(0.3)
                self.sig_progress.emit(p, f"Simulierte Optimierung ({p}%)...")
                self.sig_log_line.emit(f"Phase 1: Cluster-Reorganisation {p}% abgeschlossen.")
            self.sig_finished.emit(True, "Simulation erfolgreich beendet.")
            WindowsPowerManager.allow_sleep()
            return

        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, shell=True, startupinfo=startupinfo
            )
            pct_regex = re.compile(r'(\d{1,3})\s*%')
            while True:
                if self._cancelled:
                    self.process.terminate()
                    break
                line = self.process.stdout.readline()
                if not line and self.process.poll() is not None:
                    break
                if line:
                    clean_line = line.strip()
                    self.sig_log_line.emit(clean_line)
                    match = pct_regex.search(clean_line)
                    if match:
                        pct_val = int(match.group(1))
                        self.sig_progress.emit(pct_val, clean_line)

            rc = self.process.poll()
            self.sig_finished.emit(rc == 0, "Defragmentierung abgeschlossen." if rc == 0 else f"Code {rc}")
        except Exception as ex:
            self.sig_finished.emit(False, str(ex))
        finally:
            WindowsPowerManager.allow_sleep()

