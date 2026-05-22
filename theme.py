import json
import os
import os.path
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import base64


def _get_app_dirs():
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


class ConfigHandler:

    @property
    def config_path(self):
        config_dir, _ = _get_app_dirs()
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "config.json"

    def load_preferences(self):
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r') as f:
                    config = json.load(f)

                    encoded_dirs = config.get('selected_dirs', [])
                    decoded_dirs = []
                    for ed in encoded_dirs:
                        try:
                            decoded_dirs.append(base64.b64decode(ed.encode()).decode())
                        except Exception:
                            pass
                    last_played_encoded = config.get('last_played_video_path', '')
                    try:
                        last_played_path = os.path.normpath(base64.b64decode(last_played_encoded.encode()).decode())
                    except Exception:
                        last_played_path = ''

                    encoded_excluded_subdirs = config.get('excluded_subdirs', {})
                    decoded_excluded_subdirs = {}
                    for encoded_root, encoded_subdirs in encoded_excluded_subdirs.items():
                        try:
                            root_dir = base64.b64decode(encoded_root.encode()).decode()
                            subdirs  = []
                            for encoded_subdir in encoded_subdirs:
                                try:
                                    subdirs.append(base64.b64decode(encoded_subdir.encode()).decode())
                                except Exception:
                                    pass
                            if subdirs:
                                decoded_excluded_subdirs[root_dir] = subdirs
                        except Exception:
                            pass

                    encoded_excluded_videos = config.get('excluded_videos', {})
                    decoded_excluded_videos = {}
                    for encoded_root, encoded_videos in encoded_excluded_videos.items():
                        try:
                            root_dir = base64.b64decode(encoded_root.encode()).decode()
                            videos   = []
                            for encoded_video in encoded_videos:
                                try:
                                    videos.append(base64.b64decode(encoded_video.encode()).decode())
                                except Exception:
                                    pass
                            if videos:
                                decoded_excluded_videos[root_dir] = videos
                        except Exception:
                            pass

                    return {
                        'dark_mode':               config.get('dark_mode', False),
                        'show_videos':             config.get('show_videos', True),
                        'expand_all':              False,
                        'selected_dirs':           decoded_dirs,
                        'save_directories':        True,
                        'start_from_last_played':  config.get('start_from_last_played', False),
                        'last_played_video_index': config.get('last_played_video_index', 0),
                        'last_played_video_path':  last_played_path,
                        'excluded_subdirs':        decoded_excluded_subdirs,
                        'excluded_videos':         decoded_excluded_videos,
                        'smart_resume_enabled':    config.get('smart_resume_enabled', False),
                        'volume':                  config.get('volume', 50),
                        'is_muted':                config.get('is_muted', False),
                        'loop_mode':               config.get('loop_mode', 'loop_on'),
                        'show_console':            config.get('show_console', True),
                    }
        except Exception:
            pass
        return {
            'dark_mode': False, 'show_videos': True, 'expand_all': False,
            'selected_dirs': [], 'save_directories': True,
            'start_from_last_played': False, 'last_played_video_index': 0,
            'last_played_video_path': '', 'excluded_subdirs': {}, 'excluded_videos': {},
            'smart_resume_enabled': False, 'volume': 50, 'is_muted': False,
            'loop_mode': 'loop_on', 'show_console': True,
        }

    def save(self, config_dict):
        try:
            encoded_dirs       = [base64.b64encode(d.encode()).decode() for d in config_dict.get('selected_dirs', [])]
            config_dict        = dict(config_dict)
            config_dict['selected_dirs'] = encoded_dirs
            last_played_path   = config_dict.get('last_played_video_path', '')
            config_dict['last_played_video_path'] = base64.b64encode(last_played_path.encode()).decode()
            with open(self.config_path, 'w') as f:
                json.dump(config_dict, f, indent=2)
        except Exception:
            pass


