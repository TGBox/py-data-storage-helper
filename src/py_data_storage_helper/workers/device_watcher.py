import time
from typing import Dict, Any
from PySide6.QtCore import QThread, Signal

from ..core.drive_detector import DriveDetector


class DeviceWatcher(QThread):
    sig_drive_arrived = Signal(dict)
    sig_drive_removed = Signal(str)

    def __init__(self, poll_interval_ms: int = 1500):
        super().__init__()
        self.poll_interval = poll_interval_ms / 1000.0
        self._running = True
        self._known_letters = set()
        self._init_known_letters()

    def _init_known_letters(self) -> None:
        drives = DriveDetector.get_mounted_drives()
        self._known_letters = {d["letter"].upper().rstrip("\\") for d in drives}

    def stop(self) -> None:
        self._running = False

    def trigger_simulated_arrival(self, drive_dict: Dict[str, Any]) -> None:
        clean_let = drive_dict["letter"].upper().rstrip("\\")
        self._known_letters.add(clean_let)
        self.sig_drive_arrived.emit(drive_dict)

    def trigger_simulated_removal(self, letter: str) -> None:
        clean_let = letter.upper().rstrip("\\")
        if clean_let in self._known_letters:
            self._known_letters.remove(clean_let)
        self.sig_drive_removed.emit(clean_let)

    def run(self) -> None:
        while self._running:
            try:
                current_drives = DriveDetector.get_mounted_drives()
                current_letters = {d["letter"].upper().rstrip("\\"): d for d in current_drives}

                for letter, drv in current_letters.items():
                    if letter not in self._known_letters:
                        self._known_letters.add(letter)
                        self.sig_drive_arrived.emit(drv)

                removed = self._known_letters - set(current_letters.keys())
                for r in removed:
                    self._known_letters.remove(r)
                    self.sig_drive_removed.emit(r)
            except Exception:
                pass
            waited = 0.0
            while self._running and waited < self.poll_interval:
                time.sleep(0.1)  # kurze Schritte, damit stop() sofort greift
                waited += 0.1

