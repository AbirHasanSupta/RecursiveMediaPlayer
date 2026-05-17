import os
import threading
import tkinter as tk
from tkinter import font as tkfont
from typing import Optional, Callable

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

def _p(dark_mode):
    if dark_mode:
        return {
            "accent":      "#4A9EFF",
            "gold":        "#f5c518",
            "gold_dim":    "#b8920f",
            "panel":       "#1e1f22",
            "sidebar":     "#27282c",
            "header_bg":   "#1a1b1e",
            "tag_sel_bg":  "#1c3557",
            "tag_sel_fg":  "#4A9EFF",
            "tag_norm_fg": "#8b9ab0",
            "tag_hover":   "#2a2b30",
            "item_hover":  "#2a2b30",
            "item_alt":    "#252628",
            "pill_bg":     "#1c3557",
            "pill_fg":     "#4A9EFF",
            "star_on":     "#f5c518",
            "star_off":    "#3a3b3f",
            "rb_sel":      "#1c3557",
            "rb_sel_fg":   "#4A9EFF",
            "rb_nor":      "#27282c",
            "rb_nor_fg":   "#6b7a8a",
            "sep":         "#2d2e33",
            "count_bg":    "#1c3557",
            "count_fg":    "#4A9EFF",
            "bm_bg":       "#1c2e48",
            "bm_fg":       "#4A9EFF",
            "bm_border":   "#1c3557",
            "detail_bg":   "#1e1f22",
            "status_bg":   "#16171a",
            "search_bg":   "#2a2b30",
            "search_hl":   "#4A9EFF",
        }
    return {
        "accent":      "#2d89ef",
        "gold":        "#c8a000",
        "gold_dim":    "#8a6d0a",
        "panel":       "#ffffff",
        "sidebar":     "#f4f5f7",
        "header_bg":   "#ebedf0",
        "tag_sel_bg":  "#dceeff",
        "tag_sel_fg":  "#1a6dc8",
        "tag_norm_fg": "#555e6e",
        "tag_hover":   "#ebedf0",
        "item_hover":  "#f0f6ff",
        "item_alt":    "#f9f9fb",
        "pill_bg":     "#dceeff",
        "pill_fg":     "#1a6dc8",
        "star_on":     "#c8a000",
        "star_off":    "#d0d5de",
        "rb_sel":      "#dceeff",
        "rb_sel_fg":   "#1a6dc8",
        "rb_nor":      "#ebedf0",
        "rb_nor_fg":   "#888",
        "sep":         "#e0e2e8",
        "count_bg":    "#dceeff",
        "count_fg":    "#1a6dc8",
        "bm_bg":       "#e8f3ff",
        "bm_fg":       "#1a6dc8",
        "bm_border":   "#b8d4f5",
        "detail_bg":   "#f4f5f7",
        "status_bg":   "#ebedf0",
        "search_bg":   "#ffffff",
        "search_hl":   "#2d89ef",
    }


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
        self._tag_frame_inner: Optional[tk.Frame] = None
        self._tag_canvas: Optional[tk.Canvas] = None
        self._tag_canvas_win = None
        self._tag_btns: dict = {}
        self._filtered_videos: list = []
        self._detail_lbl: Optional[tk.Label] = None
        self._detail_path_lbl: Optional[tk.Label] = None
        self._bookmark_frame: Optional[tk.Frame] = None
        self._count_lbl: Optional[tk.Label] = None
        self._active_filter_lbl: Optional[tk.Label] = None
        self._rb_btns: list = []
        self._dragging_index = None
        self.video_preview_manager = None
        self.grid_view_manager = None

        theme_provider.register_manager_ui(self)

    # ── Public ────────────────────────────────────────────────────────────────

    def show(self):
        if self._win and self._win.winfo_exists():
            self._win.lift()
            self._win.focus_force()
            return
        self._build_window()

    def refresh(self):
        if self._win and self._win.winfo_exists():
            self._rebuild_tags()
            self._apply_filter()

    def set_video_preview_manager(self, preview_manager):
        self.video_preview_manager = preview_manager

    def set_grid_view_manager(self, grid_view_manager):
        self.grid_view_manager = grid_view_manager

    # ── Window ────────────────────────────────────────────────────────────────

    def _build_window(self):
        tp = self.tp
        P = _p(tp.dark_mode)

        win = tk.Toplevel(self.root)
        win.withdraw()
        win.title("Tags & Ratings")
        win.geometry(_responsive_geometry(self.root, 1100, 700))
        win.configure(bg=P["panel"])
        win.minsize(820, 520)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        apply_icon(win)
        self._win = win

        # ── Header ────────────────────────────────────────────────────────────
        header = tk.Frame(win, bg=P["header_bg"], height=58)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        h_inner = tk.Frame(header, bg=P["header_bg"])
        h_inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=0)

        # Icon + title
        title_box = tk.Frame(h_inner, bg=P["header_bg"])
        title_box.pack(side=tk.LEFT, fill=tk.Y)

        icon_lbl = tk.Label(title_box, text="🏷", font=("Segoe UI Emoji", 18),
                            bg=P["header_bg"], fg=P["gold"])
        icon_lbl.pack(side=tk.LEFT, padx=(0, 10), pady=14)

        tk.Label(title_box, text="Tags & Ratings",
                 font=("Segoe UI Semibold", 15) if tp.dark_mode else ("Segoe UI", 15, "bold"),
                 bg=P["header_bg"], fg=tp.text_color).pack(side=tk.LEFT, pady=14)

        # Header actions
        if self.play_callback:
            btn_frame = tk.Frame(h_inner, bg=P["header_bg"])
            btn_frame.pack(side=tk.RIGHT, fill=tk.Y, pady=10)
            self._play_btn = self._make_header_btn(btn_frame, "▶  Play Filtered", self._play_smart,
                                                   P["gold"], "#1a1a1a")
            self._play_btn.pack(side=tk.RIGHT)
            self._play_btn_P = P

        # Header bottom border
        tk.Frame(win, bg=P["sep"], height=1).pack(fill=tk.X)

        # ── Filter bar ────────────────────────────────────────────────────────
        fbar = tk.Frame(win, bg=P["sidebar"])
        fbar.pack(fill=tk.X)

        fb = tk.Frame(fbar, bg=P["sidebar"])
        fb.pack(fill=tk.X, padx=18, pady=10)

        # Search box
        search_wrap = tk.Frame(fb, bg=P["sidebar"])
        search_wrap.pack(side=tk.LEFT, padx=(0, 20))

        tk.Label(search_wrap, text="SEARCH TAGS", font=("Segoe UI", 7, "bold"),
                 bg=P["sidebar"], fg=tp.muted_fg).pack(anchor="w")

        search_entry_frame = tk.Frame(search_wrap, bg=P["search_bg"],
                                      highlightbackground=P["sep"],
                                      highlightthickness=1)
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

        # Min rating
        rating_wrap = tk.Frame(fb, bg=P["sidebar"])
        rating_wrap.pack(side=tk.LEFT, padx=(0, 20))

        tk.Label(rating_wrap, text="MIN RATING", font=("Segoe UI", 7, "bold"),
                 bg=P["sidebar"], fg=tp.muted_fg).pack(anchor="w")

        rb_row = tk.Frame(rating_wrap, bg=P["sidebar"])
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
            rb.bind("<Enter>", lambda e, b=rb: b.config(bg=P["tag_hover"]))
            rb.bind("<Leave>", lambda e, b=rb, v=i:
                    b.config(bg=P["rb_sel"] if self._rating_var.get() == v else P["rb_nor"]))
            self._rb_btns.append(rb)

        self._update_rb_visuals(P)

        # Divider
        tk.Frame(fb, bg=P["sep"], width=1).pack(side=tk.LEFT, fill=tk.Y, padx=14, pady=2)

        # Action buttons
        action_wrap = tk.Frame(fb, bg=P["sidebar"])
        action_wrap.pack(side=tk.LEFT)
        tk.Label(action_wrap, text=" ", font=("Segoe UI", 7),
                 bg=P["sidebar"]).pack(anchor="w")
        btn_wrap = tk.Frame(action_wrap, bg=P["sidebar"])
        btn_wrap.pack()
        self._make_flat_btn(btn_wrap, "✕  Clear", self._clear_filters, P).pack(side=tk.LEFT, padx=(0, 6))
        self._make_flat_btn(btn_wrap, "⟳  Refresh", self.refresh, P).pack(side=tk.LEFT)

        # Active filter label
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
        body.pack(fill=tk.BOTH, expand=True)

        # ── LEFT sidebar ──────────────────────────────────────────────────────
        sidebar = tk.Frame(body, bg=P["sidebar"], width=220)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        sid_hdr = tk.Frame(sidebar, bg=P["sidebar"])
        sid_hdr.pack(fill=tk.X, padx=14, pady=(14, 4))
        tk.Label(sid_hdr, text="TAGS", font=("Segoe UI", 7, "bold"),
                 bg=P["sidebar"], fg=tp.muted_fg).pack(side=tk.LEFT)
        self._tag_count_lbl = tk.Label(sid_hdr, text="",
                                       font=("Segoe UI", 7),
                                       bg=P["sidebar"], fg=tp.muted_fg)
        self._tag_count_lbl.pack(side=tk.RIGHT)

        tk.Frame(sidebar, bg=P["sep"], height=1).pack(fill=tk.X, padx=10)

        tag_scroll_area = tk.Frame(sidebar, bg=P["sidebar"])
        tag_scroll_area.pack(fill=tk.BOTH, expand=True)

        tag_sb = tk.Scrollbar(tag_scroll_area, width=6, relief=tk.FLAT, bd=0,
                              troughcolor=P["sidebar"], bg=P["sep"])
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

        # sidebar separator
        tk.Frame(body, bg=P["sep"], width=1).pack(side=tk.LEFT, fill=tk.Y)

        # ── RIGHT content ──────────────────────────────────────────────────────
        right = tk.Frame(body, bg=P["panel"])
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Count + filter info row
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

        # Double-click hint
        tk.Label(info_bar, text="drag to reorder  •  double-click to play",
                 font=("Segoe UI", 8), bg=P["panel"], fg=tp.muted_fg).pack(side=tk.RIGHT)

        # Video list
        list_outer = tk.Frame(right, bg=P["panel"],
                              highlightbackground=P["sep"], highlightthickness=1)
        list_outer.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 12))

        vid_hdr = tk.Frame(list_outer, bg=P["sidebar"])
        vid_hdr.pack(fill=tk.X)
        tk.Label(vid_hdr, text="  VIDEOS", font=("Segoe UI", 7, "bold"),
                 bg=P["sidebar"], fg=tp.muted_fg, pady=7, anchor="w"
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        tk.Frame(list_outer, bg=P["sep"], height=1).pack(fill=tk.X)

        vid_body = tk.Frame(list_outer, bg=P["panel"])
        vid_body.pack(fill=tk.BOTH, expand=True)

        vid_sb = tk.Scrollbar(vid_body, width=6, relief=tk.FLAT, bd=0,
                              troughcolor=P["panel"], bg=P["sep"])
        vid_sb.pack(side=tk.RIGHT, fill=tk.Y, pady=4)

        list_font = ("Segoe UI", 10) if tk.font.Font(font=tp.normal_font).actual()["size"] < 11 \
            else tp.normal_font

        self._video_listbox = tk.Listbox(
            vid_body, yscrollcommand=vid_sb.set,
            font=list_font,
            bg=P["panel"], fg=tp.listbox_fg,
            selectbackground=P["accent"], selectforeground="white",
            selectmode=tk.EXTENDED,
            activestyle="none", relief=tk.FLAT, bd=0, highlightthickness=0,
            selectborderwidth=0,
        )
        self._video_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        vid_sb.config(command=self._video_listbox.yview)
        self._video_listbox.bind("<<ListboxSelect>>", self._on_video_select)
        self._video_listbox.bind("<Double-Button-1>", lambda e: self._play_selected())
        self._video_listbox.bind("<Button-1>", self._on_mouse_down)
        self._video_listbox.bind("<Button-3>", self._on_video_right_click)
        self._video_listbox.bind("<B1-Motion>", self._on_mouse_drag)
        self._video_listbox.bind("<ButtonRelease-1>", self._on_mouse_release)
        self._video_listbox.bind("<Motion>", self._on_list_hover)
        self._hovered_idx = -1

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

        tp.create_button(act_inner, "Close", win.destroy, "secondary", "md").pack(side=tk.RIGHT)

        self._rebuild_tags()
        self._apply_filter()
        win.deiconify()

    # ── Helper widget builders ─────────────────────────────────────────────────

    def _make_header_btn(self, parent, text, cmd, bg, fg):
        btn = tk.Button(parent, text=text, command=cmd,
                        font=("Segoe UI", 9, "bold"),
                        bg=bg, fg=fg, relief=tk.FLAT, bd=0,
                        padx=14, pady=6, cursor="hand2",
                        activebackground=bg, activeforeground=fg)
        btn.bind("<Enter>", lambda e: btn.config(bg=self._lighten(bg)))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg))
        return btn

    def _make_flat_btn(self, parent, text, cmd, P):
        btn = tk.Button(parent, text=text, command=cmd,
                        font=("Segoe UI", 9),
                        bg=P["rb_nor"], fg=self.tp.text_color,
                        relief=tk.FLAT, bd=0,
                        padx=10, pady=5, cursor="hand2",
                        activebackground=P["tag_hover"],
                        activeforeground=self.tp.text_color,
                        highlightbackground=P["sep"], highlightthickness=1)
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

    # ── Tag panel ─────────────────────────────────────────────────────────────

    def _rebuild_tags(self):
        if not self._tag_frame_inner:
            return
        tp = self.tp
        P = _p(tp.dark_mode)

        for w in self._tag_frame_inner.winfo_children():
            w.destroy()
        self._tag_btns.clear()

        query = (self._search_var.get().strip().lower()) if self._search_var else ""
        all_tags = self.svc.get_all_tags()
        visible_tags = [t for t in all_tags if not query or query in t.lower()]

        if hasattr(self, '_tag_count_lbl') and self._tag_count_lbl:
            self._tag_count_lbl.config(text=f"{len(visible_tags)}")

        # "All" entry
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
            count = len(self.svc.get_videos_with_tag(tag))
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
        P = _p(tp.dark_mode)
        count = len(self.svc.get_videos_with_tag(tag))
        menu = tk.Menu(self._win, tearoff=0,
                       bg="#27282c" if tp.dark_mode else "#f4f5f7",
                       fg=tp.text_color,
                       activebackground="#1c3557" if tp.dark_mode else "#dceeff",
                       activeforeground="#4A9EFF" if tp.dark_mode else "#1a6dc8",
                       relief="flat", bd=0, font=("Segoe UI", 9))
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
            self.svc._schedule_save()
        self._selected_tags.discard(tag)
        self._rebuild_tags()
        self._apply_filter()

    def _rename_tag(self, old_tag):
        tp = self.tp
        P = _p(tp.dark_mode)
        dlg = tk.Toplevel(self._win)
        dlg.withdraw()
        dlg.title("Rename Tag")
        dlg.configure(bg=tp.bg_color)
        dlg.resizable(False, False)
        dlg.transient(self._win)
        dlg.grab_set()

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
                self.svc._schedule_save()
            if old_tag in self._selected_tags:
                self._selected_tags.discard(old_tag)
                self._selected_tags.add(new_tag)
            dlg.destroy()
            self._rebuild_tags()
            self._apply_filter()

        tp.create_button(btns, "Rename", do_rename, "primary", "md").pack(side=tk.RIGHT, padx=(8, 0))
        tp.create_button(btns, "Cancel", dlg.destroy, "secondary", "md").pack(side=tk.RIGHT)

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
        self._rebuild_tags()
        self._apply_filter()

    # ── Rating clicks ─────────────────────────────────────────────────────────

    def _on_rating_click(self, val):
        self._rating_var.set(val)
        P = _p(self.tp.dark_mode)
        self._update_rb_visuals(P)
        self._apply_filter()

    def _update_rb_visuals(self, P):
        cur = self._rating_var.get()
        for rb in self._rb_btns:
            sel = rb._val == cur
            rb.config(
                bg=P["rb_sel"] if sel else P["rb_nor"],
                fg=P["rb_sel_fg"] if sel else (self.tp.muted_fg if rb._val == 0 else P["star_on"]),
                highlightbackground=P["search_hl"] if sel else P["sep"]
            )

    # ── Hover highlight for listbox ───────────────────────────────────────────

    def _on_list_hover(self, event):
        idx = self._video_listbox.nearest(event.y)
        if idx == self._hovered_idx:
            return
        self._hovered_idx = idx

    # ── Filter ────────────────────────────────────────────────────────────────

    def _apply_filter(self):
        if not self._video_listbox:
            return
        tp = self.tp
        P = _p(tp.dark_mode)

        min_rating = self._rating_var.get() if self._rating_var else 0
        all_annotated = [
            k for k, v in self.svc._data.items()
            if v.rating > 0 or v.tags or v.bookmarks
        ]

        if self._selected_tags:
            candidates = [p for p in all_annotated
                          if self._selected_tags.issubset(set(self.svc.get_tags(p)))]
        else:
            candidates = all_annotated

        if min_rating > 0:
            candidates = [p for p in candidates if self.svc.get_rating(p) >= min_rating]

        self._filtered_videos = candidates
        self._video_listbox.delete(0, tk.END)

        for path in candidates:
            rating  = self.svc.get_rating(path)
            tags    = self.svc.get_tags(path)
            bm_cnt  = len(self.svc.get_bookmarks(path))
            stars   = "★" * rating if rating else "☆"
            bm_str  = f"  🔖 {bm_cnt}" if bm_cnt else ""
            tag_str = ("  · " + "  ".join(tags[:3]) + (" +…" if len(tags) > 3 else "")) if tags else ""
            name    = os.path.basename(path)
            self._video_listbox.insert(tk.END, f"  {stars}{bm_str}    {name}{tag_str}")

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
            self.video_preview_manager.attach_to_listbox(self._video_listbox, video_mapping)

        self._update_play_btn()
        self._clear_detail()

    def _on_search_change(self):
        self._rebuild_tags()

    def _clear_filters(self):
        self._selected_tags.clear()
        self._rating_var.set(0)
        P = _p(self.tp.dark_mode)
        self._update_rb_visuals(P)
        if self._search_var:
            self._search_var.set("")
        self._rebuild_tags()
        self._apply_filter()

    # ── Detail panel ──────────────────────────────────────────────────────────

    def _on_video_select(self, event=None):
        sel = self._video_listbox.curselection()
        self._update_play_btn()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self._filtered_videos):
            self._show_detail(self._filtered_videos[idx])

    def _show_detail(self, path: str):
        tp = self.tp
        P = _p(tp.dark_mode)

        for w in self._bookmark_frame.winfo_children():
            w.destroy()

        rating    = self.svc.get_rating(path)
        tags      = self.svc.get_tags(path)
        bookmarks = self.svc.get_bookmarks(path)
        stars     = ("★" * rating) if rating else ""
        tag_str   = "  ·  " + ",  ".join(tags) if tags else ""

        self._detail_stars_lbl.config(
            text=stars if stars else "☆",
            fg=P["gold"] if stars else tp.muted_fg)

        name = os.path.basename(path)
        self._detail_lbl.config(
            text=f"  {name}{tag_str}",
            fg=tp.text_color)

        self._detail_path_lbl.config(
            text=path,
            fg=tp.muted_fg)

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
        P = _p(tp.dark_mode)
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

        index = self._video_listbox.nearest(event.y)

        if index < 0 or index >= len(self._filtered_videos):
            return

        ctrl_held = bool(event.state & 0x4)
        shift_held = bool(event.state & 0x1)
        current_selection = list(self._video_listbox.curselection())

        if shift_held and current_selection:
            self._video_listbox.selection_clear(0, tk.END)
            anchor = current_selection[-1] if current_selection else 0
            start = min(anchor, index)
            end = max(anchor, index)
            for i in range(start, end + 1):
                self._video_listbox.selection_set(i)
            return "break"

        elif ctrl_held:
            if index in current_selection:
                self._video_listbox.selection_clear(index)
            else:
                self._video_listbox.selection_set(index)
            return "break"

        else:
            self._video_listbox.selection_clear(0, tk.END)
            self._video_listbox.selection_set(index)
            self._dragging_index = index
            return "break"

    def _on_mouse_drag(self, event):
        if self._dragging_index is None or not self._filtered_videos:
            return

        current_index = self._video_listbox.nearest(event.y)
        if current_index != self._dragging_index and 0 <= current_index < len(self._filtered_videos):
            self._filtered_videos[self._dragging_index], self._filtered_videos[current_index] = \
                self._filtered_videos[current_index], self._filtered_videos[self._dragging_index]

            self._video_listbox.delete(0, tk.END)
            for path in self._filtered_videos:
                rating  = self.svc.get_rating(path)
                tags    = self.svc.get_tags(path)
                bm_cnt  = len(self.svc.get_bookmarks(path))
                stars   = "★" * rating if rating else "☆"
                bm_str  = f"  🔖 {bm_cnt}" if bm_cnt else ""
                tag_str = ("  · " + "  ".join(tags[:3]) + (" +…" if len(tags) > 3 else "")) if tags else ""
                name    = os.path.basename(path)
                self._video_listbox.insert(tk.END, f"  {stars}{bm_str}    {name}{tag_str}")

            self._dragging_index = current_index
            self._video_listbox.selection_set(current_index)

    def _on_mouse_release(self, event):
        self._dragging_index = None

    def _on_video_right_click(self, event):
        if not self._win:
            return
        tp = self.tp
        P = _p(tp.dark_mode)

        listbox = self._video_listbox
        index = listbox.nearest(event.y)
        sel = list(listbox.curselection())

        if not sel and 0 <= index < len(self._filtered_videos):
            if self.video_preview_manager:
                path = self._filtered_videos[index]
                if os.path.isfile(path):
                    self.video_preview_manager.right_clicked_item = index
                    self.video_preview_manager._show_video_preview(
                        path, event.x_root, event.y_root
                    )
            return

        if not sel:
            if 0 <= index < len(self._filtered_videos):
                listbox.selection_set(index)
                sel = [index]
            else:
                return

        menu = tk.Menu(self._win, tearoff=0,
                       bg="#27282c" if tp.dark_mode else "#f4f5f7",
                       fg=tp.text_color,
                       activebackground="#1c3557" if tp.dark_mode else "#dceeff",
                       activeforeground="#4A9EFF" if tp.dark_mode else "#1a6dc8",
                       relief="flat", bd=0, font=("Segoe UI", 9))

        n = len(sel)
        menu.add_command(
            label=f"▶  Play selected ({n} video{'s' if n > 1 else ''})",
            command=self._play_selected)
        menu.add_separator()

        menu.add_command(
            label="Open in Grid View",
            command=lambda: self._open_grid_view_from_selection(sel))
        menu.add_separator()

        if n == 1:
            path = self._filtered_videos[sel[0]]
            menu.add_command(label="📋  Copy path",
                             command=lambda: self._copy_path(path))
            menu.add_command(label="📂  Open file location",
                             command=lambda: self._open_location(path))

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

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

    # ── Playback ──────────────────────────────────────────────────────────────

    def _update_play_btn(self):
        if not hasattr(self, '_play_btn') or not self._play_btn:
            return
        P = self._play_btn_P
        sel = self._video_listbox.curselection() if self._video_listbox else []
        if sel:
            self._play_btn.config(text="▶  Play Selected", bg=P["accent"], fg="white")
        else:
            self._play_btn.config(text="▶  Play Filtered", bg=P["gold"], fg="#1a1a1a")

    def _play_smart(self):
        if self._video_listbox and self._video_listbox.curselection():
            self._play_selected()
        else:
            self._play_all()

    def _play_selected(self):
        if not self.play_callback:
            return
        sel = self._video_listbox.curselection()
        if not sel:
            return
        videos = [self._filtered_videos[i] for i in sel if i < len(self._filtered_videos)]
        if videos:
            self.play_callback(videos)

    def _play_all(self):
        if self.play_callback and self._filtered_videos:
            self.play_callback(list(self._filtered_videos))