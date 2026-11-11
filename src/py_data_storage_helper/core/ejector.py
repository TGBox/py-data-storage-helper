import time
import ctypes
import platform
import subprocess
from typing import Tuple

if platform.system() == "Windows":
    from ctypes import wintypes


class DriveEjector:
    """Safely flushes disk caches and ejects removable storage under Windows."""

    @staticmethod
    def _letter_present(clean_letter: str) -> bool:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return bool(mask & (1 << (ord(clean_letter[0]) - ord('A'))))

    @classmethod
    def safely_eject_drive(cls, drive_letter: str) -> Tuple[bool, str]:
        """Meldet nur dann Erfolg, wenn das Laufwerk nachweislich ausgeworfen wurde."""
        clean_letter = drive_letter.strip("\\").upper()
        if platform.system() != "Windows":
            return True, f"Laufwerk {clean_letter}\\ sicher getrennt (Simulationsmodus)."
        if not clean_letter or not clean_letter[0].isalpha():
            return False, "Ungültiger Laufwerksbuchstabe."

        # 1) Wie im Explorer: Shell-Verb "Auswerfen". Erfolg nur, wenn der Buchstabe danach verschwunden ist.
        try:
            ps_cmd = f'(New-Object -comObject Shell.Application).Namespace(17).ParseName("{clean_letter}").InvokeVerb("Eject")'
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW
            )
            if res.returncode == 0:
                for _ in range(10):
                    time.sleep(0.5)
                    if not cls._letter_present(clean_letter):
                        return True, f"Laufwerk {clean_letter}\\ kann jetzt sicher entfernt werden."
        except Exception:
            pass

        # 2) Direkt: Volume sperren, aushängen, auswerfen. Ohne Sperre wird nichts ausgehängt.
        try:
            device_path = f"\\\\.\\{clean_letter}"
            GENERIC_READ = 0x80000000
            GENERIC_WRITE = 0x40000000
            FILE_SHARE_READ = 1
            FILE_SHARE_WRITE = 2
            OPEN_EXISTING = 3
            FSCTL_LOCK_VOLUME = 0x00090018
            FSCTL_DISMOUNT_VOLUME = 0x00090020
            IOCTL_STORAGE_EJECT_MEDIA = 0x002D4808

            kernel32 = ctypes.windll.kernel32
            h_vol = kernel32.CreateFileW(
                device_path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None
            )
            if not h_vol or h_vol == -1:
                return False, f"Laufwerk {clean_letter}\\ konnte nicht geöffnet werden und wurde nicht ausgeworfen."

            eject_ok = False
            try:
                bytes_returned = wintypes.DWORD(0)
                locked = kernel32.DeviceIoControl(h_vol, FSCTL_LOCK_VOLUME, None, 0, None, 0, ctypes.byref(bytes_returned), None)
                if not locked:
                    return False, (f"Laufwerk {clean_letter}\\ wird noch von einem Programm verwendet "
                                   "und wurde nicht ausgeworfen.")
                dismounted = kernel32.DeviceIoControl(h_vol, FSCTL_DISMOUNT_VOLUME, None, 0, None, 0, ctypes.byref(bytes_returned), None)
                if dismounted:
                    eject_ok = bool(kernel32.DeviceIoControl(h_vol, IOCTL_STORAGE_EJECT_MEDIA, None, 0, None, 0, ctypes.byref(bytes_returned), None))
            finally:
                kernel32.CloseHandle(h_vol)

            if eject_ok:
                return True, f"Laufwerk {clean_letter}\\ wurde ausgeworfen und kann entfernt werden."
        except Exception as ex:
            return False, f"Fehler beim Auswerfen: {ex}"

        return False, (f"Laufwerk {clean_letter}\\ konnte nicht ausgeworfen werden. "
                       "Bitte über 'Hardware sicher entfernen' in Windows trennen.")
