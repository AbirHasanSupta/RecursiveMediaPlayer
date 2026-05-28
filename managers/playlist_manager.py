import json
import os
import threading
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Callable
import uuid
from tkinter import ttk

from managers.resource_manager import get_resource_manager
from managers.toast_manager import Toast
from utils import _responsive_geometry


class PlaylistData:
    """Data class for playlist information following Single Responsibility Principle"""

    def __init__(self, playlist_id: str = None, name: str = "", description: str = "", videos: List[str] = None):
        self.id = playlist_id or str(uuid.uuid4())
        self.name = name
        self.description = description
        self.videos = videos or []
        self.created_date = datetime.now().isoformat()
        self.modified_date = self.created_date

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'videos': self.videos,
            'created_date': self.created_date,
            'modified_date': self.modified_date
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'PlaylistData':
        playlist = cls(
            playlist_id=data.get('id'),
            name=data.get('name', ''),
            description=data.get('description', ''),
            videos=data.get('videos', [])
        )
        playlist.created_date = data.get('created_date', datetime.now().isoformat())
        playlist.modified_date = data.get('modified_date', playlist.created_date)
        return playlist


class PlaylistStorage:
    """Handles playlist persistence following Single Responsibility Principle"""

    def __init__(self):
        self.playlists_dir = Path.home() / "Documents" / "Recursive Media Player" / "Playlists"
        self.playlists_dir.mkdir(parents=True, exist_ok=True)
        self.playlists_file = self.playlists_dir / "playlists.json"

    def save_playlists(self, playlists: List[PlaylistData]) -> bool:
        try:
            data = [playlist.to_dict() for playlist in playlists]
            with open(self.playlists_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving playlists: {e}")
            return False

    def load_playlists(self) -> List[PlaylistData]:
        try:
            if not self.playlists_file.exists():
                return []

            with open(self.playlists_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            return [PlaylistData.from_dict(item) for item in data]
        except Exception as e:
            print(f"Error loading playlists: {e}")
            return []


class PlaylistService:
    def __init__(self, storage: PlaylistStorage):
        self.storage = storage
        self._playlists: List[PlaylistData] = []
        self._lock = threading.RLock()
        self._load_playlists()
        get_resource_manager().register_cleanup_callback(self._cleanup)

    def _cleanup(self):
        try:
            with self._lock:
                self._playlists.clear()
        except:
            pass

    def _load_playlists(self):
        self._playlists = self.storage.load_playlists()

    def get_all_playlists(self) -> List[PlaylistData]:
        return self._playlists.copy()

    def create_playlist(self, name: str, description: str = "", videos: List[str] = None) -> PlaylistData:
        with self._lock:
            playlist = PlaylistData(name=name, description=description, videos=videos or [])
            self._playlists.append(playlist)
            self.storage.save_playlists(self._playlists)
            return playlist

    def update_playlist(self, playlist_id: str, name: str = None, description: str = None,
                        videos: List[str] = None) -> bool:
        playlist = self.get_playlist_by_id(playlist_id)
        if not playlist:
            return False

        if name is not None:
            playlist.name = name
        if description is not None:
            playlist.description = description
        if videos is not None:
            playlist.videos = videos

        playlist.modified_date = datetime.now().isoformat()
        self.storage.save_playlists(self._playlists)
        return True

    def delete_playlist(self, playlist_id: str) -> bool:
        playlist = self.get_playlist_by_id(playlist_id)
        if playlist:
            self._playlists.remove(playlist)
            self.storage.save_playlists(self._playlists)
            return True
        return False

    def get_playlist_by_id(self, playlist_id: str) -> Optional[PlaylistData]:
        for playlist in self._playlists:
            if playlist.id == playlist_id:
                return playlist
        return None

    def add_videos_to_playlist(self, playlist_id: str, videos: List[str]) -> bool:
        playlist = self.get_playlist_by_id(playlist_id)
        if not playlist:
            return False

        # Add only unique videos
        for video in videos:
            if video not in playlist.videos:
                playlist.videos.append(video)

        playlist.modified_date = datetime.now().isoformat()
        self.storage.save_playlists(self._playlists)
        return True


class PlaylistUI:
    """UI components for playlist management following Interface Segregation Principle"""

    def __init__(self, parent, theme_provider, playlist_service: PlaylistService, on_play_callback: Callable = None,
                 log_callback: Callable = None):
        self.parent = parent
        self.theme_provider = theme_provider
        self.playlist_service = playlist_service
        self.on_play_callback = on_play_callback
        self.log_callback = log_callback

        self.current_playlist: Optional[PlaylistData] = None
        self.playlist_window = None
        self.video_preview_manager = None
        self.grid_view_manager = None
        self.add_to_favorites_callback = None
        self.add_to_queue_callback = None
        self.locate_in_panel_callback = None
        self.video_mapping = {}

        self.dragging_index = None
        self._sort_col = None
        self._sort_rev = False
        self._duration_cache = {}
        self.video_tree = None
        self._hovered_iid = None
        self._embedded = False
        self._close_callback = None
        self.theme_provider.register_manager_ui(self)

    def _get_design_tokens(self):
        return self.theme_provider.get_manager_design_tokens()

    def _configure_pl_video_tree_style(self):
        t = self._get_design_tokens()
        tp = self.theme_provider
        style = ttk.Style()
        try:
            style.configure("PlTree.Treeview",
                            background=t["surface"], foreground=t["listbox_fg"],
                            fieldbackground=t["surface"], rowheight=28,
                            borderwidth=0, relief="flat", font=tp.normal_font)
            style.map("PlTree.Treeview",
                      background=[("selected", t["listbox_select"])],
                      foreground=[("selected", "#FFFFFF")],
                      fieldbackground=[("!disabled", t["surface"])])
            style.configure("PlTree.Treeview.Heading",
                            background=t["surface2"], foreground=t["text_muted"],
                            relief="flat", borderwidth=0, font=("Segoe UI", 9, "bold"))
            style.map("PlTree.Treeview.Heading",
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
                if self.video_tree and self.video_tree.winfo_exists():
                    self.video_tree.after(0, lambda: self._update_tree_duration(iid, dur))
            except:
                pass

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_tree_duration(self, iid, dur):
        try:
            if self.video_tree and self.video_tree.winfo_exists() and self.video_tree.exists(iid):
                vals = list(self.video_tree.item(iid, "values"))
                if len(vals) >= 5:
                    vals[4] = dur
                    self.video_tree.item(iid, values=vals)
        except:
            pass

    def _sort_by_col(self, col):
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col
            self._sort_rev = False
        self._refresh_video_list()

    def _get_tv_selected_indices(self):
        if not self.video_tree:
            return []
        return [int(iid) for iid in self.video_tree.selection() if iid != "empty"]

    def apply_theme(self):
        win = self.playlist_window
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
        for attr in (
            "_pl_header", "_pl_cols", "_pl_left_card", "_pl_right_area",
            "_pl_right_card", "_pl_vid_hdr", "_pl_vid_body", "_pl_pl_act",
        ):
            w = getattr(self, attr, None)
            if w is None:
                continue
            role = getattr(w, "_manager_role", "body")
            bg = t.get({"header": "header_bg", "surface": "surface", "surface2": "surface2", "body": "bg"}.get(role, "bg"), t["bg"])
            try:
                w.configure(bg=bg)
            except tk.TclError:
                pass
        if hasattr(self, "playlist_info_label"):
            self.playlist_info_label.configure(bg=t["bg"], fg=t["text_muted"])
        lb = getattr(self, "playlist_listbox", None)
        if lb is not None:
            tp.configure_manager_listbox(lb, t)
        sb = getattr(self, "_pl_list_scrollbar", None)
        if sb is not None:
            tp.configure_manager_scrollbar(sb, t)
        if hasattr(self, "video_tree") and self.video_tree:
            try:
                self.video_tree.winfo_exists()
            except tk.TclError:
                pass
            else:
                self._configure_pl_video_tree_style()
                t2 = self._get_design_tokens()
                self.video_tree.tag_configure("normal", foreground=t2["listbox_fg"])
                self.video_tree.tag_configure("missing", foreground=t2["text_muted"])
                self.video_tree.tag_configure("hover_row", background=self.theme_provider.hover_color)
        sb2 = getattr(self, "_pl_video_scrollbar", None)
        if sb2 is not None:
            tp.configure_manager_scrollbar(sb2, t)
        for sb_name in ("_pl_list_scrollbar", "_pl_video_scrollbar"):
            sb = getattr(self, sb_name, None)
            if sb is not None:
                tp.configure_manager_scrollbar(sb, t)
        tp.restyle_manager_buttons(win)
        tp.restyle_manager_action_links(win)
        self._refresh_playlist_list()
        if self.current_playlist:
            self._refresh_video_list()

    def show_playlist_manager(self):
        if self.playlist_window and self.playlist_window.winfo_exists():
            self.playlist_window.lift()
            return

        self._embedded = False
        self._close_callback = None
        self.playlist_window = tk.Toplevel(self.parent)
        self.playlist_window.withdraw()
        self.playlist_window.title("Playlists")
        self.playlist_window.geometry(_responsive_geometry(self.parent, 1600, 900))
        self.playlist_window.configure(bg=self.theme_provider.bg_color)

        self._setup_playlist_manager_ui()
        self._refresh_playlist_list()

        from icon_helper import apply_icon
        apply_icon(self.playlist_window)
        self.playlist_window.deiconify()

    def show_playlist_manager_embedded(self, parent, close_callback=None):
        if self.playlist_window and self.playlist_window.winfo_exists():
            self._on_close()
        for child in parent.winfo_children():
            child.destroy()
        self._embedded = True
        self._close_callback = close_callback
        self.playlist_window = tk.Frame(parent, bg=self.theme_provider.bg_color)
        self.playlist_window.pack(fill=tk.BOTH, expand=True)
        self._setup_playlist_manager_ui()
        self._refresh_playlist_list()

    def _setup_playlist_manager_ui(self):
        tp = self.theme_provider
        t = self._get_design_tokens()

        header = tk.Frame(self.playlist_window, bg=t['header_bg'], height=58)
        header._manager_role = "header"
        self._pl_header = header
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        h_inner = tk.Frame(header, bg=t['header_bg'])
        h_inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=0)

        title_box = tk.Frame(h_inner, bg=t['header_bg'])
        title_box.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(title_box, text="🎵", font=("Segoe UI Emoji", 18),
                 bg=t['header_bg'], fg=t['playlist_accent']).pack(side=tk.LEFT, padx=(0, 10), pady=14)
        tk.Label(title_box, text="Playlist Manager",
                 font=("Segoe UI", 15, "bold"),
                 bg=t['header_bg'], fg=t['text']).pack(side=tk.LEFT, pady=14)

        if self._embedded and self._close_callback:
            close_btn = tk.Label(h_inner, text="✕", font=("Segoe UI", 14),
                                 bg=t['header_bg'], fg=t['text_muted'], cursor="hand2", padx=10)
            close_btn.pack(side=tk.RIGHT, pady=14)
            close_btn.bind("<Button-1>", lambda e: self._on_close())
            close_btn.bind("<Enter>", lambda e: close_btn.config(fg=t['accent_secondary']))
            close_btn.bind("<Leave>", lambda e: close_btn.config(fg=t['text_muted']))

        tk.Frame(self.playlist_window, bg=t['divider'], height=1).pack(fill=tk.X)

        cols = tk.Frame(self.playlist_window, bg=t['bg'])
        cols._manager_role = "body"
        self._pl_cols = cols
        cols.pack(fill=tk.BOTH, expand=True, padx=20, pady=12)

        left_card = tk.Frame(cols, bg=t['surface2'], width=310,
                             highlightbackground=t['border'], highlightthickness=1)
        left_card._manager_role = "surface2"
        self._pl_left_card = left_card
        left_card.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 10))
        left_card.pack_propagate(False)

        tk.Label(left_card, text="  PLAYLISTS", font=tp.small_font,
                 bg=t['surface2'], fg=t['text_muted'], pady=8, anchor="w"
                 ).pack(fill=tk.X, padx=(4, 0))
        tk.Frame(left_card, bg=t['divider'], height=1).pack(fill=tk.X)

        pl_body = tk.Frame(left_card, bg=t['surface'])
        pl_body.pack(fill=tk.BOTH, expand=True)
        pl_sb = ttk.Scrollbar(pl_body, orient=tk.VERTICAL,
                              style="ExclusionTree.Vertical.TScrollbar")
        self._pl_list_scrollbar = pl_sb
        pl_sb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 1), pady=1)
        self.playlist_listbox = tk.Listbox(
            pl_body, yscrollcommand=pl_sb.set, font=tp.normal_font,
            bg=t['surface'], fg=t['listbox_fg'], selectbackground=t['listbox_select'],
            selectforeground="white", activestyle="none",
            relief=tk.FLAT, bd=0, highlightthickness=0)
        self.playlist_listbox.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.playlist_listbox.bind("<<ListboxSelect>>", self._on_playlist_select)
        self.playlist_listbox.bind("<Button-3>", self._on_playlist_right_click)
        pl_sb.config(command=self.playlist_listbox.yview)

        tk.Frame(left_card, bg=t['divider'], height=1).pack(fill=tk.X)
        pl_act = tk.Frame(left_card, bg=t['surface2'])
        pl_act._manager_role = "surface2"
        self._pl_pl_act = pl_act
        pl_act.pack(fill=tk.X, padx=8, pady=8)
        pl_left = tk.Frame(pl_act, bg=t['surface2'])
        pl_left.pack(side=tk.LEFT)
        pl_right = tk.Frame(pl_act, bg=t['surface2'])
        pl_right.pack(side=tk.RIGHT)

        self.shuffle_playlist_btn = tp.create_manager_action_link(
            pl_left, "⇄  Shuffle", self._shuffle_current_playlist, style="secondary")
        self.shuffle_playlist_btn.pack(side=tk.LEFT, padx=(0, 2))

        self.new_playlist_btn = tp.create_manager_action_link(
            pl_right, "＋  New playlist", self._create_new_playlist, style="playlist")
        self.new_playlist_btn.pack(side=tk.LEFT, padx=(0, 4))

        right_area = tk.Frame(cols, bg=t['bg'])
        right_area._manager_role = "body"
        self._pl_right_area = right_area
        right_area.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        info_row = tk.Frame(right_area, bg=t['bg'])
        info_row.pack(fill=tk.X, pady=(0, 8))
        self.playlist_info_label = tk.Label(
            info_row, text="Select a playlist →",
            font=tp.small_font, bg=t['bg'], fg=t['text_muted'])
        self.playlist_info_label.pack(side=tk.LEFT, anchor="w")

        right_card = tk.Frame(right_area, bg=t['surface'],
                              highlightbackground=t['border'], highlightthickness=1)
        right_card._manager_role = "surface"
        self._pl_right_card = right_card
        right_card.pack(fill=tk.BOTH, expand=True)
        vid_hdr = tk.Frame(right_card, bg=t['surface2'])
        vid_hdr._manager_role = "surface2"
        self._pl_vid_hdr = vid_hdr
        vid_hdr.pack(fill=tk.X)
        tk.Label(vid_hdr, text="  VIDEOS  —  drag to reorder  •  double‑click to play",
                 font=tp.small_font, bg=t['surface2'], fg=t['text_muted'],
                 pady=6, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        tk.Frame(right_card, bg=t['divider'], height=1).pack(fill=tk.X)

        vid_body = tk.Frame(right_card, bg=t['surface'])
        vid_body._manager_role = "surface"
        self._pl_vid_body = vid_body
        vid_body.pack(fill=tk.BOTH, expand=True)

        vid_sb = ttk.Scrollbar(vid_body, orient=tk.VERTICAL, style="ExclusionTree.Vertical.TScrollbar")
        self._pl_video_scrollbar = vid_sb
        vid_sb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 1), pady=1)

        self._configure_pl_video_tree_style()
        self.video_tree = ttk.Treeview(
            vid_body,
            columns=("num", "name", "directory", "size", "duration"),
            show="headings",
            style="PlTree.Treeview",
            selectmode="extended",
            yscrollcommand=vid_sb.set,
        )
        self.video_listbox = self.video_tree

        for cid, heading, width, anchor, stretch in [
            ("num", "#", 52, tk.CENTER, False),
            ("name", "Video Name", 200, tk.W, True),
            ("directory", "Directory", 340, tk.CENTER, True),
            ("size", "Size", 80, tk.CENTER, False),
            ("duration", "Duration", 75, tk.CENTER, False),
        ]:
            self.video_tree.heading(cid, text=heading, command=lambda c=cid: self._sort_by_col(c))
            self.video_tree.column(cid, width=width, anchor=anchor, minwidth=30, stretch=stretch)

        t2 = self._get_design_tokens()
        self.video_tree.tag_configure("normal", foreground=t2["listbox_fg"])
        self.video_tree.tag_configure("missing", foreground=t2["text_muted"])

        self.video_tree.pack(fill=tk.BOTH, expand=True)
        self.video_tree.bind("<Double-Button-1>", self._on_video_double_click)
        self.video_tree.bind("<Button-1>", self._on_mouse_down)
        self.video_tree.bind("<B1-Motion>", self._on_mouse_drag)
        self.video_tree.bind("<ButtonRelease-1>", self._on_mouse_release)
        self.video_tree.bind("<Motion>", self._on_tree_hover)
        self.video_tree.bind("<Leave>", self._on_combined_leave)
        self._right_click_binding = self.video_tree.bind_all(
            "<Button-3>", self._on_video_right_click_wrapper)
        vid_sb.config(command=self.video_tree.yview)

    def _select_all(self, event=None):
        self.video_tree.selection_set(*self.video_tree.get_children())
        return "break"

    def _unselect_all(self, event=None):
        self.video_tree.selection_remove(*self.video_tree.get_children())

    def _on_video_right_click_wrapper(self, event):
        if not hasattr(self, 'playlist_window') or not self.playlist_window:
            return
        if not self.playlist_window.winfo_exists():
            return
        if event.widget is not self.video_tree:
            return
        self._on_video_right_click(event)

    def _on_playlist_right_click(self, event):
        selection = self.playlist_listbox.curselection()
        if not selection:
            return

        # Ensure the clicked item is selected
        index = self.playlist_listbox.nearest(event.y)
        if index not in selection:
            self.playlist_listbox.selection_clear(0, tk.END)
            self.playlist_listbox.selection_set(index)
            selection = (index,)

        playlists = self.playlist_service.get_all_playlists()
        selected_playlists = [playlists[i] for i in selection if i < len(playlists)]

        if not selected_playlists:
            return

        menu = self.theme_provider.create_manager_context_menu(self.playlist_window)

        menu.add_command(label="⊞  Open in Gallery",
                         command=lambda: self._open_grid_view_for_playlists(selected_playlists))

        if len(selected_playlists) == 1:
            menu.add_separator()
            menu.add_command(label="✎  Edit Info", command=self._edit_playlist_info)

        menu.add_separator()
        menu.add_command(label="✕  Delete", command=self._delete_playlist)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _open_grid_view_for_playlists(self, playlists):
        if not self.grid_view_manager:
            self.theme_provider.toast.warning("Warning", "Grid view not available")
            return

        all_videos = []
        for pl in playlists:
            all_videos.extend(pl.videos)

        # Remove duplicates while preserving order
        seen = set()
        unique_videos = []
        for v in all_videos:
            if v not in seen:
                seen.add(v)
                unique_videos.append(v)

        if not unique_videos:
            self.theme_provider.toast.warning("Warning", "No videos found in selected playlists")
            return

        self.grid_view_manager.show_grid_view(unique_videos, self.video_preview_manager)

    def play_from_global(self):
        """Called by the global Play Videos button."""
        if self.current_playlist and self.current_playlist.videos and self.on_play_callback:
            self.on_play_callback(self.current_playlist.videos)

    def _on_close(self):
        try:
            if hasattr(self, '_right_click_binding') and self._right_click_binding:
                self.video_tree.unbind_all('<Button-3>')
        except Exception:
            pass

        if self.playlist_window and self.playlist_window.winfo_exists():
            self.playlist_window.destroy()
        self.playlist_window = None
        if self._embedded and self._close_callback:
            self._close_callback()

    def _on_mouse_down(self, event):
        if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
            self.video_preview_manager.tooltip.hide_preview()
        if self.video_tree.identify_region(event.x, event.y) == "heading":
            return
        iid = self.video_tree.identify_row(event.y)
        if not self.current_playlist or not iid or iid == "empty":
            return
        index = int(iid)
        if index >= len(self.current_playlist.videos):
            return
        ctrl_held = bool(event.state & 0x4)
        shift_held = bool(event.state & 0x1)
        current_selection = list(self.video_tree.selection())
        if shift_held and current_selection:
            anchor = int(current_selection[-1])
            start, end = min(anchor, index), max(anchor, index)
            self.video_tree.selection_set(*[str(i) for i in range(start, end + 1)
                                            if self.video_tree.exists(str(i))])
            return "break"
        elif ctrl_held:
            if iid in current_selection:
                self.video_tree.selection_remove(iid)
            else:
                self.video_tree.selection_add(iid)
            return "break"
        else:
            self.video_tree.selection_set(iid)
            self.dragging_index = index
            return "break"

    def _on_mouse_drag(self, event):
        if self.dragging_index is None or not self.current_playlist or self._sort_col is not None:
            return
        iid = self.video_tree.identify_row(event.y)
        if not iid or iid == "empty":
            return
        current_index = int(iid)
        if current_index != self.dragging_index and 0 <= current_index < len(self.current_playlist.videos):
            videos = self.current_playlist.videos
            videos[self.dragging_index], videos[current_index] = videos[current_index], videos[self.dragging_index]
            self.video_tree.delete(*self.video_tree.get_children())
            self.video_mapping = {}
            for i, video in enumerate(videos):
                size_s = self._get_file_size(video)
                dur_s = self._duration_cache.get(video, "—")
                tag = "normal" if os.path.isfile(video) else "missing"
                self.video_tree.insert("", tk.END, iid=str(i),
                                       values=(i + 1, os.path.basename(video), os.path.normpath(os.path.dirname(video)), size_s, dur_s),
                                       tags=(tag,))
                self.video_mapping[i] = video
            self.dragging_index = current_index
            if self.video_tree.exists(str(current_index)):
                self.video_tree.selection_set(str(current_index))

    def _on_mouse_release(self, event):
        if self.dragging_index is not None and self.current_playlist:
            self.playlist_service.update_playlist(
                self.current_playlist.id, videos=self.current_playlist.videos)
        self.dragging_index = None

    def _on_mouse_motion(self, event):
        if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
            if self.video_preview_manager.tooltip.is_visible:
                iid = self.video_tree.identify_row(event.y)
                current_index = int(iid) if (iid and iid != "empty") else None
                if current_index != self.video_preview_manager.right_clicked_item:
                    self.video_preview_manager.tooltip.hide_preview()
                    self.video_preview_manager.right_clicked_item = None

    def _on_tree_hover(self, event):
        self._on_mouse_motion(event)
        iid = self.video_tree.identify_row(event.y)
        if iid == self._hovered_iid:
            return
        if self._hovered_iid and self.video_tree.exists(self._hovered_iid):
            self._restore_row_bg(self._hovered_iid)
        self._hovered_iid = iid
        if iid and iid != "empty" and iid not in self.video_tree.selection():
            try:
                self.video_tree.tag_configure("hover_row", background=self.theme_provider.hover_color)
                current_tags = [tg for tg in self.video_tree.item(iid, "tags") if tg != "hover_row"]
                self.video_tree.item(iid, tags=(*current_tags, "hover_row"))
            except (ValueError, tk.TclError):
                pass

    def _on_tree_leave(self, event):
        if self._hovered_iid and self.video_tree.exists(self._hovered_iid):
            self._restore_row_bg(self._hovered_iid)
        self._hovered_iid = None

    def _restore_row_bg(self, iid):
        try:
            current_tags = [tg for tg in self.video_tree.item(iid, "tags") if tg != "hover_row"]
            self.video_tree.item(iid, tags=current_tags)
        except Exception:
            pass

    def _on_mouse_leave(self, event):
        if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
            self.video_preview_manager.tooltip.hide_preview()

    def _on_combined_leave(self, event):
        self._on_tree_leave(event)
        self._on_mouse_leave(event)

    def _show_video_context_menu(self, event):
        selection = self._get_tv_selected_indices()
        if not selection:
            return
        context_menu = self.theme_provider.create_manager_context_menu(self.playlist_window)
        context_menu.add_command(
            label=f"Play Selected ({len(selection)} video{'s' if len(selection) > 1 else ''})",
            command=lambda: self._play_selected_from_context(selection))
        context_menu.add_separator()
        context_menu.add_command(label="Select All", command=self._select_all)
        context_menu.add_command(label="Clear Selection", command=self._unselect_all)
        context_menu.add_separator()
        context_menu.add_command(label="Open in Gallery",
                                 command=lambda: self._open_grid_view_from_selection(selection))
        if self.current_playlist:
            selected_videos = [self.current_playlist.videos[i] for i in selection
                               if 0 <= i < len(self.current_playlist.videos)
                               and os.path.isfile(self.current_playlist.videos[i])]
            if self.add_to_favorites_callback and selected_videos:
                context_menu.add_command(label="Add to Favourites",
                                         command=lambda v=selected_videos: self.add_to_favorites_callback(v))
            if self.add_to_queue_callback and selected_videos:
                context_menu.add_command(label="Add to Queue",
                                         command=lambda v=selected_videos: self.add_to_queue_callback(v))
        context_menu.add_separator()
        context_menu.add_command(label="Remove from Playlist", command=self._remove_selected_videos)
        if len(selection) == 1 and self.current_playlist:
            video_path = self.current_playlist.videos[selection[0]]
            context_menu.add_separator()
            context_menu.add_command(label="Copy Path",
                                     command=lambda: self._copy_path(video_path))
            context_menu.add_command(label="Open File Location",
                                     command=lambda: self._open_location(video_path))
            if self.locate_in_panel_callback and os.path.isfile(video_path):
                context_menu.add_command(label="Show in Panel",
                                         command=lambda p=video_path: self.locate_in_panel_callback(p))
        try:
            context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            context_menu.grab_release()

    def _on_video_right_click(self, event):
        if not self.current_playlist:
            return
        iid = self.video_tree.identify_row(event.y)
        if not iid or iid == "empty":
            return
        index = int(iid)
        selection = self._get_tv_selected_indices()
        if selection and index in selection:
            self._show_video_context_menu(event)
            return
        if 0 <= index < len(self.current_playlist.videos):
            video_path = self.current_playlist.videos[index]
            if os.path.isfile(video_path) and self.video_preview_manager:
                self.video_preview_manager.tooltip.hide_preview()
                self.video_preview_manager.right_clicked_item = index
                self.video_preview_manager._show_video_preview(video_path, event.x_root, event.y_root)

    def _play_selected_from_context(self, selection):
        if not self.current_playlist:
            return
        videos_to_play = [self.current_playlist.videos[i] for i in selection
                          if 0 <= i < len(self.current_playlist.videos)
                          and os.path.exists(self.current_playlist.videos[i])]
        if videos_to_play and self.on_play_callback:
            self.on_play_callback(videos_to_play)

    def _open_grid_view_from_selection(self, selection):
        if not self.current_playlist or not hasattr(self, 'grid_view_manager') or not self.grid_view_manager:
            return
        videos = [self.current_playlist.videos[i] for i in selection
                  if 0 <= i < len(self.current_playlist.videos)
                  and os.path.exists(self.current_playlist.videos[i])]
        if videos:
            self.grid_view_manager.show_grid_view(videos, self.video_preview_manager)

    def apply_filter_sort(self, filter_sort_manager):
        if not self.current_playlist or not self.current_playlist.videos:
            return
        video_paths = [v for v in self.current_playlist.videos if os.path.exists(v)]
        if not video_paths:
            return
        import threading
        def process():
            try:
                filtered = filter_sort_manager.apply_filter_and_sort(video_paths, load_properties=True)
                self.parent.after(0, lambda: self._apply_filtered_tree(filtered))
            except Exception as e:
                print(f"[PlaylistUI] filter_sort error: {e}")
        threading.Thread(target=process, daemon=True).start()

    def _apply_filtered_tree(self, filtered_paths):
        if not self.video_tree or not self.video_tree.winfo_exists():
            return
        if not self.current_playlist:
            return
        filtered_set = {p: i for i, p in enumerate(filtered_paths)}
        all_videos = self.current_playlist.videos
        entries = [(orig_idx, v) for orig_idx, v in enumerate(all_videos) if v in filtered_set]
        entries.sort(key=lambda t: filtered_set[t[1]])
        self.video_tree.delete(*self.video_tree.get_children())
        self.video_mapping = {}
        if not entries:
            self.video_tree.insert("", tk.END, iid="empty",
                                   values=("", "No videos match the current filters.", "", "", ""),
                                   tags=("missing",))
            return
        for i, (orig_idx, video) in enumerate(entries):
            size_str = self._get_file_size(video)
            dur_str = self._duration_cache.get(video, "—")
            tag = "normal" if os.path.isfile(video) else "missing"
            self.video_tree.insert("", tk.END, iid=str(orig_idx),
                                   values=(i + 1, os.path.basename(video),
                                           os.path.normpath(os.path.dirname(video)),
                                           size_str, dur_str),
                                   tags=(tag,))
            self.video_mapping[orig_idx] = video
            if video not in self._duration_cache:
                self._fetch_duration_async(video, str(orig_idx))

    def _open_grid_view(self):
        """Open grid view with all playlist videos"""
        if not self.current_playlist or not self.current_playlist.videos:
            self.theme_provider.toast.warning("Warning", "No videos in playlist")
            return

        if not hasattr(self, 'grid_view_manager') or not self.grid_view_manager:
            self.theme_provider.toast.warning("Warning", "Grid view not available")
            return

        valid_videos = [v for v in self.current_playlist.videos if os.path.exists(v)]
        if valid_videos:
            self.grid_view_manager.show_grid_view(valid_videos, self.video_preview_manager)
        else:
            self.theme_provider.toast.warning("Warning", "No valid videos found")

    def _shuffle_current_playlist(self):
        if not self.current_playlist:
            return
        import random
        videos = list(self.current_playlist.videos)
        random.shuffle(videos)
        self.playlist_service.update_playlist(self.current_playlist.id, videos=videos)
        self.current_playlist.videos = videos
        self._refresh_video_list()

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

    def _refresh_playlist_list(self):
        def refresh():
            if not self.playlist_listbox or not self.playlist_listbox.winfo_exists():
                return
            current_selection = self.playlist_listbox.curselection()
            current_playlist_id = None
            if current_selection and self.current_playlist:
                current_playlist_id = self.current_playlist.id

            self.playlist_listbox.delete(0, tk.END)
            playlists = self.playlist_service.get_all_playlists()

            selection_to_restore = None
            for i, playlist in enumerate(playlists):
                display_text = f"{playlist.name} ({len(playlist.videos)} videos)"
                self.playlist_listbox.insert(tk.END, display_text)

                if current_playlist_id and playlist.id == current_playlist_id:
                    selection_to_restore = i

            if not playlists:
                self.playlist_listbox.insert(tk.END, "No playlists created yet")
                self.current_playlist = None
                self.playlist_info_label.config(text="Select a playlist to view videos")
            elif selection_to_restore is not None:
                self.playlist_listbox.selection_set(selection_to_restore)
                self.playlist_listbox.activate(selection_to_restore)

        if threading.current_thread() is threading.main_thread():
            refresh()
        else:
            self.parent.after(0, refresh)

    def _on_video_double_click(self, event):
        if not self.current_playlist:
            return
        if self.video_tree.identify_region(event.x, event.y) != "cell":
            return
        iid = self.video_tree.identify_row(event.y)
        if not iid or iid == "empty":
            return
        index = int(iid)
        if 0 <= index < len(self.current_playlist.videos):
            video_path = self.current_playlist.videos[index]
            if not os.path.exists(video_path):
                self.theme_provider.toast.warning("File Not Found", f"Video file not found:\n{video_path}")
                return
            if self.on_play_callback:
                self.on_play_callback(self.current_playlist.videos[index:])

    def _refresh_video_list(self):
        def refresh():
            if not self.video_tree or not self.video_tree.winfo_exists():
                return
            self.video_tree.delete(*self.video_tree.get_children())
            self.video_mapping = {}

            if not self.current_playlist:
                return

            videos = self.current_playlist.videos
            if not videos:
                self.video_tree.insert("", tk.END, iid="empty",
                                       values=("", "No videos in this playlist.", "", "", ""),
                                       tags=("missing",))
                return

            rows = []
            for i, video in enumerate(videos):
                size_str = self._get_file_size(video)
                dur_str = self._duration_cache.get(video, "—")
                rows.append((i, i + 1, os.path.basename(video), os.path.normpath(os.path.dirname(video)),
                             size_str, dur_str))
                self.video_mapping[i] = video

            if self._sort_col:
                if self._sort_col == "size":
                    def _sk(r):
                        try:
                            return os.path.getsize(videos[r[0]])
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
                self.video_tree.heading(cid, text=lbl + (arrow[self._sort_rev] if self._sort_col == cid else ""))

            for orig_idx, num, name, dirpath, size_s, dur_s in rows:
                tag = "normal" if os.path.isfile(videos[orig_idx]) else "missing"
                self.video_tree.insert("", tk.END, iid=str(orig_idx),
                                       values=(num, name, dirpath, size_s, dur_s), tags=(tag,))
                if videos[orig_idx] not in self._duration_cache:
                    self._fetch_duration_async(videos[orig_idx], str(orig_idx))

        if threading.current_thread() is threading.main_thread():
            refresh()
        else:
            self.parent.after(0, refresh)

    def _on_playlist_select(self, event):
        # Prevent recursive calls
        if hasattr(self, '_selecting_playlist'):
            return

        selection = self.playlist_listbox.curselection()
        if not selection:
            return

        playlists = self.playlist_service.get_all_playlists()
        if selection[0] >= len(playlists):
            return

        self._selecting_playlist = True
        try:
            self.current_playlist = playlists[selection[0]]
            self._refresh_video_list()

            info_text = f"{self.current_playlist.name}"
            if self.current_playlist.description:
                info_text += f" - {self.current_playlist.description}"
            info_text += f" ({len(self.current_playlist.videos)} videos)"

            self.playlist_info_label.config(text=info_text)
        finally:
            delattr(self, '_selecting_playlist')

    def _create_new_playlist(self):
        dialog = PlaylistInfoDialog(self.playlist_window, self.theme_provider)
        result = dialog.show()

        if result:
            name, description = result
            self.playlist_service.create_playlist(name, description)
            if self.log_callback:
                self.log_callback(f"Playlist '{name}' created")
            self._refresh_playlist_list()
            self.theme_provider.toast.success("Playlist Created", f"'{name}' created")

    def _edit_playlist_info(self):
        if not self.current_playlist:
            return

        dialog = PlaylistInfoDialog(
            self.playlist_window,
            self.theme_provider,
            self.current_playlist.name,
            self.current_playlist.description
        )
        result = dialog.show()

        if result:
            name, description = result
            self.playlist_service.update_playlist(
                self.current_playlist.id,
                name=name,
                description=description
            )
            self.current_playlist.name = name
            self.current_playlist.description = description
            self._refresh_playlist_list()
            self._on_playlist_select(None)

    def _delete_playlist(self):
        if not self.current_playlist:
            self.theme_provider.toast.warning("Warning", "Please select a playlist to delete")
            return
        result = messagebox.askyesno(
            "Confirm Deletion",
            f"Are you sure you want to delete playlist '{self.current_playlist.name}'?",
            parent=self.playlist_window
        )

        if result:
            deleted_name = self.current_playlist.name
            self.playlist_service.delete_playlist(self.current_playlist.id)
            if self.log_callback:
                self.log_callback(f"Playlist '{deleted_name}' deleted")
            self.current_playlist = None
            self._refresh_playlist_list()
            self._refresh_video_list()
            self.playlist_info_label.config(text="Select a playlist to view videos")
            self.theme_provider.toast.success("Deleted", f"Playlist '{deleted_name}' deleted")

    def _remove_selected_videos(self):
        if not self.current_playlist:
            return
        selection = self._get_tv_selected_indices()
        if not selection:
            self.theme_provider.toast.warning("Warning", "Please select videos to remove")
            return
        for index in sorted(selection, reverse=True):
            if 0 <= index < len(self.current_playlist.videos):
                self.current_playlist.videos.pop(index)
        self.playlist_service.update_playlist(self.current_playlist.id, videos=self.current_playlist.videos)
        if self.log_callback:
            self.log_callback(
                f"Removed {len(selection)} video{'s' if len(selection) > 1 else ''} from '{self.current_playlist.name}'")
        self._refresh_video_list()
        self._refresh_playlist_list()
        self.theme_provider.toast.success("Removed",
                                          f"{len(selection)} video{'s' if len(selection) > 1 else ''} removed from '{self.current_playlist.name}'")

    def _play_playlist(self):
        if not self.current_playlist or not self.current_playlist.videos:
            self.theme_provider.toast.warning("Warning", "Playlist is empty or not selected")
            return

        if self.on_play_callback:
            self.on_play_callback(self.current_playlist.videos)

