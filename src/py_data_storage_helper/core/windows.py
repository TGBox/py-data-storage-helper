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
    FOF_WANTNUKEWARNING,
    DRIVE_FIXED,
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


class STORAGE_PROPERTY_QUERY(ctypes.Structure):
    _fields_ = [
        ("PropertyId", ctypes.c_uint32),
        ("QueryType", ctypes.c_uint32),
        ("AdditionalParameters", ctypes.c_ubyte * 1),
    ]


class STORAGE_DEVICE_DESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("Version", ctypes.c_uint32),
        ("Size", ctypes.c_uint32),
        ("DeviceType", ctypes.c_ubyte),
        ("DeviceTypeModifier", ctypes.c_ubyte),
        ("RemovableMedia", ctypes.c_ubyte),
        ("CommandQueueing", ctypes.c_ubyte),
        ("VendorIdOffset", ctypes.c_uint32),
        ("ProductIdOffset", ctypes.c_uint32),
        ("ProductRevisionOffset", ctypes.c_uint32),
        ("SerialNumberOffset", ctypes.c_uint32),
        ("BusType", ctypes.c_uint32),
        ("RawPropertiesLength", ctypes.c_uint32),
    ]


class DEVICE_SEEK_PENALTY_DESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("Version", ctypes.c_uint32),
        ("Size", ctypes.c_uint32),
        ("IncursSeekPenalty", ctypes.c_ubyte),
    ]


BUS_TYPE_1394 = 4
BUS_TYPE_USB = 7
BUS_TYPE_SD = 12
BUS_TYPE_MMC = 13
BUS_TYPE_NVME = 17
EXTERNAL_BUS_TYPES = frozenset({BUS_TYPE_1394, BUS_TYPE_USB, BUS_TYPE_SD, BUS_TYPE_MMC})


def query_storage_device(drive_letter: str) -> Optional[Dict[str, Any]]:
    """Fragt Bus-Typ, Wechselmedium und Seek-Penalty (HDD ja / SSD nein) direkt beim Laufwerk ab.

    Liefert {"bus_type", "removable", "seek_penalty"}; einzelne Werte sind None, wenn das Gerät sie nicht meldet.
    None insgesamt, wenn das Laufwerk nicht abgefragt werden kann.
    """
    if platform.system() != "Windows":
        return None
    clean = drive_letter.strip("\\").upper()
    try:
        IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
        STORAGE_DEVICE_PROPERTY = 0
        STORAGE_DEVICE_SEEK_PENALTY_PROPERTY = 7
        FILE_SHARE_READ = 1
        FILE_SHARE_WRITE = 2
        OPEN_EXISTING = 3

        kernel32 = ctypes.windll.kernel32
        h_vol = kernel32.CreateFileW(f"\\\\.\\{clean}", 0, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
        if not h_vol or h_vol == -1:
            return None
        try:
            info: Dict[str, Any] = {"bus_type": None, "removable": None, "seek_penalty": None}
            bytes_ret = ctypes.c_uint32(0)

            query = STORAGE_PROPERTY_QUERY(STORAGE_DEVICE_PROPERTY, 0)
            buf = ctypes.create_string_buffer(1024)
            if kernel32.DeviceIoControl(
                h_vol, IOCTL_STORAGE_QUERY_PROPERTY, ctypes.byref(query), ctypes.sizeof(query),
                buf, len(buf), ctypes.byref(bytes_ret), None
            ):
                desc = STORAGE_DEVICE_DESCRIPTOR.from_buffer(buf)
                info["bus_type"] = int(desc.BusType)
                info["removable"] = bool(desc.RemovableMedia)

            query = STORAGE_PROPERTY_QUERY(STORAGE_DEVICE_SEEK_PENALTY_PROPERTY, 0)
            seek = DEVICE_SEEK_PENALTY_DESCRIPTOR()
            if kernel32.DeviceIoControl(
                h_vol, IOCTL_STORAGE_QUERY_PROPERTY, ctypes.byref(query), ctypes.sizeof(query),
                ctypes.byref(seek), ctypes.sizeof(seek), ctypes.byref(bytes_ret), None
            ):
                info["seek_penalty"] = bool(seek.IncursSeekPenalty)
            return info
        finally:
            kernel32.CloseHandle(h_vol)
    except Exception:
        return None


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



def drive_has_recycle_bin(path_str: str) -> bool:
    """Windows führt nur für Laufwerke vom Typ 'Fixed' einen Papierkorb, nicht für Wechselmedien und Netzlaufwerke."""
    if platform.system() != "Windows":
        return False
    try:
        drive = os.path.splitdrive(os.path.abspath(strip_long_path_prefix(path_str)))[0]
        if not drive:
            return False
        return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == DRIVE_FIXED
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
        # FOF_WANTNUKEWARNING: Windows fragt nach, falls eine Datei doch nicht in den Papierkorb passt.
        fileop.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI | FOF_WANTNUKEWARNING

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

