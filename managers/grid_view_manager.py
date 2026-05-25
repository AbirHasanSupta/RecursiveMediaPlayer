import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import os
import threading
from concurrent.futures import ThreadPoolExecutor
import multiprocessing

from managers.resource_manager import ManagedExecutor, get_resource_manager, ManagedThread
from utils import _responsive_geometry

# ── Design tokens (override per-theme in _get_design_tokens) ─────────────────
_CARD_RADIUS        = 10
_CARD_W             = 240
_CARD_H             = 150   # ~16:9 for ~267px wide
_INFO_H             = 60
_CARD_PAD_X         = 7
_CARD_PAD_Y         = 7
_ACTION_STRIP_H     = 34
_ACTION_STRIP_BG    = "#0c0d11"
_ACTION_STRIP_FG    = "#c8cdd8"
_ACTION_STRIP_SEP   = "#22252e"


def _hex_blend(c1: str, c2: str, t: float) -> str:
    """Linear interpolate between two hex colours (0 = c1, 1 = c2)."""
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


class GridViewItem:
    def __init__(self, video_path, thumbnail_path=None):
        self.video_path = video_path
        self.thumbnail_path = thumbnail_path
        self.thumbnail_image = None


class GridViewManager:
    def __init__(self, root, theme_provider, console_callback=None):
        self.root = root
        self.theme_provider = theme_provider
        self.console_callback = console_callback
        max_workers = min(8, (multiprocessing.cpu_count() or 4))
        self.thumbnail_executor = ManagedExecutor(ThreadPoolExecutor, max_workers=max_workers)
        self.grid_window = None
        self._embedded = False
        self.close_callback = None
        self.items = []
        self.selected_items = set()
        self.card_widgets = {}
        self.excluded_items = set()
        self.is_loading = False
        self.loading_lock = threading.Lock()
        self.pending_tasks = set()
        self._photo_cache = {}
        self._page = 0
        self._page_size = 50
        self._grid_cols = 6
        self._pages_cache = None
        self.now_playing_path = None
        self._now_playing_badge = None
        self._last_anchor_path = None
        self._search_timer = None
        self._hovered_card_path = None
        self.annotation_service = None
        self._active_tag_filters = set()
        self._tag_filter_btn = None
        self._closing = False

        # callbacks
        self.play_callback = None
        self.add_to_playlist_callback = None
        self.add_to_favourites_callback = None
        self.remove_from_favourites_callback = None
        self.is_favourite_callback = None
        self.add_to_queue_callback = None
        self.play_in_dual_player1_callback = None
        self.play_in_dual_player2_callback = None
        self.play_in_dual_player3_callback = None
        self.play_in_dual_player_win2_1_callback = None
        self.play_in_dual_player_win2_2_callback = None
        self.play_in_dual_player_win2_3_callback = None
        self.get_player_count_callback = None
        self.open_file_location_callback = None
        self.show_properties_callback = None
        self.exclude_video_callback = None
        self.remove_exclusion_video_callback = None
        self.locate_in_panel_callback = None

        self._drag_source = None
        self._drag_ghost = None
        self._drag_over_widget = None
        self._drag_type = None

        get_resource_manager().register_cleanup_callback(self._cleanup)
        self.theme_provider.register_manager_ui(self)

    def _cleanup(self):
        try:
            if self.annotation_service and hasattr(self, '_annotation_listener') and self._annotation_listener:
                try:
                    self.annotation_service.unsubscribe(self._annotation_listener)
                except Exception:
                    pass
            with self.loading_lock:
                self.is_loading = False
            for task in list(self.pending_tasks):
                try:
                    task.cancel()
                except Exception:
                    pass
            if hasattr(self, 'thumbnail_executor'):
                try:
                    self.thumbnail_executor.shutdown(wait=False, cancel_futures=False)
                except Exception:
                    pass
            self.items = []
            self.selected_items.clear()
            self.excluded_items.clear()
            self.card_widgets.clear()
            self._photo_cache.clear()
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Callback setters (original)
    # ─────────────────────────────────────────────────────────────────────────

    def set_play_callback(self, cb):                             self.play_callback = cb
    def set_add_to_playlist_callback(self, cb):                  self.add_to_playlist_callback = cb
    def set_add_to_favourites_callback(self, cb):                self.add_to_favourites_callback = cb
    def set_remove_from_favourites_callback(self, cb):           self.remove_from_favourites_callback = cb
    def set_is_favourite_callback(self, cb):                     self.is_favourite_callback = cb
    def set_add_to_queue_callback(self, cb):                     self.add_to_queue_callback = cb
    def set_play_in_dual_player1_callback(self, cb):             self.play_in_dual_player1_callback = cb
    def set_play_in_dual_player2_callback(self, cb):             self.play_in_dual_player2_callback = cb
    def set_play_in_dual_player3_callback(self, cb):             self.play_in_dual_player3_callback = cb
    def set_play_in_dual_player_win2_1_callback(self, cb):       self.play_in_dual_player_win2_1_callback = cb
    def set_play_in_dual_player_win2_2_callback(self, cb):       self.play_in_dual_player_win2_2_callback = cb
    def set_play_in_dual_player_win2_3_callback(self, cb):       self.play_in_dual_player_win2_3_callback = cb
    def set_get_player_count_callback(self, cb):                 self.get_player_count_callback = cb
    def set_open_file_location_callback(self, cb):               self.open_file_location_callback = cb
    def set_show_properties_callback(self, cb):                  self.show_properties_callback = cb
    def set_exclude_video_callback(self, cb):                    self.exclude_video_callback = cb
    def set_remove_exclusion_video_callback(self, cb):           self.remove_exclusion_video_callback = cb
    def set_annotation_service(self, svc):
        self.annotation_service = svc
        if svc:
            self._annotation_listener = self._on_annotation_changed
            svc.subscribe(self._annotation_listener)

    def set_locate_in_panel_callback(self, cb):
        self.locate_in_panel_callback = cb

    def _on_annotation_changed(self):
        if self.grid_window and self.grid_window.winfo_exists():
            self.root.after(0, self._refresh_all_card_tags)

    def _refresh_all_card_tags(self):
        if not (self.grid_window and self.grid_window.winfo_exists()):
            return
        t = self._tok()
        for vp, card in list(self.card_widgets.items()):
            if not card.winfo_exists():
                continue
            info_frame = None
            for child in card.winfo_children():
                if getattr(child, '_is_info', False):
                    info_frame = child
                    break
            if info_frame is None:
                continue
            # Remove existing meta_frame
            for child in list(info_frame.winfo_children()):
                if getattr(child, '_is_meta', False):
                    child.destroy()
            # Rebuild meta_frame
            svc = self.annotation_service
            tags = svc.get_tags(vp)
            rating = svc.get_rating(vp)
            is_fav = (self.is_favourite_callback and self.is_favourite_callback(vp))
            is_sel = vp in self.selected_items
            info_bg = t['accent_dim'] if is_sel else t['surface']
            meta_frame = tk.Frame(info_frame, bg=info_bg, height=18)
            meta_frame._is_meta = True
            meta_frame.pack(fill=tk.X, pady=(4, 0))
            meta_frame.pack_propagate(False)
            if is_fav:
                tk.Label(meta_frame, text="♥", bg=info_bg, fg=t['warn'],
                         font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 4))
            if rating > 0:
                filled = "★" * rating
                empty  = "☆" * (5 - rating)
                tk.Label(meta_frame, text=filled + empty, bg=info_bg, fg=t['warn'],
                         font=("Segoe UI", 7)).pack(side=tk.LEFT, padx=(0, 6))
            for tag in tags[:2]:
                tk.Label(meta_frame, text=f"#{tag}",
                         bg=t['accent_dim'], fg=t['accent'],
                         font=("Segoe UI", 7), padx=5, pady=1).pack(side=tk.LEFT, padx=(0, 3))

    def _refresh_card_meta(self, vp):
        """Immediately rebuild the meta row (fav ♥, rating ★, tags) for a single card."""
        card = self.card_widgets.get(vp)
        if not card or not card.winfo_exists():
            return
        t = self._tok()
        is_sel = vp in self.selected_items
        info_bg = t['accent_dim'] if is_sel else t['surface']
        info_frame = None
        for child in card.winfo_children():
            if getattr(child, '_is_info', False):
                info_frame = child
                break
        if info_frame is None:
            return
        for child in list(info_frame.winfo_children()):
            if getattr(child, '_is_meta', False):
                child.destroy()
        svc    = self.annotation_service
        tags   = svc.get_tags(vp)   if svc else []
        rating = svc.get_rating(vp) if svc else 0
        is_fav = bool(self.is_favourite_callback and self.is_favourite_callback(vp))
        meta_frame = tk.Frame(info_frame, bg=info_bg, height=18)
        meta_frame._is_meta = True
        meta_frame.pack(fill=tk.X, pady=(4, 0))
        meta_frame.pack_propagate(False)
        if is_fav:
            tk.Label(meta_frame, text="♥", bg=info_bg, fg=t['warn'],
                     font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 4))
        if rating > 0:
            filled = "★" * rating
            empty  = "☆" * (5 - rating)
            tk.Label(meta_frame, text=filled + empty, bg=info_bg, fg=t['warn'],
                     font=("Segoe UI", 7)).pack(side=tk.LEFT, padx=(0, 6))
        for tag in tags[:2]:
            tk.Label(meta_frame, text=f"#{tag}",
                     bg=t['accent_dim'], fg=t['accent'],
                     font=("Segoe UI", 7), padx=5, pady=1
                     ).pack(side=tk.LEFT, padx=(0, 3))

    # ─────────────────────────────────────────────────────────────────────────
    # Design tokens (new UI)
    # ─────────────────────────────────────────────────────────────────────────

    def _tok(self):
        """Return design-system tokens derived from theme_provider's dashboard palette."""
        base = self.theme_provider.get_manager_design_tokens()
        dark = getattr(self.theme_provider, 'dark_mode', False)

        # Compute grid‑specific derived colours
        if dark:
            accent_dim = "#172344"
            card_hover = base.get('surface2', "#2e3139")
            pill_bg = base.get('surface2', "#2e3139")
            bar_bg   = base.get('surface2', "#252C38")
            hdr_bg   = base.get('header_bg', "#1A1E26")
        else:
            accent_dim = "#dbeafe"
            card_hover = base.get('surface2', "#edf0f6")
            pill_bg = base.get('surface2', "#edf0f6")
            # Give bars a distinct step darker than the card/canvas bg (#F7F9FC)
            # so sections are clearly layered like dark mode
            bar_bg  = "#EDF1F8"   # toolbar, status strip — subtle step from canvas
            hdr_bg  = base.get('header_bg', "#FFFFFF")  # header unchanged

        return dict(
            # base tokens (direct passthrough)
            bg          = base['bg'],
            surface     = base['surface'],
            surface2    = bar_bg,
            border      = base['border'],
            border_soft = base['divider'],
            text        = base['text'],
            text_sub    = base['text_muted'],
            text_muted  = base['text_muted'],
            accent      = base['accent'],
            success     = base.get('queue_accent', "#3ecf6e"),
            danger      = base.get('accent_secondary', "#f05252"),
            warn        = base.get('favorites_accent', "#F5C518"),
            header_bg   = hdr_bg,
            divider     = base['divider'],
            # grid‑specific overrides / additions
            accent_dim  = accent_dim,
            accent_hover= base['accent'],
            now_playing = base.get('queue_accent', "#3ecf6e"),
            excluded    = base.get('accent_secondary', "#f05252"),
            thumb_bg    = "#0b0c0f" if dark else "#0d0e10",
            pill_bg     = pill_bg,
            pill_bg_h   = bar_bg,
            pill_fg     = base['text_muted'],
            scrollbar   = base['border'],
            card_hover  = card_hover,
        )


    # ─────────────────────────────────────────────────────────────────────────
    # Main window (new UI structure)
    # ─────────────────────────────────────────────────────────────────────────
    def _get_design_tokens(self):
        return self._tok()

    def show_grid_view(self, videos, video_preview_manager=None):
        if hasattr(self.theme_provider, "_open_grid_view"):
            self.theme_provider._open_grid_view(videos)
            return

        if not self._embedded and self.grid_window and self.grid_window.winfo_exists():
            self.grid_window.lift()
            return

        self._embedded = False
        self.close_callback = None

        with self.loading_lock:
            self.is_loading = True

        for task in list(self.pending_tasks):
            try:
                task.cancel()
            except Exception:
                pass
        self.pending_tasks.clear()

        self.video_preview_manager = video_preview_manager
        t = self._tok()

        self.grid_window = tk.Toplevel(self.root)
        self.grid_window.withdraw()
        self.grid_window.title("Video Gallery")
        self.grid_window.geometry(_responsive_geometry(self.root, 1600, 900))
        self.grid_window.configure(bg=t['bg'])

        self.items = []
        self.selected_items = set()
        self.excluded_items = set()
        self._photo_cache.clear()
        self._page = 0
        self._pages_cache = None
        self._active_tag_filters.clear()
        if hasattr(self, 'all_items'):
            del self.all_items

        self._build_ui(videos, t)
        self._update_tag_filter_btn()

        from icon_helper import apply_icon
        apply_icon(self.grid_window)
        self.grid_window.deiconify()

    def show_grid_view_embedded(self, parent, videos, video_preview_manager=None, close_callback=None):
        if not videos:
            return

        with self.loading_lock:
            self.is_loading = True

        for task in list(self.pending_tasks):
            try:
                task.cancel()
            except Exception:
                pass
        self.pending_tasks.clear()

        for child in parent.winfo_children():
            child.destroy()

        self.video_preview_manager = video_preview_manager
        self.grid_window = parent
        self._embedded = True
        self.close_callback = close_callback
        t = self._tok()
        self.grid_window.configure(bg=t['bg'])

        self.items = []
        self.selected_items = set()
        self.excluded_items = set()
        self._photo_cache.clear()
        self._page = 0
        self._pages_cache = None
        self._active_tag_filters.clear()
        if hasattr(self, 'all_items'):
            del self.all_items

        self._closing = False
        self._build_ui(videos, t)
        self._update_tag_filter_btn()
        return self

    def _close_grid_view(self):
        self._teardown_grid_view()
        if self._embedded:
            if self.close_callback:
                self.close_callback()
            return
        if self.grid_window and self.grid_window.winfo_exists():
            self.grid_window.destroy()

    def _teardown_grid_view(self):
        self._closing = True
        with self.loading_lock:
            self.is_loading = False
        for task in list(self.pending_tasks):
            try:
                task.cancel()
            except Exception:
                pass
        self._cancel_drag()
        try:
            if hasattr(self, "canvas") and self.canvas.winfo_exists():
                self.canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass

        self._photo_cache.clear()
        self.now_playing_path = None
        if self._search_timer:
            self.root.after_cancel(self._search_timer)
            self._search_timer = None
        self._active_tag_filters.clear()
        self._update_tag_filter_btn()

    def _build_ui(self, videos, t):
        """Construct the entire window layout using theme tokens."""
        gw = self.grid_window

        # ── Header (icon + title + optional close button) ──────────────────────
        header = tk.Frame(gw, bg=t['header_bg'], height=54)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        h_inner = tk.Frame(header, bg=t['header_bg'])
        h_inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=0)

        # left: icon + title
        title_box = tk.Frame(h_inner, bg=t['header_bg'])
        title_box.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(title_box, text="🖼️", font=("Segoe UI Emoji", 18),
                 bg=t['header_bg'], fg=t['accent']).pack(side=tk.LEFT, padx=(0, 10), pady=14)
        tk.Label(title_box, text="Video Gallery",
                 font=("Segoe UI", 15, "bold"),
                 bg=t['header_bg'], fg=t['text']).pack(side=tk.LEFT, pady=14)

        self.selection_label = tk.Label(
            title_box, text="Nothing selected",
            font=("Segoe UI", 8),
            bg=t['surface2'], fg=t['text_muted'],
            padx=8, pady=3
        )
        self.selection_label.pack(side=tk.LEFT, padx=(12, 0), pady=14)

        self.drag_mode_label = tk.Label(title_box, text="",
            font=("Segoe UI", 8, "italic"),
            bg=t['header_bg'], fg=t['text_muted'])
        self.drag_mode_label.pack(side=tk.LEFT, padx=(6, 0), pady=14)

        if self._embedded and self.close_callback:
            close_btn = tk.Label(
                h_inner, text="✕", font=("Segoe UI", 14),
                bg=t['header_bg'], fg=t['text_sub'],
                cursor="hand2", padx=10
            )
            close_btn.pack(side=tk.RIGHT, pady=14)
            close_btn.bind("<Button-1>", lambda e: self._close_grid_view())
            close_btn.bind("<Enter>", lambda e: close_btn.config(fg=t['danger']))
            close_btn.bind("<Leave>", lambda e: close_btn.config(fg=t['text_sub']))

        # separator line
        tk.Frame(gw, bg=t['divider'], height=1).pack(fill=tk.X)

        # ── Toolbar strip ───────────────────────────────────────────────────────
        toolbar_bg = t['surface2']
        toolbar = tk.Frame(gw, bg=toolbar_bg, height=54)
        toolbar.pack(fill=tk.X, padx=0, pady=(6, 0))
        toolbar.pack_propagate(False)

        inner_tb = tk.Frame(toolbar, bg=toolbar_bg)
        inner_tb.pack(fill=tk.BOTH, expand=True, padx=20)

        # Filter
        tk.Label(inner_tb, text="Filter", font=("Segoe UI", 8),
                 bg=toolbar_bg, fg=t['text_muted']).pack(side=tk.LEFT, padx=(14, 6), pady=12)
        self.search_var = tk.StringVar()
        self.search_var.trace('w', lambda *_: self._on_search_changed())
        search_frame = tk.Frame(inner_tb, bg=t['surface'],
                                highlightthickness=1, highlightbackground=t['border'])
        search_frame.pack(side=tk.LEFT, pady=12)
        tk.Label(search_frame, text="⌕", font=("Segoe UI", 9),
                 bg=t['surface'], fg=t['text_muted']).pack(side=tk.LEFT, padx=(7, 2))
        search_entry = tk.Entry(
            search_frame, textvariable=self.search_var,
            font=("Segoe UI", 8), width=22,
            bg=t['surface'], fg=t['text'],
            relief=tk.FLAT, bd=0,
            insertbackground=t['text']
        )
        search_entry.pack(side=tk.LEFT, ipady=7, padx=(0, 7))

        tk.Frame(inner_tb, bg=t['border'], width=1).pack(side=tk.LEFT, fill=tk.Y, pady=8, padx=2)

        tp = self.theme_provider
        self._tag_filter_btn = tp.create_manager_action_link(
            inner_tb, "All tags ▾", lambda: None, style="secondary"
        )
        self._tag_filter_btn.pack(side=tk.LEFT, padx=(0, 4), pady=12)
        self._tag_filter_btn.bind("<Button-1>", lambda e: self._show_tag_filter_menu(e))

        tk.Frame(inner_tb, bg=t['border'], width=1).pack(side=tk.LEFT, fill=tk.Y, pady=8, padx=8)

        right_tb = tk.Frame(inner_tb, bg=toolbar_bg)
        right_tb.pack(side=tk.RIGHT)

        tk.Label(right_tb, text="Per page", font=("Segoe UI", 8),
                 bg=toolbar_bg, fg=t['text_muted']).pack(side=tk.LEFT, pady=12)
        self._page_size_var = tk.StringVar(value=str(self._page_size))
        om = tk.OptionMenu(right_tb, self._page_size_var,
                           "25", "50", "100", "200", "500",
                           command=self._on_page_size_changed)
        om.configure(font=("Segoe UI", 8), bg=t['surface'], fg=t['text'],
                     relief=tk.FLAT, highlightthickness=1, highlightbackground=t['border'],
                     activebackground=t['surface2'])
        om.pack(side=tk.LEFT, padx=(5, 16), pady=12)

        tk.Frame(right_tb, bg=t['border'], width=1).pack(side=tk.LEFT, fill=tk.Y, pady=8)

        tk.Label(right_tb, text="Columns", font=("Segoe UI", 8),
                 bg=toolbar_bg, fg=t['text_muted']).pack(side=tk.LEFT, padx=(16, 5), pady=12)
        self.grid_size_var = tk.IntVar(value=self._grid_cols)
        spin = tk.Spinbox(
            right_tb, from_=2, to=12, textvariable=self.grid_size_var, width=3,
            command=self._rebuild_grid,
            font=("Segoe UI", 8),
            bg=t['surface'], fg=t['text'],
            relief=tk.FLAT, bd=0,
            highlightthickness=1, highlightbackground=t['border'],
            buttonbackground=toolbar_bg,
            insertbackground=t['text']
        )
        spin.pack(side=tk.LEFT, pady=12)

        # Pagination — centered between left controls and right controls
        self._pagination_frame = tk.Frame(inner_tb, bg=toolbar_bg)
        self._pagination_frame.pack(side=tk.LEFT, expand=True, fill=tk.X)
        self._build_pagination_bar()

        tk.Frame(gw, bg=t['divider'], height=1).pack(fill=tk.X)

        # ── Canvas / scrollable grid ───────────────────────────────────────────
        body = tk.Frame(gw, bg=t['bg'])
        body.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        self.canvas = tk.Canvas(body, bg=t['bg'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.canvas.yview,
                                  style="ExclusionTree.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4))
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.grid_frame = tk.Frame(self.canvas, bg=t['bg'])
        canvas_frame = self.canvas.create_window((0, 0), window=self.grid_frame, anchor='nw')

        self.grid_frame.bind("<Configure>",
                             lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(canvas_frame, width=e.width))
        self.canvas.bind("<Button-1>", lambda e: self._clear_selection())
        self.grid_frame.bind("<Button-1>", lambda e: self._clear_selection())

        def _on_mousewheel(e):
            if self.canvas.winfo_exists():
                self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def _bind_scroll(e=None):
            self.canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_scroll(e=None):
            self.canvas.unbind_all("<MouseWheel>")

        self.canvas.bind("<Enter>", _bind_scroll)
        self.canvas.bind("<Leave>", _unbind_scroll)
        gw.bind("<Enter>", _bind_scroll)
        gw.bind("<Leave>", _unbind_scroll)

        # keyboard shortcuts
        gw.bind("<Control-a>", lambda e: self._select_all())
        gw.bind("<Escape>", lambda e: self._clear_selection())
        gw.bind("<Delete>", lambda e: self._clear_selection())
        gw.bind("<Return>", lambda e: self._play_selected())

        def _on_closing():
            self._teardown_grid_view()
            try:
                self.grid_window.destroy()
            except Exception:
                pass

        if hasattr(gw, "protocol"):
            gw.protocol("WM_DELETE_WINDOW", _on_closing)

        # Start loading videos (unchanged)
        ManagedThread(target=self._load_videos, args=(videos,), name="LoadGridVideos").start()

    # ─────────────────────────────────────────────────────────────────────────
    # Widget helpers (new UI)
    # ─────────────────────────────────────────────────────────────────────────
    def _show_tag_filter_menu(self, event):
        if not self.annotation_service:
            return
        all_tags = set()
        for it in getattr(self, 'all_items', self.items):
            if it['type'] == 'video':
                for tag in self.annotation_service.get_tags(it['path']):
                    all_tags.add(tag)
        if not all_tags:
            return

        menu = self.theme_provider.create_manager_context_menu(self.grid_window)

        if self._active_tag_filters:
            menu.add_command(label="Clear tag filter", command=lambda: (
                self._active_tag_filters.clear(),
                self._update_tag_filter_btn(),
                self._apply_tag_filter()
            ))
            menu.add_separator()

        def toggle_tag(tag):
            if tag in self._active_tag_filters:
                self._active_tag_filters.discard(tag)
            else:
                self._active_tag_filters.add(tag)
            self._update_tag_filter_btn()
            self._apply_tag_filter()

        for tag in sorted(all_tags):
            check = "✓ " if tag in self._active_tag_filters else "   "
            menu.add_command(label=f"{check}{tag}", command=lambda tg=tag: toggle_tag(tg))

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _update_tag_filter_btn(self):
        if not self._tag_filter_btn:
            return
        t = self._tok()
        tp = self.theme_provider
        if self._active_tag_filters:
            label = f"Tags: {', '.join(sorted(self._active_tag_filters)[:2])}"
            if len(self._active_tag_filters) > 2:
                label += f" +{len(self._active_tag_filters) - 2}"
            label += " ▾"
            idle, hover, active = tp._manager_action_link_colors("primary", tp.get_manager_design_tokens())
            self._tag_filter_btn.config(text=label, fg=idle)
            self._tag_filter_btn._link_idle = idle
            self._tag_filter_btn._link_hover = hover
            self._tag_filter_btn._link_active = active
        else:
            idle, hover, active = tp._manager_action_link_colors("secondary", tp.get_manager_design_tokens())
            self._tag_filter_btn.config(text="All tags ▾", fg=idle)
            self._tag_filter_btn._link_idle = idle
            self._tag_filter_btn._link_hover = hover
            self._tag_filter_btn._link_active = active

    def _apply_tag_filter(self):
        self._page = 0
        self._pages_cache = None
        if not hasattr(self, 'all_items'):
            self.all_items = self.items.copy()

        term = self.search_var.get().lower() if hasattr(self, 'search_var') else ""
        active_tags = self._active_tag_filters

        if not active_tags and not term:
            self.items = self.all_items.copy()
            self.root.after(0, self._rebuild_grid)
            return

        self.items = []
        current_header = None
        current_dir_items = []
        for item_data in self.all_items:
            if item_data['type'] == 'header':
                if current_header and current_dir_items:
                    self.items.append(current_header)
                    self.items.extend(current_dir_items)
                current_header = item_data.copy()
                current_dir_items = []
                current_header['matches'] = term in item_data['name'].lower() if term else True
            elif item_data['type'] == 'video':
                name_ok = not term or term in os.path.basename(item_data['path']).lower() or (
                            current_header and current_header.get('matches'))
                if active_tags and self.annotation_service:
                    video_tags = set(self.annotation_service.get_tags(item_data['path']))
                    tag_ok = bool(active_tags & video_tags)
                else:
                    tag_ok = True
                if name_ok and tag_ok:
                    current_dir_items.append(item_data)
        if current_header and current_dir_items:
            self.items.append(current_header)
            self.items.extend(current_dir_items)

        self.root.after(0, self._rebuild_grid)


    def apply_theme(self):
        if not self.grid_window:
            return
        try:
            if not self.grid_window.winfo_exists():
                return
        except tk.TclError:
            return
        t = self._tok()
        tp = self.theme_provider
        self.grid_window.configure(bg=t['bg'])
        tp.restyle_manager_action_links(self.grid_window)
        tp.restyle_manager_buttons(self.grid_window)
        self._update_tag_filter_btn()
        self._rebuild_grid()

    def play_from_global(self):
        """Play selected videos, or all videos if nothing selected."""
        videos = self._get_selected_videos()
        if not videos and self.items:
            videos = [it['path'] for it in self.items if it['type'] == 'video']
        if videos and self.play_callback:
            self.play_callback(videos)

    def _make_btn(self, parent, text, cmd, bg, fg, hover=None, variant="primary"):
        """Theme-aligned button using variant system."""
        tp = self.theme_provider
        colors = tp.get_button_colors(variant)
        btn = tk.Button(
            parent, text=text,
            font=("Segoe UI", 9, "bold"),
            bg=colors["bg"], fg=colors["fg"],
            relief=tk.FLAT, bd=0,
            padx=18, pady=7,
            cursor="hand2",
            activebackground=colors["active"],
            activeforeground="#FFFFFF",
        )
        btn._variant = variant
        btn.bind("<Button-1>", lambda e: cmd())
        tp._bind_button_hover(btn, variant)
        return btn

    def _make_pill_btn(self, parent, text, cmd, t):
        """Action-link style pill for toolbar/pagination – no box border."""
        tp = self.theme_provider
        btn = tp.create_manager_action_link(parent, text, cmd, style="secondary")
        return btn

    # ─────────────────────────────────────────────────────────────────────────
    # Loading (original backend)
    # ─────────────────────────────────────────────────────────────────────────

    def _load_videos(self, videos):
        try:
            with self.loading_lock:
                if not self.is_loading:
                    return
            from collections import defaultdict, OrderedDict
            dir_order = []
            dir_groups = OrderedDict()
            for video in videos:
                dir_path = os.path.dirname(video)
                if dir_path not in dir_groups:
                    dir_groups[dir_path] = []
                    dir_order.append(dir_path)
                dir_groups[dir_path].append(video)

            self.items = []
            for dir_path in dir_order:
                video_count = len(dir_groups[dir_path])
                self.items.append({
                    'type': 'header',
                    'path': dir_path,
                    'name': os.path.basename(dir_path) or dir_path,
                    'video_count': video_count
                })
                for video in dir_groups[dir_path]:
                    self.items.append({'type': 'video', 'path': video, 'video_item': GridViewItem(video)})

            self.all_items = self.items.copy()
            self._pages_cache = None

            # Prioritize these videos in the prefetch queue (original behaviour kept)
            if self.video_preview_manager:
                grid_videos = [it['path'] for it in self.items if it['type'] == 'video']
                if grid_videos:
                    self.video_preview_manager.prioritize_for_grid(grid_videos)

            term = self.search_var.get().lower() if hasattr(self, 'search_var') else ""
            if term or self._active_tag_filters:
                self.root.after(0, self._filter_directories)
            else:
                self.root.after(0, self._rebuild_grid)
        except Exception as e:
            with self.loading_lock:
                self.is_loading = False

    # ─────────────────────────────────────────────────────────────────────────
    # Pagination (original logic, with new UI pagination bar)
    # ─────────────────────────────────────────────────────────────────────────

    def _get_page_items(self):
        """Return items for the current page, never splitting a folder across pages."""
        target = self._page_size
        pages = []
        current_page = []
        current_count = 0

        i = 0
        all_items = self.items
        while i < len(all_items):
            item = all_items[i]
            if item['type'] == 'header':
                folder_block = [item]
                i += 1
                while i < len(all_items) and all_items[i]['type'] == 'video':
                    folder_block.append(all_items[i])
                    i += 1
                folder_video_count = len(folder_block) - 1

                if current_count > 0 and current_count + folder_video_count > target:
                    pages.append(current_page)
                    current_page = []
                    current_count = 0

                current_page.extend(folder_block)
                current_count += folder_video_count
            else:
                i += 1

        if current_page:
            pages.append(current_page)

        self._pages_cache = pages
        total = len(pages)
        if total == 0:
            return []
        self._page = max(0, min(self._page, total - 1))
        return pages[self._page]

    def _total_pages(self):
        if not hasattr(self, '_pages_cache') or self._pages_cache is None:
            self._get_page_items()
        return max(1, len(self._pages_cache))

    def _next_page(self):
        if self._page < self._total_pages() - 1:
            self._page += 1
            self._rebuild_grid()
            try:
                self.canvas.yview_moveto(0)
            except Exception:
                pass

    def _prev_page(self):
        if self._page > 0:
            self._page -= 1
            self._rebuild_grid()
            try:
                self.canvas.yview_moveto(0)
            except Exception:
                pass

    def _jump_to_page(self):
        try:
            p = max(0, min(int(self._jump_var.get()) - 1, self._total_pages() - 1))
            self._page = p
            self._rebuild_grid()
            try:
                self.canvas.yview_moveto(0)
            except Exception:
                pass
        except ValueError:
            pass

    def _on_page_size_changed(self, value):
        self._page_size = int(value)
        self._page = 0
        self._pages_cache = None
        self._rebuild_grid()
        try:
            self.canvas.yview_moveto(0)
        except Exception:
            pass

    def _build_pagination_bar(self):
        if not hasattr(self, '_pagination_frame') or not self._pagination_frame.winfo_exists():
            return
        for w in self._pagination_frame.winfo_children():
            w.destroy()

        t = self._tok()
        self._get_page_items()
        total_pages = self._total_pages()
        total_videos = sum(1 for i in self.items if i['type'] == 'video')

        bar_bg = t['surface2']

        tk.Frame(self._pagination_frame, bg=bar_bg).pack(side=tk.LEFT, expand=True, fill=tk.X)
        pg = tk.Frame(self._pagination_frame, bg=bar_bg)
        pg.pack(side=tk.LEFT)
        tk.Frame(self._pagination_frame, bg=bar_bg).pack(side=tk.LEFT, expand=True, fill=tk.X)

        def _nav(text, cmd, active):
            fg = t['text_sub'] if active else t['border']
            lbl = tk.Label(pg, text=text, font=("Segoe UI", 14),
                           bg=bar_bg, fg=fg,
                           cursor="hand2" if active else "arrow", padx=3)
            if active:
                lbl.bind("<Button-1>", lambda e: cmd())
                lbl.bind("<Enter>", lambda e: lbl.config(fg=t['accent']))
                lbl.bind("<Leave>", lambda e: lbl.config(fg=fg))
            return lbl

        _nav("‹", self._prev_page, self._page > 0).pack(side=tk.LEFT, padx=(0, 2))

        pill = tk.Frame(pg, bg=t['border_soft'], padx=6, pady=0)
        pill.pack(side=tk.LEFT, padx=4)
        tk.Label(pill, text=f"{self._page + 1} / {total_pages}",
                 font=("Segoe UI", 10), bg=t['border_soft'], fg=t['text_sub']).pack(pady=2)

        _nav("›", self._next_page, self._page < total_pages - 1).pack(side=tk.LEFT, padx=(2, 8))

        tk.Label(pg, text="·", font=("Segoe UI", 10), bg=bar_bg, fg=t['border']).pack(side=tk.LEFT, padx=3)
        tk.Label(pg, text=f"{total_videos:,} videos",
                 font=("Segoe UI", 9), bg=bar_bg, fg=t['text_muted']).pack(side=tk.LEFT, padx=(4, 8))
        tk.Label(pg, text="·", font=("Segoe UI", 10), bg=bar_bg, fg=t['border']).pack(side=tk.LEFT, padx=3)

        tk.Label(pg, text="Go", font=("Segoe UI", 10),
                 bg=bar_bg, fg=t['text_muted']).pack(side=tk.LEFT, padx=(4, 2))
        self._jump_var = tk.StringVar(value=str(self._page + 1))
        jump_entry = tk.Entry(
            pg, textvariable=self._jump_var, width=3,
            font=("Segoe UI", 10),
            bg=t['surface'], fg=t['text'],
            relief=tk.FLAT, bd=0,
            highlightthickness=1, highlightbackground=t['border'],
            insertbackground=t['text']
        )
        jump_entry.pack(side=tk.LEFT, padx=(0, 2), ipady=1)
        jump_entry.bind("<Return>", lambda e: self._jump_to_page())

    # ─────────────────────────────────────────────────────────────────────────
    # Grid rebuild (new UI cards with original thumbnail loading)
    # ─────────────────────────────────────────────────────────────────────────

    def _rebuild_grid(self):
        if getattr(self, '_closing', False):
            return
        try:
            if not self.grid_frame or not self.grid_frame.winfo_exists():
                return
        except Exception:
            return

        # Persist column count and page size across rebuilds / re-opens
        if hasattr(self, 'grid_size_var'):
            self._grid_cols = self.grid_size_var.get()

        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.card_widgets.clear()

        t = self._tok()
        cols = self.grid_size_var.get()

        self._build_pagination_bar()

        if not self.items:
            tk.Label(
                self.grid_frame,
                text="No videos found",
                font=("Segoe UI", 14),
                bg=t['bg'], fg=t['text_muted']
            ).pack(pady=80)
            return

        page_items = self._get_page_items()
        grid_row = -1
        video_col = 0

        for item_data in page_items:
            if item_data['type'] == 'header':
                grid_row += 1
                video_col = 0
                self._build_header(item_data, grid_row, cols, t)
                grid_row += 1
                continue

            item      = item_data['video_item']
            vp        = item_data['path']
            is_sel    = vp in self.selected_items
            is_excl   = vp in self.excluded_items

            self._build_card(item, vp, is_sel, is_excl, grid_row, video_col, t)

            video_col += 1
            if video_col >= cols:
                video_col = 0
                grid_row += 1

        for i in range(cols):
            self.grid_frame.columnconfigure(i, weight=1, uniform="col")

        self._update_selection_label()

    # ─────────────────────────────────────────────────────────────────────────
    # Header row (new UI)
    # ─────────────────────────────────────────────────────────────────────────

    def _build_header(self, item_data, grid_row, cols, t):
        dir_path = item_data['path']

        header = tk.Frame(
            self.grid_frame,
            bg=t['bg'],
            cursor="arrow"
        )
        header.grid(row=grid_row, column=0, columnspan=cols,
                    sticky='ew', padx=_CARD_PAD_X, pady=(28, 8))
        item_data['_header_widget'] = header

        # Accent left bar
        tk.Frame(header, bg=t['accent'], width=3).pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        left = tk.Frame(header, bg=t['bg'])
        left.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=2)

        drag_hint = tk.Label(
            left, text="⠿",
            font=("Segoe UI", 12),
            bg=t['bg'], fg=t['text_muted'],
            cursor="fleur", padx=2
        )
        drag_hint.pack(side=tk.LEFT)

        dir_label = tk.Label(
            left,
            text=f"📁  {item_data['name']}",
            font=("Segoe UI", 12, "bold"),
            bg=t['bg'], fg=t['text'],
            anchor='w', cursor="hand2"
        )
        dir_label.pack(side=tk.LEFT, padx=(6, 0))

        cnt = item_data.get('video_count', 0)
        count_badge = tk.Label(
            left,
            text=f"  {cnt} video{'s' if cnt != 1 else ''}  ",
            font=("Segoe UI", 8),
            bg=t['pill_bg'], fg=t['text_sub'],
            padx=6, pady=3, cursor="hand2",
            relief=tk.FLAT
        )
        count_badge.pack(side=tk.LEFT, padx=10, anchor='w', pady=3)

        # Separator line
        tk.Frame(header, bg=t['divider'], height=1).pack(
            side=tk.BOTTOM, fill=tk.X, pady=(6, 0))

        # Drag bindings on the drag handle only
        for w in (drag_hint,):
            w.bind("<Button-1>",
                   lambda e, dp=dir_path, hw=header: self._on_dir_header_press(e, dp, hw))
            w.bind("<B1-Motion>",
                   lambda e, dp=dir_path: self._on_dir_header_motion(e, dp))
            w.bind("<ButtonRelease-1>",
                   lambda e, dp=dir_path: self._on_dir_header_release(e, dp))

        for w in (header, dir_label, count_badge, left):
            w.bind("<Button-1>", lambda e, dp=dir_path: self._on_dir_click(e, dp))

    # ─────────────────────────────────────────────────────────────────────────
    # Video card (new UI style, original thumbnail loading)
    # ─────────────────────────────────────────────────────────────────────────

    def _build_card(self, item, vp, is_sel, is_excl, grid_row, video_col, t):
        # ── State-driven colours ──────────────────────────────────────────────
        dark = getattr(self.theme_provider, 'dark_mode', False)
        if is_sel:
            border_col, border_w = t['accent'], 3
            card_bg = info_bg  = t['accent_dim']
            name_fg, name_w    = t['accent'], "bold"
        elif is_excl:
            border_col, border_w = t['excluded'], 2
            card_bg = info_bg  = t['surface']
            name_fg, name_w    = t['text_muted'], "normal"
        else:
            border_col, border_w = t['border'], 1
            card_bg = info_bg  = t['surface']
            name_fg, name_w    = t['text'], "normal"

        card = tk.Frame(
            self.grid_frame, bg=card_bg,
            relief=tk.FLAT, bd=0,
            highlightthickness=border_w,
            highlightbackground=border_col,
            cursor="hand2"
        )
        card.grid(row=grid_row, column=video_col,
                  padx=_CARD_PAD_X, pady=_CARD_PAD_Y, sticky='nsew')
        self.card_widgets[vp] = card

        # ── Thumbnail container ───────────────────────────────────────────────
        thumb_container = tk.Frame(
            card, bg=t['thumb_bg'],
            width=_CARD_W, height=_CARD_H, highlightthickness=0
        )
        thumb_container._is_thumb = True
        thumb_container.pack(fill=tk.BOTH, expand=True)
        thumb_container.pack_propagate(False)

        thumb_label = tk.Label(
            thumb_container, bg=t['thumb_bg'], fg="#2e323c",
            text="▶", font=("Segoe UI", 18)
        )
        thumb_label.pack(fill=tk.BOTH, expand=True)

        # Status badges
        if is_excl:
            excl_badge = tk.Label(
                thumb_container, text=" 🚫 Excluded ",
                bg=t['excluded'], fg="#ffffff",
                font=("Segoe UI", 8, "bold"), padx=4, pady=3
            )
            excl_badge._is_excluded_badge = True
            excl_badge.place(relx=0.0, rely=0.0, anchor='nw')

        if self.now_playing_path and os.path.normpath(vp) == self.now_playing_path:
            self._place_now_playing_badge(thumb_container, t)

        # ── Hover action strip (hidden until hover) ───────────────────────────
        action_strip = tk.Frame(
            thumb_container, bg=_ACTION_STRIP_BG, height=_ACTION_STRIP_H
        )
        action_strip._is_action_strip = True

        def _make_action_btn(parent, text, fg=_ACTION_STRIP_FG, bold=False):
            weight = "bold" if bold else "normal"
            lbl = tk.Label(
                parent, text=text,
                bg=_ACTION_STRIP_BG, fg=fg,
                font=("Segoe UI", 8, weight),
                padx=10, pady=0, cursor="hand2"
            )
            lbl.pack(side=tk.LEFT, fill=tk.Y)
            return lbl

        def _sep(parent):
            tk.Frame(parent, bg=_ACTION_STRIP_SEP, width=1).pack(
                side=tk.LEFT, fill=tk.Y, pady=6)

        play_btn = _make_action_btn(action_strip, "▶  Play", fg="#ffffff", bold=True)
        _sep(action_strip)
        q_btn    = _make_action_btn(action_strip, "+ Queue")
        _sep(action_strip)
        fav_btn  = _make_action_btn(action_strip, "♥ Fav")

        _accent = t['accent']
        for _btn, _hfg, _hbg in (
            (play_btn, "#ffffff", _accent),
            (q_btn,    "#d0d6e8", "#1a1d28"),
            (fav_btn,  "#F5C518", "#1a1d28"),
        ):
            _btn.bind("<Enter>", lambda e, b=_btn, hf=_hfg, hb=_hbg:
                      b.configure(fg=hf, bg=hb))
            _btn.bind("<Leave>", lambda e, b=_btn:
                      b.configure(fg="#ffffff" if b is play_btn else (_ACTION_STRIP_FG if b is q_btn else _ACTION_STRIP_FG),
                                  bg=_ACTION_STRIP_BG))

        play_btn.bind("<Button-1>",   lambda e, _vp=vp: self._play_single(_vp))
        q_btn.bind("<Button-1>",      lambda e, _vp=vp: self._add_single_to_queue(_vp))
        fav_btn.bind("<Button-1>",    lambda e, _vp=vp: self._toggle_favourite_single(_vp))

        # ── Thumbnail loading (3-level cache, unchanged) ──────────────────────
        video_path_norm = os.path.normpath(vp)
        cached_photo = self._photo_cache.get(video_path_norm)
        if cached_photo is None and self.video_preview_manager and \
                hasattr(self.video_preview_manager, 'lru_cache'):
            cached_photo = self.video_preview_manager.lru_cache.get(video_path_norm)
            if cached_photo is not None:
                self._photo_cache[video_path_norm] = cached_photo
        if cached_photo is not None:
            self._set_thumbnail(thumb_label, cached_photo)
        else:
            self.thumbnail_executor.submit(
                self._load_thumbnail, item, thumb_label, video_path_norm)

        # ── Info panel ────────────────────────────────────────────────────────
        tk.Frame(card, bg=t['border'], height=1).pack(fill=tk.X)
        info_frame = tk.Frame(card, bg=info_bg, padx=10, pady=7, cursor="fleur")
        info_frame._is_info = True
        info_frame.pack(fill=tk.X)

        # Show filename without extension
        raw_name = os.path.basename(item.video_path)
        display_name = os.path.splitext(raw_name)[0]
        if len(display_name) > 34:
            display_name = display_name[:31] + "…"

        name_label = tk.Label(
            info_frame, text=display_name,
            bg=info_bg, fg=name_fg,
            font=("Segoe UI", 8, name_w),
            anchor='w', justify=tk.LEFT
        )
        name_label.pack(fill=tk.X)

        # Meta row — always rendered (fixed height) so all cards are the same size
        svc    = self.annotation_service
        tags   = svc.get_tags(vp)   if svc else []
        rating = svc.get_rating(vp) if svc else 0
        is_fav = bool(self.is_favourite_callback and self.is_favourite_callback(vp))

        meta_frame = tk.Frame(info_frame, bg=info_bg, height=18)
        meta_frame._is_meta = True
        meta_frame.pack(fill=tk.X, pady=(4, 0))
        meta_frame.pack_propagate(False)
        if is_fav:
            tk.Label(meta_frame, text="♥", bg=info_bg, fg=t['warn'],
                     font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 4))
        if rating > 0:
            filled = "★" * rating
            empty  = "☆" * (5 - rating)
            tk.Label(meta_frame, text=filled + empty, bg=info_bg, fg=t['warn'],
                     font=("Segoe UI", 7)).pack(side=tk.LEFT, padx=(0, 6))
        for tag in tags[:2]:
            tk.Label(meta_frame, text=f"#{tag}",
                     bg=t['accent_dim'], fg=t['accent'],
                     font=("Segoe UI", 7), padx=5, pady=1
                     ).pack(side=tk.LEFT, padx=(0, 3))

        # ── Bindings ──────────────────────────────────────────────────────────
        for w in (card, thumb_container, thumb_label, name_label, info_frame):
            w.bind("<Button-1>",
                   lambda e, _vp=vp, _cw=card: self._on_card_click_or_press(e, _vp, _cw))
            w.bind("<B1-Motion>",       lambda e, _vp=vp: self._on_card_motion(e, _vp))
            w.bind("<ButtonRelease-1>", lambda e, _vp=vp: self._on_card_release(e, _vp))
            w.bind("<Button-3>",        lambda e, _vp=vp: self._on_card_right_click(e, _vp))
            w.bind("<Double-Button-1>", lambda e, _vp=vp: self._play_single(_vp))

        # Info frame is the drag handle (cursor already fleur)
        info_frame.bind("<Button-1>",
                        lambda e, _vp=vp, _cw=card: self._on_card_press(e, _vp, _cw))
        info_frame.bind("<B1-Motion>",       lambda e, _vp=vp: self._on_card_motion(e, _vp))
        info_frame.bind("<ButtonRelease-1>", lambda e, _vp=vp: self._on_card_release(e, _vp))

        # Action strip buttons get their own Double-click so it doesn't bubble strangely
        play_btn.bind("<Double-Button-1>", lambda e, _vp=vp: self._play_single(_vp))

        card.bind("<Enter>", lambda e, _vp=vp: self._on_card_enter(e, _vp))
        card.bind("<Leave>", lambda e, _vp=vp: self._on_card_leave(e, _vp))

    def _place_now_playing_badge(self, thumb_container, t):
        badge = tk.Label(
            thumb_container,
            text="  ▶  NOW PLAYING  ",
            bg=t['now_playing'], fg="#000000",
            font=("Segoe UI", 8, "bold"),
            padx=4, pady=3
        )
        badge._is_now_playing_badge = True
        badge.place(relx=0.0, rely=1.0, anchor='sw')

    # ─────────────────────────────────────────────────────────────────────────
    # Card state refresh (adapted to new token colours)
    # ─────────────────────────────────────────────────────────────────────────

    def _refresh_card_playing_state(self, video_path, card, is_playing):
        try:
            if not card.winfo_exists():
                return
            t = self._tok()
            is_selected = video_path in self.selected_items
            is_excluded = video_path in self.excluded_items

            if is_playing:
                border_col, border_w = t['now_playing'], 3
            elif is_selected:
                border_col, border_w = t['accent'], 2
            elif is_excluded:
                border_col, border_w = t['excluded'], 2
            else:
                border_col, border_w = t['border'], 1

            card.config(highlightbackground=border_col, highlightthickness=border_w)

            thumb_container = None
            for child in card.winfo_children():
                if getattr(child, '_is_thumb', False):
                    thumb_container = child
                    break
            if thumb_container is None:
                return

            for child in thumb_container.winfo_children():
                if getattr(child, '_is_now_playing_badge', False):
                    child.destroy()

            if is_playing:
                self._place_now_playing_badge(thumb_container, t)

        except Exception:
            pass

    def mark_now_playing(self, video_path):
        old_path = self.now_playing_path
        self.now_playing_path = os.path.normpath(video_path) if video_path else None
        try:
            if not (self.grid_window and self.grid_window.winfo_exists()):
                return
            for path, card in list(self.card_widgets.items()):
                norm = os.path.normpath(path)
                is_now  = (norm == self.now_playing_path)
                was_now = (norm == (os.path.normpath(old_path) if old_path else None))
                if is_now or was_now:
                    self._refresh_card_playing_state(path, card, is_now)
        except Exception:
            pass

    def _update_card_selection(self, video_path):
        if video_path not in self.card_widgets:
            return
        card = self.card_widgets[video_path]
        if not card.winfo_exists():
            return

        t = self._tok()
        is_sel  = video_path in self.selected_items
        is_excl = video_path in self.excluded_items

        if is_sel:
            border_col, border_w = t['accent'],    3
            card_bg = info_bg    = t['accent_dim']
            name_fg, name_w      = t['accent'], "bold"
        elif is_excl:
            border_col, border_w = t['excluded'],  2
            card_bg = info_bg    = t['surface']
            name_fg, name_w      = t['text_muted'], "normal"
        else:
            border_col, border_w = t['border'],    1
            card_bg = info_bg    = t['surface']
            name_fg, name_w      = t['text'], "normal"

        card.configure(bg=card_bg,
                       highlightbackground=border_col,
                       highlightthickness=border_w)

        thumb_container = info_frame = name_label = None
        for child in card.winfo_children():
            if getattr(child, '_is_thumb', False):
                thumb_container = child
            elif getattr(child, '_is_info', False):
                info_frame = child
                for lbl in child.winfo_children():
                    if isinstance(lbl, tk.Label) and name_label is None:
                        name_label = lbl

        if info_frame:
            info_frame.configure(bg=info_bg)
            for lbl in info_frame.winfo_children():
                try:
                    lbl.configure(bg=info_bg)
                except tk.TclError:
                    pass
        # Update the thin divider frame between thumb and info
        for child in card.winfo_children():
            if not getattr(child, '_is_thumb', False) and not getattr(child, '_is_info', False):
                try:
                    child.configure(bg=t['border'])
                except tk.TclError:
                    pass
        if name_label:
            name_label.configure(fg=name_fg, font=("Segoe UI", 8, name_w))

        self._refresh_excluded_badge(thumb_container, is_excl)

    def _refresh_excluded_badge(self, thumb_container, is_excluded):
        if thumb_container is None:
            return
        for child in thumb_container.winfo_children():
            if isinstance(child, tk.Label) and getattr(child, '_is_excluded_badge', False):
                child.destroy()
        if is_excluded:
            t = self._tok()
            badge = tk.Label(
                thumb_container,
                text="  🚫  Excluded  ",
                bg=t['excluded'], fg="#ffffff",
                font=("Segoe UI", 8, "bold"),
                padx=4, pady=3
            )
            badge._is_excluded_badge = True
            badge.place(relx=0.0, rely=0.0, anchor='nw')

    # ─────────────────────────────────────────────────────────────────────────
    # Selection (original logic)
    # ─────────────────────────────────────────────────────────────────────────

    def _select_all(self):
        page_items = self._pages_cache[self._page] if self._pages_cache else self.items
        for item_data in page_items:
            if item_data['type'] == 'video':
                self.selected_items.add(item_data['path'])
                self._update_card_selection(item_data['path'])
        self._update_selection_label()

    def _clear_selection(self):
        old = self.selected_items.copy()
        self.selected_items.clear()
        self._last_anchor_path = None
        for vp in old:
            self._update_card_selection(vp)
        self._update_selection_label()

    def _toggle_select(self, vp):
        if vp in self.selected_items:
            self.selected_items.remove(vp)
        else:
            self.selected_items.add(vp)
        self._update_card_selection(vp)
        self._update_selection_label()

    def _update_selection_label(self):
        if not hasattr(self, 'selection_label'):
            return
        try:
            if not self.selection_label.winfo_exists():
                return
        except tk.TclError:
            return
        t = self._tok()
        n = len(self.selected_items)
        if n == 0:
            self.selection_label.config(text="Nothing selected",
                                        bg=t['surface2'], fg=t['text_muted'])
        elif n == 1:
            self.selection_label.config(text="1 selected",
                                        bg=t['accent_dim'], fg=t['accent'])
        else:
            self.selection_label.config(text=f"{n} selected",
                                        bg=t['accent_dim'], fg=t['accent'])

    # ─────────────────────────────────────────────────────────────────────────
    # Playback (original)
    # ─────────────────────────────────────────────────────────────────────────

    def _play_selected(self):
        videos = self._get_selected_videos()
        if not videos or not self.play_callback:
            return
        start_index = 0
        hovered = self._hovered_card_path
        if hovered and hovered in videos:
            start_index = videos.index(hovered)
        if start_index == 0:
            hovered = getattr(self, '_last_right_clicked_path', None)
            if hovered and hovered in videos:
                start_index = videos.index(hovered)
        self.play_callback(videos, start_index=start_index)

    def _play_single(self, vp):
        old = self.selected_items.copy()
        self.selected_items = {vp}
        for op in old:
            if op != vp:
                self._update_card_selection(op)
        if vp not in old:
            self._update_card_selection(vp)
        self._update_selection_label()
        self._play_selected()

    def _get_selected_videos(self):
        return [it['path'] for it in self.items
                if it['type'] == 'video'
                and it['path'] in self.selected_items
                and it['path'] not in self.excluded_items]

    # ─────────────────────────────────────────────────────────────────────────
    # Click handlers (original, using new selection label)
    # ─────────────────────────────────────────────────────────────────────────

    def _on_card_click_or_press(self, event, vp, card_widget):
        self._on_card_press(event, vp, card_widget)
        self._on_card_click(event, vp)

    def _on_card_click(self, event, vp):
        if self.video_preview_manager:
            self.video_preview_manager.tooltip.hide_preview()

        ctrl  = bool(event.state & 0x4)
        shift = bool(event.state & 0x1)
        video_paths = [it['path'] for it in self.items if it['type'] == 'video']

        if vp not in video_paths:
            return
        idx = video_paths.index(vp)

        if shift:
            anchor = getattr(self, '_last_anchor_path', None)
            ai = video_paths.index(anchor) if anchor in video_paths else idx
            for i in range(min(ai, idx), max(ai, idx) + 1):
                self.selected_items.add(video_paths[i])
                self._update_card_selection(video_paths[i])
        elif ctrl:
            if vp in self.selected_items:
                self.selected_items.remove(vp)
            else:
                self.selected_items.add(vp)
            self._update_card_selection(vp)
            self._last_anchor_path = vp
        else:
            old = self.selected_items.copy()
            self.selected_items = {vp}
            for op in old:
                if op != vp:
                    self._update_card_selection(op)
            self._update_card_selection(vp)
            self._last_anchor_path = vp

        self._update_selection_label()

    def _on_dir_click(self, event, dir_path):
        if self.video_preview_manager:
            self.video_preview_manager.tooltip.hide_preview()

        ctrl  = bool(event.state & 0x4)
        shift = bool(event.state & 0x1)
        dir_vps = [it['path'] for it in self.items
                   if it['type'] == 'video' and os.path.dirname(it['path']) == dir_path]
        if not dir_vps:
            return
        all_vps = [it['path'] for it in self.items if it['type'] == 'video']

        if shift and getattr(self, '_last_anchor_path', None) in all_vps:
            ai  = all_vps.index(self._last_anchor_path)
            dis = [all_vps.index(vp) for vp in dir_vps]
            ti  = dis[-1] if dis[-1] > ai else dis[0]
            for i in range(min(ai, ti), max(ai, ti) + 1):
                self.selected_items.add(all_vps[i])
                self._update_card_selection(all_vps[i])
        elif ctrl:
            all_sel = all(vp in self.selected_items for vp in dir_vps)
            for vp in dir_vps:
                if all_sel:
                    self.selected_items.discard(vp)
                else:
                    self.selected_items.add(vp)
                self._update_card_selection(vp)
            self._last_anchor_path = dir_vps[0]
        else:
            all_sel = all(vp in self.selected_items for vp in dir_vps)
            if all_sel:
                for vp in dir_vps:
                    self.selected_items.discard(vp)
                    self._update_card_selection(vp)
                self._last_anchor_path = None
            else:
                old = self.selected_items.copy()
                self.selected_items = set(dir_vps)
                for op in old:
                    if op not in self.selected_items:
                        self._update_card_selection(op)
                for vp in dir_vps:
                    self._update_card_selection(vp)
                self._last_anchor_path = dir_vps[0]

        self._update_selection_label()

    def _on_card_enter(self, event, vp):
        self._hovered_card_path = vp
        card = self.card_widgets.get(vp)
        if not card or not card.winfo_exists():
            return
        is_sel  = vp in self.selected_items
        is_excl = vp in self.excluded_items
        t = self._tok()

        # Elevate border on every hover (accent highlight)
        if not is_sel:
            card.configure(highlightbackground=t['accent'],
                           highlightthickness=2 if not is_excl else 2)

        # Tint info area when unselected and unexcluded
        if not is_sel and not is_excl:
            card.configure(bg=t['card_hover'])
            for child in card.winfo_children():
                if getattr(child, '_is_info', False):
                    child.configure(bg=t['card_hover'])
                    for lbl in child.winfo_children():
                        try:
                            lbl.configure(bg=t['card_hover'])
                        except tk.TclError:
                            pass
                elif not getattr(child, '_is_thumb', False):
                    try:
                        child.configure(bg=t['card_hover'])
                    except tk.TclError:
                        pass

        # Reveal action strip at bottom of thumbnail
        for child in card.winfo_children():
            if getattr(child, '_is_thumb', False):
                for sub in child.winfo_children():
                    if getattr(sub, '_is_action_strip', False):
                        sub.place(relx=0.0, rely=1.0, anchor='sw', relwidth=1.0)
                        sub.lift()
                break

    def _on_card_leave(self, event, vp):
        self._hovered_card_path = None
        if self.video_preview_manager:
            self.video_preview_manager.tooltip.hide_preview()
        card = self.card_widgets.get(vp)
        if not card or not card.winfo_exists():
            return
        is_sel  = vp in self.selected_items
        is_excl = vp in self.excluded_items
        t = self._tok()

        # Restore border
        if is_sel:
            card.configure(highlightbackground=t['accent'], highlightthickness=3)
        elif is_excl:
            card.configure(highlightbackground=t['excluded'], highlightthickness=2)
        else:
            card.configure(highlightbackground=t['border'], highlightthickness=1,
                           bg=t['surface'])
            for child in card.winfo_children():
                if getattr(child, '_is_info', False):
                    child.configure(bg=t['surface'])
                    for lbl in child.winfo_children():
                        try:
                            lbl.configure(bg=t['surface'])
                        except tk.TclError:
                            pass
                elif not getattr(child, '_is_thumb', False):
                    try:
                        child.configure(bg=t['border'])
                    except tk.TclError:
                        pass

        # Conceal action strip
        for child in card.winfo_children():
            if getattr(child, '_is_thumb', False):
                for sub in child.winfo_children():
                    if getattr(sub, '_is_action_strip', False):
                        sub.place_forget()
                break

    def _on_card_right_click(self, event, vp):
        # Original right‑click logic (unchanged)
        if vp not in self.selected_items and self.video_preview_manager:
            vp_norm = os.path.normpath(vp)
            self.video_preview_manager.right_clicked_item = (
                list(self.card_widgets.keys()).index(vp) if vp in self.card_widgets else None)
            if vp_norm in self.video_preview_manager._thumbnails:
                th = self.video_preview_manager._thumbnails[vp_norm]
                if th.is_valid() and th.thumbnail_data:
                    self.video_preview_manager.tooltip.show_preview(
                        vp, th.thumbnail_data, event.x_root, event.y_root)
                    return
            with self.video_preview_manager._lock:
                already = vp_norm in self.video_preview_manager._generation_queue
            if not already:
                self.video_preview_manager._generate_thumbnail_async(
                    vp_norm, event.x_root, event.y_root)
            return
        self._last_right_clicked_path = vp
        self._show_context_menu(event, vp)

    # ─────────────────────────────────────────────────────────────────────────
    # Context menu (original full version)
    # ─────────────────────────────────────────────────────────────────────────

    def _show_context_menu(self, event, vp):
        context_menu = self.theme_provider.create_manager_context_menu(self.grid_window)

        if not self.selected_items:
            return

        # Play
        if vp in self.selected_items:
            context_menu.add_command(
                label=f"Play Selected ({len(self.selected_items)} items)",
                command=self._play_selected
            )
        else:
            context_menu.add_command(
                label="Play This Video",
                command=lambda: self._play_single(vp)
            )

        context_menu.add_separator()

        # Exclude / Include
        selected_excluded = [vp for vp in self.selected_items if vp in self.excluded_items]
        selected_not_excluded = [vp for vp in self.selected_items if vp not in self.excluded_items]

        if selected_not_excluded:
            label = (
                f"Exclude Selected ({len(selected_not_excluded)} items)"
                if len(selected_not_excluded) > 1
                else "Exclude This Video"
            )
            context_menu.add_command(label=label, command=self._exclude_selected)

        if selected_excluded:
            label = (
                f"Remove Exclusion ({len(selected_excluded)} items)"
                if len(selected_excluded) > 1
                else "Remove Exclusion"
            )
            context_menu.add_command(label=label, command=self._remove_exclusion_selected)

        context_menu.add_separator()
        context_menu.add_command(label="Select All", command=self._select_all)
        context_menu.add_command(label="Clear Selection", command=self._clear_selection)
        context_menu.add_separator()

        # Add to Playlist / Queue
        context_menu.add_command(label="Add to Playlist", command=self._context_add_to_playlist)
        context_menu.add_command(label="Add to Queue", command=self._context_add_to_queue)

        # Favourites
        if self.is_favourite_callback and (self.add_to_favourites_callback or self.remove_from_favourites_callback):
            sel_list = list(self.selected_items)
            all_fav = sel_list and all(self.is_favourite_callback(v) for v in sel_list)
            if all_fav and self.remove_from_favourites_callback:
                context_menu.add_command(label="Remove from Favourites",
                                         command=self._context_remove_from_favourites)
            elif self.add_to_favourites_callback:
                context_menu.add_command(label="Add to Favourites",
                                         command=self._context_add_to_favourites)

        context_menu.add_separator()

        # Dual player options (Win 1)
        context_menu.add_command(label="▶ Win 1 › Player 1",
                                 command=lambda: self._context_play_in_dual_player(slot=1))
        context_menu.add_command(label="▶ Win 1 › Player 2",
                                 command=lambda: self._context_play_in_dual_player(slot=2))
        context_menu.add_command(label="▶ Win 1 › Player 3",
                                 command=lambda: self._context_play_in_dual_player(slot=3))

        # Win 2 (only if callbacks are set)
        if any([self.play_in_dual_player_win2_1_callback,
                self.play_in_dual_player_win2_2_callback,
                self.play_in_dual_player_win2_3_callback]):
            context_menu.add_separator()
            if self.play_in_dual_player_win2_1_callback:
                context_menu.add_command(label="▶ Win 2 › Player 1",
                                         command=lambda: self._context_play_in_dual_player_win2(slot=1))
            if self.play_in_dual_player_win2_2_callback:
                context_menu.add_command(label="▶ Win 2 › Player 2",
                                         command=lambda: self._context_play_in_dual_player_win2(slot=2))
            if self.play_in_dual_player_win2_3_callback:
                context_menu.add_command(label="▶ Win 2 › Player 3",
                                         command=lambda: self._context_play_in_dual_player_win2(slot=3))

        context_menu.add_separator()

        single = vp if len(self.selected_items) == 1 else None
        if single and os.path.isfile(single):
            context_menu.add_command(label="Open File Location",
                                     command=lambda: self._context_open_file_location(single))
            context_menu.add_command(label="Properties",
                                     command=lambda: self._context_show_properties(single))
            if self.locate_in_panel_callback:
                context_menu.add_command(label="Show in Panel",
                                         command=lambda: self.locate_in_panel_callback(single))

        try:
            context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            context_menu.grab_release()

    # ─────────────────────────────────────────────────────────────────────────
    # Context actions (original)
    # ─────────────────────────────────────────────────────────────────────────

    def _context_add_to_playlist(self):
        vs = self._get_selected_videos()
        if vs and self.add_to_playlist_callback:
            self.add_to_playlist_callback(vs)

    def _context_add_to_favourites(self):
        vs = self._get_selected_videos()
        if vs and self.add_to_favourites_callback:
            self.add_to_favourites_callback(vs)
            for vp in vs:
                self.root.after(0, lambda p=vp: self._refresh_card_meta(p))

    def _context_remove_from_favourites(self):
        vs = [it['path'] for it in self.items
              if it['type'] == 'video' and it['path'] in self.selected_items]
        if vs and self.remove_from_favourites_callback:
            self.remove_from_favourites_callback(vs)
            for vp in vs:
                self.root.after(0, lambda p=vp: self._refresh_card_meta(p))

    def _context_add_to_queue(self):
        vs = self._get_selected_videos()
        if vs and self.add_to_queue_callback:
            self.add_to_queue_callback(vs)

    def _auto_select_card(self, vp):
        """Select vp exclusively if it isn't already part of the current selection."""
        if vp in self.selected_items:
            return
        old = self.selected_items.copy()
        self.selected_items = {vp}
        for op in old:
            self._update_card_selection(op)
        self._update_card_selection(vp)
        self._update_selection_label()

    def _add_single_to_queue(self, vp):
        self._auto_select_card(vp)
        vs = self._get_selected_videos()
        if self.add_to_queue_callback:
            self.add_to_queue_callback(vs)

    def _add_single_to_playlist(self, vp):
        self._auto_select_card(vp)
        vs = self._get_selected_videos()
        if self.add_to_playlist_callback:
            self.add_to_playlist_callback(vs)

    def _toggle_favourite_single(self, vp):
        self._auto_select_card(vp)
        vs = self._get_selected_videos()
        if not self.is_favourite_callback:
            return
        all_fav = all(self.is_favourite_callback(v) for v in vs)
        if all_fav and self.remove_from_favourites_callback:
            self.remove_from_favourites_callback(vs)
        elif not all_fav and self.add_to_favourites_callback:
            self.add_to_favourites_callback(vs)
        for v in vs:
            self.root.after(0, lambda p=v: self._refresh_card_meta(p))

    def _context_play_in_dual_player(self, slot):
        vs = self._get_selected_videos()
        if not vs:
            return
        cbs = {1: self.play_in_dual_player1_callback,
               2: self.play_in_dual_player2_callback,
               3: self.play_in_dual_player3_callback}
        cb = cbs.get(slot)
        if cb:
            cb(vs)

    def _context_play_in_dual_player_win2(self, slot):
        vs = self._get_selected_videos()
        if not vs:
            return
        cbs = {1: self.play_in_dual_player_win2_1_callback,
               2: self.play_in_dual_player_win2_2_callback,
               3: self.play_in_dual_player_win2_3_callback}
        cb = cbs.get(slot)
        if cb:
            cb(vs)

    def _context_open_file_location(self, fp):
        fp = os.path.normpath(fp)
        if self.open_file_location_callback:
            self.open_file_location_callback(fp)
            return
        try:
            import subprocess, sys as _sys
            if os.name == 'nt':
                subprocess.Popen(f'explorer /select,"{fp}"')
            elif _sys.platform == 'darwin':
                subprocess.Popen(['open', '-R', fp])
            else:
                subprocess.Popen(['xdg-open', os.path.dirname(fp)])
        except Exception as e:
            if self.console_callback:
                self.console_callback(f"Error opening file location: {e}")

    def _context_show_properties(self, fp):
        if self.show_properties_callback:
            self.show_properties_callback(fp)
            return
        try:
            from datetime import datetime as _dt
            si = os.stat(fp)
            info = (f"File: {os.path.basename(fp)}\n\n"
                    f"Path: {fp}\n\n"
                    f"Size: {si.st_size / (1024*1024):.2f} MB ({si.st_size:,} bytes)\n\n"
                    f"Modified: {_dt.fromtimestamp(si.st_mtime):%Y-%m-%d %H:%M:%S}\n\n")
            try:
                import cv2
                cap = cv2.VideoCapture(fp)
                if cap.isOpened():
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    fc  = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    dur = fc / fps if fps > 0 else 0
                    w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    info += (f"Duration: {int(dur//60)}:{int(dur%60):02d}\n"
                             f"Resolution: {w}×{h}\nFPS: {fps:.2f}\n")
                    cap.release()
            except Exception:
                pass
            import tkinter.messagebox as _mb
            _mb.showinfo("Properties", info)
        except Exception as e:
            if self.console_callback:
                self.console_callback(f"Error showing properties: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Exclude / include (original)
    # ─────────────────────────────────────────────────────────────────────────

    def _exclude_selected(self):
        for vp in list(self.selected_items):
            self.excluded_items.add(vp)
            self._update_card_selection(vp)
            if self.exclude_video_callback:
                self.exclude_video_callback(vp)

    def _remove_exclusion_selected(self):
        for vp in list(self.selected_items):
            self.excluded_items.discard(vp)
            self._update_card_selection(vp)
            if self.remove_exclusion_video_callback:
                self.remove_exclusion_video_callback(vp)

    def get_excluded_items(self):
        return set(self.excluded_items)

    def set_excluded_items(self, excluded_set):
        self.excluded_items = set(excluded_set)
        for vp in list(self.card_widgets.keys()):
            self._update_card_selection(vp)

    # ─────────────────────────────────────────────────────────────────────────
    # Filter (original)
    # ─────────────────────────────────────────────────────────────────────────
    def _on_search_changed(self):
        """Debounce the search filter to avoid rapid rebuilds."""
        if self._search_timer:
            self.root.after_cancel(self._search_timer)
        self._search_timer = self.root.after(400, self._filter_directories)

    def _filter_directories(self):
        self._page = 0
        self._pages_cache = None
        term = self.search_var.get().lower()

        if not hasattr(self, 'all_items'):
            self.all_items = self.items.copy()

        if not term:
            self.items = self.all_items.copy()
        else:
            self.items = []
            current_dir_items = []
            current_header = None
            for item_data in self.all_items:
                if item_data['type'] == 'header':
                    if current_header and current_dir_items:
                        self.items.append(current_header)
                        self.items.extend(current_dir_items)
                    current_header = item_data.copy()
                    current_dir_items = []
                    if term in item_data['name'].lower():
                        current_header['matches'] = True
                elif item_data['type'] == 'video':
                    if (current_header and current_header.get('matches')) or \
                            term in os.path.basename(item_data['path']).lower():
                        current_dir_items.append(item_data)
            if current_header and current_dir_items:
                self.items.append(current_header)
                self.items.extend(current_dir_items)

        if self._active_tag_filters:
            self._apply_tag_filter()
        else:
            self.root.after(0, self._rebuild_grid)

    # ─────────────────────────────────────────────────────────────────────────
    # Drag & drop – directory reorder (original)
    # ─────────────────────────────────────────────────────────────────────────

    def _get_dir_order(self):
        seen = []
        for it in self.items:
            if it['type'] == 'header' and it['path'] not in seen:
                seen.append(it['path'])
        return seen

    def _reorder_items_by_dir(self, new_order):
        by_dir = {}
        for it in self.items:
            if it['type'] == 'header':
                by_dir.setdefault(it['path'], {'header': it, 'videos': []})
                by_dir[it['path']]['header'] = it
            else:
                d = os.path.dirname(it['path'])
                by_dir.setdefault(d, {'header': None, 'videos': []})
                by_dir[d]['videos'].append(it)
        self.items = []
        for d in new_order:
            if d in by_dir:
                self.items.append(by_dir[d]['header'])
                self.items.extend(by_dir[d]['videos'])
        self._pages_cache = None
        if not self.search_var.get():
            self.all_items = self.items.copy()

    def _on_dir_header_press(self, event, dir_path, header_frame):
        self._drag_source = {'type': 'dir', 'dir_path': dir_path, 'widget': header_frame}
        self._drag_type = 'dir'
        label = os.path.basename(dir_path) or dir_path
        self._create_drag_ghost(f"📁 {label}", event.x_root, event.y_root)
        try:
            self.drag_mode_label.config(text="Dragging folder…")
        except Exception:
            pass

    def _on_dir_header_motion(self, event, dir_path):
        self._move_drag_ghost(event.x_root, event.y_root)

    def _on_dir_header_release(self, event, src_dir):
        self._cancel_drag_ghost()
        if self._drag_over_widget:
            self._highlight_drop_target(self._drag_over_widget, active=False)
            self._drag_over_widget = None
        tgt = self._find_dir_at_root_coords(event.x_root, event.y_root)
        if tgt and tgt != src_dir:
            self._move_dir_before(src_dir, tgt)
            self.root.after(0, self._relayout_grid)
        self._drag_source = self._drag_type = None
        try:
            self.drag_mode_label.config(text="")
        except Exception:
            pass

    def _find_dir_at_root_coords(self, x, y):
        for it in self.items:
            if it['type'] != 'header':
                continue
            w = it.get('_header_widget')
            if w is None:
                continue
            try:
                wx, wy = w.winfo_rootx(), w.winfo_rooty()
                if wx <= x <= wx + w.winfo_width() and wy <= y <= wy + w.winfo_height():
                    return it['path']
            except Exception:
                continue
        return None

    def _move_dir_before(self, src, tgt):
        order = self._get_dir_order()
        if src not in order or tgt not in order:
            return
        order.remove(src)
        order.insert(order.index(tgt), src)
        self._reorder_items_by_dir(order)

    # ─────────────────────────────────────────────────────────────────────────
    # Drag & drop – card reorder (original)
    # ─────────────────────────────────────────────────────────────────────────

    def _on_card_press(self, event, vp, card_widget):
        ctrl_held = bool(event.state & 0x4)
        shift_held = bool(event.state & 0x1)
        if ctrl_held or shift_held:
            return

        # Only videos in the same folder as the card being dragged can be moved together
        same_dir = os.path.dirname(vp)
        selected_in_dir = [
            sp for sp in self.selected_items
            if os.path.dirname(sp) == same_dir and sp not in self.excluded_items
        ]

        if len(selected_in_dir) > 1 and vp in selected_in_dir:
            # Multi‑drag
            self._drag_type = 'video_multiple'
            count = len(selected_in_dir)
            label = f"▶  {count} video{'s' if count > 1 else ''}"
            self._drag_source = {
                'type': 'video_multiple',
                'paths': selected_in_dir,
                'widget': card_widget
            }
        else:
            # Single drag (original behaviour)
            self._drag_type = 'video'
            label = os.path.basename(vp)
            if len(label) > 30:
                label = label[:27] + "…"
            label = f"▶  {label}"
            self._drag_source = {
                'type': 'video',
                'video_path': vp,
                'widget': card_widget
            }

        self._create_drag_ghost(label, event.x_root, event.y_root)
        try:
            self.drag_mode_label.config(text="Dragging video…")
        except Exception:
            pass

    def _on_card_motion(self, event, vp):
        if self._drag_type != 'video':
            return
        self._move_drag_ghost(event.x_root, event.y_root)
        tgt = self._find_card_at_root_coords(event.x_root, event.y_root)
        if tgt and tgt != vp:
            card = self.card_widgets.get(tgt)
            if card != self._drag_over_widget:
                if self._drag_over_widget:
                    self._highlight_drop_target(self._drag_over_widget, active=False)
                self._drag_over_widget = card
                self._highlight_drop_target(card, active=True)
        else:
            if self._drag_over_widget:
                self._highlight_drop_target(self._drag_over_widget, active=False)
                self._drag_over_widget = None

    def _on_card_release(self, event, src_vp):
        self._cancel_drag_ghost()
        if self._drag_over_widget:
            self._highlight_drop_target(self._drag_over_widget, active=False)
            self._drag_over_widget = None

        if self._drag_type not in ('video', 'video_multiple'):
            self._cancel_drag()
            return

        drag_source = self._drag_source
        self._drag_source = None
        self._drag_type = None
        try:
            self.drag_mode_label.config(text="")
        except Exception:
            pass

        target_vp = self._find_card_at_root_coords(event.x_root, event.y_root)
        if not target_vp:
            return

        if drag_source['type'] == 'video_multiple':
            # Ensure target is not one of the dragged videos and is in the same folder
            if target_vp in drag_source['paths']:
                return
            dragged_dir = os.path.dirname(drag_source['paths'][0])
            target_dir = os.path.dirname(target_vp)
            if dragged_dir != target_dir:
                return  # can only reorder within one folder

            self._move_multiple_videos_before(drag_source['paths'], target_vp)
            self.root.after(0, self._relayout_grid)

        else:  # single video
            if target_vp == drag_source['video_path']:
                return
            src_dir = os.path.dirname(drag_source['video_path'])
            tgt_dir = os.path.dirname(target_vp)
            if src_dir == tgt_dir:
                self._move_video_before(drag_source['video_path'], target_vp)
                self.root.after(0, self._relayout_grid)

    def _move_multiple_videos_before(self, paths, target):
        indexed = []
        for p in paths:
            idx = next((i for i, it in enumerate(self.items)
                        if it['type'] == 'video' and it['path'] == p), None)
            if idx is not None:
                indexed.append((idx, self.items[idx]))
        if not indexed:
            return

        indexed.sort(key=lambda x: x[0])

        moved_items = []
        for idx, item in reversed(indexed):
            moved_items.append(item)
            del self.items[idx]
        moved_items.reverse()

        target_idx = next((i for i, it in enumerate(self.items)
                           if it['type'] == 'video' and it['path'] == target), None)
        if target_idx is None:
            self.items.extend(moved_items)
        else:
            for item in moved_items:
                self.items.insert(target_idx, item)
                target_idx += 1

        self._pages_cache = None
        if not self.search_var.get():
            self.all_items = self.items.copy()

    def _find_card_at_root_coords(self, x, y):
        for vp, card in self.card_widgets.items():
            try:
                wx, wy = card.winfo_rootx(), card.winfo_rooty()
                if wx <= x <= wx + card.winfo_width() and wy <= y <= wy + card.winfo_height():
                    return vp
            except Exception:
                continue
        return None

    def _move_video_before(self, src, tgt):
        si = next((i for i, it in enumerate(self.items)
                   if it['type'] == 'video' and it['path'] == src), None)
        if si is None:
            return
        item = self.items.pop(si)
        ti = next((i for i, it in enumerate(self.items)
                   if it['type'] == 'video' and it['path'] == tgt), None)
        if ti is None:
            self.items.append(item)
        else:
            self.items.insert(ti, item)
        self._pages_cache = None
        if not self.search_var.get():
            self.all_items = self.items.copy()

    # ─────────────────────────────────────────────────────────────────────────
    # Drag ghost (original)
    # ─────────────────────────────────────────────────────────────────────────

    def _create_drag_ghost(self, text, x, y):
        self._cancel_drag_ghost()
        t = self._tok()
        ghost = tk.Toplevel(self.root)
        ghost.overrideredirect(True)
        ghost.attributes('-topmost', True)
        try:
            ghost.attributes('-alpha', 0.82)
        except Exception:
            pass
        tk.Label(
            ghost, text=text,
            font=("Segoe UI", 9, "bold"),
            bg=t['accent'], fg="#ffffff",
            padx=12, pady=5
        ).pack()
        ghost.geometry(f"+{x + 16}+{y + 16}")
        self._drag_ghost = ghost

    def _move_drag_ghost(self, x, y):
        if self._drag_ghost:
            try:
                self._drag_ghost.geometry(f"+{x + 16}+{y + 16}")
            except Exception:
                pass

    def _cancel_drag_ghost(self):
        if self._drag_ghost:
            try:
                self._drag_ghost.destroy()
            except Exception:
                pass
            self._drag_ghost = None

    def _cancel_drag(self):
        self._cancel_drag_ghost()
        if self._drag_over_widget:
            self._highlight_drop_target(self._drag_over_widget, active=False)
            self._drag_over_widget = None
        self._drag_source = self._drag_type = None
        try:
            if self.drag_mode_label.winfo_exists():
                self.drag_mode_label.config(text="")
        except Exception:
            pass

    def _highlight_drop_target(self, widget, active=True):
        if widget is None:
            return
        t = self._tok()
        try:
            widget.configure(
                highlightbackground=t['accent'] if active else t['border'],
                highlightthickness=2 if active else 1
            )
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Hover preview (original)
    # ─────────────────────────────────────────────────────────────────────────

    def _on_hover_enter(self, event, idx):
        if not self.video_preview_manager:
            return
        item = self.items[idx]
        vp = item.video_path
        if not os.path.isfile(vp):
            return
        vp_norm = os.path.normpath(vp)
        if vp_norm in self.video_preview_manager._thumbnails:
            th = self.video_preview_manager._thumbnails[vp_norm]
            if th.is_valid() and th.thumbnail_data:
                self.video_preview_manager.tooltip.show_preview(
                    vp, th.thumbnail_data, event.x_root, event.y_root)

    def _on_hover_leave(self, event):
        if self.video_preview_manager:
            self.video_preview_manager.tooltip.hide_preview()

    # ─────────────────────────────────────────────────────────────────────────
    # Thumbnail loading (original three-level cache)
    # ─────────────────────────────────────────────────────────────────────────

    def _load_thumbnail(self, item, label, video_path_norm=None):
        """Load thumbnail — 3-level cache: LRU RAM → blob file → generate."""
        try:
            with self.loading_lock:
                if not self.is_loading:
                    return
            if video_path_norm is None:
                video_path_norm = os.path.normpath(item.video_path)

            vpm = self.video_preview_manager
            if vpm and hasattr(vpm, 'lru_cache'):
                photo = vpm.lru_cache.get(video_path_norm)
                if photo is not None:
                    self._photo_cache[video_path_norm] = photo
                    self.root.after(0, lambda lbl=label, p=photo: self._set_thumbnail(lbl, p))
                    return

            if vpm:
                th = vpm._thumbnails.get(video_path_norm)
                if th and th.is_valid() and hasattr(th, 'blob_path') and th.blob_path and th.blob_path.exists():
                    photo = self._photo_from_blob(th.blob_path, getattr(th, 'is_video', False), item)
                    if photo:
                        if hasattr(vpm, 'lru_cache'):
                            vpm.lru_cache.put(video_path_norm, photo)
                        self._photo_cache[video_path_norm] = photo
                        self.root.after(0, lambda lbl=label, p=photo: self._set_thumbnail(lbl, p))
                        return
                    if th.thumbnail_data:
                        self._display_thumbnail_from_data(label, th.thumbnail_data, item, video_path_norm)
                        return

                result = vpm.generator.generate_thumbnail(video_path_norm)
                if result:
                    raw_bytes, is_vid = result
                    try:
                        from managers.video_preview_manager import VideoThumbnail, _file_hash_key
                        ext = ".mp4" if is_vid else ".jpg"
                        hk = _file_hash_key(item.video_path)
                        blob_path = vpm.storage.write_blob(hk, raw_bytes, ext)
                        th_new = VideoThumbnail(item.video_path, blob_path, is_vid, hk)
                        vpm._thumbnails[video_path_norm] = th_new
                        vpm._save_thumbnails()
                        photo = self._photo_from_blob(blob_path, is_vid, item)
                        if photo:
                            if hasattr(vpm, 'lru_cache'):
                                vpm.lru_cache.put(video_path_norm, photo)
                            self._photo_cache[video_path_norm] = photo
                            self.root.after(0, lambda lbl=label, p=photo: self._set_thumbnail(lbl, p))
                            return
                    except Exception:
                        pass
                    import base64
                    prefix = "VIDEO:" if is_vid else "IMAGE:"
                    td = prefix + base64.b64encode(raw_bytes).decode("ascii")
                    self._display_thumbnail_from_data(label, td, item, video_path_norm)
                    return

            self.root.after(0, lambda lbl=label: lbl.winfo_exists() and lbl.configure(text="No Preview"))
        except Exception:
            self.root.after(0, lambda: label.winfo_exists() and label.configure(text="Error"))

    def _photo_from_blob(self, blob_path, is_video, item):
        """Decode a raw JPEG or MP4 blob file directly — no base64 at all."""
        import shutil, tempfile as _tf
        tmp_path = None
        try:
            if is_video:
                fd, tmp_path = _tf.mkstemp(suffix=".mp4")
                os.close(fd)
                shutil.copy2(str(blob_path), tmp_path)
                import cv2 as _cv2
                cap = _cv2.VideoCapture(tmp_path)
                ret, frame = cap.read()
                cap.release()
                try: os.unlink(tmp_path)
                except OSError: pass
                tmp_path = None
                if not ret or frame is None:
                    return None
                frame_resized = _cv2.resize(frame, (240, 135))
                frame_rgb = _cv2.cvtColor(frame_resized, _cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(frame_rgb)
            else:
                pil_image = Image.open(str(blob_path))
                pil_image.thumbnail((240, 135), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(pil_image)
            item.thumbnail_image = photo
            return photo
        except Exception:
            if tmp_path:
                try: os.unlink(tmp_path)
                except OSError: pass
            return None

    def _display_thumbnail_from_data(self, label, thumbnail_data, item, video_path_norm=None):
        """Decode a base64 sentinel string ("IMAGE:…" / "VIDEO:…") into a PhotoImage."""
        import tempfile, base64 as _b64
        tmp_path = None
        try:
            is_vid = thumbnail_data.startswith("VIDEO:")
            raw_b64 = thumbnail_data[6:]

            if is_vid:
                video_data = _b64.b64decode(raw_b64)
                with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tf:
                    tf.write(video_data)
                    tmp_path = tf.name
                import cv2 as _cv2
                cap = _cv2.VideoCapture(tmp_path)
                ret, frame = cap.read()
                cap.release()
                try: os.unlink(tmp_path)
                except OSError: pass
                tmp_path = None
                if ret and frame is not None:
                    fr = _cv2.resize(frame, (240, 135))
                    fr_rgb = _cv2.cvtColor(fr, _cv2.COLOR_BGR2RGB)
                    pil_image = Image.fromarray(fr_rgb)
                    photo = ImageTk.PhotoImage(pil_image)
                    item.thumbnail_image = photo
                    if video_path_norm:
                        self._photo_cache[video_path_norm] = photo
                    self.root.after(0, lambda: self._set_thumbnail(label, photo))
                    return
            else:
                image_data = _b64.b64decode(raw_b64)
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tf:
                    tf.write(image_data)
                    tmp_path = tf.name
                img = Image.open(tmp_path)
                img.thumbnail((240, 135), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                item.thumbnail_image = photo
                if video_path_norm:
                    self._photo_cache[video_path_norm] = photo
                try: os.unlink(tmp_path)
                except OSError: pass
                tmp_path = None
                self.root.after(0, lambda: self._set_thumbnail(label, photo))
                return

        except Exception:
            if tmp_path:
                try: os.unlink(tmp_path)
                except OSError: pass
            self.root.after(0, lambda: label.winfo_exists() and label.configure(text="Error"))

    def _set_thumbnail(self, label, photo):
        try:
            if label.winfo_exists():
                label.configure(image=photo, text="")
                label.image = photo
        except:
            pass

    def _relayout_grid(self):
        if getattr(self, '_closing', False):
            return
        try:
            if not self.grid_frame or not self.grid_frame.winfo_exists():
                return
        except Exception:
            return
        t = self._tok()
        cols = self.grid_size_var.get()

        old_page = self._page
        self._pages_cache = None
        new_page_items = self._get_page_items()

        if self._page != old_page or not new_page_items:
            return self._rebuild_grid()

        grid_row = -1
        video_col = 0

        for item_data in new_page_items:
            if item_data['type'] == 'header':
                grid_row += 1
                video_col = 0
                header_widget = item_data.get('_header_widget')
                if header_widget and header_widget.winfo_exists():
                    header_widget.grid(
                        row=grid_row, column=0, columnspan=cols,
                        sticky='ew', padx=_CARD_PAD_X, pady=(28, 8)
                    )
                else:
                    return self._rebuild_grid()
                grid_row += 1
                continue

            vp = item_data['path']
            card = self.card_widgets.get(vp)
            if card and card.winfo_exists():
                card.grid(
                    row=grid_row, column=video_col,
                    padx=_CARD_PAD_X, pady=_CARD_PAD_Y, sticky='nsew'
                )
            else:
                return self._rebuild_grid()

            video_col += 1
            if video_col >= cols:
                video_col = 0
                grid_row += 1

        self._update_selection_label()