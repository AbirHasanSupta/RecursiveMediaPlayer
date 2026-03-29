"""
VideoPreviewManager — fast binary thumbnail cache + LRU in-memory cache + background prefetch.

Changes vs previous version:
1. LRU in-memory PhotoImage cache (configurable size, default 200 entries).
   Decoded PhotoImage objects live in RAM so grid re-opens / re-renders need
   zero disk I/O and zero decode work.
2. Background prefetch queue.  When a directory scan completes (or any caller
   calls prefetch_for_videos()), a low-priority background worker starts
   generating blobs for every video in the directory.  By the time the user
   opens Grid View the thumbnails are already on disk (and likely in LRU RAM).
3. Prefetch is throttled to not starve the UI: one frame per ~80 ms, with a
   configurable worker count (default 2 threads).
4. All persistence is still raw binary blobs + pickle index (no base64 on disk).
"""

import os
import hashlib
import threading
import time
import tempfile
import shutil
import queue
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Optional, Callable, List

import cv2
import tkinter as tk
from PIL import Image, ImageTk
import pickle

from managers.resource_manager import get_resource_manager, ManagedThread


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_hash_key(video_path: str) -> str:
    try:
        st = os.stat(video_path)
        raw = f"{video_path}_{st.st_size}_{st.st_mtime}"
    except OSError:
        raw = video_path
    return hashlib.md5(raw.encode()).hexdigest()


def _safe_unlink(path):
    try:
        os.unlink(str(path))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# LRU PhotoImage cache
# ---------------------------------------------------------------------------

class LRUPhotoCache:
    """
    Thread-safe LRU cache for decoded PhotoImage objects.
    Keyed by normalised video path.  Evicts the least-recently-used entry
    when the capacity is exceeded.

    PhotoImage objects must be kept alive (not garbage-collected) to display
    correctly in Tkinter — holding them here serves that purpose as well.
    """

    def __init__(self, maxsize: int = 200):
        self._maxsize = maxsize
        self._cache: OrderedDict[str, ImageTk.PhotoImage] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[ImageTk.PhotoImage]:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)   # mark as recently used
                return self._cache[key]
        return None

    def put(self, key: str, photo: ImageTk.PhotoImage):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = photo
            while len(self._cache) > self._maxsize:
                self._cache.popitem(last=False)   # evict LRU

    def discard(self, key: str):
        with self._lock:
            self._cache.pop(key, None)

    def discard_prefix(self, prefix: str):
        """Remove all entries whose key starts with prefix."""
        with self._lock:
            keys = [k for k in self._cache if k.startswith(prefix)]
            for k in keys:
                del self._cache[k]

    def clear(self):
        with self._lock:
            self._cache.clear()

    def __len__(self):
        with self._lock:
            return len(self._cache)


# ---------------------------------------------------------------------------
# VideoThumbnail
# ---------------------------------------------------------------------------

