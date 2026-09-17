"""Application-wide constants and Windows API definitions."""

APP_NAME = "Storage & Drive Manager"
APP_VERSION = "1.5.1"
DB_FILENAME = "storage_manager.db"
PLAN_FILE_EXTENSION = ".stplan"

# Execution state flags for Windows power management
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_AWAYMODE_REQUIRED = 0x00000040

# Windows drive types
DRIVE_FIXED = 3
DRIVE_REMOVABLE = 2
DRIVE_CDROM = 5
DRIVE_REMOTE = 4

# Windows shell file operations
FO_DELETE = 0x0003
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004
FOF_NOERRORUI = 0x0400

# Device change window messages
WM_DEVICECHANGE = 0x0219
DBT_DEVICEARRIVAL = 0x8000
DBT_DEVICEREMOVECOMPLETE = 0x8004
DBT_DEVTYP_VOLUME = 0x00000002
