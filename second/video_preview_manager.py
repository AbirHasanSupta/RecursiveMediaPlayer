import os
import threading
import tkinter as tk
from tkinter import ttk
from pathlib import Path
import cv2
import base64
import json
import hashlib
import time
from typing import Dict, Optional, Callable
from PIL import Image, ImageTk
import tempfile


class VideoThumbnail:
    """Data class for video thumbnail information"""

    def __init__(self, video_path: str, thumbnail_data: str = None, timestamp: float = None):
        self.video_path = os.path.normpath(video_path)
        self.thumbnail_data = thumbnail_data  # base64 encoded image
        self.timestamp = timestamp or time.time()
        self.file_hash = self._calculate_file_hash()

    def _calculate_file_hash(self) -> str:
        """Calculate a hash of the video file for cache validation"""
        try:
            # Use file path and modification time for hash
            stat = os.stat(self.video_path)
            hash_input = f"{self.video_path}_{stat.st_size}_{stat.st_mtime}"
            return hashlib.md5(hash_input.encode()).hexdigest()
        except:
            return hashlib.md5(self.video_path.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            'video_path': self.video_path,
            'thumbnail_data': self.thumbnail_data,
            'timestamp': self.timestamp,
            'file_hash': self.file_hash
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'VideoThumbnail':
        thumbnail = cls(data.get('video_path', ''))
        thumbnail.thumbnail_data = data.get('thumbnail_data')
        thumbnail.timestamp = data.get('timestamp', time.time())
        thumbnail.file_hash = data.get('file_hash', '')
        return thumbnail

    def is_valid(self) -> bool:
        """Check if thumbnail is still valid for the video file"""
        try:
            return self.file_hash == self._calculate_file_hash()
        except:
            return False


class ThumbnailStorage:
    """Handles thumbnail persistence with base64 encoding"""

    def __init__(self):
        self.thumbnails_dir = Path.home() / "Documents" / "Recursive Media Player" / "Thumbnails"
        self.thumbnails_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnails_file = self.thumbnails_dir / "thumbnails_cache.json"
        self.max_cache_size = 1000  # Limit number of cached thumbnails

    def save_thumbnails(self, thumbnails: Dict[str, VideoThumbnail]) -> bool:
        try:
            # Keep only the most recent thumbnails
            sorted_thumbnails = sorted(
                thumbnails.values(),
                key=lambda x: x.timestamp,
                reverse=True
            )[:self.max_cache_size]

            data = {thumb.video_path: thumb.to_dict() for thumb in sorted_thumbnails}

            with open(self.thumbnails_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving thumbnails: {e}")
            return False

    def load_thumbnails(self) -> Dict[str, VideoThumbnail]:
        try:
            if not self.thumbnails_file.exists():
                return {}

            with open(self.thumbnails_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            thumbnails = {}
            for video_path, thumb_data in data.items():
                thumbnail = VideoThumbnail.from_dict(thumb_data)
                if thumbnail.is_valid():  # Only load valid thumbnails
                    thumbnails[video_path] = thumbnail

            return thumbnails
        except Exception as e:
            print(f"Error loading thumbnails: {e}")
            return {}


class ThumbnailGenerator:
    """Generates video thumbnails using OpenCV"""

    def __init__(self):
        self.thumbnail_size = (180, 320)  # 16:9 aspect ratio
        self.quality = 85

    def generate_thumbnail(self, video_path: str) -> Optional[str]:
        """Generate thumbnail and return as base64 string"""
        try:
            # Open video
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return None

            # Get video properties
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 25

            # Seek to 10% into the video, or frame 30 (whichever is later)
            target_frame = max(30, int(total_frames * 0.1))
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

            # Read frame
            ret, frame = cap.read()
            cap.release()

            if not ret or frame is None:
                return None

            # Resize frame
            frame_resized = cv2.resize(frame, self.thumbnail_size)

            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)

            # Convert to PIL Image
            pil_image = Image.fromarray(frame_rgb)

            # Save to temporary file to get base64
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
                pil_image.save(temp_file.name, 'JPEG', quality=self.quality)
                temp_path = temp_file.name

            # Read file and encode to base64
            try:
                with open(temp_path, 'rb') as f:
                    image_data = f.read()
                base64_data = base64.b64encode(image_data).decode('utf-8')

                # Clean up temp file
                os.unlink(temp_path)

                return base64_data
            except Exception:
                # Clean up temp file on error
                try:
                    os.unlink(temp_path)
                except:
                    pass
                return None

        except Exception as e:
            print(f"Error generating thumbnail for {video_path}: {e}")
            return None


class VideoPreviewTooltip:
    """Tooltip widget that shows video thumbnails"""

    def __init__(self, parent):
        self.parent = parent
        self.tooltip_window = None
        self.is_visible = False

    def show_preview(self, video_path: str, thumbnail_data: str, x: int, y: int):
        """Show preview tooltip at specified coordinates"""
        if self.tooltip_window:
            self.hide_preview()

        try:
            # Decode base64 image
            image_data = base64.b64decode(thumbnail_data)

            # Create temporary file
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as temp_file:
                temp_file.write(image_data)
                temp_path = temp_file.name

            # Load image with PIL
            pil_image = Image.open(temp_path)
            photo = ImageTk.PhotoImage(pil_image)

            # Create tooltip window
            self.tooltip_window = tk.Toplevel(self.parent)
            self.tooltip_window.wm_overrideredirect(True)
            self.tooltip_window.configure(bg='black', relief='solid', bd=1)

            # Position tooltip
            screen_width = self.parent.winfo_screenwidth()
            screen_height = self.parent.winfo_screenheight()

            # Adjust position to keep tooltip on screen
            tooltip_width = pil_image.width + 20
            tooltip_height = pil_image.height + 40

            if x + tooltip_width > screen_width:
                x = screen_width - tooltip_width - 10
            if y + tooltip_height > screen_height:
                y = y - tooltip_height - 10

            self.tooltip_window.geometry(f"+{x + 10}+{y + 10}")

            # Create content frame
            content_frame = tk.Frame(self.tooltip_window, bg='black', padx=5, pady=5)
            content_frame.pack()

            # Add image
            image_label = tk.Label(content_frame, image=photo, bg='black')
            image_label.image = photo  # Keep a reference
            image_label.pack()

            # Add video name
            video_name = os.path.basename(video_path)
            if len(video_name) > 40:
                video_name = video_name[:37] + "..."

            name_label = tk.Label(
                content_frame,
                text=video_name,
                bg='black',
                fg='white',
                font=('Arial', 9),
                wraplength=320
            )
            name_label.pack(pady=(5, 0))

            self.is_visible = True

            # Clean up temp file
            try:
                os.unlink(temp_path)
            except:
                pass

        except Exception as e:
            print(f"Error showing preview: {e}")
            self.hide_preview()

    def hide_preview(self):
        """Hide the preview tooltip"""
        if self.tooltip_window:
            try:
                self.tooltip_window.destroy()
            except:
                pass
            self.tooltip_window = None
        self.is_visible = False


class VideoPreviewManager:
    """Main manager for video preview functionality"""

    def __init__(self, parent, console_callback: Callable = None):
        self.parent = parent
        self.console_callback = console_callback

        self.storage = ThumbnailStorage()
        self.generator = ThumbnailGenerator()
        self.tooltip = VideoPreviewTooltip(parent)

        self._thumbnails: Dict[str, VideoThumbnail] = {}
        self._generation_queue = set()
        self._lock = threading.Lock()

        # Load cached thumbnails
        self._load_thumbnails()

        # Current preview state
        self.current_listbox = None
        self.current_mapping = None
        self.right_clicked_item = None

    def _load_thumbnails(self):
        """Load cached thumbnails"""
        self._thumbnails = self.storage.load_thumbnails()
        if self.console_callback:
            self.console_callback(f"Loaded {len(self._thumbnails)} cached video thumbnails")

    def _save_thumbnails(self):
        """Save thumbnails to cache"""
        with self._lock:
            self.storage.save_thumbnails(self._thumbnails)

    def attach_to_listbox(self, listbox: tk.Listbox, video_mapping: Dict[int, str]):
        """Attach preview functionality to a listbox"""
        self.current_listbox = listbox
        self.current_mapping = video_mapping

        # Bind events
        listbox.bind("<Button-3>", self._on_right_click)  # Right click
        listbox.bind("<Motion>", self._on_mouse_motion)  # Mouse motion
        listbox.bind("<Leave>", self._on_mouse_leave)  # Mouse leaves listbox

    def detach_from_listbox(self, listbox: tk.Listbox):
        """Detach preview functionality from a listbox"""
        try:
            listbox.unbind("<Button-3>")
            listbox.unbind("<Motion>")
            listbox.unbind("<Leave>")
        except:
            pass

        if self.current_listbox == listbox:
            self.current_listbox = None
            self.current_mapping = None

        self.tooltip.hide_preview()

    def _on_right_click(self, event):
        """Handle right click on listbox item"""
        if not self.current_mapping:
            return

        # Get clicked item
        listbox = event.widget
        index = listbox.nearest(event.y)

        if index < 0 or index >= listbox.size():
            return

        # Get video path from mapping
        video_path = self.current_mapping.get(index)
        if not video_path or not os.path.isfile(video_path):
            return

        # Store the right-clicked item
        self.right_clicked_item = index

        # Show preview
        self._show_video_preview(video_path, event.x_root, event.y_root)

    def _on_mouse_motion(self, event):
        """Handle mouse motion over listbox"""
        if not self.tooltip.is_visible:
            return

        # Check if mouse moved to a different item
        listbox = event.widget
        current_index = listbox.nearest(event.y)

        if current_index != self.right_clicked_item:
            self.tooltip.hide_preview()
            self.right_clicked_item = None

    def _on_mouse_leave(self, event):
        """Handle mouse leaving the listbox"""
        self.tooltip.hide_preview()
        self.right_clicked_item = None

    def _show_video_preview(self, video_path: str, x: int, y: int):
        """Show video preview at specified coordinates"""
        video_path_norm = os.path.normpath(video_path)

        # Check if thumbnail exists in cache
        if video_path_norm in self._thumbnails:
            thumbnail = self._thumbnails[video_path_norm]
            if thumbnail.is_valid() and thumbnail.thumbnail_data:
                self.tooltip.show_preview(video_path, thumbnail.thumbnail_data, x, y)
                return

        # Generate thumbnail if not in cache
        if video_path_norm not in self._generation_queue:
            self._generate_thumbnail_async(video_path_norm, x, y)

    def _generate_thumbnail_async(self, video_path: str, x: int, y: int):
        """Generate thumbnail in background thread"""
        with self._lock:
            if video_path in self._generation_queue:
                return
            self._generation_queue.add(video_path)

        def generate():
            try:
                thumbnail_data = self.generator.generate_thumbnail(video_path)

                if thumbnail_data:
                    thumbnail = VideoThumbnail(video_path, thumbnail_data)

                    with self._lock:
                        self._thumbnails[video_path] = thumbnail
                        self._generation_queue.discard(video_path)

                    self._save_thumbnails()

                    if (self.right_clicked_item is not None and
                            self.current_mapping and
                            self.current_mapping.get(self.right_clicked_item) == video_path):
                        def show_preview():
                            self.tooltip.show_preview(video_path, thumbnail_data, x, y)

                        self.parent.after(0, show_preview)

                else:
                    with self._lock:
                        self._generation_queue.discard(video_path)

                    if self.console_callback:
                        self.console_callback(f"Failed to generate thumbnail for {os.path.basename(video_path)}")

            except Exception as e:
                with self._lock:
                    self._generation_queue.discard(video_path)

                if self.console_callback:
                    self.console_callback(f"Error generating thumbnail: {e}")

        threading.Thread(target=generate, daemon=True).start()

    def pregenerate_thumbnails(self, video_paths: list, progress_callback: Callable = None):
        """Pre-generate thumbnails for a list of videos"""

        def pregenerate():
            total = len(video_paths)
            for i, video_path in enumerate(video_paths):
                if not os.path.isfile(video_path):
                    continue

                video_path_norm = os.path.normpath(video_path)

                # Skip if already exists and valid
                if (video_path_norm in self._thumbnails and
                        self._thumbnails[video_path_norm].is_valid()):
                    continue

                # Generate thumbnail
                thumbnail_data = self.generator.generate_thumbnail(video_path_norm)

                if thumbnail_data:
                    thumbnail = VideoThumbnail(video_path_norm, thumbnail_data)
                    with self._lock:
                        self._thumbnails[video_path_norm] = thumbnail

                # Update progress
                if progress_callback:
                    progress = ((i + 1) / total) * 100
                    self.parent.after(0, lambda p=progress: progress_callback(p))

            # Save all thumbnails
            self._save_thumbnails()

            if self.console_callback:
                generated_count = len([p for p in video_paths if os.path.normpath(p) in self._thumbnails])
                self.console_callback(f"Pre-generated {generated_count}/{total} video thumbnails")

        threading.Thread(target=pregenerate, daemon=True).start()

    def clear_cache(self):
        """Clear thumbnail cache"""
        with self._lock:
            self._thumbnails.clear()
        self._save_thumbnails()

        if self.console_callback:
            self.console_callback("Video thumbnail cache cleared")

    def get_cache_stats(self) -> Dict:
        """Get thumbnail cache statistics"""
        with self._lock:
            total_size = 0
            for thumbnail in self._thumbnails.values():
                if thumbnail.thumbnail_data:
                    total_size += len(thumbnail.thumbnail_data) * 3 // 4

            return {
                'total_thumbnails': len(self._thumbnails),
                'cache_size_mb': total_size / (1024 * 1024),
                'generation_queue_size': len(self._generation_queue)
            }