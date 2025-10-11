"""
Advanced Filtering and Sorting Manager for Recursive Video Player
Provides comprehensive video filtering and sorting capabilities
"""

import os
import json
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Callable, Optional, Tuple
from collections import defaultdict
import cv2


class VideoMetadata:
    """Data class for video file metadata"""

    def __init__(self, video_path: str):
        self.video_path = os.path.normpath(video_path)
        self.video_name = os.path.basename(self.video_path)
        self.directory = os.path.dirname(self.video_path)

        # File properties
        self.size_bytes = 0
        self.modified_time = 0
        self.created_time = 0

        # Video properties
        self.duration_seconds = 0
        self.resolution = (0, 0)
        self.width = 0
        self.height = 0
        self.fps = 0
        self.codec = "unknown"
        self.bitrate = 0

        # Player statistics
        self.play_count = 0
        self.last_played = None
        self.watch_time_seconds = 0

        self._load_basic_metadata()

    def _load_basic_metadata(self):
        """Load basic file system metadata"""
        try:
            if os.path.exists(self.video_path):
                stat = os.stat(self.video_path)
                self.size_bytes = stat.st_size
                self.modified_time = stat.st_mtime
                self.created_time = stat.st_ctime
        except Exception as e:
            print(f"Error loading metadata for {self.video_path}: {e}")

    def load_video_properties(self):
        """Load video properties using OpenCV"""
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

                # Try to get codec information
                fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
                if fourcc > 0:
                    self.codec = "".join([chr((fourcc >> 8 * i) & 0xFF) for i in range(4)])

                cap.release()
        except Exception as e:
            print(f"Error loading video properties for {self.video_path}: {e}")

    @property
    def size_mb(self) -> float:
        """Get file size in MB"""
        return self.size_bytes / (1024 * 1024)

    @property
    def size_gb(self) -> float:
        """Get file size in GB"""
        return self.size_bytes / (1024 * 1024 * 1024)

    @property
    def resolution_category(self) -> str:
        """Categorize resolution"""
        if self.height >= 2160:
            return "4K"
        elif self.height >= 1440:
            return "2K"
        elif self.height >= 1080:
            return "1080p"
        elif self.height >= 720:
            return "720p"
        elif self.height >= 480:
            return "480p"
        else:
            return "SD"

    @property
    def aspect_ratio(self) -> str:
        """Calculate aspect ratio"""
        if self.width == 0 or self.height == 0:
            return "Unknown"

        ratio = self.width / self.height

        if abs(ratio - 16 / 9) < 0.1:
            return "16:9"
        elif abs(ratio - 4 / 3) < 0.1:
            return "4:3"
        elif abs(ratio - 21 / 9) < 0.1:
            return "21:9"
        else:
            return f"{ratio:.2f}:1"

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            'video_path': self.video_path,
            'size_bytes': self.size_bytes,
            'modified_time': self.modified_time,
            'created_time': self.created_time,
            'duration_seconds': self.duration_seconds,
            'width': self.width,
            'height': self.height,
            'fps': self.fps,
            'codec': self.codec,
            'play_count': self.play_count,
            'last_played': self.last_played,
            'watch_time_seconds': self.watch_time_seconds
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'VideoMetadata':
        """Create from dictionary"""
        metadata = cls(data['video_path'])
        metadata.size_bytes = data.get('size_bytes', 0)
        metadata.modified_time = data.get('modified_time', 0)
        metadata.created_time = data.get('created_time', 0)
        metadata.duration_seconds = data.get('duration_seconds', 0)
        metadata.width = data.get('width', 0)
        metadata.height = data.get('height', 0)
        metadata.resolution = (metadata.width, metadata.height)
        metadata.fps = data.get('fps', 0)
        metadata.codec = data.get('codec', 'unknown')
        metadata.play_count = data.get('play_count', 0)
        metadata.last_played = data.get('last_played')
        metadata.watch_time_seconds = data.get('watch_time_seconds', 0)
        return metadata


