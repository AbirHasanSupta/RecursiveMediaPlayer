import json
import os
import threading
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from typing import List, Optional, Callable
import uuid

from managers.toast_manager import Toast
from utils import _responsive_geometry


def _get_app_dirs():
    """Return (appdata_dir, localappdata_dir) for Recursive Media Player."""
    import os, sys
    from pathlib import Path
    APP = "Recursive Media Player"
    if os.name == "nt":
        settings = Path(os.environ.get("APPDATA",  Path.home() / "AppData" / "Roaming")) / APP
        local    = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))  / APP
    elif sys.platform == "darwin":
        settings = Path.home() / "Library" / "Application Support" / APP
        local    = Path.home() / "Library" / "Caches" / APP
    else:
        settings = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP
        local    = Path(os.environ.get("XDG_CACHE_HOME",  Path.home() / ".cache"))  / APP
    return settings, local




class QueueEntry:
    def __init__(self, video_path: str, queue_id: str = None, added_from: str = "manual"):
        self.id = queue_id or str(uuid.uuid4())
        self.video_path = os.path.normpath(video_path)
        self.video_name = os.path.basename(self.video_path)
        self.added_from = added_from
        self.played = False

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'video_path': self.video_path,
            'added_from': self.added_from,
            'played': self.played
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'QueueEntry':
        entry = cls(
            video_path=data.get('video_path', ''),
            queue_id=data.get('id'),
            added_from=data.get('added_from', 'manual')
        )
        entry.played = data.get('played', False)
        return entry


