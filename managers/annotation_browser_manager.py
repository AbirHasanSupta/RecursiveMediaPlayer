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


class AnnotationBrowserManager:
    """
    Tags & Ratings browser window.
    Mirrors PlaylistUI conventions: uses theme_provider colors, create_button,
    header band, card layout, and respects dark/light mode.
    """

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
        self._bookmark_frame: Optional[tk.Frame] = None
        self._count_lbl: Optional[tk.Label] = None

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

    # ── Window ────────────────────────────────────────────────────────────────

    def _build_window(self):
        tp = self.tp
        ACCENT = "#4A9EFF" if tp.dark_mode else "#2d89ef"
        GOLD   = "#f5c518" if tp.dark_mode else "#c8a000"
        PANEL  = tp.listbox_bg
        SIDE   = tp.badge_bg

        win = tk.Toplevel(self.root)
        win.withdraw()
        win.title("Tags & Ratings")
        win.geometry(_responsive_geometry(self.root, 1040, 660))
        win.configure(bg=tp.bg_color)
        win.minsize(760, 500)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        apply_icon(win)
        self._win = win

        # ── Header band ───────────────────────────────────────────────────────
        band = tk.Frame(win, bg=GOLD)
        band.pack(fill=tk.X)
        band_row = tk.Frame(band, bg=GOLD)
        band_row.pack(fill=tk.X, padx=20, pady=14)
        tk.Label(band_row, text="🏷  Tags & Ratings",
                 font=tp.header_font, bg=GOLD, fg="white").pack(side=tk.LEFT)
        if self.play_callback:
            tp.create_button(band_row, "▶  Play All Filtered",
                             self._play_all, "success", "md").pack(side=tk.RIGHT)
            tp.create_button(band_row, "▶  Play Selected",
                             self._play_selected, "success", "md").pack(side=tk.RIGHT, padx=(0, 8))

        # ── Filter strip below band ───────────────────────────────────────────
        filter_bar = tk.Frame(win, bg=tp.badge_bg)
        filter_bar.pack(fill=tk.X)
        tk.Frame(win, bg=tp.frame_border, height=1).pack(fill=tk.X)

        fb_inner = tk.Frame(filter_bar, bg=tp.badge_bg)
        fb_inner.pack(fill=tk.X, padx=16, pady=8)

        # Search
        tk.Label(fb_inner, text="Search tags:",
                 font=tp.small_font, bg=tp.badge_bg, fg=tp.muted_fg).pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._on_search_change())
        search_e = tk.Entry(fb_inner, textvariable=self._search_var,
                            font=tp.normal_font, bg=tp.entry_bg, fg=tp.entry_fg,
                            insertbackground=tp.entry_fg, relief=tk.FLAT,
                            highlightthickness=1, highlightbackground=tp.entry_border,
                            width=16)
        search_e.pack(side=tk.LEFT, padx=(6, 20), ipady=4)

        # Min rating
        tk.Label(fb_inner, text="Min rating:",
                 font=tp.small_font, bg=tp.badge_bg, fg=tp.muted_fg).pack(side=tk.LEFT)
        self._rating_var = tk.IntVar(value=0)
        star_fg  = GOLD
        star_bg  = tp.badge_bg

        for i in range(6):
            lbl_text = "Any" if i == 0 else "★" * i
            fg = tp.muted_fg if i == 0 else star_fg
            rb = tk.Radiobutton(
                fb_inner, text=lbl_text, variable=self._rating_var, value=i,
                command=self._apply_filter,
                font=tp.small_font, bg=star_bg, fg=fg,
                selectcolor=tp.entry_bg, activebackground=star_bg,
                activeforeground=tp.text_color, bd=0, padx=6, cursor="hand2",
                indicatoron=False, relief=tk.FLAT,
                highlightthickness=0,
            )
            rb.pack(side=tk.LEFT, padx=1)
            rb.bind("<Enter>", lambda e, b=rb: b.config(bg=tp.listbox_bg))
            rb.bind("<Leave>", lambda e, b=rb: b.config(bg=star_bg))

        # Divider + buttons
        tk.Frame(fb_inner, bg=tp.divider_color, width=1).pack(side=tk.LEFT, fill=tk.Y, pady=2, padx=12)

        tp.create_button(fb_inner, "✕ Clear filters", self._clear_filters, "secondary", "sm"
                         ).pack(side=tk.LEFT, padx=(0, 6))
        tp.create_button(fb_inner, "⟳ Refresh", self.refresh, "secondary", "sm"
                         ).pack(side=tk.LEFT)

        # ── Two-column body ───────────────────────────────────────────────────
        cols = tk.Frame(win, bg=tp.bg_color)
        cols.pack(fill=tk.BOTH, expand=True, padx=20, pady=14)

        # ── LEFT sidebar — tag list ───────────────────────────────────────────
        left_card = tk.Frame(cols, bg=SIDE, width=230,
                             highlightbackground=tp.frame_border, highlightthickness=1)
        left_card.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 12))
        left_card.pack_propagate(False)

        tk.Label(left_card, text="  TAGS", font=tp.small_font,
                 bg=SIDE, fg=tp.muted_fg, pady=8, anchor="w"
                 ).pack(fill=tk.X, padx=(4, 0))
        tk.Frame(left_card, bg=tp.frame_border, height=1).pack(fill=tk.X)

        tag_scroll = tk.Frame(left_card, bg=PANEL)
        tag_scroll.pack(fill=tk.BOTH, expand=True)

        tag_sb = tk.Scrollbar(tag_scroll, width=10, relief=tk.FLAT, bd=0)
        tag_sb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 1), pady=1)

        self._tag_canvas = tk.Canvas(tag_scroll, bg=PANEL, highlightthickness=0,
                                     yscrollcommand=tag_sb.set)
        self._tag_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tag_sb.config(command=self._tag_canvas.yview)

        self._tag_frame_inner = tk.Frame(self._tag_canvas, bg=PANEL)
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

        # ── RIGHT content card ────────────────────────────────────────────────
        right_area = tk.Frame(cols, bg=tp.bg_color)
        right_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # count bar above list
        info_row = tk.Frame(right_area, bg=tp.bg_color)
        info_row.pack(fill=tk.X, pady=(0, 8))
        self._count_lbl = tk.Label(info_row, text="Videos: 0",
                                   font=tp.small_font, bg=tp.bg_color, fg=tp.muted_fg)
        self._count_lbl.pack(side=tk.LEFT, anchor="w")
        self._active_filter_lbl = tk.Label(info_row, text="",
                                           font=tp.small_font, bg=tp.bg_color, fg=GOLD)
        self._active_filter_lbl.pack(side=tk.LEFT, padx=(10, 0))

        # video list card
        right_card = tk.Frame(right_area, bg=PANEL,
                              highlightbackground=tp.frame_border, highlightthickness=1)
        right_card.pack(fill=tk.BOTH, expand=True)

        vid_hdr = tk.Frame(right_card, bg=tp.badge_bg)
        vid_hdr.pack(fill=tk.X)
        tk.Label(vid_hdr, text="  VIDEOS  —  double-click to play",
                 font=tp.small_font, bg=tp.badge_bg, fg=tp.muted_fg,
                 pady=6, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        tk.Frame(right_card, bg=tp.frame_border, height=1).pack(fill=tk.X)

        vid_body = tk.Frame(right_card, bg=PANEL)
        vid_body.pack(fill=tk.BOTH, expand=True)

        vid_sb = tk.Scrollbar(vid_body, width=10, relief=tk.FLAT, bd=0)
        vid_sb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 1), pady=1)

        self._video_listbox = tk.Listbox(
            vid_body, yscrollcommand=vid_sb.set,
            font=tp.normal_font,
            bg=PANEL, fg=tp.listbox_fg,
            selectbackground=ACCENT, selectforeground="white",
            selectmode=tk.EXTENDED,
            activestyle="none", relief=tk.FLAT, bd=0, highlightthickness=0)
        self._video_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
        vid_sb.config(command=self._video_listbox.yview)
        self._video_listbox.bind("<<ListboxSelect>>", self._on_video_select)
        self._video_listbox.bind("<Double-Button-1>", lambda e: self._play_selected())
        self._video_listbox.bind("<Button-3>", self._on_video_right_click)

        # ── Detail / bookmark strip ───────────────────────────────────────────
        tk.Frame(win, bg=tp.frame_border, height=1).pack(fill=tk.X, side=tk.BOTTOM)
        detail = tk.Frame(win, bg=tp.badge_bg)
        detail.pack(fill=tk.X, side=tk.BOTTOM)

        self._detail_lbl = tk.Label(detail, text="Select a video to see details",
                                    font=tp.small_font, bg=tp.badge_bg, fg=tp.muted_fg,
                                    anchor="w", justify=tk.LEFT, wraplength=800)
        self._detail_lbl.pack(anchor="w", padx=14, pady=(8, 2))

        self._bookmark_frame = tk.Frame(detail, bg=tp.badge_bg)
        self._bookmark_frame.pack(fill=tk.X, padx=10, pady=(0, 8))

        # ── Bottom action bar ─────────────────────────────────────────────────
        action = tk.Frame(win, bg=tp.bg_color)
        action.pack(fill=tk.X, padx=20, pady=(0, 14))
        tp.create_button(action, "Close", win.destroy, "secondary", "md").pack(side=tk.RIGHT)

        self._rebuild_tags()
        self._apply_filter()
        win.deiconify()

    # ── Tag panel ─────────────────────────────────────────────────────────────

    def _rebuild_tags(self):
        if not self._tag_frame_inner:
            return
        tp = self.tp
        ACCENT = "#4A9EFF" if tp.dark_mode else "#2d89ef"
        GOLD   = "#f5c518" if tp.dark_mode else "#c8a000"
        PANEL  = tp.listbox_bg

        for w in self._tag_frame_inner.winfo_children():
            w.destroy()
        self._tag_btns.clear()

        query = (self._search_var.get().strip().lower()) if self._search_var else ""
        all_tags = self.svc.get_all_tags()

        # "All videos" row
        is_all = not self._selected_tags
        all_btn = tk.Button(
            self._tag_frame_inner,
            text="⊞  All videos",
            command=lambda: self._toggle_tag(None),
            font=tp.small_font,
            bg=ACCENT if is_all else PANEL,
            fg="white" if is_all else tp.listbox_fg,
            relief=tk.FLAT, bd=0, padx=10, pady=5,
            anchor="w", cursor="hand2",
            activebackground=ACCENT, activeforeground="white",
        )
        all_btn.pack(fill=tk.X, padx=4, pady=(4, 6))
        self._tag_btns["__ALL__"] = all_btn

        tk.Frame(self._tag_frame_inner, bg=tp.divider_color, height=1
                 ).pack(fill=tk.X, padx=4, pady=(0, 4))

        for tag in all_tags:
            if query and query not in tag:
                continue
            count = len(self.svc.get_videos_with_tag(tag))
            is_sel = tag in self._selected_tags
            row = tk.Frame(self._tag_frame_inner, bg=PANEL)
            row.pack(fill=tk.X, padx=4, pady=1)

            dot_color = GOLD if is_sel else tp.muted_fg
            tk.Label(row, text="●", font=("Segoe UI", 7),
                     bg=PANEL, fg=dot_color).pack(side=tk.LEFT, padx=(6, 0))

            btn = tk.Button(
                row,
                text=f"{tag}",
                command=lambda t=tag: self._toggle_tag(t),
                font=tp.small_font,
                bg=PANEL,
                fg=GOLD if is_sel else tp.listbox_fg,
                relief=tk.FLAT, bd=0, padx=6, pady=4,
                anchor="w", cursor="hand2",
                activebackground=tp.badge_bg, activeforeground=tp.text_color,
            )
            btn.pack(side=tk.LEFT, fill=tk.X, expand=True)

            tk.Label(row, text=str(count), font=("Segoe UI", 8),
                     bg=PANEL, fg=tp.muted_fg,
                     padx=6).pack(side=tk.RIGHT)

            if is_sel:
                row.config(bg=tp.badge_bg)
                btn.config(bg=tp.badge_bg)
                for child in row.winfo_children():
                    if isinstance(child, tk.Label):
                        child.config(bg=tp.badge_bg)

            self._tag_btns[tag] = btn

        if not all_tags:
            tk.Label(self._tag_frame_inner, text="No tags yet.\n\nAdd tags via\n🏷 in the player.",
                     font=tp.small_font, bg=PANEL, fg=tp.muted_fg,
                     justify=tk.CENTER).pack(padx=10, pady=20)

    def _toggle_tag(self, tag):
        if tag is None:
            self._selected_tags.clear()
        elif tag in self._selected_tags:
            self._selected_tags.discard(tag)
        else:
            self._selected_tags.add(tag)
        self._rebuild_tags()
        self._apply_filter()

    # ── Filter ────────────────────────────────────────────────────────────────

    def _apply_filter(self):
        if not self._video_listbox:
            return
        tp = self.tp
        GOLD = "#f5c518" if tp.dark_mode else "#c8a000"

        min_rating = self._rating_var.get() if self._rating_var else 0
        all_annotated = list(self.svc._data.keys())

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
            stars   = ("★" * rating + "☆" * (5 - rating)) if rating else "☆☆☆☆☆"
            bm_str  = f"  🔖{bm_cnt}" if bm_cnt else ""
            tag_str = ("  [" + ", ".join(tags[:3]) + ("+…" if len(tags) > 3 else "") + "]") if tags else ""
            name    = os.path.basename(path)
            self._video_listbox.insert(tk.END, f"{stars}{bm_str}  {name}{tag_str}")

        self._count_lbl.config(text=f"Videos: {len(candidates)}")

        # Active filter summary
        parts = []
        if self._selected_tags:
            parts.append("Tags: " + ", ".join(sorted(self._selected_tags)))
        if min_rating:
            parts.append(f"Min ★: {'★' * min_rating}")
        self._active_filter_lbl.config(
            text=("  ·  " + "  |  ".join(parts)) if parts else "")

        self._clear_detail()

    def _on_search_change(self):
        self._rebuild_tags()

    def _clear_filters(self):
        self._selected_tags.clear()
        self._rating_var.set(0)
        if self._search_var:
            self._search_var.set("")
        self._rebuild_tags()
        self._apply_filter()

    # ── Detail panel ──────────────────────────────────────────────────────────

    def _on_video_select(self, event=None):
        sel = self._video_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self._filtered_videos):
            self._show_detail(self._filtered_videos[idx])

    def _show_detail(self, path: str):
        tp = self.tp
        GOLD = "#f5c518" if tp.dark_mode else "#c8a000"

        for w in self._bookmark_frame.winfo_children():
            w.destroy()

        rating    = self.svc.get_rating(path)
        tags      = self.svc.get_tags(path)
        bookmarks = self.svc.get_bookmarks(path)
        stars     = "★" * rating + "☆" * (5 - rating)
        tag_str   = ", ".join(tags) if tags else "—"

        self._detail_lbl.config(
            text=f"{os.path.basename(path)}    Rating: {stars}    Tags: {tag_str}    Bookmarks: {len(bookmarks)}    {path}",
            fg=tp.text_color)

        if bookmarks:
            tk.Label(self._bookmark_frame, text="Bookmarks:",
                     font=("Segoe UI", 8, "bold"), bg=tp.badge_bg, fg=tp.muted_fg
                     ).pack(side=tk.LEFT, padx=(2, 8))
            for bm in bookmarks[:12]:
                lbl = bm.get("label", _fmt_ms(bm["ms"]))
                pill = tk.Label(self._bookmark_frame, text=f"🔖 {lbl}",
                                font=("Segoe UI", 8),
                                bg=tp.listbox_bg, fg=tp.accent_color,
                                padx=8, pady=2, cursor="hand2",
                                relief=tk.FLAT,
                                highlightbackground=tp.frame_border, highlightthickness=1)
                pill.pack(side=tk.LEFT, padx=2)

    def _clear_detail(self):
        if self._detail_lbl:
            self._detail_lbl.config(text="Select a video to see details", fg=self.tp.muted_fg)
        if self._bookmark_frame:
            for w in self._bookmark_frame.winfo_children():
                w.destroy()

    # ── Right-click context menu ──────────────────────────────────────────────

    def _on_video_right_click(self, event):
        if not self._win:
            return
        tp = self.tp
        sel = self._video_listbox.curselection()
        if not sel:
            idx = self._video_listbox.nearest(event.y)
            if idx >= 0:
                self._video_listbox.selection_set(idx)
                sel = (idx,)
        if not sel:
            return

        menu = tk.Menu(self._win, tearoff=0,
                       bg="#313335" if tp.dark_mode else "#f5f5f5",
                       fg="#A9B7C6" if tp.dark_mode else "#333333",
                       activebackground="#2D5A8E" if tp.dark_mode else "#3498db",
                       activeforeground="#FFFFFF",
                       relief="flat", bd=1, font=tp.small_font)

        n = len(sel)
        menu.add_command(
            label=f"▶  Play selected ({n} video{'s' if n > 1 else ''})",
            command=self._play_selected)
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