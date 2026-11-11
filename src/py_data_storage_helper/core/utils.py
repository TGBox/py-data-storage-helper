import os
import platform
import ctypes
from typing import Tuple

def to_long_path(path_str: str) -> str:
    if platform.system() != "Windows":
        return os.path.abspath(path_str)
    clean_path = os.path.abspath(path_str)
    if clean_path.startswith("\\\\?\\"):
        return clean_path
    if clean_path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + clean_path[2:]
    return "\\\\?\\" + clean_path


def strip_long_path_prefix(path_str: str) -> str:
    if path_str.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path_str[8:]
    if path_str.startswith("\\\\?\\"):
        return path_str[4:]
    return path_str


def is_junction_or_symlink(path_str: str) -> bool:
    try:
        if os.path.islink(path_str):
            return True
        if platform.system() == "Windows":
            FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
            long_path = to_long_path(path_str)
            attrs = ctypes.windll.kernel32.GetFileAttributesW(long_path)
            if attrs != -1 and (attrs & FILE_ATTRIBUTE_REPARSE_POINT):
                return True
    except Exception:
        pass
    return False


# Ordner, in denen nie Duplikate zum Löschen vorgeschlagen werden (oberste Ebene eines Laufwerks).
PROTECTED_TOP_LEVEL_DIRS = frozenset({
    "windows", "program files", "program files (x86)", "programdata",
    "$recycle.bin", "system volume information", "recovery",
    "$winreagent", "$windows.~bt", "$windows.~ws", "msocache",
})


def is_protected_system_path(rel_path: str) -> bool:
    """True, wenn der laufwerksrelative Pfad in einem System- oder Programmordner liegt."""
    parts = [p.lower() for p in rel_path.replace("/", "\\").split("\\") if p]
    if not parts:
        return False
    if parts[0] in PROTECTED_TOP_LEVEL_DIRS:
        return True
    # Users\<Name>\AppData
    return len(parts) >= 3 and parts[0] == "users" and parts[2] == "appdata"


def format_bytes(size: float) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if abs(size) < 1024.0:
            return f"{size:3.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} EB"


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
