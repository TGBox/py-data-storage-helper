import ctypes
import platform
from typing import List, Dict, Optional, Any

from ..constants import (
    DRIVE_FIXED,
    DRIVE_REMOVABLE,
    DRIVE_CDROM,
    DRIVE_REMOTE,
)
from .utils import categorize_extension


class DriveDetector:
    """Discovers physical and logical Windows storage drives, capacity and filesystem details."""

    @staticmethod
    def categorize_extension(ext: str) -> str:
        ext = ext.lower().strip(".")
        categories = {
            "image": ["jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp", "raw", "cr2", "cr3", "nef", "arw", "dng"],
            "video": ["mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "ts"],
            "audio": ["mp3", "flac", "wav", "aac", "ogg", "m4a", "wma", "alac"],
            "document": ["pdf", "docx", "doc", "xlsx", "xls", "pptx", "txt", "md", "csv", "rtf", "odt"],
            "archive": ["zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso"],
            "code": ["py", "cpp", "c", "h", "cs", "java", "js", "ts", "html", "css", "json", "xml", "sql"]
        }
        for cat, exts in categories.items():
            if ext in exts:
                return cat
        return "other"

    @classmethod
    def get_mounted_drives(cls) -> List[Dict[str, Any]]:
        drives = []
        if platform.system() == "Windows":
            try:
                bitmask = ctypes.windll.kernel32.GetLogicalDrives()
                for i in range(26):
                    if bitmask & (1 << i):
                        letter = chr(65 + i) + ":\\"
                        vol_info = cls._get_windows_volume_details(letter)
                        if vol_info:
                            drives.append(vol_info)
            except Exception as e:
                print(f"Error querying Windows drives: {e}")
        else:
            drives.append({
                "id": "VOL_DEV_C",
                "label": "System NVMe (SSD)",
                "letter": "C:\\",
                "total_space": 1000 * 1024**3,
                "free_space": 320 * 1024**3,
                "file_system": "NTFS",
                "is_ssd": 1,
                "drive_type": "Fixed Disk",
                "smart_status": "OK"
            })
            drives.append({
                "id": "VOL_DEV_D",
                "label": "Data Archive (HDD)",
                "letter": "D:\\",
                "total_space": 4000 * 1024**3,
                "free_space": 1850 * 1024**3,
                "file_system": "NTFS",
                "is_ssd": 0,
                "drive_type": "Fixed Disk",
                "smart_status": "OK"
            })
            drives.append({
                "id": "VOL_DEV_E",
                "label": "External USB Archive",
                "letter": "E:\\",
                "total_space": 2000 * 1024**3,
                "free_space": 920 * 1024**3,
                "file_system": "exFAT",
                "is_ssd": 0,
                "drive_type": "Removable",
                "smart_status": "OK"
            })
        return drives

    @classmethod
    def _get_windows_volume_details(cls, drive_path: str) -> Optional[Dict[str, Any]]:
        try:
            drive_type_val = ctypes.windll.kernel32.GetDriveTypeW(drive_path)
            type_map = {
                DRIVE_REMOVABLE: "Removable (USB)",
                DRIVE_FIXED: "Fixed Disk",
                DRIVE_REMOTE: "Network Drive",
                DRIVE_CDROM: "CD/DVD"
            }
            type_label = type_map.get(drive_type_val, "Unknown")
            
            if drive_type_val == DRIVE_CDROM:
                return None

            volume_name_buf = ctypes.create_unicode_buffer(261)
            fs_name_buf = ctypes.create_unicode_buffer(261)
            serial_num = ctypes.c_ulong(0)
            max_comp_len = ctypes.c_ulong(0)
            flags = ctypes.c_ulong(0)

            res = ctypes.windll.kernel32.GetVolumeInformationW(
                drive_path,
                volume_name_buf, 260,
                ctypes.byref(serial_num),
                ctypes.byref(max_comp_len),
                ctypes.byref(flags),
                fs_name_buf, 260
            )

            vol_label = volume_name_buf.value or "Lokaler Datenträger"
            fs_name = fs_name_buf.value or "NTFS"
            vol_id = f"VOL_{serial_num.value:08X}" if res else f"VOL_{drive_path[0]}"

            free_bytes = ctypes.c_ulonglong(0)
            total_bytes = ctypes.c_ulonglong(0)
            total_free = ctypes.c_ulonglong(0)

            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                drive_path,
                ctypes.byref(free_bytes),
                ctypes.byref(total_bytes),
                ctypes.byref(total_free)
            )

            is_ssd = 1 if (drive_type_val == DRIVE_FIXED and ("C:" in drive_path.upper() or "SSD" in vol_label.upper() or "NVME" in vol_label.upper())) else 0

            return {
                "id": vol_id,
                "label": vol_label,
                "letter": drive_path,
                "total_space": int(total_bytes.value),
                "free_space": int(free_bytes.value),
                "file_system": fs_name,
                "is_ssd": is_ssd,
                "drive_type": type_label,
                "smart_status": "OK"
            }
        except Exception:
            return None

