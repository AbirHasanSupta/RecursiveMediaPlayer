"""
VideoMetadataCache — fast pickle-based cache replacing the original JSON version.

What changed vs original filter_sort_manager.py:
- VideoMetadataCache persists with pickle (protocol HIGHEST_PROTOCOL) instead
  of JSON.  Pickle is ~5-10× faster to read/write for large dicts of Python
  objects and produces smaller files.
- Saves are debounced (3-second timer) so rapid play-stat updates don't hammer
  the disk.
- All other classes (VideoMetadata, FilterCriteria, SortCriteria,
  AdvancedFilterSortManager) are identical to the original.
"""

import os
import json
import pickle
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Callable, Optional, Tuple
from collections import defaultdict
import cv2

from managers.resource_manager import get_resource_manager


# ---------------------------------------------------------------------------
# VideoMetadata  (unchanged)
# ---------------------------------------------------------------------------

class VideoMetadata:
    def __init__(self, video_path: str):
        self.video_path = os.path.normpath(video_path)
        self.video_name = os.path.basename(self.video_path)
        self.directory = os.path.dirname(self.video_path)
        self.size_bytes = 0
        self.modified_time = 0.0
        self.created_time = 0.0
        self.duration_seconds = 0.0
        self.resolution = (0, 0)
        self.width = 0
        self.height = 0
        self.fps = 0.0
        self.codec = "unknown"
        self.bitrate = 0
        self.play_count = 0
        self.last_played: Optional[str] = None
        self.watch_time_seconds = 0
        self._load_basic_metadata()

    def _load_basic_metadata(self):
        try:
            if os.path.exists(self.video_path):
                st = os.stat(self.video_path)
                self.size_bytes = st.st_size
                self.modified_time = st.st_mtime
                self.created_time = st.st_ctime
        except Exception:
            pass

    def load_video_properties(self):
        try:
            cap = cv2.VideoCapture(self.video_path)
            if cap.isOpened():
                self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                self.resolution = (self.width, self.height)
                self.fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                if self.fps > 0:
                    self.duration_seconds = frame_count / self.fps
                fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
                if fourcc > 0:
                    self.codec = "".join([chr((fourcc >> 8 * i) & 0xFF) for i in range(4)])
                cap.release()
        except Exception:
            pass

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)

    @property
    def size_gb(self) -> float:
        return self.size_bytes / (1024 ** 3)

    @property
    def resolution_category(self) -> str:
        if self.height >= 2160: return "4K"
        if self.height >= 1440: return "2K"
        if self.height >= 1080: return "1080p"
        if self.height >= 720:  return "720p"
        if self.height >= 480:  return "480p"
        return "SD"

    @property
    def aspect_ratio(self) -> str:
        if self.width == 0 or self.height == 0:
            return "Unknown"
        r = self.width / self.height
        if abs(r - 16/9)  < 0.1: return "16:9"
        if abs(r - 4/3)   < 0.1: return "4:3"
        if abs(r - 21/9)  < 0.1: return "21:9"
        return f"{r:.2f}:1"

    def to_dict(self) -> dict:
        return {
            "video_path": self.video_path,
            "size_bytes": self.size_bytes,
            "modified_time": self.modified_time,
            "created_time": self.created_time,
            "duration_seconds": self.duration_seconds,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "codec": self.codec,
            "play_count": self.play_count,
            "last_played": self.last_played,
            "watch_time_seconds": self.watch_time_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VideoMetadata":
        m = cls.__new__(cls)
        m.video_path        = data.get("video_path", "")
        m.video_name        = os.path.basename(m.video_path)
        m.directory         = os.path.dirname(m.video_path)
        m.size_bytes        = data.get("size_bytes", 0)
        m.modified_time     = data.get("modified_time", 0.0)
        m.created_time      = data.get("created_time", 0.0)
        m.duration_seconds  = data.get("duration_seconds", 0.0)
        m.width             = data.get("width", 0)
        m.height            = data.get("height", 0)
        m.resolution        = (m.width, m.height)
        m.fps               = data.get("fps", 0.0)
        m.codec             = data.get("codec", "unknown")
        m.bitrate           = 0
        m.play_count        = data.get("play_count", 0)
        m.last_played       = data.get("last_played")
        m.watch_time_seconds = data.get("watch_time_seconds", 0)
        return m


# ---------------------------------------------------------------------------
# VideoMetadataCache  (fast pickle, debounced saves)
# ---------------------------------------------------------------------------

class VideoMetadataCache:
    """
    Pickle-based metadata cache.

    Compared to the original JSON version:
    - load: uses pickle.load  (no per-object JSON parsing)
    - save: uses pickle.dump with HIGHEST_PROTOCOL  (binary, compact, fast)
    - saves are debounced 3 s so rapid play-stat updates don't thrash disk
    """

    def __init__(self):
        self.cache_dir = (
            Path.home() / "Documents" / "Recursive Media Player" / "Cache"
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "video_metadata_cache.pkl"
        # Keep the old JSON path around only for migration
        self._legacy_json = self.cache_dir / "video_metadata_cache.json"

        self._cache: Dict[str, VideoMetadata] = {}
        self._lock = threading.RLock()
        self._save_timer: Optional[threading.Timer] = None
        self._dirty = False

        self._load_cache()
        get_resource_manager().register_cleanup_callback(self._cleanup)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _cleanup(self):
        try:
            self._cancel_save_timer()
            if self._dirty:
                self._flush()
            with self._lock:
                self._cache.clear()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def _load_cache(self):
        # 1. Try the fast pickle file first
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "rb") as f:
                    data = pickle.load(f)
                # data might be dict[path, VideoMetadata] (new) or dict[path, dict] (old pickle)
                self._cache = {}
                for k, v in data.items():
                    if isinstance(v, VideoMetadata):
                        self._cache[k] = v
                    elif isinstance(v, dict):
                        self._cache[k] = VideoMetadata.from_dict(v)
                return
            except Exception as e:
                print(f"[MetadataCache] pickle load failed: {e}, trying legacy JSON")

        # 2. Fall back to legacy JSON and migrate
        if self._legacy_json.exists():
            try:
                with open(self._legacy_json, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self._cache = {k: VideoMetadata.from_dict(v) for k, v in raw.items()}
                self._dirty = True   # schedule migration write
                self._schedule_save()
                return
            except Exception as e:
                print(f"[MetadataCache] JSON fallback failed: {e}")

        self._cache = {}

    # ------------------------------------------------------------------
    # Save (debounced)
    # ------------------------------------------------------------------

    def _schedule_save(self, delay: float = 3.0):
        self._dirty = True
        self._cancel_save_timer()
        self._save_timer = threading.Timer(delay, self._flush)
        self._save_timer.daemon = True
        self._save_timer.start()

    def _cancel_save_timer(self):
        if self._save_timer:
            self._save_timer.cancel()
            self._save_timer = None

    def _flush(self):
        """Atomically write the pickle cache."""
        with self._lock:
            snapshot = dict(self._cache)   # shallow copy while holding lock
        tmp = self.cache_file.with_suffix(".tmp")
        try:
            with open(tmp, "wb") as f:
                pickle.dump(snapshot, f, protocol=pickle.HIGHEST_PROTOCOL)
            tmp.replace(self.cache_file)
            self._dirty = False
        except Exception as e:
            print(f"[MetadataCache] flush error: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Public API  (identical to original)
    # ------------------------------------------------------------------

    def get_metadata(self, video_path: str, load_properties: bool = False) -> VideoMetadata:
        video_path = os.path.normpath(video_path)
        with self._lock:
            cached = self._cache.get(video_path)
            if cached is not None:
                try:
                    if os.path.exists(video_path):
                        if abs(os.stat(video_path).st_mtime - cached.modified_time) < 1:
                            return cached
                except Exception:
                    pass

            m = VideoMetadata(video_path)
            if load_properties:
                m.load_video_properties()
            self._cache[video_path] = m
            self._schedule_save()
            return m

    def update_play_stats(self, video_path: str, duration_watched: int = 0):
        video_path = os.path.normpath(video_path)
        with self._lock:
            if video_path not in self._cache:
                self._cache[video_path] = VideoMetadata(video_path)
            m = self._cache[video_path]
            m.play_count += 1
            m.last_played = datetime.now().isoformat()
            m.watch_time_seconds += duration_watched
        self._schedule_save(delay=5.0)   # longer debounce for frequent play events

    def clear_cache(self) -> int:
        self._cancel_save_timer()
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
        self._flush()
        return count

    def get_cache_info(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._cache)
        size = 0
        try:
            if self.cache_file.exists():
                size = self.cache_file.stat().st_size
        except Exception:
            pass
        return {
            "total_entries": total,
            "cache_size_bytes": size,
            "cache_size_mb": size / (1024 * 1024),
            "cache_file": str(self.cache_file),
        }


# ---------------------------------------------------------------------------
# FilterCriteria  (unchanged)
# ---------------------------------------------------------------------------

class FilterCriteria:
    def __init__(self):
        self.min_size_mb: Optional[float] = None
        self.max_size_mb: Optional[float] = None
        self.modified_within_days: Optional[int] = None
        self.min_duration_seconds: Optional[float] = None
        self.max_duration_seconds: Optional[float] = None
        self.resolution_categories: List[str] = []
        self.min_width: Optional[int] = None
        self.min_height: Optional[int] = None
        self.codecs: List[str] = []
        self.played_recently_days: Optional[int] = None
        self.never_played: bool = False
        self.min_play_count: Optional[int] = None
        self.frequently_played_threshold: int = 3
        self.filename_contains: str = ""
        self.path_contains: str = ""

    def matches(self, m: VideoMetadata) -> bool:
        if self.min_size_mb is not None and m.size_mb < self.min_size_mb: return False
        if self.max_size_mb is not None and m.size_mb > self.max_size_mb: return False
        if self.modified_within_days is not None:
            if datetime.fromtimestamp(m.modified_time) < datetime.now() - timedelta(days=self.modified_within_days):
                return False
        if self.min_duration_seconds is not None and m.duration_seconds < self.min_duration_seconds: return False
        if self.max_duration_seconds is not None and m.duration_seconds > self.max_duration_seconds: return False
        if self.resolution_categories and m.resolution_category not in self.resolution_categories: return False
        if self.min_width  is not None and m.width  < self.min_width:  return False
        if self.min_height is not None and m.height < self.min_height: return False
        if self.codecs and m.codec not in self.codecs: return False
        if self.never_played and m.play_count > 0: return False
        if self.min_play_count is not None and m.play_count < self.min_play_count: return False
        if self.played_recently_days is not None:
            if m.last_played is None: return False
            try:
                if datetime.fromisoformat(m.last_played) < datetime.now() - timedelta(days=self.played_recently_days):
                    return False
            except Exception:
                return False
        if self.filename_contains and self.filename_contains.lower() not in m.video_name.lower(): return False
        if self.path_contains  and self.path_contains.lower()  not in m.video_path.lower():  return False
        return True


# ---------------------------------------------------------------------------
# SortCriteria  (unchanged)
# ---------------------------------------------------------------------------

class SortCriteria:
    SORT_OPTIONS = {
        "name_asc":            ("Name (A-Z)",              lambda m: m.video_name.lower(),        False),
        "name_desc":           ("Name (Z-A)",              lambda m: m.video_name.lower(),        True),
        "date_modified_desc":  ("Date Modified (Newest)",  lambda m: m.modified_time,             True),
        "date_modified_asc":   ("Date Modified (Oldest)",  lambda m: m.modified_time,             False),
        "date_created_desc":   ("Date Created (Newest)",   lambda m: m.created_time,              True),
        "date_created_asc":    ("Date Created (Oldest)",   lambda m: m.created_time,              False),
        "size_desc":           ("Size (Largest)",          lambda m: m.size_bytes,                True),
        "size_asc":            ("Size (Smallest)",         lambda m: m.size_bytes,                False),
        "duration_desc":       ("Duration (Longest)",      lambda m: m.duration_seconds,          True),
        "duration_asc":        ("Duration (Shortest)",     lambda m: m.duration_seconds,          False),
        "resolution_desc":     ("Resolution (Highest)",    lambda m: m.width * m.height,          True),
        "resolution_asc":      ("Resolution (Lowest)",     lambda m: m.width * m.height,          False),
        "play_count_desc":     ("Most Played",             lambda m: m.play_count,                True),
        "play_count_asc":      ("Least Played",            lambda m: m.play_count,                False),
        "last_played_desc":    ("Recently Played",         lambda m: m.last_played or "",         True),
        "last_played_asc":     ("Least Recently Played",   lambda m: m.last_played or "",         False),
        "watch_time_desc":     ("Most Watched Time",       lambda m: m.watch_time_seconds,        True),
        "random":              ("Random",                  None,                                  False),
    }

    def __init__(self, sort_by: str = "name_asc"):
        self.sort_by = sort_by

    def sort_videos(self, videos: List[VideoMetadata]) -> List[VideoMetadata]:
        if self.sort_by == "random":
            import random
            result = videos.copy()
            random.shuffle(result)
            return result
        info = self.SORT_OPTIONS.get(self.sort_by)
        if not info or info[1] is None:
            return videos
        return sorted(videos, key=info[1], reverse=info[2])


# ---------------------------------------------------------------------------
# AdvancedFilterSortManager  (unchanged, uses new cache)
# ---------------------------------------------------------------------------

class AdvancedFilterSortManager:
    def __init__(self, watch_history_manager=None):
        self.metadata_cache = VideoMetadataCache()
        self.watch_history_manager = watch_history_manager
        self.current_filter = FilterCriteria()
        self.current_sort   = SortCriteria()

        self.quick_filters = {
            "all":                ("All Videos",                FilterCriteria()),
            "recent_7days":       ("Added Last 7 Days",         self._recent(7)),
            "recent_30days":      ("Added Last 30 Days",        self._recent(30)),
            "played_today":       ("Played Today",              self._played_recently(1)),
            "played_week":        ("Played This Week",          self._played_recently(7)),
            "never_played":       ("Never Played",              self._never_played()),
            "frequently_played":  ("Frequently Played",         self._frequent()),
            "hd_videos":          ("HD Videos (720p+)",         self._min_h(720)),
            "full_hd_videos":     ("Full HD Videos (1080p+)",   self._min_h(1080)),
            "large_files":        ("Large Files (>1GB)",        self._large()),
            "short_videos":       ("Short Videos (<5min)",      self._short()),
            "long_videos":        ("Long Videos (>30min)",      self._long()),
        }

    # ------------------------------------------------------------------
    # Quick-filter factories
    # ------------------------------------------------------------------
    def _recent(self, days):
        c = FilterCriteria(); c.modified_within_days = days; return c
    def _played_recently(self, days):
        c = FilterCriteria(); c.played_recently_days = days; return c
    def _never_played(self):
        c = FilterCriteria(); c.never_played = True; return c
    def _frequent(self):
        c = FilterCriteria(); c.min_play_count = 3; return c
    def _min_h(self, h):
        c = FilterCriteria(); c.min_height = h; return c
    def _large(self):
        c = FilterCriteria(); c.min_size_mb = 1024; return c
    def _short(self):
        c = FilterCriteria(); c.max_duration_seconds = 300; return c
    def _long(self):
        c = FilterCriteria(); c.min_duration_seconds = 1800; return c

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def apply_filter_and_sort(self, video_paths: List[str],
                              load_properties: bool = True,
                              progress_callback: Optional[Callable] = None) -> List[str]:
        meta_list = []
        total = len(video_paths)
        for i, vp in enumerate(video_paths):
            try:
                m = self.metadata_cache.get_metadata(vp, load_properties)
                if self.watch_history_manager:
                    self._update_play_stats(m)
                meta_list.append(m)
                if progress_callback and i % 10 == 0:
                    progress_callback(i, total)
            except Exception as e:
                print(f"[FilterSort] {vp}: {e}")
        if progress_callback:
            progress_callback(total, total)
        filtered = [m for m in meta_list if self.current_filter.matches(m)]
        sorted_m = self.current_sort.sort_videos(filtered)
        return [m.video_path for m in sorted_m]

    def _update_play_stats(self, m: VideoMetadata):
        try:
            history = self.watch_history_manager.service.get_all_history()
            norm = os.path.normpath(m.video_path)
            pc = 0; last = None; wt = 0
            for e in history:
                if os.path.normpath(e.video_path) == norm:
                    pc += 1; wt += e.duration_watched
                    if last is None or e.watched_at > last:
                        last = e.watched_at
            m.play_count = pc; m.last_played = last; m.watch_time_seconds = wt
        except Exception:
            pass

    def get_quick_filter_names(self) -> List[Tuple[str, str]]:
        return [(k, v[0]) for k, v in self.quick_filters.items()]

    def apply_quick_filter(self, key: str):
        if key in self.quick_filters:
            self.current_filter = self.quick_filters[key][1]

    def get_sort_options(self) -> List[Tuple[str, str]]:
        return [(k, v[0]) for k, v in SortCriteria.SORT_OPTIONS.items()]

    def set_sort(self, key: str):
        self.current_sort = SortCriteria(key)

    def get_video_statistics(self, video_paths: List[str]) -> Dict[str, Any]:
        meta_list = [self.metadata_cache.get_metadata(vp, True) for vp in video_paths]
        total_size = sum(m.size_bytes for m in meta_list)
        total_dur  = sum(m.duration_seconds for m in meta_list)
        res_counts  = defaultdict(int)
        codec_counts = defaultdict(int)
        for m in meta_list:
            res_counts[m.resolution_category] += 1
            codec_counts[m.codec] += 1
        n = len(meta_list) or 1
        return {
            "total_videos":            len(meta_list),
            "total_size_gb":           total_size / (1024 ** 3),
            "total_duration_hours":    total_dur / 3600,
            "avg_size_mb":             (total_size / n) / (1024 ** 2),
            "avg_duration_minutes":    (total_dur / n) / 60,
            "resolution_distribution": dict(res_counts),
            "codec_distribution":      dict(codec_counts),
            "played_count":            sum(1 for m in meta_list if m.play_count > 0),
            "never_played_count":      sum(1 for m in meta_list if m.play_count == 0),
        }