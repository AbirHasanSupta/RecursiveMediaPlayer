import os
import json
import cv2
import threading
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageTk
from typing import Dict, List, Optional, Tuple, Any


class VideoMetadata:
    """Extract and manage video metadata"""

    def __init__(self):
        self.metadata_cache = {}
        self.cache_path = Path.home() / "Documents" / "Recursive Media Player" / "metadata_cache.json"
        self.load_cache()

    def extract_metadata(self, video_path: str) -> Dict[str, Any]:
        """Extract comprehensive video metadata"""
        if video_path in self.metadata_cache:
            return self.metadata_cache[video_path]

        metadata = {
            'file_size': 0,
            'duration': 0,
            'width': 0,
            'height': 0,
            'fps': 0,
            'codec': 'unknown',
            'bitrate': 0,
            'creation_date': '',
            'modified_date': '',
            'thumbnail_path': ''
        }

        try:
            # File system metadata
            stat = os.stat(video_path)
            metadata['file_size'] = stat.st_size
            metadata['creation_date'] = datetime.fromtimestamp(stat.st_ctime).isoformat()
            metadata['modified_date'] = datetime.fromtimestamp(stat.st_mtime).isoformat()

            # Video metadata using OpenCV
            cap = cv2.VideoCapture(video_path)
            if cap.isOpened():
                metadata['width'] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                metadata['height'] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                metadata['fps'] = cap.get(cv2.CAP_PROP_FPS)
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                if metadata['fps'] > 0:
                    metadata['duration'] = frame_count / metadata['fps']

                # Try to get codec info
                fourcc = cap.get(cv2.CAP_PROP_FOURCC)
                if fourcc:
                    metadata['codec'] = "".join([chr((int(fourcc) >> 8 * i) & 0xFF) for i in range(4)])

                cap.release()

            # Estimate bitrate
            if metadata['duration'] > 0:
                metadata['bitrate'] = int((metadata['file_size'] * 8) / metadata['duration'])

            # Cache the metadata
            self.metadata_cache[video_path] = metadata
            self.save_cache()

        except Exception as e:
            print(f"Error extracting metadata for {video_path}: {e}")

        return metadata

    def load_cache(self):
        """Load metadata cache from file"""
        try:
            if self.cache_path.exists():
                with open(self.cache_path, 'r') as f:
                    self.metadata_cache = json.load(f)
        except Exception as e:
            print(f"Error loading metadata cache: {e}")
            self.metadata_cache = {}

    def save_cache(self):
        """Save metadata cache to file"""
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, 'w') as f:
                json.dump(self.metadata_cache, f, indent=2)
        except Exception as e:
            print(f"Error saving metadata cache: {e}")

    def format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"

    def format_file_size(self, bytes_size: int) -> str:
        """Format file size in human-readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f} PB"


class ThumbnailGenerator:
    """Generate and manage video thumbnails"""

    def __init__(self):
        self.thumbnail_dir = Path.home() / "Documents" / "Recursive Media Player" / "thumbnails"
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnail_cache = {}
        self.thumbnail_size = (160, 120)

    def generate_thumbnail(self, video_path: str) -> Optional[str]:
        """Generate thumbnail for video"""
        video_name = Path(video_path).stem
        thumbnail_path = self.thumbnail_dir / f"{video_name}_{hash(video_path) % 100000}.jpg"

        if thumbnail_path.exists():
            return str(thumbnail_path)

        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return None

            # Get frame from 10% into the video
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            target_frame = int(frame_count * 0.1)
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

            ret, frame = cap.read()
            if ret:
                # Resize frame
                frame = cv2.resize(frame, self.thumbnail_size)
                # Convert BGR to RGB
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                # Save as JPEG
                frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                cv2.imwrite(str(thumbnail_path), frame_bgr)
                cap.release()
                return str(thumbnail_path)

            cap.release()

        except Exception as e:
            print(f"Error generating thumbnail for {video_path}: {e}")

        return None

    def get_thumbnail(self, video_path: str) -> Optional[str]:
        """Get thumbnail path for video, generating if necessary"""
        if video_path in self.thumbnail_cache:
            return self.thumbnail_cache[video_path]

        thumbnail_path = self.generate_thumbnail(video_path)
        if thumbnail_path:
            self.thumbnail_cache[video_path] = thumbnail_path

        return thumbnail_path


class ResumePlaybackManager:
    """Manage video playback resume positions"""

    def __init__(self):
        self.resume_file = Path.home() / "Documents" / "Recursive Media Player" / "resume_data.json"
        self.resume_data = {}
        self.load_resume_data()

    def save_position(self, video_path: str, position_seconds: float, duration_seconds: float = None):
        """Save playback position for a video"""
        self.resume_data[video_path] = {
            'position': position_seconds,
            'duration': duration_seconds,
            'timestamp': datetime.now().isoformat()
        }
        self.save_resume_data()

    def get_resume_position(self, video_path: str) -> Optional[float]:
        """Get resume position for a video"""
        if video_path in self.resume_data:
            data = self.resume_data[video_path]
            # Don't resume if we're near the end (last 5% or 30 seconds)
            if data.get('duration'):
                remaining = data['duration'] - data['position']
                if remaining < 30 or (remaining / data['duration']) < 0.05:
                    return None
            return data['position']
        return None

    def clear_resume_position(self, video_path: str):
        """Clear resume position for a video"""
        if video_path in self.resume_data:
            del self.resume_data[video_path]
            self.save_resume_data()

    def load_resume_data(self):
        """Load resume data from file"""
        try:
            if self.resume_file.exists():
                with open(self.resume_file, 'r') as f:
                    self.resume_data = json.load(f)
        except Exception as e:
            print(f"Error loading resume data: {e}")
            self.resume_data = {}

    def save_resume_data(self):
        """Save resume data to file"""
        try:
            self.resume_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.resume_file, 'w') as f:
                json.dump(self.resume_data, f, indent=2)
        except Exception as e:
            print(f"Error saving resume data: {e}")


class PreviewWindow:
    """Show video preview window with thumbnail and metadata"""

    def __init__(self, parent, thumbnail_generator: ThumbnailGenerator, metadata_extractor: VideoMetadata):
        self.parent = parent
        self.thumbnail_generator = thumbnail_generator
        self.metadata_extractor = metadata_extractor
        self.preview_window = None
        self.current_video = None

    def show_preview(self, video_path: str, x: int, y: int):
        """Show preview window for video"""
        if self.preview_window:
            self.hide_preview()

        self.current_video = video_path
        self.preview_window = tk.Toplevel(self.parent)
        self.preview_window.wm_overrideredirect(True)
        self.preview_window.configure(bg='black', highlightbackground='gray', highlightthickness=1)

        # Position window
        self.preview_window.geometry(f"+{x + 10}+{y + 10}")

        # Create content frame
        content_frame = tk.Frame(self.preview_window, bg='black', padx=10, pady=10)
        content_frame.pack()

        # Load and display thumbnail
        thumbnail_path = self.thumbnail_generator.get_thumbnail(video_path)
        if thumbnail_path and os.path.exists(thumbnail_path):
            try:
                image = Image.open(thumbnail_path)
                photo = ImageTk.PhotoImage(image)

                thumbnail_label = tk.Label(content_frame, image=photo, bg='black')
                thumbnail_label.image = photo  # Keep a reference
                thumbnail_label.pack()
            except Exception as e:
                print(f"Error loading thumbnail: {e}")
                # Fallback to text
                tk.Label(content_frame, text="No Preview", fg='white', bg='black').pack()
        else:
            tk.Label(content_frame, text="Generating Preview...", fg='white', bg='black').pack()

        # Load and display metadata
        metadata = self.metadata_extractor.extract_metadata(video_path)

        info_frame = tk.Frame(content_frame, bg='black')
        info_frame.pack(pady=(10, 0))

        # File name
        filename = os.path.basename(video_path)
        if len(filename) > 30:
            filename = filename[:27] + "..."
        tk.Label(info_frame, text=filename, fg='white', bg='black', font=('Arial', 9, 'bold')).pack()

        # Duration and size
        duration_str = self.metadata_extractor.format_duration(metadata.get('duration', 0))
        size_str = self.metadata_extractor.format_file_size(metadata.get('file_size', 0))
        tk.Label(info_frame, text=f"{duration_str} • {size_str}", fg='lightgray', bg='black').pack()

        # Resolution and codec
        resolution = f"{metadata.get('width', 0)}×{metadata.get('height', 0)}"
        codec = metadata.get('codec', 'unknown')
        tk.Label(info_frame, text=f"{resolution} • {codec}", fg='lightgray', bg='black').pack()

        # Lift window to top
        self.preview_window.lift()

        # Generate thumbnail in background if needed
        if not thumbnail_path:
            threading.Thread(target=self._generate_thumbnail_async, args=(video_path,), daemon=True).start()

    def _generate_thumbnail_async(self, video_path: str):
        """Generate thumbnail asynchronously and update preview"""
        thumbnail_path = self.thumbnail_generator.generate_thumbnail(video_path)
        if thumbnail_path and self.current_video == video_path and self.preview_window:
            # Update the preview window with the new thumbnail
            try:
                def update_thumbnail():
                    if self.preview_window and self.current_video == video_path:
                        # Find and update the thumbnail label
                        for widget in self.preview_window.winfo_children():
                            if isinstance(widget, tk.Frame):
                                for child in widget.winfo_children():
                                    if isinstance(child, tk.Label) and hasattr(child, 'image'):
                                        try:
                                            image = Image.open(thumbnail_path)
                                            photo = ImageTk.PhotoImage(image)
                                            child.configure(image=photo)
                                            child.image = photo
                                        except Exception:
                                            pass
                                        break
                                break

                self.parent.after(0, update_thumbnail)
            except Exception as e:
                print(f"Error updating thumbnail: {e}")

    def hide_preview(self):
        """Hide preview window"""
        if self.preview_window:
            self.preview_window.destroy()
            self.preview_window = None
            self.current_video = None


class WatchHistory:
    """Track and manage video watch history"""

    def __init__(self):
        self.history_file = Path.home() / "Documents" / "Recursive Media Player" / "watch_history.json"
        self.history_data = []
        self.max_history_entries = 500  # Limit history size
        self.load_history()

    def add_watch_entry(self, video_path: str, watch_duration: float = None, completed: bool = False):
        """Add a watch history entry"""
        entry = {
            'video_path': os.path.abspath(video_path),
            'timestamp': datetime.now().isoformat(),
            'watch_duration': watch_duration,
            'completed': completed
        }

        # Remove existing entry for same video (keep most recent)
        self.history_data = [h for h in self.history_data if h['video_path'] != entry['video_path']]

        # Add new entry at beginning
        self.history_data.insert(0, entry)

        # Limit history size
        if len(self.history_data) > self.max_history_entries:
            self.history_data = self.history_data[:self.max_history_entries]

        self.save_history()

    def get_recent_videos(self, limit: int = 20) -> List[Dict]:
        """Get recently watched videos"""
        return self.history_data[:limit]

    def get_watch_count(self, video_path: str) -> int:
        """Get how many times a video was watched"""
        abs_path = os.path.abspath(video_path)
        return len([h for h in self.history_data if h['video_path'] == abs_path])

    def clear_history(self):
        """Clear all watch history"""
        self.history_data = []
        self.save_history()

    def load_history(self):
        """Load watch history from file"""
        try:
            if self.history_file.exists():
                with open(self.history_file, 'r') as f:
                    self.history_data = json.load(f)
        except Exception as e:
            print(f"Error loading watch history: {e}")
            self.history_data = []

    def save_history(self):
        """Save watch history to file"""
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, 'w') as f:
                json.dump(self.history_data, f, indent=2)
        except Exception as e:
            print(f"Error saving watch history: {e}")


class PlaylistManager:
    """Enhanced playlist management with better features"""

    def __init__(self):
        self.playlists_dir = Path.home() / "Documents" / "Recursive Media Player" / "playlists"
        self.playlists_dir.mkdir(parents=True, exist_ok=True)
        self.playlists = {}
        self.load_playlists()

    def create_playlist(self, name: str, videos: List[str] = None, description: str = "") -> bool:
        """Create a new playlist with optional description"""
        if name in self.playlists:
            return False

        self.playlists[name] = {
            'name': name,
            'description': description,
            'videos': videos or [],
            'created_date': datetime.now().isoformat(),
            'modified_date': datetime.now().isoformat(),
            'play_count': 0,
            'total_duration': 0,
            'tags': []
        }

        # Calculate total duration if videos provided
        if videos:
            self._update_playlist_metadata(name)

        self.save_playlist(name)
        return True

    def duplicate_playlist(self, source_name: str, new_name: str) -> bool:
        """Duplicate an existing playlist"""
        if source_name not in self.playlists or new_name in self.playlists:
            return False

        source_playlist = self.playlists[source_name].copy()
        source_playlist['name'] = new_name
        source_playlist['created_date'] = datetime.now().isoformat()
        source_playlist['modified_date'] = datetime.now().isoformat()
        source_playlist['play_count'] = 0
        source_playlist['description'] = f"Copy of {source_name}"

        self.playlists[new_name] = source_playlist
        self.save_playlist(new_name)
        return True

    def update_playlist_info(self, name: str, description: str = None, tags: List[str] = None) -> bool:
        """Update playlist description and tags"""
        if name not in self.playlists:
            return False

        if description is not None:
            self.playlists[name]['description'] = description
        if tags is not None:
            self.playlists[name]['tags'] = tags

        self.playlists[name]['modified_date'] = datetime.now().isoformat()
        self.save_playlist(name)
        return True

    def add_videos_to_playlist(self, playlist_name: str, videos: List[str]) -> bool:
        """Add videos to existing playlist"""
        if playlist_name not in self.playlists:
            return False

        playlist = self.playlists[playlist_name]
        added_count = 0

        for video in videos:
            if video not in playlist['videos']:
                playlist['videos'].append(video)
                added_count += 1

        if added_count > 0:
            playlist['modified_date'] = datetime.now().isoformat()
            self._update_playlist_metadata(playlist_name)
            self.save_playlist(playlist_name)

        return added_count > 0

    def remove_videos_from_playlist(self, playlist_name: str, video_indices: List[int]) -> bool:
        """Remove videos by indices from playlist"""
        if playlist_name not in self.playlists:
            return False

        playlist = self.playlists[playlist_name]
        # Sort indices in reverse to avoid index shifting issues
        for index in sorted(video_indices, reverse=True):
            if 0 <= index < len(playlist['videos']):
                playlist['videos'].pop(index)

        playlist['modified_date'] = datetime.now().isoformat()
        self._update_playlist_metadata(playlist_name)
        self.save_playlist(playlist_name)
        return True

    def reorder_playlist(self, playlist_name: str, old_index: int, new_index: int) -> bool:
        """Reorder videos in playlist"""
        if playlist_name not in self.playlists:
            return False

        playlist = self.playlists[playlist_name]
        videos = playlist['videos']

        if not (0 <= old_index < len(videos) and 0 <= new_index < len(videos)):
            return False

        # Move video to new position
        video = videos.pop(old_index)
        videos.insert(new_index, video)

        playlist['modified_date'] = datetime.now().isoformat()
        self.save_playlist(playlist_name)
        return True

    def increment_play_count(self, playlist_name: str):
        """Increment playlist play count"""
        if playlist_name in self.playlists:
            self.playlists[playlist_name]['play_count'] += 1
            self.playlists[playlist_name]['modified_date'] = datetime.now().isoformat()
            self.save_playlist(playlist_name)

    def get_playlist_stats(self, playlist_name: str) -> Dict:
        """Get detailed playlist statistics"""
        if playlist_name not in self.playlists:
            return {}

        playlist = self.playlists[playlist_name]
        existing_videos = [v for v in playlist['videos'] if os.path.exists(v)]
        missing_count = len(playlist['videos']) - len(existing_videos)

        return {
            'total_videos': len(playlist['videos']),
            'existing_videos': len(existing_videos),
            'missing_videos': missing_count,
            'total_duration': playlist.get('total_duration', 0),
            'play_count': playlist.get('play_count', 0),
            'created_date': playlist.get('created_date', ''),
            'modified_date': playlist.get('modified_date', ''),
            'size_mb': sum(os.path.getsize(v) for v in existing_videos if os.path.exists(v)) / (1024 * 1024)
        }

    def search_playlists(self, query: str) -> List[str]:
        """Search playlists by name, description, or tags"""
        query = query.lower()
        matches = []

        for name, playlist in self.playlists.items():
            if (query in name.lower() or
                    query in playlist.get('description', '').lower() or
                    any(query in tag.lower() for tag in playlist.get('tags', []))):
                matches.append(name)

        return matches

    def _update_playlist_metadata(self, playlist_name: str):
        """Update playlist duration and other metadata"""
        if playlist_name not in self.playlists:
            return

        playlist = self.playlists[playlist_name]
        total_duration = 0

        # Calculate total duration (simplified - would need video metadata in practice)
        for video in playlist['videos']:
            if os.path.exists(video):
                try:
                    import cv2
                    cap = cv2.VideoCapture(video)
                    if cap.isOpened():
                        fps = cap.get(cv2.CAP_PROP_FPS) or 25
                        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                        if fps > 0:
                            total_duration += frame_count / fps
                        cap.release()
                except:
                    pass

        playlist['total_duration'] = total_duration

    def export_playlist(self, playlist_name: str, export_path: str, format: str = "m3u") -> bool:
        """Export playlist to various formats"""
        if playlist_name not in self.playlists:
            return False

        playlist = self.playlists[playlist_name]

        try:
            with open(export_path, 'w', encoding='utf-8') as f:
                if format == "m3u":
                    f.write("#EXTM3U\n")
                    f.write(f"#PLAYLIST:{playlist_name}\n")
                    for video in playlist['videos']:
                        if os.path.exists(video):
                            f.write(f"#EXTINF:-1,{os.path.basename(video)}\n")
                            f.write(f"{video}\n")
                elif format == "txt":
                    f.write(f"# Playlist: {playlist_name}\n")
                    f.write(f"# Description: {playlist.get('description', '')}\n")
                    f.write(f"# Created: {playlist.get('created_date', '')}\n\n")
                    for video in playlist['videos']:
                        f.write(f"{video}\n")
            return True
        except Exception as e:
            print(f"Error exporting playlist: {e}")
            return False

    # Keep existing methods (delete_playlist, get_playlist, etc.)
    def delete_playlist(self, name: str) -> bool:
        if name not in self.playlists:
            return False
        del self.playlists[name]
        playlist_file = self.playlists_dir / f"{name}.json"
        try:
            if playlist_file.exists():
                playlist_file.unlink()
        except Exception as e:
            print(f"Error deleting playlist file: {e}")
        return True

    def get_playlist(self, name: str) -> Optional[Dict]:
        return self.playlists.get(name)

    def get_all_playlists(self) -> Dict[str, Dict]:
        return self.playlists.copy()

    def save_playlist(self, name: str):
        if name not in self.playlists:
            return
        playlist_file = self.playlists_dir / f"{name}.json"
        try:
            with open(playlist_file, 'w') as f:
                json.dump(self.playlists[name], f, indent=2)
        except Exception as e:
            print(f"Error saving playlist {name}: {e}")

    def load_playlists(self):
        try:
            for playlist_file in self.playlists_dir.glob("*.json"):
                try:
                    with open(playlist_file, 'r') as f:
                        playlist = json.load(f)
                        self.playlists[playlist['name']] = playlist
                except Exception as e:
                    print(f"Error loading playlist {playlist_file}: {e}")
        except Exception as e:
            print(f"Error loading playlists: {e}")


class EnhancedPlaylistDialog:
    """Advanced playlist creation and selection dialog"""

    def __init__(self, parent, playlist_manager: PlaylistManager):
        self.parent = parent
        self.playlist_manager = playlist_manager
        self.result = None

    def show_create_playlist_dialog(self, videos: List[str] = None) -> Optional[str]:
        """Show create new playlist dialog"""
        dialog = tk.Toplevel(self.parent)
        dialog.title("Create New Playlist")
        dialog.geometry("500x400")
        dialog.transient(self.parent)
        dialog.grab_set()

        # Center dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (250)
        y = (dialog.winfo_screenheight() // 2) - (200)
        dialog.geometry(f"+{x}+{y}")

        main_frame = tk.Frame(dialog, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header
        tk.Label(main_frame, text="Create New Playlist",
                 font=('Arial', 14, 'bold')).pack(pady=(0, 20))

        # Playlist name
        tk.Label(main_frame, text="Playlist Name:").pack(anchor='w')
        name_entry = tk.Entry(main_frame, font=('Arial', 11))
        name_entry.pack(fill=tk.X, pady=(5, 15))
        name_entry.focus()

        # Description
        tk.Label(main_frame, text="Description (optional):").pack(anchor='w')
        desc_text = tk.Text(main_frame, height=3, font=('Arial', 10))
        desc_text.pack(fill=tk.X, pady=(5, 15))

        # Tags
        tk.Label(main_frame, text="Tags (comma-separated):").pack(anchor='w')
        tags_entry = tk.Entry(main_frame, font=('Arial', 10))
        tags_entry.pack(fill=tk.X, pady=(5, 15))

        # Video count info
        if videos:
            tk.Label(main_frame, text=f"Will add {len(videos)} video(s) to this playlist",
                     fg='gray').pack(pady=(0, 15))

        # Buttons
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(20, 0))

        def create_playlist():
            name = name_entry.get().strip()
            if not name:
                tk.messagebox.showwarning("Warning", "Please enter a playlist name")
                return

            description = desc_text.get(1.0, tk.END).strip()
            tags = [tag.strip() for tag in tags_entry.get().split(',') if tag.strip()]

            if self.playlist_manager.create_playlist(name, videos or [], description):
                if tags:
                    self.playlist_manager.update_playlist_info(name, tags=tags)
                self.result = name
                dialog.destroy()
            else:
                tk.messagebox.showerror("Error", "Playlist name already exists!")

        tk.Button(button_frame, text="Create", command=create_playlist,
                  bg='#4CAF50', fg='white', padx=20).pack(side=tk.RIGHT)
        tk.Button(button_frame, text="Cancel", command=dialog.destroy,
                  padx=20).pack(side=tk.RIGHT, padx=(0, 10))

        # Handle Enter key
        def on_enter(event):
            create_playlist()

        dialog.bind('<Return>', on_enter)
        dialog.wait_window()
        return self.result

    def show_playlist_selection(self, videos: List[str]) -> Optional[str]:
        """Show playlist selection dialog with enhanced features"""
        dialog = tk.Toplevel(self.parent)
        dialog.title("Add to Playlist")
        dialog.geometry("600x500")
        dialog.transient(self.parent)
        dialog.grab_set()

        # Center dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (300)
        y = (dialog.winfo_screenheight() // 2) - (250)
        dialog.geometry(f"+{x}+{y}")

        main_frame = tk.Frame(dialog, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text=f"Add {len(videos)} video(s) to playlist",
                 font=('Arial', 12, 'bold')).pack(anchor='w', pady=(0, 20))

        # Search frame
        search_frame = tk.Frame(main_frame)
        search_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(search_frame, text="Search:").pack(side=tk.LEFT)
        search_entry = tk.Entry(search_frame, font=('Arial', 10))
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))

        # Playlist list with details
        list_frame = tk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        # Create Treeview for better display
        columns = ('Name', 'Videos', 'Duration', 'Created')
        tree = ttk.Treeview(list_frame, columns=columns, show='tree headings', height=12)

        # Configure columns
        tree.heading('#0', text='', anchor='w')
        tree.column('#0', width=20, minwidth=20)
        tree.heading('Name', text='Playlist Name')
        tree.column('Name', width=200, minwidth=150)
        tree.heading('Videos', text='Videos')
        tree.column('Videos', width=80, minwidth=60)
        tree.heading('Duration', text='Duration')
        tree.column('Duration', width=100, minwidth=80)
        tree.heading('Created', text='Created')
        tree.column('Created', width=100, minwidth=80)

        # Scrollbar
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def populate_tree(filter_text=""):
            tree.delete(*tree.get_children())
            playlists = self.playlist_manager.get_all_playlists()

            for name in sorted(playlists.keys()):
                if filter_text.lower() in name.lower():
                    playlist = playlists[name]
                    stats = self.playlist_manager.get_playlist_stats(name)

                    duration_str = f"{stats['total_duration'] // 3600:.0f}h {(stats['total_duration'] % 3600) // 60:.0f}m" if \
                    stats['total_duration'] > 0 else "Unknown"
                    created_date = playlist.get('created_date', '')[:10]

                    tree.insert('', 'end', values=(
                        name,
                        f"{stats['existing_videos']}/{stats['total_videos']}",
                        duration_str,
                        created_date
                    ))

        def on_search(*args):
            populate_tree(search_entry.get())

        search_entry.bind('<KeyRelease>', on_search)
        populate_tree()

        # New playlist section
        new_playlist_frame = tk.Frame(main_frame)
        new_playlist_frame.pack(fill=tk.X, pady=(20, 0))

        tk.Label(new_playlist_frame, text="Or create new playlist:").pack(anchor='w')
        new_name_frame = tk.Frame(new_playlist_frame)
        new_name_frame.pack(fill=tk.X, pady=(5, 0))

        new_playlist_entry = tk.Entry(new_name_frame)
        new_playlist_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        create_new_btn = tk.Button(new_name_frame, text="Create & Add",
                                   command=lambda: create_new_playlist())
        create_new_btn.pack(side=tk.RIGHT, padx=(10, 0))

        # Buttons
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(20, 0))

        def add_to_selected():
            selection = tree.selection()
            if selection:
                item = tree.item(selection[0])
                playlist_name = item['values'][0]
                if self.playlist_manager.add_videos_to_playlist(playlist_name, videos):
                    self.result = playlist_name
                    dialog.destroy()
                else:
                    tk.messagebox.showerror("Error", "Failed to add videos to playlist!")
            else:
                tk.messagebox.showwarning("Warning", "Please select a playlist!")

        def create_new_playlist():
            name = new_playlist_entry.get().strip()
            if name:
                if self.playlist_manager.create_playlist(name, videos):
                    self.result = name
                    dialog.destroy()
                else:
                    tk.messagebox.showerror("Error", "Playlist already exists!")
            else:
                tk.messagebox.showwarning("Warning", "Please enter a playlist name!")

        tk.Button(button_frame, text="Add to Selected", command=add_to_selected,
                  bg='#4CAF50', fg='white', padx=20).pack(side=tk.RIGHT)
        tk.Button(button_frame, text="Cancel", command=dialog.destroy,
                  padx=20).pack(side=tk.RIGHT, padx=(0, 10))

        dialog.wait_window()
        return self.result