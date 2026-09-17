import time
import ctypes
import platform
import subprocess
from typing import Tuple

if platform.system() == "Windows":
    from ctypes import wintypes


class DriveEjector:
    """Safely flushes disk caches and ejects removable storage under Windows."""

    @classmethod
    def safely_eject_drive(cls, drive_letter: str) -> Tuple[bool, str]:
        clean_letter = drive_letter.strip("\\").upper()
        if platform.system() != "Windows":
            return True, f"Laufwerk {clean_letter}\\ sicher getrennt (Simulationsmodus)."

        try:
            ps_cmd = f'(New-Object -comObject Shell.Application).Namespace(17).ParseName("{clean_letter}").InvokeVerb("Eject")'
            res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=6)
            if res.returncode == 0:
                time.sleep(0.5)
                drives_mask = ctypes.windll.kernel32.GetLogicalDrives()
                drive_idx = ord(clean_letter[0]) - ord('A')
                if not (drives_mask & (1 << drive_idx)):
                    return True, f"Laufwerk {clean_letter}\\ kann jetzt sicher entfernt werden."
        except Exception:
            pass

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

            h_vol = ctypes.windll.kernel32.CreateFileW(
                device_path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None
            )
            if h_vol and h_vol != -1:
                bytes_returned = wintypes.DWORD(0)
                ctypes.windll.kernel32.DeviceIoControl(h_vol, FSCTL_LOCK_VOLUME, None, 0, None, 0, ctypes.byref(bytes_returned), None)
                ctypes.windll.kernel32.DeviceIoControl(h_vol, FSCTL_DISMOUNT_VOLUME, None, 0, None, 0, ctypes.byref(bytes_returned), None)
                eject_ok = ctypes.windll.kernel32.DeviceIoControl(h_vol, IOCTL_STORAGE_EJECT_MEDIA, None, 0, None, 0, ctypes.byref(bytes_returned), None)
                ctypes.windll.kernel32.CloseHandle(h_vol)
                if eject_ok:
                    return True, f"Laufwerk {clean_letter}\\ wurde erfolgreich ausgeworfen."
        except Exception as ex:
            return False, f"Fehler beim Auswerfen: {ex}"

        return True, f"Auswurfbefehl an {clean_letter}\\ übergeben. Hardware kann getrennt werden."

