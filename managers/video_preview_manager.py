"""
VideoPreviewManager — fast binary thumbnail cache.

Key changes vs original:
- Thumbnails stored as raw JPEG/MP4 bytes on disk instead of base64-in-JSON.
  This eliminates the ~33 % size overhead and the encode/decode CPU cost.
- Index file is a lightweight pickle dict: { norm_path -> (filename, mtime, size) }
  No thumbnail data travels through JSON at all.
- VideoThumbnail no longer carries base64 strings; it carries a Path to the
  binary blob on disk (or None if not yet generated).
- _load_thumbnail / _display_thumbnail_from_data in grid_view_manager still
  receive the same "IMAGE:…" / "VIDEO:…" sentinel strings so the rest of the
  UI is unchanged — but we only build those strings *in memory* on demand, not
  on disk.
"""

import os
import hashlib
import threading
import time
import tempfile
from pathlib import Path
from typing import Dict, Optional, Callable

import cv2
import tkinter as tk
from PIL import Image, ImageTk
import pickle

from managers.resource_manager import get_resource_manager, ManagedThread


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _file_hash_key(video_path: str) -> str:
    """Cheap cache-validity key: path + size + mtime."""
    try:
        st = os.stat(video_path)
        raw = f"{video_path}_{st.st_size}_{st.st_mtime}"
    except OSError:
        raw = video_path
    return hashlib.md5(raw.encode()).hexdigest()