class VideoThumbnail:
    def __init__(self, video_path: str, blob_path: Optional[Path] = None,
                 is_video: bool = False, hash_key: str = ""):
        self.video_path = os.path.normpath(video_path)
        self.blob_path: Optional[Path] = blob_path
        self.is_video: bool = is_video
        self.hash_key: str = hash_key or _file_hash_key(video_path)
        self._thumbnail_data_cache: Optional[str] = None

    # Legacy sentinel-string property (built lazily, never stored on disk)
    @property
    def thumbnail_data(self) -> Optional[str]:
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
    MAX_ENTRIES = 1000

    def __init__(self):
        self.thumbnails_dir = (
            Path.home() / "Documents" / "Recursive Media Player" / "Thumbnails"
        )
        self.blobs_dir = self.thumbnails_dir / "blobs"
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.thumbnails_dir / "index.pkl"
        self._index_lock = threading.Lock()

    def load_index(self) -> Dict[str, dict]:
        try:
            if self.index_file.exists():
                with open(self.index_file, "rb") as f:
                    return pickle.load(f)
        except Exception:
            pass
        return {}

    def save_index(self, index: Dict[str, dict]):
        with self._index_lock:
            try:
                tmp = self.index_file.with_suffix(".tmp")
                with open(tmp, "wb") as f:
                    pickle.dump(index, f, protocol=pickle.HIGHEST_PROTOCOL)
                tmp.replace(self.index_file)
            except Exception as e:
                print(f"[ThumbnailStorage] save_index error: {e}")

    def write_blob(self, key: str, data: bytes, ext: str) -> Path:
        blob_path = self.blobs_dir / (key + ext)
        blob_path.write_bytes(data)
        return blob_path

    def delete_blob(self, blob_path: Optional[Path]):
        if blob_path and blob_path.exists():
            _safe_unlink(blob_path)

    def prune(self, index: Dict[str, dict]) -> Dict[str, dict]:
        if len(index) <= self.MAX_ENTRIES:
            return index

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
        for entry in dict(ordered[self.MAX_ENTRIES :]).values():
            self.delete_blob(Path(entry["blob"]) if entry.get("blob") else None)
        return keep

    def clear(self):
        try:
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
        self.preview_duration = 3
        self.use_video_preview = True
        self.fallback_to_static = True

    def generate_thumbnail(self, video_path: str):
        """Returns (raw_bytes: bytes, is_video: bool) or None."""
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

    def _gen_video(self, video_path: str):
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
            if len(raw) > 5 * 1024 * 1024:
                return None
            return raw, True
        except Exception:
            if tmp_path:
                _safe_unlink(tmp_path)
            return None

    def _gen_static(self, video_path: str):
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
# VideoPreviewTooltip
# ---------------------------------------------------------------------------

class VideoPreviewTooltip:
    def __init__(self, parent):
        self.parent = parent
        self.tooltip_window = None
        self.is_visible = False

    def show_preview(self, video_path: str, thumbnail_data: str, x: int, y: int):
        if self.tooltip_window:
            self.hide_preview()
        try:
            import base64
            is_video = thumbnail_data.startswith("VIDEO:")
            raw_bytes = base64.b64decode(thumbnail_data[6:])
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
                    tk.Label(frame, text="VLC not available", bg="black", fg="yellow").pack()
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
            print(f"[Tooltip] error: {e}")
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
# PrefetchQueue — background thumbnail generation
# ---------------------------------------------------------------------------

