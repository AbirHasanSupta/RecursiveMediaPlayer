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

def _get_app_dirs():
    """Return (appdata_dir, localappdata_dir) for Recursive Media Player."""
    import os, sys
    from pathlib import Path
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




# ---------------------------------------------------------------------------
# Default hotkey bindings.  Keys are stable action identifiers; values are
# the key/combo strings accepted by the `keyboard` library (e.g. 'space',
# 'ctrl+c', 'right').  "mouse_wheel" is handled separately in key_press.py
# and is included here only so the Settings UI can display/edit it.
# ---------------------------------------------------------------------------
DEFAULT_HOTKEYS: Dict[str, str] = {
    # Playback
    "toggle_pause":       "space",
    "stop_video":         "esc",
    "fast_forward":       "right",
    "rewind":             "left",
    # Navigation
    "next_video":         "d",
    "prev_video":         "a",
    "next_directory":     "e",
    "prev_directory":     "q",
    # Audio
    "volume_up":          "w",
    "volume_down":        "s",
    "toggle_mute":        "m",
    # Speed
    "increase_speed":     "=",
    "decrease_speed":     "-",
    "reset_speed":        "0",
    # Display
    "toggle_fullscreen":  "f",
    "rotate_right":       "r",
    "flip_h":              "h",
    "zoom_in":            "ctrl+=",
    "zoom_out":           "ctrl+-",
    "zoom_reset":         "ctrl+0",
    # Tools
    "take_screenshot":    "t",
    "copy_video_path":    "ctrl+c",
    # Chapters
    "next_chapter":       "n",
    "prev_chapter":       "b",
    # Subtitles
    "cycle_subtitle":     "u",
    "disable_subtitles":  "ctrl+u",
    "ab_set_a": "[",
    "ab_set_b": "]",
    "ab_clear": "\\",
}

# Human-readable labels for the Settings UI
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
    "ab_set_a": "A-B Loop: Set point A",
    "ab_set_b": "A-B Loop: Set point B",
    "ab_clear": "A-B Loop: Clear",
}

# Group order for the Settings UI
HOTKEY_GROUPS: list = [
    ("▶  Playback",       ["toggle_pause", "stop_video", "fast_forward", "rewind"]),
    ("📁  Navigation",    ["next_video", "prev_video", "next_directory", "prev_directory"]),
    ("🔊  Audio",         ["volume_up", "volume_down", "toggle_mute"]),
    ("⚡  Speed",          ["increase_speed", "decrease_speed", "reset_speed"]),
    ("🖼  Display",        ["toggle_fullscreen",
                            "rotate_right", "flip_h",
                            "zoom_in", "zoom_out", "zoom_reset"]),
    ("🛠  Tools",          ["take_screenshot", "copy_video_path"]),
    ("📖  Chapters",       ["next_chapter", "prev_chapter"]),
    ("💬  Subtitles",      ["cycle_subtitle", "disable_subtitles"]),
    ("🔁  A-B Loop", ["ab_set_a", "ab_set_b", "ab_clear"]),
]


class SettingsData:
    """Data class for application settings following Single Responsibility Principle"""

    def __init__(self):
        _, _local = _get_app_dirs()
        self.ai_index_path = str(_local / "index_data")
        self.preprocessing_workers = 3
        self.max_frames_per_video = 60
        self.auto_cleanup_days = 30
        self.enable_gpu_acceleration = True
        self.incremental_preprocessing = True
        self.skip_raw_directories = True
        self.preprocessing_batch_size = 10
        self.preview_duration = 3
        self.use_video_preview = True
        self.enable_watch_history = True
        self.dual_window_enabled = False
        # Mutable copy of default hotkeys — users can override individual bindings
        self.hotkeys: Dict[str, str] = dict(DEFAULT_HOTKEYS)

    def to_dict(self) -> dict:
        return {
            'ai_index_path': self.ai_index_path,
            'preprocessing_workers': self.preprocessing_workers,
            'max_frames_per_video': self.max_frames_per_video,
            'auto_cleanup_days': self.auto_cleanup_days,
            'enable_gpu_acceleration': self.enable_gpu_acceleration,
            'incremental_preprocessing': self.incremental_preprocessing,
            'skip_raw_directories': self.skip_raw_directories,
            'preprocessing_batch_size': self.preprocessing_batch_size,
            'preview_duration': self.preview_duration,
            'use_video_preview': self.use_video_preview,
            'enable_watch_history': self.enable_watch_history,
            'dual_window_enabled': self.dual_window_enabled,
            'hotkeys': dict(self.hotkeys),
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
        settings.skip_raw_directories = data.get('skip_raw_directories', settings.skip_raw_directories)
        settings.preprocessing_batch_size = data.get('preprocessing_batch_size', settings.preprocessing_batch_size)
        settings.preview_duration = data.get('preview_duration', settings.preview_duration)
        settings.use_video_preview = data.get('use_video_preview', settings.use_video_preview)
        settings.enable_watch_history = data.get('enable_watch_history', settings.enable_watch_history)
        settings.dual_window_enabled = data.get('dual_window_enabled', settings.dual_window_enabled)
        # Merge saved hotkeys on top of defaults so new actions always have a binding
        saved_hotkeys = data.get('hotkeys', {})
        if isinstance(saved_hotkeys, dict):
            settings.hotkeys.update(saved_hotkeys)
        return settings


class SettingsStorage:
    """Handles settings persistence following Single Responsibility Principle"""

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


class PreprocessingRunner:
    """Handles running AI preprocessing in background"""

    def __init__(self, console_callback: Callable = None):
        self.console_callback = console_callback
        self.current_process = None
        self.is_running = False
        self.output_queue = queue.Queue()

    def start_preprocessing(self, videos_dir: str, settings: SettingsData) -> bool:
        """Start preprocessing in background thread"""
        if self.is_running:
            return False

        self.is_running = True

        def run_preprocessing():
            try:
                script_path = Path(__file__).parent.parent / "enhanced_model.py"
                if not script_path.exists():
                    self._log("Error: enhanced_model.py not found")
                    return

                cmd = [
                    sys.executable,
                    str(script_path),
                    "--mode", "preprocess",
                    "--videos_dir", videos_dir,
                    "--out_dir", settings.ai_index_path,
                    "--workers", str(settings.preprocessing_workers),
                    "--max_frames", str(settings.max_frames_per_video)
                ]

                if settings.incremental_preprocessing:
                    cmd.append("--incremental")
                else:
                    cmd.append("--force_rebuild")

                self._log(f"Starting AI preprocessing...")
                self._log(f"Command: {' '.join(cmd)}")

                self.current_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )

                while self.current_process.poll() is None:
                    line = self.current_process.stdout.readline()
                    if line:
                        self._log(line.strip())

                return_code = self.current_process.wait()

                if return_code == 0:
                    self._log("AI preprocessing completed successfully!")
                else:
                    self._log(f"AI preprocessing failed with return code: {return_code}")

            except Exception as e:
                self._log(f"Error during preprocessing: {e}")
            finally:
                self.is_running = False
                self.current_process = None

        threading.Thread(target=run_preprocessing, daemon=True).start()
        return True

    def stop_preprocessing(self):
        """Stop current preprocessing"""
        if self.current_process:
            try:
                self.current_process.terminate()
                self.current_process.wait(timeout=5)
            except:
                try:
                    self.current_process.kill()
                except:
                    pass
            finally:
                self.current_process = None
                self.is_running = False
                self._log("AI preprocessing stopped by user")

    def _log(self, message: str):
        """Log message to console callback"""
        if self.console_callback:
            self.console_callback(f"[AI Preprocessing] {message}")


