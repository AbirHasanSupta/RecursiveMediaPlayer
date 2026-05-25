import json
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict
import uuid

from managers.resource_manager import get_resource_manager
from utils import _responsive_geometry


def _get_app_dirs():
    import os, sys
    from pathlib import Path
    APP = "Recursive Media Player"
    if os.name == "nt":
        settings = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP
    elif sys.platform == "darwin":
        settings = Path.home() / "Library" / "Application Support" / APP
        local = Path.home() / "Library" / "Caches" / APP
    else:
        settings = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP
        local = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / APP
    return settings, local


class WatchHistoryEntry:

    def __init__(self, video_path: str, watched_at: str = None, duration_watched: int = 0,
                 total_duration: int = 0, completion_percentage: float = 0.0):
        self.id = str(uuid.uuid4())
        self.video_path = os.path.normpath(video_path)
        self.watched_at = watched_at or datetime.now().isoformat()
        self.duration_watched = duration_watched
        self.total_duration = total_duration
        self.completion_percentage = completion_percentage
        self.video_name = os.path.basename(self.video_path)
        self.directory_path = os.path.dirname(self.video_path)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'video_path': self.video_path,
            'watched_at': self.watched_at,
            'duration_watched': self.duration_watched,
            'total_duration': self.total_duration,
            'completion_percentage': self.completion_percentage,
            'video_name': self.video_name,
            'directory_path': self.directory_path
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'WatchHistoryEntry':
        entry = cls(
            video_path=data.get('video_path', ''),
            watched_at=data.get('watched_at'),
            duration_watched=data.get('duration_watched', 0),
            total_duration=data.get('total_duration', 0),
            completion_percentage=data.get('completion_percentage', 0.0)
        )
        entry.id = data.get('id', str(uuid.uuid4()))
        return entry

    def get_watch_date_formatted(self) -> str:
        try:
            dt = datetime.fromisoformat(self.watched_at)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            return self.watched_at

    def get_duration_formatted(self) -> str:
        if self.duration_watched == 0:
            return "Not tracked"

        hours = self.duration_watched // 3600
        minutes = (self.duration_watched % 3600) // 60
        seconds = self.duration_watched % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"

    def is_recently_watched(self, hours: int = 24) -> bool:
        try:
            watched_time = datetime.fromisoformat(self.watched_at)
            return datetime.now() - watched_time < timedelta(hours=hours)
        except:
            return False


