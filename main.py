import sys
import os
import json
import multiprocessing
from pathlib import Path

# Add source directories to sys.path to preserve all imports
root_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(root_dir, "src"))
sys.path.insert(0, os.path.join(root_dir, "src", "core"))
sys.path.insert(0, os.path.join(root_dir, "src", "utils"))


def _load_media_mode():
    app_name = "Recursive Video Player"
    if os.name == "nt":
        settings_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / app_name
    elif sys.platform == "darwin":
        settings_dir = Path.home() / "Library" / "Application Support" / app_name
    else:
        settings_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / app_name
    settings_file = settings_dir / "app_settings.json"
    try:
        if settings_file.exists():
            with open(settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return (data.get("media_mode") or "video").lower()
    except Exception:
        pass
    return "video"


if __name__ == "__main__":
    multiprocessing.freeze_support()

    from app import select_multiple_folders_and_play, check_vlc, show_vlc_missing_and_exit

    media_mode = _load_media_mode()
    if media_mode in ("video", "both") and not check_vlc():
        show_vlc_missing_and_exit()
    select_multiple_folders_and_play()
