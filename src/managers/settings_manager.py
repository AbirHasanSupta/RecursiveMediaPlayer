import json
import os
import threading
import tkinter as tk
from tkinter import messagebox, filedialog, ttk
from pathlib import Path
from typing import Dict, Optional, Callable
import subprocess
import sys
import queue

from utils import _responsive_geometry


def _get_app_dirs():
    import os, sys
    from pathlib import Path
    APP = "Recursive Video Player"
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


DEFAULT_HOTKEYS: Dict[str, str] = {
    "toggle_pause":       "space",
    "stop_video":         "esc",
    "fast_forward":       "right",
    "rewind":             "left",
    "next_video":         "d",
    "prev_video":         "a",
    "next_directory":     "e",
    "prev_directory":     "q",
    "volume_up":          "w",
    "volume_down":        "s",
    "toggle_mute":        "m",
    "increase_speed":     "=",
    "decrease_speed":     "-",
    "reset_speed":        "0",
    "toggle_fullscreen":  "f",
    "rotate_right":       "r",
    "flip_h":              "h",
    "zoom_in":            "ctrl+=",
    "zoom_out":           "ctrl+-",
    "zoom_reset":         "ctrl+0",
    "take_screenshot":    "t",
    "copy_video_path":    "ctrl+c",
    "next_chapter":       "n",
    "prev_chapter":       "b",
    "cycle_subtitle":     "u",
    "disable_subtitles":  "ctrl+u",
    "toggle_gaming_mode":  "g",
    "ab_set_a": "[",
    "ab_set_b": "]",
    "ab_clear": "\\",
}

HOTKEY_LABELS: Dict[str, str] = {
    "toggle_pause":       "Pause / Resume",
    "stop_video":         "Stop playback",
    "fast_forward":       "Fast-forward 200 ms",
    "rewind":             "Rewind 200 ms",
    "next_video":         "Next video",
    "prev_video":         "Previous video",
    "next_directory":     "Next directory",
    "prev_directory":     "Previous directory",
    "volume_up":          "Volume up (+10)",
    "volume_down":        "Volume down (-10)",
    "toggle_mute":        "Toggle mute",
    "increase_speed":     "Increase speed (+0.25×)",
    "decrease_speed":     "Decrease speed (−0.25×)",
    "reset_speed":        "Reset speed to 1.0×",
    "toggle_fullscreen":  "Toggle fullscreen",
    "rotate_right":       "Rotate video 90° clockwise",
    "flip_h":              "Horizontal flip",
    "zoom_in":            "Zoom in (+10%)",
    "zoom_out":           "Zoom out (−10%)",
    "zoom_reset":         "Reset zoom to 100%",
    "take_screenshot":    "Take screenshot",
    "copy_video_path":    "Copy current video path",
    "next_chapter":       "Next chapter",
    "prev_chapter":       "Previous chapter",
    "cycle_subtitle":     "Cycle subtitle track",
    "disable_subtitles":  "Disable subtitles",
    "toggle_gaming_mode":  "Toggle Gaming Mode",
    "ab_set_a": "A-B Loop: Set point A",
    "ab_set_b": "A-B Loop: Set point B",
    "ab_clear": "A-B Loop: Clear",
}

HOTKEY_GROUPS: list = [
    ("▶  Playback",       ["toggle_pause", "stop_video", "fast_forward", "rewind"]),
    ("📁  Navigation",    ["next_video", "prev_video", "next_directory", "prev_directory"]),
    ("🔊  Audio",         ["volume_up", "volume_down", "toggle_mute"]),
    ("⚡  Speed",          ["increase_speed", "decrease_speed", "reset_speed"]),
    ("🖼  Display",        ["toggle_fullscreen",
                            "rotate_right", "flip_h",
                            "zoom_in", "zoom_out", "zoom_reset"]),
    ("🛠  Tools",          ["take_screenshot", "copy_video_path", "toggle_gaming_mode"]),
    ("📖  Chapters",       ["next_chapter", "prev_chapter"]),
    ("💬  Subtitles",      ["cycle_subtitle", "disable_subtitles"]),
    ("🔁  A-B Loop", ["ab_set_a", "ab_set_b", "ab_clear"]),
]


