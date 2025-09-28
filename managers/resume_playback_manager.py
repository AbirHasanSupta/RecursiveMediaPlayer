import json
import os
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional, Callable


class PlaybackPosition:
    """Data class for storing playback position information"""

    def __init__(self, video_path: str, position: int = 0, duration: int = 0,
                 last_updated: str = None):
        self.video_path = os.path.normpath(video_path)
        self.position = position
        self.duration = duration
        self.last_updated = last_updated or datetime.now().isoformat()
        self.percentage = 0.0
        if duration > 0:
            self.percentage = (position / duration) * 100

    def to_dict(self) -> dict:
        return {
            'video_path': self.video_path,
            'position': self.position,
            'duration': self.duration,
            'last_updated': self.last_updated,
            'percentage': self.percentage
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'PlaybackPosition':
        return cls(
            video_path=data.get('video_path', ''),
            position=data.get('position', 0),
            duration=data.get('duration', 0),
            last_updated=data.get('last_updated')
        )

    def should_resume(self) -> bool:
        """Determine if this video should be resumed (not near beginning or end)"""
        if self.duration == 0:
            return False

        min_position = 5000
        max_position = self.duration - 5000

        return (self.position >= min_position and
                self.position <= max_position)

    def get_position_formatted(self) -> str:
        """Get formatted position string"""
        seconds = self.position // 1000
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"


class PlaybackPositionStorage:
    """Handles playback position persistence"""

    def __init__(self):
        self.positions_dir = Path.home() / "Documents" / "Recursive Media Player" / "Resume"
        self.positions_dir.mkdir(parents=True, exist_ok=True)
        self.positions_file = self.positions_dir / "playback_positions.json"
        self.max_entries = 500

    def save_positions(self, positions: Dict[str, PlaybackPosition]) -> bool:
        try:
            sorted_positions = sorted(
                positions.values(),
                key=lambda x: x.last_updated,
                reverse=True
            )[:self.max_entries]

            data = {pos.video_path: pos.to_dict() for pos in sorted_positions}

            with open(self.positions_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving playback positions: {e}")
            return False

    def load_positions(self) -> Dict[str, PlaybackPosition]:
        try:
            if not self.positions_file.exists():
                return {}

            with open(self.positions_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            positions = {}
            for video_path, pos_data in data.items():
                positions[video_path] = PlaybackPosition.from_dict(pos_data)

            return positions
        except Exception as e:
            print(f"Error loading playback positions: {e}")
            return {}


class ResumePlaybackService:
    """Service for managing playback positions and resume functionality"""

    def __init__(self, storage: PlaybackPositionStorage):
        self.storage = storage
        self._positions: Dict[str, PlaybackPosition] = {}
        self._lock = threading.Lock()
        self._load_positions()

        self._save_timer = None
        self._pending_saves = False

    def _load_positions(self):
        self._positions = self.storage.load_positions()

    def _schedule_save(self):
        """Schedule a save operation to avoid too frequent disk writes"""
        if self._save_timer:
            self._save_timer.cancel()

        self._pending_saves = True
        self._save_timer = threading.Timer(5.0, self._perform_save)
        self._save_timer.start()

    def _perform_save(self):
        """Perform the actual save operation"""
        if self._pending_saves:
            self.storage.save_positions(self._positions)
            self._pending_saves = False

    def update_position(self, video_path: str, position: int, duration: int = 0):
        """Update playback position for a video"""
        with self._lock:
            video_path_norm = os.path.normpath(video_path)

            playback_pos = PlaybackPosition(
                video_path=video_path_norm,
                position=position,
                duration=duration
            )

            self._positions[video_path_norm] = playback_pos
            self._schedule_save()

    def get_resume_position(self, video_path: str) -> Optional[PlaybackPosition]:
        """Get resume position for a video"""
        with self._lock:
            video_path_norm = os.path.normpath(video_path)
            position = self._positions.get(video_path_norm)

            if position and position.should_resume():
                return position
            return None

    def clear_position(self, video_path: str) -> bool:
        """Clear saved position for a video"""
        with self._lock:
            video_path_norm = os.path.normpath(video_path)
            if video_path_norm in self._positions:
                del self._positions[video_path_norm]
                self._schedule_save()
                return True
            return False

    def get_all_resume_positions(self) -> Dict[str, PlaybackPosition]:
        """Get all positions that can be resumed"""
        with self._lock:
            resumable = {}
            for video_path, position in self._positions.items():
                if position.should_resume():
                    resumable[video_path] = position
            return resumable

    def cleanup_old_positions(self, days: int = 30):
        """Clean up positions older than specified days"""
        with self._lock:
            cutoff_date = datetime.now() - timedelta(days=days)
            to_remove = []

            for video_path, position in self._positions.items():
                try:
                    last_updated = datetime.fromisoformat(position.last_updated)
                    if last_updated < cutoff_date:
                        to_remove.append(video_path)
                except:
                    to_remove.append(video_path)

            for video_path in to_remove:
                del self._positions[video_path]

            if to_remove:
                self._schedule_save()

            return len(to_remove)

    def force_save(self):
        """Force immediate save of positions"""
        if self._save_timer:
            self._save_timer.cancel()
        self._perform_save()


class ResumePlaybackTracker:
    """Tracks playback in real-time and manages resume functionality"""

    def __init__(self, service: ResumePlaybackService):
        self.service = service
        self._tracking_thread = None
        self._is_tracking = False
        self._current_player = None
        self._current_video = None
        self._position_update_callback = None

    def start_tracking(self, player, video_path: str):
        """Start tracking playback position for a video"""
        self.stop_tracking()

        self._current_player = player
        self._current_video = video_path
        self._is_tracking = True

        self._tracking_thread = threading.Thread(
            target=self._track_position,
            daemon=True
        )
        self._tracking_thread.start()

    def stop_tracking(self):
        """Stop tracking current playback"""
        self._is_tracking = False
        if self._tracking_thread and self._tracking_thread.is_alive():
            self._tracking_thread.join(timeout=1.0)

        if self._current_player and self._current_video:
            try:
                position = self._current_player.get_time()
                duration = self._current_player.get_length()
                if position >= 0 and duration > 0:
                    self.service.update_position(self._current_video, position, duration)
            except:
                pass

        self._current_player = None
        self._current_video = None

    def _track_position(self):
        """Background thread that tracks playback position"""
        last_save_time = 0
        save_interval = 10000

        while self._is_tracking and self._current_player:
            try:
                position = self._current_player.get_time()
                duration = self._current_player.get_length()

                if position >= 0 and duration > 0:
                    if position - last_save_time >= save_interval:
                        self.service.update_position(self._current_video, position, duration)
                        last_save_time = position

                        if self._position_update_callback:
                            try:
                                self._position_update_callback(self._current_video, position, duration)
                            except:
                                pass

                time.sleep(1)

            except Exception:
                break

    def set_position_update_callback(self, callback: Callable):
        """Set callback for position updates"""
        self._position_update_callback = callback


class ResumePlaybackManager:
    """Main manager for resume playback functionality"""

    def __init__(self):
        self.storage = PlaybackPositionStorage()
        self.service = ResumePlaybackService(self.storage)
        self.tracker = ResumePlaybackTracker(self.service)

        self._resume_enabled = True
        self._auto_cleanup_days = 30

    def set_resume_enabled(self, enabled: bool):
        """Enable or disable resume functionality"""
        self._resume_enabled = enabled

    def is_resume_enabled(self) -> bool:
        """Check if resume functionality is enabled"""
        return self._resume_enabled

    def should_resume_video(self, video_path: str) -> Optional[PlaybackPosition]:
        """Check if a video should be resumed and return position"""
        if not self._resume_enabled:
            return None

        return self.service.get_resume_position(video_path)

    def start_tracking_video(self, player, video_path: str):
        """Start tracking playback for a video"""
        if self._resume_enabled:
            self.tracker.start_tracking(player, video_path)

    def stop_tracking_video(self):
        """Stop tracking current video"""
        self.tracker.stop_tracking()

    def clear_video_position(self, video_path: str) -> bool:
        """Clear saved position for a specific video"""
        return self.service.clear_position(video_path)

    def get_all_resumable_videos(self) -> Dict[str, PlaybackPosition]:
        """Get all videos that can be resumed"""
        return self.service.get_all_resume_positions()

    def cleanup_old_positions(self) -> int:
        """Clean up old position data"""
        return self.service.cleanup_old_positions(self._auto_cleanup_days)

    def force_save_positions(self):
        """Force save all positions immediately"""
        self.service.force_save()

    def set_position_update_callback(self, callback: Callable):
        """Set callback for position updates during playback"""
        self.tracker.set_position_update_callback(callback)

    def get_resume_stats(self) -> Dict:
        """Get statistics about resumable videos"""
        resumable = self.get_all_resumable_videos()

        return {
            'total_resumable': len(resumable),
            'positions_stored': len(self.service._positions),
            'resume_enabled': self._resume_enabled
        }