class SettingsUI:
    """UI for settings management following Interface Segregation Principle"""

    def __init__(self, parent, theme_provider, settings: SettingsData,
                 console_callback: Callable = None, on_settings_changed: Callable = None,
                 enable_ai: bool = True):
        self.parent = parent
        self.theme_provider = theme_provider
        self.settings = settings
        self.console_callback = console_callback
        self.on_settings_changed = on_settings_changed
        self.enable_ai = enable_ai

        self.settings_window = None
        self.preprocessing_runner = PreprocessingRunner(console_callback)

        self.ai_index_path_var = None
        self.workers_var = None
        self.max_frames_var = None
        self.cleanup_days_var = None
        self.gpu_acceleration_var = None
        self.incremental_var = None
        self.skip_raw_var = None
        self.batch_size_var = None
        self.cleanup_resume_callback = None
        self.cleanup_history_callback = None
        self.clear_thumbnails_callback = None
        self.clear_metadata_callback = None
        self.get_metadata_info_callback = None
        self.filter_sort_manager = None
        # Maps action_id -> tk.Button so the shortcuts tab can update button labels
        self._hotkey_btn_map: Dict[str, tk.Button] = {}

    def show_settings_window(self):
        """Show the settings window"""
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return

        self.settings_window = tk.Toplevel(self.parent)
        self.settings_window.title("Application Settings")
        self.settings_window.geometry("700x880")
        self.settings_window.configure(bg=self.theme_provider.bg_color)
        self.settings_window.resizable(True, True)

        self._setup_settings_ui()
        self.settings_window.transient(self.parent)
        self.settings_window.grab_set()

    def _setup_settings_ui(self):
        """Setup the settings UI components"""
        notebook = ttk.Notebook(self.settings_window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        general_frame = self._create_general_settings_tab(notebook)
        notebook.add(general_frame, text="General Settings")

        if self.enable_ai:
            ai_frame = self._create_ai_settings_tab(notebook)
            notebook.add(ai_frame, text="AI & Preprocessing")

        shortcuts_frame = self._create_shortcuts_tab(notebook)
        notebook.add(shortcuts_frame, text="⌨ Keyboard Shortcuts")

        self._create_action_buttons()

    def _create_ai_settings_tab(self, parent):
        """Create AI settings tab"""
        frame = ttk.Frame(parent)

        main_container = tk.Frame(frame, bg=self.theme_provider.bg_color)
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        path_section = tk.LabelFrame(
            main_container,
            text="AI Index Configuration",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            padx=10,
            pady=10
        )
        path_section.pack(fill=tk.X, pady=(0, 20))

        path_label = tk.Label(
            path_section,
            text="AI Index Data Directory:",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color
        )
        path_label.pack(anchor='w', pady=(0, 5))

        path_frame = tk.Frame(path_section, bg=self.theme_provider.bg_color)
        path_frame.pack(fill=tk.X, pady=(0, 10))

        self.ai_index_path_var = tk.StringVar(value=self.settings.ai_index_path)
        path_entry = tk.Entry(
            path_frame,
            textvariable=self.ai_index_path_var,
            font=self.theme_provider.normal_font,
            bg="white",
            fg=self.theme_provider.text_color,
            relief=tk.FLAT,
            bd=1,
            highlightthickness=1,
            highlightbackground="#e0e0e0"
        )
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        if hasattr(self.theme_provider, 'entry_bg'):
            path_entry.configure(
                bg=self.theme_provider.entry_bg,
                fg=self.theme_provider.entry_fg,
                insertbackground=self.theme_provider.entry_fg,
                highlightbackground=self.theme_provider.entry_border
            )

        browse_btn = self.theme_provider.create_button(
            path_frame, "Browse", self._browse_index_path, "secondary", "sm"
        )
        browse_btn.pack(side=tk.RIGHT)

        self.index_info_label = tk.Label(
            path_section,
            text="",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666"
        )
        self.index_info_label.pack(anchor='w')

        prep_section = tk.LabelFrame(
            main_container,
            text="AI Preprocessing Settings",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            padx=10,
            pady=10
        )
        prep_section.pack(fill=tk.X, pady=(0, 20))

        workers_frame = tk.Frame(prep_section, bg=self.theme_provider.bg_color)
        workers_frame.pack(fill=tk.X, pady=5)

        tk.Label(
            workers_frame,
            text="Processing Workers:",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            width=20,
            anchor='w'
        ).pack(side=tk.LEFT)

        self.workers_var = tk.IntVar(value=self.settings.preprocessing_workers)
        workers_spin = tk.Spinbox(
            workers_frame,
            from_=1,
            to=8,
            textvariable=self.workers_var,
            font=self.theme_provider.normal_font,
            width=10,
            bg="white"
        )
        workers_spin.pack(side=tk.LEFT, padx=(0, 5))

        if hasattr(self.theme_provider, 'entry_bg'):
            workers_spin.configure(
                bg=self.theme_provider.entry_bg,
                fg=self.theme_provider.entry_fg,
                buttonbackground=self.theme_provider.bg_color
            )

        tk.Label(
            workers_frame,
            text="(1-8, recommend 2-4)",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666"
        ).pack(side=tk.LEFT)

        frames_frame = tk.Frame(prep_section, bg=self.theme_provider.bg_color)
        frames_frame.pack(fill=tk.X, pady=5)

        tk.Label(
            frames_frame,
            text="Max Frames per Video:",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            width=20,
            anchor='w'
        ).pack(side=tk.LEFT)

        self.max_frames_var = tk.IntVar(value=self.settings.max_frames_per_video)
        frames_spin = tk.Spinbox(
            frames_frame,
            from_=20,
            to=200,
            textvariable=self.max_frames_var,
            font=self.theme_provider.normal_font,
            width=10,
            bg="white"
        )
        frames_spin.pack(side=tk.LEFT, padx=(0, 5))

        if hasattr(self.theme_provider, 'entry_bg'):
            frames_spin.configure(
                bg=self.theme_provider.entry_bg,
                fg=self.theme_provider.entry_fg,
                buttonbackground=self.theme_provider.bg_color
            )

        tk.Label(
            frames_frame,
            text="(20-200, higher = more accurate)",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666"
        ).pack(side=tk.LEFT)

        self.incremental_var = tk.BooleanVar(value=self.settings.incremental_preprocessing)
        incremental_check = ttk.Checkbutton(
            prep_section,
            text="Incremental Preprocessing (add new videos only)",
            variable=self.incremental_var,
            style="Modern.TCheckbutton"
        )
        incremental_check.pack(anchor='w', pady=2)

        self.gpu_acceleration_var = tk.BooleanVar(value=self.settings.enable_gpu_acceleration)
        gpu_check = ttk.Checkbutton(
            prep_section,
            text="Enable GPU Acceleration (if available)",
            variable=self.gpu_acceleration_var,
            style="Modern.TCheckbutton"
        )
        gpu_check.pack(anchor='w', pady=2)

        self.skip_raw_var = tk.BooleanVar(value=self.settings.skip_raw_directories)
        skip_raw_check = ttk.Checkbutton(
            prep_section,
            text="Skip 'Raw' directories during preprocessing",
            variable=self.skip_raw_var,
            style="Modern.TCheckbutton"
        )
        skip_raw_check.pack(anchor='w', pady=2)

        action_section = tk.LabelFrame(
            main_container,
            text="Run AI Preprocessing",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            padx=10,
            pady=10
        )
        action_section.pack(fill=tk.X)

        action_desc = tk.Label(
            action_section,
            text="Select a directory to preprocess videos for AI search functionality:",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color
        )
        action_desc.pack(anchor='w', pady=(0, 10))

        action_frame = tk.Frame(action_section, bg=self.theme_provider.bg_color)
        action_frame.pack(fill=tk.X)

        self.select_preprocess_btn = self.theme_provider.create_button(
            action_frame, "Select Directory & Start Preprocessing",
            self._start_preprocessing, "primary", "md"
        )
        self.select_preprocess_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.stop_preprocess_btn = self.theme_provider.create_button(
            action_frame, "Stop Preprocessing",
            self._stop_preprocessing, "danger", "md"
        )
        self.stop_preprocess_btn.pack(side=tk.LEFT)
        self.stop_preprocess_btn.pack_forget()

        self._update_index_info()

        return frame

    def _create_general_settings_tab(self, parent):
        """Create general settings tab"""
        frame = ttk.Frame(parent)

        main_container = tk.Frame(frame, bg=self.theme_provider.bg_color)
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        preview_section = tk.LabelFrame(
            main_container,
            text="Video Preview Settings",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            padx=10,
            pady=5
        )
        preview_section.pack(fill=tk.X, pady=(0, 5))

        self.enable_watch_history_var = tk.BooleanVar(value=self.settings.enable_watch_history)
        watch_history_check = ttk.Checkbutton(
            preview_section,
            text="Enable Watch History tracking",
            variable=self.enable_watch_history_var,
            style="Modern.TCheckbutton"
        )
        watch_history_check.pack(anchor='w', pady=1)

        self.show_console_var = tk.BooleanVar(value=getattr(self.theme_provider, 'show_console', True))
        show_console_check = ttk.Checkbutton(
            preview_section,
            text="Show Player Console panel",
            variable=self.show_console_var,
            style="Modern.TCheckbutton"
        )
        show_console_check.pack(anchor='w', pady=(0, 1))

        duration_frame = tk.Frame(preview_section, bg=self.theme_provider.bg_color)
        duration_frame.pack(fill=tk.X, pady=5)

        tk.Label(
            duration_frame,
            text="Preview Duration (sec):",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            width=20,
            anchor='w'
        ).pack(side=tk.LEFT)

        self.preview_duration_var = tk.IntVar(value=self.settings.preview_duration)
        duration_spin = tk.Spinbox(
            duration_frame,
            from_=1,
            to=10,
            textvariable=self.preview_duration_var,
            font=self.theme_provider.normal_font,
            width=10,
            bg="white"
        )
        duration_spin.pack(side=tk.LEFT, padx=(0, 2))

        if hasattr(self.theme_provider, 'entry_bg'):
            duration_spin.configure(
                bg=self.theme_provider.entry_bg,
                fg=self.theme_provider.entry_fg,
                buttonbackground=self.theme_provider.bg_color
            )

        tk.Label(
            duration_frame,
            text="(1-10 seconds)",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666"
        ).pack(side=tk.LEFT)

        self.use_video_preview_var = tk.BooleanVar(value=self.settings.use_video_preview)
        video_preview_check = ttk.Checkbutton(
            preview_section,
            text="Use Video Previews (disable for static thumbnails only)",
            variable=self.use_video_preview_var,
            style="Modern.TCheckbutton"
        )
        video_preview_check.pack(anchor='w', pady=2)

        # ── Player Window Settings ─────────────────────────────────────────────
        player_window_section = tk.LabelFrame(
            main_container,
            text="Player Windows",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            padx=10,
            pady=6
        )
        player_window_section.pack(fill=tk.X, pady=(0, 10))

        self.dual_window_enabled_var = tk.BooleanVar(value=self.settings.dual_window_enabled)
        dual_window_check = ttk.Checkbutton(
            player_window_section,
            text="Enable Second Player Window (each window has 3 players)",
            variable=self.dual_window_enabled_var,
            style="Modern.TCheckbutton"
        )
        dual_window_check.pack(anchor='w', pady=2)

        tk.Label(
            player_window_section,
            text="By default one player window is active with 3 players.\n"
                 "Enabling the second window adds an independent Player Window 2\n"
                 "with its own 3 players — ideal for a second monitor.",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666",
            justify=tk.LEFT
        ).pack(anchor='w', pady=(4, 2))

        thumbnail_btn_frame = tk.Frame(preview_section, bg=self.theme_provider.bg_color)
        thumbnail_btn_frame.pack(fill=tk.X, pady=10)

        self.clear_thumbnails_btn = self.theme_provider.create_button(
            thumbnail_btn_frame, "Clear Preview Cache",
            self._clear_thumbnail_cache, "warning", "sm"
        )
        self.clear_thumbnails_btn.pack(side=tk.LEFT)

        self.thumbnail_info_label = tk.Label(
            preview_section,
            text="",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666"
        )
        self.thumbnail_info_label.pack(anchor='w', pady=(5, 0))

        cache_section = tk.LabelFrame(
            main_container,
            text="Metadata Cache Settings",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            padx=10,
            pady=10
        )
        cache_section.pack(fill=tk.X, pady=(0, 20))

        cache_desc = tk.Label(
            cache_section,
            text="Video metadata cache stores information like resolution, duration, and play statistics.",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666",
            wraplength=600,
            justify=tk.LEFT
        )
        cache_desc.pack(anchor='w', pady=(0, 10))

        cache_btn_frame = tk.Frame(cache_section, bg=self.theme_provider.bg_color)
        cache_btn_frame.pack(fill=tk.X, pady=10)

        self.clear_metadata_btn = self.theme_provider.create_button(
            cache_btn_frame, "Clear Metadata Cache",
            self._clear_metadata_cache, "warning", "sm"
        )
        self.clear_metadata_btn.pack(side=tk.LEFT)

        self.metadata_info_label = tk.Label(
            cache_section,
            text="",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666"
        )
        self.metadata_info_label.pack(anchor='w', pady=(5, 0))

        self._update_metadata_info()

        cleanup_section = tk.LabelFrame(
            main_container,
            text="Data Cleanup Settings",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            padx=10,
            pady=10
        )
        cleanup_section.pack(fill=tk.X, pady=(0, 20))

        cleanup_frame = tk.Frame(cleanup_section, bg=self.theme_provider.bg_color)
        cleanup_frame.pack(fill=tk.X, pady=5)

        tk.Label(
            cleanup_frame,
            text="Auto-cleanup after (days):",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            width=25,
            anchor='w'
        ).pack(side=tk.LEFT)

        self.cleanup_days_var = tk.IntVar(value=self.settings.auto_cleanup_days)
        cleanup_spin = tk.Spinbox(
            cleanup_frame,
            from_=0,
            to=365,
            textvariable=self.cleanup_days_var,
            font=self.theme_provider.normal_font,
            width=10,
            bg="white"
        )
        cleanup_spin.pack(side=tk.LEFT, padx=(0, 5))

        if hasattr(self.theme_provider, 'entry_bg'):
            cleanup_spin.configure(
                bg=self.theme_provider.entry_bg,
                fg=self.theme_provider.entry_fg,
                buttonbackground=self.theme_provider.bg_color
            )

        tk.Label(
            cleanup_frame,
            text="(applies to watch history & resume data)",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666"
        ).pack(side=tk.LEFT)

        manual_cleanup_section = tk.LabelFrame(
            main_container,
            text="Manual Data Management",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            padx=10,
            pady=10
        )
        manual_cleanup_section.pack(fill=tk.X)

        cleanup_btn_frame = tk.Frame(manual_cleanup_section, bg=self.theme_provider.bg_color)
        cleanup_btn_frame.pack(fill=tk.X, pady=10)

        self.cleanup_resume_btn = self.theme_provider.create_button(
            cleanup_btn_frame, "Clean Resume Data",
            self._cleanup_resume_data, "warning", "sm"
        )
        self.cleanup_resume_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.cleanup_history_btn = self.theme_provider.create_button(
            cleanup_btn_frame, "Clean Watch History",
            self._cleanup_watch_history, "warning", "sm"
        )
        self.cleanup_history_btn.pack(side=tk.LEFT)

        return frame

    def _create_shortcuts_tab(self, parent):
        """Create editable Keyboard Shortcuts tab."""
        frame = ttk.Frame(parent)

        main_container = tk.Frame(frame, bg=self.theme_provider.bg_color)
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # ── header ──────────────────────────────────────────────────────────
        tk.Label(
            main_container,
            text="Click a key badge to reassign it.  Press the new key (or combo) when prompted.",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666",
            wraplength=620,
            justify=tk.LEFT
        ).pack(anchor='w', pady=(0, 4))

        conflict_bar_frame = tk.Frame(main_container, bg=self.theme_provider.bg_color)
        conflict_bar_frame.pack(fill=tk.X, pady=(0, 8))
        self._conflict_label = tk.Label(
            conflict_bar_frame,
            text="",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#cc3300",
        )
        self._conflict_label.pack(anchor='w')

        # ── scrollable canvas ────────────────────────────────────────────────
        canvas_frame = tk.Frame(main_container, bg=self.theme_provider.bg_color)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(canvas_frame, bg=self.theme_provider.bg_color, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=self.theme_provider.bg_color)
        canvas_window = canvas.create_window((0, 0), window=inner, anchor='nw')

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))

        def _on_mousewheel(event):
            try:
                if canvas.winfo_exists():
                    canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except Exception:
                pass

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.settings_window.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # ── state for key-capture ────────────────────────────────────────────
        self._capturing_action: Optional[str] = None
        self._capture_overlay: Optional[tk.Toplevel] = None

        # Working copy of hotkeys (not committed until Save is pressed)
        self._hotkeys_draft: Dict[str, str] = dict(self.settings.hotkeys)
        # Reset the button map for this window instance
        self._hotkey_btn_map = {}

        # badge colours
        badge_bg = getattr(self.theme_provider, 'badge_bg', '#e8e8e8')
        badge_fg = getattr(self.theme_provider, 'badge_fg', '#333333')
        active_bg = getattr(self.theme_provider, 'accent_color', '#0078d4')

        KEY_COL_W = 20

        def _start_capture(action_id: str, btn: tk.Button):
            """Open a small overlay that waits for a single keypress."""
            if self._capturing_action is not None:
                return  # already capturing

            self._capturing_action = action_id
            self._conflict_label.config(text="")

            # Dim the button to show it's "armed"
            btn.config(bg=active_bg, fg='white', relief=tk.SUNKEN)

            overlay = tk.Toplevel(self.settings_window)
            overlay.title("Press new key…")
            overlay.geometry("340x120")
            overlay.configure(bg=self.theme_provider.bg_color)
            overlay.transient(self.settings_window)
            overlay.grab_set()
            overlay.resizable(False, False)
            self._capture_overlay = overlay

            action_label = HOTKEY_LABELS.get(action_id, action_id)
            tk.Label(
                overlay,
                text=f"Reassigning:  {action_label}",
                font=self.theme_provider.normal_font,
                bg=self.theme_provider.bg_color,
                fg=self.theme_provider.text_color,
                wraplength=300
            ).pack(pady=(18, 6))

            tk.Label(
                overlay,
                text="Press any key or combo  (Esc = cancel)",
                font=self.theme_provider.small_font,
                bg=self.theme_provider.bg_color,
                fg="#888888"
            ).pack()

            def _finish_capture(event):
                # ── Step 1: identify the main key, ignoring bare modifiers ──
                keysym_raw = event.keysym.lower()

                # Skip bare modifier keypresses entirely
                if keysym_raw in ('control_l', 'control_r', 'shift_l', 'shift_r',
                                  'alt_l', 'alt_r', 'super_l', 'super_r',
                                  'caps_lock', 'num_lock', 'scroll_lock'):
                    return

                # Esc with NO other real key held → cancel (check raw keysym first,
                # before we inspect state, to avoid the spurious-Alt problem on Windows)
                if keysym_raw == 'escape':
                    _cancel()
                    return

                # ── Step 2: detect held modifiers via keysym names, NOT event.state ──
                # event.state is unreliable on Windows (spurious Alt bit after grab_set).
                # Instead we ask Tk which modifier keys are physically pressed right now.
                mods = []
                try:
                    # widget.tk.call returns a list of currently-pressed keys
                    pressed = overlay.tk.call('::tk::PressedKeys') if False else []
                except Exception:
                    pressed = []

                # Fallback: use event.state but mask out the known-spurious Alt bit (0x8)
                # that Windows sets after grab_set/focus_force.  We still honour Ctrl (0x4)
                # and Shift (0x1) from state because those don't suffer the same issue.
                # Alt is only added if the keysym itself tells us it was held.
                if event.state & 0x4:
                    mods.append('ctrl')
                if event.state & 0x1:
                    mods.append('shift')
                # Alt: only trust it when the previous event's keysym was alt_l/alt_r,
                # i.e. when there is actual evidence in the keysym stream.
                # The simplest safe approach: never infer Alt from state alone.
                # Users who want Alt+X can press Alt first (it gets filtered above only
                # for *bare* Alt presses), then X — at that point keysym_raw will be
                # something like 'a' and state will have bit 0x20000 on Windows or 0x8
                # on X11.  We honour the X11 bit only when keysym_raw is NOT 'escape'.
                if (event.state & 0x20000) or (event.state & 0x8 and keysym_raw != 'escape'):
                    # Double-check: if the previous keydown was actually an alt key,
                    # include alt.  We use a simpler heuristic: only add 'alt' when
                    # event.state has the bit AND the char produced is not a normal char
                    # (alt on Windows produces odd chars via AltGr etc.).
                    # Safe approach: skip adding 'alt' from state — users wanting
                    # Alt combos are rare for a video player and it avoids all bugs.
                    pass  # intentionally not adding alt from state bits

                # Normalise keysym to the strings the `keyboard` library expects
                _norm = {
                    'return':    'enter',
                    'prior':     'page_up',
                    'next':      'page_down',
                    'equal':     '=',
                    'minus':     '-',
                    'plus':      '+',
                    'bracketleft':  '[',
                    'bracketright': ']',
                    'semicolon': ';',
                    'apostrophe': "'",
                    'comma':     ',',
                    'period':    '.',
                    'slash':     '/',
                    'backslash': '\\',
                    'grave':     '`',
                    'space':     'space',
                    'tab':       'tab',
                    'delete':    'delete',
                    'backspace': 'backspace',
                    'insert':    'insert',
                    'home':      'home',
                    'end':       'end',
                    'f1': 'f1', 'f2': 'f2', 'f3': 'f3', 'f4': 'f4',
                    'f5': 'f5', 'f6': 'f6', 'f7': 'f7', 'f8': 'f8',
                    'f9': 'f9', 'f10': 'f10', 'f11': 'f11', 'f12': 'f12',
                    'up': 'up', 'down': 'down', 'left': 'left', 'right': 'right',
                }
                keysym = _norm.get(keysym_raw, keysym_raw)

                combo = '+'.join(mods + [keysym]) if mods else keysym

                # ── Step 3: detect collision and swap if needed ──────────────
                conflict_action = None
                for aid, k in self._hotkeys_draft.items():
                    if k == combo and aid != action_id:
                        conflict_action = aid
                        break

                old_combo = self._hotkeys_draft.get(action_id, '')

                if conflict_action:
                    # Swap: give the displaced action the key we are moving away from
                    self._hotkeys_draft[conflict_action] = old_combo
                    displaced_label = HOTKEY_LABELS.get(conflict_action, conflict_action)
                    # Update the displaced action's button label immediately
                    displaced_btn = self._hotkey_btn_map.get(conflict_action)
                    if displaced_btn and displaced_btn.winfo_exists():
                        displaced_btn.config(text=old_combo or '—',
                                             bg=badge_bg, fg=badge_fg, relief=tk.GROOVE)
                    try:
                        self._conflict_label.config(
                            text=f"↔  Swapped: '{displaced_label}' is now '{old_combo or '—'}'"
                        )
                    except Exception:
                        pass

                # ── Step 4: commit this action's new binding ──────────────────
                self._hotkeys_draft[action_id] = combo
                try:
                    if btn.winfo_exists():
                        btn.config(text=combo, bg=badge_bg, fg=badge_fg, relief=tk.GROOVE)
                    if not conflict_action:
                        self._conflict_label.config(text="")
                except Exception:
                    pass
                _close_overlay()
                self._capturing_action = None

            def _cancel(revert=True):
                if revert:
                    btn.config(bg=badge_bg, fg=badge_fg, relief=tk.GROOVE)
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

        def _add_group(parent_frame, title, action_ids):
            section = tk.LabelFrame(
                parent_frame,
                text=title,
                font=self.theme_provider.normal_font,
                bg=self.theme_provider.bg_color,
                fg=self.theme_provider.text_color,
                padx=10, pady=6
            )
            section.pack(fill=tk.X, pady=(0, 12))

            hdr = tk.Frame(section, bg=self.theme_provider.bg_color)
            hdr.pack(fill=tk.X, pady=(0, 4))
            tk.Label(hdr, text="Key / Combo", font=self.theme_provider.small_font,
                     bg=self.theme_provider.bg_color, fg="#999999",
                     width=KEY_COL_W, anchor='w').pack(side=tk.LEFT)
            tk.Label(hdr, text="Action", font=self.theme_provider.small_font,
                     bg=self.theme_provider.bg_color, fg="#999999",
                     anchor='w').pack(side=tk.LEFT)

            tk.Frame(section, bg="#dddddd", height=1).pack(fill=tk.X, pady=(0, 6))

            alt_row = getattr(self.theme_provider, 'alt_row_color', self.theme_provider.bg_color)
            for i, action_id in enumerate(action_ids):
                current_key = self._hotkeys_draft.get(action_id, '—')
                action_label = HOTKEY_LABELS.get(action_id, action_id)
                row_bg = alt_row if i % 2 else self.theme_provider.bg_color

                row = tk.Frame(section, bg=row_bg)
                row.pack(fill=tk.X, pady=1)

                btn = tk.Button(
                    row,
                    text=current_key,
                    font=self.theme_provider.normal_font,
                    bg=badge_bg, fg=badge_fg,
                    relief=tk.GROOVE, bd=1,
                    padx=6, pady=2,
                    width=KEY_COL_W,
                    anchor='w',
                    cursor='hand2',
                )
                # Capture btn in closure
                btn.config(command=lambda aid=action_id, b=btn: _start_capture(aid, b))
                btn.pack(side=tk.LEFT, padx=(0, 10))
                self._hotkey_btn_map[action_id] = btn

                tk.Label(
                    row,
                    text=action_label,
                    font=self.theme_provider.normal_font,
                    bg=row_bg,
                    fg=self.theme_provider.text_color,
                    anchor='w'
                ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        for group_title, action_ids in HOTKEY_GROUPS:
            _add_group(inner, group_title, action_ids)

        # ── Reset shortcuts button ───────────────────────────────────────────
        reset_frame = tk.Frame(main_container, bg=self.theme_provider.bg_color)
        reset_frame.pack(fill=tk.X, pady=(8, 0))

        def _reset_shortcuts():
            if messagebox.askyesno("Reset Shortcuts",
                                   "Reset all keyboard shortcuts to their defaults?"):
                self._hotkeys_draft = dict(DEFAULT_HOTKEYS)
                self._conflict_label.config(text="")
                for aid, btn in self._hotkey_btn_map.items():
                    btn.config(text=self._hotkeys_draft.get(aid, '—'),
                               bg=badge_bg, fg=badge_fg, relief=tk.GROOVE)

        self.theme_provider.create_button(
            reset_frame, "Reset Shortcuts to Defaults", _reset_shortcuts, "warning", "sm"
        ).pack(side=tk.LEFT)

        return frame

    def _create_action_buttons(self):
        """Create action buttons at bottom of window"""
        button_frame = tk.Frame(self.settings_window, bg=self.theme_provider.bg_color)
        button_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=20, pady=20)

        reset_btn = self.theme_provider.create_button(
            button_frame, "Reset to Defaults", self._reset_to_defaults, "warning", "md"
        )
        reset_btn.pack(side=tk.LEFT)

        cancel_btn = self.theme_provider.create_button(
            button_frame, "Cancel", self.settings_window.destroy, "secondary", "md"
        )
        cancel_btn.pack(side=tk.RIGHT, padx=(5, 0))

        save_btn = self.theme_provider.create_button(
            button_frame, "Save Settings", self._save_settings, "primary", "md"
        )
        save_btn.pack(side=tk.RIGHT)

    def _browse_index_path(self):
        """Browse for AI index directory"""
        current_path = self.ai_index_path_var.get()
        initial_dir = os.path.dirname(current_path) if os.path.exists(current_path) else os.path.expanduser("~")

        directory = filedialog.askdirectory(
            title="Select AI Index Data Directory",
            initialdir=initial_dir
        )

        if directory:
            self.ai_index_path_var.set(directory)
            self._update_index_info()

    def _update_index_info(self):
        """Update index information display"""
        if not self.ai_index_path_var or not self.index_info_label:
            return
        index_path = self.ai_index_path_var.get()

        if not os.path.exists(index_path):
            info_text = "Directory does not exist - will be created when needed"
        else:
            required_files = ["clip_index.faiss", "text_index.faiss", "metadata.pkl", "tfidf_index.pkl"]
            existing_files = [f for f in required_files if os.path.exists(os.path.join(index_path, f))]

            if len(existing_files) == len(required_files):
                try:
                    import pickle
                    metadata_path = os.path.join(index_path, "metadata.pkl")
                    with open(metadata_path, 'rb') as f:
                        metadata = pickle.load(f)
                    video_count = len(metadata.get('video_paths', []))
                    info_text = f"Valid AI index found - {video_count} videos indexed"
                except:
                    info_text = "AI index files found"
            elif existing_files:
                info_text = f"Incomplete index ({len(existing_files)}/{len(required_files)} files) - needs preprocessing"
            else:
                info_text = "Empty directory - needs preprocessing"

        self.index_info_label.config(text=info_text)

    def _start_preprocessing(self):
        """Start AI preprocessing"""
        self._apply_current_settings()

        directory = filedialog.askdirectory(
            title="Select Directory to Preprocess for AI Search"
        )

        if not directory:
            return

        result = messagebox.askyesno(
            "Confirm Preprocessing",
            f"Start AI preprocessing for:\n{directory}\n\n"
            f"Output directory: {self.settings.ai_index_path}\n"
            f"Workers: {self.settings.preprocessing_workers}\n"
            f"Max frames: {self.settings.max_frames_per_video}\n"
            f"Mode: {'Incremental' if self.settings.incremental_preprocessing else 'Full rebuild'}\n\n"
            "This may take a long time for large video collections. Continue?"
        )

        if result:
            success = self.preprocessing_runner.start_preprocessing(directory, self.settings)
            if success:
                self.select_preprocess_btn.pack_forget()
                self.stop_preprocess_btn.pack(side=tk.LEFT)
            else:
                messagebox.showerror("Error", "Failed to start preprocessing - another process may be running")

    def _stop_preprocessing(self):
        """Stop preprocessing"""
        result = messagebox.askyesno("Confirm Stop", "Stop AI preprocessing?")
        if result:
            self.preprocessing_runner.stop_preprocessing()
            self.stop_preprocess_btn.pack_forget()
            self.select_preprocess_btn.pack(side=tk.LEFT, padx=(0, 10))

    def _cleanup_resume_data(self):
        """Clean up old resume data"""
        result = messagebox.askyesno(
            "Confirm Cleanup",
            "Clean up old resume position data?\n\nThis will remove positions older than the configured cleanup period."
        )
        if result:
            if self.cleanup_resume_callback:
                try:
                    self._apply_current_settings()
                    count = self.cleanup_resume_callback()
                    messagebox.showinfo("Cleanup Complete", f"Cleaned up {count} old resume entries")
                    if self.console_callback:
                        self.console_callback(f"Cleaned up {count} old resume position entries")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to cleanup resume data: {e}")
            else:
                messagebox.showwarning("Warning", "Resume cleanup function not available")

    def _cleanup_watch_history(self):
        """Clean up old watch history"""
        result = messagebox.askyesno(
            "Confirm Cleanup",
            "Clean up old watch history data?\n\nThis will remove history older than the configured cleanup period."
        )
        if result:
            if self.cleanup_history_callback:
                try:
                    count = self.cleanup_history_callback()
                    messagebox.showinfo("Cleanup Complete", f"Cleaned up {count} old history entries")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to cleanup watch history: {e}")
            else:
                messagebox.showwarning("Warning", "History cleanup function not available")

    def _clear_metadata_cache(self):
        """Clear video metadata cache"""
        result = messagebox.askyesno(
            "Confirm Clear Cache",
            "Clear all cached video metadata?\n\nThis will remove stored information like resolution, duration, and play statistics. The data will be regenerated when needed."
        )

        if result:
            if self.clear_metadata_callback:
                try:
                    count = self.clear_metadata_callback()
                    self._update_metadata_info()
                    messagebox.showinfo("Cache Cleared", f"Cleared {count} metadata cache entries")
                    if self.console_callback:
                        self.console_callback(f"Cleared {count} video metadata cache entries")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to clear metadata cache: {e}")
            else:
                messagebox.showwarning("Warning", "Metadata cache manager not available")

    def _update_metadata_info(self):
        """Update metadata cache information display"""
        try:
            if self.get_metadata_info_callback:
                info = self.get_metadata_info_callback()
                entries = info.get('total_entries', 0)
                size_mb = info.get('cache_size_mb', 0)
                self.metadata_info_label.config(
                    text=f"Current cache: {entries} videos, {size_mb:.2f} MB"
                )
            else:
                self.metadata_info_label.config(text="Cache info unavailable")
        except Exception as e:
            self.metadata_info_label.config(text="Cache info unavailable")

    def _clear_thumbnail_cache(self):
        """Clear video thumbnail cache"""
        result = messagebox.askyesno(
            "Confirm Clear Cache",
            "Clear all cached video thumbnails?\n\nThis will remove all stored preview images."
        )

        if result:
            if hasattr(self, 'clear_thumbnails_callback') and self.clear_thumbnails_callback:
                self.clear_thumbnails_callback()
                self._update_thumbnail_info()
                messagebox.showinfo("Cache Cleared", "Thumbnail cache has been cleared")
            else:
                if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
                    self.video_preview_manager.clear_cache()
                    self._update_thumbnail_info()
                else:
                    messagebox.showwarning("Warning", "Thumbnail cache manager not available")

    def _update_thumbnail_info(self):
        """Update thumbnail cache information"""
        try:
            if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
                self.thumbnail_info_label.config(text="Cache Cleared.")
            else:
                self.thumbnail_info_label.config(text="Cache info unavailable")
        except Exception as e:
            self.thumbnail_info_label.config(text="Cache info unavailable")

    def _reset_to_defaults(self):
        """Reset settings to default values"""
        result = messagebox.askyesno("Confirm Reset", "Reset all settings to default values?")
        if result:
            default_settings = SettingsData()
            self._populate_ui_from_settings(default_settings)

    def _populate_ui_from_settings(self, settings: SettingsData):
        """Populate UI fields from settings object"""
        if self.ai_index_path_var:
            self.ai_index_path_var.set(settings.ai_index_path)
        if self.workers_var:
            self.workers_var.set(settings.preprocessing_workers)
        if self.max_frames_var:
            self.max_frames_var.set(settings.max_frames_per_video)
        if self.cleanup_days_var:
            self.cleanup_days_var.set(settings.auto_cleanup_days)
        if self.gpu_acceleration_var:
            self.gpu_acceleration_var.set(settings.enable_gpu_acceleration)
        if self.incremental_var:
            self.incremental_var.set(settings.incremental_preprocessing)
        if self.skip_raw_var:
            self.skip_raw_var.set(settings.skip_raw_directories)
        self.preview_duration_var.set(settings.preview_duration)
        self.use_video_preview_var.set(settings.use_video_preview)
        self.enable_watch_history_var.set(settings.enable_watch_history)
        if hasattr(self, 'dual_window_enabled_var'):
            self.dual_window_enabled_var.set(settings.dual_window_enabled)
        if hasattr(self, 'show_console_var'):
            self.show_console_var.set(getattr(settings, 'show_console', True))
        # Refresh the shortcuts tab draft + button labels if the tab exists
        if hasattr(self, '_hotkeys_draft'):
            self._hotkeys_draft = dict(settings.hotkeys)
            badge_bg = getattr(self.theme_provider, 'badge_bg', '#e8e8e8')
            badge_fg = getattr(self.theme_provider, 'badge_fg', '#333333')
            for aid, btn in self._hotkey_btn_map.items():
                btn.config(text=self._hotkeys_draft.get(aid, '—'),
                           bg=badge_bg, fg=badge_fg, relief=tk.GROOVE)
        self._update_index_info()

    def _apply_current_settings(self):
        """Apply current UI values to settings object"""
        if self.ai_index_path_var:
            self.settings.ai_index_path = self.ai_index_path_var.get()
        if self.workers_var:
            self.settings.preprocessing_workers = self.workers_var.get()
        if self.max_frames_var:
            self.settings.max_frames_per_video = self.max_frames_var.get()
        if self.cleanup_days_var:
            self.settings.auto_cleanup_days = self.cleanup_days_var.get()
        if self.gpu_acceleration_var:
            self.settings.enable_gpu_acceleration = self.gpu_acceleration_var.get()
        if self.incremental_var:
            self.settings.incremental_preprocessing = self.incremental_var.get()
        if self.skip_raw_var:
            self.settings.skip_raw_directories = self.skip_raw_var.get()
        self.settings.preview_duration = self.preview_duration_var.get()
        self.settings.use_video_preview = self.use_video_preview_var.get()
        self.settings.enable_watch_history = self.enable_watch_history_var.get()
        if hasattr(self, 'dual_window_enabled_var'):
            self.settings.dual_window_enabled = self.dual_window_enabled_var.get()

        if hasattr(self, 'show_console_var'):
            if hasattr(self.theme_provider, 'toggle_console'):
                new_val = self.show_console_var.get()
                if new_val != getattr(self.theme_provider, 'show_console', True):
                    self.theme_provider.toggle_console()
        # Commit the draft hotkeys edited in the shortcuts tab
        if hasattr(self, '_hotkeys_draft'):
            self.settings.hotkeys = dict(self._hotkeys_draft)

    def _save_settings(self):
        """Save current settings"""
        self._apply_current_settings()

        if self.on_settings_changed:
            self.on_settings_changed(self.settings)

        messagebox.showinfo("Success", "Settings saved successfully!")
        self.settings_window.destroy()


