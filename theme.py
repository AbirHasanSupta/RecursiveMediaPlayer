import json
import os
import os.path
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import base64


def _get_app_dirs():
    """Return (appdata_dir, localappdata_dir) for Recursive Media Player."""
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
                            subdirs = []
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
                            videos = []
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
                        'dark_mode': config.get('dark_mode', False),
                        'show_videos': config.get('show_videos', True),
                        'expand_all': config.get('expand_all', True),
                        'selected_dirs': decoded_dirs,
                        'save_directories': config.get('save_directories', False),
                        'start_from_last_played': config.get('start_from_last_played', False),
                        'last_played_video_index': config.get('last_played_video_index', 0),
                        'last_played_video_path': last_played_path,
                        'excluded_subdirs': decoded_excluded_subdirs,
                        'excluded_videos': decoded_excluded_videos,
                        'smart_resume_enabled': config.get('smart_resume_enabled', False),
                        'volume': config.get('volume', 50),
                        'is_muted': config.get('is_muted', False),
                        'loop_mode': config.get('loop_mode', 'loop_on'),
                        'show_console': config.get('show_console', True),
                    }
        except Exception:
            pass
        return {'dark_mode': False, 'show_videos': True, 'expand_all': True, 'selected_dirs': [],
                'save_directories': False, 'start_from_last_played': False,
                'last_played_video_index': 0, 'last_played_video_path': '',
                'excluded_subdirs': {}, 'excluded_videos': {}, 'smart_resume_enabled':False, 'volume':50,
                'is_muted': False, 'loop_mode':'loop_on', 'show_console': True}

    def save(self, config_dict):
        try:
            encoded_dirs = [base64.b64encode(d.encode()).decode() for d in config_dict.get('selected_dirs', [])]
            config_dict = dict(config_dict)
            config_dict['selected_dirs'] = encoded_dirs

            last_played_path = config_dict.get('last_played_video_path', '')
            config_dict['last_played_video_path'] = base64.b64encode(last_played_path.encode()).decode()

            with open(self.config_path, 'w') as f:
                json.dump(config_dict, f, indent=2)
        except Exception as e:
            pass