class SettingsData:
    def __init__(self):
        _, _local = _get_app_dirs()
        self.ai_index_path = str(_local / "index_data")
        self.preprocessing_workers = 3
        self.max_frames_per_video = 60
        self.auto_cleanup_days = 30
        self.enable_gpu_acceleration = True
        self.incremental_preprocessing = True
        self.excluded_index_dirs = "raw"
        self.preprocessing_batch_size = 10
        self.preview_duration = 3
        self.use_video_preview = True
        self.enable_watch_history = True
        self.dual_window_enabled = False
        self.gaming_mode = False
        self.ai_search_enabled = False
        self.show_video_annotations_in_tree = True
        self.hotkeys: Dict[str, str] = dict(DEFAULT_HOTKEYS)
        self.ai_server_url: str = ""
        self.dir_panel_width = 380
        self.dir_panel_mode = "expanded"

    def to_dict(self) -> dict:
        return {
            'ai_index_path': self.ai_index_path,
            'preprocessing_workers': self.preprocessing_workers,
            'max_frames_per_video': self.max_frames_per_video,
            'auto_cleanup_days': self.auto_cleanup_days,
            'enable_gpu_acceleration': self.enable_gpu_acceleration,
            'incremental_preprocessing': self.incremental_preprocessing,
            'excluded_index_dirs': self.excluded_index_dirs,
            'preprocessing_batch_size': self.preprocessing_batch_size,
            'preview_duration': self.preview_duration,
            'use_video_preview': self.use_video_preview,
            'enable_watch_history': self.enable_watch_history,
            'dual_window_enabled': self.dual_window_enabled,
            'hotkeys': dict(self.hotkeys),
            'gaming_mode': self.gaming_mode,
            'show_video_annotations_in_tree': self.show_video_annotations_in_tree,
            'ai_server_url': self.ai_server_url,
            'ai_search_enabled': self.ai_search_enabled,
            'dir_panel_width': self.dir_panel_width,
            'dir_panel_mode': self.dir_panel_mode,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'SettingsData':
        settings = cls()
        settings.ai_index_path = data.get('ai_index_path', settings.ai_index_path)
        settings.preprocessing_workers = data.get('preprocessing_workers', settings.preprocessing_workers)
        settings.max_frames_per_video = data.get('max_frames_per_video', settings.max_frames_per_video)
        settings.auto_cleanup_days = data.get('auto_cleanup_days', settings.auto_cleanup_days)
        settings.enable_gpu_acceleration = data.get('enable_gpu_acceleration', settings.enable_gpu_acceleration)
        settings.incremental_preprocessing = data.get('incremental_preprocessing', settings.incremental_preprocessing)
        settings.excluded_index_dirs = data.get('excluded_index_dirs', data.get('skip_raw_directories', None) and "raw" or settings.excluded_index_dirs)
        settings.preprocessing_batch_size = data.get('preprocessing_batch_size', settings.preprocessing_batch_size)
        settings.preview_duration = data.get('preview_duration', settings.preview_duration)
        settings.use_video_preview = data.get('use_video_preview', settings.use_video_preview)
        settings.enable_watch_history = data.get('enable_watch_history', settings.enable_watch_history)
        settings.dual_window_enabled = data.get('dual_window_enabled', settings.dual_window_enabled)
        settings.gaming_mode = data.get('gaming_mode', False)
        settings.show_video_annotations_in_tree = data.get('show_video_annotations_in_tree', True)
        settings.ai_server_url = data.get('ai_server_url', '')
        settings.ai_search_enabled = data.get('ai_search_enabled', False)
        settings.dir_panel_width = data.get('dir_panel_width', settings.dir_panel_width)
        settings.dir_panel_mode = data.get('dir_panel_mode', settings.dir_panel_mode)
        saved_hotkeys = data.get('hotkeys', {})
        if isinstance(saved_hotkeys, dict):
            settings.hotkeys.update(saved_hotkeys)
        return settings


class SettingsStorage:
    def __init__(self):
        _settings_dir, _local_dir = _get_app_dirs()
        self.settings_dir = _settings_dir
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        self.settings_file = self.settings_dir / "app_settings.json"

    def save_settings(self, settings: SettingsData) -> bool:
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings.to_dict(), f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving settings: {e}")
            return False

    def load_settings(self) -> SettingsData:
        try:
            if not self.settings_file.exists():
                return SettingsData()
            with open(self.settings_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return SettingsData.from_dict(data)
        except Exception as e:
            print(f"Error loading settings: {e}")
            return SettingsData()





class SettingsUI:
    def __init__(self, parent, theme_provider, settings: SettingsData,
                 console_callback: Callable = None, on_settings_changed: Callable = None,
                 enable_ai: bool = True):
        self.parent = parent
        self.theme_provider = theme_provider
        self.settings = settings
        self.console_callback = console_callback
        self.on_settings_changed = on_settings_changed
        self.enable_ai = enable_ai
        self._ai_search_manager = None
        self.settings_window = None

        self.ai_index_path_var = None
        self.workers_var = None
        self.max_frames_var = None
        self.cleanup_days_var = None
        self.gpu_acceleration_var = None
        self.incremental_var = None
        self.excluded_dirs_var = None
        self.batch_size_var = None
        self.ai_server_url_var = None
        self.cleanup_resume_callback = None
        self.cleanup_history_callback = None
        self.clear_thumbnails_callback = None
        self.clear_metadata_callback = None
        self.get_metadata_info_callback = None
        self.filter_sort_manager = None
        self._hotkey_btn_map: Dict[str, tk.Button] = {}
        self._embedded = False
        self._close_callback = None
        self._notebook = None
        self._section_parts = []

    # ── Theme helpers ──────────────────────────────────────────────────────────

    def _style_notebook(self, notebook):
        tp = self.theme_provider
        style = ttk.Style()
        try:
            style.configure(
                "Settings.TNotebook",
                background=tp.bg_color,
                borderwidth=0,
                relief="flat",
                tabmargins=[0, 0, 0, 0],
            )
            style.configure(
                "Settings.TNotebook.Tab",
                background=tp.surface_color,
                foreground=tp.text_muted,
                font=("Segoe UI", 10),
                padding=[16, 8],
                borderwidth=0,
                relief="flat",
            )
            style.map(
                "Settings.TNotebook.Tab",
                background=[
                    ("selected", tp.bg_color),
                    ("active", tp.hover_color),
                ],
                foreground=[
                    ("selected", tp.accent_color),
                    ("active", tp.text_color),
                ],
                font=[
                    ("selected", ("Segoe UI", 10, "bold")),
                ],
            )
            notebook.configure(style="Settings.TNotebook")
        except Exception:
            pass

    def _make_section(self, parent, title, pady=(0, 10)):
        """Themed card section that replaces tk.LabelFrame."""
        tp = self.theme_provider
        border = tk.Frame(parent, bg=tp.border_color, bd=0)
        border.pack(fill=tk.X, pady=pady)

        header = tk.Frame(border, bg=tp.surface_color)
        header.pack(fill=tk.X)
        lbl = tk.Label(
            header, text=title,
            font=("Segoe UI", 9, "bold"),
            bg=tp.surface_color, fg=tp.text_muted,
            padx=10, pady=5,
        )
        lbl.pack(side=tk.LEFT)

        h_sep = tk.Frame(border, bg=tp.border_color, height=1)
        h_sep.pack(fill=tk.X)

        body = tk.Frame(border, bg=tp.bg_color, padx=10, pady=8)
        body.pack(fill=tk.X, padx=1, pady=(0, 1))

        self._section_parts.append((border, header, h_sep, body))
        return body

    def apply_theme(self):
        if not self.settings_window:
            return
        try:
            if not self.settings_window.winfo_exists():
                return
        except Exception:
            return
        tp = self.theme_provider
        try:
            self.settings_window.configure(bg=tp.bg_color)
        except tk.TclError:
            pass
        if hasattr(tp, '_restyle_toplevel'):
            tp._restyle_toplevel(self.settings_window)
        if self._notebook:
            self._style_notebook(self._notebook)
        for border, header, h_sep, body in self._section_parts:
            try:
                border.configure(bg=tp.border_color)
                header.configure(bg=tp.surface_color)
                for child in header.winfo_children():
                    if isinstance(child, tk.Label):
                        child.configure(bg=tp.surface_color, fg=tp.text_muted)
                h_sep.configure(bg=tp.border_color)
                body.configure(bg=tp.bg_color)
            except tk.TclError:
                pass
        badge_bg = getattr(tp, 'badge_bg', tp.surface_color)
        badge_fg = getattr(tp, 'badge_fg', tp.text_color)
        badge_border = getattr(tp, 'border_color', '#E2E8F0')
        for btn in self._hotkey_btn_map.values():
            try:
                if btn.winfo_exists():
                    active_bg = getattr(tp, 'accent_color', '')
                    if btn.cget('bg') != active_bg:
                        btn.configure(bg=badge_bg, fg=badge_fg, highlightbackground=badge_border)
            except tk.TclError:
                pass

    # ── Window management ──────────────────────────────────────────────────────

    def show_settings_window(self, tab_index: int = 0):
        """Open settings window and optionally select a tab."""
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            if tab_index is not None and self._notebook:
                try:
                    self._notebook.select(tab_index)
                except Exception:
                    pass
            return

        self._embedded = False
        self._close_callback = None
        self.settings_window = tk.Toplevel(self.parent)
        self.settings_window.withdraw()
        self.settings_window.title("Application Settings")
        self.settings_window.geometry(_responsive_geometry(self.parent, 700, 820))
        self.settings_window.configure(bg=self.theme_provider.bg_color)
        self.settings_window.resizable(True, True)

        self._setup_settings_ui()
        if tab_index is not None and self._notebook:
            try:
                self._notebook.select(tab_index)
            except Exception:
                pass

        self.settings_window.transient(self.parent)
        self.settings_window.grab_set()

        from icon_helper import apply_icon
        apply_icon(self.settings_window)
        self.settings_window.deiconify()

    def show_settings_embedded(self, parent, close_callback=None, tab_index: int = 0):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.destroy()
        for child in parent.winfo_children():
            child.destroy()

        self._embedded = True
        self._close_callback = close_callback
        self.settings_window = tk.Frame(parent, bg=self.theme_provider.bg_color)
        self.settings_window.pack(fill=tk.BOTH, expand=True)
        self._setup_settings_ui()
        if tab_index is not None and self._notebook:
            try:
                self._notebook.select(tab_index)
            except Exception:
                pass

    def _close_settings(self):
        if self._embedded:
            if self._close_callback:
                self._close_callback()
            elif self.settings_window and self.settings_window.winfo_exists():
                self.settings_window.destroy()
            return
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.destroy()

    # ── UI construction ────────────────────────────────────────────────────────

    def _setup_settings_ui(self):
        self._section_parts = []

        notebook = ttk.Notebook(self.settings_window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=20, pady=(12, 0))
        self._notebook = notebook
        self._style_notebook(notebook)

        general_frame = self._create_general_settings_tab(notebook)
        notebook.add(general_frame, text="  General Settings  ")

        if self.enable_ai:
            ai_frame = self._create_ai_settings_tab(notebook)
            notebook.add(ai_frame, text="  AI & Preprocessing  ")

        shortcuts_frame = self._create_shortcuts_tab(notebook)
        notebook.add(shortcuts_frame, text="  ⌨  Keyboard Shortcuts  ")

        self._create_action_buttons()

    def _create_ai_settings_tab(self, parent):
        tp = self.theme_provider
        frame = ttk.Frame(parent)

        main_container = tk.Frame(frame, bg=tp.bg_color)
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        url_body = self._make_section(main_container, "AI Server Connection", pady=(0, 10))

        self.ai_server_url_var = tk.StringVar(value=self.settings.ai_server_url)
        self.ai_search_enabled_var = tk.BooleanVar(value=self.settings.ai_search_enabled)
        cb = ttk.Checkbutton(
            url_body, text="Enable AI Search",
            variable=self.ai_search_enabled_var,
            style="Modern.TCheckbutton",
            command=self._toggle_ai_search_url_state
        )
        cb.pack(anchor='w', pady=(0, 8))

        tk.Label(
            url_body,
            text="AI Server URL",
            font=("Segoe UI", 10, "bold"),
            bg=tp.bg_color, fg=tp.text_color,
        ).pack(anchor='w', pady=(0, 4))

        tk.Label(
            url_body,
            text=(
                "Run the ai_service.py (find it inside 'RecursiveVideoPlayer/_internal/') server separately (or on another machine), "
                "then paste its base URL here.  The app will connect to it for AI search."
            ),
            font=tp.small_font,
            bg=tp.bg_color, fg=tp.text_muted,
            wraplength=560, justify=tk.LEFT,
        ).pack(anchor='w', pady=(0, 8))

        url_frame = tk.Frame(url_body, bg=tp.bg_color)
        url_frame.pack(fill=tk.X, pady=(0, 4))

        # URL field (same as before but with state management)
        self.url_entry = tk.Entry(
            url_frame,
            textvariable=self.ai_server_url_var,
            font=tp.normal_font,
            bg=getattr(tp, 'entry_bg', tp.surface_color),
            fg=getattr(tp, 'entry_fg', tp.text_color),
            insertbackground=getattr(tp, 'entry_fg', tp.text_color),
            readonlybackground=getattr(tp, 'entry_bg', tp.surface_color),
            disabledbackground=getattr(tp, 'entry_bg', tp.surface_color),
            relief=tk.FLAT, bd=0,
            highlightthickness=1,
            highlightbackground=getattr(tp, 'entry_border', tp.border_color),
            state='normal' if self.ai_search_enabled_var.get() else 'readonly'
        )
        self.url_entry.pack(fill=tk.X, ipady=4)

        tk.Label(
            url_body,
            text='e.g.  http://localhost:8000   or   http://192.168.1.10:8000',
            font=tp.small_font,
            bg=tp.bg_color, fg=tp.text_muted,
        ).pack(anchor='w', pady=(3, 0))

        tk.Label(
            url_body,
            text='The URL is saved and applied automatically when you click Save Settings.',
            font=tp.small_font,
            bg=tp.bg_color, fg=tp.text_muted,
        ).pack(anchor='w', pady=(4, 0))

        index_body = self._make_section(main_container, "AI Index Path", pady=(0, 10))

        tk.Label(
            index_body,
            text="AI Index Storage Path",
            font=("Segoe UI", 10, "bold"),
            bg=tp.bg_color, fg=tp.text_color,
        ).pack(anchor='w', pady=(0, 4))

        tk.Label(
            index_body,
            text="Directory where AI index data (embeddings, metadata) is stored. Changing this requires re-indexing.",
            font=tp.small_font,
            bg=tp.bg_color, fg=tp.text_muted,
            wraplength=560, justify=tk.LEFT,
        ).pack(anchor='w', pady=(0, 8))

        path_frame = tk.Frame(index_body, bg=tp.bg_color)
        path_frame.pack(fill=tk.X, pady=(0, 4))

        self.ai_index_path_var = tk.StringVar(value=self.settings.ai_index_path)
        self.index_path_entry = tk.Entry(
            path_frame,
            textvariable=self.ai_index_path_var,
            font=tp.normal_font,
            bg=getattr(tp, 'entry_bg', tp.surface_color),
            fg=getattr(tp, 'entry_fg', tp.text_color),
            insertbackground=getattr(tp, 'entry_fg', tp.text_color),
            readonlybackground=getattr(tp, 'entry_bg', tp.surface_color),
            disabledbackground=getattr(tp, 'entry_bg', tp.surface_color),
            relief=tk.FLAT, bd=0,
            highlightthickness=1,
            highlightbackground=getattr(tp, 'entry_border', tp.border_color),
            state='normal' if self.ai_search_enabled_var.get() else 'readonly'
        )
        self.index_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4, padx=(0, 5))

        self.browse_index_btn = tp.create_button(path_frame, "Browse", self._browse_index_path, "secondary", "sm")
        self.browse_index_btn.pack(side=tk.RIGHT)

        preproc_body = self._make_section(main_container, "Preprocessing Defaults", pady=(0, 10))

        for label, var_attr, setting_attr, from_, to_, hint in [
            ("Workers:", "workers_var", "preprocessing_workers", 1, 8, "1–8"),
            ("Max Frames per Video:", "max_frames_var", "max_frames_per_video", 10, 200, "10–200"),
        ]:
            row = tk.Frame(preproc_body, bg=tp.bg_color)
            row.pack(fill=tk.X, pady=3)
            tk.Label(row, text=label, font=tp.normal_font, bg=tp.bg_color, fg=tp.text_color,
                     width=22, anchor='w').pack(side=tk.LEFT)
            var = tk.IntVar(value=getattr(self.settings, setting_attr))
            setattr(self, var_attr, var)
            tk.Spinbox(row, from_=from_, to=to_, textvariable=var, font=tp.normal_font, width=6,
                       bg=getattr(tp, 'entry_bg', tp.surface_color),
                       fg=getattr(tp, 'entry_fg', tp.text_color),
                       buttonbackground=tp.bg_color, relief=tk.FLAT, bd=1).pack(side=tk.LEFT)
            tk.Label(row, text=hint, font=tp.small_font, bg=tp.bg_color,
                     fg=tp.text_muted).pack(side=tk.LEFT, padx=(6, 0))

        self.incremental_var = tk.BooleanVar(value=self.settings.incremental_preprocessing)
        ttk.Checkbutton(preproc_body, text="Incremental mode (skip already-indexed videos)",
                        variable=self.incremental_var,
                        style="Modern.TCheckbutton").pack(anchor='w', pady=2)

        self.gpu_acceleration_var = tk.BooleanVar(value=self.settings.enable_gpu_acceleration)
        ttk.Checkbutton(preproc_body, text="GPU acceleration (requires CUDA)",
                        variable=self.gpu_acceleration_var,
                        style="Modern.TCheckbutton").pack(anchor='w', pady=2)

        tk.Label(preproc_body, text="Exclude directory names:", font=tp.normal_font,
                 bg=tp.bg_color, fg=tp.text_color).pack(anchor='w', pady=(6, 2))
        self.excluded_dirs_var = tk.StringVar(value=self.settings.excluded_index_dirs)
        excl_wrap = tk.Frame(preproc_body, bg=getattr(tp, 'entry_bg', tp.surface_color),
                             highlightbackground=tp.border_color, highlightthickness=1)
        excl_wrap.pack(fill=tk.X)
        tk.Entry(excl_wrap, textvariable=self.excluded_dirs_var,
                 bg=getattr(tp, 'entry_bg', tp.surface_color),
                 fg=getattr(tp, 'entry_fg', tp.text_color),
                 relief='flat', bd=0, font=tp.normal_font,
                 insertbackground=getattr(tp, 'entry_fg', tp.text_color)).pack(fill=tk.X, ipady=4, padx=6)
        tk.Label(preproc_body, text='Comma-separated, e.g.  raw, raws, footage',
                 font=tp.small_font, bg=tp.bg_color, fg=tp.text_muted).pack(anchor='w', pady=(3, 0))

        return frame

    def _toggle_ai_search_url_state(self):
        enabled = self.ai_search_enabled_var.get()
        self.url_entry.config(state='normal' if enabled else 'readonly')
        if hasattr(self, 'index_path_entry'):
            self.index_path_entry.config(state='normal' if enabled else 'readonly')
        if hasattr(self, 'browse_index_btn'):
            self.browse_index_btn.config(state='normal' if enabled else 'disabled')

    def _create_general_settings_tab(self, parent):
        tp = self.theme_provider
        frame = ttk.Frame(parent)

        # ── Scrollable canvas so all sections fit without cutting off Save button ──
        canvas_frame = tk.Frame(frame, bg=tp.bg_color)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(canvas_frame, bg=tp.bg_color, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview,
                                  style="ExclusionTree.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        main_container = tk.Frame(canvas, bg=tp.bg_color)
        canvas_window = canvas.create_window((20, 12), window=main_container, anchor='nw', tags='inner')

        def _on_inner_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(e):
            canvas.itemconfig('inner', width=max(1, e.width - 40))

        main_container.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            try:
                if canvas.winfo_exists():
                    canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except Exception:
                pass

        canvas.bind_all("<MouseWheel>", _on_mousewheel)


        # ── 1. Video Preview ──────────────────────────────────────────────────────
        preview_body = self._make_section(main_container, "Video Preview", pady=(0, 8))

        duration_frame = tk.Frame(preview_body, bg=tp.bg_color)
        duration_frame.pack(fill=tk.X, pady=(0, 4))
        tk.Label(duration_frame, text="Preview Duration (sec):", font=tp.normal_font,
                 bg=tp.bg_color, fg=tp.text_color, width=22, anchor='w').pack(side=tk.LEFT)
        self.preview_duration_var = tk.IntVar(value=self.settings.preview_duration)
        duration_spin = tk.Spinbox(
            duration_frame, from_=1, to=10, textvariable=self.preview_duration_var,
            font=tp.normal_font, width=8,
            bg=getattr(tp, 'entry_bg', tp.surface_color),
            fg=getattr(tp, 'entry_fg', tp.text_color),
            buttonbackground=tp.bg_color,
            relief=tk.FLAT, bd=1,
        )
        duration_spin.pack(side=tk.LEFT, padx=(0, 2))
        tk.Label(duration_frame, text="(1–10 seconds)", font=tp.small_font,
                 bg=tp.bg_color, fg=tp.text_muted).pack(side=tk.LEFT)

        self.use_video_preview_var = tk.BooleanVar(value=self.settings.use_video_preview)
        ttk.Checkbutton(preview_body, text="Use Video Previews (disable for static thumbnails only)",
                        variable=self.use_video_preview_var,
                        style="Modern.TCheckbutton").pack(anchor='w', pady=2)

        thumbnail_btn_frame = tk.Frame(preview_body, bg=tp.bg_color)
        thumbnail_btn_frame.pack(fill=tk.X, pady=(6, 0))
        self.clear_thumbnails_btn = tp.create_modern_button(
            thumbnail_btn_frame, "Clear Preview Cache",
            self._clear_thumbnail_cache, "warning", "sm"
        )
        self.clear_thumbnails_btn.pack(side=tk.LEFT)

        self.thumbnail_info_label = tk.Label(
            preview_body, text="",
            font=tp.small_font, bg=tp.bg_color, fg=tp.text_muted
        )
        self.thumbnail_info_label.pack(anchor='w', pady=(4, 0))

        # ── 2. Player Windows ─────────────────────────────────────────────────────
        player_body = self._make_section(main_container, "Player Windows", pady=(0, 8))

        self.dual_window_enabled_var = tk.BooleanVar(value=self.settings.dual_window_enabled)
        ttk.Checkbutton(player_body, text="Enable Second Player Window (each window has 3 players)",
                        variable=self.dual_window_enabled_var,
                        style="Modern.TCheckbutton").pack(anchor='w', pady=2)

        self.gaming_mode_var = tk.BooleanVar(value=self.settings.gaming_mode)
        ttk.Checkbutton(
            player_body,
            text="Gaming Mode — hotkeys work when mouse hovers over player (no click-to-focus needed)",
            variable=self.gaming_mode_var,
            style="Modern.TCheckbutton"
        ).pack(anchor='w', pady=2)

        self.show_console_var = tk.BooleanVar(value=getattr(tp, 'show_console', True))
        ttk.Checkbutton(player_body, text="Show Player Console panel",
                        variable=self.show_console_var,
                        style="Modern.TCheckbutton").pack(anchor='w', pady=2)

        # ── 3. Watch History ──────────────────────────────────────────────────────
        history_body = self._make_section(main_container, "Watch History", pady=(0, 8))

        self.enable_watch_history_var = tk.BooleanVar(value=self.settings.enable_watch_history)
        ttk.Checkbutton(history_body, text="Enable Watch History tracking",
                        variable=self.enable_watch_history_var,
                        style="Modern.TCheckbutton").pack(anchor='w', pady=2)

        cleanup_row = tk.Frame(history_body, bg=tp.bg_color)
        cleanup_row.pack(fill=tk.X, pady=(6, 0))
        tk.Label(cleanup_row, text="Auto-cleanup after (days):", font=tp.normal_font,
                 bg=tp.bg_color, fg=tp.text_color, width=22, anchor='w').pack(side=tk.LEFT)
        self.cleanup_days_var = tk.IntVar(value=self.settings.auto_cleanup_days)
        cleanup_spin = tk.Spinbox(
            cleanup_row, from_=0, to=365, textvariable=self.cleanup_days_var,
            font=tp.normal_font, width=8,
            bg=getattr(tp, 'entry_bg', tp.surface_color),
            fg=getattr(tp, 'entry_fg', tp.text_color),
            buttonbackground=tp.bg_color,
            relief=tk.FLAT, bd=1,
        )
        cleanup_spin.pack(side=tk.LEFT, padx=(0, 5))
        tk.Label(cleanup_row, text="(watch history & resume data)", font=tp.small_font,
                 bg=tp.bg_color, fg=tp.text_muted).pack(side=tk.LEFT)

        # ── 4. Metadata Cache ─────────────────────────────────────────────────────
        cache_body = self._make_section(main_container, "Metadata Cache", pady=(0, 8))

        tk.Label(
            cache_body,
            text="Stores video info like resolution, duration, and play statistics.",
            font=tp.small_font, bg=tp.bg_color, fg=tp.text_muted,
            wraplength=560, justify=tk.LEFT
        ).pack(anchor='w', pady=(0, 6))

        cache_btn_frame = tk.Frame(cache_body, bg=tp.bg_color)
        cache_btn_frame.pack(fill=tk.X)
        self.clear_metadata_btn = tp.create_modern_button(
            cache_btn_frame, "Clear Metadata Cache",
            self._clear_metadata_cache, "warning", "sm"
        )
        self.clear_metadata_btn.pack(side=tk.LEFT)

        self.metadata_info_label = tk.Label(
            cache_body, text="",
            font=tp.small_font, bg=tp.bg_color, fg=tp.text_muted
        )
        self.metadata_info_label.pack(anchor='w', pady=(4, 0))

        self._update_metadata_info()

        # ── 5. Manual Data Management ─────────────────────────────────────────────
        manual_body = self._make_section(main_container, "Manual Data Management", pady=(0, 8))

        cleanup_btn_frame = tk.Frame(manual_body, bg=tp.bg_color)
        cleanup_btn_frame.pack(fill=tk.X)
        self.cleanup_resume_btn = tp.create_modern_button(
            cleanup_btn_frame, "Clean Resume Data",
            self._cleanup_resume_data, "warning", "sm"
        )
        self.cleanup_resume_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.cleanup_history_btn = tp.create_modern_button(
            cleanup_btn_frame, "Clean Watch History",
            self._cleanup_watch_history, "warning", "sm"
        )
        self.cleanup_history_btn.pack(side=tk.LEFT)

        return frame

    def _create_shortcuts_tab(self, parent):
        tp = self.theme_provider
        frame = ttk.Frame(parent)

        main_container = tk.Frame(frame, bg=tp.bg_color)
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        tk.Label(
            main_container,
            text="Click a key badge to reassign it.  Press the new key (or combo) when prompted.",
            font=tp.small_font,
            bg=tp.bg_color, fg=tp.text_muted,
            wraplength=620, justify=tk.LEFT
        ).pack(anchor='w', pady=(0, 4))

        conflict_bar_frame = tk.Frame(main_container, bg=tp.bg_color)
        conflict_bar_frame.pack(fill=tk.X, pady=(0, 8))
        self._conflict_label = tk.Label(
            conflict_bar_frame, text="",
            font=tp.small_font,
            bg=tp.bg_color, fg=getattr(tp, 'accent_secondary', '#FF6B6B'),
        )
        self._conflict_label.pack(anchor='w')

        canvas_frame = tk.Frame(main_container, bg=tp.bg_color)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(canvas_frame, bg=tp.bg_color, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview,
                                  style="ExclusionTree.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=tp.bg_color)
        canvas_window = canvas.create_window((0, 0), window=inner, anchor='nw', tags='inner')

        def _on_inner_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(e):
            canvas.itemconfig('inner', width=e.width)

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            try:
                if canvas.winfo_exists():
                    canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except Exception:
                pass

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.settings_window.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        self._capturing_action: Optional[str] = None
        self._capture_overlay: Optional[tk.Toplevel] = None
        self._hotkeys_draft: Dict[str, str] = dict(self.settings.hotkeys)
        self._hotkey_btn_map = {}

        badge_bg = getattr(tp, 'badge_bg', tp.surface_color)
        badge_fg = getattr(tp, 'badge_fg', tp.text_color)
        active_bg = getattr(tp, 'accent_color', '#5E81F4')
        badge_border = getattr(tp, 'border_color', '#E2E8F0')

        KEY_COL_W = 20

        def _start_capture(action_id: str, btn: tk.Button):
            if self._capturing_action is not None:
                return
            self._capturing_action = action_id
            self._conflict_label.config(text="")
            btn.config(bg=active_bg, fg='white', relief=tk.FLAT, highlightbackground=active_bg)

            overlay_parent = self.settings_window.winfo_toplevel()
            overlay = tk.Toplevel(overlay_parent)
            overlay.withdraw()
            overlay.title("Press new key…")
            overlay.geometry("400x148")
            overlay.configure(bg=tp.bg_color)
            overlay.transient(overlay_parent)
            overlay.grab_set()
            overlay.resizable(False, False)
            self._capture_overlay = overlay

            action_label = HOTKEY_LABELS.get(action_id, action_id)

            tk.Frame(overlay, bg=tp.border_color, height=1).pack(fill=tk.X)

            inner_o = tk.Frame(overlay, bg=tp.bg_color)
            inner_o.pack(fill=tk.BOTH, expand=True, padx=20, pady=16)

            tk.Label(
                inner_o, text="Reassigning shortcut",
                font=("Segoe UI", 9, "bold"),
                bg=tp.bg_color, fg=tp.text_muted,
            ).pack(anchor='w')

            tk.Label(
                inner_o, text=HOTKEY_LABELS.get(action_id, action_id),
                font=tp.normal_font,
                bg=tp.bg_color, fg=tp.text_color,
                wraplength=360,
            ).pack(anchor='w', pady=(2, 10))

            tk.Label(
                inner_o, text="Press any key or combo  ·  Esc to cancel",
                font=tp.small_font,
                bg=tp.bg_color, fg=tp.text_muted,
            ).pack(anchor='w')

            def _finish_capture(event):
                keysym_raw = event.keysym.lower()
                if keysym_raw in ('control_l', 'control_r', 'shift_l', 'shift_r',
                                  'alt_l', 'alt_r', 'super_l', 'super_r',
                                  'caps_lock', 'num_lock', 'scroll_lock'):
                    return
                if keysym_raw == 'escape':
                    _cancel()
                    return
                mods = []
                if event.state & 0x4:
                    mods.append('ctrl')
                if event.state & 0x1:
                    mods.append('shift')
                _norm = {
                    'return': 'enter', 'prior': 'page_up', 'next': 'page_down',
                    'equal': '=', 'minus': '-', 'plus': '+',
                    'bracketleft': '[', 'bracketright': ']',
                    'semicolon': ';', 'apostrophe': "'", 'comma': ',',
                    'period': '.', 'slash': '/', 'backslash': '\\',
                    'grave': '`', 'space': 'space', 'tab': 'tab',
                    'delete': 'delete', 'backspace': 'backspace',
                    'insert': 'insert', 'home': 'home', 'end': 'end',
                    'f1': 'f1', 'f2': 'f2', 'f3': 'f3', 'f4': 'f4',
                    'f5': 'f5', 'f6': 'f6', 'f7': 'f7', 'f8': 'f8',
                    'f9': 'f9', 'f10': 'f10', 'f11': 'f11', 'f12': 'f12',
                    'up': 'up', 'down': 'down', 'left': 'left', 'right': 'right',
                }
                keysym = _norm.get(keysym_raw, keysym_raw)
                combo = '+'.join(mods + [keysym]) if mods else keysym

                conflict_action = None
                for aid, k in self._hotkeys_draft.items():
                    if k == combo and aid != action_id:
                        conflict_action = aid
                        break

                old_combo = self._hotkeys_draft.get(action_id, '')
                if conflict_action:
                    self._hotkeys_draft[conflict_action] = old_combo
                    displaced_label = HOTKEY_LABELS.get(conflict_action, conflict_action)
                    displaced_btn = self._hotkey_btn_map.get(conflict_action)
                    if displaced_btn and displaced_btn.winfo_exists():
                        displaced_btn.config(text=old_combo or '—',
                                             bg=badge_bg, fg=badge_fg, relief=tk.FLAT, highlightbackground=badge_border)
                    try:
                        self._conflict_label.config(
                            text=f"↔  Swapped: '{displaced_label}' is now '{old_combo or '—'}'"
                        )
                    except Exception:
                        pass

                self._hotkeys_draft[action_id] = combo
                try:
                    if btn.winfo_exists():
                        btn.config(text=combo, bg=badge_bg, fg=badge_fg, relief=tk.FLAT, highlightbackground=badge_border)
                    if not conflict_action:
                        self._conflict_label.config(text="")
                except Exception:
                    pass
                _close_overlay()
                self._capturing_action = None

            def _cancel(revert=True):
                if revert:
                    btn.config(bg=badge_bg, fg=badge_fg, relief=tk.FLAT, highlightbackground=badge_border)
                _close_overlay()
                self._capturing_action = None

            def _close_overlay():
                try:
                    overlay.unbind_all('<KeyPress>')
                    overlay.grab_release()
                    overlay.destroy()
                except Exception:
                    pass
                self._capture_overlay = None

            overlay.bind('<KeyPress>', _finish_capture)
            overlay.protocol("WM_DELETE_WINDOW", _cancel)
            overlay.focus_force()
            from icon_helper import apply_icon
            apply_icon(overlay)
            overlay.deiconify()

        def _add_group(parent_frame, title, action_ids):
            section_body = self._make_section(parent_frame, title, pady=(0, 10))

            hdr = tk.Frame(section_body, bg=tp.bg_color)
            hdr.pack(fill=tk.X, pady=(0, 4))
            tk.Label(hdr, text="Key / Combo", font=tp.small_font,
                     bg=tp.bg_color, fg=tp.text_muted,
                     width=KEY_COL_W, anchor='w').pack(side=tk.LEFT)
            tk.Label(hdr, text="Action", font=tp.small_font,
                     bg=tp.bg_color, fg=tp.text_muted, anchor='w').pack(side=tk.LEFT)

            tk.Frame(section_body, bg=tp.border_color, height=1).pack(fill=tk.X, pady=(0, 6))

            alt_row = getattr(tp, 'alt_row_color', tp.bg_color)
            for i, action_id in enumerate(action_ids):
                current_key = self._hotkeys_draft.get(action_id, '—')
                action_label = HOTKEY_LABELS.get(action_id, action_id)
                row_bg = alt_row if i % 2 else tp.bg_color

                row = tk.Frame(section_body, bg=row_bg)
                row.pack(fill=tk.X, pady=1)

                btn = tk.Button(
                    row, text=current_key,
                    font=("Consolas", 9),
                    bg=badge_bg, fg=badge_fg,
                    relief=tk.FLAT, bd=0,
                    padx=10, pady=5,
                    width=KEY_COL_W, anchor='w',
                    cursor='hand2',
                    activebackground=tp.accent_color,
                    activeforeground='#ffffff',
                    highlightthickness=1,
                    highlightbackground=badge_border,
                )
                btn.config(command=lambda aid=action_id, b=btn: _start_capture(aid, b))

                def _badge_enter(e, b=btn):
                    if b.cget('bg') != active_bg:
                        b.config(bg=tp.hover_color, highlightbackground=tp.accent_color)

                def _badge_leave(e, b=btn):
                    if b.cget('bg') != active_bg:
                        b.config(bg=badge_bg, fg=badge_fg, highlightbackground=badge_border)

                btn.bind('<Enter>', _badge_enter)
                btn.bind('<Leave>', _badge_leave)
                btn.pack(side=tk.LEFT, padx=(0, 10))
                self._hotkey_btn_map[action_id] = btn

                tk.Label(
                    row, text=action_label,
                    font=tp.normal_font,
                    bg=row_bg, fg=tp.text_color, anchor='w'
                ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        for group_title, action_ids in HOTKEY_GROUPS:
            _add_group(inner, group_title, action_ids)

        reset_frame = tk.Frame(main_container, bg=tp.bg_color)
        reset_frame.pack(fill=tk.X, pady=(8, 0))

        def _reset_shortcuts():
            if messagebox.askyesno("Reset Shortcuts",
                                   "Reset all keyboard shortcuts to their defaults?"):
                self._hotkeys_draft = dict(DEFAULT_HOTKEYS)
                self._conflict_label.config(text="")
                for aid, b in self._hotkey_btn_map.items():
                    b.config(text=self._hotkeys_draft.get(aid, '—'),
                             bg=badge_bg, fg=badge_fg, relief=tk.FLAT, highlightbackground=badge_border)
                self.theme_provider.toast.success("Shortcuts Reset", "All shortcuts restored to defaults")

        tp.create_modern_button(
            reset_frame, "Reset Shortcuts to Defaults", _reset_shortcuts, "warning", "sm"
        ).pack(side=tk.LEFT)

        return frame

    def _create_action_buttons(self):
        tp = self.theme_provider

        tk.Frame(self.settings_window, bg=tp.border_color, height=1).pack(fill=tk.X, side=tk.BOTTOM)

        bar = tk.Frame(self.settings_window, bg=tp.bg_color)
        bar.pack(fill=tk.X, side=tk.BOTTOM, padx=20, pady=10)

        tp.create_modern_button(bar, "↺  Reset to Defaults", self._reset_to_defaults, "warning", "md").pack(
            side=tk.LEFT)
        tp.create_modern_button(bar, "✓  Save Settings", self._save_settings, "primary", "md").pack(side=tk.RIGHT,
                                                                                                    padx=(6, 0))
        tp.create_modern_button(bar, "Cancel", self._close_settings, "secondary", "md").pack(side=tk.RIGHT)

    # ── Data actions ───────────────────────────────────────────────────────────

    def _browse_index_path(self):
        current_path = self.ai_index_path_var.get()
        initial_dir = os.path.dirname(current_path) if os.path.exists(current_path) else os.path.expanduser("~")
        directory = filedialog.askdirectory(title="Select AI Index Data Directory", initialdir=initial_dir)
        if directory:
            self.ai_index_path_var.set(directory)


    def _cleanup_resume_data(self):
        result = messagebox.askyesno(
            "Confirm Cleanup",
            "Clean up old resume position data?\n\nThis will remove positions older than the configured cleanup period."
        )
        if result:
            if self.cleanup_resume_callback:
                try:
                    self._apply_current_settings()
                    count = self.cleanup_resume_callback()
                    self.theme_provider.toast.info("Cleanup Complete", f"Cleaned up {count} old resume entries")
                    if self.console_callback:
                        self.console_callback(f"Cleaned up {count} old resume position entries")
                except Exception as e:
                    self.theme_provider.toast.error("Error", f"Failed to cleanup resume data: {e}")
            else:
                self.theme_provider.toast.warning("Warning", "Resume cleanup function not available")

    def _cleanup_watch_history(self):
        result = messagebox.askyesno(
            "Confirm Cleanup",
            "Clean up old watch history data?\n\nThis will remove history older than the configured cleanup period."
        )
        if result:
            if self.cleanup_history_callback:
                try:
                    count = self.cleanup_history_callback()
                    self.theme_provider.toast.info("Cleanup Complete", f"Cleaned up {count} old history entries")
                except Exception as e:
                    self.theme_provider.toast.error("Error", f"Failed to cleanup watch history: {e}")
            else:
                self.theme_provider.toast.warning("Warning", "History cleanup function not available")

    def _clear_metadata_cache(self):
        result = messagebox.askyesno(
            "Confirm Clear Cache",
            "Clear all cached video metadata?\n\nThis will remove stored information like resolution, duration, and play statistics. The data will be regenerated when needed."
        )
        if result:
            if self.clear_metadata_callback:
                try:
                    count = self.clear_metadata_callback()
                    self._update_metadata_info()
                    self.theme_provider.toast.info("Cache Cleared", f"Cleared {count} metadata cache entries")
                    if self.console_callback:
                        self.console_callback(f"Cleared {count} video metadata cache entries")
                except Exception as e:
                    self.theme_provider.toast.error("Error", f"Failed to clear metadata cache: {e}")
            else:
                self.theme_provider.toast.warning("Warning", "Metadata cache manager not available")

    def _update_metadata_info(self):
        try:
            if self.get_metadata_info_callback:
                info = self.get_metadata_info_callback()
                entries = info.get('total_entries', 0)
                size_mb = info.get('cache_size_mb', 0)
                self.metadata_info_label.config(text=f"Current cache: {entries} videos, {size_mb:.2f} MB")
            else:
                self.metadata_info_label.config(text="Cache info unavailable")
        except Exception:
            self.metadata_info_label.config(text="Cache info unavailable")

    def _clear_thumbnail_cache(self):
        result = messagebox.askyesno(
            "Confirm Clear Cache",
            "Clear all cached video thumbnails?\n\nThis will remove all stored preview images."
        )
        if result:
            if hasattr(self, 'clear_thumbnails_callback') and self.clear_thumbnails_callback:
                self.clear_thumbnails_callback()
                self._update_thumbnail_info()
                self.theme_provider.toast.info("Cache Cleared", "Thumbnail cache has been cleared")
            else:
                if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
                    self.video_preview_manager.clear_cache()
                    self._update_thumbnail_info()
                else:
                    self.theme_provider.toast.warning("Warning", "Thumbnail cache manager not available")

    def _update_thumbnail_info(self):
        try:
            if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
                self.thumbnail_info_label.config(text="Cache Cleared.")
            else:
                self.thumbnail_info_label.config(text="Cache info unavailable")
        except Exception:
            self.thumbnail_info_label.config(text="Cache info unavailable")

    def _reset_to_defaults(self):
        result = messagebox.askyesno("Confirm Reset", "Reset all settings to default values?")
        if result:
            self._populate_ui_from_settings(SettingsData())
            self.theme_provider.toast.success("Settings Reset", "All settings restored to defaults")

    def _populate_ui_from_settings(self, settings: SettingsData):
        if self.workers_var:
            self.workers_var.set(settings.preprocessing_workers)
        if self.max_frames_var:
            self.max_frames_var.set(settings.max_frames_per_video)
        if self.incremental_var:
            self.incremental_var.set(settings.incremental_preprocessing)
        if self.gpu_acceleration_var:
            self.gpu_acceleration_var.set(settings.enable_gpu_acceleration)
        if self.excluded_dirs_var:
            self.excluded_dirs_var.set(settings.excluded_index_dirs)
        if self.ai_server_url_var:
            self.ai_server_url_var.set(settings.ai_server_url)
        if self.ai_index_path_var:
            self.ai_index_path_var.set(settings.ai_index_path)
        if self.cleanup_days_var:
            self.cleanup_days_var.set(settings.auto_cleanup_days)
        self.preview_duration_var.set(settings.preview_duration)
        self.use_video_preview_var.set(settings.use_video_preview)
        self.enable_watch_history_var.set(settings.enable_watch_history)
        if hasattr(self, 'dual_window_enabled_var'):
            self.dual_window_enabled_var.set(settings.dual_window_enabled)
        if hasattr(self, 'gaming_mode_var'):
            self.gaming_mode_var.set(settings.gaming_mode)
        if hasattr(self, 'show_console_var'):
            self.show_console_var.set(getattr(settings, 'show_console', True))
        if hasattr(self, 'show_annotations_var'):
            self.show_annotations_var.set(settings.show_video_annotations_in_tree)
        if hasattr(self, 'ai_search_enabled_var'):
            self.ai_search_enabled_var.set(settings.ai_search_enabled)
            self._toggle_ai_search_url_state()
        if hasattr(self, '_hotkeys_draft'):
            self._hotkeys_draft = dict(settings.hotkeys)
            badge_bg = getattr(self.theme_provider, 'badge_bg', self.theme_provider.surface_color)
            badge_fg = getattr(self.theme_provider, 'badge_fg', self.theme_provider.text_color)
            badge_border = getattr(self.theme_provider, 'border_color', '#E2E8F0')
            for aid, btn in self._hotkey_btn_map.items():
                btn.config(text=self._hotkeys_draft.get(aid, '—'),
                           bg=badge_bg, fg=badge_fg, relief=tk.FLAT, highlightbackground=badge_border)

    def _apply_current_settings(self):
        if self.workers_var:
            self.settings.preprocessing_workers = self.workers_var.get()
        if self.max_frames_var:
            self.settings.max_frames_per_video = self.max_frames_var.get()
        if self.incremental_var:
            self.settings.incremental_preprocessing = self.incremental_var.get()
        if self.gpu_acceleration_var:
            self.settings.enable_gpu_acceleration = self.gpu_acceleration_var.get()
        if self.excluded_dirs_var:
            self.settings.excluded_index_dirs = self.excluded_dirs_var.get()
        if self.ai_server_url_var:
            self.settings.ai_server_url = self.ai_server_url_var.get().strip()
        if self.ai_index_path_var:
            self.settings.ai_index_path = self.ai_index_path_var.get().strip()
        if self.cleanup_days_var:
            self.settings.auto_cleanup_days = self.cleanup_days_var.get()
        self.settings.preview_duration = self.preview_duration_var.get()
        self.settings.use_video_preview = self.use_video_preview_var.get()
        self.settings.enable_watch_history = self.enable_watch_history_var.get()
        if hasattr(self, 'dual_window_enabled_var'):
            self.settings.dual_window_enabled = self.dual_window_enabled_var.get()
        if hasattr(self, 'gaming_mode_var'):
            self.settings.gaming_mode = self.gaming_mode_var.get()
        if hasattr(self, 'show_annotations_var'):
            self.settings.show_video_annotations_in_tree = self.show_annotations_var.get()
        if hasattr(self, 'show_console_var'):
            if hasattr(self.theme_provider, 'toggle_console'):
                new_val = self.show_console_var.get()
                if new_val != getattr(self.theme_provider, 'show_console', True):
                    self.theme_provider.toggle_console()
        if hasattr(self, '_hotkeys_draft'):
            self.settings.hotkeys = dict(self._hotkeys_draft)
        if hasattr(self, 'ai_search_enabled_var'):
            self.settings.ai_search_enabled = self.ai_search_enabled_var.get()

    def _save_settings(self):
        self._apply_current_settings()
        if self.on_settings_changed:
            self.on_settings_changed(self.settings)
        if self._ai_search_manager is not None:
            try:
                self._ai_search_manager.notify_url_changed()
            except Exception:
                pass
        self.theme_provider.toast.info("Success", "Settings saved successfully!")
        self._close_settings()


class SettingsManager:
    def __init__(self, parent, theme_provider, console_callback: Callable = None, enable_ai: bool = True):
        self.storage = SettingsStorage()
        self.settings = self.storage.load_settings()
        self.ui = SettingsUI(parent, theme_provider, self.settings, console_callback, self._on_settings_changed, enable_ai=enable_ai)

        self._settings_changed_callbacks = []
        self._hotkey_reload_callback: Optional[Callable] = None

    def set_hotkey_reload_callback(self, callback: Callable):
        self._hotkey_reload_callback = callback

    def show_settings(self, tab_index: int = 0):
        self.ui.show_settings_window(tab_index=tab_index)

    def show_embedded(self, parent, close_callback=None, tab_index: int = 0):
        self.ui.show_settings_embedded(parent, close_callback, tab_index=tab_index)

    def get_settings(self) -> SettingsData:
        return self.settings

    def update_setting(self, key: str, value):
        if hasattr(self.settings, key):
            setattr(self.settings, key, value)
            self.storage.save_settings(self.settings)
            self._notify_settings_changed()

    def add_settings_changed_callback(self, callback: Callable):
        self._settings_changed_callbacks.append(callback)

    def _on_settings_changed(self, new_settings: SettingsData):
        self.settings = new_settings
        self.storage.save_settings(self.settings)
        if self._hotkey_reload_callback is not None:
            try:
                self._hotkey_reload_callback(self.settings.hotkeys)
            except Exception as e:
                print(f"[SettingsManager] Error reloading hotkeys: {e}")
        self._notify_settings_changed()

    def _notify_settings_changed(self):
        for callback in self._settings_changed_callbacks:
            try:
                callback(self.settings)
            except Exception as e:
                print(f"Error in settings callback: {e}")