class ThemeSelector:
    def __init__(self):
        self.config = ConfigHandler()

    def save_preferences(self):
        encoded_excluded_subdirs = {}
        for root_dir, subdirs in getattr(self, 'excluded_subdirs', {}).items():
            encoded_root    = base64.b64encode(root_dir.encode()).decode()
            encoded_subdirs = [base64.b64encode(s.encode()).decode() for s in subdirs]
            encoded_excluded_subdirs[encoded_root] = encoded_subdirs

        encoded_excluded_videos = {}
        for root_dir, videos in getattr(self, 'excluded_videos', {}).items():
            encoded_root   = base64.b64encode(root_dir.encode()).decode()
            encoded_videos = [base64.b64encode(v.encode()).decode() for v in videos]
            encoded_excluded_videos[encoded_root] = encoded_videos

        prefs = {
            'dark_mode':               self.dark_mode,
            'show_videos':             self.show_videos,
            'expand_all':              False,
            'selected_dirs': [
                d for d in getattr(self, 'selected_dirs', [])
                if isinstance(d, str)
                and not d.startswith('gdrive://')
                and not d.startswith('http://')
                and not d.startswith('https://')
            ],
            'save_directories':        True,
            'start_from_last_played':  getattr(self, 'start_from_last_played', False),
            'smart_resume_enabled':    getattr(self, 'smart_resume_enabled', False),
            'last_played_video_index': getattr(self, 'last_played_video_index', 0),
            'last_played_video_path':  getattr(self, 'last_played_video_path', ''),
            'excluded_subdirs':        encoded_excluded_subdirs,
            'excluded_videos':         encoded_excluded_videos,
            'volume':                  getattr(self, 'volume', 50),
            'is_muted':                getattr(self, 'is_muted', False),
            'loop_mode':               getattr(self, 'loop_mode', 'loop_on'),
            'show_console':            getattr(self, 'show_console', True),
        }
        self.config.save(prefs)

    def _apply_menubar_colors(self):
        if not hasattr(self, 'toolbar') or not hasattr(self, '_tb_colors'):
            return
        cc = self._tb_colors()
        self.toolbar.config(bg=cc["bg"])

        for child in self.toolbar.winfo_children():
            if isinstance(child, tk.Label):
                is_play = hasattr(self, 'play_toolbar_btn') and child is self.play_toolbar_btn
                if is_play:
                    self._apply_play_toolbar_idle()
                else:
                    child.config(bg=cc["bg"], fg=cc["fg"])

        def restyle_menu(m):
            try:
                m.configure(
                    bg=cc["bg"], fg=cc["fg"],
                    activebackground=cc["hover"],
                    activeforeground=cc["fg"])
                end = m.index("end")
                if end is not None:
                    for i in range(end + 1):
                        try:
                            sub = m.nametowidget(m.entrycget(i, "menu"))
                            restyle_menu(sub)
                        except Exception:
                            pass
            except Exception:
                pass

        for widget in self.root.winfo_children():
            if isinstance(widget, tk.Menu):
                restyle_menu(widget)

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.save_preferences()
        self.apply_theme()

    def apply_theme(self):
        if self.dark_mode:
            self.bg_color = "#0F1217"
            self.surface_color = "#1A1E26"
            self.accent_color = "#7B9CFF"
            self.accent_secondary = "#FF8A8A"
            self.text_color = "#E2E8F0"
            self.text_muted = "#8A99B5"
            self.border_color = "#2A303C"
            self.hover_color = "#252C38"
            self.listbox_bg = "#1A1E26"
            self.listbox_fg = "#E2E8F0"
            self.listbox_select_bg = "#7B9CFF"
            self.console_bg = "#1A1E26"
            self.console_fg = "#E2E8F0"
            self.entry_bg = "#1A1E26"
            self.entry_fg = "#E2E8F0"
            self.entry_border = "#2A303C"
            self.alt_row_color = "#252C38"
            self.badge_bg = "#2A303C"
            self.badge_fg = "#E2E8F0"
            self.divider_color = "#2A303C"
        else:
            self.bg_color = "#F7F9FC"
            self.surface_color = "#FFFFFF"
            self.accent_color = "#5E81F4"
            self.accent_secondary = "#FF6B6B"
            self.text_color = "#1E2A3A"
            self.text_muted = "#5B6C8F"
            self.border_color = "#E2E8F0"
            self.hover_color = "#EDF2F7"
            self.listbox_bg = "#FFFFFF"
            self.listbox_fg = "#1E2A3A"
            self.listbox_select_bg = "#5E81F4"
            self.console_bg = "#1E2A3A"
            self.console_fg = "#F7F9FC"
            self.entry_bg = "#FFFFFF"
            self.entry_fg = "#1E2A3A"
            self.entry_border = "#E2E8F0"
            self.alt_row_color = "#F7F9FC"
            self.badge_bg = "#EDF2F7"
            self.badge_fg = "#1E2A3A"
            self.divider_color = "#E2E8F0"

        self.muted_fg = self.text_muted
        self.frame_border = self.border_color
        self.header_color = self.text_color
        self.excluded_color = "#C24E4E" if self.dark_mode else "#C44A4A"
        self.favorite_color = "#B8890A" if self.dark_mode else "#8F6B08"

        # Apply colours to root and main frames
        self.root.configure(bg=self.bg_color)
        self.main_frame.configure(bg=self.bg_color)
        self.content_frame.configure(bg=self.bg_color)
        for section in ['dir_section', 'status_frame', 'button_frame']:
            if hasattr(self, section):
                getattr(self, section).configure(bg=self.bg_color)

        # Update labels
        for label_attr in dir(self):
            if label_attr.endswith('_label') and hasattr(self, label_attr):
                label = getattr(self, label_attr)
                if isinstance(label, tk.Label):
                    label.configure(bg=self.bg_color, fg=self.text_color)

        # Directory panel tree + scrollbar (ttk needs explicit styling on Windows)
        if hasattr(self, 'exclusion_tree'):
            self._configure_directory_ttk_styles()
        elif hasattr(self, '_configure_tree_style'):
            self._configure_tree_style()

        # Console
        if hasattr(self, 'console_text'):
            self.console_text.configure(
                bg=self.console_bg, fg=self.console_fg,
                selectbackground="#214283", selectforeground="white",
                insertbackground=self.console_fg,
            )

        # Entries
        for entry_attr in dir(self):
            if entry_attr.endswith('_entry') and hasattr(self, entry_attr):
                entry = getattr(self, entry_attr)
                if isinstance(entry, tk.Entry):
                    entry.configure(
                        bg=self.entry_bg, fg=self.entry_fg,
                        insertbackground=self.entry_fg,
                        highlightbackground=self.entry_border,
                    )

        # Buttons
        self.update_all_buttons()

        self._apply_workspace_chrome_theme()
        self._apply_ttk_chrome_theme()

        # Toolbar and pills
        if hasattr(self, '_fix_toolbar_colors'):
            self._fix_toolbar_colors()
        if hasattr(self, '_refresh_media_pill_state'):
            self._refresh_media_pill_state()

        self._apply_menubar_colors()

        # Reload home dashboard if visible
        if getattr(self, '_active_app_view', None) == 'home':
            if hasattr(self, 'exclusion_section') and self.exclusion_section.winfo_ismapped():
                self.exclusion_section.pack_forget()
            self._render_home_dashboard()


    def _get_loop_icon(self):
        icons = {"loop_on": "⟳  ON", "loop_off": "→ OFF", "shuffle": "⤨ RND"}
        return icons.get(self.loop_mode, "⟳  ON")

    def _get_loop_tooltip(self):
        tooltips = {
            "loop_on":  "Loop: ON - Videos will repeat",
            "loop_off": "Loop: OFF - Play once then stop",
            "shuffle":  "Shuffle: ON - Random playback",
        }
        return tooltips.get(self.loop_mode, "")

    def toggle_loop_mode(self):
        modes         = ["loop_on", "loop_off", "shuffle"]
        current_index = modes.index(self.loop_mode)
        self.loop_mode = modes[(current_index + 1) % len(modes)]
        if hasattr(self, 'loop_toggle_button'):
            self.loop_toggle_button.config(text=self._get_loop_icon())
        if self.controller:
            self.controller.set_loop_mode(self.loop_mode)
        mode_names = {"loop_on": "Loop ON", "loop_off": "Loop OFF", "shuffle": "Shuffle ON"}
        self.update_console(f"Playback mode: {mode_names[self.loop_mode]}")
        self.save_preferences()

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

    def _ensure_ttk_native_theme(self):
        native = getattr(self, '_ttk_native_theme', None)
        if native:
            return native
        style = ttk.Style()
        names = style.theme_names()
        if 'vista' in names:
            native = 'vista'
        elif 'xpnative' in names:
            native = 'xpnative'
        else:
            native = 'default'
        self._ttk_native_theme = native
        return native

    def _configure_directory_ttk_styles(self):
        self._configure_directory_tree_style()
        self._configure_directory_scrollbar_style()

    def _configure_directory_tree_style(self):
        """Native tree look with forced dashboard background colors."""
        try:
            style = ttk.Style()
            native = self._ensure_ttk_native_theme()
            try:
                style.theme_use(native)
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
                    style.theme_use(native)
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
        except Exception:
            pass

    def _apply_ttk_chrome_theme(self):
        try:
            style = ttk.Style()
            style.configure("TFrame", background=self.bg_color)
            style.configure("TLabel", background=self.bg_color, foreground=self.text_color)
            style.configure(
                "Modern.TCheckbutton",
                background=self.bg_color,
                foreground=self.text_color,
                font=("Segoe UI", 10),
                padding=4,
            )
            style.map(
                "Modern.TCheckbutton",
                foreground=[("active", self.text_color), ("disabled", self.text_muted)],
                background=[("active", self.bg_color)],
            )
        except Exception:
            pass

    def _apply_workspace_chrome_theme(self):
        frame_names = (
            'workspace_frame', 'workspace_header', 'workspace_body', 'workspace_nav',
            'content_frame', 'dir_section', 'dir_compact_rail', 'dir_frame',
            'exclusion_buttons_frame', 'embedded_view_frame', 'console_section',
        )
        for name in frame_names:
            widget = getattr(self, name, None)
            if widget is not None:
                try:
                    widget.configure(bg=self.bg_color)
                except tk.TclError:
                    pass

        for name in ('workspace_title_label', 'dir_header_label'):
            label = getattr(self, name, None)
            if isinstance(label, tk.Label):
                label.configure(bg=self.bg_color, fg=self.text_color)

        context = getattr(self, 'workspace_context_label', None)
        if isinstance(context, tk.Label):
            context.configure(bg=self.bg_color, fg=self.muted_fg)

        header = getattr(self, 'workspace_header', None)
        if header is not None:
            self._restyle_frame_subtree(header, skip_toolbar=False)

        if hasattr(self, 'dir_section'):
            self._restyle_directory_panel()

        if hasattr(self, 'embedded_view_frame') and self.embedded_view_frame is not None:
            try:
                if self.embedded_view_frame.winfo_exists():
                    self.embedded_view_frame.configure(bg=self.bg_color)
            except tk.TclError:
                pass

        self.update_container_borders()
        self._style_directory_compact_rail()

    def _pointer_over_widget(self, widget):
        try:
            if not widget.winfo_exists():
                return False
            px, py = widget.winfo_pointerxy()
            wx, wy = widget.winfo_rootx(), widget.winfo_rooty()
            return wx <= px <= (wx + widget.winfo_width()) and wy <= py <= (wy + widget.winfo_height())
        except tk.TclError:
            return False

    def _play_toolbar_font_idle(self):
        from tkinter.font import Font
        return Font(family="Segoe UI", size=10, weight="bold", underline=False)

    def _play_toolbar_font_hover(self):
        from tkinter.font import Font
        return Font(family="Segoe UI", size=10, weight="bold", underline=True)

    def _play_toolbar_font_active(self):
        from tkinter.font import Font
        return Font(family="Segoe UI", size=10, weight="bold", underline=False)

    def _ensure_play_toolbar_fonts(self):
        """Legacy helper for initial widget creation in build_app."""
        if not getattr(self, '_play_toolbar_fonts_ready', False):
            self._play_toolbar_font = self._play_toolbar_font_idle()
            self._play_toolbar_fonts_ready = True

    def _apply_play_toolbar_idle(self):
        btn = getattr(self, 'play_toolbar_btn', None)
        if btn is None or not hasattr(self, '_tb_colors'):
            return
        c = self._tb_colors()
        btn.config(bg=c["bg"], fg=c["play_text"], font=self._play_toolbar_font_idle())

    def _apply_play_toolbar_hover(self):
        btn = getattr(self, 'play_toolbar_btn', None)
        if btn is None or not hasattr(self, '_tb_colors'):
            return
        c = self._tb_colors()
        btn.config(bg=c["bg"], fg=c["play_text_hover"], font=self._play_toolbar_font_hover())

    def _restore_play_toolbar_after_click(self):
        """Re-apply hover or idle after click; run deferred so Leave is processed first."""
        btn = getattr(self, 'play_toolbar_btn', None)
        if btn is None:
            return
        if self._pointer_over_widget(btn):
            self._apply_play_toolbar_hover()
        else:
            self._apply_play_toolbar_idle()

    def _sync_play_toolbar_btn(self):
        self._restore_play_toolbar_after_click()

    def _create_dir_rail_icon_btn(self, parent, icon, command, variant="primary"):
        colors = self.get_button_colors(variant)
        btn = tk.Label(
            parent, text=icon,
            bg=colors["bg"], fg=colors["fg"],
            font=("Segoe UI", 13, "bold" if variant == "primary" else "normal"),
            width=2, height=1,
            padx=12, pady=11,
            cursor="hand2",
            relief=tk.FLAT, bd=0,
        )
        btn._rail_variant = variant

        def on_enter(_e, v=variant):
            c = self.get_button_colors(v)
            btn.configure(bg=c["active"])

        def on_leave(_e, v=variant):
            c = self.get_button_colors(v)
            btn.configure(bg=c["bg"])

        def on_press(_e, v=variant):
            c = self.get_button_colors(v)
            btn.configure(bg=c["active"])

        def on_release(_e):
            c = self.get_button_colors(btn._rail_variant)
            btn.configure(bg=c["active"] if self._pointer_over_widget(btn) else c["bg"])
            if command:
                command()

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        btn.bind("<ButtonPress-1>", on_press)
        btn.bind("<ButtonRelease-1>", on_release)
        return btn

    def _style_directory_compact_rail(self):
        rail = getattr(self, 'dir_compact_rail', None)
        if rail is None:
            return
        try:
            rail.configure(bg=self.bg_color, width=52)
            card = getattr(self, 'dir_rail_card', None)
            if card is not None:
                card.configure(
                    bg=self.surface_color,
                    highlightbackground=self.border_color,
                    highlightthickness=1,
                )
            sep = getattr(self, 'dir_rail_sep', None)
            if sep is not None:
                sep.configure(bg=self.border_color)
            for attr in ('dir_rail_add_btn', 'dir_rail_expand_btn'):
                btn = getattr(self, attr, None)
                if btn is None:
                    continue
                variant = getattr(btn, '_rail_variant', 'secondary')
                colors = self.get_button_colors(variant)
                btn.configure(bg=colors["bg"], fg=colors["fg"])
        except tk.TclError:
            pass

    def _restyle_frame_subtree(self, widget, skip_toolbar=False):
        if skip_toolbar and hasattr(self, 'toolbar'):
            try:
                if widget is self.toolbar or self._is_toolbar_descendant(widget):
                    return
            except Exception:
                pass
        try:
            if isinstance(widget, (tk.Frame, tk.Toplevel)):
                widget.configure(bg=self.bg_color)
            elif isinstance(widget, tk.Label):
                if widget is getattr(self, 'workspace_context_label', None):
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

    def register_manager_ui(self, manager_ui):
        if not hasattr(self, '_manager_uis'):
            self._manager_uis = []
        if manager_ui not in self._manager_uis:
            self._manager_uis.append(manager_ui)

    def _apply_theme_to_toplevels(self):
        for manager_ui in getattr(self, '_manager_uis', []):
            try:
                window = None
                for attr in ('favorites_window', 'queue_window', 'history_window', 'playlist_window'):
                    w = getattr(manager_ui, attr, None)
                    if w and w.winfo_exists():
                        window = w
                        break
                if window is None:
                    continue
                window.configure(bg=self.bg_color)
                self._restyle_toplevel(window)
            except Exception:
                pass

    def _restyle_toplevel(self, window):
        def _walk(widget):
            try:
                if isinstance(widget, tk.Button) and hasattr(widget, '_variant'):
                    colors = self.get_button_colors(widget._variant)
                    widget.configure(bg=colors['bg'], fg=colors['fg'], activebackground=colors['active'])
                    self._bind_button_hover(widget, widget._variant)
                    return

                if isinstance(widget, tk.Frame) and getattr(widget, '_accent', False):
                    for child in widget.winfo_children():
                        _walk(child)
                    return

                if isinstance(widget, tk.Frame) and getattr(widget, '_card', False):
                    widget.configure(bg=self.listbox_bg, highlightbackground=self.frame_border)
                    for child in widget.winfo_children():
                        _walk(child)
                    return

                if isinstance(widget, tk.Frame):
                    widget.configure(bg=self.bg_color)

                if isinstance(widget, tk.Label):
                    if getattr(widget, '_muted', False):
                        widget.configure(bg=self.bg_color, fg=self.muted_fg)
                    elif getattr(widget, '_badge', False):
                        widget.configure(bg=self.badge_bg, fg=self.badge_fg)
                    else:
                        widget.configure(bg=self.bg_color, fg=self.text_color)

                if isinstance(widget, tk.Listbox):
                    widget.configure(
                        bg=self.listbox_bg, fg=self.listbox_fg,
                        selectbackground=self.listbox_select_bg,
                    )

                if isinstance(widget, tk.Entry):
                    widget.configure(
                        bg=self.entry_bg, fg=self.entry_fg,
                        insertbackground=self.entry_fg,
                        highlightbackground=self.entry_border,
                    )

                if isinstance(widget, tk.Text):
                    widget.configure(bg=self.entry_bg, fg=self.entry_fg, insertbackground=self.entry_fg)

                if isinstance(widget, ttk.Treeview):
                    style_name = widget.cget("style") or "Treeview"
                    s = ttk.Style()
                    s.configure(style_name,
                                background=self.listbox_bg,
                                fieldbackground=self.listbox_bg,
                                foreground=self.listbox_fg)
                    s.map(style_name,
                          background=[("selected", self.listbox_select_bg)],
                          foreground=[("selected", "white")])

                for child in widget.winfo_children():
                    _walk(child)

            except tk.TclError:
                pass

        _walk(window)

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

    # ── Toolbar / pill colour palette ─────────────────────────────────────────
    PILL_ACCENTS_LIGHT = {
        "Home":           ("#4a5568", "#d7dde8", "#1a2035", "#c7cfdd"),
        "Gallery":        ("#2d7ef7", "#1a6de8", "#FFFFFF", "#1557bd"),
        "🎵 Playlist":   ("#5B9BD5", "#1a5fa8", "#FFFFFF", "#144d8a"),
        "⬛ Queue":      ("#2ecc71", "#1a8a4a", "#FFFFFF", "#156e3a"),
        "♥ Favourites": ("#e67e22", "#b35a00", "#FFFFFF", "#8a4400"),
        "🕐 History":   ("#9b59b6", "#6c2f8f", "#FFFFFF", "#521f6e"),
        "🏷 Tags & Ratings": ("#c8a000", "#8a6d0a", "#FFFFFF", "#5a4600"),
    }
    PILL_ACCENTS_DARK = {
        "Home":           ("#A9B7C6", "#343a46", "#FFFFFF", "#2b303a"),
        "Gallery":        ("#5b9cf6", "#2D5A8E", "#FFFFFF", "#1A4070"),
        "🎵 Playlist":   ("#4A9EFF", "#1a5fa8", "#FFFFFF", "#144d8a"),
        "⬛ Queue":      ("#2ecc71", "#1a8a4a", "#FFFFFF", "#156e3a"),
        "♥ Favourites": ("#FF9F43", "#b35a00", "#FFFFFF", "#8a4400"),
        "🕐 History":   ("#C39BD3", "#6c2f8f", "#FFFFFF", "#521f6e"),
        "🏷 Tags & Ratings": ("#f5c518", "#b8920f", "#FFFFFF", "#8a6d0a"),
    }

    def pill_accents(self, lbl):
        return (self.PILL_ACCENTS_DARK if self.dark_mode else self.PILL_ACCENTS_LIGHT)[lbl]

    def _active_tab_label(self):
        return getattr(self, '_view_tab_labels', {}).get(
            getattr(self, '_active_app_view', 'home'), 'Home')

    def _bind_toolbar_label_hover(self, btn, play=False, menu=None, command=None):
        def on_enter(_e):
            c = self._tb_colors()
            if play:
                btn.config(bg=c["play_hover_bg"], fg="#FFFFFF")
            else:
                btn.config(bg=c["hover"], fg=c["fg"])

        def on_leave(_e):
            c = self._tb_colors()
            if play:
                btn.config(bg=c["play_fg"], fg="#FFFFFF")
            else:
                btn.config(bg=c["bg"], fg=c["fg"])

        def on_press(_e):
            c = self._tb_colors()
            if play:
                btn.config(bg=c["play_active_bg"], fg="#FFFFFF")
            else:
                btn.config(bg=c["active"], fg="#FFFFFF")

        def on_release(_e):
            c = self._tb_colors()
            if play:
                btn.config(bg=c["play_hover_bg"], fg="#FFFFFF")
            else:
                btn.config(bg=c["hover"], fg=c["fg"])
            if menu is not None:
                try:
                    menu.tk_popup(btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height())
                finally:
                    menu.grab_release()
            elif command is not None:
                command()

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        btn.bind("<ButtonPress-1>", on_press)
        btn.bind("<ButtonRelease-1>", on_release)

    def _bind_theme_toolbar_hover(self):
        btn = getattr(self, 'theme_toolbar_btn', None)
        if btn is None:
            return

        def on_enter(_e):
            c = self._tb_colors()
            btn.config(bg=c["hover"], fg=c["fg"])

        def on_leave(_e):
            c = self._tb_colors()
            btn.config(bg=c["bg"], fg=c["fg"])

        def on_press(_e):
            c = self._tb_colors()
            btn.config(bg=c["active"], fg="#FFFFFF")

        def on_release(_e):
            c = self._tb_colors()
            btn.config(bg=c["hover"], fg=c["fg"])
            self._toggle_theme_menu()

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        btn.bind("<ButtonPress-1>", on_press)
        btn.bind("<ButtonRelease-1>", on_release)

    def _bind_play_toolbar_hover(self):
        btn = getattr(self, 'play_toolbar_btn', None)
        if btn is None:
            return
        self._ensure_play_toolbar_fonts()

        def on_enter(_e):
            self._apply_play_toolbar_hover()

        def on_leave(_e):
            self._apply_play_toolbar_idle()

        def on_press(_e):
            c = self._tb_colors()
            btn.config(
                bg=c["bg"],
                fg=c.get("play_text_active", c["play_text"]),
                font=self._play_toolbar_font_active(),
            )

        def on_release(_e):
            self.global_play()
            btn.after(20, self._restore_play_toolbar_after_click)

        btn.unbind("<Enter>")
        btn.unbind("<Leave>")
        btn.unbind("<ButtonPress-1>")
        btn.unbind("<ButtonRelease-1>")
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        btn.bind("<ButtonPress-1>", on_press)
        btn.bind("<ButtonRelease-1>", on_release)
        self._apply_play_toolbar_idle()

    def _bind_media_pill_hover(self, btn, label):
        def on_enter(_e):
            if label != self._active_tab_label():
                btn.config(bg=self.hover_color, fg=self.accent_color)

        def on_leave(_e):
            if label != self._active_tab_label():
                btn.config(bg=self.bg_color, fg=self.text_muted)

        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)

    def _fix_toolbar_colors(self):
        if not hasattr(self, 'toolbar') or not hasattr(self, '_tb_colors'):
            return
        cc = self._tb_colors()
        self.toolbar.configure(bg=cc["bg"])
        if hasattr(self, '_toolbar_btns'):
            menus = getattr(self, '_toolbar_menus', {})
            commands = getattr(self, '_toolbar_commands', {})
            for text, btn in self._toolbar_btns.items():
                play = getattr(btn, '_toolbar_play', False)
                btn.config(bg=cc["bg"], fg=cc["play_fg"] if play else cc["fg"])
                self._bind_toolbar_label_hover(
                    btn, play=play,
                    menu=menus.get(text),
                    command=commands.get(text),
                )
        if hasattr(self, 'play_toolbar_btn'):
            self._bind_play_toolbar_hover()
        if hasattr(self, 'theme_toolbar_btn'):
            self.theme_toolbar_btn.config(
                text="☀" if self.dark_mode else "🌙",
                bg=cc["bg"], fg=cc["fg"])
            self._bind_theme_toolbar_hover()
        if hasattr(self, 'loop_toolbar_btn'):
            self.loop_toolbar_btn.config(bg=cc["bg"], fg=cc["fg"])
            self._bind_toolbar_label_hover(self.loop_toolbar_btn, play=False)
        if hasattr(self, 'sleep_countdown_label'):
            self.sleep_countdown_label.config(bg=cc["bg"], fg=cc["fg"])
        for child in self.toolbar.winfo_children():
            if isinstance(child, tk.Frame):
                child.configure(bg=cc["border"])
        if hasattr(self, '_media_pill_btns'):
            for lbl, btn in self._media_pill_btns.items():
                btn.config(bg=self.bg_color)
                self._bind_media_pill_hover(btn, lbl)

    def _fix_pill_colors_initial(self):
        self._fix_toolbar_colors()

    def _toggle_theme_menu(self):
        self._show_home_view()
        self.toggle_theme()

    def _toggle_loop_from_menu(self):
        self.toggle_loop_mode()
        if hasattr(self, 'loop_toolbar_btn') and hasattr(self, '_tb_colors'):
            cc = self._tb_colors()
            self.loop_toolbar_btn.config(text=self._get_loop_icon(), bg=cc["bg"], fg=cc["fg"])

    def _set_loop_mode_menu(self, mode):
        self.loop_mode = mode
        if hasattr(self, '_loop_mode_var'):
            self._loop_mode_var.set(mode)
        if self._active_player is not None:
            try:
                self._active_player.loop_mode = mode
                labels = {"loop_on": "↺  Loop", "loop_off": "→  Once", "shuffle": "⇄  Shuffle"}
                self._active_player._btn_loop.config(text=labels[mode])
            except Exception:
                pass
        if self.controller:
            self.controller.set_loop_mode(self.loop_mode)
        self.update_console(f"Loop mode: {mode}")
        self.save_preferences()