class QueueStorage:
    def __init__(self):
        self.queue_dir = _get_app_dirs()[1] / "Queue"
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.queue_file = self.queue_dir / "playback_queue.json"

    def save_queue(self, entries: List[QueueEntry], current_index: int = 0) -> bool:
        try:
            data = {
                'entries': [entry.to_dict() for entry in entries],
                'current_index': current_index
            }
            with open(self.queue_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving queue: {e}")
            return False

    def load_queue(self) -> tuple:
        try:
            if not self.queue_file.exists():
                return [], 0

            with open(self.queue_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            entries = [QueueEntry.from_dict(item) for item in data.get('entries', [])]
            current_index = data.get('current_index', 0)

            return entries, current_index
        except Exception as e:
            print(f"Error loading queue: {e}")
            return [], 0

    def clear_queue(self) -> bool:
        try:
            if self.queue_file.exists():
                self.queue_file.unlink()
            return True
        except Exception as e:
            print(f"Error clearing queue: {e}")
            return False


class QueueService:
    def __init__(self, storage: QueueStorage):
        self.storage = storage
        self._queue: List[QueueEntry] = []
        self._current_index = 0
        self._lock = threading.RLock()
        self._load_queue()
        from managers.resource_manager import get_resource_manager
        get_resource_manager().register_cleanup_callback(self._cleanup)

    def _cleanup(self):
        try:
            with self._lock:
                self._queue.clear()
        except:
            pass

    def _load_queue(self):
        entries, index = self.storage.load_queue()
        self._queue = entries
        self._current_index = index

    def get_queue(self) -> List[QueueEntry]:
        with self._lock:
            return self._queue.copy()

    def get_current_index(self) -> int:
        with self._lock:
            return self._current_index

    def set_current_index(self, index: int):
        with self._lock:
            if 0 <= index < len(self._queue):
                self._current_index = index
                self.storage.save_queue(self._queue, self._current_index)

    def add_to_queue(self, video_paths: List[str], added_from: str = "manual") -> int:
        with self._lock:
            added_count = 0
            existing_paths = {entry.video_path for entry in self._queue}

            for video_path in video_paths:
                normalized = os.path.normpath(video_path)
                if normalized not in existing_paths:
                    entry = QueueEntry(normalized, added_from=added_from)
                    self._queue.append(entry)
                    existing_paths.add(normalized)
                    added_count += 1

            if added_count > 0:
                self.storage.save_queue(self._queue, self._current_index)

            return added_count

    def play_next(self, video_paths: List[str], added_from: str = "manual") -> int:
        with self._lock:
            added_count = 0
            existing_paths = {entry.video_path for entry in self._queue}
            insert_position = self._current_index + 1

            for video_path in video_paths:
                normalized = os.path.normpath(video_path)
                if normalized not in existing_paths:
                    entry = QueueEntry(normalized, added_from=added_from)
                    self._queue.insert(insert_position, entry)
                    existing_paths.add(normalized)
                    insert_position += 1
                    added_count += 1

            if added_count > 0:
                self.storage.save_queue(self._queue, self._current_index)

            return added_count

    def remove_from_queue(self, indices: List[int]) -> int:
        with self._lock:
            if not self._queue:
                return 0

            sorted_indices = sorted(set(indices), reverse=True)
            removed_count = 0

            for index in sorted_indices:
                if 0 <= index < len(self._queue):
                    self._queue.pop(index)
                    removed_count += 1

                    if index < self._current_index:
                        self._current_index -= 1
                    elif index == self._current_index and self._current_index >= len(self._queue):
                        self._current_index = max(0, len(self._queue) - 1)

            if removed_count > 0:
                self.storage.save_queue(self._queue, self._current_index)

            return removed_count

    def move_items(self, indices: List[int], direction: str) -> bool:
        with self._lock:
            if not self._queue or not indices:
                return False

            indices = sorted(set(indices))

            if direction == 'up':
                if indices[0] == 0:
                    return False
                for idx in indices:
                    if idx > 0:
                        self._queue[idx], self._queue[idx - 1] = self._queue[idx - 1], self._queue[idx]
                        if self._current_index == idx:
                            self._current_index -= 1
                        elif self._current_index == idx - 1:
                            self._current_index += 1

            elif direction == 'down':
                if indices[-1] >= len(self._queue) - 1:
                    return False
                for idx in reversed(indices):
                    if idx < len(self._queue) - 1:
                        self._queue[idx], self._queue[idx + 1] = self._queue[idx + 1], self._queue[idx]
                        if self._current_index == idx:
                            self._current_index += 1
                        elif self._current_index == idx + 1:
                            self._current_index -= 1

            self.storage.save_queue(self._queue, self._current_index)
            return True

    def clear_queue(self) -> bool:
        with self._lock:
            self._queue.clear()
            self._current_index = 0
            return self.storage.clear_queue()

    def clear_played(self) -> int:
        with self._lock:
            if not self._queue:
                return 0

            original_length = len(self._queue)
            self._queue = [entry for entry in self._queue if not entry.played]
            removed = original_length - len(self._queue)

            if self._current_index >= len(self._queue):
                self._current_index = max(0, len(self._queue) - 1)

            if removed > 0:
                self.storage.save_queue(self._queue, self._current_index)

            return removed

    def get_next_video(self) -> Optional[str]:
        with self._lock:
            if not self._queue:
                return None

            next_index = self._current_index + 1
            if next_index < len(self._queue):
                return self._queue[next_index].video_path

            return None

    def advance_queue(self) -> Optional[str]:
        with self._lock:
            if not self._queue:
                return None

            if 0 <= self._current_index < len(self._queue):
                self._queue[self._current_index].played = True

            self._current_index += 1

            if self._current_index < len(self._queue):
                video_path = self._queue[self._current_index].video_path
                self.storage.save_queue(self._queue, self._current_index)
                return video_path

            self.storage.save_queue(self._queue, self._current_index)
            return None

    def jump_to_index(self, index: int) -> Optional[str]:
        with self._lock:
            if 0 <= index < len(self._queue):
                self._current_index = index
                self.storage.save_queue(self._queue, self._current_index)
                return self._queue[index].video_path
            return None

    def get_current_video(self) -> Optional[str]:
        with self._lock:
            if 0 <= self._current_index < len(self._queue):
                return self._queue[self._current_index].video_path
            return None

    def reorder_queue(self, new_order: List[int]) -> bool:
        with self._lock:
            if len(new_order) != len(self._queue):
                return False

            try:
                current_video = None
                if 0 <= self._current_index < len(self._queue):
                    current_video = self._queue[self._current_index].video_path

                self._queue = [self._queue[i] for i in new_order]

                if current_video:
                    for i, entry in enumerate(self._queue):
                        if entry.video_path == current_video:
                            self._current_index = i
                            break

                self.storage.save_queue(self._queue, self._current_index)
                return True
            except:
                return False


class QueueUI:
    def __init__(self, parent, theme_provider, queue_service: QueueService):
        self.parent = parent
        self.theme_provider = theme_provider
        self.queue_service = queue_service

        self.queue_window = None
        self.queue_listbox = None
        self.on_play_callback = None
        self.on_jump_callback = None

        self.drag_start_index = None
        self.drag_data = None
        self.video_preview_manager = None
        self.grid_view_manager = None
        self.add_to_favorites_callback = None
        self.add_to_playlist_callback = None
        self.locate_in_panel_callback = None
        self._embedded = False
        self._close_callback = None
        self._sort_col = None
        self._sort_rev = False
        self._duration_cache = {}
        self.queue_tree = None
        self.theme_provider.register_manager_ui(self)

    def show_queue_manager(self):
        if self.queue_window and self.queue_window.winfo_exists():
            self.queue_window.lift()
            self._refresh_queue()
            return

        self._embedded = False
        self._close_callback = None
        self.queue_window = tk.Toplevel(self.parent)
        self.queue_window.withdraw()
        self.queue_window.title("Playback Queue")
        self.queue_window.geometry(_responsive_geometry(self.parent, 1600, 900))
        self.queue_window.configure(bg=self.theme_provider.bg_color)

        self._setup_queue_ui()
        self._refresh_queue()

        from icon_helper import apply_icon
        apply_icon(self.queue_window)
        self.queue_window.deiconify()

    def show_queue_manager_embedded(self, parent, close_callback=None):
        if self.queue_window and self.queue_window.winfo_exists():
            self.queue_window.destroy()
        for child in parent.winfo_children():
            child.destroy()
        self._embedded = True
        self._close_callback = close_callback
        self.queue_window = tk.Frame(parent, bg=self.theme_provider.bg_color)
        self.queue_window.pack(fill=tk.BOTH, expand=True)
        self._setup_queue_ui()
        self._refresh_queue()

    def _close_queue(self):
        if self.queue_window and self.queue_window.winfo_exists():
            self.queue_window.destroy()
        self.queue_window = None
        if self._embedded and self._close_callback:
            self._close_callback()

    def _configure_queue_tree_style(self):
        t = self._get_design_tokens()
        tp = self.theme_provider
        style = ttk.Style()
        try:
            style.configure("QueueTree.Treeview",
                            background=t["surface"], foreground=t["listbox_fg"],
                            fieldbackground=t["surface"], rowheight=28,
                            borderwidth=0, relief="flat", font=tp.normal_font)
            style.map("QueueTree.Treeview",
                      background=[("selected", t["listbox_select"])],
                      foreground=[("selected", "#FFFFFF")],
                      fieldbackground=[("!disabled", t["surface"])])
            style.configure("QueueTree.Treeview.Heading",
                            background=t["surface2"], foreground=t["text_muted"],
                            relief="flat", borderwidth=0, font=("Segoe UI", 9, "bold"))
            style.map("QueueTree.Treeview.Heading",
                      background=[("active", t["surface2"]), ("pressed", t["surface2"])],
                      foreground=[("active", t["text"]), ("pressed", t["text"])])
        except Exception:
            pass

    def _get_file_size(self, path):
        try:
            s = os.path.getsize(path)
            if s >= 1_073_741_824: return f"{s / 1_073_741_824:.1f} GB"
            if s >= 1_048_576: return f"{s / 1_048_576:.1f} MB"
            if s >= 1024: return f"{s / 1024:.0f} KB"
            return f"{s} B"
        except:
            return "—"

    def _get_duration(self, path):
        if path in self._duration_cache:
            return self._duration_cache[path]
        try:
            import subprocess
            import sys
            kwargs = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, timeout=5, **kwargs)
            secs = float(r.stdout.strip())
            h, rem = divmod(int(secs), 3600)
            m, s = divmod(rem, 60)
            dur = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        except:
            dur = "—"
        self._duration_cache[path] = dur
        return dur

    def _fetch_duration_async(self, path, iid):
        def _fetch():
            dur = self._get_duration(path)
            try:
                if self.queue_tree and self.queue_tree.winfo_exists():
                    self.queue_tree.after(0, lambda: self._update_tree_duration(iid, dur))
            except:
                pass

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_tree_duration(self, iid, dur):
        try:
            if self.queue_tree and self.queue_tree.winfo_exists() and self.queue_tree.exists(iid):
                vals = list(self.queue_tree.item(iid, "values"))
                if len(vals) >= 5:
                    vals[4] = dur
                    self.queue_tree.item(iid, values=vals)
        except:
            pass

    def _sort_by_col(self, col):
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col
            self._sort_rev = False
        self._refresh_queue()

    def _get_tv_selected_indices(self):
        if not self.queue_tree:
            return []
        return [int(iid) for iid in self.queue_tree.selection() if iid != "empty"]

    def _get_design_tokens(self):
        return self.theme_provider.get_manager_design_tokens()

    def apply_theme(self):
        win = self.queue_window
        if win is None:
            return
        try:
            if not win.winfo_exists():
                return
        except tk.TclError:
            return
        t = self._get_design_tokens()
        tp = self.theme_provider
        win.configure(bg=t["bg"])
        for attr in ("_queue_header", "_queue_body", "_queue_card", "_queue_col_hdr", "_queue_lb_row", "_queue_btn_row"):
            w = getattr(self, attr, None)
            if w is None:
                continue
            role = getattr(w, "_manager_role", "body")
            bg = t.get({"header": "header_bg", "surface": "surface", "surface2": "surface2", "body": "bg"}.get(role, "bg"), t["bg"])
            try:
                w.configure(bg=bg)
            except tk.TclError:
                pass
        if hasattr(self, "queue_info_label"):
            self.queue_info_label.configure(bg=t["header_bg"], fg=t["text_muted"])
        if hasattr(self, "queue_tree") and self.queue_tree:
            try:
                self.queue_tree.winfo_exists()
            except tk.TclError:
                pass
            else:
                self._configure_queue_tree_style()
                t2 = self._get_design_tokens()
                self.queue_tree.tag_configure("playing", foreground=t2["queue_accent"])
                self.queue_tree.tag_configure("played", foreground=t2["text_muted"])
                self.queue_tree.tag_configure("normal", foreground=t2["listbox_fg"])
        if hasattr(self, "_queue_scrollbar"):
            tp.configure_manager_scrollbar(self._queue_scrollbar, t)
        tp.restyle_manager_buttons(win)
        tp.restyle_manager_action_links(win)
        self._refresh_queue()

    def _setup_queue_ui(self):
        tp = self.theme_provider
        t = self._get_design_tokens()

        header = tk.Frame(self.queue_window, bg=t['header_bg'], height=58)
        header._manager_role = "header"
        self._queue_header = header
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        h_inner = tk.Frame(header, bg=t['header_bg'])
        h_inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=0)

        title_box = tk.Frame(h_inner, bg=t['header_bg'])
        title_box.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(title_box, text="⬛", font=("Segoe UI Emoji", 18),
                 bg=t['header_bg'], fg=t['queue_accent']).pack(side=tk.LEFT, padx=(0, 10), pady=14)
        tk.Label(title_box, text="Playback Queue",
                 font=("Segoe UI", 15, "bold"),
                 bg=t['header_bg'], fg=t['text']).pack(side=tk.LEFT, pady=14)

        if self._embedded and self._close_callback:
            close_btn = tk.Label(h_inner, text="✕", font=("Segoe UI", 14),
                                 bg=t['header_bg'], fg=t['text_muted'], cursor="hand2", padx=10)
            close_btn.pack(side=tk.RIGHT, pady=14)
            close_btn.bind("<Button-1>", lambda e: self._close_queue())
            close_btn.bind("<Enter>", lambda e: close_btn.config(fg=t['accent_secondary']))
            close_btn.bind("<Leave>", lambda e: close_btn.config(fg=t['text_muted']))

        info_lbl = tk.Label(h_inner, text="",
                            font=tp.small_font, bg=t['header_bg'], fg=t['text_muted'])
        info_lbl.pack(side=tk.RIGHT, padx=(0, 10))
        self.queue_info_label = info_lbl

        tk.Frame(self.queue_window, bg=t['divider'], height=1).pack(fill=tk.X)

        body = tk.Frame(self.queue_window, bg=t['bg'])
        body._manager_role = "body"
        self._queue_body = body
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=(12, 0))

        card = tk.Frame(body, bg=t['surface'],
                        highlightbackground=t['border'], highlightthickness=1)
        card._manager_role = "surface"
        self._queue_card = card
        card.pack(fill=tk.BOTH, expand=True)

        tree_frame = tk.Frame(card, bg=t['surface'])
        tree_frame._manager_role = "surface"
        self._queue_col_hdr = tree_frame
        self._queue_lb_row = tree_frame
        tree_frame.pack(fill=tk.BOTH, expand=True)

        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, style="ExclusionTree.Vertical.TScrollbar")
        self._queue_scrollbar = sb
        sb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 1), pady=1)

        self._configure_queue_tree_style()
        self.queue_tree = ttk.Treeview(
            tree_frame,
            columns=("num", "name", "directory", "size", "duration"),
            show="headings",
            style="QueueTree.Treeview",
            selectmode="extended",
            yscrollcommand=sb.set,
        )
        self.queue_listbox = self.queue_tree

        for cid, heading, width, anchor, stretch in [
            ("num", "#", 52, tk.CENTER, False),
            ("name", "Video Name", 200, tk.W, True),
            ("directory", "Directory", 340, tk.CENTER, True),
            ("size", "Size", 80, tk.CENTER, False),
            ("duration", "Duration", 75, tk.CENTER, False),
        ]:
            self.queue_tree.heading(cid, text=heading, command=lambda c=cid: self._sort_by_col(c))
            self.queue_tree.column(cid, width=width, anchor=anchor, minwidth=30, stretch=stretch)

        t2 = self._get_design_tokens()
        self.queue_tree.tag_configure("playing", foreground=t2["queue_accent"])
        self.queue_tree.tag_configure("played", foreground=t2["text_muted"])
        self.queue_tree.tag_configure("normal", foreground=t2["listbox_fg"])

        self.queue_tree.pack(fill=tk.BOTH, expand=True)
        sb.config(command=self.queue_tree.yview)

        self.queue_tree.bind("<Double-Button-1>", self._on_double_click)
        self.queue_tree.bind("<Button-1>", self._on_drag_start)
        self.queue_tree.bind("<Button-3>", self._on_right_click)
        self.queue_tree.bind("<B1-Motion>", self._on_drag_motion)
        self.queue_tree.bind("<ButtonRelease-1>", self._on_drag_release)
        self.queue_tree.bind("<Leave>", self._on_mouse_leave)

        # ---- Buttons placed directly on body, no extra bar ----
        btn_container = tk.Frame(body, bg=t['bg'])
        btn_container._manager_role = "body"
        self._queue_btn_row = btn_container
        btn_container.pack(fill=tk.X, pady=(4, 8))

        queue_actions = tk.Frame(btn_container, bg=t["bg"])
        queue_actions.pack(side=tk.RIGHT)
        self._clear_played_btn = tp.create_manager_action_link(
            queue_actions, "↺  Clear played", self._clear_played, style="queue")
        self._clear_played_btn.pack(side=tk.LEFT)
        self._clear_queue_btn = tp.create_manager_action_link(
            queue_actions, "✕  Clear all", self._clear_queue, style="warning")
        self._clear_queue_btn.pack(side=tk.LEFT)

    def play_from_global(self):
        """Play the queue from the current position."""
        queue = self.queue_service.get_queue()
        if not queue:
            return
        current_index = self.queue_service.get_current_index()
        videos = [entry.video_path for entry in queue[current_index:]]
        if videos and self.on_play_callback:
            self.on_play_callback(videos)

    def _refresh_queue(self):
        def refresh():
            if not self.queue_tree or not self.queue_tree.winfo_exists():
                return
            t = self._get_design_tokens()
            ACCENT = t["queue_accent"]

            self.queue_tree.delete(*self.queue_tree.get_children())
            queue = self.queue_service.get_queue()
            current_index = self.queue_service.get_current_index()

            if not queue:
                self.queue_tree.insert("", tk.END, iid="empty",
                                       values=("", "Queue is empty. Right-click a video to add.", "", "", ""),
                                       tags=("played",))
                self.queue_info_label.config(text="0 videos")
                return

            rows = []
            for i, entry in enumerate(queue):
                dir_str = os.path.normpath(os.path.dirname(entry.video_path))
                size_str = self._get_file_size(entry.video_path)
                dur_str = self._duration_cache.get(entry.video_path, "—")
                rows.append((i, i + 1, entry.video_name, dir_str, size_str, dur_str, entry))

            if self._sort_col:
                if self._sort_col == "size":
                    def _sk(r):
                        try:
                            return os.path.getsize(r[6].video_path)
                        except:
                            return 0

                    rows.sort(key=_sk, reverse=self._sort_rev)
                elif self._sort_col == "duration":
                    def _dk(r):
                        d = r[5]
                        if d == "—": return -1
                        try:
                            p = list(map(int, d.split(":")))
                            return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]
                        except:
                            return -1

                    rows.sort(key=_dk, reverse=self._sort_rev)
                else:
                    ki = {"num": 1, "name": 2, "directory": 3}[self._sort_col]
                    rows.sort(key=lambda r: int(r[ki]) if self._sort_col == "num" else str(r[ki]).lower(), reverse=self._sort_rev)


            arrow = {True: " ▼", False: " ▲"}
            for cid, lbl in [("num", "#"), ("name", "Video Name"), ("directory", "Directory"),
                             ("size", "Size"), ("duration", "Duration")]:
                self.queue_tree.heading(cid, text=lbl + (arrow[self._sort_rev] if self._sort_col == cid else ""))

            for orig_idx, num, name, dirpath, size_s, dur_s, entry in rows:
                if orig_idx == current_index:
                    tag = "playing"
                elif entry.played:
                    tag = "played"
                else:
                    tag = "normal"
                self.queue_tree.insert("", tk.END, iid=str(orig_idx),
                                       values=(num, name, dirpath, size_s, dur_s), tags=(tag,))
                if entry.video_path not in self._duration_cache:
                    self._fetch_duration_async(entry.video_path, str(orig_idx))

            unplayed = sum(1 for e in queue if not e.played)
            self.queue_info_label.config(
                text=f"{len(queue)} videos  •  {unplayed} unplayed  •  #{current_index + 1} playing")

        if threading.current_thread() is threading.main_thread():
            refresh()
        else:
            self.parent.after(0, refresh)

    def _show_queue_context_menu(self, event):
        selection = self._get_tv_selected_indices()
        if not selection:
            return
        queue = self.queue_service.get_queue()
        selected_videos = [queue[idx].video_path for idx in selection
                           if 0 <= idx < len(queue) and os.path.exists(queue[idx].video_path)]

        context_menu = self.theme_provider.create_manager_context_menu(self.queue_window)
        context_menu.add_command(
            label=f"Play Selected ({len(selection)} item{'s' if len(selection) > 1 else ''})",
            command=lambda v=selected_videos: self._play_from_context(v))
        context_menu.add_command(label="Jump to Selected",
                                 command=lambda: self._jump_to_first_selected(selection))
        context_menu.add_separator()
        context_menu.add_command(label="Select All", command=self._select_all)
        context_menu.add_command(label="Clear Selection", command=self._unselect_all)
        context_menu.add_separator()
        context_menu.add_command(label="Open in Gallery",
                                 command=lambda: self._open_grid_view_from_selection(selection))
        if self.add_to_favorites_callback and selected_videos:
            context_menu.add_command(label="Add to Favourites",
                                     command=lambda v=selected_videos: self.add_to_favorites_callback(v))
        if self.add_to_playlist_callback and selected_videos:
            context_menu.add_command(label="Add to Playlist",
                                     command=lambda v=selected_videos: self.add_to_playlist_callback(v))
        context_menu.add_separator()
        context_menu.add_command(label="Remove from Queue", command=self._remove_selected)
        if len(selection) == 1:
            entry = queue[selection[0]]
            context_menu.add_separator()
            context_menu.add_command(label="Copy Path",
                                     command=lambda: self._copy_path(entry.video_path))
            context_menu.add_command(label="Open File Location",
                                     command=lambda: self._open_location(entry.video_path))
            if self.locate_in_panel_callback and os.path.isfile(entry.video_path):
                context_menu.add_command(label="Show in Panel",
                                         command=lambda p=entry.video_path: self.locate_in_panel_callback(p))
        try:
            context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            context_menu.grab_release()

    def _select_all(self, event=None):
        self.queue_tree.selection_set(*self.queue_tree.get_children())
        return "break"

    def _unselect_all(self, event=None):
        self.queue_tree.selection_remove(*self.queue_tree.get_children())

    def _on_mouse_leave(self, event):
        if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
            self.video_preview_manager.tooltip.hide_preview()

    def _on_right_click(self, event):
        iid = self.queue_tree.identify_row(event.y)
        if not iid or iid == "empty":
            return
        index = int(iid)
        selection = self._get_tv_selected_indices()
        queue = self.queue_service.get_queue()
        if selection and index in selection:
            self._show_queue_context_menu(event)
            return
        if 0 <= index < len(queue):
            entry = queue[index]
            if os.path.isfile(entry.video_path) and self.video_preview_manager:
                self.video_preview_manager.tooltip.hide_preview()
                self.video_preview_manager.right_clicked_item = index
                self.video_preview_manager._show_video_preview(entry.video_path, event.x_root, event.y_root)

    def _play_from_context(self, videos):
        if videos and self.on_play_callback:
            self.on_play_callback(videos)
        self._refresh_queue()

    def _play_from_selection(self, selection):
        """Play queue starting from first selected item"""
        if not selection:
            return

        first_index = min(selection)
        video_path = self.queue_service.jump_to_index(first_index)

        if video_path and self.on_jump_callback:
            self.on_jump_callback(video_path)

        self._refresh_queue()

    def _jump_to_first_selected(self, selection):
        """Jump to first selected item without playing"""
        if not selection:
            return

        first_index = min(selection)
        self.queue_service.set_current_index(first_index)
        self._refresh_queue()

    def _open_grid_view(self):
        """Open grid view with entire queue"""
        queue = self.queue_service.get_queue()

        if not queue:
            self.theme_provider.toast.warning("Warning", "Queue is empty")
            return

        if not hasattr(self, 'grid_view_manager') or not self.grid_view_manager:
            self.theme_provider.toast.warning("Warning", "Grid view not available")
            return

        video_paths = [entry.video_path for entry in queue if os.path.exists(entry.video_path)]

        if video_paths:
            self.grid_view_manager.show_grid_view(video_paths, self.video_preview_manager)
        else:
            self.theme_provider.toast.warning("No Valid Files", "No valid video files in queue")

    def _open_grid_view_from_selection(self, selection):
        """Open grid view with selected queue items"""
        if not hasattr(self, 'grid_view_manager') or not self.grid_view_manager:
            return

        queue = self.queue_service.get_queue()
        video_paths = []

        for index in selection:
            if 0 <= index < len(queue):
                entry = queue[index]
                if os.path.exists(entry.video_path):
                    video_paths.append(entry.video_path)

        if video_paths:
            self.grid_view_manager.show_grid_view(video_paths, self.video_preview_manager)

    def _copy_path(self, file_path):
        """Copy file path to clipboard"""
        try:
            self.parent.clipboard_clear()
            self.parent.clipboard_append(file_path)
        except Exception as e:
            print(f"Error copying path: {e}")

    def _open_location(self, file_path):
        """Open file location in explorer"""
        try:
            import subprocess
            import sys
            if os.name == 'nt':
                subprocess.Popen(f'explorer /select,"{file_path}"')
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', '-R', file_path])
            else:
                subprocess.Popen(['xdg-open', os.path.dirname(file_path)])
        except Exception as e:
            print(f"Error opening location: {e}")

    def _on_double_click(self, event):
        if self.queue_tree.identify_region(event.x, event.y) != "cell":
            return
        iid = self.queue_tree.identify_row(event.y)
        if iid and iid != "empty":
            index = int(iid)
            video_path = self.queue_service.jump_to_index(index)
            if video_path and self.on_jump_callback:
                self.on_jump_callback(video_path)
            self._refresh_queue()

    def _on_drag_start(self, event):
        if self.queue_tree.identify_region(event.x, event.y) == "heading":
            return
        if self._sort_col is not None:
            self.drag_start_index = None
            return
        iid = self.queue_tree.identify_row(event.y)
        if not iid or iid == "empty":
            return
        index = int(iid)
        ctrl_held = bool(event.state & 0x4)
        shift_held = bool(event.state & 0x1)
        current_selection = list(self.queue_tree.selection())
        if shift_held and current_selection:
            anchor = int(current_selection[-1])
            start, end = min(anchor, index), max(anchor, index)
            self.queue_tree.selection_set(*[str(i) for i in range(start, end + 1)
                                            if self.queue_tree.exists(str(i))])
            self.drag_start_index = None
            return "break"
        elif ctrl_held:
            if iid in current_selection:
                self.queue_tree.selection_remove(iid)
            else:
                self.queue_tree.selection_add(iid)
            self.drag_start_index = None
            return "break"
        else:
            self.queue_tree.selection_set(iid)
            self.drag_start_index = index
            self.drag_data = None
            return "break"

    def _on_drag_motion(self, event):
        if self.drag_start_index is None:
            return
        iid = self.queue_tree.identify_row(event.y)
        if iid and iid != "empty":
            idx = int(iid)
            if idx != self.drag_start_index:
                self.drag_data = idx

    def _on_drag_release(self, event):
        if self.drag_start_index is None or self.drag_data is None:
            self.drag_start_index = None
            self.drag_data = None
            return
        selection = self._get_tv_selected_indices()
        if not selection:
            self.drag_start_index = None
            self.drag_data = None
            return
        target = self.drag_data
        if target > max(selection):
            direction, moves = 'down', target - max(selection)
        elif target < min(selection):
            direction, moves = 'up', min(selection) - target
        else:
            self.drag_start_index = None
            self.drag_data = None
            return
        for _ in range(moves):
            self.queue_service.move_items(selection, direction)
            selection = [s + (-1 if direction == 'up' else 1) for s in selection]
        self._refresh_queue()
        for idx in selection:
            if self.queue_tree.exists(str(idx)):
                self.queue_tree.selection_add(str(idx))
        self.drag_start_index = None
        self.drag_data = None

    def _move_up(self):
        selection = self._get_tv_selected_indices()
        if selection and self.queue_service.move_items(selection, 'up'):
            self._refresh_queue()
            for idx in selection:
                new = max(0, idx - 1)
                if self.queue_tree.exists(str(new)):
                    self.queue_tree.selection_add(str(new))

    def _move_down(self):
        selection = self._get_tv_selected_indices()
        if selection and self.queue_service.move_items(selection, 'down'):
            self._refresh_queue()
            q_len = len(self.queue_service.get_queue())
            for idx in selection:
                new = min(q_len - 1, idx + 1)
                if self.queue_tree.exists(str(new)):
                    self.queue_tree.selection_add(str(new))

    def _remove_selected(self):
        selection = self._get_tv_selected_indices()
        removed = self.queue_service.remove_from_queue(selection) if selection else 0
        if removed > 0:
            self._refresh_queue()
            self.theme_provider.toast.success("Removed",
                                              f"{removed} video{'s' if removed != 1 else ''} removed from queue")

    def _clear_played(self):
        removed = self.queue_service.clear_played()
        if removed > 0:
            self._refresh_queue()
            self.theme_provider.toast.info("Success", f"Removed {removed} played videos from queue")

    def _clear_queue(self):
        count = len(self.queue_service.get_queue())
        if count == 0:
            return
        result = messagebox.askyesno(
            "Confirm Clear",
            "Clear entire queue?",
            parent=self.queue_window
        )
        if result:
            self.theme_provider.toast.success("Queue Cleared",
                                              f"Cleared {count} video{'s' if count != 1 else ''} from queue")
            self.queue_service.clear_queue()
            self._refresh_queue()

    def _play_queue(self):
        queue = self.queue_service.get_queue()
        if not queue:
            self.theme_provider.toast.warning("Empty Queue", "Queue is empty")
            return

        current_index = self.queue_service.get_current_index()
        videos = [entry.video_path for entry in queue[current_index:]]

        if self.on_play_callback:
            self.on_play_callback(videos)


