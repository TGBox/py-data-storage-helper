"""Storage & Drive Manager package."""

from .constants import APP_VERSION, APP_NAME
from .main import main

__version__ = APP_VERSION
__all__ = ["main", "APP_NAME", "__version__"]