class VideoMetadataCache:
    """Cache for video metadata to avoid repeated file operations"""

    def __init__(self):
        self.cache_dir = Path.home() / "Documents" / "Recursive Media Player" / "Cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "video_metadata_cache.json"

        self._cache: Dict[str, VideoMetadata] = {}
        self._lock = threading.Lock()
        self._load_cache()

    def _load_cache(self):
        """Load cache from disk"""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                for video_path, metadata_dict in data.items():
                    self._cache[video_path] = VideoMetadata.from_dict(metadata_dict)
        except Exception as e:
            print(f"Error loading metadata cache: {e}")

    def _save_cache(self):
        """Save cache to disk"""
        try:
            data = {path: meta.to_dict() for path, meta in self._cache.items()}
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving metadata cache: {e}")

    def get_metadata(self, video_path: str, load_properties: bool = False) -> VideoMetadata:
        """Get metadata for a video, using cache if available"""
        video_path = os.path.normpath(video_path)

        with self._lock:
            # Check if in cache and still valid
            if video_path in self._cache:
                cached = self._cache[video_path]

                # Verify file still exists and hasn't been modified
                try:
                    if os.path.exists(video_path):
                        current_mtime = os.stat(video_path).st_mtime
                        if abs(current_mtime - cached.modified_time) < 1:
                            return cached
                except:
                    pass

            # Create new metadata
            metadata = VideoMetadata(video_path)
            if load_properties:
                metadata.load_video_properties()

            self._cache[video_path] = metadata
            return metadata

    def update_play_stats(self, video_path: str, duration_watched: int = 0):
        """Update play statistics for a video"""
        video_path = os.path.normpath(video_path)

        with self._lock:
            if video_path not in self._cache:
                self._cache[video_path] = VideoMetadata(video_path)

            metadata = self._cache[video_path]
            metadata.play_count += 1
            metadata.last_played = datetime.now().isoformat()
            metadata.watch_time_seconds += duration_watched

            self._save_cache()

    def clear_cache(self):
        """Clear all cached metadata"""
        with self._lock:
            self._cache.clear()
            self._save_cache()


class FilterCriteria:
    """Criteria for filtering videos"""

    def __init__(self):
        # File properties
        self.min_size_mb: Optional[float] = None
        self.max_size_mb: Optional[float] = None
        self.modified_within_days: Optional[int] = None

        # Video properties
        self.min_duration_seconds: Optional[float] = None
        self.max_duration_seconds: Optional[float] = None
        self.resolution_categories: List[str] = []
        self.min_width: Optional[int] = None
        self.min_height: Optional[int] = None
        self.codecs: List[str] = []

        # Play statistics
        self.played_recently_days: Optional[int] = None
        self.never_played: bool = False
        self.min_play_count: Optional[int] = None
        self.frequently_played_threshold: int = 3

        # Text search
        self.filename_contains: str = ""
        self.path_contains: str = ""

    def matches(self, metadata: VideoMetadata) -> bool:
        """Check if video matches filter criteria"""
        # Size filters
        if self.min_size_mb is not None and metadata.size_mb < self.min_size_mb:
            return False
        if self.max_size_mb is not None and metadata.size_mb > self.max_size_mb:
            return False

        # Modified time filter
        if self.modified_within_days is not None:
            cutoff = datetime.now() - timedelta(days=self.modified_within_days)
            file_time = datetime.fromtimestamp(metadata.modified_time)
            if file_time < cutoff:
                return False

        # Duration filters
        if self.min_duration_seconds is not None and metadata.duration_seconds < self.min_duration_seconds:
            return False
        if self.max_duration_seconds is not None and metadata.duration_seconds > self.max_duration_seconds:
            return False

        # Resolution filters
        if self.resolution_categories and metadata.resolution_category not in self.resolution_categories:
            return False
        if self.min_width is not None and metadata.width < self.min_width:
            return False
        if self.min_height is not None and metadata.height < self.min_height:
            return False

        # Codec filter
        if self.codecs and metadata.codec not in self.codecs:
            return False

        # Play statistics filters
        if self.never_played and metadata.play_count > 0:
            return False

        if self.min_play_count is not None and metadata.play_count < self.min_play_count:
            return False

        if self.played_recently_days is not None:
            if metadata.last_played is None:
                return False

            try:
                last_played = datetime.fromisoformat(metadata.last_played)
                cutoff = datetime.now() - timedelta(days=self.played_recently_days)
                if last_played < cutoff:
                    return False
            except:
                return False

        # Text search
        if self.filename_contains and self.filename_contains.lower() not in metadata.video_name.lower():
            return False
        if self.path_contains and self.path_contains.lower() not in metadata.video_path.lower():
            return False

        return True


