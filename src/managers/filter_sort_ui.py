import tkinter as tk
from tkinter import ttk
import threading

from utils import _responsive_geometry


class FilterSortUI:
    def __init__(self, parent, theme_provider, filter_sort_manager, on_apply_callback):
        self.parent = parent
        self.theme_provider = theme_provider
        self.manager = filter_sort_manager
        self.on_apply_callback = on_apply_callback
        self.filter_window = None
        self.app_instance = None
        self._tile_refreshers = []
        self._active_canvas = None

    def show_filter_dialog(self):
        if self.filter_window and self.filter_window.winfo_exists():
            self.filter_window.lift()
            return

        self.filter_window = tk.Toplevel(self.parent)
        self.filter_window.withdraw()
        self.filter_window.title("Advanced Filters & Sorting")
        self.filter_window.geometry(_responsive_geometry(self.parent, 1600, 900))
        self.filter_window.configure(bg=self.theme_provider.bg_color)
        self.filter_window.transient(self.parent)
        self.filter_window.grab_set()

        self._setup_filter_ui()

        from icon_helper import apply_icon
        apply_icon(self.filter_window)
        self.filter_window.deiconify()

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _style_notebook(self, nb):
        tp = self.theme_provider
        style = ttk.Style()
        try:
            style.configure(
                "FilterSort.TNotebook",
                background=tp.bg_color,
                borderwidth=0,
                relief="flat",
                tabmargins=[0, 0, 0, 0],
            )
            style.configure(
                "FilterSort.TNotebook.Tab",
                background=tp.surface_color,
                foreground=tp.text_muted,
                font=("Segoe UI", 10),
                padding=[22, 10],
                borderwidth=0,
                relief="flat",
            )
            style.map(
                "FilterSort.TNotebook.Tab",
                background=[("selected", tp.bg_color), ("active", tp.hover_color)],
                foreground=[("selected", tp.accent_color), ("active", tp.text_color)],
                font=[("selected", ("Segoe UI", 10, "bold"))],
            )
            nb.configure(style="FilterSort.TNotebook")
        except Exception:
            pass

    def _make_section(self, parent, title, pady=(0, 12)):
        tp = self.theme_provider
        border = tk.Frame(parent, bg=tp.border_color, bd=0)
        border.pack(fill=tk.X, pady=pady)

        header = tk.Frame(border, bg=tp.surface_color)
        header.pack(fill=tk.X)
        tk.Label(
            header, text=title,
            font=("Segoe UI", 9, "bold"),
            bg=tp.surface_color, fg=tp.text_muted,
            padx=12, pady=6,
        ).pack(side=tk.LEFT)

        tk.Frame(border, bg=tp.border_color, height=1).pack(fill=tk.X)

        body = tk.Frame(border, bg=tp.bg_color, padx=12, pady=10)
        body.pack(fill=tk.X, padx=1, pady=(0, 1))
        return body

    def _make_styled_entry(self, parent, width=12, textvariable=None):
        tp = self.theme_provider
        kwargs = dict(
            font=tp.normal_font,
            bg=getattr(tp, 'entry_bg', tp.surface_color),
            fg=getattr(tp, 'entry_fg', tp.text_color),
            insertbackground=getattr(tp, 'entry_fg', tp.text_color),
            relief=tk.FLAT, bd=0,
            highlightthickness=1,
            highlightbackground=getattr(tp, 'entry_border', tp.border_color),
            width=width,
        )
        if textvariable is not None:
            kwargs['textvariable'] = textvariable
        e = tk.Entry(parent, **kwargs)
        border_normal = getattr(tp, 'entry_border', tp.border_color)
        e.bind('<FocusIn>',  lambda ev: e.config(highlightbackground=tp.accent_color))
        e.bind('<FocusOut>', lambda ev: e.config(highlightbackground=border_normal))
        return e

    def _make_scrollable(self, parent):
        """Return (outer_frame, scroll_canvas, inner_container)."""
        tp = self.theme_provider
        outer = tk.Frame(parent, bg=tp.bg_color)

        canvas = tk.Canvas(outer, bg=tp.bg_color, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=tp.bg_color)
        win_id = canvas.create_window((0, 0), window=inner, anchor='nw')

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))

        container = tk.Frame(inner, bg=tp.bg_color)
        container.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        return outer, canvas, container

    def _make_pill_group(self, parent, variable, options, cols=3):
        """Clickable pill tiles bound to a StringVar. Returns (grid_frame, refresh_fn)."""
        tp = self.theme_provider
        tiles = {}

        def refresh():
            val = variable.get()
            for v, (f, l) in tiles.items():
                if v == val:
                    f.config(bg=tp.accent_color, highlightbackground=tp.accent_color)
                    l.config(bg=tp.accent_color, fg='#ffffff')
                else:
                    f.config(bg=tp.surface_color, highlightbackground=tp.border_color)
                    l.config(bg=tp.surface_color, fg=tp.text_color)

        grid = tk.Frame(parent, bg=tp.bg_color)
        for i in range(cols):
            grid.columnconfigure(i, weight=1)

        for idx, (value, text) in enumerate(options):
            f = tk.Frame(
                grid, bg=tp.surface_color, cursor='hand2',
                highlightthickness=1, highlightbackground=tp.border_color,
            )
            f.grid(row=idx // cols, column=idx % cols, padx=4, pady=4, sticky='ew')
            l = tk.Label(
                f, text=text, font=tp.normal_font,
                bg=tp.surface_color, fg=tp.text_color,
                padx=12, pady=9, anchor='w',
            )
            l.pack(fill=tk.X)

            def _click(v=value):
                variable.set(v)
                refresh()

            def _enter(e, f=f, l=l, v=value):
                if variable.get() != v:
                    f.config(bg=tp.hover_color, highlightbackground=tp.accent_color)
                    l.config(bg=tp.hover_color)

            def _leave(e, f=f, l=l, v=value):
                if variable.get() != v:
                    f.config(bg=tp.surface_color, highlightbackground=tp.border_color)
                    l.config(bg=tp.surface_color, fg=tp.text_color)

            for w in (f, l):
                w.bind('<Button-1>', lambda e, v=value: _click(v))
                w.bind('<Enter>', _enter)
                w.bind('<Leave>', _leave)

            tiles[value] = (f, l)

        refresh()
        self._tile_refreshers.append(refresh)
        return grid, refresh

    # ── Main UI ────────────────────────────────────────────────────────────────

    def _setup_filter_ui(self):
        self._tile_refreshers = []
        tp = self.theme_provider

        main = tk.Frame(self.filter_window, bg=tp.bg_color)
        main.pack(fill=tk.BOTH, expand=True)

        hdr = tk.Frame(main, bg=tp.bg_color)
        hdr.pack(fill=tk.X, padx=24, pady=(20, 0))

        tk.Label(
            hdr,
            text="Advanced Filters & Sorting",
            font=tp.header_font,
            bg=tp.bg_color, fg=tp.text_color,
        ).pack(side=tk.LEFT)

        btn_area = tk.Frame(hdr, bg=tp.bg_color)
        btn_area.pack(side=tk.RIGHT)
        tp.create_modern_button(btn_area, "↺  Reset All", self._reset_filters, "warning", "sm").pack(side=tk.LEFT,
                                                                                                     padx=(0, 6))
        tp.create_modern_button(btn_area, "Cancel", self.filter_window.destroy, "secondary", "sm").pack(side=tk.LEFT,
                                                                                                        padx=(0, 6))
        tp.create_modern_button(btn_area, "✓  Apply", self._apply_filters, "success", "sm").pack(side=tk.LEFT)

        tk.Frame(main, bg=tp.border_color, height=1).pack(fill=tk.X, pady=(14, 0))

        nb = ttk.Notebook(main)
        nb.pack(fill=tk.BOTH, expand=True, padx=24, pady=16)
        self._style_notebook(nb)

        scroll_canvases = {}

        def _make_tab(build_fn, label):
            frame, canvas = build_fn(nb)
            nb.add(frame, text=label)
            idx = nb.index(nb.tabs()[-1])
            scroll_canvases[idx] = canvas

        _make_tab(self._create_quick_filters_tab,    "  ⚡  Quick Filters  ")
        _make_tab(self._create_sort_options_tab,     "  ↕  Sort Options  ")
        _make_tab(self._create_advanced_filters_tab, "  🔧  Advanced Filters  ")

        stats_frame = self._create_statistics_tab(nb)
        nb.add(stats_frame, text="  📊  Statistics  ")

        def _on_tab_change(e):
            try:
                idx = nb.index(nb.select())
                self._active_canvas = scroll_canvases.get(idx)
            except Exception:
                pass

        nb.bind("<<NotebookTabChanged>>", _on_tab_change)
        self._active_canvas = scroll_canvases.get(0)

        def _on_mousewheel(event):
            canvas = self._active_canvas
            if canvas:
                try:
                    if canvas.winfo_exists():
                        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                except Exception:
                    pass

        self.filter_window.bind("<MouseWheel>", _on_mousewheel)

    # ── Tabs ───────────────────────────────────────────────────────────────────

    def _create_quick_filters_tab(self, parent):
        tp = self.theme_provider
        outer, canvas, container = self._make_scrollable(parent)

        self.quick_filter_var = tk.StringVar(value='all')
        quick_filters = dict(self.manager.get_quick_filter_names())

        categories = {
            'General':          ['all'],
            'Recently Added':   ['recent_7days', 'recent_30days'],
            'Playback History': ['played_today', 'played_week', 'never_played', 'frequently_played'],
            'Quality':          ['hd_videos', 'full_hd_videos'],
            'Duration':         ['short_videos', 'long_videos'],
            'File Size':        ['large_files'],
        }

        for cat_title, keys in categories.items():
            opts = [(k, quick_filters[k]) for k in keys if k in quick_filters]
            if not opts:
                continue
            body = self._make_section(container, cat_title)
            grid, _ = self._make_pill_group(body, self.quick_filter_var, opts, cols=3)
            grid.pack(fill=tk.X)

        return outer, canvas

    def _create_sort_options_tab(self, parent):
        tp = self.theme_provider
        outer, canvas, container = self._make_scrollable(parent)

        self.sort_var = tk.StringVar(value='name_asc')
        sort_opts = dict(self.manager.get_sort_options())

        categories = {
            'Name':       ['name_asc', 'name_desc'],
            'Date':       ['date_modified_desc', 'date_modified_asc', 'date_created_desc', 'date_created_asc'],
            'Size':       ['size_desc', 'size_asc'],
            'Duration':   ['duration_desc', 'duration_asc'],
            'Resolution': ['resolution_desc', 'resolution_asc'],
            'Playback':   ['play_count_desc', 'play_count_asc', 'last_played_desc', 'last_played_asc', 'watch_time_desc'],
            'Other':      ['random'],
        }

        for cat_title, keys in categories.items():
            opts = [(k, sort_opts[k]) for k in keys if k in sort_opts]
            if not opts:
                continue
            body = self._make_section(container, cat_title)
            grid, _ = self._make_pill_group(body, self.sort_var, opts, cols=3)
            grid.pack(fill=tk.X)

        return outer, canvas

    def _create_advanced_filters_tab(self, parent):
        tp = self.theme_provider
        outer, canvas, container = self._make_scrollable(parent)

        # File Size
        size_body = self._make_section(container, "File Size")
        size_row = tk.Frame(size_body, bg=tp.bg_color)
        size_row.pack(fill=tk.X)
        tk.Label(size_row, text="Minimum (MB)", font=tp.small_font, bg=tp.bg_color, fg=tp.text_muted, anchor='w').pack(side=tk.LEFT, padx=(0, 6))
        self.min_size_entry = self._make_styled_entry(size_row, width=10)
        self.min_size_entry.pack(side=tk.LEFT, padx=(0, 28))
        tk.Label(size_row, text="Maximum (MB)", font=tp.small_font, bg=tp.bg_color, fg=tp.text_muted, anchor='w').pack(side=tk.LEFT, padx=(0, 6))
        self.max_size_entry = self._make_styled_entry(size_row, width=10)
        self.max_size_entry.pack(side=tk.LEFT)

        # Duration
        dur_body = self._make_section(container, "Duration")
        dur_row = tk.Frame(dur_body, bg=tp.bg_color)
        dur_row.pack(fill=tk.X)
        tk.Label(dur_row, text="Minimum (sec)", font=tp.small_font, bg=tp.bg_color, fg=tp.text_muted, anchor='w').pack(side=tk.LEFT, padx=(0, 6))
        self.min_duration_entry = self._make_styled_entry(dur_row, width=10)
        self.min_duration_entry.pack(side=tk.LEFT, padx=(0, 28))
        tk.Label(dur_row, text="Maximum (sec)", font=tp.small_font, bg=tp.bg_color, fg=tp.text_muted, anchor='w').pack(side=tk.LEFT, padx=(0, 6))
        self.max_duration_entry = self._make_styled_entry(dur_row, width=10)
        self.max_duration_entry.pack(side=tk.LEFT)

        # Resolution
        res_body = self._make_section(container, "Resolution")
        self.resolution_vars = {}
        resolutions = ['4K', '2K', '1080p', '720p', '480p', 'SD']
        res_grid = tk.Frame(res_body, bg=tp.bg_color)
        res_grid.pack(fill=tk.X)
        for i, res in enumerate(resolutions):
            var = tk.BooleanVar()
            self.resolution_vars[res] = var
            cell = tk.Frame(res_grid, bg=tp.bg_color)
            cell.grid(row=i // 3, column=i % 3, sticky='w', padx=8, pady=4)
            ttk.Checkbutton(cell, text=res, variable=var, style="Modern.TCheckbutton").pack(anchor='w')

        # Date Modified
        date_body = self._make_section(container, "Date Modified")
        date_row = tk.Frame(date_body, bg=tp.bg_color)
        date_row.pack(fill=tk.X)
        tk.Label(date_row, text="Modified within last (days)", font=tp.small_font, bg=tp.bg_color, fg=tp.text_muted, anchor='w').pack(side=tk.LEFT, padx=(0, 10))
        self.modified_days_entry = self._make_styled_entry(date_row, width=10)
        self.modified_days_entry.pack(side=tk.LEFT)

        # Text Search
        search_body = self._make_section(container, "Text Search", pady=(0, 0))

        fn_row = tk.Frame(search_body, bg=tp.bg_color)
        fn_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(fn_row, text="Filename contains", font=tp.small_font, bg=tp.bg_color, fg=tp.text_muted, width=18, anchor='w').pack(side=tk.LEFT, padx=(0, 8))
        self.filename_search_entry = self._make_styled_entry(fn_row)
        self.filename_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        path_row = tk.Frame(search_body, bg=tp.bg_color)
        path_row.pack(fill=tk.X)
        tk.Label(path_row, text="Path contains", font=tp.small_font, bg=tp.bg_color, fg=tp.text_muted, width=18, anchor='w').pack(side=tk.LEFT, padx=(0, 8))
        self.path_search_entry = self._make_styled_entry(path_row)
        self.path_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        return outer, canvas

    def _create_statistics_tab(self, parent):
        tp = self.theme_provider
        frame = tk.Frame(parent, bg=tp.bg_color)

        container = tk.Frame(frame, bg=tp.bg_color)
        container.pack(fill=tk.BOTH, expand=True, padx=24, pady=20)

        hdr_row = tk.Frame(container, bg=tp.bg_color)
        hdr_row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(hdr_row, text="Collection Statistics", font=tp.header_font, bg=tp.bg_color, fg=tp.text_color).pack(side=tk.LEFT)
        tp.create_modern_button(hdr_row, "↻  Refresh", self._refresh_statistics, "primary", "sm").pack(side=tk.RIGHT)
        tk.Label(
            container,
            text="Detailed statistics about your video collection — size, duration, resolution, and playback data.",
            font=tp.small_font, bg=tp.bg_color, fg=tp.text_muted,
            wraplength=900, justify=tk.LEFT,
        ).pack(anchor='w', pady=(0, 14))

        text_border = tk.Frame(container, bg=tp.border_color, bd=0)
        text_border.pack(fill=tk.BOTH, expand=True)

        self.stats_text = tk.Text(
            text_border,
            wrap=tk.WORD,
            font=tp.normal_font,
            bg=getattr(tp, 'surface_color', tp.bg_color),
            fg=tp.text_color,
            relief=tk.FLAT, bd=0,
            highlightthickness=0,
            padx=16, pady=14,
            state=tk.DISABLED,
        )
        stats_vsb = ttk.Scrollbar(text_border, orient=tk.VERTICAL, command=self.stats_text.yview)
        self.stats_text.configure(yscrollcommand=stats_vsb.set)
        stats_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.stats_text.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.insert(tk.END, "📊  Collection Statistics\n\n", "h1")
        self.stats_text.insert(tk.END, "Click  ↻ Refresh  to analyse your current video selection.\n\n")
        for line in [
            "• Total videos, size, and duration",
            "• Average file size and duration",
            "• Playback statistics",
            "• Resolution distribution",
            "• Codec information",
        ]:
            self.stats_text.insert(tk.END, f"  {line}\n")
        self.stats_text.tag_configure("h1", font=("Segoe UI", 13, "bold"), foreground=tp.accent_color)
        self.stats_text.config(state=tk.DISABLED)

        return frame

    # ── Actions ────────────────────────────────────────────────────────────────

    def _reset_filters(self):
        self.quick_filter_var.set('all')
        self.sort_var.set('name_asc')
        self.min_size_entry.delete(0, tk.END)
        self.max_size_entry.delete(0, tk.END)
        self.min_duration_entry.delete(0, tk.END)
        self.max_duration_entry.delete(0, tk.END)
        self.modified_days_entry.delete(0, tk.END)
        self.filename_search_entry.delete(0, tk.END)
        self.path_search_entry.delete(0, tk.END)
        for var in self.resolution_vars.values():
            var.set(False)
        for refresh in self._tile_refreshers:
            refresh()

    def _apply_filters(self):
        quick_filter_key = self.quick_filter_var.get()
        self.manager.apply_quick_filter(quick_filter_key)

        if quick_filter_key == 'all':
            filter_criteria = self.manager.current_filter

            try:
                min_size = self.min_size_entry.get().strip()
                if min_size:
                    filter_criteria.min_size_mb = float(min_size)
            except ValueError:
                pass
            try:
                max_size = self.max_size_entry.get().strip()
                if max_size:
                    filter_criteria.max_size_mb = float(max_size)
            except ValueError:
                pass
            try:
                min_dur = self.min_duration_entry.get().strip()
                if min_dur:
                    filter_criteria.min_duration_seconds = float(min_dur)
            except ValueError:
                pass
            try:
                max_dur = self.max_duration_entry.get().strip()
                if max_dur:
                    filter_criteria.max_duration_seconds = float(max_dur)
            except ValueError:
                pass

            filter_criteria.resolution_categories = [r for r, v in self.resolution_vars.items() if v.get()]

            try:
                mod_days = self.modified_days_entry.get().strip()
                if mod_days:
                    filter_criteria.modified_within_days = int(mod_days)
            except ValueError:
                pass

            filter_criteria.filename_contains = self.filename_search_entry.get().strip()
            filter_criteria.path_contains     = self.path_search_entry.get().strip()

        self.manager.set_sort(self.sort_var.get())
        self.filter_window.destroy()
        if self.on_apply_callback:
            self.on_apply_callback()

    def _refresh_statistics(self):
        tp = self.theme_provider
        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.delete(1.0, tk.END)
        self.stats_text.insert(tk.END, "Calculating statistics…\n\n")
        self.stats_text.config(state=tk.DISABLED)

        def calculate_stats():
            try:
                if hasattr(self.parent, 'master') and hasattr(self.parent.master, 'get_all_videos_for_statistics'):
                    video_paths = self.parent.master.get_all_videos_for_statistics()
                else:
                    video_paths = self._get_videos_from_app()

                if not video_paths:
                    def show_no_videos():
                        self.stats_text.config(state=tk.NORMAL)
                        self.stats_text.delete(1.0, tk.END)
                        self.stats_text.insert(tk.END, "No videos found.\n\n")
                        self.stats_text.insert(tk.END, "Please select a directory with videos first.")
                        self.stats_text.config(state=tk.DISABLED)
                    self.parent.after(0, show_no_videos)
                    return

                stats = self.manager.get_video_statistics(video_paths)

                def display_stats():
                    self.stats_text.config(state=tk.NORMAL)
                    self.stats_text.delete(1.0, tk.END)

                    self.stats_text.insert(tk.END, "📊  COLLECTION OVERVIEW\n", "h1")
                    self.stats_text.insert(tk.END, "─" * 60 + "\n\n", "div")
                    self.stats_text.insert(tk.END, f"  Total Videos       {stats['total_videos']}\n", "stat")
                    self.stats_text.insert(tk.END, f"  Total Size         {stats['total_size_gb']:.2f} GB\n", "stat")
                    self.stats_text.insert(tk.END, f"  Total Duration     {stats['total_duration_hours']:.2f} hours\n\n", "stat")

                    self.stats_text.insert(tk.END, "📈  AVERAGES\n", "h1")
                    self.stats_text.insert(tk.END, "─" * 60 + "\n\n", "div")
                    self.stats_text.insert(tk.END, f"  Average File Size  {stats['avg_size_mb']:.2f} MB\n", "stat")
                    self.stats_text.insert(tk.END, f"  Average Duration   {stats['avg_duration_minutes']:.2f} min\n\n", "stat")

                    self.stats_text.insert(tk.END, "🎬  PLAYBACK\n", "h1")
                    self.stats_text.insert(tk.END, "─" * 60 + "\n\n", "div")
                    played_percent = (stats['played_count'] / stats['total_videos'] * 100) if stats['total_videos'] > 0 else 0
                    self.stats_text.insert(tk.END, f"  Played             {stats['played_count']}\n", "stat")
                    self.stats_text.insert(tk.END, f"  Never Played       {stats['never_played_count']}\n", "stat")
                    self.stats_text.insert(tk.END, f"  Played %           {played_percent:.1f}%\n\n", "stat")

                    self.stats_text.insert(tk.END, "📺  RESOLUTION\n", "h1")
                    self.stats_text.insert(tk.END, "─" * 60 + "\n\n", "div")
                    res_dist = stats['resolution_distribution']
                    if res_dist:
                        for res, count in sorted(res_dist.items(), key=lambda x: x[1], reverse=True):
                            pct = (count / stats['total_videos'] * 100) if stats['total_videos'] > 0 else 0
                            self.stats_text.insert(tk.END, f"  {res:<12} {count:>6} videos   ({pct:.1f}%)\n", "stat")
                    else:
                        self.stats_text.insert(tk.END, "  No resolution data available\n", "muted")
                    self.stats_text.insert(tk.END, "\n")

                    self.stats_text.insert(tk.END, "🎞️  CODECS\n", "h1")
                    self.stats_text.insert(tk.END, "─" * 60 + "\n\n", "div")
                    codec_dist = stats['codec_distribution']
                    if codec_dist:
                        for codec, count in sorted(codec_dist.items(), key=lambda x: x[1], reverse=True)[:5]:
                            if codec and codec != "unknown":
                                pct = (count / stats['total_videos'] * 100) if stats['total_videos'] > 0 else 0
                                self.stats_text.insert(tk.END, f"  {codec:<12} {count:>6} videos   ({pct:.1f}%)\n", "stat")
                    else:
                        self.stats_text.insert(tk.END, "  No codec data available\n", "muted")

                    self.stats_text.tag_configure("h1",   font=("Segoe UI", 11, "bold"), foreground=tp.accent_color, spacing1=6)
                    self.stats_text.tag_configure("div",  foreground=tp.text_muted)
                    self.stats_text.tag_configure("stat", font=("Consolas", 10),         foreground=tp.text_color)
                    self.stats_text.tag_configure("muted",                                foreground=tp.text_muted)
                    self.stats_text.config(state=tk.DISABLED)

                self.parent.after(0, display_stats)

            except Exception as e:
                def show_error():
                    self.stats_text.config(state=tk.NORMAL)
                    self.stats_text.delete(1.0, tk.END)
                    self.stats_text.insert(tk.END, f"Error calculating statistics:\n\n{str(e)}\n\n")
                    self.stats_text.insert(tk.END, "Please make sure you have selected a directory with videos.")
                    self.stats_text.config(state=tk.DISABLED)
                self.parent.after(0, show_error)

        threading.Thread(target=calculate_stats, daemon=True).start()

    def _get_videos_from_app(self):
        try:
            if hasattr(self, 'app_instance'):
                return self.app_instance.get_all_videos_for_statistics()
            if hasattr(self.theme_provider, 'get_all_videos_for_statistics'):
                return self.theme_provider.get_all_videos_for_statistics()
            root = self.parent
            attempts = 0
            while root and attempts < 10:
                if hasattr(root, 'get_all_videos_for_statistics'):
                    return root.get_all_videos_for_statistics()
                if hasattr(root, 'master'):
                    root = root.master
                else:
                    break
                attempts += 1
        except Exception as e:
            print(f"Error getting videos from app: {e}")
        return []