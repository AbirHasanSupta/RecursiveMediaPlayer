import os
import threading
import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable, Dict, List, Any
from collections import Counter

try:
    from icon_helper import apply_icon
except ImportError:
    def apply_icon(w): pass

try:
    from utils import _responsive_geometry
except ImportError:
    def _responsive_geometry(parent, w, h):
        return f"{w}x{h}"


def _fmt_ms(ms: int) -> str:
    s = ms // 1000
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


# ── Palette helpers ────────────────────────────────────────────────────────────

def _hex_blend(fg: str, bg: str, alpha: float) -> str:
    def _p(h):
        h = h.lstrip('#')
        return [int(h[i:i+2], 16) for i in (0, 2, 4)]
    a, b = _p(fg), _p(bg)
    r = [int(a[i] * alpha + b[i] * (1 - alpha)) for i in range(3)]
    return '#{:02x}{:02x}{:02x}'.format(*r)


def _p(dark_mode, tp=None):
    if tp is None:
        if dark_mode:
            return {
                "accent": "#4A9EFF", "gold": "#f5c518", "gold_dim": "#b8920f",
                "panel": "#1e1f22", "sidebar": "#27282c", "header_bg": "#1a1b1e",
                "tag_sel_bg": "#1c3557", "tag_sel_fg": "#4A9EFF",
                "tag_norm_fg": "#8b9ab0", "tag_hover": "#2a2b30",
                "item_hover": "#2a2b30", "item_alt": "#252628",
                "pill_bg": "#1c3557", "pill_fg": "#4A9EFF",
                "star_on": "#f5c518", "star_off": "#3a3b3f",
                "rb_sel": "#1c3557", "rb_sel_fg": "#4A9EFF",
                "rb_nor": "#27282c", "rb_nor_fg": "#6b7a8a",
                "sep": "#2d2e33", "border": "#2d2e33",
                "count_bg": "#1c3557", "count_fg": "#4A9EFF",
                "bm_bg": "#1c2e48", "bm_fg": "#4A9EFF", "bm_border": "#1c3557",
                "detail_bg": "#1e1f22", "status_bg": "#16171a",
                "search_bg": "#2a2b30", "search_hl": "#4A9EFF",
                "text": "#e4e7ee", "text_muted": "#8b9ab0",
            }
        return {
            "accent": "#2d89ef", "gold": "#c8a000", "gold_dim": "#8a6d0a",
            "panel": "#ffffff", "sidebar": "#f4f5f7", "header_bg": "#ebedf0",
            "tag_sel_bg": "#dceeff", "tag_sel_fg": "#2d89ef",
            "tag_norm_fg": "#555e6e", "tag_hover": "#ebedf0",
            "item_hover": "#f0f6ff", "item_alt": "#f9f9fb",
            "pill_bg": "#dceeff", "pill_fg": "#2d89ef",
            "star_on": "#c8a000", "star_off": "#d0d5de",
            "rb_sel": "#dceeff", "rb_sel_fg": "#2d89ef",
            "rb_nor": "#ebedf0", "rb_nor_fg": "#888",
            "sep": "#e0e2e8", "border": "#e0e2e8",
            "count_bg": "#dceeff", "count_fg": "#2d89ef",
            "bm_bg": "#e8f3ff", "bm_fg": "#2d89ef", "bm_border": "#b8d4f5",
            "detail_bg": "#f4f5f7", "status_bg": "#ebedf0",
            "search_bg": "#ffffff", "search_hl": "#2d89ef",
            "text": "#1a2035", "text_muted": "#555e6e",
        }

    t = tp.get_manager_design_tokens()
    accent  = t["accent"]
    gold    = t["favorites_accent"]
    panel   = t["surface"]
    sidebar = t["surface2"]
    header_bg = t["header_bg"]
    sep     = t["divider"]
    border  = t["border"]
    text    = t["text"]
    muted   = t["text_muted"]

    _sel_bg   = _hex_blend(accent, panel,   0.18)
    _hover_bg = _hex_blend(accent, panel,   0.07)
    _bm_bg    = _hex_blend(accent, panel,   0.12)
    _bm_bdr   = _hex_blend(accent, border,  0.35)
    _star_off = border

    return {
        "accent": accent, "gold": gold, "gold_dim": gold,
        "panel": panel, "sidebar": sidebar, "header_bg": header_bg,
        "tag_sel_bg":  _sel_bg,   "tag_sel_fg":  accent,
        "tag_norm_fg": muted,     "tag_hover":   sidebar,
        "item_hover":  _hover_bg, "item_alt":    sidebar,
        "pill_bg":     _sel_bg,   "pill_fg":     accent,
        "star_on":     gold,      "star_off":    _star_off,
        "rb_sel":      _sel_bg,   "rb_sel_fg":   accent,
        "rb_nor":      sidebar,   "rb_nor_fg":   muted,
        "sep": sep, "border": border,
        "count_bg": _sel_bg, "count_fg": accent,
        "bm_bg": _bm_bg, "bm_fg": accent, "bm_border": _bm_bdr,
        "detail_bg": panel, "status_bg": sidebar,
        "search_bg": t["surface"], "search_hl": accent,
        "text": text, "text_muted": muted,
    }


def _show_menu(menu, x, y):
    try:
        menu.tk_popup(x, y)
    finally:
        menu.grab_release()