class SortCriteria:
    """Criteria for sorting videos"""

    SORT_OPTIONS = {
        'name_asc': ('Name (A-Z)', lambda m: m.video_name.lower()),
        'name_desc': ('Name (Z-A)', lambda m: m.video_name.lower(), True),
        'date_modified_desc': ('Date Modified (Newest)', lambda m: m.modified_time, True),
        'date_modified_asc': ('Date Modified (Oldest)', lambda m: m.modified_time),
        'date_created_desc': ('Date Created (Newest)', lambda m: m.created_time, True),
        'date_created_asc': ('Date Created (Oldest)', lambda m: m.created_time),
        'size_desc': ('Size (Largest)', lambda m: m.size_bytes, True),
        'size_asc': ('Size (Smallest)', lambda m: m.size_bytes),
        'duration_desc': ('Duration (Longest)', lambda m: m.duration_seconds, True),
        'duration_asc': ('Duration (Shortest)', lambda m: m.duration_seconds),
        'resolution_desc': ('Resolution (Highest)', lambda m: m.width * m.height, True),
        'resolution_asc': ('Resolution (Lowest)', lambda m: m.width * m.height),
        'play_count_desc': ('Most Played', lambda m: m.play_count, True),
        'play_count_asc': ('Least Played', lambda m: m.play_count),
        'last_played_desc': ('Recently Played', lambda m: m.last_played or "", True),
        'last_played_asc': ('Least Recently Played', lambda m: m.last_played or ""),
        'watch_time_desc': ('Most Watched Time', lambda m: m.watch_time_seconds, True),
        'random': ('Random', None)
    }

    def __init__(self, sort_by: str = 'name_asc'):
        self.sort_by = sort_by

    def sort_videos(self, videos: List[VideoMetadata]) -> List[VideoMetadata]:
        """Sort videos according to criteria"""
        if self.sort_by == 'random':
            import random
            result = videos.copy()
            random.shuffle(result)
            return result

        if self.sort_by not in self.SORT_OPTIONS:
            return videos

        sort_info = self.SORT_OPTIONS[self.sort_by]
        key_func = sort_info[1]
        reverse = sort_info[2] if len(sort_info) > 2 else False

        if key_func:
            return sorted(videos, key=key_func, reverse=reverse)

        return videos