class ThemeSelector:
    def __init__(self):
        self.config = ConfigHandler()

    def save_preferences(self):
        encoded_excluded_subdirs = {}
        for root_dir, subdirs in getattr(self, 'excluded_subdirs', {}).items():
            encoded_root = base64.b64encode(root_dir.encode()).decode()
            encoded_subdirs = [base64.b64encode(subdir.encode()).decode() for subdir in subdirs]
            encoded_excluded_subdirs[encoded_root] = encoded_subdirs

        encoded_excluded_videos = {}
        for root_dir, videos in getattr(self, 'excluded_videos', {}).items():
            encoded_root = base64.b64encode(root_dir.encode()).decode()
            encoded_videos = [base64.b64encode(video.encode()).decode() for video in videos]
            encoded_excluded_videos[encoded_root] = encoded_videos

        prefs = {
            'dark_mode': self.dark_mode,
            'show_videos': self.show_videos,
            'expand_all': self.expand_all_var.get() if hasattr(self, 'expand_all_var') else True,
            'selected_dirs': [
                d for d in getattr(self, 'selected_dirs', [])
                if isinstance(d, str)
                and not d.startswith('gdrive://')
                and not d.startswith('http://')
                and not d.startswith('https://')
            ],
            'save_directories': getattr(self, 'save_directories', False),
            'start_from_last_played': getattr(self, 'start_from_last_played', False),
            'smart_resume_enabled': getattr(self, 'smart_resume_enabled', False),
            'last_played_video_index': getattr(self, 'last_played_video_index', 0),
            'last_played_video_path': getattr(self, 'last_played_video_path', ''),
            'excluded_subdirs': encoded_excluded_subdirs,
            'excluded_videos': encoded_excluded_videos,
            'volume': getattr(self, 'volume', 50),
            'is_muted': getattr(self, 'is_muted', False),
            'loop_mode': getattr(self, 'loop_mode', 'loop_on'),
            'show_console': getattr(self, 'show_console', True),
        }
        self.config.save(prefs)

    def _apply_menubar_colors(self):
        """Repaint the custom toolbar frame and all its dropdown menus."""
        if not hasattr(self, 'toolbar'):
            return
        if not hasattr(self, '_tb_colors'):
            return

        cc = self._tb_colors()

        # toolbar background
        self.toolbar.config(bg=cc["bg"])

        # all Label-based menu buttons (left side)
        for child in self.toolbar.winfo_children():
            if isinstance(child, tk.Label):
                # decide text colour: play button stays play_fg unless hovered
                is_play = hasattr(self, 'play_toolbar_btn') and child is self.play_toolbar_btn
                child.config(bg=cc["bg"], fg=cc["play_fg"] if is_play else cc["fg"])

        # rebuild dropdown-menu colors inline (they are tk.Menu objects stored on root)
        def restyle_menu(m):
            try:
                m.configure(
                    bg=cc["bg"], fg=cc["fg"],
                    activebackground=cc["hover_bg"],
                    activeforeground=cc["hover_fg"])
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

        # walk all Menu widgets that are children of root
        for widget in self.root.winfo_children():
            if isinstance(widget, tk.Menu):
                restyle_menu(widget)

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.save_preferences()
        self.apply_theme()

    def apply_theme(self):
        if self.dark_mode:
            self.bg_color = "#2B2B2B"
            self.accent_color = "#4A9EFF"
            self.text_color = "#A9B7C6"
            self.listbox_bg = "#313335"
            self.listbox_fg = "#A9B7C6"
            self.listbox_select_bg = "#214283"
            self.console_bg = "#1E1F22"
            self.console_fg = "#BCBEC4"
            self.frame_border = "#323232"
            self.header_color = "#BBBBBB"
            self.entry_bg = "#313335"
            self.entry_fg = "#A9B7C6"
            self.entry_border = "#323232"
            self.muted_fg = "#6B7A8A"
            self.badge_bg = "#3C3F41"
            self.badge_fg = "#A9B7C6"
            self.alt_row_color = "#313335"
            self.divider_color = "#3A3B3E"
        else:
            self.bg_color = "#f5f5f5"
            self.accent_color = "#3498db"
            self.text_color = "#333333"
            self.listbox_bg = "white"
            self.listbox_fg = "#333333"
            self.listbox_select_bg = "#3498db"
            self.console_bg = "#2c3e50"
            self.console_fg = "#ecf0f1"
            self.frame_border = "#cccccc"
            self.entry_bg = "white"
            self.entry_fg = "#333333"
            self.entry_border = "#e0e0e0"
            self.header_color = "#333333"
            self.muted_fg = "#666666"
            self.badge_bg = "#e8e8e8"
            self.badge_fg = "#333333"
            self.alt_row_color = "#ebebeb"
            self.divider_color = "#dddddd"

        if hasattr(self, 'theme_button'):
            self.theme_button.config(text="Light Mode" if self.dark_mode else "Dark Mode")

        self.root.configure(bg=self.bg_color)
        self.main_frame.configure(bg=self.bg_color)
        self.content_frame.configure(bg=self.bg_color)

        for section in ['dir_section', 'exclusion_section', 'status_frame', 'button_frame']:
            if hasattr(self, section):
                getattr(self, section).configure(bg=self.bg_color)

        for frame_attr in dir(self):
            if frame_attr.endswith('_frame') and hasattr(self, frame_attr):
                frame = getattr(self, frame_attr)
                # Skip the toolbar — _fix_toolbar_colors() handles it
                if hasattr(self, 'toolbar') and frame is self.toolbar:
                    continue
                if isinstance(frame, tk.Frame):
                    frame.configure(bg=self.bg_color)

        # Re-apply all toolbar widget colors via the single source of truth
        self._fix_toolbar_colors()

        for label_attr in dir(self):
            if label_attr.endswith('_label') and hasattr(self, label_attr):
                # Toolbar labels are handled by _fix_toolbar_colors() — skip them
                if label_attr == 'sleep_countdown_label':
                    continue
                label = getattr(self, label_attr)
                if isinstance(label, tk.Label):
                    if 'header' in label_attr or label.cget('font') == str(self.header_font):
                        label.configure(bg=self.bg_color, fg=self.header_color)
                    else:
                        label.configure(bg=self.bg_color, fg=self.text_color)

        if hasattr(self, 'dir_listbox'):
            self.dir_listbox.configure(
                bg=self.listbox_bg,
                fg=self.listbox_fg,
                selectbackground=self.listbox_select_bg,
                selectforeground="white",
                highlightbackground=self.frame_border
            )

        if hasattr(self, 'exclusion_listbox'):
            self.exclusion_listbox.configure(
                bg=self.listbox_bg,
                fg=self.listbox_fg,
                selectbackground="#CC7832",
                selectforeground="white",
                highlightbackground=self.frame_border
            )

        if hasattr(self, 'console_text'):
            self.console_text.configure(
                bg=self.console_bg,
                fg=self.console_fg,
                selectbackground="#214283",
                selectforeground="white",
                insertbackground=self.console_fg
            )

        if hasattr(self, 'scrollbar'):
            if self.dark_mode:
                self.scrollbar.configure(bg=self.bg_color, troughcolor=self.listbox_bg)

        if hasattr(self, 'exclusion_scrollbar'):
            if self.dark_mode:
                self.exclusion_scrollbar.configure(bg=self.bg_color, troughcolor=self.listbox_bg)

        if hasattr(self, 'console_scrollbar'):
            if self.dark_mode:
                self.console_scrollbar.configure(bg=self.console_bg, troughcolor=self.console_bg)

        self.update_container_borders()

        self._apply_menubar_colors()

        style = ttk.Style()
        style.configure("TFrame", background=self.bg_color)
        style.configure("TLabel", background=self.bg_color, foreground=self.text_color)
        style.configure(
            "Modern.TCheckbutton",
            background=self.bg_color,
            foreground=self.text_color,
            font=("Segoe UI", 10),
            padding=4
        )
        style.map(
            "Modern.TCheckbutton",
            foreground=[("active", self.text_color), ("selected", self.accent_color)],
            background=[("active", self.bg_color)]
        )

        for entry_attr in dir(self):
            if entry_attr.endswith('_entry') and hasattr(self, entry_attr):
                entry = getattr(self, entry_attr)
                if isinstance(entry, tk.Entry):
                    entry.configure(
                        bg=self.entry_bg,
                        fg=self.entry_fg,
                        insertbackground=self.entry_fg,
                        highlightbackground=self.entry_border
                    )

        style.configure("TRadiobutton", background=self.bg_color, foreground=self.text_color)
        style.map("TRadiobutton", background=[("active", self.bg_color)])

        self.update_all_buttons()
        self.update_frames_recursive(self.root)
        self._apply_theme_to_toplevels()

    def _get_loop_icon(self):
        icons = {
            "loop_on": "⟳  ON",
            "loop_off": "→ OFF",
            "shuffle": "⤨ RND"
        }
        return icons.get(self.loop_mode, "⟳  ON")

    def _get_loop_tooltip(self):
        tooltips = {
            "loop_on": "Loop: ON - Videos will repeat",
            "loop_off": "Loop: OFF - Play once then stop",
            "shuffle": "Shuffle: ON - Random playback"
        }
        return tooltips.get(self.loop_mode, "")

    def toggle_loop_mode(self):
        modes = ["loop_on", "loop_off", "shuffle"]
        current_index = modes.index(self.loop_mode)
        next_index = (current_index + 1) % len(modes)
        self.loop_mode = modes[next_index]

        if hasattr(self, 'loop_toggle_button'):
            self.loop_toggle_button.config(text=self._get_loop_icon())

        if self.controller:
            self.controller.set_loop_mode(self.loop_mode)

        mode_names = {
            "loop_on": "Loop ON",
            "loop_off": "Loop OFF",
            "shuffle": "Shuffle ON"
        }
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
                if 'exclude' in text and 'all' in text:
                    variant = 'warning'
                elif 'exclude' in text:
                    variant = 'danger'
                elif 'include' in text:
                    variant = 'success'
                elif 'play' in text:
                    variant = 'danger'
                elif 'add' in text:
                    variant = 'primary'
                elif 'playlist' in text:
                    variant = 'playlist'
                elif 'history' in text:
                    variant = 'history'
                elif 'settings' in text:
                    variant = 'settings'
                else:
                    variant = 'secondary'
            colors = self.get_button_colors(variant)
            button.configure(
                bg=colors['bg'],
                fg=colors['fg'],
                activebackground=colors['active']
            )

        # Also update buttons on any registered manager UIs
        for manager_ui in getattr(self, '_manager_uis', []):
            try:
                for attr_name in dir(manager_ui):
                    if not any(attr_name.endswith(s) for s in suffixes):
                        continue
                    button = getattr(manager_ui, attr_name, None)
                    if not isinstance(button, tk.Button):
                        continue
                    variant = getattr(button, '_variant', 'secondary')
                    colors = self.get_button_colors(variant)
                    button.configure(
                        bg=colors['bg'],
                        fg=colors['fg'],
                        activebackground=colors['active']
                    )
            except Exception:
                pass

    def register_manager_ui(self, manager_ui):
        """Register a manager UI object so apply_theme() can restyle it on theme toggle."""
        if not hasattr(self, '_manager_uis'):
            self._manager_uis = []
        if manager_ui not in self._manager_uis:
            self._manager_uis.append(manager_ui)

    def _apply_theme_to_toplevels(self):
        """
        Restyle every open manager Toplevel when the theme changes.
        Each manager UI must expose a `_window` attribute (the Toplevel)
        and a `_rebuild_theme()` method that re-applies bg/fg/accent colours.
        Uses update_frames_recursive as a fallback for any plain frames/labels.
        """
        for manager_ui in getattr(self, '_manager_uis', []):
            try:
                # Find the window attribute (favorites_window, queue_window, etc.)
                window = None
                for attr in ('favorites_window', 'queue_window', 'history_window',
                             'playlist_window'):
                    w = getattr(manager_ui, attr, None)
                    if w and w.winfo_exists():
                        window = w
                        break

                if window is None:
                    continue

                # Restyle the window background
                window.configure(bg=self.bg_color)

                # Walk all widgets inside the Toplevel and recolour
                # standard frames/labels/entries.  Accent-coloured header
                # bands and cards are identified by their stored _accent tag.
                self._restyle_toplevel(window)

            except Exception:
                pass

    def _restyle_toplevel(self, window):
        """
        Recursively restyle a Toplevel's widget tree to match the current theme.
        Widgets that carry a `_accent` attribute keep their accent colour.
        Widgets that carry a `_variant` attribute (buttons) are re-coloured via
        get_button_colors().
        """
        def _walk(widget):
            try:
                # Buttons with _variant
                if isinstance(widget, tk.Button) and hasattr(widget, '_variant'):
                    colors = self.get_button_colors(widget._variant)
                    widget.configure(
                        bg=colors['bg'],
                        fg=colors['fg'],
                        activebackground=colors['active'],
                    )
                    # re-bind hover so active colour is also correct
                    bg, active = colors['bg'], colors['active']
                    widget.bind("<Enter>", lambda e, b=active: widget.configure(bg=b))
                    widget.bind("<Leave>", lambda e, b=bg:    widget.configure(bg=b))
                    return  # don't recurse into button

                # Frames tagged as accent bands — skip (keep accent colour)
                if isinstance(widget, tk.Frame) and getattr(widget, '_accent', False):
                    for child in widget.winfo_children():
                        _walk(child)
                    return

                # Card frames (listbox containers) — set to listbox_bg
                if isinstance(widget, tk.Frame) and getattr(widget, '_card', False):
                    widget.configure(
                        bg=self.listbox_bg,
                        highlightbackground=self.frame_border,
                    )
                    for child in widget.winfo_children():
                        _walk(child)
                    return

                # Plain frames
                if isinstance(widget, (tk.Frame,)):
                    widget.configure(bg=self.bg_color)

                # Labels — muted, normal, or inside accent band (handled above)
                if isinstance(widget, tk.Label):
                    if getattr(widget, '_muted', False):
                        widget.configure(bg=self.bg_color, fg=self.muted_fg)
                    elif getattr(widget, '_badge', False):
                        widget.configure(bg=self.badge_bg, fg=self.badge_fg)
                    else:
                        widget.configure(bg=self.bg_color, fg=self.text_color)

                # Listboxes
                if isinstance(widget, tk.Listbox):
                    widget.configure(
                        bg=self.listbox_bg,
                        fg=self.listbox_fg,
                        selectbackground=self.listbox_select_bg,
                    )

                # Entry widgets
                if isinstance(widget, tk.Entry):
                    widget.configure(
                        bg=self.entry_bg,
                        fg=self.entry_fg,
                        insertbackground=self.entry_fg,
                        highlightbackground=self.entry_border,
                    )

                # Text widgets (description boxes)
                if isinstance(widget, tk.Text):
                    widget.configure(
                        bg=self.entry_bg,
                        fg=self.entry_fg,
                        insertbackground=self.entry_fg,
                    )

                for child in widget.winfo_children():
                    _walk(child)

            except tk.TclError:
                pass

        _walk(window)

    def get_button_colors(self, variant):
        if self.dark_mode:
            variants = {
                "primary": {"bg": "#365880", "fg": "#A9B7C6", "active": "#4A6BA3"},
                "success": {"bg": "#499C54", "fg": "white", "active": "#5AAE66"},
                "danger": {"bg": "#C75450", "fg": "white", "active": "#E06862"},
                "warning": {"bg": "#CC7832", "fg": "white", "active": "#D68843"},
                "secondary": {"bg": "#4C5052", "fg": "#A9B7C6", "active": "#5C6164"},
                "dark": {"bg": "#3A3A3C", "fg": "#A9B7C6", "active": "#4A4A4C"},
                "theme": {"bg": "#5C6164", "fg": "#FFFFFF", "active": "#6C7174"},
                "playlist": {"bg": "#9b59b6", "fg": "white", "active": "#8e44ad"},
                "history": {"bg": "#5a6c7d", "fg": "white", "active": "#4a5a6b"},
                "settings": {"bg": "#6c7b7c", "fg": "white", "active": "#5a6c6d"}
            }
        else:
            variants = {
                "primary": {"bg": "#2d89ef", "fg": "white", "active": "#1e70cf"},
                "success": {"bg": "#27ae60", "fg": "white", "active": "#229954"},
                "danger": {"bg": "#e74c3c", "fg": "white", "active": "#c0392b"},
                "warning": {"bg": "#f39c12", "fg": "white", "active": "#e67e22"},
                "secondary": {"bg": "#95a5a6", "fg": "white", "active": "#7f8c8d"},
                "dark": {"bg": "#34495e", "fg": "white", "active": "#2c3e50"},
                "theme": {"bg": "#34495e", "fg": "white", "active": "#2c3e50"},
                "playlist": {"bg": "#8e44ad", "fg": "white", "active": "#7d3c98"},
                "history": {"bg": "#2c3e50", "fg": "white", "active": "#34495e"},
                "settings": {"bg": "#7f8c8d", "fg": "white", "active": "#6c7b7c"}
            }
        return variants.get(variant, variants["primary"])

    def update_container_borders(self):
        if hasattr(self, 'dir_frame'):
            for child in self.dir_frame.winfo_children():
                if isinstance(child, tk.Frame) and any(isinstance(x, tk.Listbox) for x in child.winfo_children()):
                    child.configure(bg=self.bg_color, highlightbackground=self.frame_border, highlightthickness=1)
                    break

        if hasattr(self, 'exclusion_frame'):
            for child in self.exclusion_frame.winfo_children():
                if isinstance(child, tk.Frame) and any(isinstance(x, tk.Listbox) for x in child.winfo_children()):
                    child.configure(bg=self.bg_color, highlightbackground=self.frame_border, highlightthickness=1)
                    break

        for child in self.main_frame.winfo_children():
            for subchild in child.winfo_children():
                if isinstance(subchild, tk.Frame):
                    for subsubchild in subchild.winfo_children():
                        if isinstance(subsubchild, tk.Frame) and any(
                                isinstance(x, tk.Text) for x in subsubchild.winfo_children()):
                            subchild.configure(bg=self.bg_color, highlightbackground=self.frame_border,
                                               highlightthickness=1)
                            break

    def update_frames_recursive(self, widget):
        try:
            # Skip the toolbar and ALL its descendants — toolbar manages its own colors
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
        """Return True if widget is inside self.toolbar."""
        try:
            w = widget.master
            toolbar = self.toolbar
            while w is not None:
                if w is toolbar:
                    return True
                w = w.master
        except Exception:
            pass
        return False

    # ── Toolbar / pill colour palette ─────────────────────────────────────────
    # (normal_fg, hover_bg, hover_fg, active_bg)
    PILL_ACCENTS_LIGHT = {
        "🎵 Playlist":   ("#5B9BD5", "#1a5fa8", "#FFFFFF", "#144d8a"),
        "⬛ Queue":      ("#2ecc71", "#1a8a4a", "#FFFFFF", "#156e3a"),
        "♥ Favourites": ("#e67e22", "#b35a00", "#FFFFFF", "#8a4400"),
        "🕐 History":   ("#9b59b6", "#6c2f8f", "#FFFFFF", "#521f6e"),
    }
    PILL_ACCENTS_DARK = {
        "🎵 Playlist":   ("#4A9EFF", "#1a5fa8", "#FFFFFF", "#144d8a"),
        "⬛ Queue":      ("#2ecc71", "#1a8a4a", "#FFFFFF", "#156e3a"),
        "♥ Favourites": ("#FF9F43", "#b35a00", "#FFFFFF", "#8a4400"),
        "🕐 History":   ("#C39BD3", "#6c2f8f", "#FFFFFF", "#521f6e"),
    }

    def pill_accents(self, lbl):
        """Return the correct accent tuple for lbl given the current theme."""
        return (self.PILL_ACCENTS_DARK if self.dark_mode else self.PILL_ACCENTS_LIGHT)[lbl]

    def _fix_toolbar_colors(self):
        """Re-apply correct colors to every widget on the toolbar."""
        if not hasattr(self, 'toolbar') or not hasattr(self, '_tb_colors'):
            return
        cc = self._tb_colors()
        self.toolbar.configure(bg=cc["bg"])
        if hasattr(self, '_toolbar_btns'):
            for btn in self._toolbar_btns.values():
                btn.config(bg=cc["bg"], fg=cc["fg"])
        if hasattr(self, 'play_toolbar_btn'):
            self.play_toolbar_btn.config(bg=cc["bg"], fg=cc["play_fg"])
        if hasattr(self, 'theme_toolbar_btn'):
            self.theme_toolbar_btn.config(bg=cc["bg"], fg=cc["fg"])
        if hasattr(self, 'loop_toolbar_btn'):
            self.loop_toolbar_btn.config(bg=cc["bg"], fg=cc["fg"])
        if hasattr(self, 'sleep_countdown_label'):
            self.sleep_countdown_label.config(bg=cc["bg"], fg=cc["fg"])
        # Separator frames inside toolbar
        for child in self.toolbar.winfo_children():
            if isinstance(child, tk.Frame):
                child.configure(bg=cc["sep"])
        # Pill buttons
        self._fix_pill_colors()

    def _fix_pill_colors(self):
        """Apply accent colors to all media pill buttons for the current theme."""
        if not hasattr(self, '_media_pill_btns') or not self._media_pill_btns:
            return
        if not hasattr(self, '_tb_colors'):
            return
        cc = self._tb_colors()
        for lbl, btn in self._media_pill_btns.items():
            try:
                normal_fg = self.pill_accents(lbl)[0]
                btn.config(bg=cc["bg"], fg=normal_fg,
                           highlightbackground=normal_fg, highlightcolor=normal_fg)
            except KeyError:
                pass

    def _fix_pill_colors_initial(self):
        """Deferred call after tkinter's first render to lock in pill accent colors."""
        self._fix_toolbar_colors()

    def _toggle_theme_menu(self):
        """Toggle dark/light theme and refresh all toolbar widgets."""
        self.toggle_theme()
        if hasattr(self, 'theme_toolbar_btn') and hasattr(self, '_tb_colors'):
            cc = self._tb_colors()
            self.theme_toolbar_btn.config(
                text="☀" if self.dark_mode else "🌙",
                bg=cc["bg"], fg=cc["fg"])
        self._fix_toolbar_colors()

    def _toggle_loop_from_menu(self):
        """Toggle loop mode and refresh the loop toolbar button."""
        self.toggle_loop_mode()
        if hasattr(self, 'loop_toolbar_btn') and hasattr(self, '_tb_colors'):
            cc = self._tb_colors()
            self.loop_toolbar_btn.config(
                text=self._get_loop_icon(), bg=cc["bg"], fg=cc["fg"])

    def _set_loop_mode_menu(self, mode):
        """Set loop mode from menu and refresh toolbar button."""
        self.loop_mode = mode
        if hasattr(self, 'loop_toolbar_btn') and hasattr(self, '_tb_colors'):
            cc = self._tb_colors()
            self.loop_toolbar_btn.config(
                text=self._get_loop_icon(), bg=cc["bg"], fg=cc["fg"])
        if hasattr(self, '_loop_mode_var'):
            self._loop_mode_var.set(mode)
        if self.controller:
            self.controller.set_loop_mode(self.loop_mode)
        self.update_console(f"Loop mode: {mode}")
        self.save_preferences()