class WatchHistoryStorage:

    def __init__(self):
        self.history_dir = _get_app_dirs()[1] / "History"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = self.history_dir / "watch_history.json"
        self.max_entries = 10000

    def save_history(self, entries: List[WatchHistoryEntry]) -> bool:
        try:
            sorted_entries = sorted(entries, key=lambda x: x.watched_at, reverse=True)
            limited_entries = sorted_entries[:self.max_entries]

            data = [entry.to_dict() for entry in limited_entries]
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving watch history: {e}")
            return False

    def load_history(self) -> List[WatchHistoryEntry]:
        try:
            if not self.history_file.exists():
                return []

            with open(self.history_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            entries = [WatchHistoryEntry.from_dict(item) for item in data]
            return sorted(entries, key=lambda x: x.watched_at, reverse=True)
        except Exception as e:
            print(f"Error loading watch history: {e}")
            return []


class WatchHistoryService:

    def __init__(self, storage: WatchHistoryStorage):
        self.storage = storage
        self._history: List[WatchHistoryEntry] = []
        self._lock = threading.RLock()
        self._load_history()
        get_resource_manager().register_cleanup_callback(self._cleanup)

    def _cleanup(self):
        try:
            with self._lock:
                self._history.clear()
        except:
            pass

    def _load_history(self):
        self._history = self.storage.load_history()
        with self._lock:
            if self._history:
                seen_videos = {}
                to_remove = []

                for entry in self._history:
                    if entry.video_path not in seen_videos:
                        seen_videos[entry.video_path] = []
                    seen_videos[entry.video_path].append(entry)

                for path, entries in seen_videos.items():
                    if len(entries) < 2:
                        continue

                    kept_entry = entries[0]
                    for other_entry in entries[1:]:
                        try:
                            t1 = datetime.fromisoformat(kept_entry.watched_at)
                            t2 = datetime.fromisoformat(other_entry.watched_at)

                            is_identical = (kept_entry.duration_watched == other_entry.duration_watched and
                                            kept_entry.total_duration == other_entry.total_duration)

                            if is_identical or abs((t1 - t2).total_seconds()) < 300:
                                to_remove.append(other_entry)
                            else:
                                kept_entry = other_entry
                        except:
                            continue

                if to_remove:
                    for entry in to_remove:
                        if entry in self._history:
                            self._history.remove(entry)
                    self.storage.save_history(self._history)

    def get_all_history(self) -> List[WatchHistoryEntry]:
        with self._lock:
            return self._history.copy()

    def add_watch_entry(self, video_path: str, duration_watched: int = 0,
                        total_duration: int = 0) -> WatchHistoryEntry:
        if duration_watched < 2 and total_duration > 10:
            with self._lock:
                video_path_norm = os.path.normpath(video_path)
                for entry in self._history:
                    if entry.video_path == video_path_norm:
                        return entry

        with self._lock:
            video_path_norm = os.path.normpath(video_path)
            now = datetime.now()

            recent_entry = None
            for entry in self._history:
                if entry.video_path == video_path_norm:
                    try:
                        watched_at = datetime.fromisoformat(entry.watched_at)
                        if (now - watched_at).total_seconds() < 300:
                            recent_entry = entry
                            break
                    except:
                        continue

            if recent_entry:
                recent_entry.duration_watched = duration_watched
                recent_entry.total_duration = total_duration
                if total_duration > 0:
                    recent_entry.completion_percentage = (duration_watched / total_duration) * 100
                recent_entry.watched_at = now.isoformat()

                self._history.remove(recent_entry)
                self._history.insert(0, recent_entry)

                self.storage.save_history(self._history)
                return recent_entry

            completion_percentage = 0.0
            if total_duration > 0:
                completion_percentage = (duration_watched / total_duration) * 100

            entry = WatchHistoryEntry(
                video_path=video_path_norm,
                duration_watched=duration_watched,
                total_duration=total_duration,
                completion_percentage=completion_percentage
            )

            self._history.insert(0, entry)
            self.storage.save_history(self._history)
            return entry

    def update_entry(self, entry_id: str, duration_watched: int, total_duration: int) -> bool:
        with self._lock:
            for entry in self._history:
                if entry.id == entry_id:
                    entry.duration_watched = duration_watched
                    entry.total_duration = total_duration
                    if total_duration > 0:
                        entry.completion_percentage = (duration_watched / total_duration) * 100
                    entry.watched_at = datetime.now().isoformat()
                    self._history.remove(entry)
                    self._history.insert(0, entry)
                    self.storage.save_history(self._history)
                    return True
            return False

    def remove_entry(self, entry_id: str) -> bool:
        with self._lock:
            for entry in self._history:
                if entry.id == entry_id:
                    self._history.remove(entry)
                    self.storage.save_history(self._history)
                    return True
            return False

    def remove_entries(self, entry_ids: List[str]) -> int:
        with self._lock:
            removed_count = 0
            entries_to_remove = []

            for entry in self._history:
                if entry.id in entry_ids:
                    entries_to_remove.append(entry)

            for entry in entries_to_remove:
                self._history.remove(entry)
                removed_count += 1

            if removed_count > 0:
                self.storage.save_history(self._history)

            return removed_count

    def clear_all_history(self) -> bool:
        with self._lock:
            self._history.clear()
            self.storage.save_history(self._history)
            return True

    def get_history_by_date_range(self, days: int) -> List[WatchHistoryEntry]:
        with self._lock:
            cutoff_date = (datetime.now() - timedelta(days=days)).date()
            return [entry for entry in self._history
                    if datetime.fromisoformat(entry.watched_at).date() >= cutoff_date]

    def get_unique_videos_count(self) -> int:
        with self._lock:
            unique_paths = set(entry.video_path for entry in self._history)
            return len(unique_paths)

    def cleanup_old_entries(self, days: int) -> int:
        with self._lock:
            cutoff_date = datetime.now() - timedelta(days=days)
            entries_to_remove = []

            for entry in self._history:
                try:
                    entry_date = datetime.fromisoformat(entry.watched_at)
                    if entry_date < cutoff_date:
                        entries_to_remove.append(entry)
                except:
                    entries_to_remove.append(entry)

            for entry in entries_to_remove:
                self._history.remove(entry)

            if entries_to_remove:
                self.storage.save_history(self._history)

            return len(entries_to_remove)


class WatchHistoryUI:

    def __init__(self, parent, theme_provider, history_service: WatchHistoryService):
        self.parent = parent
        self.theme_provider = theme_provider
        self.history_service = history_service

        self.history_window = None
        self.history_listbox = None
        self.current_entries: List[WatchHistoryEntry] = []
        self.filter_var = None
        self.directory_filter: List[str] = []
        self.video_preview_manager = None
        self._embedded = False
        self._close_callback = None
        self.grid_view_manager = None
        self.add_to_playlist_callback = None
        self.add_to_queue_callback = None
        self.add_to_favourites_callback = None
        self.remove_from_favourites_callback = None
        self.is_favourite_callback = None
        self.locate_in_panel_callback = None
        self.theme_provider.register_manager_ui(self)

    def _get_design_tokens(self):
        return self.theme_provider.get_manager_design_tokens()

    def show_history_manager(self):
        if self.history_window and self.history_window.winfo_exists():
            self.history_window.lift()
            return

        self._embedded = False
        self._close_callback = None
        self.history_window = tk.Toplevel(self.parent)
        self.history_window.withdraw()
        self.history_window.title("Watch History")
        self.history_window.geometry(_responsive_geometry(self.parent, 1600, 900))
        self.history_window.configure(bg=self.theme_provider.bg_color)

        self._setup_history_ui()
        self._refresh_history_list()

        from icon_helper import apply_icon
        apply_icon(self.history_window)
        self.history_window.deiconify()

    def set_directory_filter(self, directories: List[str] = None):
        self.directory_filter = [os.path.normpath(d) for d in (directories or [])]

    def refresh(self):
        if self.history_window and self.history_window.winfo_exists():
            self._refresh_history_list()

    def show_history_manager_embedded(self, parent, close_callback=None):
        if self.history_window and self.history_window.winfo_exists():
            self.history_window.destroy()
        for child in parent.winfo_children():
            child.destroy()
        self._embedded = True
        self._close_callback = close_callback
        self.history_window = tk.Frame(parent, bg=self.theme_provider.bg_color)
        self.history_window.pack(fill=tk.BOTH, expand=True)
        self._setup_history_ui()
        self._refresh_history_list()

    def _close_history(self):
        if self.history_window and self.history_window.winfo_exists():
            self.history_window.destroy()
        self.history_window = None
        if self._embedded and self._close_callback:
            self._close_callback()

    def apply_theme(self):
        win = self.history_window
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
        for attr in ("_hist_header", "_hist_body", "_hist_card", "_hist_filter_row", "_hist_btn_row"):
            w = getattr(self, attr, None)
            if w is None:
                continue
            role = getattr(w, "_manager_role", "body")
            bg = t.get({"header": "header_bg", "surface": "surface", "surface2": "surface2", "body": "bg"}.get(role, "bg"), t["bg"])
            try:
                w.configure(bg=bg)
            except tk.TclError:
                pass
        if hasattr(self, "stats_label"):
            self.stats_label.configure(bg=t["header_bg"], fg=t["text_muted"])
        self._restyle_filter_buttons()
        self._restyle_treeview()
        if hasattr(self, '_hist_scrollbar'):
            try:
                tp = self.theme_provider
                trough = tp.bg_color if tp.dark_mode else tp.alt_row_color
                scroll_bg = tp.border_color
                scroll_active = tp.hover_color
                style = ttk.Style()
                self._hist_scrollbar.configure(style="ExclusionTree.Vertical.TScrollbar")
                style.configure("ExclusionTree.Vertical.TScrollbar",
                                background=scroll_bg, troughcolor=trough,
                                bordercolor=tp.border_color, arrowcolor=tp.text_muted,
                                darkcolor=tp.border_color, lightcolor=tp.surface_color,
                                relief="flat", gripcount=0)
                style.map("ExclusionTree.Vertical.TScrollbar",
                          background=[("active", scroll_active),
                                      ("pressed", tp.accent_color),
                                      ("disabled", scroll_bg)],
                          arrowcolor=[("active", tp.text_color), ("pressed", "#FFFFFF")])
            except Exception:
                pass
        tp.restyle_manager_buttons(win)
        tp.restyle_manager_action_links(win)

    def _restyle_filter_buttons(self):
        t = self._get_design_tokens()
        tp = self.theme_provider
        if not hasattr(self, "filter_buttons"):
            return
        cur = self.filter_var.get() if self.filter_var else "all"
        for btn, val in self.filter_buttons:
            try:
                if val == cur:
                    btn.config(
                        bg=t["accent"], fg="#FFFFFF",
                        relief=tk.FLAT,
                        highlightbackground=t["accent"], highlightthickness=1,
                    )
                else:
                    btn.config(
                        bg=t["surface2"], fg=t["text"],
                        relief=tk.FLAT,
                        highlightbackground=t["border"], highlightthickness=1,
                    )
            except tk.TclError:
                pass

    def _restyle_treeview(self):
        if not hasattr(self, "history_tree"):
            return
        t = self._get_design_tokens()
        tp = self.theme_provider
        style = ttk.Style()
        style.theme_use("clam")
        try:
            style.element_create("Hist.customfield", "from", "default", "field")
        except tk.TclError:
            pass
        try:
            style.element_create("Hist.customheading", "from", "default", "field")
        except tk.TclError:
            pass
        style.layout("Hist.Treeview", [
            ("Hist.customfield", {"sticky": "nswe", "border": "2", "children": [
                ("Hist.Treeview.padding", {"sticky": "nswe", "children": [
                    ("Hist.Treeview.treearea", {"sticky": "nswe"})
                ]})
            ]})
        ])
        style.layout("Hist.Treeview.Heading", [
            ("Hist.customheading", {"sticky": "nswe", "children": [
                ("Treeheading.padding", {"sticky": "nswe", "children": [
                    ("Treeheading.label", {"sticky": "we"})
                ]})
            ]})
        ])
        style.configure("Hist.Treeview",
                        background=t["surface"], fieldbackground=t["surface"],
                        foreground=t["text"], rowheight=28,
                        borderwidth=0, relief="flat")
        style.configure("Hist.Treeview.Heading",
                        background=t["surface2"], fieldbackground=t["surface2"], foreground=t["text"],
                        font=(tp.small_font.actual()["family"], 9, "bold"),
                        relief="flat", borderwidth=0, padding=(6, 6))
        style.map("Hist.Treeview",
                  background=[("selected", t["accent"])],
                  foreground=[("selected", "white")],
                  fieldbackground=[("!selected", t["surface"])])
        style.map("Hist.Treeview.Heading",
                  background=[("active", t["surface2"])],
                  foreground=[("active", t["text"])])
        if hasattr(self, "_hist_card"):
            try:
                self._hist_card.configure(
                    bg=t["surface"],
                    highlightbackground=t["border"], highlightthickness=1,
                )
            except tk.TclError:
                pass

    def _setup_history_ui(self):
        tp = self.theme_provider
        t = self._get_design_tokens()

        header = tk.Frame(self.history_window, bg=t['header_bg'], height=58)
        header._manager_role = "header"
        self._hist_header = header
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        h_inner = tk.Frame(header, bg=t['header_bg'])
        h_inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=0)

        title_box = tk.Frame(h_inner, bg=t['header_bg'])
        title_box.pack(side=tk.LEFT, fill=tk.Y)

        tp_dark = tp.dark_mode
        history_accent = "#C39BD3" if tp_dark else "#9b59b6"
        tk.Label(title_box, text="🕐", font=("Segoe UI Emoji", 18),
                 bg=t['header_bg'], fg=history_accent).pack(side=tk.LEFT, padx=(0, 10), pady=14)
        tk.Label(title_box, text="Watch History",
                 font=("Segoe UI", 15, "bold"),
                 bg=t['header_bg'], fg=t['text']).pack(side=tk.LEFT, pady=14)

        if self._embedded and self._close_callback:
            close_btn = tk.Label(h_inner, text="✕", font=("Segoe UI", 14),
                                 bg=t['header_bg'], fg=t['text_muted'], cursor="hand2", padx=10)
            close_btn.pack(side=tk.RIGHT, pady=14)
            close_btn.bind("<Button-1>", lambda e: self._close_history())
            close_btn.bind("<Enter>", lambda e: close_btn.config(fg=t['accent_secondary']))
            close_btn.bind("<Leave>", lambda e: close_btn.config(fg=t['text_muted']))

        self.stats_label = tk.Label(h_inner, text="",
                                    font=tp.small_font, bg=t['header_bg'], fg=t['text_muted'])
        self.stats_label.pack(side=tk.RIGHT, padx=(10, 0))

        tk.Frame(self.history_window, bg=t['divider'], height=1).pack(fill=tk.X)

        filter_row = tk.Frame(self.history_window, bg=t['bg'])
        filter_row._manager_role = "body"
        self._hist_filter_row = filter_row
        filter_row.pack(fill=tk.X, padx=20, pady=(12, 0))

        tk.Label(filter_row, text="Filter by:", font=tp.small_font,
                 bg=t['bg'], fg=t['text_muted']).pack(side=tk.LEFT, padx=(0, 10))

        self.filter_var = tk.StringVar(value="all")
        self.filter_buttons = []

        filters = [("All time", "all"), ("Today", "today"),
                   ("7 days", "week"), ("30 days", "month")]

        for label_text, val in filters:
            lbl = tk.Label(filter_row, text=f"  {label_text}  ",
                           font=tp.small_font,
                           padx=4, pady=4,
                           cursor="hand2",
                           relief=tk.FLAT,
                           highlightthickness=1)
            lbl.pack(side=tk.LEFT, padx=3)

            is_active = (val == self.filter_var.get())
            if is_active:
                lbl.config(bg=t['accent'], fg="#FFFFFF",
                           highlightbackground=t['accent'])
            else:
                lbl.config(bg=t['surface2'], fg=t['text'],
                           highlightbackground=t['border'])

            self.filter_buttons.append((lbl, val))

            def click_handler(v=val):
                self.filter_var.set(v)
                self._restyle_filter_buttons()
                self._apply_filter()
                self._update_stats_label()

            def on_enter(e, btn=lbl, v=val):
                if self.filter_var.get() != v:
                    btn.config(bg=t['hover_color'] if hasattr(t, 'hover_color') else t['surface2'],
                               fg=t['accent'],
                               highlightbackground=t['accent'])

            def on_leave(e, btn=lbl, v=val):
                if self.filter_var.get() != v:
                    btn.config(bg=t['surface2'], fg=t['text'],
                               highlightbackground=t['border'])

            lbl.bind("<Button-1>", lambda e, h=click_handler: h())
            lbl.bind("<Enter>", on_enter)
            lbl.bind("<Leave>", on_leave)

        body = tk.Frame(self.history_window, bg=t['bg'])
        body._manager_role = "body"
        self._hist_body = body
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=12)

        card = tk.Frame(body, bg=t['surface'],
                        highlightbackground=t['border'], highlightthickness=1)
        card._manager_role = "surface"
        self._hist_card = card
        card.pack(fill=tk.BOTH, expand=True)

        style = ttk.Style()
        try:
            style.element_create("Hist.customfield", "from", "default", "field")
        except tk.TclError:
            pass
        try:
            style.element_create("Hist.customheading", "from", "default", "field")
        except tk.TclError:
            pass
        style.layout("Hist.Treeview", [
            ("Hist.customfield", {"sticky": "nswe", "border": "2", "children": [
                ("Hist.Treeview.padding", {"sticky": "nswe", "children": [
                    ("Hist.Treeview.treearea", {"sticky": "nswe"})
                ]})
            ]})
        ])
        style.layout("Hist.Treeview.Heading", [
            ("Hist.customheading", {"sticky": "nswe", "children": [
                ("Treeheading.padding", {"sticky": "nswe", "children": [
                    ("Treeheading.label", {"sticky": "we"})
                ]})
            ]})
        ])
        style.configure("Hist.Treeview",
                        background=t['surface'], fieldbackground=t['surface'],
                        foreground=t['text'], rowheight=28,
                        borderwidth=0, relief="flat")
        style.configure("Hist.Treeview.Heading",
                        background=t["surface2"], fieldbackground=t["surface2"], foreground=t["text"],
                        font=(tp.small_font.actual()["family"], 9, "bold"),
                        relief="flat", borderwidth=0, padding=(6, 6))
        style.map("Hist.Treeview",
                  background=[("selected", t['accent'])],
                  foreground=[("selected", "white")])

        columns = ("video", "directory", "watched_at", "duration", "completion")
        self.history_tree = ttk.Treeview(card, columns=columns,
                                         show="headings", style="Hist.Treeview")
        for col, heading, width, anchor in [
            ("video", "Video", 260, "w"),
            ("directory", "Directory", 190, "w"),
            ("watched_at", "Watched At", 160, "w"),
            ("duration", "Duration", 90, "center"),
            ("completion", "Completion", 90, "center"),
        ]:
            self.history_tree.heading(col, text=heading, anchor=anchor)
            self.history_tree.column(col, width=width, minwidth=70, anchor=anchor)

        vsb = ttk.Scrollbar(card, orient=tk.VERTICAL, command=self.history_tree.yview,
                            style="ExclusionTree.Vertical.TScrollbar")
        self.history_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.history_tree.configure(yscrollcommand=vsb.set)
        self._hist_scrollbar = vsb
        card.grid_rowconfigure(0, weight=1)
        card.grid_columnconfigure(0, weight=1)

        self.history_tree.bind("<Double-Button-1>", self._on_history_double_click)
        self.history_tree.bind("<Button-3>", self._on_history_right_click)
        self.history_tree.bind("<Button-1>", self._on_history_left_click)
        self.history_tree.bind("<Leave>", self._on_tree_leave)

        btn_container = tk.Frame(body, bg=t['bg'])
        btn_container._manager_role = "body"
        self._hist_btn_row = btn_container
        btn_container.pack(fill=tk.X, pady=(8, 0))

        hist_actions = tk.Frame(btn_container, bg=t["bg"])
        hist_actions.pack(side=tk.RIGHT)
        tp.create_manager_action_link(
            hist_actions, "↺  Refresh", self._refresh_history_list, style="secondary"
        ).pack(side=tk.LEFT)
        tp.create_manager_action_link(
            hist_actions, "✕  Clear all history", self._clear_all_history, style="warning"
        ).pack(side=tk.LEFT)

    def _update_stats_label(self):
        total = len(self.history_service.get_all_history())
        unique = self.history_service.get_unique_videos_count()
        shown = len(self.current_entries) if hasattr(self, "current_entries") else total
        text = f"{total} entries  •  {unique} unique"
        if shown != total:
            text += f"  •  showing {shown}"
        self.stats_label.config(text=text)

    def play_from_global(self):
        selection = self.history_tree.selection()
        if selection:
            videos = []
            for item in selection:
                tags = self.history_tree.item(item, 'tags')
                if tags:
                    entry_id = tags[0]
                    for entry in self.current_entries:
                        if entry.id == entry_id:
                            if os.path.isfile(entry.video_path):
                                videos.append(entry.video_path)
                            break
            if videos and self.play_callback:
                self.play_callback(videos)
        else:
            if self.current_entries and self.play_callback:
                self.play_callback([self.current_entries[0].video_path])

    def _refresh_history_list(self):
        def refresh():
            for item in self.history_tree.get_children():
                self.history_tree.delete(item)

            self._apply_filter()

            for i, entry in enumerate(self.current_entries):
                pct = f"{entry.completion_percentage:.0f}%" \
                    if entry.completion_percentage > 0 else "—"
                self.history_tree.insert("", tk.END, values=(
                    entry.video_name,
                    os.path.basename(entry.directory_path),
                    entry.get_watch_date_formatted(),
                    entry.get_duration_formatted(),
                    pct,
                ), tags=(entry.id,))

            self._update_stats_label()

        if threading.current_thread() is threading.main_thread():
            refresh()
        else:
            self.parent.after(0, refresh)

    def _on_history_left_click(self, event):
        if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
            self.video_preview_manager.tooltip.hide_preview()

    def _on_tree_leave(self, event):
        if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
            self.video_preview_manager.tooltip.hide_preview()

    def _on_history_right_click(self, event):
        item_id = self.history_tree.identify_row(event.y)
        if not item_id:
            return

        selection = self.history_tree.selection()
        if item_id in selection:
            self._show_history_context_menu(event)
            return

        tags = self.history_tree.item(item_id, 'tags')
        if tags and hasattr(self, 'video_preview_manager') and self.video_preview_manager:
            entry_id = tags[0]
            for entry in self.current_entries:
                if entry.id == entry_id and os.path.isfile(entry.video_path):
                    self.video_preview_manager.tooltip.hide_preview()
                    try:
                        idx = self.current_entries.index(entry)
                        self.video_preview_manager.right_clicked_item = idx
                        self.video_preview_manager._show_video_preview(
                            entry.video_path, event.x_root, event.y_root
                        )
                    except ValueError:
                        pass
                    break

    def _select_all(self, event=None):
        self.history_tree.selection_set(self.history_tree.get_children())
        return "break"

    def _unselect_all(self, event=None):
        self.history_tree.selection_remove(self.history_tree.selection())

    def _show_history_context_menu(self, event):
        selection = self.history_tree.selection()
        if not selection:
            return

        selected_entries = []
        for item_id in selection:
            tags = self.history_tree.item(item_id, 'tags')
            if tags:
                entry_id = tags[0]
                for entry in self.current_entries:
                    if entry.id == entry_id:
                        selected_entries.append(entry)
                        break

        if not selected_entries:
            return

        context_menu = self.theme_provider.create_manager_context_menu(self.history_window)

        context_menu.add_command(
            label=f"Play Selected ({len(selected_entries)} video{'s' if len(selected_entries) > 1 else ''})",
            command=lambda: self._play_selected_from_context(selected_entries)
        )

        context_menu.add_separator()
        context_menu.add_command(label="Select All", command=self._select_all)
        context_menu.add_command(label="Clear Selection", command=self._unselect_all)

        context_menu.add_separator()

        context_menu.add_command(
            label="Open in Gallery",
            command=lambda: self._open_grid_view_from_selection(selected_entries))
        context_menu.add_separator()

        if self.add_to_playlist_callback:
            context_menu.add_command(label="Add to Playlist",
                                     command=lambda es=selected_entries: self._context_add_to_playlist(es))
        if self.add_to_queue_callback:
            context_menu.add_command(label="Add to Queue",
                                     command=lambda es=selected_entries: self._context_add_to_queue(es))
        if self.is_favourite_callback and (self.add_to_favourites_callback or self.remove_from_favourites_callback):
            paths = [e.video_path for e in selected_entries]
            all_fav = all(self.is_favourite_callback(p) for p in paths)
            if all_fav and self.remove_from_favourites_callback:
                context_menu.add_command(label="Remove from Favourites",
                                         command=lambda es=selected_entries: self._context_remove_from_favourites(es))
            elif self.add_to_favourites_callback:
                context_menu.add_command(label="Add to Favourites",
                                         command=lambda es=selected_entries: self._context_add_to_favourites(es))

        context_menu.add_separator()

        context_menu.add_command(
            label="Remove from History",
            command=self._remove_selected
        )

        if len(selected_entries) == 1:
            entry = selected_entries[0]
            context_menu.add_separator()
            context_menu.add_command(
                label="Copy Path",
                command=lambda: self._copy_path(entry.video_path)
            )
            context_menu.add_command(
                label="Open File Location",
                command=lambda: self._open_location(entry.video_path)
            )
            context_menu.add_command(
                label="Properties",
                command=lambda: self._show_properties(entry)
            )
            if self.locate_in_panel_callback and os.path.isfile(entry.video_path):
                context_menu.add_command(
                    label="Show in Panel",
                    command=lambda p=entry.video_path: self.locate_in_panel_callback(p)
                )

        try:
            context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            context_menu.grab_release()

    def _context_add_to_playlist(self, entries):
        paths = [e.video_path for e in entries if os.path.isfile(e.video_path)]
        if paths and self.add_to_playlist_callback:
            self.add_to_playlist_callback(paths)

    def _context_add_to_queue(self, entries):
        paths = [e.video_path for e in entries if os.path.isfile(e.video_path)]
        if paths and self.add_to_queue_callback:
            self.add_to_queue_callback(paths)

    def _context_add_to_favourites(self, entries):
        paths = [e.video_path for e in entries if os.path.isfile(e.video_path)]
        if paths and self.add_to_favourites_callback:
            self.add_to_favourites_callback(paths)

    def _context_remove_from_favourites(self, entries):
        paths = [e.video_path for e in entries if os.path.isfile(e.video_path)]
        if paths and self.remove_from_favourites_callback:
            self.remove_from_favourites_callback(paths)

    def _open_grid_view_from_selection(self, selection):
        if not hasattr(self, 'grid_view_manager') or not self.grid_view_manager:
            return

        videos_to_play = set()

        for entry in selection:
            if os.path.exists(entry.video_path):
                videos_to_play.add(entry.video_path)

        if videos_to_play:
            self.grid_view_manager.show_grid_view(videos_to_play, self.video_preview_manager)

    def _play_selected_from_context(self, entries):
        if not entries:
            return

        videos_to_play = []
        missing_files = []

        for entry in entries:
            if os.path.exists(entry.video_path):
                videos_to_play.append(entry.video_path)
            else:
                missing_files.append(entry.video_name)

        if missing_files:
            messagebox.showwarning(
                "Missing Files",
                f"{len(missing_files)} file(s) not found",
                parent=self.history_window
            )

        if videos_to_play and hasattr(self, 'play_callback') and self.play_callback:
            self.play_callback(videos_to_play)
        elif not videos_to_play:
            messagebox.showwarning(
                "No Valid Files",
                "No valid video files found",
                parent=self.history_window
            )

    def _copy_path(self, file_path):
        try:
            self.parent.clipboard_clear()
            self.parent.clipboard_append(file_path)
        except Exception as e:
            print(f"Error copying path: {e}")

    def _open_location(self, file_path):
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

    def _show_properties(self, entry):
        try:
            from datetime import datetime

            stat_info = os.stat(entry.video_path)
            size_mb = stat_info.st_size / (1024 * 1024)
            modified = datetime.fromtimestamp(stat_info.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

            info = f"File: {entry.video_name}\n\n"
            info += f"Path: {entry.video_path}\n\n"
            info += f"Size: {size_mb:.2f} MB ({stat_info.st_size:,} bytes)\n\n"
            info += f"Modified: {modified}\n\n"
            info += f"Watch History:\n"
            info += f"  Last Watched: {entry.get_watch_date_formatted()}\n"
            info += f"  Duration Watched: {entry.get_duration_formatted()}\n"
            if entry.completion_percentage > 0:
                info += f"  Completion: {entry.completion_percentage:.1f}%\n"

            try:
                import cv2
                cap = cv2.VideoCapture(entry.video_path)
                if cap.isOpened():
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    duration = frame_count / fps if fps > 0 else 0
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

                    info += f"\nVideo Properties:\n"
                    info += f"  Duration: {int(duration // 60)}:{int(duration % 60):02d}\n"
                    info += f"  Resolution: {width}x{height}\n"
                    info += f"  FPS: {fps:.2f}\n"
                    cap.release()
            except:
                pass

            messagebox.showinfo("Properties", info, parent=self.history_window)
        except Exception as e:
            messagebox.showerror("Error", f"Could not retrieve properties: {e}", parent=self.history_window)

    def _apply_filter(self):
        filter_value = self.filter_var.get()

        if filter_value == "all":
            self.current_entries = self.history_service.get_all_history()
        elif filter_value == "today":
            self.current_entries = self.history_service.get_history_by_date_range(0)
        elif filter_value == "week":
            self.current_entries = self.history_service.get_history_by_date_range(7)
        elif filter_value == "month":
            self.current_entries = self.history_service.get_history_by_date_range(30)

        if self.directory_filter:
            self.current_entries = [
                entry for entry in self.current_entries
                if any(os.path.normpath(entry.directory_path) == directory or
                       os.path.normpath(entry.directory_path).startswith(directory + os.sep)
                       for directory in self.directory_filter)
            ]

        for item in self.history_tree.get_children():
            self.history_tree.delete(item)

        video_mapping = {}
        for i, entry in enumerate(self.current_entries):
            completion_text = f"{entry.completion_percentage:.1f}%" if entry.completion_percentage > 0 else "N/A"

            self.history_tree.insert('', tk.END, values=(
                entry.video_name,
                os.path.basename(entry.directory_path),
                entry.get_watch_date_formatted(),
                entry.get_duration_formatted(),
                completion_text
            ), tags=(entry.id,))

            video_mapping[i] = entry.video_path

    def _play_selected_video(self):
        selection = self.history_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a video to play")
            return

        if len(selection) > 1:
            messagebox.showwarning("Warning", "Please select only one video to play")
            return

        item = selection[0]
        tags = self.history_tree.item(item, 'tags')
        if not tags:
            return

        entry_id = tags[0]

        selected_entry = None
        for entry in self.current_entries:
            if entry.id == entry_id:
                selected_entry = entry
                break

        if not selected_entry:
            messagebox.showerror("Error", "Could not find selected video entry")
            return

        if not os.path.exists(selected_entry.video_path):
            messagebox.showerror("Error", f"Video file not found:\n{selected_entry.video_path}")
            return

        if hasattr(self, 'play_callback') and self.play_callback:
            self.play_callback([selected_entry.video_path])
        else:
            messagebox.showinfo("Info", f"Would play: {selected_entry.video_name}")

    def _remove_selected(self):
        selection = self.history_tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select entries to remove")
            return

        entry_ids = []
        for item in selection:
            tags = self.history_tree.item(item, 'tags')
            if tags:
                entry_ids.append(tags[0])

        if not entry_ids:
            return

        removed_count = self.history_service.remove_entries(entry_ids)
        if removed_count > 0:
            self._refresh_history_list()

    def _clear_all_history(self):
        total_entries = len(self.history_service.get_all_history())
        if total_entries == 0:
            return

        result = messagebox.askyesno(
            "Confirm Clear All",
            f"Are you sure you want to clear all {total_entries} entries from watch history?\n\n"
            "This action cannot be undone."
        )

        if result:
            self.history_service.clear_all_history()
            messagebox.showinfo("Success", "All watch history has been cleared")
            self._refresh_history_list()

    def _on_history_double_click(self, event):
        selection = self.history_tree.selection()
        if not selection:
            return

        item = selection[0]
        tags = self.history_tree.item(item, 'tags')
        if not tags:
            return

        entry_id = tags[0]

        selected_entry = None
        for entry in self.current_entries:
            if entry.id == entry_id:
                selected_entry = entry
                break

        if not selected_entry:
            return

        if not os.path.exists(selected_entry.video_path):
            messagebox.showerror(
                "File Not Found",
                f"Video file not found:\n{selected_entry.video_path}",
                parent=self.history_window
            )
            return

        if hasattr(self, 'play_callback') and self.play_callback:
            self.play_callback([selected_entry.video_path])


class WatchHistoryManager:

    def __init__(self, parent, theme_provider):
        self.storage = WatchHistoryStorage()
        self.service = WatchHistoryService(self.storage)
        self.ui = WatchHistoryUI(parent, theme_provider, self.service)
        self.ui.play_callback = None
        self.settings_manager = None

        self._last_video_path = None
        self._last_start_time = None
        self._resume_entry_id = None
        self._resume_video_path = None

    def set_resume_entry(self, video_path: str, entry_id: str):
        self._resume_video_path = os.path.normpath(video_path)
        self._resume_entry_id = entry_id

    def set_settings_manager(self, settings_manager):
        self.settings_manager = settings_manager

    def show_manager(self):
        self.ui.show_history_manager()

    def show_embedded(self, parent, close_callback=None):
        self.ui.show_history_manager_embedded(parent, close_callback)
        return self.ui

    def set_play_callback(self, callback):
        self.ui.play_callback = callback

    def set_grid_view_manager(self, grid_view_manager):
        self.ui.grid_view_manager = grid_view_manager

    def set_add_to_playlist_callback(self, cb):
        self.ui.add_to_playlist_callback = cb

    def set_add_to_queue_callback(self, cb):
        self.ui.add_to_queue_callback = cb

    def set_add_to_favourites_callback(self, cb):
        self.ui.add_to_favourites_callback = cb

    def set_remove_from_favourites_callback(self, cb):
        self.ui.remove_from_favourites_callback = cb

    def set_is_favourite_callback(self, cb):
        self.ui.is_favourite_callback = cb

    def set_locate_in_panel_callback(self, cb):
        self.ui.locate_in_panel_callback = cb

    def _should_track_history(self) -> bool:
        if self.settings_manager:
            settings = self.settings_manager.get_settings()
            return getattr(settings, 'enable_watch_history', True)
        return True

    def track_video_start(self, video_path: str):
        if not self._should_track_history():
            return
        self._last_video_path = video_path
        self._last_start_time = datetime.now()

    def track_video_end(self, video_path: str, duration_watched: int = 0, total_duration: int = 0):
        if not self._should_track_history():
            return
        if not video_path or not os.path.exists(video_path):
            return
        norm_path = os.path.normpath(video_path)
        if self._resume_entry_id and self._resume_video_path == norm_path:
            self.service.update_entry(self._resume_entry_id, duration_watched, total_duration)
            self._resume_entry_id = None
            self._resume_video_path = None
        else:
            self.service.add_watch_entry(video_path, duration_watched, total_duration)

    def track_video_playback(self, video_path: str, duration_watched: int = 0, total_duration: int = 0):
        self.track_video_end(video_path, duration_watched, total_duration)

    def get_recent_videos(self, count: int = 10) -> List[WatchHistoryEntry]:
        all_history = self.service.get_all_history()
        return all_history[:count]

    def get_history_stats(self) -> Dict:
        all_history = self.service.get_all_history()
        unique_videos = self.service.get_unique_videos_count()

        return {
            'total_entries': len(all_history),
            'unique_videos': unique_videos,
            'today_count': len(self.service.get_history_by_date_range(0)),
            'week_count': len(self.service.get_history_by_date_range(7)),
            'month_count': len(self.service.get_history_by_date_range(30))
        }

    def set_video_preview_manager(self, preview_manager):
        self.ui.video_preview_manager = preview_manager