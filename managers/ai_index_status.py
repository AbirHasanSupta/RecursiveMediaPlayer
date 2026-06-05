from __future__ import annotations

import os
import pickle
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

_INDEX_FILES = ("clip_index.faiss", "text_index.faiss", "metadata.pkl", "tfidf_index.pkl")
_VIDEO_EXTS = frozenset({
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv",
    ".webm", ".m4v", ".ts", ".mts", ".m2ts", ".mpg", ".mpeg",
})


@dataclass
class IndexStatus:
    files_present: bool = False
    video_count: int = 0
    index_mtime: float = 0.0
    device: str = ""
    bridge_ready: bool = False
    new_video_count: int = 0
    missing_video_count: int = 0
    _indexed_dirs: List[str] = field(default_factory=list, repr=False)

    @property
    def is_stale(self) -> bool:
        return self.new_video_count > 0 or self.missing_video_count > 0

    @property
    def indexed_dirs(self) -> List[str]:
        return list(self._indexed_dirs)

    @property
    def index_age_str(self) -> str:
        if not self.index_mtime:
            return ""
        try:
            dt = datetime.fromtimestamp(self.index_mtime)
            now = datetime.now()
            delta = now - dt
            if delta.days == 0:
                return "built today"
            if delta.days == 1:
                return "built yesterday"
            if delta.days < 30:
                return f"built {delta.days}d ago"
            if delta.days < 365:
                return f"built {delta.days // 30}mo ago"
            return f"built {delta.days // 365}y ago"
        except Exception:
            return ""

    def format_device(self) -> Tuple[str, str]:
        """Returns (label, hex_color) for the device badge."""
        d = self.device.lower()
        if "cuda" in d:
            return "GPU", "#34c98a"
        if d == "mps":
            return "MPS", "#5E81F4"
        if d == "cpu":
            return "CPU", "#8B9CB6"
        if d:
            return d.upper()[:6], "#8B9CB6"
        return "", ""

    def ready_status_text(self) -> str:
        parts = []
        if self.video_count:
            parts.append(f"{self.video_count:,} videos indexed")
        age = self.index_age_str
        if age:
            parts.append(age)
        if self.is_stale:
            stale_parts = []
            if self.new_video_count:
                stale_parts.append(f"{self.new_video_count:,} new")
            if self.missing_video_count:
                stale_parts.append(f"{self.missing_video_count:,} removed")
            parts.append("⚠  " + "  ·  ".join(stale_parts) + " — click Index to update")
        text = "  ·  ".join(parts)
        return f"✓  Ready  ·  {text}" if text else "✓  Ready"


class IndexStatusChecker:
    def __init__(self, index_dir: str):
        self._index_dir = Path(index_dir)

    def check_files(self) -> IndexStatus:
        status = IndexStatus()
        if not all((self._index_dir / f).exists() for f in _INDEX_FILES):
            return status

        status.files_present = True
        faiss_path = self._index_dir / "clip_index.faiss"
        try:
            status.index_mtime = faiss_path.stat().st_mtime
        except Exception:
            pass

        meta_path = self._index_dir / "metadata.pkl"
        try:
            with open(meta_path, "rb") as f:
                meta = pickle.load(f)
            paths = meta.get("video_paths", [])
            status.video_count = len(set(paths))
            dirs: set = set()
            for p in paths:
                d = os.path.dirname(p)
                if d:
                    dirs.add(d)
            status._indexed_dirs = sorted(dirs)
        except Exception:
            pass

        return status

    def check_staleness(
        self, status: IndexStatus, watched_dirs: Optional[List[str]] = None
    ) -> IndexStatus:
        if not status.files_present or status.video_count == 0:
            return status

        meta_path = self._index_dir / "metadata.pkl"
        try:
            with open(meta_path, "rb") as f:
                meta = pickle.load(f)
            indexed_set = {
                os.path.normpath(p) for p in meta.get("video_paths", [])
            }
        except Exception:
            return status

        missing = sum(1 for p in indexed_set if not os.path.isfile(p))
        status.missing_video_count = missing

        dirs_to_scan = watched_dirs if watched_dirs else status._indexed_dirs
        if not dirs_to_scan:
            return status

        new_count = 0
        for d in dirs_to_scan:
            try:
                for entry in os.scandir(d):
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if Path(entry.name).suffix.lower() not in _VIDEO_EXTS:
                        continue
                    if os.path.normpath(entry.path) not in indexed_set:
                        new_count += 1
            except (PermissionError, OSError):
                continue

        status.new_video_count = new_count
        return status