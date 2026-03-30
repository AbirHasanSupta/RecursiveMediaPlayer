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
            cache_root = os.path.join(base, "Recursive Media Player", "drive_cache")
        self.cache_root = cache_root
        os.makedirs(self.cache_root, exist_ok=True)
        # In-memory cache for last scraped folder tree and names
        # keyed by root_id (the id after gdrive://folder/)
        self._folder_trees: Dict[str, dict] = {}

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

    def _list_public_folder_children(self, folder_id: str) -> Tuple[list[dict], list[dict]]:
        """
        Returns (files, subfolders) for a public folder id by scraping the embedded view.
        - files: list of {id, name}
        - subfolders: list of {id, name}
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

        files: list[dict] = []
        subfolders: list[dict] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text_name = a.get("title") or a.get_text(strip=True)
            # File pattern
            m_file = re.search(r"/file/d/([a-zA-Z0-9_-]+)/view", href)
            if m_file:
                fid = m_file.group(1)
                files.append({"id": fid, "name": text_name or fid})
                continue
            # Folder pattern (various)
            m_folder = re.search(r"/drive/folders/([a-zA-Z0-9_-]+)", href)
            if m_folder:
                sid = m_folder.group(1)
                # skip self links
                if sid != folder_id:
                    subfolders.append({"id": sid, "name": text_name or sid})
                continue
        return files, subfolders

    def _build_recursive_tree_for_folder(self, root_id: str, max_depth: int = 10) -> dict:
        """
        Scrape a whole public folder tree recursively and build a synthetic directory structure.
        Returns a dict with keys:
          - dirs: set of pseudo directory keys (including the root)
          - dir_names: mapping from pseudo directory key to friendly name
          - file_parent: mapping from stream URL to its parent pseudo directory key
          - file_names: mapping from stream URL to friendly file name
        """
        pseudo_root = f"gdrive://folder/{root_id}"
        dirs: set[str] = {pseudo_root}
        dir_names: Dict[str, str] = {pseudo_root: f"Drive Folder {root_id}"}
        file_parent: Dict[str, str] = {}
        file_names: Dict[str, str] = {}

        visited: set[str] = set()

        # stack holds tuples: (folder_id, pseudo_dir_key, depth)
        stack: list[Tuple[str, str, int]] = [(root_id, pseudo_root, 0)]
        while stack:
            fid, pkey, depth = stack.pop()
            if fid in visited or depth > max_depth:
                continue
            visited.add(fid)
            try:
                files, subfolders = self._list_public_folder_children(fid)
            except Exception:
                # skip this branch on error
                continue
            # files
            for f in files:
                name = f.get("name") or f.get("id")
                # Filter by known video suffixes
                if not (name or "").lower().endswith(self.VIDEO_SUFFIXES):
                    continue
                url = self.build_stream_url(f["id"])
                file_parent[url] = pkey
                file_names[url] = name
            # subfolders
            for sf in subfolders:
                sf_id = sf["id"]
                sf_name = sf.get("name") or sf_id
                child_key = f"{pkey}/{sf_id}"
                if child_key not in dirs:
                    dirs.add(child_key)
                    dir_names[child_key] = sf_name
                stack.append((sf_id, child_key, depth + 1))

        return {
            "dirs": dirs,
            "dir_names": dir_names,
            "file_parent": file_parent,
            "file_names": file_names,
        }

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
            pseudo_root = f"gdrive://folder/{folder_id}"
            # Build a full recursive tree and cache it for name/lookups
            tree = self._build_recursive_tree_for_folder(folder_id)
            self._folder_trees[folder_id] = tree

            videos: List[str] = list(tree["file_parent"].keys())
            video_to_dir: Dict[str, str] = dict(tree["file_parent"])  # url -> parent pseudo dir
            directories = sorted(tree["dirs"])  # include all pseudo directories
            return videos, video_to_dir, directories
        else:
            raise ValueError("Invalid Google Drive source descriptor.")

    # Public helpers for UI to get names for display
    def get_folder_tree(self, any_pseudo_dir: str) -> Optional[dict]:
        """
        Given a pseudo directory like gdrive://folder/<root_id>/... return the cached tree
        dict built by gather_videos_with_directories_for_source. Returns None if missing.
        """
        try:
            if not any_pseudo_dir.startswith("gdrive://folder/"):
                return None
            parts = any_pseudo_dir.split("/")
            # parts: ['gdrive:', '', 'folder', '<root_id>', ...]
            if len(parts) < 4:
                return None
            root_id = parts[3]
            return self._folder_trees.get(root_id)
        except Exception:
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