class SettingsManager:
    """Main settings manager following Dependency Inversion Principle"""

    def __init__(self, parent, theme_provider, console_callback: Callable = None, enable_ai: bool = True):
        self.storage = SettingsStorage()
        self.settings = self.storage.load_settings()
        self.ui = SettingsUI(parent, theme_provider, self.settings, console_callback, self._on_settings_changed, enable_ai=enable_ai)

        self._settings_changed_callbacks = []
        # Optional callback that re-registers hotkeys in the player immediately.
        # Set via set_hotkey_reload_callback(fn) where fn(hotkeys: dict) -> None.
        self._hotkey_reload_callback: Optional[Callable] = None

    def set_hotkey_reload_callback(self, callback: Callable):
        """Register a function called with the new hotkeys dict every time the
        user saves the Settings window.  Typically::

            settings_manager.set_hotkey_reload_callback(
                lambda hk: reload_hotkeys(controller, hk)
            )
        """
        self._hotkey_reload_callback = callback

    def show_settings(self):
        """Show settings window"""
        self.ui.show_settings_window()

    def get_settings(self) -> SettingsData:
        """Get current settings"""
        return self.settings

    def update_setting(self, key: str, value):
        """Update a specific setting"""
        if hasattr(self.settings, key):
            setattr(self.settings, key, value)
            self.storage.save_settings(self.settings)
            self._notify_settings_changed()

    def add_settings_changed_callback(self, callback: Callable):
        """Add callback for when settings change"""
        self._settings_changed_callbacks.append(callback)

    def _on_settings_changed(self, new_settings: SettingsData):
        """Handle settings change from UI"""
        self.settings = new_settings
        self.storage.save_settings(self.settings)
        if self._hotkey_reload_callback is not None:
            try:
                self._hotkey_reload_callback(self.settings.hotkeys)
            except Exception as e:
                print(f"[SettingsManager] Error reloading hotkeys: {e}")
        self._notify_settings_changed()

    def _notify_settings_changed(self):
        """Notify all callbacks about settings change"""
        for callback in self._settings_changed_callbacks:
            try:
                callback(self.settings)
            except Exception as e:
                print(f"Error in settings callback: {e}")