class VideoQueueManager:
    def __init__(self, parent, theme_provider):
        self.storage = QueueStorage()
        self.service = QueueService(self.storage)
        self.ui = QueueUI(parent, theme_provider, self.service)

        self._play_callback = None

    def set_play_callback(self, callback: Callable):
        self._play_callback = callback
        self.ui.on_play_callback = self._on_play_queue
        self.ui.on_jump_callback = self._on_jump_to_video

    def show_manager(self):
        self.ui.show_queue_manager()

    def show_embedded(self, parent, close_callback=None):
        self.ui.show_queue_manager_embedded(parent, close_callback)
        return self.ui

    def add_to_queue(self, video_paths: List[str], added_from: str = "manual") -> int:
        count = self.service.add_to_queue(video_paths, added_from)
        if count and self.ui:
            self.ui._refresh_queue()
        return count

    def play_next(self, video_paths: List[str], added_from: str = "manual") -> int:
        count = self.service.play_next(video_paths, added_from)
        if count and self.ui:
            self.ui._refresh_queue()
        return count

    def get_next_video(self) -> Optional[str]:
        return self.service.get_next_video()

    def advance_queue(self) -> Optional[str]:
        return self.service.advance_queue()

    def get_current_video(self) -> Optional[str]:
        return self.service.get_current_video()

    def clear_queue(self):
        self.service.clear_queue()

    def _on_play_queue(self, videos: List[str]):
        if self._play_callback:
            self._play_callback(videos)

    def _on_jump_to_video(self, video_path: str):
        if self._play_callback:
            self._play_callback([video_path])

    def set_video_preview_manager(self, preview_manager):
        self.ui.video_preview_manager = preview_manager

    def set_grid_view_manager(self, grid_view_manager):
        self.ui.grid_view_manager = grid_view_manager

    def set_add_to_favorites_callback(self, callback):
        self.ui.add_to_favorites_callback = callback

    def set_add_to_playlist_callback(self, callback):
        self.ui.add_to_playlist_callback = callback

    def set_locate_in_panel_callback(self, callback):
        self.ui.locate_in_panel_callback = callback