class PlaylistInfoDialog:
    """Dialog for editing playlist information"""

    def __init__(self, parent, theme_provider, name: str = "", description: str = ""):
        self.parent = parent
        self.theme_provider = theme_provider
        self.result = None
        self.name_entry = None
        self.description_entry = None

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("New Playlist")
        self.dialog.geometry("460x370")
        self.dialog.configure(bg=theme_provider.bg_color)
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()

        # Center the dialog
        self.dialog.geometry("+%d+%d" % (
            parent.winfo_rootx() + 50,
            parent.winfo_rooty() + 50
        ))

        self._setup_dialog(name, description)
        from icon_helper import apply_icon
        apply_icon(self.dialog)
        self.dialog.deiconify()

    def _setup_dialog(self, name: str, description: str):
        tp = self.theme_provider
        t = tp.get_manager_design_tokens()
        ACCENT = t["playlist_accent"]
        BG = t["bg"]
        SURFACE = t["surface"]
        SURFACE2 = t["surface2"]

        self.dialog.geometry("460x320")
        self.dialog.configure(bg=BG)

        # Header
        header = tk.Frame(self.dialog, bg=SURFACE, height=64)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        h_inner = tk.Frame(header, bg=SURFACE)
        h_inner.pack(fill=tk.BOTH, expand=True, padx=20)
        tk.Label(h_inner, text="♪", font=("Segoe UI Emoji", 16),
                 bg=SURFACE, fg=ACCENT).pack(side=tk.LEFT, pady=16, padx=(0, 10))
        title_text = "Edit Playlist" if name else "New Playlist"
        tk.Label(h_inner, text=title_text, font=("Segoe UI", 13, "bold"),
                 bg=SURFACE, fg=t["text"]).pack(side=tk.LEFT, pady=16)
        tk.Frame(self.dialog, bg=t["divider"], height=1).pack(fill=tk.X)

        # Body
        body = tk.Frame(self.dialog, bg=BG, padx=24, pady=20)
        body.pack(fill=tk.BOTH, expand=True)

        # Name field
        tk.Label(body, text="NAME", font=("Segoe UI", 8, "bold"),
                 bg=BG, fg=t["text_muted"]).pack(anchor="w", pady=(0, 5))
        name_wrap = tk.Frame(body, bg=SURFACE2,
                             highlightbackground=t["border"], highlightthickness=1)
        name_wrap.pack(fill=tk.X, pady=(0, 14))
        self.name_entry = tk.Entry(name_wrap, font=("Segoe UI", 10),
                                   bg=SURFACE2, fg=t["text"],
                                   insertbackground=t["text"],
                                   relief=tk.FLAT, bd=0)
        self.name_entry.pack(fill=tk.X, padx=10, pady=8)
        self.name_entry.insert(0, name)

        def _on_name_focus_in(e):
            name_wrap.config(highlightbackground=ACCENT)

        def _on_name_focus_out(e):
            name_wrap.config(highlightbackground=t["border"])

        self.name_entry.bind("<FocusIn>", _on_name_focus_in)
        self.name_entry.bind("<FocusOut>", _on_name_focus_out)

        # Description field
        tk.Label(body, text="DESCRIPTION  (optional)", font=("Segoe UI", 8, "bold"),
                 bg=BG, fg=t["text_muted"]).pack(anchor="w", pady=(0, 5))
        desc_wrap = tk.Frame(body, bg=SURFACE2,
                             highlightbackground=t["border"], highlightthickness=1)
        desc_wrap.pack(fill=tk.BOTH, expand=True, pady=(0, 16))
        self.description_entry = tk.Text(desc_wrap, font=("Segoe UI", 10),
                                         bg=SURFACE2, fg=t["text"],
                                         insertbackground=t["text"],
                                         relief=tk.FLAT, bd=0, height=3)
        self.description_entry.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        self.description_entry.insert("1.0", description)

        def _on_desc_focus_in(e):
            desc_wrap.config(highlightbackground=ACCENT)

        def _on_desc_focus_out(e):
            desc_wrap.config(highlightbackground=t["border"])

        self.description_entry.bind("<FocusIn>", _on_desc_focus_in)
        self.description_entry.bind("<FocusOut>", _on_desc_focus_out)

        # Buttons
        tk.Frame(body, bg=t["divider"], height=1).pack(fill=tk.X, pady=(0, 14))
        btn_row = tk.Frame(body, bg=BG)
        btn_row.pack(fill=tk.X)
        tp.create_modern_button(btn_row, "Cancel", self._cancel, "secondary", "md").pack(side=tk.RIGHT, padx=(8, 0))
        tp.create_modern_button(btn_row, "Save Playlist", self._ok, "playlist", "md").pack(side=tk.RIGHT)

        self.name_entry.focus_set()
        self.dialog.bind("<Return>", lambda e: self._ok())
        self.dialog.bind("<Escape>", lambda e: self._cancel())

    def _ok(self):
        name = self.name_entry.get().strip()
        if not name:
            self.theme_provider.toast.warning("Warning", "Please enter a playlist name")
            return

        description = self.description_entry.get("1.0", tk.END).strip()
        self.result = (name, description)
        self.dialog.destroy()

    def _cancel(self):
        self.result = None
        self.dialog.destroy()

    def show(self):
        self.parent.wait_window(self.dialog)
        return self.result


