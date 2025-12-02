import os
import re
import shutil
from dataclasses import dataclass
from typing import Optional, Callable

try:
    import gdown
except Exception:  # pragma: no cover
    gdown = None


DriveProgressCallback = Callable[[str], None]


def _default_progress(msg: str):
    print(msg)


@dataclass
class GoogleDriveResult:
    local_path: str
    is_folder: bool
    drive_id: str


class GoogleDriveManager:
    """
    Minimal Google Drive helper that downloads public file/folder share links
    into a local cache directory and returns the local path. Designed so the
    app can treat the result just like an added directory.
    """

    def __init__(self, cache_root: Optional[str] = None):
        # Use local app data on Windows, else home directory
        if cache_root is None:
            base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
            cache_root = os.path.join(base, "RecursiveMediaPlayer", "drive_cache")
        self.cache_root = cache_root
        os.makedirs(self.cache_root, exist_ok=True)

    @staticmethod
    def _extract_id_and_type(url: str) -> Optional[tuple[str, str]]:
        """Return (id, type) where type in {"file","folder"} if matches."""
        # Common folder link: https://drive.google.com/drive/folders/<FOLDER_ID>
        m = re.search(r"drive\.google\.com/drive/folders/([a-zA-Z0-9_-]+)", url)
        if m:
            return m.group(1), "folder"
        # File link: https://drive.google.com/file/d/<FILE_ID>/view
        m = re.search(r"drive\.google\.com/file/d/([a-zA-Z0-9_-]+)", url)
        if m:
            return m.group(1), "file"
        # Another pattern: open?id=<ID>
        m = re.search(r"open\?id=([a-zA-Z0-9_-]+)", url)
        if m:
            # Unknown; assume file
            return m.group(1), "file"
        # Or uc?id=<ID>&export=download
        m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
        if m:
            return m.group(1), "file"
        return None

    def _target_path(self, drive_id: str, is_folder: bool) -> str:
        sub = "folders" if is_folder else "files"
        return os.path.join(self.cache_root, sub, drive_id)

    def clear_cache_for(self, drive_id: str, is_folder: bool):
        path = self._target_path(drive_id, is_folder)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

    def ensure_downloaded(self, url: str, progress_cb: DriveProgressCallback | None = None) -> GoogleDriveResult:
        if gdown is None:
            raise RuntimeError("gdown is not installed. Please install 'gdown' from requirements and try again.")
        if progress_cb is None:
            progress_cb = _default_progress

        parsed = self._extract_id_and_type(url)
        if not parsed:
            raise ValueError("Unrecognized Google Drive link.")
        drive_id, typ = parsed
        is_folder = typ == "folder"

        target = self._target_path(drive_id, is_folder)
        os.makedirs(target, exist_ok=True)

        # If already contains content, assume cached and return
        if any(os.scandir(target)):
            progress_cb("Using cached Google Drive content.")
            return GoogleDriveResult(local_path=target, is_folder=is_folder, drive_id=drive_id)

        # Download
        if is_folder:
            progress_cb("Downloading Google Drive folder… this may take a while…")
            # gdown.download_folder expects the folder url or id; pass URL to preserve simplicity
            gdown.download_folder(url=url, output=target, quiet=False, use_cookies=False)
        else:
            progress_cb("Downloading Google Drive file…")
            # For single file, output into target path; gdown will create file under target's parent
            # We download into parent then move into target
            parent = os.path.dirname(target)
            os.makedirs(parent, exist_ok=True)
            out = gdown.download(id=drive_id, output=parent, quiet=False, use_cookies=False)
            if out is None:
                raise RuntimeError("Failed to download file from Google Drive.")
            # Move the file into target directory
            os.makedirs(target, exist_ok=True)
            dest = os.path.join(target, os.path.basename(out))
            try:
                shutil.move(out, dest)
            except Exception:
                # If out already inside target, ignore
                pass

        progress_cb("Google Drive download complete.")
        return GoogleDriveResult(local_path=target, is_folder=is_folder, drive_id=drive_id)
