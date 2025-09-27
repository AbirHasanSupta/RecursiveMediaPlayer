"""
Enhanced Video Player Features
- Playlist Management
- Resume Playback
- Thumbnail Generation
- Preview Window
- Metadata Extraction
"""

import os
import json
import cv2
import threading
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import base64
from PIL import Image, ImageTk
import subprocess
import time
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


class PlaylistManager:
    """Manage video playlists"""

    def __init__(self):
        self.playlists_dir = Path.home() / "Documents" / "Recursive Media Player" / "playlists"
        self.playlists_dir.mkdir(parents=True, exist_ok=True)
        self.playlists = {}
        self.load_playlists()

    def create_playlist(self, name: str, videos: List[str] = None) -> bool:
        """Create a new playlist"""
        if name in self.playlists:
            return False

        self.playlists[name] = {
            'name': name,
            'videos': videos or [],
            'created_date': datetime.now().isoformat(),
            'modified_date': datetime.now().isoformat()
        }
        self.save_playlist(name)
        return True

    def add_videos_to_playlist(self, playlist_name: str, videos: List[str]) -> bool:
        """Add videos to existing playlist"""
        if playlist_name not in self.playlists:
            return False

        playlist = self.playlists[playlist_name]
        for video in videos:
            if video not in playlist['videos']:
                playlist['videos'].append(video)

        playlist['modified_date'] = datetime.now().isoformat()
        self.save_playlist(playlist_name)
        return True

    def remove_videos_from_playlist(self, playlist_name: str, videos: List[str]) -> bool:
        """Remove videos from playlist"""
        if playlist_name not in self.playlists:
            return False

        playlist = self.playlists[playlist_name]
        playlist['videos'] = [v for v in playlist['videos'] if v not in videos]
        playlist['modified_date'] = datetime.now().isoformat()
        self.save_playlist(playlist_name)
        return True

    def delete_playlist(self, name: str) -> bool:
        """Delete a playlist"""
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
        """Get playlist by name"""
        return self.playlists.get(name)

    def get_all_playlists(self) -> Dict[str, Dict]:
        """Get all playlists"""
        return self.playlists.copy()

    def save_playlist(self, name: str):
        """Save playlist to file"""
        if name not in self.playlists:
            return

        playlist_file = self.playlists_dir / f"{name}.json"
        try:
            with open(playlist_file, 'w') as f:
                json.dump(self.playlists[name], f, indent=2)
        except Exception as e:
            print(f"Error saving playlist {name}: {e}")

    def load_playlists(self):
        """Load all playlists from files"""
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


