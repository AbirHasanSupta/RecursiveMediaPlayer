import os
import re
import shutil
from dataclasses import dataclass
from typing import Optional, Callable, List, Dict, Tuple
import requests
from bs4 import BeautifulSoup

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
    Helper for Google Drive links.
    Previous behavior downloaded to a local cache; now we also support streaming
    (no local storage) by producing HTTP URLs and synthetic directory structures.
    """
    VIDEO_SUFFIXES = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv')

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

    @staticmethod
    def build_stream_url(file_id: str) -> str:
        # Use the usercontent host which serves the file bytes directly and
        # avoids the Google Drive interstitial confirmation page for large files.
        # VLC can open this URL directly for streaming.
        return f"https://drive.usercontent.google.com/uc?id={file_id}&export=download"

    @staticmethod
    def make_source_from_url(url: str) -> Optional[dict]:
        parsed = GoogleDriveManager._extract_id_and_type(url)
        if not parsed:
            return None
        drive_id, typ = parsed
        if typ == "file":
            return {"provider": "gdrive", "kind": "file", "id": drive_id, "url": url}
        else:
            return {"provider": "gdrive", "kind": "folder", "id": drive_id, "url": url}

    def _list_public_folder_files(self, folder_id: str) -> list[dict]:
        """
        Scrape the public embedded folder view to list files.
        Returns list of dicts: {id, name, href}
        """
        url = f"https://drive.google.com/embeddedfolderview?id={folder_id}#list"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        results: list[dict] = []
        # Strategy: find anchor tags linking to /file/d/<ID>/view
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = re.search(r"/file/d/([a-zA-Z0-9_-]+)/view", href)
            if not m:
                continue
            fid = m.group(1)
            # Try to get a readable name
            name = a.get("title") or a.get_text(strip=True) or fid
            results.append({"id": fid, "name": name, "href": href})
        return results

    def gather_videos_with_directories_for_source(self, source: dict):
        """
        For a gdrive 'file' source: return a pseudo directory with one video that streams via HTTP.
        For a 'folder' source: currently unsupported without API; raise NotImplementedError.
        Returns tuple (videos, video_to_dir, directories).
        """
        kind = source.get("kind")
        if kind == "file":
            file_id = source.get("id")
            # Use id as filename placeholder; VLC will display stream title
            pseudo_dir = f"gdrive://file/{file_id}"
            video_url = self.build_stream_url(file_id)
            videos = [video_url]
            video_to_dir = {video_url: pseudo_dir}
            directories = [pseudo_dir]
            return videos, video_to_dir, directories
        elif kind == "folder":
            folder_id = source.get("id")
            pseudo_dir = f"gdrive://folder/{folder_id}"
            # Scrape folder for file ids and names
            items = self._list_public_folder_files(folder_id)
            videos: List[str] = []
            video_to_dir: Dict[str, str] = {}
            for it in items:
                name = (it.get("name") or "").lower()
                if not name.endswith(self.VIDEO_SUFFIXES):
                    # Unknown extension: still allow if no dot? Keep conservative: skip
                    continue
                file_id = it["id"]
                video_url = self.build_stream_url(file_id)
                videos.append(video_url)
                video_to_dir[video_url] = pseudo_dir
            directories = [pseudo_dir]
            return videos, video_to_dir, directories
        else:
            raise ValueError("Invalid Google Drive source descriptor.")

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