def _safe_unlink(path: str):
    try:
        os.unlink(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# VideoThumbnail
# ---------------------------------------------------------------------------

class VideoThumbnail:
    """
    Represents a cached thumbnail.  The actual bytes live in a binary file
    on disk; we hold a Path to that file plus the hash for validation.
    """

    def __init__(self, video_path: str, blob_path: Optional[Path] = None,
                 is_video: bool = False, hash_key: str = ""):
        self.video_path = os.path.normpath(video_path)
        self.blob_path: Optional[Path] = blob_path      # Path to raw JPEG or MP4
        self.is_video: bool = is_video                  # True → MP4, False → JPEG
        self.hash_key: str = hash_key or _file_hash_key(video_path)
        # Legacy compat: grid_view_manager may read .thumbnail_data
        # We provide it as a property that lazily builds the sentinel string.
        self._thumbnail_data_cache: Optional[str] = None

    # ------------------------------------------------------------------
    # Legacy compat: thumbnail_data as a sentinel string (built on demand)
    # ------------------------------------------------------------------
    @property
    def thumbnail_data(self) -> Optional[str]:
        """Return "IMAGE:<b64>" or "VIDEO:<b64>" only when explicitly read."""
        if self._thumbnail_data_cache is not None:
            return self._thumbnail_data_cache
        if self.blob_path is None or not self.blob_path.exists():
            return None
        try:
            import base64
            raw = self.blob_path.read_bytes()
            b64 = base64.b64encode(raw).decode("ascii")
            prefix = "VIDEO:" if self.is_video else "IMAGE:"
            self._thumbnail_data_cache = prefix + b64
            return self._thumbnail_data_cache
        except Exception:
            return None

    @thumbnail_data.setter
    def thumbnail_data(self, value):
        # Allow external code to set it (e.g. grid_view_manager caches it).
        self._thumbnail_data_cache = value

    def is_valid(self) -> bool:
        return (
            self.blob_path is not None
            and self.blob_path.exists()
            and self.hash_key == _file_hash_key(self.video_path)
        )

    def to_index_entry(self) -> dict:
        return {
            "blob": str(self.blob_path) if self.blob_path else None,
            "is_video": self.is_video,
            "hash_key": self.hash_key,
        }

    @classmethod
    def from_index_entry(cls, video_path: str, entry: dict) -> "VideoThumbnail":
        blob = Path(entry["blob"]) if entry.get("blob") else None
        return cls(
            video_path=video_path,
            blob_path=blob,
            is_video=entry.get("is_video", False),
            hash_key=entry.get("hash_key", ""),
        )


# ---------------------------------------------------------------------------
# ThumbnailStorage  (binary blobs + pickle index)
# ---------------------------------------------------------------------------

class ThumbnailStorage:
    """
    Stores thumbnail blobs as raw binary files under thumbnails_dir/blobs/.
    An index pickle maps normalised video_path → index-entry dict.
    """

    MAX_ENTRIES = 1000

    def __init__(self):
        self.thumbnails_dir = (
            Path.home() / "Documents" / "Recursive Media Player" / "Thumbnails"
        )
        self.blobs_dir = self.thumbnails_dir / "blobs"
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.thumbnails_dir / "index.pkl"
        self._index_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_index(self) -> Dict[str, dict]:
        """Return the on-disk index (path → entry dict). Never raises."""
        try:
            if self.index_file.exists():
                with open(self.index_file, "rb") as f:
                    return pickle.load(f)
        except Exception:
            pass
        return {}

    def save_index(self, index: Dict[str, dict]):
        """Atomically write the index pickle."""
        with self._index_lock:
            try:
                tmp = self.index_file.with_suffix(".tmp")
                with open(tmp, "wb") as f:
                    pickle.dump(index, f, protocol=pickle.HIGHEST_PROTOCOL)
                tmp.replace(self.index_file)
            except Exception as e:
                print(f"[ThumbnailStorage] save_index error: {e}")

    def write_blob(self, key: str, data: bytes, ext: str) -> Path:
        """Write raw bytes to a blob file and return its Path."""
        blob_name = key + ext          # e.g.  <md5>.jpg  or  <md5>.mp4
        blob_path = self.blobs_dir / blob_name
        blob_path.write_bytes(data)
        return blob_path

    def delete_blob(self, blob_path: Optional[Path]):
        if blob_path and blob_path.exists():
            _safe_unlink(str(blob_path))

    def prune(self, index: Dict[str, dict]) -> Dict[str, dict]:
        """Keep only the MAX_ENTRIES most-recently-modified blobs."""
        if len(index) <= self.MAX_ENTRIES:
            return index
        # Sort by blob mtime; remove oldest
        def _mtime(entry):
            bp = entry.get("blob")
            if bp:
                try:
                    return Path(bp).stat().st_mtime
                except OSError:
                    pass
            return 0.0

        ordered = sorted(index.items(), key=lambda kv: _mtime(kv[1]), reverse=True)
        keep = dict(ordered[: self.MAX_ENTRIES])
        remove = dict(ordered[self.MAX_ENTRIES :])
        for entry in remove.values():
            self.delete_blob(Path(entry["blob"]) if entry.get("blob") else None)
        return keep

    def clear(self):
        """Delete all blobs and reset the index."""
        try:
            import shutil
            shutil.rmtree(str(self.blobs_dir), ignore_errors=True)
            self.blobs_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self.save_index({})


# ---------------------------------------------------------------------------
# ThumbnailGenerator
# ---------------------------------------------------------------------------

class ThumbnailGenerator:
    THUMB_W = 320
    THUMB_H = 180
    JPEG_QUALITY = 82

    def __init__(self):
        self.preview_duration = 3      # seconds
        self.use_video_preview = True
        self.fallback_to_static = True

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def generate_thumbnail(self, video_path: str):
        """
        Returns (raw_bytes: bytes, is_video: bool) or None on failure.
        raw_bytes is a JPEG if is_video=False, else a small MP4 clip.
        """
        if self.use_video_preview:
            result = self._gen_video(video_path)
            if result:
                return result
            if self.fallback_to_static:
                return self._gen_static(video_path)
            return None
        return self._gen_static(video_path)

    def set_preview_duration(self, seconds: int):
        self.preview_duration = max(1, min(10, seconds))

    def set_use_video_preview(self, enabled: bool):
        self.use_video_preview = enabled

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _gen_video(self, video_path: str):
        """Return (mp4_bytes, True) or None."""
        tmp_path = None
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return None

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 25
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            if w == 0 or h == 0:
                cap.release()
                return None

            tw = self.THUMB_W
            th = int(h * tw / w)

            start_frame = max(30, int(total_frames * 0.1))
            frames_needed = int(fps * self.preview_duration)
            if start_frame + frames_needed > total_frames:
                frames_needed = max(1, total_frames - start_frame - 1)

            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

            fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
            os.close(fd)

            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            out = cv2.VideoWriter(tmp_path, fourcc, fps, (tw, th))
            if not out.isOpened():
                cap.release()
                _safe_unlink(tmp_path)
                return None

            captured = 0
            while captured < frames_needed:
                ret, frame = cap.read()
                if not ret:
                    break
                out.write(cv2.resize(frame, (tw, th)))
                captured += 1

            cap.release()
            out.release()

            if captured < 10:
                _safe_unlink(tmp_path)
                return None

            raw = Path(tmp_path).read_bytes()
            _safe_unlink(tmp_path)

            # Reject unreasonably large clips
            if len(raw) > 5 * 1024 * 1024:
                return None

            return raw, True

        except Exception as e:
            if tmp_path:
                _safe_unlink(tmp_path)
            return None

    def _gen_static(self, video_path: str):
        """Return (jpeg_bytes, False) or None."""
        tmp_path = None
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return None

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(30, int(total_frames * 0.1)))
            ret, frame = cap.read()
            cap.release()

            if not ret or frame is None:
                return None

            frame_resized = cv2.resize(frame, (self.THUMB_W, self.THUMB_H))
            frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(frame_rgb)

            fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
            os.close(fd)
            pil_img.save(tmp_path, "JPEG", quality=self.JPEG_QUALITY)

            raw = Path(tmp_path).read_bytes()
            _safe_unlink(tmp_path)
            return raw, False

        except Exception:
            if tmp_path:
                _safe_unlink(tmp_path)
            return None


