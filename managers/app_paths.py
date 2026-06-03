import os
import sys
from pathlib import Path


APP_NAME = "Recursive Media Player"


def get_app_dirs():
    """Return the app's settings and local-cache directories."""
    if os.name == "nt":
        settings = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    elif sys.platform == "darwin":
        settings = Path.home() / "Library" / "Application Support" / APP_NAME
        local = Path.home() / "Library" / "Caches" / APP_NAME
    else:
        settings = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
        local = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / APP_NAME
    return settings, local
