"""
unified_panel.py
────────────────
Unified right-side panel with a custom vertical icon+label tab bar on the
left side and a content stack on the right.  Replaces all separate Toplevel
windows for Browse, Playlist, Queue, Favourites, History, and Gallery.
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox

TAB_BROWSE     = 0
TAB_PLAYLIST   = 1
TAB_QUEUE      = 2
TAB_FAVOURITES = 3
TAB_HISTORY    = 4
TAB_GALLERY    = 5

_TAB_DEFS = [
    (TAB_BROWSE,     "Browse",     "📁"),
    (TAB_PLAYLIST,   "Playlist",   "🎵"),
    (TAB_QUEUE,      "Queue",      "⬛"),
    (TAB_FAVOURITES, "Favourites", "♥"),
    (TAB_HISTORY,    "History",    "🕐"),
    (TAB_GALLERY,    "Gallery",    "⊞"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Colour helpers
# ─────────────────────────────────────────────────────────────────────────────

def _tok(app):
    """Return GridViewManager design tokens (reuse them for the whole panel)."""
    return app.grid_view_manager._tok()


# ─────────────────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────────────────

class UnifiedPanel:
    """
    After all managers are constructed in build_app.py, call:

        self.unified_panel = UnifiedPanel(self)
        self.unified_panel.build()
    """

    def __init__(self, app):
        self.app            = app
        self._current_tab   = TAB_BROWSE
        self._tab_btns      = {}   # tab_index -> tk.Frame (button)
        self._tab_frames    = {}   # tab_index -> tk.Frame (content)
        self._tab_bar       = None
        self._content_host  = None

    # ──────────────────────────────────────────────────────────────────────────
    # Build
    # ──────────────────────────────────────────────────────────────────────────

    def build(self):
        app = self.app
        t   = _tok(app)
        bg  = app.bg_color

        # Tear down old exclusion_section
        app.exclusion_section.pack_forget()
        app.exclusion_section.destroy()

        # ── outer shell ───────────────────────────────────────────────────────
        shell = tk.Frame(app.content_frame, bg=bg)
        shell.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))
        app.exclusion_section = shell

        # header row (video count + dir label)
        hdr = tk.Frame(shell, bg=bg)
        hdr.pack(fill=tk.X, pady=(0, 4))
        tk.Label(hdr, text="Library", font=app.header_font,
                 bg=bg, fg=app.text_color).pack(side=tk.LEFT, anchor='w')
        app.video_count_label = tk.Label(
            hdr, text="  —  0 videos",
            font=app.normal_font, bg=bg, fg=app.muted_fg)
        app.video_count_label.pack(side=tk.LEFT)
        app.selected_dir_label = tk.Label(
            shell, text="Select a directory",
            font=app.small_font, bg=bg, fg=app.muted_fg)
        app.selected_dir_label.pack(anchor='w', pady=(0, 6))

        # ── inner panel: [tab-bar | content] ─────────────────────────────────
        inner = tk.Frame(shell, bg=bg)
        inner.pack(fill=tk.BOTH, expand=True)

        self._tab_bar = self._build_tab_bar(inner, t)
        self._tab_bar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 0))

        # thin separator line
        tk.Frame(inner, bg=t['border'], width=1).pack(side=tk.LEFT, fill=tk.Y)

        self._content_host = tk.Frame(inner, bg=bg)
        self._content_host.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # build all content frames (stacked, only one visible at a time)
        builders = {
            TAB_BROWSE:     self._build_browse_tab,
            TAB_PLAYLIST:   self._build_playlist_tab,
            TAB_QUEUE:      self._build_queue_tab,
            TAB_FAVOURITES: self._build_favourites_tab,
            TAB_HISTORY:    self._build_history_tab,
            TAB_GALLERY:    self._build_gallery_tab,
        }
        for idx, _, _ in _TAB_DEFS:
            f = tk.Frame(self._content_host, bg=bg)
            self._tab_frames[idx] = f
            builders[idx](f)

        self._patch_pill_buttons()
        self._patch_managers()
        self.switch_to(TAB_BROWSE)

    # ──────────────────────────────────────────────────────────────────────────
    # Custom vertical tab bar
    # ──────────────────────────────────────────────────────────────────────────

    def _build_tab_bar(self, parent, t):
        dark   = self.app.dark_mode
        bar_bg = t['surface'] if not dark else "#1a1d22"

        bar = tk.Frame(parent, bg=bar_bg, width=72)
        bar.pack_propagate(False)

        # top spacer
        tk.Frame(bar, bg=bar_bg, height=6).pack(fill=tk.X)

        for idx, label, icon in _TAB_DEFS:
            btn_frame = tk.Frame(bar, bg=bar_bg, cursor="hand2")
            btn_frame.pack(fill=tk.X, pady=1)

            # left accent bar (hidden by default)
            accent_bar = tk.Frame(btn_frame, width=3, bg=bar_bg)
            accent_bar.pack(side=tk.LEFT, fill=tk.Y)

            inner = tk.Frame(btn_frame, bg=bar_bg, padx=0, pady=8)
            inner.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            icon_lbl = tk.Label(inner, text=icon, font=("Segoe UI Emoji", 14),
                                bg=bar_bg, fg=t['text_muted'])
            icon_lbl.pack()

            txt_lbl = tk.Label(inner, text=label, font=("Segoe UI", 7),
                               bg=bar_bg, fg=t['text_muted'])
            txt_lbl.pack()

            # store references
            btn_frame._tab_idx   = idx
            btn_frame._accent    = accent_bar
            btn_frame._icon_lbl  = icon_lbl
            btn_frame._txt_lbl   = txt_lbl
            btn_frame._bar_bg    = bar_bg
            self._tab_btns[idx]  = btn_frame

            def _bind(bf=btn_frame, i=idx):
                def _enter(e):
                    if self._current_tab != i:
                        bf.configure(bg=t['surface2'])
                        bf._icon_lbl.configure(bg=t['surface2'])
                        bf._txt_lbl.configure(bg=t['surface2'])
                        bf._accent.configure(bg=t['surface2'])
                def _leave(e):
                    if self._current_tab != i:
                        bf.configure(bg=bf._bar_bg)
                        bf._icon_lbl.configure(bg=bf._bar_bg)
                        bf._txt_lbl.configure(bg=bf._bar_bg)
                        bf._accent.configure(bg=bf._bar_bg)
                def _click(e):
                    self.switch_to(i)

                for w in (bf, bf._icon_lbl, bf._txt_lbl, bf._accent, inner):
                    w.bind("<Enter>",   _enter)
                    w.bind("<Leave>",   _leave)
                    w.bind("<Button-1>", _click)

            _bind()

        # bottom spacer
        tk.Frame(bar, bg=bar_bg).pack(fill=tk.BOTH, expand=True)
        return bar

    def _refresh_tab_bar(self):
        t    = _tok(self.app)
        dark = self.app.dark_mode
        bar_bg  = t['surface'] if not dark else "#1a1d22"
        sel_bg  = self.app.accent_color
        sel_fg  = "#ffffff"
        idle_fg = t['text_muted']

        for idx, btn_frame in self._tab_btns.items():
            active = (idx == self._current_tab)
            if active:
                btn_frame.configure(bg=t['surface2'] if not dark else "#252830")
                btn_frame._icon_lbl.configure(
                    bg=t['surface2'] if not dark else "#252830", fg=sel_bg)
                btn_frame._txt_lbl.configure(
                    bg=t['surface2'] if not dark else "#252830",
                    fg=sel_bg, font=("Segoe UI", 7, "bold"))
                btn_frame._accent.configure(bg=sel_bg)
            else:
                btn_frame.configure(bg=bar_bg)
                btn_frame._icon_lbl.configure(bg=bar_bg, fg=idle_fg)
                btn_frame._txt_lbl.configure(
                    bg=bar_bg, fg=idle_fg, font=("Segoe UI", 7))
                btn_frame._accent.configure(bg=bar_bg)

    # ──────────────────────────────────────────────────────────────────────────
    # Switch tab
    # ──────────────────────────────────────────────────────────────────────────

    def switch_to(self, tab_index):
        for f in self._tab_frames.values():
            f.pack_forget()
        self._tab_frames[tab_index].pack(fill=tk.BOTH, expand=True)
        self._current_tab = tab_index
        self._refresh_tab_bar()

        # auto-refresh on switch
        if tab_index == TAB_QUEUE:
            self._q_refresh()
        elif tab_index == TAB_FAVOURITES:
            d = self.app.get_current_selected_directory()
            if d:
                self._fav_load_for_dir(d)
        elif tab_index == TAB_HISTORY:
            self._hist_refresh()
        elif tab_index == TAB_PLAYLIST:
            self._pl_refresh()

    # ──────────────────────────────────────────────────────────────────────────
    # Shared widget builders
    # ──────────────────────────────────────────────────────────────────────────

    def _section_header(self, parent, text, accent_color):
        """Coloured band header used in every tab."""
        hdr = tk.Frame(parent, bg=accent_color)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text=text, font=self.app.header_font,
                 bg=accent_color, fg="white", pady=10
                 ).pack(side=tk.LEFT, padx=14)
        return hdr

    def _card(self, parent, bg=None):
        app = self.app
        bg  = bg or app.listbox_bg
        c   = tk.Frame(parent, bg=bg,
                       highlightbackground=app.frame_border,
                       highlightthickness=1)
        c.pack(fill=tk.BOTH, expand=True)
        return c

    def _col_header(self, card, text):
        app = self.app
        row = tk.Frame(card, bg=app.badge_bg)
        row.pack(fill=tk.X)
        tk.Label(row, text=f"  {text}", font=app.small_font,
                 bg=app.badge_bg, fg=app.muted_fg,
                 pady=5, anchor="w").pack(fill=tk.X, padx=4)
        tk.Frame(card, bg=app.frame_border, height=1).pack(fill=tk.X)
        return row

    def _scrolled_listbox(self, card, accent, selectmode=tk.MULTIPLE):
        app   = self.app
        PANEL = app.listbox_bg
        row   = tk.Frame(card, bg=PANEL); row.pack(fill=tk.BOTH, expand=True)
        sb    = tk.Scrollbar(row, width=8, relief=tk.FLAT, bd=0)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        lb = tk.Listbox(row, yscrollcommand=sb.set,
                        selectmode=selectmode,
                        font=app.normal_font, bg=PANEL, fg=app.listbox_fg,
                        selectbackground=accent, selectforeground="white",
                        activestyle="none", relief=tk.FLAT, bd=0,
                        highlightthickness=0)
        lb.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        sb.config(command=lb.yview)
        return lb

    def _action_bar(self, parent):
        app = self.app
        bg  = app.bg_color
        bar = tk.Frame(parent, bg=bg)
        bar.pack(fill=tk.X, pady=(5, 2))
        l = tk.Frame(bar, bg=bg); l.pack(side=tk.LEFT)
        r = tk.Frame(bar, bg=bg); r.pack(side=tk.RIGHT)
        return l, r

    # ──────────────────────────────────────────────────────────────────────────
    # Browse tab
    # ──────────────────────────────────────────────────────────────────────────

    def _build_browse_tab(self, parent):
        app = self.app
        bg  = app.bg_color

        # search bar
        sf = tk.Frame(parent, bg=bg)
        sf.pack(fill=tk.X, pady=(6, 4), padx=6)
        tk.Label(sf, text="🔍", font=("Segoe UI Emoji", 10),
                 bg=bg, fg=app.muted_fg).pack(side=tk.LEFT, padx=(0, 4))

        search_container = tk.Frame(sf, bg=app.entry_bg,
                                    highlightthickness=1,
                                    highlightbackground=app.entry_border)
        search_container.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        app.search_entry = tk.Entry(
            search_container, font=app.normal_font,
            bg=app.entry_bg, fg=app.entry_fg,
            relief=tk.FLAT, bd=0,
            insertbackground=app.entry_fg)
        app.search_entry.pack(fill=tk.X, padx=6, pady=4)
        app.search_entry.bind('<KeyRelease>', app.on_search_changed)

        app.create_button(sf, "Clear", app.clear_search,
                          "secondary", "sm").pack(side=tk.LEFT)

        # treeview container
        tree_outer = tk.Frame(parent, bg=bg,
                               highlightbackground=app.frame_border,
                               highlightthickness=1)
        tree_outer.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))

        app.exclusion_scrollbar = ttk.Scrollbar(tree_outer, orient=tk.VERTICAL)
        app.exclusion_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        app.exclusion_tree = ttk.Treeview(
            tree_outer,
            style="ExclusionTree.Treeview",
            selectmode="extended",
            show="tree headings",
            columns=("size",),
            yscrollcommand=app.exclusion_scrollbar.set,
        )
        app.exclusion_scrollbar.config(command=app.exclusion_tree.yview)
        app.exclusion_tree.column("#0",   width=380, minwidth=160, stretch=True,  anchor="w")
        app.exclusion_tree.column("size", width=80,  minwidth=50,  stretch=False, anchor="e")
        app.exclusion_tree["show"] = "tree"

        app._tree_header_frame = tk.Frame(tree_outer, bg=bg)
        app._tree_header_frame.pack(side=tk.TOP, fill=tk.X)
        app._tree_header_name_lbl = tk.Label(
            app._tree_header_frame, text="Name", anchor="w",
            font=app.small_font, bg=bg, fg=app.text_color, padx=4, pady=2)
        app._tree_header_name_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        app._tree_header_size_lbl = tk.Label(
            app._tree_header_frame, text="Size", anchor="w", width=10,
            font=app.small_font, bg=bg, fg=app.text_color, padx=4, pady=2)
        app._tree_header_size_lbl.pack(side=tk.RIGHT)

        app.exclusion_tree.pack(fill=tk.BOTH, expand=True)
        app._configure_tree_style()

        # bindings
        app._selection_anchor = None
        app.exclusion_tree.bind("<Button-1>",        app._on_left_click)
        app.exclusion_tree.bind("<Double-Button-1>", app._on_double_click)
        app.exclusion_tree.bind("<Button-3>",        app._show_context_menu)
        app.exclusion_tree.bind("<<TreeviewOpen>>",  app._on_tree_open)
        app.exclusion_tree.bind("<<TreeviewClose>>", app._on_tree_close)
        app.exclusion_tree.bind("<Control-a>",
            lambda e: (app.exclusion_tree.selection_set(app._tree_get_all_iids()), "break")[1])
        app.exclusion_tree.bind("<Control-A>",
            lambda e: (app.exclusion_tree.selection_set(app._tree_get_all_iids()), "break")[1])
        app.exclusion_tree.bind("<Delete>", app._on_key_toggle_exclusion)
        app.exclusion_tree.bind("<space>",  app._on_key_toggle_exclusion)

        # checkboxes
        chk = tk.Frame(parent, bg=bg)
        chk.pack(fill=tk.X, padx=6, pady=(2, 6))
        app.show_videos_var      = tk.BooleanVar(value=app.show_videos)
        app.excluded_only_var    = tk.BooleanVar(value=app.show_only_excluded)
        app.expand_all_var       = tk.BooleanVar(value=app.expand_all_default)
        app.save_directories_var = tk.BooleanVar(value=app.save_directories)
        for text, var, cmd in [
            ("Show Videos",  app.show_videos_var,      app.toggle_videos_visibility),
            ("Expand All",   app.expand_all_var,        app.toggle_expand_all),
            ("Excl. Only",   app.excluded_only_var,     app.toggle_excluded_only),
            ("Save Dirs",    app.save_directories_var,  app.toggle_save_directories),
        ]:
            ttk.Checkbutton(chk, text=text, style="Modern.TCheckbutton",
                            variable=var, command=cmd).pack(side=tk.LEFT, padx=(0, 8))
        app.smart_resume_var = tk.BooleanVar(value=app.smart_resume_enabled)
        app.speed_var        = tk.DoubleVar(value=1.0)

    # ──────────────────────────────────────────────────────────────────────────
    # Playlist tab
    # ──────────────────────────────────────────────────────────────────────────

    def _build_playlist_tab(self, parent):
        app    = self.app
        bg     = app.bg_color
        ACCENT = "#4A9EFF" if app.dark_mode else "#2d89ef"
        PANEL  = app.listbox_bg

        self._section_header(parent, "🎵  Playlists", ACCENT)

        body = tk.Frame(parent, bg=bg)
        body.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # two columns
        cols = tk.Frame(body, bg=bg)
        cols.pack(fill=tk.BOTH, expand=True)

        # LEFT sidebar
        left = tk.Frame(cols, bg=app.badge_bg, width=180,
                        highlightbackground=app.frame_border, highlightthickness=1)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 6))
        left.pack_propagate(False)
        tk.Label(left, text="  PLAYLISTS", font=app.small_font,
                 bg=app.badge_bg, fg=app.muted_fg, pady=6, anchor="w").pack(fill=tk.X, padx=4)
        tk.Frame(left, bg=app.frame_border, height=1).pack(fill=tk.X)

        pl_body = tk.Frame(left, bg=PANEL)
        pl_body.pack(fill=tk.BOTH, expand=True)
        pl_sb = tk.Scrollbar(pl_body, width=8, relief=tk.FLAT, bd=0)
        pl_sb.pack(side=tk.RIGHT, fill=tk.Y)
        pl_lb = tk.Listbox(pl_body, yscrollcommand=pl_sb.set,
                           font=app.normal_font, bg=PANEL, fg=app.listbox_fg,
                           selectbackground=ACCENT, selectforeground="white",
                           activestyle="none", relief=tk.FLAT, bd=0, highlightthickness=0)
        pl_lb.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        pl_sb.config(command=pl_lb.yview)

        tk.Frame(left, bg=app.frame_border, height=1).pack(fill=tk.X)
        act = tk.Frame(left, bg=app.badge_bg)
        act.pack(fill=tk.X, padx=6, pady=6)
        app.create_button(act, "+ New",  self._pl_create_new, "primary", "sm").pack(side=tk.LEFT)
        app.create_button(act, "Delete", self._pl_delete,     "danger",  "sm").pack(side=tk.RIGHT)

        # RIGHT
        right = tk.Frame(cols, bg=bg)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        info_row = tk.Frame(right, bg=bg)
        info_row.pack(fill=tk.X, pady=(0, 4))
        self._pl_info_lbl = tk.Label(info_row, text="Select a playlist",
                                     font=app.small_font, bg=bg, fg=app.muted_fg)
        self._pl_info_lbl.pack(side=tk.LEFT)

        vid_card = tk.Frame(right, bg=PANEL,
                            highlightbackground=app.frame_border, highlightthickness=1)
        vid_card.pack(fill=tk.BOTH, expand=True)
        self._col_header(vid_card, "VIDEOS — dbl-click to play")

        vid_body = tk.Frame(vid_card, bg=PANEL)
        vid_body.pack(fill=tk.BOTH, expand=True)
        vid_sb = tk.Scrollbar(vid_body, width=8, relief=tk.FLAT, bd=0)
        vid_sb.pack(side=tk.RIGHT, fill=tk.Y)
        vid_lb = tk.Listbox(vid_body, yscrollcommand=vid_sb.set, selectmode=tk.MULTIPLE,
                            font=app.normal_font, bg=PANEL, fg=app.listbox_fg,
                            selectbackground=ACCENT, selectforeground="white",
                            activestyle="none", relief=tk.FLAT, bd=0, highlightthickness=0)
        vid_lb.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        vid_sb.config(command=vid_lb.yview)

        l, r = self._action_bar(right)
        app.create_button(l, "Remove",       self._pl_remove_videos, "warning", "sm").pack(side=tk.LEFT)
        app.create_button(r, "▶ Play All",   self._pl_play_all,      "success", "sm").pack(side=tk.RIGHT, padx=(4, 0))
        app.create_button(r, "▶ Play Sel",   self._pl_play_selected, "primary", "sm").pack(side=tk.RIGHT)

        self._pl_lb            = pl_lb
        self._pl_vid_lb        = vid_lb
        self._pl_svc           = app.playlist_manager.service
        self._pl_current       = None
        self._pl_video_mapping = {}

        pl_lb.bind("<<ListboxSelect>>",  self._pl_on_select)
        vid_lb.bind("<Double-Button-1>", self._pl_on_vid_dblclick)
        vid_lb.bind("<Button-3>",        self._pl_on_vid_rclick)
        self._pl_refresh()

    def _pl_refresh(self):
        if not hasattr(self, '_pl_lb'):
            return
        self._pl_lb.delete(0, tk.END)
        for pl in self._pl_svc.get_all_playlists():
            self._pl_lb.insert(tk.END, f"  {pl.name}  ({len(pl.videos)})")

    def _pl_on_select(self, _e=None):
        sel = self._pl_lb.curselection()
        if not sel:
            return
        pls = self._pl_svc.get_all_playlists()
        if sel[0] >= len(pls):
            return
        self._pl_current = pls[sel[0]]
        self._pl_vid_lb.delete(0, tk.END)
        self._pl_video_mapping = {}
        for i, v in enumerate(self._pl_current.videos):
            self._pl_vid_lb.insert(tk.END, f"  {os.path.basename(v)}")
            self._pl_video_mapping[i] = v
        self._pl_info_lbl.config(
            text=f"{self._pl_current.name}  —  {len(self._pl_current.videos)} videos")
        if hasattr(self.app, 'video_preview_manager') and self.app.video_preview_manager:
            self.app.video_preview_manager.attach_to_listbox(
                self._pl_vid_lb, self._pl_video_mapping)

    def _pl_create_new(self):
        from managers.playlist_manager import PlaylistInfoDialog
        r = PlaylistInfoDialog(self.app.root, self.app).show()
        if r:
            name, desc = r
            self._pl_svc.create_playlist(name, desc)
            self.app.update_console(f"Playlist '{name}' created")
            self._pl_refresh()

    def _pl_delete(self):
        if not self._pl_current:
            return
        if messagebox.askyesno("Delete", f"Delete '{self._pl_current.name}'?"):
            self._pl_svc.delete_playlist(self._pl_current.id)
            self._pl_current = None
            self._pl_vid_lb.delete(0, tk.END)
            self._pl_info_lbl.config(text="Select a playlist")
            self._pl_refresh()

    def _pl_play_all(self):
        if self._pl_current and self._pl_current.videos:
            self.app._play_playlist_videos(self._pl_current.videos)

    def _pl_play_selected(self):
        sel = self._pl_vid_lb.curselection()
        if not sel or not self._pl_current:
            return
        videos = [self._pl_current.videos[i] for i in sel
                  if i < len(self._pl_current.videos) and os.path.exists(self._pl_current.videos[i])]
        if videos:
            self.app._play_playlist_videos(videos)

    def _pl_remove_videos(self):
        sel = self._pl_vid_lb.curselection()
        if not sel or not self._pl_current:
            return
        for i in reversed(sel):
            if i < len(self._pl_current.videos):
                self._pl_current.videos.pop(i)
        self._pl_svc.update_playlist(self._pl_current.id, videos=self._pl_current.videos)
        self._pl_on_select()
        self._pl_refresh()

    def _pl_on_vid_dblclick(self, _e=None):
        sel = self._pl_vid_lb.curselection()
        if not sel or not self._pl_current:
            return
        self.app._play_playlist_videos(self._pl_current.videos[sel[0]:])

    def _pl_on_vid_rclick(self, event):
        sel = self._pl_vid_lb.curselection()
        if not sel:
            return
        m = tk.Menu(self.app.root, tearoff=0)
        m.add_command(label="Play Selected", command=self._pl_play_selected)
        m.add_command(label="Remove",        command=self._pl_remove_videos)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    # ──────────────────────────────────────────────────────────────────────────
    # Queue tab
    # ──────────────────────────────────────────────────────────────────────────

    def _build_queue_tab(self, parent):
        app    = self.app
        bg     = app.bg_color
        ACCENT = "#2ecc71"
        PANEL  = app.listbox_bg

        hdr = self._section_header(parent, "⬛  Queue", ACCENT)
        self._q_info_lbl = tk.Label(hdr, text="0 videos",
                                    font=app.small_font, bg=ACCENT, fg="white")
        self._q_info_lbl.pack(side=tk.RIGHT, padx=14)

        body = tk.Frame(parent, bg=bg)
        body.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        card = self._card(body, PANEL)
        self._col_header(card, "▶=playing  ✓=played  —  dbl-click to jump")

        q_lb = self._scrolled_listbox(card, ACCENT)

        l, r = self._action_bar(body)
        app.create_button(l, "↑",          self._q_move_up,   "secondary", "sm").pack(side=tk.LEFT, padx=(0,2))
        app.create_button(l, "↓",          self._q_move_down, "secondary", "sm").pack(side=tk.LEFT, padx=(0,2))
        app.create_button(l, "Remove Sel", self._q_remove_sel,"warning",   "sm").pack(side=tk.LEFT, padx=(0,2))
        app.create_button(l, "Clear All",  self._q_clear,     "danger",    "sm").pack(side=tk.LEFT)
        app.create_button(r, "▶ Play Queue", self._q_play,    "success",   "sm").pack(side=tk.RIGHT)

        self._q_lb  = q_lb
        self._q_svc = app.queue_manager.service
        q_lb.bind("<Double-Button-1>", self._q_dblclick)
        q_lb.bind("<Button-3>",        self._q_rclick)
        self._q_refresh()

    def _q_refresh(self):
        if not hasattr(self, '_q_lb'):
            return
        self._q_lb.delete(0, tk.END)
        queue   = self._q_svc.get_queue()
        cur     = self._q_svc.get_current_index()
        ACCENT  = "#2ecc71"
        muted   = self.app.muted_fg
        fg      = self.app.listbox_fg
        video_mapping = {}
        for i, entry in enumerate(queue):
            if i == cur:    marker, color = "▶", ACCENT
            elif entry.played: marker, color = "✓", muted
            else:            marker, color = " ", fg
            self._q_lb.insert(tk.END, f"  {marker}  {i+1}.  {entry.video_name}")
            self._q_lb.itemconfig(i, fg=color)
            video_mapping[i] = entry.video_path
        unplayed = sum(1 for e in queue if not e.played)
        if hasattr(self, '_q_info_lbl'):
            self._q_info_lbl.config(
                text=f"{len(queue)} videos  •  {unplayed} unplayed")
        if hasattr(self.app, 'video_preview_manager') and self.app.video_preview_manager:
            self.app.video_preview_manager.attach_to_listbox(self._q_lb, video_mapping)

    def _q_dblclick(self, _e=None):
        sel = self._q_lb.curselection()
        if sel:
            vp = self._q_svc.jump_to_index(sel[0])
            if vp: self.app._play_queue_videos([vp])
            self._q_refresh()

    def _q_rclick(self, event):
        sel = self._q_lb.curselection()
        if not sel: return
        m = tk.Menu(self.app.root, tearoff=0)
        m.add_command(label="Play Selected", command=self._q_play_selected)
        m.add_command(label="Remove",        command=self._q_remove_sel)
        try: m.tk_popup(event.x_root, event.y_root)
        finally: m.grab_release()

    def _q_play(self):
        queue = self._q_svc.get_queue()
        if not queue: return
        self.app._play_queue_videos([e.video_path for e in queue[self._q_svc.get_current_index():]])

    def _q_play_selected(self):
        sel   = self._q_lb.curselection()
        queue = self._q_svc.get_queue()
        videos = [queue[i].video_path for i in sel if i < len(queue)]
        if videos: self.app._play_queue_videos(videos)

    def _q_move_up(self):
        sel = list(self._q_lb.curselection())
        if sel: self._q_svc.move_items(sel, 'up'); self._q_refresh()

    def _q_move_down(self):
        sel = list(self._q_lb.curselection())
        if sel: self._q_svc.move_items(sel, 'down'); self._q_refresh()

    def _q_remove_sel(self):
        sel = list(self._q_lb.curselection())
        if sel: self._q_svc.remove_from_queue(sel); self._q_refresh()

    def _q_clear(self):
        if messagebox.askyesno("Clear Queue", "Clear entire queue?"):
            self._q_svc.clear_queue(); self._q_refresh()

    # ──────────────────────────────────────────────────────────────────────────
    # Favourites tab
    # ──────────────────────────────────────────────────────────────────────────

    def _build_favourites_tab(self, parent):
        app    = self.app
        bg     = app.bg_color
        ACCENT = "#FF9F43" if app.dark_mode else "#e67e22"
        PANEL  = app.listbox_bg

        hdr = self._section_header(parent, "♥  Favourites", ACCENT)
        self._fav_info_lbl = tk.Label(hdr, text="",
                                      font=app.small_font, bg=ACCENT, fg="white")
        self._fav_info_lbl.pack(side=tk.RIGHT, padx=14)

        chip_bar = tk.Frame(parent, bg=bg)
        chip_bar.pack(fill=tk.X, padx=6, pady=(6, 0))
        self._fav_dir_lbl = tk.Label(chip_bar, text="No directory selected",
                                     font=app.small_font, bg=app.badge_bg, fg=app.muted_fg,
                                     padx=8, pady=3)
        self._fav_dir_lbl.pack(side=tk.LEFT)

        body = tk.Frame(parent, bg=bg)
        body.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        card = self._card(body, PANEL)
        self._col_header(card, "VIDEOS — dbl-click to play")
        fav_lb = self._scrolled_listbox(card, ACCENT)

        l, r = self._action_bar(body)
        app.create_button(l, "Remove Sel", self._fav_remove_sel, "warning", "sm").pack(side=tk.LEFT, padx=(0,4))
        app.create_button(l, "Clear All",  self._fav_clear,      "danger",  "sm").pack(side=tk.LEFT)
        app.create_button(r, "▶ Play All", self._fav_play_all,   "success", "sm").pack(side=tk.RIGHT, padx=(4,0))
        app.create_button(r, "▶ Play Sel", self._fav_play_sel,   "primary", "sm").pack(side=tk.RIGHT)

        self._fav_lb      = fav_lb
        self._fav_svc     = app.favorites_manager.service
        self._fav_entries = []
        self._fav_dir     = None
        fav_lb.bind("<Double-Button-1>", self._fav_dblclick)
        fav_lb.bind("<Button-3>",        self._fav_rclick)

    def _fav_load_for_dir(self, directory):
        if not directory or not hasattr(self, '_fav_lb'):
            return
        self._fav_dir     = directory
        self._fav_entries = self._fav_svc.get_favorites_by_directory(directory)
        self._fav_lb.delete(0, tk.END)
        video_mapping = {}
        for i, fav in enumerate(self._fav_entries):
            self._fav_lb.insert(tk.END, f"  {i+1}.  {fav.video_name}")
            video_mapping[i] = fav.video_path
        self._fav_dir_lbl.config(text=f"  📁  {os.path.basename(directory)}  ")
        cnt = len(self._fav_entries)
        self._fav_info_lbl.config(text=f"{cnt} videos")
        if hasattr(self.app, 'video_preview_manager') and self.app.video_preview_manager:
            self.app.video_preview_manager.attach_to_listbox(self._fav_lb, video_mapping)

    def _fav_dblclick(self, _e=None):
        sel = self._fav_lb.curselection()
        if not sel or not self._fav_entries: return
        fav = self._fav_entries[sel[0]]
        if os.path.isfile(fav.video_path):
            self.app._play_favorites_videos([fav.video_path])

    def _fav_rclick(self, event):
        sel = self._fav_lb.curselection()
        if not sel: return
        m = tk.Menu(self.app.root, tearoff=0)
        m.add_command(label="Play Selected", command=self._fav_play_sel)
        m.add_command(label="Remove",        command=self._fav_remove_sel)
        try: m.tk_popup(event.x_root, event.y_root)
        finally: m.grab_release()

    def _fav_play_all(self):
        if not self._fav_entries: return
        videos = [f.video_path for f in self._fav_entries if os.path.isfile(f.video_path)]
        if videos: self.app._play_favorites_videos(videos)

    def _fav_play_sel(self):
        sel = self._fav_lb.curselection()
        if not sel or not self._fav_entries: return
        videos = [self._fav_entries[i].video_path for i in sel
                  if i < len(self._fav_entries) and os.path.isfile(self._fav_entries[i].video_path)]
        if videos: self.app._play_favorites_videos(videos)

    def _fav_remove_sel(self):
        sel = list(self._fav_lb.curselection())
        if not sel or not self._fav_dir or not self._fav_entries: return
        paths = [self._fav_entries[i].video_path for i in sel if i < len(self._fav_entries)]
        if paths:
            self._fav_svc.remove_multiple_from_favorites(paths, self._fav_dir)
            self._fav_load_for_dir(self._fav_dir)

    def _fav_clear(self):
        if not self._fav_dir or not self._fav_entries: return
        if messagebox.askyesno("Clear", f"Clear all {len(self._fav_entries)} favourites?"):
            self._fav_svc.clear_favorites_for_directory(self._fav_dir)
            self._fav_load_for_dir(self._fav_dir)

    # ──────────────────────────────────────────────────────────────────────────
    # History tab
    # ──────────────────────────────────────────────────────────────────────────

    def _build_history_tab(self, parent):
        app    = self.app
        bg     = app.bg_color
        ACCENT = "#C39BD3" if app.dark_mode else "#9b59b6"
        PANEL  = app.listbox_bg

        hdr = self._section_header(parent, "🕐  Watch History", ACCENT)
        self._hist_stats_lbl = tk.Label(hdr, text="",
                                        font=app.small_font, bg=ACCENT, fg="white")
        self._hist_stats_lbl.pack(side=tk.RIGHT, padx=14)

        # filter pills
        pill_row = tk.Frame(parent, bg=bg)
        pill_row.pack(fill=tk.X, padx=6, pady=(6, 2))
        tk.Label(pill_row, text="Show:", font=app.small_font,
                 bg=bg, fg=app.muted_fg).pack(side=tk.LEFT, padx=(0, 6))
        self._hist_filter = tk.StringVar(value="all")
        self._hist_pills  = []
        for lbl_text, val in [("All", "all"), ("Today", "today"), ("7 days", "week"), ("30 days", "month")]:
            pill = tk.Label(pill_row, text=f"  {lbl_text}  ",
                            font=app.small_font, bg=app.badge_bg, fg=app.badge_fg,
                            padx=4, pady=3, cursor="hand2")
            def _click(v=val):
                self._hist_filter.set(v)
                for p, pv in self._hist_pills:
                    p.config(bg=ACCENT if pv == v else app.badge_bg,
                             fg="white" if pv == v else app.badge_fg)
                self._hist_refresh()
            pill.bind("<Button-1>", lambda e, fn=_click: fn())
            pill.pack(side=tk.LEFT, padx=(0, 3))
            self._hist_pills.append((pill, val))

        body = tk.Frame(parent, bg=bg)
        body.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # treeview
        style = ttk.Style()
        style.configure("H.Treeview", background=PANEL, fieldbackground=PANEL,
                        foreground=app.listbox_fg, rowheight=24,
                        borderwidth=0, relief="flat")
        style.configure("H.Treeview.Heading",
                        background=app.badge_bg, foreground=app.text_color,
                        relief="flat", borderwidth=0)
        style.map("H.Treeview",
                  background=[("selected", app.listbox_select_bg)],
                  foreground=[("selected", "white")])

        card = tk.Frame(body, bg=PANEL,
                        highlightbackground=app.frame_border, highlightthickness=1)
        card.pack(fill=tk.BOTH, expand=True)

        columns = ("video", "dir", "watched_at", "dur", "pct")
        hist_tv = ttk.Treeview(card, columns=columns, show="headings", style="H.Treeview")
        for col, hdg, w in [("video","Video",200),("dir","Dir",110),
                             ("watched_at","Watched",120),("dur","Dur",70),("pct","Done",50)]:
            hist_tv.heading(col, text=hdg, anchor="w")
            hist_tv.column(col, width=w, minwidth=40, anchor="w")
        vsb = ttk.Scrollbar(card, orient=tk.VERTICAL,   command=hist_tv.yview)
        hsb = ttk.Scrollbar(card, orient=tk.HORIZONTAL, command=hist_tv.xview)
        hist_tv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        hist_tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        card.grid_rowconfigure(0, weight=1)
        card.grid_columnconfigure(0, weight=1)

        l, r = self._action_bar(body)
        app.create_button(l, "Clear All History", self._hist_clear_all, "warning", "sm").pack(side=tk.LEFT)
        app.create_button(r, "Remove Sel",        self._hist_remove_sel,"danger",  "sm").pack(side=tk.RIGHT, padx=(4,0))
        app.create_button(r, "▶ Play Sel",        self._hist_play_sel,  "success", "sm").pack(side=tk.RIGHT)

        self._hist_tv      = hist_tv
        self._hist_svc     = app.watch_history_manager.service
        self._hist_entries = []
        hist_tv.bind("<Double-Button-1>", self._hist_dblclick)
        hist_tv.bind("<Button-3>",        self._hist_rclick)

        # activate "all" pill after render
        parent.after(60, lambda: [
            p.config(bg=ACCENT if pv == "all" else app.badge_bg,
                     fg="white" if pv == "all" else app.badge_fg)
            for p, pv in self._hist_pills])
        self._hist_refresh()

    def _hist_refresh(self):
        if not hasattr(self, '_hist_tv'): return
        fv = self._hist_filter.get()
        if fv == "all":    entries = self._hist_svc.get_all_history()
        elif fv == "today": entries = self._hist_svc.get_history_by_date_range(0)
        elif fv == "week":  entries = self._hist_svc.get_history_by_date_range(7)
        else:               entries = self._hist_svc.get_history_by_date_range(30)
        self._hist_entries = entries
        for item in self._hist_tv.get_children():
            self._hist_tv.delete(item)
        for entry in entries:
            pct = f"{entry.completion_percentage:.0f}%" if entry.completion_percentage > 0 else "—"
            self._hist_tv.insert("", tk.END, tags=(entry.id,), values=(
                entry.video_name, os.path.basename(entry.directory_path),
                entry.get_watch_date_formatted(), entry.get_duration_formatted(), pct))
        total  = len(self._hist_svc.get_all_history())
        unique = self._hist_svc.get_unique_videos_count()
        if hasattr(self, '_hist_stats_lbl'):
            self._hist_stats_lbl.config(
                text=f"{total} total  •  {unique} unique  •  {len(entries)} shown")

    def _hist_dblclick(self, _e=None):
        sel = self._hist_tv.selection()
        if not sel: return
        tags = self._hist_tv.item(sel[0], 'tags')
        if not tags: return
        for entry in self._hist_entries:
            if entry.id == tags[0] and os.path.exists(entry.video_path):
                self.app._play_history_videos([entry.video_path]); return

    def _hist_rclick(self, event):
        sel = self._hist_tv.selection()
        if not sel: return
        m = tk.Menu(self.app.root, tearoff=0)
        m.add_command(label="Play Selected", command=self._hist_play_sel)
        m.add_command(label="Remove",        command=self._hist_remove_sel)
        try: m.tk_popup(event.x_root, event.y_root)
        finally: m.grab_release()

    def _hist_play_sel(self):
        sel = self._hist_tv.selection()
        if not sel: return
        videos = []
        for item in sel:
            tags = self._hist_tv.item(item, 'tags')
            if tags:
                for entry in self._hist_entries:
                    if entry.id == tags[0] and os.path.exists(entry.video_path):
                        videos.append(entry.video_path); break
        if videos: self.app._play_history_videos(videos)

    def _hist_remove_sel(self):
        sel = self._hist_tv.selection()
        if not sel: return
        ids = [self._hist_tv.item(i, 'tags')[0] for i in sel
               if self._hist_tv.item(i, 'tags')]
        if ids: self._hist_svc.remove_entries(ids); self._hist_refresh()

    def _hist_clear_all(self):
        total = len(self._hist_svc.get_all_history())
        if total and messagebox.askyesno("Clear History", f"Clear all {total} history entries?"):
            self._hist_svc.clear_all_history(); self._hist_refresh()

    # ──────────────────────────────────────────────────────────────────────────
    # Gallery tab
    # ──────────────────────────────────────────────────────────────────────────

    def _build_gallery_tab(self, parent):
        app = self.app
        bg  = app.bg_color
        t   = _tok(app)

        self._gallery_items    = []
        self._gallery_all      = []
        self._gallery_sel      = set()
        self._gallery_excl     = set()
        self._gallery_cards    = {}
        self._gallery_page     = 0
        self._gallery_pagesize = 50
        self._gallery_pages    = None
        self._gallery_anchor   = None
        self._gallery_search_timer = None
        self._gallery_photo_cache  = {}
        self._gallery_vpm      = None

        # top bar
        topbar = tk.Frame(parent, bg=t['surface'])
        topbar.pack(fill=tk.X)
        inner_top = tk.Frame(topbar, bg=t['surface'])
        inner_top.pack(fill=tk.BOTH, expand=True, padx=14, pady=0)

        trow = tk.Frame(inner_top, bg=t['surface'])
        trow.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(trow, text="Gallery", font=("Segoe UI", 13, "bold"),
                 bg=t['surface'], fg=t['text']).pack(side=tk.LEFT, anchor='w', pady=(10,0))
        self._gallery_sel_lbl = tk.Label(
            trow, text="  Nothing selected  ",
            font=("Segoe UI", 8), bg=t['pill_bg'], fg=t['text_muted'], padx=8, pady=2)
        self._gallery_sel_lbl.pack(side=tk.LEFT, anchor='w', padx=(10,0), pady=(12,0))

        arow = tk.Frame(inner_top, bg=t['surface'])
        arow.pack(side=tk.RIGHT, fill=tk.Y, pady=8)
        self._gal_btn(arow, "▶  Play Selected", self._gallery_play_selected,
                      t['accent'], "#fff", t['accent_hover']).pack(side=tk.RIGHT)

        tk.Frame(parent, bg=t['divider'], height=1).pack(fill=tk.X)

        # toolbar
        tbg = t['surface2']
        tb  = tk.Frame(parent, bg=tbg, height=42)
        tb.pack(fill=tk.X); tb.pack_propagate(False)
        itb = tk.Frame(tb, bg=tbg); itb.pack(fill=tk.BOTH, expand=True, padx=14)

        tk.Label(itb, text="Cols", font=("Segoe UI", 9),
                 bg=tbg, fg=t['text_sub']).pack(side=tk.LEFT, pady=10)
        self._gallery_cols_var = tk.IntVar(value=4)
        tk.Spinbox(itb, from_=2, to=10, textvariable=self._gallery_cols_var, width=3,
                   command=self._gallery_rebuild, font=("Segoe UI", 9),
                   bg=t['surface'], fg=t['text'], relief=tk.FLAT, bd=0,
                   highlightthickness=1, highlightbackground=t['border'],
                   buttonbackground=t['surface2'], insertbackground=t['text']
                   ).pack(side=tk.LEFT, padx=(4, 14), pady=10)

        tk.Frame(itb, bg=t['border'], width=1).pack(side=tk.LEFT, fill=tk.Y, pady=8)

        self._gallery_search_var = tk.StringVar()
        self._gallery_search_var.trace('w', lambda *_: self._gallery_on_search())
        sf = tk.Frame(itb, bg=t['surface'], highlightthickness=1, highlightbackground=t['border'])
        sf.pack(side=tk.LEFT, padx=(12, 0), pady=10)
        tk.Label(sf, text="⌕", font=("Segoe UI", 10),
                 bg=t['surface'], fg=t['text_muted']).pack(side=tk.LEFT, padx=(6,2))
        tk.Entry(sf, textvariable=self._gallery_search_var,
                 font=("Segoe UI", 9), width=18, bg=t['surface'], fg=t['text'],
                 relief=tk.FLAT, bd=0, insertbackground=t['text']
                 ).pack(side=tk.LEFT, ipady=4, padx=(0,6))

        tk.Frame(itb, bg=t['border'], width=1).pack(side=tk.LEFT, fill=tk.Y, pady=8, padx=8)
        self._gal_pill(itb, "Sel All", self._gallery_select_all, t).pack(side=tk.LEFT, padx=2, pady=10)
        self._gal_pill(itb, "Clear",   self._gallery_clear_sel,  t).pack(side=tk.LEFT, padx=2, pady=10)

        rt = tk.Frame(itb, bg=tbg); rt.pack(side=tk.RIGHT)
        tk.Label(rt, text="Per page", font=("Segoe UI", 9),
                 bg=tbg, fg=t['text_sub']).pack(side=tk.LEFT, pady=10)
        self._gallery_ps_var = tk.StringVar(value="50")
        om = tk.OptionMenu(rt, self._gallery_ps_var, "25","50","100","200",
                           command=self._gallery_page_size_changed)
        om.configure(font=("Segoe UI", 9), bg=t['surface'], fg=t['text'],
                     relief=tk.FLAT, highlightthickness=1, highlightbackground=t['border'],
                     activebackground=t['surface2'])
        om.pack(side=tk.LEFT, padx=(4,0), pady=10)

        tk.Frame(parent, bg=t['divider'], height=1).pack(fill=tk.X)

        self._gallery_pag_frame = tk.Frame(parent, bg=t['bg'])
        self._gallery_pag_frame.pack(fill=tk.X, padx=14, pady=(6,2))

        body = tk.Frame(parent, bg=t['bg'])
        body.pack(fill=tk.BOTH, expand=True)
        self._gallery_canvas = tk.Canvas(body, bg=t['bg'], highlightthickness=0)
        vsb = tk.Scrollbar(body, orient=tk.VERTICAL, command=self._gallery_canvas.yview,
                           width=10, bg=t['bg'], troughcolor=t['bg'],
                           activebackground=t['scrollbar'])
        self._gallery_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0,2))
        self._gallery_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._gallery_grid_frame = tk.Frame(self._gallery_canvas, bg=t['bg'])
        cw = self._gallery_canvas.create_window((0,0), window=self._gallery_grid_frame, anchor='nw')
        self._gallery_grid_frame.bind("<Configure>",
            lambda e: self._gallery_canvas.configure(scrollregion=self._gallery_canvas.bbox("all")))
        self._gallery_canvas.bind("<Configure>",
            lambda e: self._gallery_canvas.itemconfig(cw, width=e.width))

        self._gallery_show_empty()

    def _gallery_show_empty(self):
        for w in self._gallery_grid_frame.winfo_children():
            w.destroy()
        t = _tok(self.app)
        tk.Label(self._gallery_grid_frame,
                 text="Select videos or open a directory to view gallery",
                 font=("Segoe UI", 10), bg=t['bg'], fg=t['text_muted']).pack(pady=60)

    def load_gallery(self, videos, video_preview_manager=None):
        self._gallery_vpm = video_preview_manager or getattr(self.app,'video_preview_manager',None)
        self._gallery_sel.clear(); self._gallery_excl.clear()
        self._gallery_cards.clear(); self._gallery_photo_cache.clear()
        self._gallery_page = 0; self._gallery_pages = None
        self.switch_to(TAB_GALLERY)

        from managers.grid_view_manager import GridViewItem
        from collections import OrderedDict

        def _load():
            dg = OrderedDict()
            for v in videos: dg.setdefault(os.path.dirname(v), []).append(v)
            items = []
            for d, vids in dg.items():
                items.append({'type':'header','path':d,'name':os.path.basename(d) or d,'video_count':len(vids)})
                for v in vids: items.append({'type':'video','path':v,'video_item':GridViewItem(v)})
            self._gallery_items = items; self._gallery_all = items.copy()
            self.app.root.after(0, self._gallery_rebuild)

        threading.Thread(target=_load, daemon=True, name="GalleryLoad").start()

    def _gallery_get_page_items(self):
        target = self._gallery_pagesize
        pages, cur, cnt = [], [], 0
        i = 0; items = self._gallery_items
        while i < len(items):
            item = items[i]
            if item['type'] == 'header':
                block = [item]; i += 1
                while i < len(items) and items[i]['type'] == 'video':
                    block.append(items[i]); i += 1
                vcnt = len(block) - 1
                if cnt > 0 and cnt + vcnt > target:
                    pages.append(cur); cur = []; cnt = 0
                cur.extend(block); cnt += vcnt
            else: i += 1
        if cur: pages.append(cur)
        self._gallery_pages = pages
        total = max(1, len(pages))
        self._gallery_page = max(0, min(self._gallery_page, total-1))
        return pages[self._gallery_page] if pages else []

    def _gallery_total_pages(self):
        if not self._gallery_pages: self._gallery_get_page_items()
        return max(1, len(self._gallery_pages or []))

    def _gallery_page_size_changed(self, val):
        self._gallery_pagesize = int(val); self._gallery_page = 0
        self._gallery_pages = None; self._gallery_rebuild()

    def _gallery_build_pagination(self):
        for w in self._gallery_pag_frame.winfo_children(): w.destroy()
        t = _tok(self.app); pf = self._gallery_pag_frame
        total = self._gallery_total_pages()
        tv = sum(1 for i in self._gallery_items if i['type']=='video')
        self._gal_pill(pf, "← Prev", self._gallery_prev_page, t).pack(side=tk.LEFT, padx=(0,4))
        tk.Label(pf, text=f"Page {self._gallery_page+1} / {total}  ·  {tv:,} videos",
                 font=("Segoe UI",9), bg=t['bg'], fg=t['text_sub']).pack(side=tk.LEFT, padx=8)
        self._gal_pill(pf, "Next →", self._gallery_next_page, t).pack(side=tk.LEFT, padx=(4,0))

    def _gallery_prev_page(self):
        if self._gallery_page > 0:
            self._gallery_page -= 1; self._gallery_rebuild()
            try: self._gallery_canvas.yview_moveto(0)
            except: pass

    def _gallery_next_page(self):
        if self._gallery_page < self._gallery_total_pages()-1:
            self._gallery_page += 1; self._gallery_rebuild()
            try: self._gallery_canvas.yview_moveto(0)
            except: pass

    def _gallery_rebuild(self):
        for w in self._gallery_grid_frame.winfo_children(): w.destroy()
        self._gallery_cards.clear()
        t = _tok(self.app); cols = self._gallery_cols_var.get()
        self._gallery_build_pagination()
        if not self._gallery_items: self._gallery_show_empty(); return
        page_items = self._gallery_get_page_items()
        gr = -1; vc = 0
        for item_data in page_items:
            if item_data['type'] == 'header':
                gr += 1; vc = 0
                self._gallery_build_header(item_data, gr, cols, t); gr += 1; continue
            vp = item_data['path']
            self._gallery_build_card(item_data['video_item'], vp,
                                     vp in self._gallery_sel, vp in self._gallery_excl, gr, vc, t)
            vc += 1
            if vc >= cols: vc = 0; gr += 1
        for i in range(cols):
            self._gallery_grid_frame.columnconfigure(i, weight=1, uniform="gcol")
        self._gallery_update_sel_label()

    CARD_W = 180; CARD_H = 100

    def _gallery_build_header(self, item_data, gr, cols, t):
        hdr = tk.Frame(self._gallery_grid_frame, bg=t['bg'])
        hdr.grid(row=gr, column=0, columnspan=cols, sticky='ew', padx=6, pady=(18,4))
        tk.Frame(hdr, bg=t['accent'], width=3).pack(side=tk.LEFT, fill=tk.Y, padx=(0,8))
        left = tk.Frame(hdr, bg=t['bg']); left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(left, text=f"📁  {item_data['name']}", font=("Segoe UI",11,"bold"),
                 bg=t['bg'], fg=t['text'], anchor='w', cursor="hand2").pack(side=tk.LEFT)
        cnt = item_data.get('video_count',0)
        tk.Label(left, text=f"  {cnt} video{'s' if cnt!=1 else ''}  ",
                 font=("Segoe UI",7), bg=t['pill_bg'], fg=t['text_sub'],
                 padx=6, pady=2).pack(side=tk.LEFT, padx=6, anchor='w', pady=2)
        tk.Frame(hdr, bg=t['divider'], height=1).pack(side=tk.BOTTOM, fill=tk.X, pady=(4,0))
        for w in (hdr, left):
            w.bind("<Button-1>", lambda e, dp=item_data['path']: self._gallery_dir_click(e, dp))

    def _gallery_build_card(self, item, vp, is_sel, is_exc, gr, vc, t):
        if is_sel:  bc,bw = t['accent'],  2; cbg=ibg=t['accent_dim']; nfg,nw=t['accent'],  "bold"
        elif is_exc:bc,bw = t['excluded'],2; cbg=ibg=t['surface'];    nfg,nw=t['text_muted'],"normal"
        else:       bc,bw = t['border'],  1; cbg=ibg=t['surface'];    nfg,nw=t['text'],     "normal"

        card = tk.Frame(self._gallery_grid_frame, bg=cbg,
                        highlightthickness=bw, highlightbackground=bc, cursor="hand2")
        card.grid(row=gr, column=vc, padx=5, pady=5, sticky='nsew')
        self._gallery_cards[vp] = card

        tc = tk.Frame(card, bg=t['thumb_bg'], width=self.CARD_W, height=self.CARD_H)
        tc._is_thumb = True; tc.pack(fill=tk.BOTH, expand=True); tc.pack_propagate(False)
        tl = tk.Label(tc, bg=t['thumb_bg'], fg="#555a65", text="▶", font=("Segoe UI",20))
        tl.pack(expand=True)
        if is_exc:
            b = tk.Label(tc, text=" 🚫 Excluded ", bg=t['excluded'], fg="#fff",
                         font=("Segoe UI",7,"bold"), padx=2, pady=2)
            b._is_excluded_badge = True; b.place(relx=0, rely=0, anchor='nw')

        inf = tk.Frame(card, bg=ibg, padx=6, pady=5); inf._is_info = True; inf.pack(fill=tk.X)
        name = os.path.basename(vp)
        if len(name) > 28: name = name[:25]+"…"
        tk.Label(inf, text=name, bg=ibg, fg=nfg,
                 font=("Segoe UI",8,nw), anchor='w').pack(fill=tk.X)

        for w in (card, tc, tl, inf):
            w.bind("<Button-1>",        lambda e, _v=vp: self._gallery_card_click(e, _v))
            w.bind("<Button-3>",        lambda e, _v=vp: self._gallery_card_rclick(e, _v))
            w.bind("<Double-Button-1>", lambda e, _v=vp: self._gallery_play_single(_v))
        card.bind("<Enter>", lambda e, _v=vp: self._gallery_card_enter(e, _v))
        card.bind("<Leave>", lambda e, _v=vp: self._gallery_card_leave(e, _v))

        gvm = self.app.grid_view_manager
        vn  = os.path.normpath(vp)
        ph  = self._gallery_photo_cache.get(vn)
        if ph is None and gvm.video_preview_manager and hasattr(gvm.video_preview_manager,'lru_cache'):
            ph = gvm.video_preview_manager.lru_cache.get(vn)
            if ph: self._gallery_photo_cache[vn] = ph
        if ph: self._gallery_set_thumb(tl, ph)
        else:  gvm.thumbnail_executor.submit(gvm._load_thumbnail, item, tl, vn)

    def _gallery_card_click(self, event, vp):
        ctrl = bool(event.state&0x4); shift = bool(event.state&0x1)
        vids = [i['path'] for i in self._gallery_items if i['type']=='video']
        if vp not in vids: return
        idx = vids.index(vp)
        if shift:
            anchor = self._gallery_anchor if self._gallery_anchor in vids else vp
            ai = vids.index(anchor)
            for i in range(min(ai,idx), max(ai,idx)+1):
                self._gallery_sel.add(vids[i]); self._gallery_update_card(vids[i])
        elif ctrl:
            if vp in self._gallery_sel: self._gallery_sel.discard(vp)
            else: self._gallery_sel.add(vp)
            self._gallery_update_card(vp); self._gallery_anchor = vp
        else:
            old = self._gallery_sel.copy(); self._gallery_sel = {vp}
            for op in old:
                if op != vp: self._gallery_update_card(op)
            self._gallery_update_card(vp); self._gallery_anchor = vp
        self._gallery_update_sel_label()

    def _gallery_dir_click(self, event, dir_path):
        ctrl    = bool(event.state&0x4)
        dir_vps = [i['path'] for i in self._gallery_items
                   if i['type']=='video' and os.path.dirname(i['path'])==dir_path]
        if not dir_vps: return
        if ctrl:
            all_sel = all(v in self._gallery_sel for v in dir_vps)
            for v in dir_vps:
                if all_sel: self._gallery_sel.discard(v)
                else: self._gallery_sel.add(v)
                self._gallery_update_card(v)
        else:
            all_sel = all(v in self._gallery_sel for v in dir_vps)
            old = self._gallery_sel.copy()
            self._gallery_sel = set() if all_sel else set(dir_vps)
            for v in old | self._gallery_sel: self._gallery_update_card(v)
            self._gallery_anchor = dir_vps[0] if not all_sel else None
        self._gallery_update_sel_label()

    def _gallery_card_enter(self, event, vp):
        card = self._gallery_cards.get(vp)
        if card and card.winfo_exists() and vp not in self._gallery_sel and vp not in self._gallery_excl:
            t = _tok(self.app)
            card.configure(bg=t['card_hover'], highlightbackground=t['accent'])
            for ch in card.winfo_children():
                if getattr(ch,'_is_info',False):
                    ch.configure(bg=t['card_hover'])
                    for lbl in ch.winfo_children():
                        if isinstance(lbl, tk.Label): lbl.configure(bg=t['card_hover'])

    def _gallery_card_leave(self, event, vp):
        card = self._gallery_cards.get(vp)
        if card and card.winfo_exists() and vp not in self._gallery_sel and vp not in self._gallery_excl:
            t = _tok(self.app)
            card.configure(bg=t['surface'], highlightbackground=t['border'])
            for ch in card.winfo_children():
                if getattr(ch,'_is_info',False):
                    ch.configure(bg=t['surface'])
                    for lbl in ch.winfo_children():
                        if isinstance(lbl, tk.Label): lbl.configure(bg=t['surface'])

    def _gallery_card_rclick(self, event, vp):
        if vp not in self._gallery_sel:
            self._gallery_sel = {vp}; self._gallery_update_card(vp)
            self._gallery_update_sel_label()
        self._gallery_show_context(event, vp)

    def _gallery_show_context(self, event, vp):
        app = self.app
        m   = tk.Menu(app.root, tearoff=0,
                      bg="#313335" if app.dark_mode else "#f5f5f5",
                      fg="#A9B7C6" if app.dark_mode else "#333333",
                      activebackground="#2D5A8E" if app.dark_mode else "#3498db",
                      activeforeground="#FFFFFF", relief="flat", bd=1, font=("Segoe UI",9))
        m.add_command(label=f"▶ Play Selected ({len(self._gallery_sel)})",
                      command=self._gallery_play_selected)
        m.add_separator()
        m.add_command(label="Add to Playlist",
                      command=lambda: app.playlist_manager.add_videos_to_playlist(
                          [], list(self._gallery_sel)))
        m.add_command(label="Add to Queue",
                      command=lambda: app.queue_manager.add_to_queue(
                          list(self._gallery_sel), added_from="gallery"))
        m.add_separator()
        sn = [v for v in self._gallery_sel if v not in self._gallery_excl]
        se = [v for v in self._gallery_sel if v in self._gallery_excl]
        if sn:
            m.add_command(label="Exclude Selected",
                          command=lambda: [self._gallery_excl.update(sn),
                                           [self._gallery_update_card(v) for v in sn]])
        if se:
            m.add_command(label="Remove Exclusion",
                          command=lambda: [self._gallery_excl.difference_update(se),
                                           [self._gallery_update_card(v) for v in se]])
        m.add_separator()
        if len(self._gallery_sel) == 1:
            fp = list(self._gallery_sel)[0]
            if os.path.isfile(fp):
                m.add_command(label="Open File Location",
                              command=lambda: app._context_open_location(fp))
                m.add_command(label="Properties",
                              command=lambda: app._context_show_properties(fp))
        try: m.tk_popup(event.x_root, event.y_root)
        finally: m.grab_release()

    def _gallery_update_card(self, vp):
        card = self._gallery_cards.get(vp)
        if not card or not card.winfo_exists(): return
        t = _tok(self.app); is_sel = vp in self._gallery_sel; is_exc = vp in self._gallery_excl
        if is_sel:  bc,bw=t['accent'],  2; cbg=ibg=t['accent_dim']; nfg,nw=t['accent'],  "bold"
        elif is_exc:bc,bw=t['excluded'],2; cbg=ibg=t['surface'];    nfg,nw=t['text_muted'],"normal"
        else:       bc,bw=t['border'],  1; cbg=ibg=t['surface'];    nfg,nw=t['text'],    "normal"
        card.configure(bg=cbg, highlightbackground=bc, highlightthickness=bw)
        for ch in card.winfo_children():
            if getattr(ch,'_is_info',False):
                ch.configure(bg=ibg)
                for lbl in ch.winfo_children():
                    if isinstance(lbl, tk.Label): lbl.configure(bg=ibg, fg=nfg, font=("Segoe UI",8,nw))

    def _gallery_update_sel_label(self):
        if not hasattr(self,'_gallery_sel_lbl'): return
        t = _tok(self.app); n = len(self._gallery_sel)
        if n == 0: self._gallery_sel_lbl.config(text="  Nothing selected  ", bg=t['pill_bg'], fg=t['text_muted'])
        else:      self._gallery_sel_lbl.config(text=f"  {n} selected  ", bg=t['accent_dim'], fg=t['accent'])

    def _gallery_select_all(self):
        page = self._gallery_pages[self._gallery_page] if self._gallery_pages else self._gallery_items
        for item in page:
            if item['type']=='video': self._gallery_sel.add(item['path']); self._gallery_update_card(item['path'])
        self._gallery_update_sel_label()

    def _gallery_clear_sel(self):
        old = self._gallery_sel.copy(); self._gallery_sel.clear(); self._gallery_anchor = None
        for v in old: self._gallery_update_card(v)
        self._gallery_update_sel_label()

    def _gallery_play_selected(self):
        videos = [i['path'] for i in self._gallery_items
                  if i['type']=='video' and i['path'] in self._gallery_sel
                  and i['path'] not in self._gallery_excl]
        if videos: self.app._play_grid_videos(videos)

    def _gallery_play_single(self, vp):
        self._gallery_sel = {vp}; self._gallery_update_sel_label(); self._gallery_play_selected()

    def _gallery_on_search(self):
        if self._gallery_search_timer: self.app.root.after_cancel(self._gallery_search_timer)
        self._gallery_search_timer = self.app.root.after(380, self._gallery_filter)

    def _gallery_filter(self):
        self._gallery_page = 0; self._gallery_pages = None
        term = self._gallery_search_var.get().lower()
        if not term:
            self._gallery_items = self._gallery_all.copy()
        else:
            result = []; cur_hdr = None; cur_vids = []
            for item in self._gallery_all:
                if item['type'] == 'header':
                    if cur_hdr and cur_vids: result.append(cur_hdr); result.extend(cur_vids)
                    cur_hdr = dict(item); cur_hdr['matches'] = term in item['name'].lower(); cur_vids=[]
                else:
                    if (cur_hdr and cur_hdr.get('matches')) or term in os.path.basename(item['path']).lower():
                        cur_vids.append(item)
            if cur_hdr and cur_vids: result.append(cur_hdr); result.extend(cur_vids)
            self._gallery_items = result
        self._gallery_rebuild()

    def _gallery_set_thumb(self, label, photo):
        try:
            if label.winfo_exists(): label.configure(image=photo, text=""); label.image = photo
        except Exception: pass

    def _gal_btn(self, parent, text, cmd, bg, fg, hover=None):
        btn = tk.Label(parent, text=text, font=("Segoe UI",9,"bold"),
                       bg=bg, fg=fg, padx=12, pady=6, cursor="hand2")
        btn.bind("<Button-1>", lambda e: cmd())
        if hover:
            btn.bind("<Enter>", lambda e: btn.configure(bg=hover))
            btn.bind("<Leave>", lambda e: btn.configure(bg=bg))
        return btn

    def _gal_pill(self, parent, text, cmd, t):
        btn = tk.Label(parent, text=text, font=("Segoe UI",8),
                       bg=t['pill_bg'], fg=t['pill_fg'], padx=10, pady=3, cursor="hand2")
        btn.bind("<Button-1>", lambda e: cmd())
        btn.bind("<Enter>",    lambda e: btn.configure(bg=t['pill_bg_h'], fg=t['text']))
        btn.bind("<Leave>",    lambda e: btn.configure(bg=t['pill_bg'],   fg=t['pill_fg']))
        return btn

    # ──────────────────────────────────────────────────────────────────────────
    # Notify helpers
    # ──────────────────────────────────────────────────────────────────────────

    def notify_directory_changed(self, directory):
        if hasattr(self, '_fav_lb'): self._fav_load_for_dir(directory)

    def notify_queue_changed(self):
        if self._current_tab == TAB_QUEUE: self._q_refresh()

    def notify_favourites_changed(self):
        d = self.app.get_current_selected_directory()
        if d and hasattr(self, '_fav_lb'): self._fav_load_for_dir(d)

    def notify_history_changed(self):
        if self._current_tab == TAB_HISTORY: self._hist_refresh()

    def notify_playlist_changed(self):
        self._pl_refresh()
        if self._pl_current: self._pl_on_select()

    # ──────────────────────────────────────────────────────────────────────────
    # Patch toolbar pills
    # ──────────────────────────────────────────────────────────────────────────

    def _patch_pill_buttons(self):
        app     = self.app
        mapping = {
            "🎵 Playlist":   TAB_PLAYLIST,
            "⬛ Queue":      TAB_QUEUE,
            "♥ Favourites": TAB_FAVOURITES,
            "🕐 History":   TAB_HISTORY,
        }
        for label, tab_idx in mapping.items():
            btn = app._media_pill_btns.get(label)
            if not btn: continue
            btn.unbind("<ButtonRelease-1>")
            def _make(ti=tab_idx, lbl=label, b=btn):
                def on_release(e):
                    a = app.pill_accents(lbl)
                    b.config(bg=a[1], fg=a[2], highlightbackground=a[1])
                    self.switch_to(ti)
                return on_release
            btn.bind("<ButtonRelease-1>", _make())

    # ──────────────────────────────────────────────────────────────────────────
    # Patch managers
    # ──────────────────────────────────────────────────────────────────────────

    def _patch_managers(self):
        app = self.app; panel = self

        def _show_playlist(*a, **kw): panel.switch_to(TAB_PLAYLIST); panel._pl_refresh()
        app.playlist_manager.show_manager = _show_playlist
        app._manage_playlists             = _show_playlist

        def _show_queue(*a, **kw): panel.switch_to(TAB_QUEUE); panel._q_refresh()
        app.queue_manager.show_manager = _show_queue
        app._show_queue_manager        = _show_queue

        def _show_favs(selected_directory=None, *a, **kw):
            panel.switch_to(TAB_FAVOURITES)
            d = selected_directory or app.get_current_selected_directory()
            if d: panel._fav_load_for_dir(d)
        app.favorites_manager.show_manager = _show_favs
        app._show_favorites_manager        = _show_favs

        def _show_hist(*a, **kw): panel.switch_to(TAB_HISTORY); panel._hist_refresh()
        app.watch_history_manager.show_manager = _show_hist
        app._show_watch_history               = _show_hist

        # directory select hook
        orig_on_dir = app.on_directory_select
        def _patched_on_dir(event):
            orig_on_dir(event)
            sel = app.dir_listbox.curselection()
            if sel and sel[0] < len(app.selected_dirs):
                panel.notify_directory_changed(app.selected_dirs[sel[0]])
        app.on_directory_select = _patched_on_dir
        app.dir_listbox.bind('<<ListboxSelect>>', app.on_directory_select)

        orig_add_fav = app.favorites_manager.add_to_favorites
        def _padd_fav(vps, dp):
            r = orig_add_fav(vps, dp); panel.notify_favourites_changed(); return r
        app.favorites_manager.add_to_favorites = _padd_fav

        orig_rem_fav = app.favorites_manager.remove_from_favorites
        def _prem_fav(vps, dp):
            r = orig_rem_fav(vps, dp); panel.notify_favourites_changed(); return r
        app.favorites_manager.remove_from_favorites = _prem_fav

        orig_add_q = app.queue_manager.add_to_queue
        def _padd_q(vps, added_from="manual"):
            r = orig_add_q(vps, added_from); panel.notify_queue_changed(); return r
        app.queue_manager.add_to_queue = _padd_q

        orig_track = app.watch_history_manager.track_video_playback
        def _ptrack(vp, dw=0, td=0):
            orig_track(vp, dw, td); panel.notify_history_changed()
        app.watch_history_manager.track_video_playback = _ptrack

        orig_pl_add = app.playlist_manager.add_videos_to_playlist
        def _ppl_add(videos, selected_videos=None):
            orig_pl_add(videos, selected_videos); panel.notify_playlist_changed()
        app.playlist_manager.add_videos_to_playlist = _ppl_add

        # Grid view → Gallery tab
        def _patched_show_grid(videos, video_preview_manager=None):
            panel.load_gallery(videos, video_preview_manager)
        app.grid_view_manager.show_grid_view = _patched_show_grid

        def _patched_open_grid(videos):
            panel.load_gallery(videos, app.video_preview_manager)
        app._open_grid_view = _patched_open_grid

        app.grid_view_manager.play_callback = app._play_grid_videos