class PlaylistManager:
    def __init__(self, parent, theme_provider):
        self.storage = PlaylistStorage()
        self.service = PlaylistService(self.storage)
        self.ui = PlaylistUI(parent, theme_provider, self.service, self._on_play_playlist, log_callback=self._log)

        self._play_callback = None
        self._log_callback = None

    def set_log_callback(self, callback: Callable):
        self._log_callback = callback
        self.ui.log_callback = callback

    def _log(self, message: str):
        if self._log_callback:
            self._log_callback(message)

    def set_play_callback(self, callback: Callable):
        self._play_callback = callback

    def set_video_preview_manager(self, preview_manager):
        self.ui.video_preview_manager = preview_manager

    def set_grid_view_manager(self, grid_view_manager):
        self.ui.grid_view_manager = grid_view_manager

    def set_add_to_favorites_callback(self, callback):
        self.ui.add_to_favorites_callback = callback

    def set_add_to_queue_callback(self, callback):
        self.ui.add_to_queue_callback = callback

    def set_locate_in_panel_callback(self, callback):
        self.ui.locate_in_panel_callback = callback

    def show_manager(self):
        self.ui.show_playlist_manager()

    def show_embedded(self, parent, close_callback=None):
        self.ui.show_playlist_manager_embedded(parent, close_callback)
        return self.ui

    def add_videos_to_playlist(self, videos: List[str], selected_videos: List[str] = None):
        if not videos and not selected_videos:
            self.ui.theme_provider.toast.warning("Warning", "No videos to add to playlist")
            return

        videos_to_add = selected_videos if selected_videos else videos

        playlists = self.service.get_all_playlists()

        if not playlists:
            dialog = PlaylistInfoDialog(self.ui.parent, self.ui.theme_provider)
            result = dialog.show()

            if result:
                name, description = result
                self.service.create_playlist(name, description, videos_to_add)
                self._log(f"Playlist '{name}' created with {len(videos_to_add)} videos")
                self.ui._refresh_playlist_list()
        else:
            self._show_add_to_playlist_dialog(videos_to_add, playlists)

    def _show_add_to_playlist_dialog(self, videos: list, playlists: list):
        tp = self.ui.theme_provider
        t = tp.get_manager_design_tokens()
        ACCENT = t["playlist_accent"]
        BG = t["bg"]
        SURFACE = t["surface"]
        SURFACE2 = t["surface2"]

        dialog = tk.Toplevel(self.ui.parent)
        dialog.withdraw()
        dialog.title("Add to Playlist")
        dialog.geometry("440x400")
        dialog.minsize(360, 320)
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        dialog.transient(self.ui.parent)
        dialog.grab_set()

        dialog.update_idletasks()
        px = self.ui.parent.winfo_rootx() + (self.ui.parent.winfo_width() - 440) // 2
        py = self.ui.parent.winfo_rooty() + (self.ui.parent.winfo_height() - 400) // 2
        dialog.geometry(f"440x400+{max(0, px)}+{max(0, py)}")

        # Header
        header = tk.Frame(dialog, bg=SURFACE, height=64)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        h_inner = tk.Frame(header, bg=SURFACE)
        h_inner.pack(fill=tk.BOTH, expand=True, padx=20)
        tk.Label(h_inner, text="♪", font=("Segoe UI Emoji", 16),
                 bg=SURFACE, fg=ACCENT).pack(side=tk.LEFT, pady=16, padx=(0, 10))
        tk.Label(h_inner, text="Add to Playlist", font=("Segoe UI", 13, "bold"),
                 bg=SURFACE, fg=t["text"]).pack(side=tk.LEFT, pady=16)
        count_badge = tk.Label(h_inner,
                               text=f" {len(videos)} video{'s' if len(videos) != 1 else ''} ",
                               font=("Segoe UI", 9), bg=ACCENT, fg="#FFFFFF",
                               padx=6, pady=2)
        count_badge.pack(side=tk.LEFT, padx=(10, 0), pady=20)
        tk.Frame(dialog, bg=t["divider"], height=1).pack(fill=tk.X)

        # Body
        body = tk.Frame(dialog, bg=BG, padx=20, pady=16)
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(body, text="SELECT PLAYLIST", font=("Segoe UI", 8, "bold"),
                 bg=BG, fg=t["text_muted"]).pack(anchor="w", pady=(0, 8))

        # List card
        card = tk.Frame(body, bg=SURFACE2,
                        highlightbackground=t["border"], highlightthickness=1)
        card.pack(fill=tk.BOTH, expand=True, pady=(0, 16))

        sb = ttk.Scrollbar(card, orient=tk.VERTICAL, style="ExclusionTree.Vertical.TScrollbar")
        sb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 1), pady=1)

        playlist_listbox = tk.Listbox(
            card, yscrollcommand=sb.set, font=("Segoe UI", 10),
            bg=SURFACE2, fg=t["listbox_fg"],
            selectbackground=ACCENT, selectforeground="#FFFFFF",
            activestyle="none", relief=tk.FLAT, bd=0, highlightthickness=0,
            cursor="hand2")
        playlist_listbox.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        sb.config(command=playlist_listbox.yview)

        for pl in playlists:
            count = len(pl.videos)
            playlist_listbox.insert(tk.END, f"  {pl.name}  ·  {count} video{'s' if count != 1 else ''}")

        tk.Frame(body, bg=t["divider"], height=1).pack(fill=tk.X, pady=(0, 12))

        btn_row = tk.Frame(body, bg=BG)
        btn_row.pack(fill=tk.X)

        def create_new():
            dialog.destroy()
            info_dialog = PlaylistInfoDialog(self.ui.parent, tp)
            result = info_dialog.show()
            if result:
                name, desc = result
                self.service.create_playlist(name, desc, videos)
                self._log(f"Playlist '{name}' created with {len(videos)} videos")
                self.ui._refresh_playlist_list()

        def add_to_existing():
            sel = playlist_listbox.curselection()
            if not sel:
                self.ui.theme_provider.toast.warning("Warning", "Please select a playlist")
                return
            chosen = playlists[sel[0]]
            self.service.add_videos_to_playlist(chosen.id, videos)
            self._log(f"Added {len(videos)} videos to '{chosen.name}'")
            dialog.destroy()
            self.ui._refresh_playlist_list()

        tp.create_modern_button(btn_row, "+ New Playlist", create_new, "secondary", "md").pack(side=tk.LEFT)
        tp.create_modern_button(btn_row, "Cancel", dialog.destroy, "secondary", "md").pack(side=tk.RIGHT, padx=(8, 0))
        tp.create_modern_button(btn_row, "Add to Selected", add_to_existing, "playlist", "md").pack(side=tk.RIGHT)

        from icon_helper import apply_icon
        apply_icon(dialog)
        dialog.deiconify()
        self.ui.parent.wait_window(dialog)

    def _on_play_playlist(self, videos: List[str]):
        """Handle playlist playback"""
        if self._play_callback:
            self._play_callback(videos)