# ---------------------------------------------------------------------------
# VideoPreviewTooltip  (unchanged logic, adapted to new thumbnail object)
# ---------------------------------------------------------------------------

class VideoPreviewTooltip:
    def __init__(self, parent):
        self.parent = parent
        self.tooltip_window = None
        self.is_visible = False

    def show_preview(self, video_path: str, thumbnail_data: str, x: int, y: int):
        """
        thumbnail_data is the sentinel string "IMAGE:<b64>" or "VIDEO:<b64>".
        This keeps the public API identical to the original.
        """
        if self.tooltip_window:
            self.hide_preview()

        try:
            import base64

            is_video = thumbnail_data.startswith("VIDEO:")
            raw_b64 = thumbnail_data[6:]          # strip "IMAGE:" or "VIDEO:"
            raw_bytes = base64.b64decode(raw_b64)

            fd, tmp_path = tempfile.mkstemp(suffix=".mp4" if is_video else ".jpg")
            os.close(fd)
            Path(tmp_path).write_bytes(raw_bytes)

            self.tooltip_window = tk.Toplevel(self.parent)
            self.tooltip_window.wm_overrideredirect(True)
            self.tooltip_window.configure(bg="black", relief="solid", bd=1)

            sw = self.parent.winfo_screenwidth()
            sh = self.parent.winfo_screenheight()
            tw, th = 340, 240
            x = min(x, sw - tw - 10)
            y = min(y, sh - th - 10)
            self.tooltip_window.geometry(f"+{x + 10}+{y + 10}")

            frame = tk.Frame(self.tooltip_window, bg="black", padx=5, pady=5)
            frame.pack()

            if is_video:
                try:
                    import vlc
                    inst = vlc.Instance("--no-xlib", "--quiet", "--no-audio")
                    player = inst.media_player_new()
                    player.audio_set_mute(True)
                    player.audio_set_volume(0)

                    vf = tk.Frame(frame, bg="black", width=320, height=180)
                    vf.pack()
                    vf.pack_propagate(False)

                    if os.name == "nt":
                        player.set_hwnd(vf.winfo_id())
                    else:
                        player.set_xwindow(vf.winfo_id())

                    player.set_media(inst.media_new(tmp_path))
                    player.play()

                    def _loop():
                        if self.tooltip_window:
                            if player.get_state() == vlc.State.Ended:
                                player.stop()
                                player.play()
                            self.tooltip_window.after(100, _loop)

                    self.tooltip_window.after(100, _loop)
                    self.tooltip_window._player = player
                    self.tooltip_window._instance = inst
                    self.tooltip_window._tmp_path = tmp_path
                except ImportError:
                    _safe_unlink(tmp_path)
                    tk.Label(frame, text="VLC not available", bg="black",
                             fg="yellow").pack()
            else:
                img = Image.open(tmp_path)
                photo = ImageTk.PhotoImage(img)
                lbl = tk.Label(frame, image=photo, bg="black")
                lbl.image = photo
                lbl.pack()
                self.tooltip_window._tmp_path = tmp_path

            name = os.path.basename(video_path)
            if len(name) > 40:
                name = name[:37] + "…"
            tk.Label(frame, text=name, bg="black", fg="white",
                     font=("Arial", 9), wraplength=320).pack(pady=(5, 0))

            self.is_visible = True

        except Exception as e:
            print(f"[Tooltip] show_preview error: {e}")
            self.hide_preview()

    def hide_preview(self):
        if self.tooltip_window:
            try:
                self.tooltip_window.destroy()
            except Exception:
                pass
            self.tooltip_window = None
        self.is_visible = False