class PrefetchQueue:
    """
    Low-priority background worker that generates thumbnail blobs for a list
    of video paths.  New batch() calls cancel any in-progress work for the
    same directory and replace it.

    Design:
    - A fixed pool of worker threads (default 2) drains a priority queue.
    - Each item is (priority, video_path).  Lower priority = processed first.
    - Items already having a valid blob are skipped instantly.
    - A cancellation token per batch lets old batches be abandoned cheaply.
    """

    def __init__(self, num_workers: int = 2):
        self._q: queue.PriorityQueue = queue.PriorityQueue()
        self._lock = threading.Lock()
        self._active_token: object = None      # current batch token
        self._thumbnails_ref: Optional[Dict] = None   # set by manager
        self._storage_ref: Optional[ThumbnailStorage] = None
        self._generator_ref: Optional[ThumbnailGenerator] = None
        self._on_done_cb: Optional[Callable] = None    # called after each blob
        self._running = True
        self._num_workers = num_workers
        self._workers: List[threading.Thread] = []
        self._batch_done_cb: Optional[Callable] = None  # called when queue drains
        self._start_workers()

    def _start_workers(self):
        for i in range(self._num_workers):
            t = threading.Thread(target=self._worker_loop,
                                 name=f"PrefetchWorker-{i}", daemon=True)
            t.start()
            self._workers.append(t)

    def attach(self, thumbnails: Dict, storage: ThumbnailStorage,
               generator: ThumbnailGenerator, on_done_cb: Callable,
               batch_done_cb: Optional[Callable] = None):
        self._thumbnails_ref = thumbnails
        self._storage_ref = storage
        self._generator_ref = generator
        self._on_done_cb = on_done_cb
        self._batch_done_cb = batch_done_cb

    def enqueue_batch(self, video_paths: List[str]):
        """
        Cancel the current batch and enqueue a new one.
        Videos are enqueued in order so the first ones (most likely to appear
        at the top of grid view) are processed first.
        """
        with self._lock:
            token = object()
            self._active_token = token

        # Drain old items (non-blocking) — can't truly cancel already-running
        # work but skipping in the worker is essentially free.
        try:
            while True:
                self._q.get_nowait()
                self._q.task_done()
        except queue.Empty:
            pass

        for priority, vp in enumerate(video_paths):
            self._q.put((priority, vp, token))

    def stop(self):
        self._running = False
        # Unblock workers
        for _ in self._workers:
            self._q.put((-1, None, None))

    def _worker_loop(self):
        while self._running:
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                continue

            priority, video_path, token = item
            try:
                if video_path is None:          # stop sentinel
                    break

                # Skip if this batch was cancelled
                with self._lock:
                    if token is not self._active_token:
                        continue

                if not self._thumbnails_ref or not self._storage_ref or not self._generator_ref:
                    continue

                norm = os.path.normpath(video_path)
                th = self._thumbnails_ref.get(norm)
                if th and th.is_valid():
                    continue                     # already have a fresh blob

                if not os.path.isfile(video_path):
                    continue

                result = self._generator_ref.generate_thumbnail(video_path)
                if result is None:
                    continue

                raw_bytes, is_vid = result
                ext = ".mp4" if is_vid else ".jpg"
                hk = _file_hash_key(video_path)
                blob_path = self._storage_ref.write_blob(hk, raw_bytes, ext)
                th_new = VideoThumbnail(video_path, blob_path, is_vid, hk)
                self._thumbnails_ref[norm] = th_new

                if self._on_done_cb:
                    try:
                        self._on_done_cb(norm, th_new)
                    except Exception:
                        pass

                # Small sleep so we don't saturate the CPU and starve the UI
                time.sleep(0.08)

            except Exception as e:
                print(f"[PrefetchWorker] {e}")
            finally:
                try:
                    self._q.task_done()
                    # When queue fully drains, fire the batch-complete callback
                    if self._q.empty() and self._batch_done_cb:
                        try:
                            self._batch_done_cb()
                        except Exception:
                            pass
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# VideoPreviewManager
# ---------------------------------------------------------------------------

