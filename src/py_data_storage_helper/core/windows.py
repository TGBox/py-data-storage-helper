import os
import ctypes
import platform
from typing import Dict, List, Optional, Tuple, Any

if platform.system() == "Windows":
    from ctypes import wintypes

from ..constants import (
    ES_CONTINUOUS,
    ES_SYSTEM_REQUIRED,
    ES_AWAYMODE_REQUIRED,
    FO_DELETE,
    FOF_ALLOWUNDO,
    FOF_NOCONFIRMATION,
    FOF_SILENT,
    FOF_NOERRORUI,
)
from .utils import to_long_path, strip_long_path_prefix

if platform.system() == "Windows":
    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.WORD),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", wintypes.LPVOID),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    class STORAGE_DEVICE_NUMBER(ctypes.Structure):
        _fields_ = [
            ("DeviceType", wintypes.DWORD),
            ("DeviceNumber", wintypes.DWORD),
            ("PartitionNumber", wintypes.DWORD),
        ]


class PhysicalDiskResolver:
    """Maps logical Windows volume letters to physical spindle drive numbers (e.g., PhysicalDrive0)."""
    _cache: Dict[str, Tuple[str, str, bool]] = {}

    @classmethod
    def get_physical_disk_info(cls, drive_letter: str, db_volumes: Optional[List[Dict[str, Any]]] = None) -> Tuple[str, str, bool]:
        clean = drive_letter.strip("\\").upper()
        if not clean.endswith(":"):
            if len(clean) == 1 and clean.isalpha():
                clean += ":"
            elif ":" in clean:
                clean = clean[:clean.index(":") + 1]

        if clean in cls._cache:
            return cls._cache[clean]

        is_ssd = False
        if db_volumes:
            for v in db_volumes:
                v_let = v.get("letter", "").strip("\\").upper()
                if v_let.startswith(clean):
                    is_ssd = bool(v.get("is_ssd", 0))
                    break

        if platform.system() != "Windows":
            res = (f"Spindle_{clean[0]}", f"Laufwerk {clean}", is_ssd)
            cls._cache[clean] = res
            return res

        try:
            IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x002D1080
            FILE_SHARE_READ = 1
            FILE_SHARE_WRITE = 2
            OPEN_EXISTING = 3

            device_path = f"\\\\.\\{clean}"
            h_vol = ctypes.windll.kernel32.CreateFileW(
                device_path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None
            )
            if h_vol and h_vol != -1:
                sdn = STORAGE_DEVICE_NUMBER()
                bytes_ret = wintypes.DWORD(0)
                ok = ctypes.windll.kernel32.DeviceIoControl(
                    h_vol, IOCTL_STORAGE_GET_DEVICE_NUMBER, None, 0,
                    ctypes.byref(sdn), ctypes.sizeof(sdn),
                    ctypes.byref(bytes_ret), None
                )
                ctypes.windll.kernel32.CloseHandle(h_vol)
                if ok:
                    dev_num = sdn.DeviceNumber
                    type_str = "SSD" if is_ssd else "HDD (Spindel)"
                    res = (f"PhysicalDrive{dev_num}", f"Physische Disk #{dev_num} [{type_str}]", is_ssd)
                    cls._cache[clean] = res
                    return res
        except Exception:
            pass

        type_str = "SSD" if is_ssd else "HDD"
        res = (f"Spindle_{clean[0]}", f"Laufwerk {clean} [{type_str}]", is_ssd)
        cls._cache[clean] = res
        return res



def is_running_as_admin() -> bool:
    if platform.system() != "Windows":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False



def send_to_recycle_bin(path_str: str) -> Tuple[bool, str]:
    long_path = to_long_path(path_str)
    if platform.system() != "Windows":
        try:
            os.remove(path_str)
            return True, "Datei gelöscht (Nicht-Windows Testmodus)"
        except Exception as ex:
            return False, str(ex)

    try:
        clean_abs_path = os.path.abspath(strip_long_path_prefix(long_path))
        p_from = clean_abs_path + "\0\0"
        fileop = SHFILEOPSTRUCTW()
        fileop.hwnd = None
        fileop.wFunc = FO_DELETE
        fileop.pFrom = p_from
        fileop.pTo = None
        fileop.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI

        ret = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(fileop))
        if ret == 0 and not fileop.fAnyOperationsAborted:
            return True, "In den Windows-Papierkorb verschoben"
        return False, f"Windows Shell Fehler (Code {ret})"
    except Exception as ex:
        return False, str(ex)



class WindowsPowerManager:
    _is_preventing_sleep = False

    @classmethod
    def prevent_sleep(cls) -> bool:
        if platform.system() != "Windows":
            return False
        try:
            state = ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
            )
            cls._is_preventing_sleep = (state != 0)
            return cls._is_preventing_sleep
        except Exception:
            return False

    @classmethod
    def allow_sleep(cls) -> None:
        if platform.system() != "Windows":
            return
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            cls._is_preventing_sleep = False
        except Exception:
            pass

    @classmethod
    def is_active(cls) -> bool:
        return cls._is_preventing_sleep