class PlaylistDialog:
    """Dialog for managing playlists"""

    def __init__(self, parent, playlist_manager: PlaylistManager):
        self.parent = parent
        self.playlist_manager = playlist_manager
        self.result = None

    def show_playlist_selection(self, videos: List[str]) -> Optional[str]:
        """Show dialog to select playlist for adding videos"""
        dialog = tk.Toplevel(self.parent)
        dialog.title("Add to Playlist")
        dialog.geometry("400x300")
        dialog.transient(self.parent)
        dialog.grab_set()

        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (400 // 2)
        y = (dialog.winfo_screenheight() // 2) - (300 // 2)
        dialog.geometry(f"+{x}+{y}")

        main_frame = tk.Frame(dialog, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text=f"Add {len(videos)} video(s) to playlist:",
                 font=('Arial', 12, 'bold')).pack(anchor='w', pady=(0, 10))

        # Playlist selection
        playlist_frame = tk.Frame(main_frame)
        playlist_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        tk.Label(playlist_frame, text="Select existing playlist:").pack(anchor='w')

        playlist_listbox = tk.Listbox(playlist_frame, height=8)
        playlist_listbox.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        # Populate with existing playlists
        playlists = self.playlist_manager.get_all_playlists()
        for name in sorted(playlists.keys()):
            playlist = playlists[name]
            video_count = len(playlist.get('videos', []))
            playlist_listbox.insert(tk.END, f"{name} ({video_count} videos)")

        # New playlist entry
        new_playlist_frame = tk.Frame(main_frame)
        new_playlist_frame.pack(fill=tk.X, pady=(10, 0))

        tk.Label(new_playlist_frame, text="Or create new playlist:").pack(anchor='w')
        new_playlist_entry = tk.Entry(new_playlist_frame)
        new_playlist_entry.pack(fill=tk.X, pady=(5, 0))

        # Buttons
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(20, 0))

        def on_add():
            # Check if new playlist name is provided
            new_name = new_playlist_entry.get().strip()
            if new_name:
                if self.playlist_manager.create_playlist(new_name, videos):
                    self.result = new_name
                    dialog.destroy()
                else:
                    messagebox.showerror("Error", "Playlist already exists!")
                return

            # Check if existing playlist is selected
            selection = playlist_listbox.curselection()
            if selection:
                selected_text = playlist_listbox.get(selection[0])
                playlist_name = selected_text.split(' (')[0]  # Extract name before count
                if self.playlist_manager.add_videos_to_playlist(playlist_name, videos):
                    self.result = playlist_name
                    dialog.destroy()
                else:
                    messagebox.showerror("Error", "Failed to add videos to playlist!")
                return

            messagebox.showwarning("Warning", "Please select a playlist or enter a new name!")

        def on_cancel():
            dialog.destroy()

        tk.Button(button_frame, text="Add", command=on_add, bg='#4CAF50', fg='white').pack(side=tk.RIGHT, padx=(10, 0))
        tk.Button(button_frame, text="Cancel", command=on_cancel).pack(side=tk.RIGHT)

        dialog.wait_window()
        return self.result


# Integration helper functions for the main application

def integrate_enhanced_features():
    """
    Integration guide for adding these features to the main application:

    1. Add these imports to exe_app.py:
       from enhanced_features import (
           VideoMetadata, ThumbnailGenerator, PlaylistManager,
           ResumePlaybackManager, PreviewWindow, PlaylistDialog
       )

    2. Initialize in DirectorySelector.__init__():
       self.video_metadata = VideoMetadata()
       self.thumbnail_generator = ThumbnailGenerator()
       self.playlist_manager = PlaylistManager()
       self.resume_manager = ResumePlaybackManager()
       self.preview_window = PreviewWindow(self.root, self.thumbnail_generator, self.video_metadata)

    3. Add playlist management buttons to UI:
       - "Create Playlist" button
       - "Add to Playlist" button (when videos are selected)
       - "Manage Playlists" button

    4. Modify video listing to show thumbnails and metadata

    5. Add hover events for preview window

    6. Integrate resume playback in VLC controller

    Example integration code snippets are provided below.
    """
    pass


# Example integration snippets:

def add_playlist_buttons_to_ui(self):
    """Add to DirectorySelector.setup_exclusion_section()"""

    # Add after existing buttons
    playlist_buttons_row = tk.Frame(self.exclusion_section, bg=self.bg_color)
    playlist_buttons_row.pack(fill=tk.X, pady=(10, 0))

    self.create_playlist_button = self.create_button(
        playlist_buttons_row,
        text="Create Playlist",
        command=self.create_playlist_from_selection,
        variant="success",
        size="sm"
    )
    self.create_playlist_button.pack(side=tk.LEFT, padx=(0, 5))

    self.manage_playlists_button = self.create_button(
        playlist_buttons_row,
        text="Manage Playlists",
        command=self.show_playlist_manager,
        variant="primary",
        size="sm"
    )
    self.manage_playlists_button.pack(side=tk.LEFT)


def create_playlist_from_selection(self):
    """Create playlist from selected videos in AI search results"""
    if not self.ai_mode or not self.current_subdirs_mapping:
        messagebox.showinfo("Info", "Please perform an AI search first")
        return

    selection = self.exclusion_listbox.curselection()
    if not selection:
        messagebox.showinfo("Info", "Please select videos to add to playlist")
        return

    selected_videos = []
    for index in selection:
        if index in self.current_subdirs_mapping:
            video_path = self.current_subdirs_mapping[index]
            if os.path.isfile(video_path):
                selected_videos.append(video_path)

    if not selected_videos:
        messagebox.showinfo("Info", "No valid videos selected")
        return

    dialog = PlaylistDialog(self.root, self.playlist_manager)
    result = dialog.show_playlist_selection(selected_videos)

    if result:
        self.update_console(f"Added {len(selected_videos)} videos to playlist '{result}'")


def add_preview_hover_events(self):
    """Add to DirectorySelector.setup_exclusion_section()"""

    def on_listbox_motion(event):
        index = self.exclusion_listbox.nearest(event.y)
        if index in self.current_subdirs_mapping:
            video_path = self.current_subdirs_mapping[index]
            if os.path.isfile(video_path):
                x = self.exclusion_listbox.winfo_rootx() + event.x
                y = self.exclusion_listbox.winfo_rooty() + event.y
                self.preview_window.show_preview(video_path, x, y)

    def on_listbox_leave(event):
        self.preview_window.hide_preview()

    self.exclusion_listbox.bind('<Motion>', on_listbox_motion)
    self.exclusion_listbox.bind('<Leave>', on_listbox_leave)


def integrate_resume_playback_in_vlc(self):
    """Add to VLCPlayerController.play_video()"""

    # After setting media and before playing:
    resume_position = self.resume_manager.get_resume_position(video_path)
    if resume_position:
        # Show resume dialog
        result = messagebox.askyesno(
            "Resume Playback",
            f"Resume from {self.format_time(resume_position)}?",
            default='yes'
        )
        if result:
            # Set position after video starts playing
            def set_resume_position():
                time.sleep(1)  # Wait for video to load
                if self.player.is_playing():
                    self.player.set_time(int(resume_position * 1000))

            threading.Thread(target=set_resume_position, daemon=True).start()
        else:
            self.resume_manager.clear_resume_position(video_path)

    # Add periodic position saving
    def save_position_periodically():
        while self.running and self.player.is_playing():
            current_time = self.player.get_time() / 1000.0  # Convert to seconds
            duration = self.player.get_length() / 1000.0
            if current_time > 10:  # Only save after 10 seconds
                self.resume_manager.save_position(video_path, current_time, duration)
            time.sleep(10)  # Save every 10 seconds

    threading.Thread(target=save_position_periodically, daemon=True).start()