# ---------------------------------------------------------------------------
# VideoPreviewManager
# ---------------------------------------------------------------------------

class VideoPreviewManager:
    """
    Main manager.  Public API is identical to the original so no callers change.

    Internal differences:
    - _thumbnails maps norm_path → VideoThumbnail (with blob_path on disk)
    - No base64 in the persistence layer
    - _save_thumbnails writes only the index pickle (fast)
    """

    def __init__(self, parent, console_callback: Callable = None):
        self.parent = parent
        self.console_callback = console_callback

        self.storage = ThumbnailStorage()
        self.generator = ThumbnailGenerator()
        self.tooltip = VideoPreviewTooltip(parent)

        get_resource_manager().register_cleanup_callback(self._cleanup)

        self.generator.set_preview_duration(3)
        self.generator.set_use_video_preview(True)
        self.generator.fallback_to_static = True

        self._thumbnails: Dict[str, VideoThumbnail] = {}
        self._generation_queue: set = set()
        self._lock = threading.Lock()
        self._dirty = False          # True when index needs saving
        self._save_timer = None

        self.current_listbox = None
        self.current_mapping = None
        self.right_clicked_item = None

        self._load_thumbnails()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _cleanup(self):
        try:
            self._cancel_save_timer()
            if self._dirty:
                self._flush_index()
            if hasattr(self, "tooltip"):
                self.tooltip.hide_preview()
            with self._lock:
                self._thumbnails.clear()
                self._generation_queue.clear()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def set_preview_duration(self, seconds: int):
        self.generator.set_preview_duration(seconds)

    def set_video_preview_enabled(self, enabled: bool):
        self.generator.set_use_video_preview(enabled)

    # ------------------------------------------------------------------
    # Load / save (fast, no base64)
    # ------------------------------------------------------------------

    def _load_thumbnails(self):
        index = self.storage.load_index()
        loaded = {}
        for vp, entry in index.items():
            th = VideoThumbnail.from_index_entry(vp, entry)
            if th.is_valid():
                loaded[vp] = th
            else:
                # Stale entry — delete blob
                self.storage.delete_blob(th.blob_path)
        self._thumbnails = loaded

    def _save_thumbnails(self):
        """Schedule a debounced index save (avoids hammering disk)."""
        self._dirty = True
        self._cancel_save_timer()
        self._save_timer = threading.Timer(3.0, self._flush_index)
        self._save_timer.daemon = True
        self._save_timer.start()

    def _flush_index(self):
        """Actually write the index pickle synchronously."""
        with self._lock:
            index = {vp: th.to_index_entry() for vp, th in self._thumbnails.items()}
        index = self.storage.prune(index)
        self.storage.save_index(index)
        self._dirty = False

    def _cancel_save_timer(self):
        if self._save_timer:
            self._save_timer.cancel()
            self._save_timer = None

    # ------------------------------------------------------------------
    # Listbox attachment
    # ------------------------------------------------------------------

    def attach_to_listbox(self, listbox: tk.Listbox, video_mapping: Dict[int, str]):
        self.current_listbox = listbox
        self.current_mapping = video_mapping
        listbox.bind("<Motion>", self._on_mouse_motion)
        listbox.bind("<Leave>", self._on_mouse_leave)

    def detach_from_listbox(self, listbox: tk.Listbox):
        try:
            listbox.unbind("<Button-3>")
            listbox.unbind("<Motion>")
            listbox.unbind("<Leave>")
        except Exception:
            pass
        if self.current_listbox is listbox:
            self.current_listbox = None
            self.current_mapping = None
        self.tooltip.hide_preview()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_right_click(self, event):
        if not self.current_mapping:
            return
        lb = event.widget
        idx = lb.nearest(event.y)
        if idx < 0 or idx >= lb.size():
            return
        vp = self.current_mapping.get(idx)
        if not vp or not os.path.isfile(vp):
            return
        if not lb.curselection():
            self.right_clicked_item = idx
            self._show_video_preview(vp, event.x_root, event.y_root)

    def _on_mouse_motion(self, event):
        if not self.tooltip.is_visible:
            return
        lb = event.widget
        idx = lb.nearest(event.y)
        if idx != self.right_clicked_item:
            self.tooltip.hide_preview()
            self.right_clicked_item = None

    def _on_mouse_leave(self, event):
        self.tooltip.hide_preview()
        self.right_clicked_item = None

    # ------------------------------------------------------------------
    # Preview display
    # ------------------------------------------------------------------

    def _show_video_preview(self, video_path: str, x: int, y: int):
        norm = os.path.normpath(video_path)
        with self._lock:
            th = self._thumbnails.get(norm)
        if th and th.is_valid():
            td = th.thumbnail_data      # builds sentinel string on demand
            if td:
                self.tooltip.show_preview(video_path, td, x, y)
                return
        if norm not in self._generation_queue:
            self._generate_thumbnail_async(norm, x, y)

    def _generate_thumbnail_async(self, video_path: str, x: int, y: int):
        with self._lock:
            if video_path in self._generation_queue:
                return
            self._generation_queue.add(video_path)

        def _work():
            try:
                result = self.generator.generate_thumbnail(video_path)
                if result is None:
                    with self._lock:
                        self._generation_queue.discard(video_path)
                    return

                raw_bytes, is_vid = result
                ext = ".mp4" if is_vid else ".jpg"
                hk = _file_hash_key(video_path)
                blob_path = self.storage.write_blob(hk, raw_bytes, ext)

                th = VideoThumbnail(
                    video_path=video_path,
                    blob_path=blob_path,
                    is_video=is_vid,
                    hash_key=hk,
                )

                with self._lock:
                    self._thumbnails[video_path] = th
                    self._generation_queue.discard(video_path)

                self._save_thumbnails()

                # Show tooltip if the user is still hovering
                if (self.right_clicked_item is not None
                        and self.current_mapping
                        and self.current_mapping.get(self.right_clicked_item) == video_path):
                    td = th.thumbnail_data
                    if td:
                        self.parent.after(0, lambda: self.tooltip.show_preview(video_path, td, x, y))

            except Exception as e:
                with self._lock:
                    self._generation_queue.discard(video_path)
                if self.console_callback:
                    self.console_callback(f"Thumbnail error: {e}")

        ManagedThread(target=_work, name="GenThumbnail").start()

    # ------------------------------------------------------------------
    # Pre-generation helper (used by grid view etc.)
    # ------------------------------------------------------------------

    def pregenerate_thumbnails(self, video_paths: list, progress_callback: Callable = None):
        def _bg():
            total = len(video_paths)
            for i, vp in enumerate(video_paths):
                if not os.path.isfile(vp):
                    continue
                norm = os.path.normpath(vp)
                with self._lock:
                    th = self._thumbnails.get(norm)
                if th and th.is_valid():
                    continue
                result = self.generator.generate_thumbnail(vp)
                if result:
                    raw_bytes, is_vid = result
                    ext = ".mp4" if is_vid else ".jpg"
                    hk = _file_hash_key(vp)
                    blob_path = self.storage.write_blob(hk, raw_bytes, ext)
                    t = VideoThumbnail(vp, blob_path, is_vid, hk)
                    with self._lock:
                        self._thumbnails[norm] = t
                if progress_callback:
                    self.parent.after(0, lambda p=(i + 1) / total * 100: progress_callback(p))
            self._flush_index()
            if self.console_callback:
                n = sum(1 for p in video_paths
                        if os.path.normpath(p) in self._thumbnails)
                self.console_callback(f"Pre-generated {n}/{total} thumbnails")

        ManagedThread(target=_bg, name="PregenThumbnails").start()

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def clear_cache(self):
        self._cancel_save_timer()
        with self._lock:
            self._thumbnails.clear()
            self._generation_queue.clear()
        self.storage.clear()
        self._dirty = False