class AdvancedFilterSortManager:
    """Main manager for advanced filtering and sorting"""

    def __init__(self, watch_history_manager=None):
        self.metadata_cache = VideoMetadataCache()
        self.watch_history_manager = watch_history_manager

        self.current_filter = FilterCriteria()
        self.current_sort = SortCriteria()

        # Quick filter presets
        self.quick_filters = {
            'all': ('All Videos', FilterCriteria()),
            'recent_7days': ('Added Last 7 Days', self._create_recent_filter(7)),
            'recent_30days': ('Added Last 30 Days', self._create_recent_filter(30)),
            'played_today': ('Played Today', self._create_played_recently_filter(1)),
            'played_week': ('Played This Week', self._create_played_recently_filter(7)),
            'never_played': ('Never Played', self._create_never_played_filter()),
            'frequently_played': ('Frequently Played', self._create_frequently_played_filter()),
            'hd_videos': ('HD Videos (720p+)', self._create_hd_filter()),
            'full_hd_videos': ('Full HD Videos (1080p+)', self._create_full_hd_filter()),
            'large_files': ('Large Files (>1GB)', self._create_large_files_filter()),
            'short_videos': ('Short Videos (<5min)', self._create_short_videos_filter()),
            'long_videos': ('Long Videos (>30min)', self._create_long_videos_filter())
        }

    def _create_recent_filter(self, days: int) -> FilterCriteria:
        """Create filter for recently added videos"""
        criteria = FilterCriteria()
        criteria.modified_within_days = days
        return criteria

    def _create_played_recently_filter(self, days: int) -> FilterCriteria:
        """Create filter for recently played videos"""
        criteria = FilterCriteria()
        criteria.played_recently_days = days
        return criteria

    def _create_never_played_filter(self) -> FilterCriteria:
        """Create filter for never played videos"""
        criteria = FilterCriteria()
        criteria.never_played = True
        return criteria

    def _create_frequently_played_filter(self) -> FilterCriteria:
        """Create filter for frequently played videos"""
        criteria = FilterCriteria()
        criteria.min_play_count = 3
        return criteria

    def _create_hd_filter(self) -> FilterCriteria:
        """Create filter for HD videos"""
        criteria = FilterCriteria()
        criteria.min_height = 720
        return criteria

    def _create_full_hd_filter(self) -> FilterCriteria:
        """Create filter for Full HD videos"""
        criteria = FilterCriteria()
        criteria.min_height = 1080
        return criteria

    def _create_large_files_filter(self) -> FilterCriteria:
        """Create filter for large files"""
        criteria = FilterCriteria()
        criteria.min_size_mb = 1024  # 1GB
        return criteria

    def _create_short_videos_filter(self) -> FilterCriteria:
        """Create filter for short videos"""
        criteria = FilterCriteria()
        criteria.max_duration_seconds = 300  # 5 minutes
        return criteria

    def _create_long_videos_filter(self) -> FilterCriteria:
        """Create filter for long videos"""
        criteria = FilterCriteria()
        criteria.min_duration_seconds = 1800  # 30 minutes
        return criteria

    def apply_filter_and_sort(self, video_paths: List[str],
                              load_properties: bool = True,
                              progress_callback: Optional[Callable] = None) -> List[str]:
        """Apply current filter and sort criteria to video list"""
        # Load metadata for all videos
        metadata_list = []
        total = len(video_paths)

        for i, video_path in enumerate(video_paths):
            try:
                metadata = self.metadata_cache.get_metadata(video_path, load_properties)

                # Update with play statistics from watch history
                if self.watch_history_manager:
                    self._update_play_stats_from_history(metadata)

                metadata_list.append(metadata)

                if progress_callback and i % 10 == 0:
                    progress_callback(i, total)

            except Exception as e:
                print(f"Error processing {video_path}: {e}")

        if progress_callback:
            progress_callback(total, total)

        # Apply filter
        filtered = [m for m in metadata_list if self.current_filter.matches(m)]

        # Apply sort
        sorted_metadata = self.current_sort.sort_videos(filtered)

        # Return sorted video paths
        return [m.video_path for m in sorted_metadata]

    def _update_play_stats_from_history(self, metadata: VideoMetadata):
        """Update metadata with play statistics from watch history"""
        try:
            history = self.watch_history_manager.service.get_all_history()
            video_path_norm = os.path.normpath(metadata.video_path)

            play_count = 0
            last_played = None
            total_watch_time = 0

            for entry in history:
                if os.path.normpath(entry.video_path) == video_path_norm:
                    play_count += 1
                    total_watch_time += entry.duration_watched

                    if last_played is None or entry.watched_at > last_played:
                        last_played = entry.watched_at

            metadata.play_count = play_count
            metadata.last_played = last_played
            metadata.watch_time_seconds = total_watch_time

        except Exception as e:
            print(f"Error updating play stats: {e}")

    def get_quick_filter_names(self) -> List[Tuple[str, str]]:
        """Get list of quick filter names"""
        return [(key, info[0]) for key, info in self.quick_filters.items()]

    def apply_quick_filter(self, filter_key: str):
        """Apply a quick filter preset"""
        if filter_key in self.quick_filters:
            self.current_filter = self.quick_filters[filter_key][1]

    def get_sort_options(self) -> List[Tuple[str, str]]:
        """Get list of sort options"""
        return [(key, info[0]) for key, info in SortCriteria.SORT_OPTIONS.items()]

    def set_sort(self, sort_key: str):
        """Set current sort criteria"""
        self.current_sort = SortCriteria(sort_key)

    def get_video_statistics(self, video_paths: List[str]) -> Dict[str, Any]:
        """Get statistics about video collection"""
        metadata_list = [self.metadata_cache.get_metadata(vp, True) for vp in video_paths]

        total_size = sum(m.size_bytes for m in metadata_list)
        total_duration = sum(m.duration_seconds for m in metadata_list)

        resolution_counts = defaultdict(int)
        codec_counts = defaultdict(int)

        for m in metadata_list:
            resolution_counts[m.resolution_category] += 1
            codec_counts[m.codec] += 1

        return {
            'total_videos': len(metadata_list),
            'total_size_gb': total_size / (1024 ** 3),
            'total_duration_hours': total_duration / 3600,
            'avg_size_mb': (total_size / len(metadata_list)) / (1024 ** 2) if metadata_list else 0,
            'avg_duration_minutes': (total_duration / len(metadata_list)) / 60 if metadata_list else 0,
            'resolution_distribution': dict(resolution_counts),
            'codec_distribution': dict(codec_counts),
            'played_count': sum(1 for m in metadata_list if m.play_count > 0),
            'never_played_count': sum(1 for m in metadata_list if m.play_count == 0)
        }