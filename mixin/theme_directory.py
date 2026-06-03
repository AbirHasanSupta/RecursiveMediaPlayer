import tkinter as tk
from tkinter import ttk


class ThemeDirectoryMixin:
    def update_all_buttons(self):
        suffixes = ('_button', '_btn')
        for attr_name in dir(self):
            if not any(attr_name.endswith(s) for s in suffixes):
                continue
            if not hasattr(self, attr_name):
                continue
            button = getattr(self, attr_name)
            if not isinstance(button, tk.Button):
                continue
            variant = getattr(button, '_variant', None)
            if variant is None:
                text = button.cget('text').lower()
                if 'exclude' in text and 'all' in text:   variant = 'warning'
                elif 'exclude' in text:                    variant = 'danger'
                elif 'include' in text:                    variant = 'success'
                elif 'play'    in text:                    variant = 'danger'
                elif 'add'     in text:                    variant = 'primary'
                elif 'playlist' in text:                   variant = 'playlist'
                elif 'history'  in text:                   variant = 'history'
                elif 'settings' in text:                   variant = 'settings'
                else:                                      variant = 'secondary'
            colors = self.get_button_colors(variant)
            button.configure(bg=colors['bg'], fg=colors['fg'], activebackground=colors['active'])
            self._bind_button_hover(button, variant)

        for manager_ui in getattr(self, '_manager_uis', []):
            try:
                for attr_name in dir(manager_ui):
                    if not any(attr_name.endswith(s) for s in suffixes):
                        continue
                    button = getattr(manager_ui, attr_name, None)
                    if not isinstance(button, tk.Button):
                        continue
                    variant = getattr(button, '_variant', 'secondary')
                    colors  = self.get_button_colors(variant)
                    button.configure(bg=colors['bg'], fg=colors['fg'], activebackground=colors['active'])
                    self._bind_button_hover(button, variant)
            except Exception:
                pass

    def _bind_button_hover(self, button, variant):
        def on_enter(_e, v=variant):
            colors = self.get_button_colors(v)
            button.configure(bg=colors['active'])

        def on_leave(_e, v=variant):
            colors = self.get_button_colors(v)
            button.configure(bg=colors['bg'])

        button.bind("<Enter>", on_enter)
        button.bind("<Leave>", on_leave)

    def _configure_directory_ttk_styles(self):
        self._configure_directory_tree_style()
        self._configure_directory_scrollbar_style()

    def _configure_directory_tree_style(self):
        """Native tree look with forced dashboard background colors."""
        try:
            style = ttk.Style()
            native = self._ensure_ttk_native_theme()
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass

            tree_bg = self.listbox_bg
            tree_fg = self.listbox_fg
            style.configure(
                "ExclusionTree.Treeview",
                background=tree_bg,
                foreground=tree_fg,
                fieldbackground=tree_bg,
                rowheight=32,
                borderwidth=0,
                relief="flat",
            )
            if hasattr(self, 'tree_font'):
                style.configure("ExclusionTree.Treeview", font=self.tree_font)

            style.map(
                "ExclusionTree.Treeview",
                background=[("selected", self.listbox_select_bg)],
                foreground=[("selected", "#FFFFFF")],
                fieldbackground=[("!disabled", tree_bg), ("disabled", tree_bg)],
            )
            try:
                style.element_create("ExclusionTree.customfield", "from", "default", "field")
                style.layout("ExclusionTree.Treeview", [
                    ("ExclusionTree.customfield", {
                        "sticky": "nswe",
                        "border": "2",
                        "children": [
                            ("ExclusionTree.Treeview.padding", {
                                "sticky": "nswe",
                                "children": [
                                    ("ExclusionTree.Treeview.treearea", {"sticky": "nswe"})
                                ]
                            })
                        ]
                    })
                ])
            except tk.TclError:
                pass
            style.configure(
                "ExclusionTree.Treeview.Heading",
                background=self.surface_color,
                foreground=self.text_color,
                relief="flat",
                borderwidth=0,
                font=("Segoe UI", 9, "bold"),
            )
            style.map(
                "ExclusionTree.Treeview.Heading",
                background=[
                    ("active", self.surface_color),
                    ("pressed", self.surface_color),
                ],
                foreground=[
                    ("active", self.text_color),
                    ("pressed", self.text_color),
                ],
            )

            tree = getattr(self, 'exclusion_tree', None)
            if tree is not None:
                try:
                    tree.configure(style="ExclusionTree.Treeview")
                except tk.TclError:
                    pass

            container = getattr(self, 'dir_tree_container', None)
            if container is not None:
                try:
                    container.configure(
                        bg=tree_bg,
                        highlightbackground=self.border_color,
                        highlightthickness=1,
                    )
                except tk.TclError:
                    pass

            self._configure_directory_tree_tags()
        except Exception:
            pass

    def _configure_directory_tree_tags(self):
        """Row tags: excluded dirs (italic/red), excluded videos (italic strike), favourites (yellow)."""
        tree = getattr(self, 'exclusion_tree', None)
        if tree is None:
            return
        try:
            excl_fg = getattr(self, 'excluded_color', self.accent_secondary)
            fav_fg = getattr(self, 'favorite_color', "#F5C518")
            normal_fg = self.listbox_fg
            muted_fg = self.text_muted

            italic = getattr(self, 'tree_font_italic', None)
            excl_video_font = getattr(self, 'tree_font_excl_video', None)
            bold = getattr(self, 'tree_font_bold', None)
            if italic is None and hasattr(self, 'tree_font'):
                from tkinter.font import Font
                fam = self.tree_font.actual().get("family", "Segoe UI")
                size = self.tree_font.actual().get("size", 10)
                italic = Font(family=fam, size=size, slant="italic")
            if excl_video_font is None and italic is not None:
                from tkinter.font import Font
                fam = italic.actual().get("family", "Segoe UI")
                size = italic.actual().get("size", 10)
                excl_video_font = Font(family=fam, size=size, slant="italic", overstrike=True)

            tree.tag_configure("folder", foreground=normal_fg)
            tree.tag_configure(
                "folder_excl",
                foreground=excl_fg,
                font=italic,
            )
            tree.tag_configure("video", foreground=normal_fg)
            tree.tag_configure(
                "video_excl",
                foreground=excl_fg,
                font=excl_video_font,
            )
            tree.tag_configure("video_fav", foreground=fav_fg)
            tree.tag_configure(
                "video_fav_excl",
                foreground=fav_fg,
                font=excl_video_font,
            )
            tree.tag_configure(
                "now_playing",
                foreground=self.accent_color,
                font=bold,
            )
            tree.tag_configure("placeholder", foreground=muted_fg)
            tree.tag_configure("drag_indicator", foreground=self.accent_color)
            tree.tag_configure("rating_star", foreground=fav_fg)
            tree.tag_configure("hover", background=self.hover_color)
        except tk.TclError:
            pass

    def _configure_directory_scrollbar_style(self):
        """Scrollbar only: clam layout/colors copied into the native ttk theme."""
        try:
            style = ttk.Style()
            native = self._ensure_ttk_native_theme()
            trough = self.bg_color if self.dark_mode else self.alt_row_color
            scroll_bg = self.border_color
            scroll_active = self.hover_color
            scroll_style = "ExclusionTree.Vertical.TScrollbar"
            scroll_opts = dict(
                background=scroll_bg,
                troughcolor=trough,
                bordercolor=self.border_color,
                arrowcolor=self.text_muted,
                darkcolor=self.border_color,
                lightcolor=self.surface_color,
                relief="flat",
                gripcount=0,
            )
            scroll_map = dict(
                background=[
                    ("active", scroll_active),
                    ("pressed", self.accent_color),
                    ("disabled", scroll_bg),
                ],
                arrowcolor=[("active", self.text_color), ("pressed", "#FFFFFF")],
            )

            layout = None
            try:
                style.theme_use("clam")
                style.configure(scroll_style, **scroll_opts)
                style.map(scroll_style, **scroll_map)
                try:
                    layout = style.layout(scroll_style)
                except tk.TclError:
                    layout = None
            except tk.TclError:
                pass
            finally:
                try:
                    style.theme_use("clam")
                except tk.TclError:
                    pass

            if layout:
                try:
                    style.layout(scroll_style, layout)
                except tk.TclError:
                    pass
            style.configure(scroll_style, **scroll_opts)
            style.map(scroll_style, **scroll_map)

            scrollbar = getattr(self, 'exclusion_scrollbar', None)
            if scrollbar is not None:
                try:
                    scrollbar.configure(style=scroll_style)
                except tk.TclError:
                    pass
                try:
                    scrollbar.configure(
                        bg=scroll_bg,
                        troughcolor=trough,
                        activebackground=scroll_active,
                        highlightbackground=trough,
                        highlightthickness=0,
                        bd=0,
                    )
                except tk.TclError:
                    pass
        except Exception:
            pass

    def _create_sidebar_icon_btn(self, parent, icon, command, tooltip=None):
        btn = tk.Label(
            parent, text=icon,
            bg=self.surface_color, fg=self.text_color,
            font=("Segoe UI", 15, "bold"), anchor="center",
            pady=10, cursor="hand2",
            relief=tk.FLAT, bd=0, highlightthickness=0,
        )
        btn._sb_command = command

        def on_enter(_e):
            btn.config(bg=self.accent_color, fg="#ffffff")
        def on_leave(_e):
            btn.config(bg=self.surface_color, fg=self.text_color)
        def on_click(_e):
            btn.config(bg=self.accent_color, fg="#ffffff")
            if command:
                btn.after(80, command)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        btn.bind("<Button-1>", on_click)

        if tooltip:
            import tkinter as _tk
            _tip_win = [None]
            def _show_tip(e):
                if _tip_win[0]: return
                x = btn.winfo_rootx() + btn.winfo_width() + 6
                y = btn.winfo_rooty() + 4
                tw = _tk.Toplevel(btn)
                tw.wm_overrideredirect(True)
                tw.wm_geometry(f"+{x}+{y}")
                _tk.Label(tw, text=tooltip, bg=self.console_bg, fg=self.console_fg,
                          font=("Segoe UI", 9), padx=8, pady=4, relief="flat").pack()
                _tip_win[0] = tw
            def _hide_tip(e):
                if _tip_win[0]:
                    try: _tip_win[0].destroy()
                    except: pass
                    _tip_win[0] = None
            btn.bind("<Enter>", lambda e: (_show_tip(e), on_enter(e)))
            btn.bind("<Leave>", lambda e: (_hide_tip(e), on_leave(e)))

        return btn

    def _create_dir_rail_icon_btn(self, parent, icon, command, variant="primary"):
        return self._create_sidebar_icon_btn(parent, icon, command)

    def _style_sidebar(self):
        panel = getattr(self, '_sidebar_panel', None)
        if panel is None:
            return
        try:
            panel.configure(bg=self.surface_color)
            divider = getattr(self, '_sidebar_divider', None)
            if divider:
                divider.configure(bg=self.border_color)
            play_btn = getattr(self, 'play_toolbar_btn', None)
            theme_btn = getattr(self, 'theme_toolbar_btn', None)
            for child in panel.winfo_children():
                try:
                    if isinstance(child, tk.Frame):
                        child.configure(bg=self.border_color)
                    elif isinstance(child, tk.Label):
                        if child is play_btn:
                            child.configure(bg=self.surface_color, fg=self.accent_secondary)
                        elif child is theme_btn:
                            child.configure(bg=self.surface_color, fg=self.text_color)
                        else:
                            child.configure(bg=self.surface_color, fg=self.text_color)
                except tk.TclError:
                    pass
        except tk.TclError:
            pass

    def _style_directory_compact_rail(self):
        self._style_sidebar()

    def _restyle_frame_subtree(self, widget, skip_toolbar=False):
        if skip_toolbar and hasattr(self, 'toolbar'):
            try:
                if widget is self.toolbar or self._is_toolbar_descendant(widget):
                    return
            except Exception:
                pass
        try:
            if isinstance(widget, (tk.Frame, tk.Toplevel)):
                if widget is getattr(self, '_global_search_wrap', None):
                    widget.configure(bg=self.entry_bg, highlightbackground=self.entry_border)
                else:
                    widget.configure(bg=self.bg_color)
            elif isinstance(widget, tk.Entry):
                if widget is getattr(self, 'global_search_entry', None):
                    widget.configure(bg=self.entry_bg, fg=self.entry_fg, insertbackground=self.accent_color)
            elif isinstance(widget, tk.Label):
                if widget is getattr(self, 'global_search_icon', None):
                    widget.configure(bg=self.entry_bg, fg=self.text_muted)
                elif widget is getattr(self, 'workspace_context_label', None):
                    widget.configure(bg=self.bg_color, fg=self.muted_fg)
                else:
                    widget.configure(bg=self.bg_color, fg=self.text_color)
            for child in widget.winfo_children():
                self._restyle_frame_subtree(child, skip_toolbar=skip_toolbar)
        except tk.TclError:
            pass

    def _restyle_directory_panel(self):
        section = getattr(self, 'dir_section', None)
        if section is None:
            return

        def _walk(widget):
            try:
                if isinstance(widget, tk.Frame):
                    tree_container = getattr(self, 'dir_tree_container', None)
                    if tree_container is not None and widget is tree_container:
                        widget.configure(
                            bg=self.listbox_bg,
                            highlightbackground=self.border_color,
                            highlightthickness=1,
                        )
                    elif widget.winfo_children() and any(
                            isinstance(c, ttk.Treeview) for c in widget.winfo_children()):
                        widget.configure(
                            bg=self.listbox_bg,
                            highlightbackground=self.border_color,
                            highlightthickness=1,
                        )
                    else:
                        widget.configure(bg=self.bg_color)
                elif isinstance(widget, tk.Label):
                    widget.configure(bg=self.bg_color, fg=self.text_color)
                elif isinstance(widget, tk.Entry):
                    widget.configure(
                        bg=self.entry_bg, fg=self.entry_fg,
                        insertbackground=self.entry_fg,
                        highlightbackground=self.entry_border,
                    )
                for child in widget.winfo_children():
                    _walk(child)
            except tk.TclError:
                pass

        _walk(section)
        self._configure_directory_ttk_styles()
        rail = getattr(self, 'dir_compact_rail', None)
        if rail is not None:
            try:
                rail.configure(bg=self.bg_color)
            except tk.TclError:
                pass
        wrap = getattr(self, '_search_wrap', None)
        if wrap:
            try:
                wrap.configure(bg=self.entry_bg, highlightbackground=self.entry_border)
                icon = getattr(self, '_search_icon', None)
                if icon:
                    icon.configure(bg=self.entry_bg, fg=self.text_muted)
            except tk.TclError:
                pass
        if hasattr(self, '_refresh_dir_action_states'):
            self._refresh_dir_action_states()

    def get_button_colors(self, variant):
        if self.dark_mode:
            variants = {
                "primary": {"bg": "#2D5A8E", "fg": "#FFFFFF", "active": "#1A4070"},
                "success": {"bg": "#2E7D32", "fg": "#FFFFFF", "active": "#1B5E20"},
                "danger": {"bg": "#C62828", "fg": "#FFFFFF", "active": "#B71C1C"},
                "warning": {"bg": "#F57C00", "fg": "#FFFFFF", "active": "#E65100"},
                "secondary": {"bg": "#4A5568", "fg": "#FFFFFF", "active": "#2D3748"},
                "dark": {"bg": "#2D3748", "fg": "#FFFFFF", "active": "#1A202C"},
                "theme": {"bg": "#4A5568", "fg": "#FFFFFF", "active": "#2D3748"},
                "playlist": {"bg": "#6B46C1", "fg": "#FFFFFF", "active": "#553C9A"},
                "history": {"bg": "#3182CE", "fg": "#FFFFFF", "active": "#2B6CB0"},
                "settings": {"bg": "#718096", "fg": "#FFFFFF", "active": "#4A5568"},
            }
        else:
            variants = {
                "primary": {"bg": "#5E81F4", "fg": "#FFFFFF", "active": "#4A6CD4"},
                "success": {"bg": "#38A169", "fg": "#FFFFFF", "active": "#2F855A"},
                "danger": {"bg": "#FF6B6B", "fg": "#FFFFFF", "active": "#E05555"},
                "warning": {"bg": "#ED8936", "fg": "#FFFFFF", "active": "#DD6B20"},
                "secondary": {"bg": "#A0AEC0", "fg": "#FFFFFF", "active": "#718096"},
                "dark": {"bg": "#4A5568", "fg": "#FFFFFF", "active": "#2D3748"},
                "theme": {"bg": "#4A5568", "fg": "#FFFFFF", "active": "#2D3748"},
                "playlist": {"bg": "#9F7AEA", "fg": "#FFFFFF", "active": "#805AD5"},
                "history": {"bg": "#4299E1", "fg": "#FFFFFF", "active": "#3182CE"},
                "settings": {"bg": "#A0AEC0", "fg": "#FFFFFF", "active": "#718096"},
            }
        return variants.get(variant, variants["primary"])

    def update_container_borders(self):
        if hasattr(self, 'dir_frame'):
            for child in self.dir_frame.winfo_children():
                if isinstance(child, tk.Frame) and any(isinstance(x, tk.Listbox) for x in child.winfo_children()):
                    child.configure(bg=self.bg_color,
                                    highlightbackground=self.frame_border, highlightthickness=1)
                    break

        # Exclusion panel now uses Treeview inside a plain Frame container
        if hasattr(self, 'exclusion_frame'):
            for child in self.exclusion_frame.winfo_children():
                if isinstance(child, tk.Frame):
                    child.configure(bg=self.listbox_bg,
                                    highlightbackground=self.frame_border, highlightthickness=1)
                    break

        for child in self.main_frame.winfo_children():
            for subchild in child.winfo_children():
                if isinstance(subchild, tk.Frame):
                    for subsubchild in subchild.winfo_children():
                        if isinstance(subsubchild, tk.Frame) and any(
                                isinstance(x, tk.Text) for x in subsubchild.winfo_children()):
                            subchild.configure(bg=self.bg_color,
                                               highlightbackground=self.frame_border, highlightthickness=1)
                            break

    def update_frames_recursive(self, widget):
        try:
            if hasattr(self, 'toolbar') and (widget is self.toolbar or self._is_toolbar_descendant(widget)):
                return
            if isinstance(widget, (tk.Frame, tk.Toplevel)):
                widget.configure(bg=self.bg_color)
            elif isinstance(widget, tk.Label):
                widget.configure(bg=self.bg_color, fg=self.text_color)
            for child in widget.winfo_children():
                self.update_frames_recursive(child)
        except tk.TclError:
            pass

    def _is_toolbar_descendant(self, widget):
        try:
            w       = widget.master
            toolbar = self.toolbar
            while w is not None:
                if w is toolbar:
                    return True
                w = w.master
        except Exception:
            pass
        return False