class VideoPreviewManager:
    """
    Public API is identical to the original.

    New capabilities:
    - lru_cache: LRU in-memory PhotoImage cache (default 200 slots)
    - prefetch_for_videos(paths): kick off background blob generation
    - prefetch_for_directory(dir_path, video_list): called by app when a
      directory scan completes
    """

    # How many decoded PhotoImages to keep in RAM
    LRU_SIZE = 200
    # Background worker threads for prefetch
    PREFETCH_WORKERS = 2

    def __init__(self, parent, console_callback: Callable = None):
        self.parent = parent
        self.console_callback = console_callback

        self.storage = ThumbnailStorage()
        self.generator = ThumbnailGenerator()
        self.tooltip = VideoPreviewTooltip(parent)

        # In-memory LRU cache: norm_path → PhotoImage
        self.lru_cache = LRUPhotoCache(maxsize=self.LRU_SIZE)

        # Disk-level thumbnail map: norm_path → VideoThumbnail
        self._thumbnails: Dict[str, VideoThumbnail] = {}
        self._generation_queue: set = set()
        self._lock = threading.Lock()
        self._dirty = False
        self._save_timer: Optional[threading.Timer] = None

        # Background prefetch
        self._prefetch = PrefetchQueue(num_workers=self.PREFETCH_WORKERS)
        self._prefetch.attach(
            self._thumbnails,
            self.storage,
            self.generator,
            self._on_prefetch_done,
            batch_done_cb=self._on_prefetch_batch_done,
        )

        get_resource_manager().register_cleanup_callback(self._cleanup)

        self.generator.set_preview_duration(3)
        self.generator.set_use_video_preview(True)
        self.generator.fallback_to_static = True

        self.current_listbox = None
        self.current_mapping = None
        self.right_clicked_item = None

        self._load_thumbnails()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _cleanup(self):
        try:
            self._prefetch.stop()
            self._cancel_save_timer()
            # Always flush index on exit — even if not dirty — so any
            # blobs written this session are indexed for next startup.
            self._flush_index()
            if hasattr(self, "tooltip"):
                self.tooltip.hide_preview()
            self.lru_cache.clear()
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
    # Load / save
    # ------------------------------------------------------------------

    def _load_thumbnails(self):
        index = self.storage.load_index()
        loaded = {}
        for vp, entry in index.items():
            th = VideoThumbnail.from_index_entry(vp, entry)
            if th.is_valid():
                loaded[vp] = th
            else:
                self.storage.delete_blob(th.blob_path)
        self._thumbnails = loaded
        # Re-attach prefetch to new dict
        self._prefetch.attach(self._thumbnails, self.storage,
                              self.generator, self._on_prefetch_done,
                              batch_done_cb=self._on_prefetch_batch_done)

    def _save_thumbnails(self):
        """Schedule debounced index save."""
        self._dirty = True
        self._cancel_save_timer()
        self._save_timer = threading.Timer(3.0, self._flush_index)
        self._save_timer.daemon = True
        self._save_timer.start()

    def _flush_index(self):
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
    # Prefetch — called by the application when videos become known
    # ------------------------------------------------------------------

    def prefetch_for_videos(self, video_paths: List[str]):
        """
        Start background generation for the given video list.
        Safe to call multiple times; cancels the previous batch automatically.
        Only enqueues paths that don't already have a valid blob on disk.
        Videos with existing valid blobs are skipped — their cache is reused.
        """
        needed = [
            p for p in video_paths
            if os.path.isfile(p)
            and not self._has_valid_blob(os.path.normpath(p))
        ]
        if needed:
            self._prefetch.enqueue_batch(needed)
        # If needed is empty, all blobs already exist — nothing to do.

    def prefetch_for_directory(self, dir_path: str, video_paths: List[str]):
        """
        Called when a directory scan completes.
        Checks each video against the persisted blob index first.
        Already-cached videos are skipped entirely — their blobs are reused
        from disk on next Grid View open without any regeneration.
        """
        all_local = [p for p in video_paths if os.path.isfile(p)]
        already_cached = [
            p for p in all_local
            if self._has_valid_blob(os.path.normpath(p))
        ]
        needed = [p for p in all_local if p not in already_cached]

        if self.console_callback:
            cached_count = len(already_cached)
            if cached_count:
                self.console_callback(
                    f"Thumbnails: {cached_count} already cached, "
                    f"{len(needed)} to generate in "
                    f"'{os.path.basename(dir_path)}'"
                )
            elif needed:
                self.console_callback(
                    f"Prefetching thumbnails for {len(needed)} videos "
                    f"in '{os.path.basename(dir_path)}' …"
                )

        if needed:
            self._prefetch.enqueue_batch(needed)

    def _has_valid_blob(self, norm_path: str) -> bool:
        th = self._thumbnails.get(norm_path)
        return th is not None and th.is_valid()

    def _on_prefetch_done(self, norm_path: str, thumbnail: VideoThumbnail):
        """Called by PrefetchQueue worker after each individual blob is written."""
        # Mark dirty but don't flush per-item — wait for batch to complete.
        self._dirty = True

    def _on_prefetch_batch_done(self):
        """Called by PrefetchQueue when the entire queue drains.
        Flushes index immediately so blobs are indexed for next startup."""
        self._cancel_save_timer()
        self._flush_index()

    # ------------------------------------------------------------------
    # PhotoImage from blob (shared by manager and grid_view_manager)
    # ------------------------------------------------------------------

    def decode_blob_to_photo(self, blob_path: Path, is_video: bool) -> Optional[ImageTk.PhotoImage]:
        """
        Decode a raw blob file into a PhotoImage with no base64 anywhere.
        Returns None on any failure.
        """
        tmp_path = None
        try:
            if is_video:
                fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
                os.close(fd)
                shutil.copy2(str(blob_path), tmp_path)
                cap = cv2.VideoCapture(tmp_path)
                ret, frame = cap.read()
                cap.release()
                _safe_unlink(tmp_path)
                tmp_path = None
                if not ret or frame is None:
                    return None
                frame_resized = cv2.resize(frame, (190, 140))
                frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(frame_rgb)
            else:
                pil_image = Image.open(str(blob_path))
                pil_image.thumbnail((190, 140), Image.Resampling.LANCZOS)

            return ImageTk.PhotoImage(pil_image)
        except Exception:
            if tmp_path:
                _safe_unlink(tmp_path)
            return None

    def get_photo_for_video(self, video_path: str) -> Optional[ImageTk.PhotoImage]:
        """
        Return a PhotoImage for the given video path.
        Priority:
          1. LRU RAM cache (instant)
          2. Blob on disk  (fast decode, no base64)
          3. None (not yet generated — caller should use prefetch or on-demand)
        """
        norm = os.path.normpath(video_path)

        # 1. LRU hit
        photo = self.lru_cache.get(norm)
        if photo is not None:
            return photo

        # 2. Blob on disk
        th = self._thumbnails.get(norm)
        if th and th.is_valid() and th.blob_path and th.blob_path.exists():
            photo = self.decode_blob_to_photo(th.blob_path, th.is_video)
            if photo:
                self.lru_cache.put(norm, photo)
                return photo

        return None

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
            td = th.thumbnail_data
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
                th = VideoThumbnail(video_path, blob_path, is_vid, hk)

                with self._lock:
                    self._thumbnails[video_path] = th
                    self._generation_queue.discard(video_path)

                self._save_thumbnails()

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
    # Pre-generation / bulk
    # ------------------------------------------------------------------

    def pregenerate_thumbnails(self, video_paths: list, progress_callback: Callable = None):
        """
        Original API — still works.  Internally delegates to prefetch now.
        progress_callback receives (percentage: float).
        """
        self.prefetch_for_videos(video_paths)
        if progress_callback:
            # Fire a single 100% callback since prefetch is asynchronous
            self.parent.after(200, lambda: progress_callback(100.0))

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def clear_cache(self):
        self._cancel_save_timer()
        self._prefetch.enqueue_batch([])   # cancel pending work
        with self._lock:
            self._thumbnails.clear()
            self._generation_queue.clear()
        self.lru_cache.clear()
        self.storage.clear()
        self._dirty = False

    def evict_for_directory(self, dir_path: str):
        """
        Remove all blobs and LRU entries whose video path is inside dir_path.
        Call this when a directory is removed from the application.
        """
        prefix = os.path.normpath(dir_path) + os.sep
        root_norm = os.path.normpath(dir_path)

        with self._lock:
            to_remove = [
                k for k in self._thumbnails
                if k == root_norm or k.startswith(prefix)
            ]
            for k in to_remove:
                th = self._thumbnails.pop(k)
                self.storage.delete_blob(th.blob_path)

        self.lru_cache.discard_prefix(root_norm)

        if to_remove:
            self._flush_index()
            if self.console_callback:
                self.console_callback(
                    f"Evicted {len(to_remove)} cached thumbnails for "
                    f"'{os.path.basename(dir_path)}'"
                )