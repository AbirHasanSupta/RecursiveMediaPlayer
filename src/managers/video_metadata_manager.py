import json
import os
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import atexit

def _get_app_dirs():
    import sys
    APP = "Recursive Video Player"
    if os.name == "nt":
        settings = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP
        local    = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP
    elif sys.platform == "darwin":
        settings = Path.home() / "Library" / "Application Support" / APP
        local    = Path.home() / "Library" / "Caches" / APP
    else:
        settings = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP
        local    = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / APP
    return settings, local


class VideoAnnotations:
    """Stores tags, rating, and bookmarks for a single video."""
    def __init__(self, video_path: str):
        self.video_path = os.path.normpath(video_path)
        self.rating: int = 0                    # 0–5
        self.tags: List[str] = []
        self.bookmarks: List[dict] = []         # [{ms, label, created}]

    def to_dict(self):
        return {
            "video_path": self.video_path,
            "rating": self.rating,
            "tags": self.tags,
            "bookmarks": self.bookmarks,
        }

    @classmethod
    def from_dict(cls, data: dict):
        obj = cls(data.get("video_path", ""))
        obj.rating    = data.get("rating", 0)
        obj.tags      = data.get("tags", [])
        obj.bookmarks = data.get("bookmarks", [])
        return obj


class VideoAnnotationStorage:
    def __init__(self):
        settings_dir, _ = _get_app_dirs()
        settings_dir.mkdir(parents=True, exist_ok=True)
        self.file = settings_dir / "video_annotations.json"

    def load(self) -> dict:
        try:
            if not self.file.exists():
                return {}, set(), []
            with open(self.file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            annotations = {k: VideoAnnotations.from_dict(v) for k, v in raw.get("annotations", raw).items()}
            empty_tags = set(raw.get("empty_tags", []))
            browser_order = raw.get("browser_order", [])
            return annotations, empty_tags, browser_order
        except Exception as e:
            print(f"[Annotations] load error: {e}")
            return {}, set(), []

    def save(self, data, empty_tags, browser_order=None) -> bool:
        try:
            with open(self.file, "w", encoding="utf-8") as f:
                json.dump({
                    "annotations": {k: v.to_dict() for k, v in data.items()},
                    "empty_tags": sorted(empty_tags),
                    "browser_order": browser_order or [],
                }, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[Annotations] save error: {e}")
            return False


class VideoAnnotationService:
    def __init__(self):
        self.storage = VideoAnnotationStorage()
        self._data: Dict[str, VideoAnnotations] = {}
        self._lock = threading.RLock()
        self._save_timer: Optional[threading.Timer] = None
        self._data, self._empty_tags, self._browser_order = self.storage.load()
        self._change_listeners: list = []
        atexit.register(self._flush)

    def subscribe(self, callback):
        """callback() called on any data mutation."""
        if callback not in self._change_listeners:
            self._change_listeners.append(callback)

    def unsubscribe(self, callback):
        if callback in self._change_listeners:
            self._change_listeners.remove(callback)

    def _notify(self):
        for cb in list(self._change_listeners):
            try:
                cb()
            except Exception:
                pass

    def _key(self, path: str) -> str:
        return os.path.normpath(path)

    def _get_or_create(self, path: str) -> VideoAnnotations:
        k = self._key(path)
        if k not in self._data:
            self._data[k] = VideoAnnotations(path)
        return self._data[k]

    def _schedule_save(self):
        if self._save_timer:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(2.0, self._flush)
        self._save_timer.daemon = True
        self._save_timer.start()

    def _flush(self):
        with self._lock:
            self.storage.save(self._data, self._empty_tags, self._browser_order)

    # ── Ratings ─────────────────────────────────────────────────────────────

    def set_rating(self, path: str, rating: int):
        with self._lock:
            ann = self._get_or_create(path)
            ann.rating = max(0, min(5, rating))
            self._schedule_save()
        self._notify()

    def get_rating(self, path: str) -> int:
        with self._lock:
            return self._data.get(self._key(path), VideoAnnotations(path)).rating

    # ── Tags ─────────────────────────────────────────────────────────────────

    def add_tag(self, path: str, tag: str):
        tag = tag.strip().lower()
        if not tag:
            return
        with self._lock:
            ann = self._get_or_create(path)
            if tag not in ann.tags:
                ann.tags.append(tag)
                self._empty_tags.discard(tag)
                self._schedule_save()
        self._notify()

    def remove_tag(self, path: str, tag: str):
        with self._lock:
            ann = self._data.get(self._key(path))
            if ann and tag in ann.tags:
                ann.tags.remove(tag)
                still_used = any(tag in v.tags for v in self._data.values())
                if not still_used:
                    self._empty_tags.add(tag)
                self._schedule_save()
        self._notify()

    def get_tags(self, path: str) -> List[str]:
        with self._lock:
            ann = self._data.get(self._key(path))
            return list(ann.tags) if ann else []

    def get_all_tags(self) -> List[str]:
        with self._lock:
            tags = set(self._empty_tags)
            for ann in self._data.values():
                tags.update(ann.tags)
            return sorted(tags)

    def create_empty_tag(self, tag: str):
        tag = tag.strip().lower()
        if not tag:
            return
        with self._lock:
            if tag not in self._empty_tags:
                self._empty_tags.add(tag)
                self._schedule_save()
        self._notify()

    def get_videos_with_tag(self, tag: str) -> List[str]:
        with self._lock:
            return [k for k, v in self._data.items() if tag in v.tags]

    # ── Bookmarks ────────────────────────────────────────────────────────────

    def add_bookmark(self, path: str, position_ms: int, label: str = "") -> dict:
        with self._lock:
            ann = self._get_or_create(path)
            bm = {
                "ms": position_ms,
                "label": label or self._fmt_ms(position_ms),
                "created": datetime.now().isoformat()
            }
            ann.bookmarks.append(bm)
            ann.bookmarks.sort(key=lambda b: b["ms"])
            self._schedule_save()
        self._notify()
        return bm

    def remove_bookmark(self, path: str, position_ms: int):
        with self._lock:
            ann = self._data.get(self._key(path))
            if ann:
                ann.bookmarks = [b for b in ann.bookmarks if b["ms"] != position_ms]
                self._schedule_save()
        self._notify()

    def get_bookmarks(self, path: str) -> List[dict]:
        with self._lock:
            ann = self._data.get(self._key(path))
            return list(ann.bookmarks) if ann else []

    def _fmt_ms(self, ms: int) -> str:
        s = ms // 1000
        h, r = divmod(s, 3600)
        m, sec = divmod(r, 60)
        return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

    # ── Query helpers ────────────────────────────────────────────────────────

    def filter_by_rating(self, paths: List[str], min_rating: int) -> List[str]:
        with self._lock:
            return [p for p in paths
                    if self._data.get(self._key(p), VideoAnnotations(p)).rating >= min_rating]

    def filter_by_tag(self, paths: List[str], tag: str) -> List[str]:
        with self._lock:
            return [p for p in paths if tag in self._data.get(self._key(p), VideoAnnotations(p)).tags]

    def set_browser_order(self, ordered_paths: list):
        with self._lock:
            self._browser_order = list(ordered_paths)
            self._flush()

    def get_browser_order(self) -> list:
        with self._lock:
            return list(self._browser_order)