class AnnotationBrowserManager:

    def __init__(self, root, theme_provider, annotation_service,
                 play_callback: Optional[Callable] = None,
                 logger: Optional[Callable] = None):
        self.root = root
        self.tp = theme_provider
        self.svc = annotation_service
        self.play_callback = play_callback
        self.logger = logger
        self._win: Optional[tk.Toplevel] = None

        self._selected_tags: set = set()
        self._search_var: Optional[tk.StringVar] = None
        self._rating_var: Optional[tk.IntVar] = None
        self._video_listbox: Optional[tk.Listbox] = None
        self._vid_canvas: Optional[tk.Canvas] = None
        self._vid_rows: list = []
        self._vid_selection: set = set()
        self._row_height: int = 28
        self._tag_frame_inner: Optional[tk.Frame] = None
        self._tag_canvas: Optional[tk.Canvas] = None
        self._tag_canvas_win = None
        self._tag_btns: dict = {}
        self._filtered_videos: list = []
        self.directory_filter: list = []
        self._detail_lbl: Optional[tk.Label] = None
        self._detail_path_lbl: Optional[tk.Label] = None
        self._bookmark_frame: Optional[tk.Frame] = None
        self._count_lbl: Optional[tk.Label] = None
        self._active_filter_lbl: Optional[tk.Label] = None
        self._rb_btns: list = []
        self._dragging_index = None
        self.video_preview_manager = None
        self.grid_view_manager = None
        self.add_to_playlist_callback = None
        self.add_to_queue_callback = None
        self.add_to_favourites_callback = None
        self.remove_from_favourites_callback = None
        self.is_favourite_callback = None
        self.locate_in_panel_callback = None
        self._annotation_listener = None
        self._embedded = False
        self._close_callback = None

        # Async loading attributes
        self._load_thread: Optional[threading.Thread] = None
        self._cancel_load = threading.Event()
        self._loading = False

        theme_provider.register_manager_ui(self)

    # ── Public ────────────────────────────────────────────────────────────────
    def cleanup(self):
        self._cancel_load.set()
        self._loading = False
        self._win = None

    def show(self):
        if self._win and self._win.winfo_exists():
            self._win.lift()
            self._win.focus_force()
            return
        self._embedded = False
        self._close_callback = None
        self._build_window()

    def show_embedded(self, parent, close_callback=None):
        if self._win and self._win.winfo_exists():
            self._on_close()
        for child in parent.winfo_children():
            child.destroy()
        self._embedded = True
        self._close_callback = close_callback
        self._build_window(parent)
        return self

    def refresh(self):
        """Refresh the UI – called after any annotation change or manual refresh."""
        if self._win and self._win.winfo_exists():
            self._start_async_load()

    def set_directory_filter(self, directories: list = None):
        self.directory_filter = [os.path.normpath(d) for d in (directories or [])]

    def set_video_preview_manager(self, preview_manager):
        self.video_preview_manager = preview_manager

    def set_grid_view_manager(self, grid_view_manager):
        self.grid_view_manager = grid_view_manager

    def set_add_to_playlist_callback(self, cb):
        self.add_to_playlist_callback = cb

    def set_add_to_queue_callback(self, cb):
        self.add_to_queue_callback = cb

    def set_add_to_favourites_callback(self, cb):
        self.add_to_favourites_callback = cb

    def set_remove_from_favourites_callback(self, cb):
        self.remove_from_favourites_callback = cb

    def set_is_favourite_callback(self, cb):
        self.is_favourite_callback = cb

    def set_locate_in_panel_callback(self, cb):
        self.locate_in_panel_callback = cb

    # ── Async Loading ────────────────────────────────────────────────────────

    def _start_async_load(self):
        self._cancel_load.set()
        self._loading = False
        self._cancel_load.clear()
        self._loading = True
        self._show_loading_indicators()
        self._load_thread = threading.Thread(target=self._load_data_in_background, daemon=True)
        self._load_thread.start()

    def _load_data_in_background(self):
        if self._cancel_load.is_set():
            return
        try:
            with self.svc._lock:
                all_tags = self.svc.get_all_tags()
                data_snapshot = {k: (v.rating, list(v.tags), list(v.bookmarks))
                                 for k, v in self.svc._data.items()}
                browser_order = list(self.svc._browser_order)

            if self._cancel_load.is_set():
                return

            # Efficient tag counting – single pass O(V) instead of O(T×V)
            tag_counts = Counter()
            for _, (_, tags, _) in data_snapshot.items():
                tag_counts.update(tags)
                if self._cancel_load.is_set():
                    return

            annotated_videos = [
                k for k, (rating, tags, bookmarks) in data_snapshot.items()
                if rating > 0 or tags or bookmarks
            ]

            if not self._cancel_load.is_set():
                self.root.after(0, self._apply_loaded_data, {
                    "all_tags": all_tags,
                    "tag_counts": tag_counts,
                    "annotated_videos": annotated_videos,
                    "browser_order": browser_order,
                })
        except Exception as e:
            if self.logger:
                self.logger(f"Async load error: {e}")
            self.root.after(0, self._clear_loading_state)

    def _apply_loaded_data(self, data: Dict[str, Any]):
        if self._cancel_load.is_set() or not self._win or not self._win.winfo_exists():
            self._clear_loading_state()
            return

        # Store loaded data to use in rebuild methods
        self._cached_all_tags = data["all_tags"]
        self._cached_tag_counts = data["tag_counts"]
        self._cached_annotated_videos = data["annotated_videos"]

        # Rebuild UI with cached data
        self._rebuild_tags_from_cache()
        self._apply_filter_from_cache()

        self._clear_loading_state()
        self._loading = False

    def _context_add_to_playlist(self, paths):
        valid = [p for p in paths if os.path.isfile(p)]
        if valid and self.add_to_playlist_callback:
            self.add_to_playlist_callback(valid)

    def _context_add_to_queue(self, paths):
        valid = [p for p in paths if os.path.isfile(p)]
        if valid and self.add_to_queue_callback:
            self.add_to_queue_callback(valid)

    def _context_add_to_favourites(self, paths):
        valid = [p for p in paths if os.path.isfile(p)]
        if valid and self.add_to_favourites_callback:
            self.add_to_favourites_callback(valid)

    def _context_remove_from_favourites(self, paths):
        valid = [p for p in paths if os.path.isfile(p)]
        if valid and self.remove_from_favourites_callback:
            self.remove_from_favourites_callback(valid)

    def _clear_loading_state(self):
        self._loading = False
        self._cancel_load.clear()

    def _show_loading_indicators(self):
        """Display dark-themed loading placeholders to prevent white flash."""
        if not self._tag_frame_inner or not self._vid_inner:
            return

        P = _p(self.tp.dark_mode, self.tp)

        # Clear existing content and show loading message in tag panel
        for w in self._tag_frame_inner.winfo_children():
            w.destroy()
        loading_lbl = tk.Label(
            self._tag_frame_inner,
            text="⏳ Loading tags...",
            font=("Segoe UI", 10, "italic"),
            bg=P["sidebar"],
            fg=self.tp.muted_fg,
            pady=20
        )
        loading_lbl.pack(expand=True)

        # Show loading message in video list
        for w in self._vid_inner.winfo_children():
            w.destroy()
        vid_loading = tk.Label(
            self._vid_inner,
            text="⏳ Loading videos...",
            font=("Segoe UI", 12, "italic"),
            bg=P["panel"],
            fg=self.tp.muted_fg,
            pady=40
        )
        vid_loading.pack(expand=True)
        self._vid_inner.update_idletasks()

    # ── Window ────────────────────────────────────────────────────────────────

    def _show_add_tag_menu(self, event):
        tp = self.tp
        P = _p(tp.dark_mode, tp)
        menu = tp.create_manager_context_menu(self._win)
        if self._vid_selection:
            menu.add_command(label="✏  Add new tag to selected videos",
                             command=self._prompt_add_tag_to_selection)
        else:
            menu.add_command(label="✏  Add new tag",
                             command=self._prompt_create_empty_tag)
        try:
            menu.tk_popup(event.widget.winfo_rootx(),
                          event.widget.winfo_rooty() + event.widget.winfo_height())
        finally:
            menu.grab_release()

    def _prompt_add_tag_to_selection(self):
        tp = self.tp
        P = _p(tp.dark_mode, tp)
        if not self._vid_selection:
            return
        dlg = tk.Toplevel(self._win)
        dlg.withdraw()
        dlg.title("Add Tag")
        dlg.configure(bg=tp.bg_color)
        dlg.resizable(False, False)
        dlg.transient(self._win)
        dlg.grab_set()
        apply_icon(dlg)

        targets = [self._filtered_videos[i] for i in sorted(self._vid_selection)
                   if i < len(self._filtered_videos)]

        tk.Label(dlg, text=f"Add tag to {len(targets)} video{'s' if len(targets) != 1 else ''}:",
                 font=("Segoe UI", 10), bg=tp.bg_color, fg=tp.text_color
                 ).pack(padx=20, pady=(18, 6), anchor="w")

        all_tags = self.svc.get_all_tags()
        var = tk.StringVar()

        entry_frame = tk.Frame(dlg, bg=P["search_bg"],
                               highlightbackground=P["sep"], highlightthickness=1)
        entry_frame.pack(fill=tk.X, padx=20, pady=(0, 4))
        entry = tk.Entry(entry_frame, textvariable=var, font=("Segoe UI", 10),
                         bg=P["search_bg"], fg=tp.entry_fg,
                         insertbackground=tp.entry_fg, relief=tk.FLAT, bd=0)
        entry.pack(fill=tk.X, ipady=6, padx=8)
        entry.focus_set()

        if all_tags:
            tk.Label(dlg, text="Existing tags (click to reuse):",
                     font=("Segoe UI", 8), bg=tp.bg_color, fg=tp.muted_fg
                     ).pack(anchor="w", padx=20, pady=(4, 2))
            chips_frame = tk.Frame(dlg, bg=tp.bg_color)
            chips_frame.pack(fill=tk.X, padx=20, pady=(0, 8))
            for tag in all_tags[:20]:
                chip = tk.Label(chips_frame, text=f"#{tag}",
                                font=("Segoe UI", 8), bg=P["pill_bg"], fg=P["pill_fg"],
                                padx=6, pady=2, cursor="hand2")
                chip.pack(side=tk.LEFT, padx=2, pady=2)
                chip.bind("<Button-1>", lambda e, t=tag: var.set(t))

        btns = tk.Frame(dlg, bg=tp.bg_color)
        btns.pack(anchor="e", padx=20, pady=(4, 16))

        def do_save():
            tag = var.get().strip().lower()
            if not tag:
                return
            for path in targets:
                self.svc.add_tag(path, tag)
            dlg.destroy()
            self.refresh()
            self.tp.toast.success("Tag Added",
                                  f'"{tag}" added to {len(targets)} video{"s" if len(targets) != 1 else ""}')

        tp.create_modern_button(btns, "Create", do_save, "primary", "md").pack(side=tk.RIGHT, padx=(8, 0))
        tp.create_modern_button(btns, "Cancel", dlg.destroy, "secondary", "md").pack(side=tk.RIGHT)
        entry.bind("<Return>", lambda e: do_save())
        entry.bind("<Escape>", lambda e: dlg.destroy())

        dlg.update_idletasks()
        x = self._win.winfo_x() + (self._win.winfo_width() - dlg.winfo_reqwidth()) // 2
        y = self._win.winfo_y() + (self._win.winfo_height() - dlg.winfo_reqheight()) // 2
        dlg.geometry(f"+{x}+{y}")
        dlg.deiconify()

    def _prompt_create_empty_tag(self):
        tp = self.tp
        P = _p(tp.dark_mode, tp)
        dlg = tk.Toplevel(self._win)
        dlg.withdraw()
        dlg.title("New Tag")
        dlg.configure(bg=tp.bg_color)
        dlg.resizable(False, False)
        dlg.transient(self._win)
        dlg.grab_set()
        apply_icon(dlg)

        tk.Label(dlg, text="Create a new tag (no videos assigned):",
                 font=("Segoe UI", 10), bg=tp.bg_color, fg=tp.text_color
                 ).pack(padx=20, pady=(18, 6), anchor="w")

        var = tk.StringVar()
        entry_frame = tk.Frame(dlg, bg=P["search_bg"],
                               highlightbackground=P["sep"], highlightthickness=1)
        entry_frame.pack(fill=tk.X, padx=20, pady=(0, 4))
        entry = tk.Entry(entry_frame, textvariable=var, font=("Segoe UI", 10),
                         bg=P["search_bg"], fg=tp.entry_fg,
                         insertbackground=tp.entry_fg, relief=tk.FLAT, bd=0)
        entry.pack(fill=tk.X, ipady=6, padx=8)
        entry.focus_set()

        err_lbl = tk.Label(dlg, text="", font=("Segoe UI", 8),
                           bg=tp.bg_color, fg="#e17055")
        err_lbl.pack(anchor="w", padx=20)

        btns = tk.Frame(dlg, bg=tp.bg_color)
        btns.pack(anchor="e", padx=20, pady=(4, 16))

        def do_save():
            tag = var.get().strip().lower()
            if not tag:
                err_lbl.config(text="Tag name cannot be empty.")
                return
            if tag in self.svc.get_all_tags():
                err_lbl.config(text=f'"{tag}" already exists.')
                return
            self.svc.create_empty_tag(tag)
            dlg.destroy()
            self.refresh()
            self.tp.toast.success("Tag Created", f'Tag: "{tag}" created')

        tp.create_button(btns, "Create", do_save, "primary", "md").pack(side=tk.RIGHT, padx=(8, 0))
        tp.create_button(btns, "Cancel", dlg.destroy, "secondary", "md").pack(side=tk.RIGHT)
        entry.bind("<Return>", lambda e: do_save())
        entry.bind("<Escape>", lambda e: dlg.destroy())

        dlg.update_idletasks()
        x = self._win.winfo_x() + (self._win.winfo_width() - dlg.winfo_reqwidth()) // 2
        y = self._win.winfo_y() + (self._win.winfo_height() - dlg.winfo_reqheight()) // 2
        dlg.geometry(f"+{x}+{y}")
        dlg.deiconify()

    def _build_window(self, parent=None):
        tp = self.tp
        P = _p(tp.dark_mode, tp)

        embedded = parent is not None
        win = tk.Frame(parent, bg=P["panel"]) if embedded else tk.Toplevel(self.root)
        if not embedded:
            win.withdraw()
            win.title("Tags & Ratings")
            win.geometry(_responsive_geometry(self.root, 1600, 900))
        win.configure(bg=P["panel"])
        if embedded:
            win.pack(fill=tk.BOTH, expand=True)
        else:
            win.minsize(820, 520)
            win.protocol("WM_DELETE_WINDOW", win.destroy)
            apply_icon(win)
        self._win = win
        self._annotation_listener = self._on_annotation_changed
        self.svc.subscribe(self._annotation_listener)
        if hasattr(win, "protocol"):
            win.protocol("WM_DELETE_WINDOW", self._on_close)

        # ── Header ────────────────────────────────────────────────────────────
        header = tk.Frame(win, bg=P["header_bg"], height=58)
        header._ann_role = "header"
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        h_inner = tk.Frame(header, bg=P["header_bg"])
        h_inner._ann_role = "header"
        h_inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=0)

        title_box = tk.Frame(h_inner, bg=P["header_bg"])
        title_box.pack(side=tk.LEFT, fill=tk.Y)

        icon_lbl = tk.Label(title_box, text="🏷", font=("Segoe UI Emoji", 18),
                            bg=P["header_bg"], fg=P["gold"])
        icon_lbl.pack(side=tk.LEFT, padx=(0, 10), pady=14)

        tk.Label(title_box, text="Tags & Ratings",
                 font=("Segoe UI Semibold", 15) if tp.dark_mode else ("Segoe UI", 15, "bold"),
                 bg=P["header_bg"], fg=tp.text_color).pack(side=tk.LEFT, pady=14)

        if self._embedded and self._close_callback:
            close_btn = tk.Label(h_inner, text="✕", font=("Segoe UI", 14),
                                 bg=P["header_bg"], fg=P["text_muted"], cursor="hand2", padx=10)
            close_btn.pack(side=tk.RIGHT, pady=14)
            close_btn.bind("<Button-1>", lambda e: self._on_close())
            close_btn.bind("<Enter>", lambda e: close_btn.config(fg=P["accent"]))
            close_btn.bind("<Leave>", lambda e: close_btn.config(fg=P["text_muted"]))

        tk.Frame(win, bg=P["sep"], height=1).pack(fill=tk.X)

        # ── Filter bar ────────────────────────────────────────────────────────
        fbar = tk.Frame(win, bg=P["sidebar"])
        fbar._ann_role = "filter"
        fbar.pack(fill=tk.X)

        fb = tk.Frame(fbar, bg=P["sidebar"])
        fb._ann_role = "filter"
        fb.pack(fill=tk.X, padx=20, pady=10)

        search_wrap = tk.Frame(fb, bg=P["sidebar"])
        search_wrap._ann_role = "filter"
        search_wrap.pack(side=tk.LEFT, padx=(0, 20))

        tk.Label(search_wrap, text="SEARCH TAGS", font=("Segoe UI", 7, "bold"),
                 bg=P["sidebar"], fg=tp.muted_fg).pack(anchor="w")

        search_entry_frame = tk.Frame(search_wrap, bg=P["search_bg"],
                                      highlightbackground=P["sep"],
                                      highlightthickness=1)
        search_entry_frame._ann_role = "search"
        self._search_entry_frame = search_entry_frame
        search_entry_frame.pack(fill=tk.X, pady=(2, 0))

        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._on_search_change())

        tk.Label(search_entry_frame, text="⌕", font=("Segoe UI", 11),
                 bg=P["search_bg"], fg=tp.muted_fg).pack(side=tk.LEFT, padx=(6, 2))
        search_e = tk.Entry(search_entry_frame, textvariable=self._search_var,
                            font=tp.normal_font, bg=P["search_bg"], fg=tp.entry_fg,
                            insertbackground=tp.entry_fg, relief=tk.FLAT,
                            highlightthickness=0, width=14)
        search_e.pack(side=tk.LEFT, ipady=5, padx=(0, 6))
        search_e.bind("<FocusIn>",
                      lambda e: search_entry_frame.config(highlightbackground=P["search_hl"]))
        search_e.bind("<FocusOut>",
                      lambda e: search_entry_frame.config(highlightbackground=P["sep"]))

        rating_wrap = tk.Frame(fb, bg=P["sidebar"])
        rating_wrap._ann_role = "filter"
        rating_wrap.pack(side=tk.LEFT, padx=(0, 20))

        tk.Label(rating_wrap, text="MIN RATING", font=("Segoe UI", 7, "bold"),
                 bg=P["sidebar"], fg=tp.muted_fg).pack(anchor="w")

        rb_row = tk.Frame(rating_wrap, bg=P["sidebar"])
        rb_row._ann_role = "filter"
        rb_row.pack(pady=(2, 0))

        self._rating_var = tk.IntVar(value=0)
        self._rb_btns = []
        for i in range(6):
            text = "All" if i == 0 else "★" * i
            fg_n = tp.muted_fg if i == 0 else P["star_on"]

            rb = tk.Label(rb_row, text=text,
                          font=("Segoe UI", 9) if i == 0 else ("Segoe UI", 10),
                          bg=P["rb_nor"], fg=fg_n,
                          padx=10, pady=4, cursor="hand2",
                          relief=tk.FLAT,
                          highlightbackground=P["sep"], highlightthickness=1)
            rb.pack(side=tk.LEFT, padx=1)
            rb._val = i
            rb.bind("<Button-1>", lambda e, v=i: self._on_rating_click(v))
            rb.bind("<Enter>", lambda e, b=rb, v=i: b.config(
                bg=_p(self.tp.dark_mode, self.tp)["rb_sel"] if self._rating_var.get() != v else _p(self.tp.dark_mode, self.tp)["rb_sel"],
                highlightbackground=_p(self.tp.dark_mode, self.tp)["search_hl"]
            ))
            rb.bind("<Leave>", lambda e, b=rb, v=i: b.config(
                bg=_p(self.tp.dark_mode, self.tp)["rb_sel"] if self._rating_var.get() == v else _p(self.tp.dark_mode, self.tp)["rb_nor"],
                highlightbackground=_p(self.tp.dark_mode, self.tp)["search_hl"] if self._rating_var.get() == v else _p(self.tp.dark_mode, self.tp)["sep"]
            ))
            self._rb_btns.append(rb)

        self._update_rb_visuals(P)

        tk.Frame(fb, bg=P["sep"], width=1).pack(side=tk.LEFT, fill=tk.Y, padx=14, pady=2)

        action_wrap = tk.Frame(fb, bg=P["sidebar"])
        action_wrap.pack(side=tk.LEFT)
        tk.Label(action_wrap, text=" ", font=("Segoe UI", 7),
                 bg=P["sidebar"]).pack(anchor="w")
        btn_wrap = tk.Frame(action_wrap, bg=P["sidebar"])
        btn_wrap.pack()
        self.tp.create_manager_action_link(
            btn_wrap, "✕  Clear", self._clear_filters, style="warning"
        ).pack(side=tk.LEFT, padx=(0, 2))
        self.tp.create_manager_action_link(
            btn_wrap, "⟳  Refresh", self.refresh, style="secondary"
        ).pack(side=tk.LEFT)

        filter_lbl_wrap = tk.Frame(fb, bg=P["sidebar"])
        filter_lbl_wrap.pack(side=tk.RIGHT, fill=tk.Y)
        tk.Label(filter_lbl_wrap, text=" ", font=("Segoe UI", 7),
                 bg=P["sidebar"]).pack(anchor="w")
        self._active_filter_lbl = tk.Label(filter_lbl_wrap, text="",
                                           font=("Segoe UI", 9, "italic"),
                                           bg=P["sidebar"], fg=P["gold"])
        self._active_filter_lbl.pack(side=tk.RIGHT, padx=4)

        tk.Frame(win, bg=P["sep"], height=1).pack(fill=tk.X)

        # ── Body: sidebar + main ──────────────────────────────────────────────
        body = tk.Frame(win, bg=P["panel"])
        body._ann_role = "panel"
        body.pack(fill=tk.BOTH, expand=True)

        # ── LEFT sidebar ──────────────────────────────────────────────────────
        sidebar = tk.Frame(body, bg=P["sidebar"], width=220)
        sidebar._ann_role = "sidebar"
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        sid_hdr = tk.Frame(sidebar, bg=P["sidebar"])
        sid_hdr.pack(fill=tk.X, padx=14, pady=(14, 4))
        tk.Label(sid_hdr, text="TAGS", font=("Segoe UI", 7, "bold"),
                 bg=P["sidebar"], fg=tp.muted_fg).pack(side=tk.LEFT)
        self._tag_count_lbl = tk.Label(sid_hdr, text="",
                                       font=("Segoe UI", 7),
                                       bg=P["sidebar"], fg=tp.muted_fg)
        self._tag_count_lbl.pack(side=tk.RIGHT, padx=(0, 6))
        add_tag_btn = tk.Label(sid_hdr, text="＋ Add ▾",
                               font=("Segoe UI", 7, "bold"),
                               bg=P["accent"], fg="white",
                               padx=6, pady=2, cursor="hand2")
        add_tag_btn.pack(side=tk.RIGHT, padx=(0, 4))
        add_tag_btn.bind("<Button-1>", lambda e: self._show_add_tag_menu(e))
        add_tag_btn.bind("<Enter>", lambda e: add_tag_btn.config(bg=self._lighten(P["accent"])))
        add_tag_btn.bind("<Leave>", lambda e: add_tag_btn.config(bg=P["accent"]))

        tk.Frame(sidebar, bg=P["sep"], height=1).pack(fill=tk.X, padx=10)

        tag_scroll_area = tk.Frame(sidebar, bg=P["sidebar"])
        tag_scroll_area.pack(fill=tk.BOTH, expand=True)

        tag_sb = ttk.Scrollbar(tag_scroll_area, orient=tk.VERTICAL,
                               style="ExclusionTree.Vertical.TScrollbar")
        tag_sb.pack(side=tk.RIGHT, fill=tk.Y, pady=4)

        self._tag_canvas = tk.Canvas(tag_scroll_area, bg=P["sidebar"],
                                     highlightthickness=0, yscrollcommand=tag_sb.set)
        self._tag_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tag_sb.config(command=self._tag_canvas.yview)

        self._tag_frame_inner = tk.Frame(self._tag_canvas, bg=P["sidebar"])
        self._tag_canvas_win = self._tag_canvas.create_window(
            (0, 0), window=self._tag_frame_inner, anchor="nw")
        self._tag_frame_inner.bind(
            "<Configure>",
            lambda e: self._tag_canvas.configure(scrollregion=self._tag_canvas.bbox("all")))
        self._tag_canvas.bind(
            "<Configure>",
            lambda e: self._tag_canvas.itemconfig(self._tag_canvas_win, width=e.width))
        self._tag_canvas.bind(
            "<MouseWheel>",
            lambda e: self._tag_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))

        tk.Frame(body, bg=P["sep"], width=1).pack(side=tk.LEFT, fill=tk.Y)

        # ── RIGHT content ──────────────────────────────────────────────────────
        right = tk.Frame(body, bg=P["panel"])
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        info_bar = tk.Frame(right, bg=P["panel"])
        info_bar.pack(fill=tk.X, padx=18, pady=(12, 6))

        count_pill = tk.Frame(info_bar, bg=P["count_bg"],
                              highlightbackground=P["bm_border"], highlightthickness=1)
        count_pill.pack(side=tk.LEFT)
        self._count_lbl = tk.Label(count_pill, text="0 videos",
                                   font=("Segoe UI", 9, "bold"),
                                   bg=P["count_bg"], fg=P["count_fg"],
                                   padx=10, pady=3)
        self._count_lbl.pack()

        self._active_filter_lbl2 = tk.Label(info_bar, text="",
                                            font=("Segoe UI", 9, "italic"),
                                            bg=P["panel"], fg=P["gold"])
        self._active_filter_lbl2.pack(side=tk.LEFT, padx=10)

        tk.Label(info_bar, text="drag to reorder  •  double-click to play",
                 font=("Segoe UI", 8), bg=P["panel"], fg=tp.muted_fg).pack(side=tk.RIGHT)

        list_outer = tk.Frame(right, bg=P["panel"],
                              highlightbackground=P["sep"], highlightthickness=1)
        list_outer.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 12))

        col_hdr = tk.Frame(list_outer, bg=P["sidebar"], height=26)
        col_hdr.pack(fill=tk.X)
        col_hdr.pack_propagate(False)
        self._col_weights = [0.55, 0.13, 0.12, 0.20]
        self._col_labels_text = ["Name", "Rating", "Bookmarks", "Tags"]
        self._col_header_frame = col_hdr

        def _place_headers(event=None):
            w = col_hdr.winfo_width()
            if w < 2:
                return
            for j, lbl in enumerate(col_hdr.winfo_children()):
                x = int(sum(self._col_weights[:j]) * w)
                lbl.place(x=x, y=0, width=int(self._col_weights[j] * w), height=26)

        for txt in self._col_labels_text:
            tk.Label(col_hdr, text=txt.upper(), font=("Segoe UI", 7, "bold"),
                     bg=P["sidebar"], fg=tp.muted_fg, padx=8, anchor="w")
        col_hdr.bind("<Configure>", _place_headers)
        tk.Frame(list_outer, bg=P["sep"], height=1).pack(fill=tk.X)

        vid_body = tk.Frame(list_outer, bg=P["panel"])
        vid_body.pack(fill=tk.BOTH, expand=True)

        vid_sb = ttk.Scrollbar(vid_body, orient=tk.VERTICAL,
                               style="ExclusionTree.Vertical.TScrollbar")
        vid_sb.pack(side=tk.RIGHT, fill=tk.Y, pady=4)

        self._vid_canvas = tk.Canvas(vid_body, bg=P["panel"],
                                     highlightthickness=0,
                                     yscrollcommand=vid_sb.set)
        self._vid_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vid_sb.config(command=self._vid_canvas.yview)

        self._vid_inner = tk.Frame(self._vid_canvas, bg=P["panel"])
        self._vid_canvas_win = self._vid_canvas.create_window(
            (0, 0), window=self._vid_inner, anchor="nw")
        self._vid_inner.bind(
            "<Configure>",
            lambda e: self._vid_canvas.configure(scrollregion=self._vid_canvas.bbox("all")))
        self._vid_canvas.bind(
            "<Configure>",
            lambda e: self._vid_canvas.itemconfig(self._vid_canvas_win, width=e.width))
        self._vid_canvas.bind(
            "<MouseWheel>",
            lambda e: self._vid_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))

        self._video_listbox = None
        self._vid_selection: set = set()
        self._vid_rows = []
        self._vid_P = P

        # ── Detail panel ──────────────────────────────────────────────────────
        tk.Frame(win, bg=P["sep"], height=1).pack(fill=tk.X, side=tk.BOTTOM)

        detail_panel = tk.Frame(win, bg=P["detail_bg"])
        detail_panel.pack(fill=tk.X, side=tk.BOTTOM)

        detail_top = tk.Frame(detail_panel, bg=P["detail_bg"])
        detail_top.pack(fill=tk.X, padx=16, pady=(10, 4))

        self._detail_stars_lbl = tk.Label(detail_top, text="",
                                          font=("Segoe UI", 11),
                                          bg=P["detail_bg"], fg=P["gold"])
        self._detail_stars_lbl.pack(side=tk.LEFT)

        self._detail_lbl = tk.Label(detail_top,
                                    text="  Select a video to see details",
                                    font=("Segoe UI", 10),
                                    bg=P["detail_bg"], fg=tp.muted_fg,
                                    anchor="w")
        self._detail_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._detail_path_lbl = tk.Label(detail_panel, text="",
                                         font=("Segoe UI", 8),
                                         bg=P["detail_bg"], fg=tp.muted_fg,
                                         anchor="w")
        self._detail_path_lbl.pack(anchor="w", padx=16, pady=(0, 4))

        self._bookmark_frame = tk.Frame(detail_panel, bg=P["detail_bg"])
        self._bookmark_frame.pack(fill=tk.X, padx=12, pady=(0, 10))

        # ── Bottom action bar ─────────────────────────────────────────────────
        tk.Frame(win, bg=P["sep"], height=1).pack(fill=tk.X, side=tk.BOTTOM)
        action = tk.Frame(win, bg=P["status_bg"])
        action.pack(fill=tk.X, side=tk.BOTTOM)
        act_inner = tk.Frame(action, bg=P["status_bg"])
        act_inner.pack(fill=tk.X, padx=18, pady=10)


        # Start async loading (shows loading indicators, then populates UI)
        self._start_async_load()
        if hasattr(win, "deiconify"):
            win.deiconify()

    def apply_theme(self):
        if not self._win or not self._win.winfo_exists():
            return
        try:
            tp = self.tp
            P = _p(tp.dark_mode, tp)
            self._win.configure(bg=P["panel"])

            _role_bg = {
                "header": P["header_bg"],
                "filter": P["sidebar"],
                "search": P["search_bg"],
                "sidebar": P["sidebar"],
                "detail":  P["detail_bg"],
                "status":  P["status_bg"],
                "panel":   P["panel"],
            }

            def _walk(widget):
                try:
                    if isinstance(widget, tk.Frame):
                        role = getattr(widget, "_ann_role", None)
                        if role in _role_bg:
                            hl = widget.cget("highlightthickness")
                            if role == "search" and hl:
                                widget.configure(bg=P["search_bg"],
                                                 highlightbackground=P["sep"])
                            else:
                                widget.configure(bg=_role_bg[role])

                    elif isinstance(widget, tk.Label):
                        # skip pills and special-colored labels
                        if getattr(widget, "_modern_btn", False):
                            return
                        parent_role = getattr(widget.master, "_ann_role", None)
                        if parent_role in _role_bg and parent_role != "search":
                            bg = _role_bg[parent_role]
                            try:
                                widget.configure(bg=bg)
                            except tk.TclError:
                                pass

                    elif isinstance(widget, tk.Entry):
                        parent_role = getattr(widget.master, "_ann_role", None)
                        if parent_role == "search":
                            widget.configure(
                                bg=P["search_bg"], fg=tp.entry_fg,
                                insertbackground=tp.entry_fg)

                    for child in widget.winfo_children():
                        _walk(child)
                except tk.TclError:
                    pass

            _walk(self._win)
            tp.restyle_manager_buttons(self._win)
            tp.restyle_manager_action_links(self._win)
            self._update_rb_visuals(P)
            # re-sync search entry frame border if stored
            if hasattr(self, '_search_entry_frame'):
                try:
                    self._search_entry_frame.configure(
                        bg=P["search_bg"], highlightbackground=P["sep"])
                except tk.TclError:
                    pass
            self._start_async_load()
        except Exception:
            pass

    def play_from_global(self):
        """Play the filtered videos (or selected if any)."""
        if self._vid_selection:
            self._play_selected()
        elif self._filtered_videos and self.play_callback:
            self.play_callback(self._filtered_videos)

    def _on_close(self):
        if self._annotation_listener:
            self.svc.unsubscribe(self._annotation_listener)
            self._annotation_listener = None
        self._cancel_load.set()
        self._loading = False
        if self._win:
            self._win.destroy()
        self._win = None
        if self._embedded and self._close_callback:
            self._close_callback()

    def _on_annotation_changed(self):
        if self._win and self._win.winfo_exists():
            try:
                self._win.after(0, self.refresh)
            except Exception:
                pass

    # ── Helper widget builders ─────────────────────────────────────────────────

    def _make_header_btn(self, parent, text, cmd, bg, fg):
        tp = self.tp
        colors = tp.get_button_colors("primary")
        btn = tk.Button(parent, text=text, command=cmd,
                        font=("Segoe UI", 9, "bold"),
                        bg=colors["bg"], fg=colors["fg"], relief=tk.FLAT, bd=0,
                        padx=14, pady=6, cursor="hand2",
                        activebackground=colors["active"], activeforeground="#FFFFFF")
        btn._variant = "primary"
        tp._bind_button_hover(btn, "primary")
        return btn

    def _make_flat_btn(self, parent, text, cmd, P):
        tp = self.tp
        colors = tp.get_button_colors("secondary")
        btn = tk.Button(parent, text=text, command=cmd,
                        font=("Segoe UI", 9),
                        bg=colors["bg"], fg=colors["fg"],
                        relief=tk.FLAT, bd=0,
                        padx=10, pady=5, cursor="hand2",
                        activebackground=colors["active"],
                        activeforeground="#FFFFFF")
        btn._variant = "secondary"
        tp._bind_button_hover(btn, "secondary")
        return btn

    @staticmethod
    def _lighten(hex_color):
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            r = min(255, r + 20)
            g = min(255, g + 20)
            b = min(255, b + 20)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    # ── Tag panel (cached version) ──────────────────────────────────────────

    def _rebuild_tags_from_cache(self):
        """Rebuild tag panel using pre‑fetched data from _cached_* attributes."""
        if not self._tag_frame_inner or not hasattr(self, '_cached_all_tags'):
            return

        tp = self.tp
        P = _p(tp.dark_mode, tp)

        for w in self._tag_frame_inner.winfo_children():
            w.destroy()
        self._tag_btns.clear()

        query = (self._search_var.get().strip().lower()) if self._search_var else ""
        visible_tags = [t for t in self._cached_all_tags if not query or query in t.lower()]

        if hasattr(self, '_tag_count_lbl') and self._tag_count_lbl:
            self._tag_count_lbl.config(text=f"{len(visible_tags)}")

        is_all = not self._selected_tags
        all_row = tk.Frame(self._tag_frame_inner,
                           bg=P["tag_sel_bg"] if is_all else P["sidebar"],
                           cursor="hand2")
        all_row.pack(fill=tk.X, padx=8, pady=(8, 2))
        all_row.bind("<Button-1>", lambda e: self._toggle_tag(None))

        tk.Label(all_row,
                 text="⊞",
                 font=("Segoe UI Emoji", 9),
                 bg=P["tag_sel_bg"] if is_all else P["sidebar"],
                 fg=P["tag_sel_fg"] if is_all else tp.muted_fg
                 ).pack(side=tk.LEFT, padx=(8, 4), pady=6)

        tk.Label(all_row,
                 text="All videos",
                 font=("Segoe UI", 10, "bold") if is_all else ("Segoe UI", 10),
                 bg=P["tag_sel_bg"] if is_all else P["sidebar"],
                 fg=P["tag_sel_fg"] if is_all else tp.text_color,
                 anchor="w"
                 ).pack(side=tk.LEFT, pady=6, fill=tk.X, expand=True)

        if not is_all:
            all_row.bind("<Enter>", lambda e: all_row.config(bg=P["tag_hover"]))
            all_row.bind("<Leave>", lambda e: all_row.config(bg=P["sidebar"]))
            for child in all_row.winfo_children():
                child.bind("<Button-1>", lambda e: self._toggle_tag(None))
                child.bind("<Enter>", lambda e: all_row.config(bg=P["tag_hover"]))
                child.bind("<Leave>", lambda e: all_row.config(bg=P["sidebar"]))

        self._tag_btns["__ALL__"] = all_row

        tk.Frame(self._tag_frame_inner, bg=P["sep"], height=1
                 ).pack(fill=tk.X, padx=12, pady=(4, 4))

        for tag in visible_tags:
            count = self._cached_tag_counts.get(tag, 0)
            is_sel = tag in self._selected_tags

            row_bg = P["tag_sel_bg"] if is_sel else P["sidebar"]
            row = tk.Frame(self._tag_frame_inner, bg=row_bg, cursor="hand2")
            row.pack(fill=tk.X, padx=8, pady=1)

            dot = tk.Label(row, text="●",
                           font=("Segoe UI", 6),
                           bg=row_bg,
                           fg=P["tag_sel_fg"] if is_sel else tp.muted_fg)
            dot.pack(side=tk.LEFT, padx=(10, 4), pady=7)

            name_lbl = tk.Label(row,
                                text=tag,
                                font=("Segoe UI", 10, "bold") if is_sel else ("Segoe UI", 10),
                                bg=row_bg,
                                fg=P["tag_sel_fg"] if is_sel else tp.text_color,
                                anchor="w")
            name_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=6)

            cnt_frame = tk.Frame(row, bg=P["count_bg"] if is_sel else P["sidebar"])
            cnt_frame.pack(side=tk.RIGHT, padx=8, pady=5)
            tk.Label(cnt_frame, text=str(count),
                     font=("Segoe UI", 8, "bold"),
                     bg=P["count_bg"] if is_sel else P["tag_hover"],
                     fg=P["count_fg"] if is_sel else tp.muted_fg,
                     padx=6, pady=2).pack()

            def _bind_row(r, t, widgets, sel):
                def on_click(e): self._toggle_tag(t)
                def on_right(e): self._on_tag_right_click(e, t)
                def on_enter(e):
                    if t not in self._selected_tags:
                        r.config(bg=P["tag_hover"])
                        for w in widgets: w.config(bg=P["tag_hover"])
                def on_leave(e):
                    nb = P["tag_sel_bg"] if t in self._selected_tags else P["sidebar"]
                    r.config(bg=nb)
                    for w in widgets: w.config(bg=nb)
                for w in [r] + widgets:
                    w.bind("<Button-1>", on_click)
                    w.bind("<Button-3>", on_right)
                    w.bind("<Enter>", on_enter)
                    w.bind("<Leave>", on_leave)

            _bind_row(row, tag, [dot, name_lbl, cnt_frame] + cnt_frame.winfo_children(), is_sel)
            self._tag_btns[tag] = row

        if not visible_tags:
            msg = "No tags match." if query else "No tags yet.\n\nAdd tags via\n🏷 in the player."
            tk.Label(self._tag_frame_inner, text=msg,
                     font=("Segoe UI", 9), bg=P["sidebar"], fg=tp.muted_fg,
                     justify=tk.CENTER, pady=20).pack()

    def _on_tag_right_click(self, event, tag):
        tp = self.tp
        P = _p(tp.dark_mode, tp)
        count = len(self.svc.get_videos_with_tag(tag))
        menu = tp.create_manager_context_menu(self._win)
        menu.add_command(
            label=f"  {tag}  ({count} video{'s' if count != 1 else ''})",
            state="disabled")
        menu.add_separator()
        menu.add_command(label="✏  Rename tag",
                         command=lambda: self._rename_tag(tag))
        menu.add_command(label="✕  Delete tag",
                         command=lambda: self._delete_tag(tag))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _delete_tag(self, tag):
        from tkinter import messagebox
        count = len(self.svc.get_videos_with_tag(tag))
        msg = f'Delete tag "{tag}" from {count} video{"s" if count != 1 else ""}?\nThis cannot be undone.'
        if not messagebox.askyesno("Delete Tag", msg, parent=self._win):
            return
        with self.svc._lock:
            for ann in self.svc._data.values():
                if tag in ann.tags:
                    ann.tags.remove(tag)
            self.svc._empty_tags.discard(tag)
            self.svc._schedule_save()
        self._selected_tags.discard(tag)
        self.refresh()
        self.tp.toast.success("Tag Deleted", f'"{tag}" removed from {count} video{"s" if count != 1 else ""}')

    def _rename_tag(self, old_tag):
        tp = self.tp
        P = _p(tp.dark_mode, tp)
        dlg = tk.Toplevel(self._win)
        dlg.withdraw()
        dlg.title("Rename Tag")
        dlg.configure(bg=tp.bg_color)
        dlg.resizable(False, False)
        dlg.transient(self._win)
        dlg.grab_set()
        apply_icon(dlg)

        tk.Label(dlg, text=f'Rename  "{old_tag}"  to:',
                 font=("Segoe UI", 10), bg=tp.bg_color, fg=tp.text_color
                 ).pack(padx=20, pady=(18, 6), anchor="w")

        var = tk.StringVar(value=old_tag)
        entry_frame = tk.Frame(dlg, bg=P["search_bg"],
                               highlightbackground=P["sep"], highlightthickness=1)
        entry_frame.pack(fill=tk.X, padx=20, pady=(0, 4))
        entry = tk.Entry(entry_frame, textvariable=var, font=("Segoe UI", 10),
                         bg=P["search_bg"], fg=tp.entry_fg,
                         insertbackground=tp.entry_fg, relief=tk.FLAT, bd=0)
        entry.pack(fill=tk.X, ipady=6, padx=8)
        entry.select_range(0, tk.END)
        entry.focus_set()

        err_lbl = tk.Label(dlg, text="", font=("Segoe UI", 8),
                           bg=tp.bg_color, fg="#e17055")
        err_lbl.pack(anchor="w", padx=20)

        btns = tk.Frame(dlg, bg=tp.bg_color)
        btns.pack(anchor="e", padx=20, pady=(8, 16))

        def do_rename():
            new_tag = var.get().strip().lower()
            if not new_tag:
                err_lbl.config(text="Tag name cannot be empty.")
                return
            if new_tag == old_tag:
                dlg.destroy()
                return
            if new_tag in self.svc.get_all_tags():
                err_lbl.config(text=f'"{new_tag}" already exists.')
                return
            with self.svc._lock:
                for ann in self.svc._data.values():
                    if old_tag in ann.tags:
                        ann.tags = [new_tag if t == old_tag else t for t in ann.tags]
                if old_tag in self.svc._empty_tags:
                    self.svc._empty_tags.discard(old_tag)
                    self.svc._empty_tags.add(new_tag)
                self.svc._schedule_save()
            if old_tag in self._selected_tags:
                self._selected_tags.discard(old_tag)
                self._selected_tags.add(new_tag)
            dlg.destroy()
            self.refresh()
            self.tp.toast.success("Tag Renamed", f'Tag Renamed: "{old_tag}" → "{new_tag}"')

        tp.create_modern_button(btns, "Rename", do_rename, "primary", "md").pack(side=tk.RIGHT, padx=(8, 0))
        tp.create_modern_button(btns, "Cancel", dlg.destroy, "secondary", "md").pack(side=tk.RIGHT)

        entry.bind("<Return>", lambda e: do_rename())
        entry.bind("<Escape>", lambda e: dlg.destroy())
        dlg.update_idletasks()
        x = self._win.winfo_x() + (self._win.winfo_width() - dlg.winfo_reqwidth()) // 2
        y = self._win.winfo_y() + (self._win.winfo_height() - dlg.winfo_reqheight()) // 2
        dlg.geometry(f"+{x}+{y}")
        dlg.deiconify()

    def _toggle_tag(self, tag):
        if tag is None:
            self._selected_tags.clear()
        elif tag in self._selected_tags:
            self._selected_tags.discard(tag)
        else:
            self._selected_tags.add(tag)
        self.refresh()

    # ── Rating clicks ─────────────────────────────────────────────────────────

    def _on_rating_click(self, val):
        self._rating_var.set(val)
        P = _p(self.tp.dark_mode, self.tp)
        self._update_rb_visuals(P)
        self.refresh()

    def _update_rb_visuals(self, P):
        cur = self._rating_var.get()
        for rb in self._rb_btns:
            sel = rb._val == cur
            rb.config(
                bg=P["rb_sel"] if sel else P["rb_nor"],
                fg=P["rb_sel_fg"] if sel else (self.tp.muted_fg if rb._val == 0 else P["star_on"]),
                highlightbackground=P["search_hl"] if sel else P["sep"]
            )

    # ── Filter (cached version) ──────────────────────────────────────────────

    def _apply_filter_from_cache(self):
        """Apply filter using cached annotated videos list."""
        if not hasattr(self, '_vid_canvas') or not self._vid_canvas or not hasattr(self, '_cached_annotated_videos'):
            return

        tp = self.tp
        P = _p(tp.dark_mode, tp)

        min_rating = self._rating_var.get() if self._rating_var else 0
        all_annotated = self._cached_annotated_videos

        if self._selected_tags:
            candidates = [p for p in all_annotated
                          if self._selected_tags.issubset(set(self.svc.get_tags(p)))]
        else:
            candidates = all_annotated

        if self.directory_filter:
            candidates = [
                p for p in candidates
                if any(os.path.normpath(p) == directory or
                       os.path.normpath(p).startswith(directory + os.sep)
                       for directory in self.directory_filter)
            ]

        if min_rating > 0:
            candidates = [p for p in candidates if self.svc.get_rating(p) >= min_rating]

        self._filtered_videos = candidates
        saved_order = self.svc.get_browser_order()
        if saved_order:
            order_map = {p: i for i, p in enumerate(saved_order)}
            self._filtered_videos.sort(key=lambda p: order_map.get(p, len(saved_order)))
        self._vid_selection.clear()
        self._rebuild_vid_rows()

        count_text = f"{len(candidates)} video{'s' if len(candidates) != 1 else ''}"
        self._count_lbl.config(text=count_text)

        parts = []
        if self._selected_tags:
            parts.append("Tags: " + ", ".join(sorted(self._selected_tags)))
        if min_rating:
            parts.append(f"Min: {'★' * min_rating}")
        filter_text = "  ·  " + "   |   ".join(parts) if parts else ""
        self._active_filter_lbl.config(text=filter_text)
        if hasattr(self, '_active_filter_lbl2'):
            self._active_filter_lbl2.config(text=filter_text)

        if self.video_preview_manager:
            video_mapping = {i: path for i, path in enumerate(candidates)}
            self._vid_canvas._row_height = self._row_height
            self.video_preview_manager.attach_to_listbox(self._vid_canvas, video_mapping)

        self._clear_detail()

    def _row_at_y(self, y: int) -> int:
        canvas_y = self._vid_canvas.canvasy(y)
        rh = self._row_height
        return max(0, int(canvas_y // rh))

    def _rebuild_vid_rows(self):
        if not hasattr(self, '_vid_inner') or not self._vid_inner:
            return

        for w in self._vid_inner.winfo_children():
            w.destroy()
        self._vid_rows = []

        if not self._filtered_videos:
            self._vid_inner.update_idletasks()
            self._vid_canvas.configure(scrollregion=self._vid_canvas.bbox("all"))
            return

        self._vid_canvas.configure(scrollregion=f"0 0 1 {len(self._filtered_videos) * self._row_height}")
        self._render_chunk(0, list(self._filtered_videos), id(self._filtered_videos))

    def _render_chunk(self, start: int, snapshot: list, snapshot_id: int, chunk: int = 30):
        if not hasattr(self, '_vid_inner') or not self._vid_inner:
            return
        if id(self._filtered_videos) != snapshot_id:
            return

        tp = self.tp
        P = _p(tp.dark_mode, tp)
        col_w = self._col_weights
        end = min(start + chunk, len(snapshot))

        for i in range(start, end):
            path = snapshot[i]
            rating = self.svc.get_rating(path)
            tags = self.svc.get_tags(path)
            bm_cnt = len(self.svc.get_bookmarks(path))
            name = os.path.basename(path)
            stars = "★" * rating if rating else ""
            bm_text = f"🔖 {bm_cnt}" if bm_cnt else "—"
            is_sel = i in self._vid_selection
            row_bg = P["accent"] if is_sel else (P["item_alt"] if i % 2 else P["panel"])
            fg = "white" if is_sel else tp.text_color
            muted = "white" if is_sel else tp.muted_fg
            gold = "white" if is_sel else P["star_on"]

            row = tk.Frame(self._vid_inner, bg=row_bg, height=self._row_height)
            row.pack(fill=tk.X)
            row.pack_propagate(False)

            tag_cell = tk.Frame(row, bg=row_bg)

            def _build_tag_cell(tc, path_, tags_, row_bg_, muted_, P_):
                if not tags_:
                    tk.Label(tc, text="—", font=("Segoe UI", 9),
                             bg=row_bg_, fg=muted_, anchor="w").pack(side=tk.LEFT, padx=4)
                    return
                for t in tags_[:4]:
                    pill = tk.Frame(tc, bg=P_["pill_bg"], padx=2, pady=1)
                    pill.pack(side=tk.LEFT, padx=2, pady=4)
                    tk.Label(pill, text=t, font=("Segoe UI", 8),
                             bg=P_["pill_bg"], fg=P_["pill_fg"]).pack(side=tk.LEFT, padx=(4, 1))
                    x_btn = tk.Label(pill, text="×", font=("Segoe UI", 9, "bold"),
                                     bg=P_["pill_bg"], fg=P_["pill_fg"],
                                     cursor="hand2", padx=3)
                    x_btn.pack(side=tk.LEFT)
                    x_btn.bind("<Button-1>", lambda e, p=path_, tg=t: (
                        e.widget.winfo_toplevel().after(0, lambda: self._remove_tag_from_video(p, tg))
                    ) or "break")
                    x_btn.bind("<Enter>", lambda e, b=x_btn: b.config(fg="#e17055"))
                    x_btn.bind("<Leave>", lambda e, b=x_btn, P_=P_: b.config(fg=P_["pill_fg"]))
                if len(tags_) > 4:
                    tk.Label(tc, text=f"+{len(tags_) - 4}", font=("Segoe UI", 8),
                             bg=row_bg_, fg=muted_).pack(side=tk.LEFT, padx=2)

            _build_tag_cell(tag_cell, path, tags, row_bg, muted, P)

            cells = [
                tk.Label(row, text=f"  {name}", font=("Segoe UI", 10), bg=row_bg, fg=fg, anchor="w"),
                tk.Label(row, text=stars or "—", font=("Segoe UI", 10), bg=row_bg, fg=gold, anchor="w"),
                tk.Label(row, text=bm_text, font=("Segoe UI", 10), bg=row_bg, fg=muted, anchor="w"),
                tag_cell,
            ]
            for j, cell in enumerate(cells):
                cell._col_idx = j
                cell.place(relx=sum(col_w[:j]), rely=0, relwidth=col_w[j], relheight=1.0)

            def _bind_row(r, idx_, cells_):
                def on_click(e):
                    if self.video_preview_manager and hasattr(self.video_preview_manager, 'tooltip'):
                        try:
                            self.video_preview_manager.tooltip.hide_preview()
                        except Exception:
                            pass
                    ctrl = bool(e.state & 0x4)
                    shift = bool(e.state & 0x1)
                    if shift and self._vid_selection:
                        anchor = max(self._vid_selection)
                        self._vid_selection = set(range(min(anchor, idx_), max(anchor, idx_) + 1))
                    elif ctrl:
                        if idx_ in self._vid_selection:
                            self._vid_selection.discard(idx_)
                        else:
                            self._vid_selection.add(idx_)
                    else:
                        self._vid_selection = {idx_}
                        self._dragging_index = idx_
                    self._refresh_row_colors()
                    self._on_video_select()
                    return "break"

                def on_dbl(e):
                    self._vid_selection = {idx_}
                    self._refresh_row_colors()
                    self._play_selected()
                    return "break"

                def on_right(e):
                    if idx_ in self._vid_selection:
                        self._on_video_right_click(e)
                    else:
                        if self.video_preview_manager:
                            path_ = self._filtered_videos[idx_]
                            if os.path.isfile(path_):
                                self.video_preview_manager.right_clicked_item = idx_
                                self.video_preview_manager._show_video_preview(
                                    path_, e.x_root, e.y_root)
                    return "break"

                def on_enter(e):
                    if idx_ not in self._vid_selection:
                        r.config(bg=P["item_hover"])
                        for c in cells_:
                            c.config(bg=P["item_hover"])

                def on_leave(e):
                    if idx_ not in self._vid_selection:
                        bg_ = P["item_alt"] if idx_ % 2 else P["panel"]
                        r.config(bg=bg_)
                        for c in cells_: c.config(bg=bg_)

                def on_drag(e):
                    if self._selected_tags or (self._search_var and self._search_var.get().strip()):
                        return
                    if self._dragging_index is None:
                        return
                    canvas_y = r.winfo_y() + e.y
                    ci = max(0, int(canvas_y // self._row_height))
                    ci = min(ci, len(self._filtered_videos) - 1)
                    if ci != self._dragging_index:
                        self._filtered_videos[self._dragging_index], self._filtered_videos[ci] = \
                            self._filtered_videos[ci], self._filtered_videos[self._dragging_index]
                        self._dragging_index = ci
                        self._vid_selection = {ci}
                        self._rebuild_vid_rows()

                def on_release(e):
                    if self._selected_tags or (self._search_var and self._search_var.get().strip()):
                        self._dragging_index = None
                        return
                    if self._dragging_index is not None:
                        self.svc.set_browser_order(list(self._filtered_videos))
                    self._dragging_index = None

                bindable = [r] + [c for c in cells_ if not isinstance(c, tk.Frame)]
                for w in bindable:
                    w.bind("<Button-1>", on_click)
                    w.bind("<Double-Button-1>", on_dbl)
                    w.bind("<Button-3>", on_right)
                    w.bind("<Enter>", on_enter)
                    w.bind("<Leave>", on_leave)
                    w.bind("<B1-Motion>", on_drag)
                    w.bind("<ButtonRelease-1>", on_release)
                    w.bind("<MouseWheel>",
                           lambda e: self._vid_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))

            _bind_row(row, i, cells)
            self._vid_rows.append(row)

        self._vid_canvas.configure(scrollregion=self._vid_canvas.bbox("all"))

        if end < len(snapshot):
            self._vid_canvas.after(0, lambda: self._render_chunk(end, snapshot, snapshot_id, chunk))

    def _remove_tag_from_video(self, path, tag):
        self.svc.remove_tag(path, tag)
        self.refresh()

    def _refresh_row_colors(self):
        tp = self.tp
        P = _p(tp.dark_mode, tp)
        for i, row in enumerate(self._vid_rows):
            is_sel = i in self._vid_selection
            bg_ = P["accent"] if is_sel else (P["item_alt"] if i % 2 else P["panel"])
            fg_ = "white" if is_sel else tp.text_color
            muted_ = "white" if is_sel else tp.muted_fg
            gold_ = "white" if is_sel else P["star_on"]
            row.config(bg=bg_)
            for cell in row.winfo_children():
                col = getattr(cell, '_col_idx', -1)
                if isinstance(cell, tk.Frame):
                    cell.config(bg=bg_)
                    for sub in cell.winfo_children():
                        try:
                            sub.config(bg=bg_)
                        except Exception:
                            pass
                elif col == 1:
                    cell.config(bg=bg_, fg=gold_)
                elif col == 2:
                    cell.config(bg=bg_, fg=muted_)
                else:
                    cell.config(bg=bg_, fg=fg_)

    def _on_search_change(self):
        self.refresh()

    def _clear_filters(self):
        self._selected_tags.clear()
        self._rating_var.set(0)
        P = _p(self.tp.dark_mode, self.tp)
        self._update_rb_visuals(P)
        if self._search_var:
            self._search_var.set("")
        self.refresh()

    # ── Detail panel ──────────────────────────────────────────────────────────

    def _on_video_select(self, event=None):
        if not self._vid_selection:
            return
        idx = min(self._vid_selection)
        if idx < len(self._filtered_videos):
            self._show_detail(self._filtered_videos[idx])

    def _show_detail(self, path: str):
        tp = self.tp
        P = _p(tp.dark_mode, tp)
        rating = self.svc.get_rating(path)
        tags = self.svc.get_tags(path)
        bookmarks = self.svc.get_bookmarks(path)
        name = os.path.basename(path)

        stars_text = "★" * rating if rating else ""
        if self._detail_stars_lbl:
            self._detail_stars_lbl.config(text=stars_text)

        tag_str = "  ".join(f"#{t}" for t in tags) if tags else ""
        detail_text = f"  {name}"
        if tag_str:
            detail_text += f"    {tag_str}"
        if self._detail_lbl:
            self._detail_lbl.config(text=detail_text, fg=tp.text_color)

        if self._detail_path_lbl:
            self._detail_path_lbl.config(text=path)

        if self._bookmark_frame:
            for w in self._bookmark_frame.winfo_children():
                w.destroy()

            if bookmarks:
                tk.Label(self._bookmark_frame, text="BOOKMARKS",
                         font=("Segoe UI", 7, "bold"),
                         bg=P["detail_bg"], fg=tp.muted_fg
                         ).pack(side=tk.LEFT, padx=(2, 10), pady=2)
                for bm in bookmarks[:14]:
                    lbl = bm.get("label", _fmt_ms(bm["ms"]))
                    pill_outer = tk.Frame(self._bookmark_frame,
                                          bg=P["bm_border"],
                                          padx=1, pady=1)
                    pill_outer.pack(side=tk.LEFT, padx=3, pady=2)
                    pill = tk.Label(pill_outer, text=f"🔖 {lbl}",
                                    font=("Segoe UI", 8),
                                    bg=P["bm_bg"], fg=P["bm_fg"],
                                    padx=8, pady=3, cursor="hand2")
                    pill.pack()
                    pill.bind("<Enter>", lambda e, p=pill: p.config(bg=P["tag_sel_bg"]))
                    pill.bind("<Leave>", lambda e, p=pill: p.config(bg=P["bm_bg"]))

    def _clear_detail(self):
        tp = self.tp
        P = _p(tp.dark_mode, tp)
        if self._detail_lbl:
            self._detail_lbl.config(text="  Select a video to see details", fg=tp.muted_fg)
        if self._detail_stars_lbl:
            self._detail_stars_lbl.config(text="")
        if self._detail_path_lbl:
            self._detail_path_lbl.config(text="")
        if self._bookmark_frame:
            for w in self._bookmark_frame.winfo_children():
                w.destroy()

    def _on_mouse_down(self, event):
        if self.video_preview_manager:
            self.video_preview_manager.tooltip.hide_preview()

        index = self._row_at_y(event.y)

        if index < 0 or index >= len(self._filtered_videos):
            return

        ctrl_held  = bool(event.state & 0x4)
        shift_held = bool(event.state & 0x1)
        current_selection = sorted(self._vid_selection)

        if shift_held and current_selection:
            anchor = current_selection[-1]
            start  = min(anchor, index)
            end    = max(anchor, index)
            self._vid_selection = set(range(start, end + 1))
            self._refresh_row_colors()
            self._on_video_select()
            return "break"
        elif ctrl_held:
            if index in self._vid_selection:
                self._vid_selection.discard(index)
            else:
                self._vid_selection.add(index)
            self._refresh_row_colors()
            self._on_video_select()
            return "break"
        else:
            self._vid_selection = {index}
            self._dragging_index = index
            self._refresh_row_colors()
            self._on_video_select()
            return "break"

    def _on_mouse_drag(self, event):
        if self._dragging_index is None or not self._filtered_videos:
            return

        current_index = self._row_at_y(event.y)
        if current_index != self._dragging_index and 0 <= current_index < len(self._filtered_videos):
            self._filtered_videos[self._dragging_index], self._filtered_videos[current_index] = \
                self._filtered_videos[current_index], self._filtered_videos[self._dragging_index]
            self._dragging_index = current_index
            self._vid_selection = {current_index}
            self._rebuild_vid_rows()


    def _on_video_right_click(self, event):
        if not self._win:
            return
        tp = self.tp
        P = _p(tp.dark_mode, tp)

        sel = sorted(self._vid_selection)
        if not sel:
            return

        menu = tp.create_manager_context_menu(self._win)

        n = len(sel)
        menu.add_command(
            label=f"Play selected ({n} video{'s' if n > 1 else ''})",
            command=self._play_selected)
        menu.add_separator()

        menu.add_command(label="Select All", command=self._select_all)
        menu.add_command(label="Clear Selection", command=self._unselect_all)

        menu.add_separator()

        menu.add_command(
            label="Open in Gallery",
            command=lambda: self._open_grid_view_from_selection(sel))
        menu.add_separator()

        paths = [self._filtered_videos[i] for i in sel if i < len(self._filtered_videos)]

        if self.add_to_playlist_callback:
            menu.add_command(label="Add to Playlist",
                             command=lambda ps=paths: self._context_add_to_playlist(ps))
        if self.add_to_queue_callback:
            menu.add_command(label="Add to Queue",
                             command=lambda ps=paths: self._context_add_to_queue(ps))
        if self.is_favourite_callback and (self.add_to_favourites_callback or self.remove_from_favourites_callback):
            all_fav = all(self.is_favourite_callback(p) for p in paths)
            if all_fav and self.remove_from_favourites_callback:
                menu.add_command(label="Remove from Favourites",
                                 command=lambda ps=paths: self._context_remove_from_favourites(ps))
            elif self.add_to_favourites_callback:
                menu.add_command(label="Add to Favourites",
                                 command=lambda ps=paths: self._context_add_to_favourites(ps))
        menu.add_separator()

        if n == 1:
            path = self._filtered_videos[sel[0]]
            menu.add_command(label="📋  Copy path",
                             command=lambda: self._copy_path(path))
            menu.add_command(label="📂  Open file location",
                             command=lambda: self._open_location(path))
            if self.locate_in_panel_callback and os.path.isfile(path):
                menu.add_command(label="Show in Panel",
                                 command=lambda p=path: self.locate_in_panel_callback(p))

        paths = [self._filtered_videos[i] for i in sel if i < len(self._filtered_videos)]
        has_rating = any(self.svc.get_rating(p) > 0 for p in paths)
        has_tags = any(self.svc.get_tags(p) for p in paths)
        has_bookmarks = any(self.svc.get_bookmarks(p) for p in paths)

        if has_rating or has_tags or has_bookmarks:
            menu.add_separator()
            if has_rating:
                menu.add_command(label="☆  Remove rating",
                                 command=lambda ps=paths: self._remove_annotation(ps, rating=True))
            if has_tags:
                menu.add_command(label="🏷  Remove tags",
                                 command=lambda ps=paths: self._remove_annotation(ps, tags=True))
            if has_bookmarks:
                menu.add_command(label="🔖  Remove bookmarks",
                                 command=lambda ps=paths: self._remove_annotation(ps, bookmarks=True))

        self._win.after(10, lambda: _show_menu(menu, event.x_root, event.y_root))

    def _remove_annotation(self, paths, rating=False, tags=False, bookmarks=False):
        for path in paths:
            if rating:
                self.svc.set_rating(path, 0)
            if tags:
                for tag in list(self.svc.get_tags(path)):
                    self.svc.remove_tag(path, tag)
            if bookmarks:
                for bm in list(self.svc.get_bookmarks(path)):
                    self.svc.remove_bookmark(path, bm["ms"])
        self.refresh()
        parts = []
        if rating: parts.append("ratings")
        if tags: parts.append("tags")
        if bookmarks: parts.append("bookmarks")
        self.tp.toast.success("Cleared",
                              f"Removed {', '.join(parts)} from {len(paths)} video{'s' if len(paths) != 1 else ''}")

    def apply_filter_sort(self, filter_sort_manager):
        video_paths = [p for p in getattr(self, '_filtered_videos', []) if os.path.isfile(p)]
        if not video_paths:
            return
        def process():
            try:
                filtered = filter_sort_manager.apply_filter_and_sort(video_paths, load_properties=True)
                self.root.after(0, lambda: self._apply_filter_sort_result(filtered))
            except Exception as e:
                print(f"[AnnotationBrowser] filter_sort error: {e}")
        threading.Thread(target=process, daemon=True).start()

    def _apply_filter_sort_result(self, filtered_paths):
        if not self._win or not self._win.winfo_exists():
            return
        self._filtered_videos = filtered_paths
        self._vid_selection.clear()
        self._rebuild_vid_rows()
        count_text = f"{len(filtered_paths)} video{'s' if len(filtered_paths) != 1 else ''}"
        if hasattr(self, '_count_lbl'):
            self._count_lbl.config(text=count_text)

    def _open_grid_view_from_selection(self, selection):
        if not self.grid_view_manager:
            return
        video_paths = []
        for index in selection:
            if 0 <= index < len(self._filtered_videos):
                path = self._filtered_videos[index]
                if os.path.isfile(path):
                    video_paths.append(path)
        if video_paths:
            self.grid_view_manager.show_grid_view(video_paths, self.video_preview_manager)

    def _copy_path(self, path: str):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(path)
            self.tp.toast.info("Copied", f"Path copied to clipboard")
        except Exception:
            pass

    def _open_location(self, path: str):
        try:
            import subprocess, sys
            if os.name == "nt":
                subprocess.Popen(f'explorer /select,"{path}"')
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception:
            pass

    def _select_all(self, event=None):
        self._vid_selection = set(range(len(self._filtered_videos)))
        self._refresh_row_colors()
        return "break"

    def _unselect_all(self, event=None):
        self._vid_selection.clear()
        self._refresh_row_colors()

    # ── Playback ──────────────────────────────────────────────────────────────

    def _play_smart(self):
        if self._vid_selection:
            self._play_selected()
        else:
            self._play_all()

    def _play_selected(self):
        if not self.play_callback:
            return
        sel = sorted(self._vid_selection)
        if not sel:
            return
        videos = [self._filtered_videos[i] for i in sel if i < len(self._filtered_videos)]
        if videos:
            self.play_callback(videos)

    def _play_all(self):
        if self.play_callback and self._filtered_videos:
            self.play_callback(list(self._filtered_videos))