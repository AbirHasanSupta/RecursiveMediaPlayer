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


class SettingsData:
    """Data class for application settings following Single Responsibility Principle"""

    def __init__(self):
        self.ai_index_path = r"C:\Users\Abir\Documents\Recursive Media Player\index_data"
        self.preprocessing_workers = 3
        self.max_frames_per_video = 60
        self.auto_cleanup_days = 30
        self.enable_gpu_acceleration = True
        self.incremental_preprocessing = True
        self.skip_raw_directories = True
        self.preprocessing_batch_size = 10

    def to_dict(self) -> dict:
        return {
            'ai_index_path': self.ai_index_path,
            'preprocessing_workers': self.preprocessing_workers,
            'max_frames_per_video': self.max_frames_per_video,
            'auto_cleanup_days': self.auto_cleanup_days,
            'enable_gpu_acceleration': self.enable_gpu_acceleration,
            'incremental_preprocessing': self.incremental_preprocessing,
            'skip_raw_directories': self.skip_raw_directories,
            'preprocessing_batch_size': self.preprocessing_batch_size
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
        return settings


class SettingsStorage:
    """Handles settings persistence following Single Responsibility Principle"""

    def __init__(self):
        self.settings_dir = Path.home() / "Documents" / "Recursive Media Player"
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
                script_path = Path(__file__).parent / "enhanced_model.py"
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
                 console_callback: Callable = None, on_settings_changed: Callable = None):
        self.parent = parent
        self.theme_provider = theme_provider
        self.settings = settings
        self.console_callback = console_callback
        self.on_settings_changed = on_settings_changed

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

    def show_settings_window(self):
        """Show the settings window"""
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return

        self.settings_window = tk.Toplevel(self.parent)
        self.settings_window.title("Application Settings")
        self.settings_window.geometry("700x800")
        self.settings_window.configure(bg=self.theme_provider.bg_color)
        self.settings_window.resizable(True, True)

        self._setup_settings_ui()

    def _setup_settings_ui(self):
        """Setup the settings UI components"""
        notebook = ttk.Notebook(self.settings_window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        ai_frame = self._create_ai_settings_tab(notebook)
        notebook.add(ai_frame, text="AI & Preprocessing")

        general_frame = self._create_general_settings_tab(notebook)
        notebook.add(general_frame, text="General Settings")

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
            variable=self.incremental_var
        )
        incremental_check.pack(anchor='w', pady=2)

        self.gpu_acceleration_var = tk.BooleanVar(value=self.settings.enable_gpu_acceleration)
        gpu_check = ttk.Checkbutton(
            prep_section,
            text="Enable GPU Acceleration (if available)",
            variable=self.gpu_acceleration_var
        )
        gpu_check.pack(anchor='w', pady=2)

        self.skip_raw_var = tk.BooleanVar(value=self.settings.skip_raw_directories)
        skip_raw_check = ttk.Checkbutton(
            prep_section,
            text="Skip 'Raw' directories during preprocessing",
            variable=self.skip_raw_var
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


        thumbnail_section = tk.LabelFrame(
            main_container,
            text="Thumbnail Cache Management",
            font=self.theme_provider.normal_font,
            bg=self.theme_provider.bg_color,
            fg=self.theme_provider.text_color,
            padx=10,
            pady=10
        )
        thumbnail_section.pack(fill=tk.X, pady=(0, 20))

        thumbnail_btn_frame = tk.Frame(thumbnail_section, bg=self.theme_provider.bg_color)
        thumbnail_btn_frame.pack(fill=tk.X, pady=10)

        self.clear_thumbnails_btn = self.theme_provider.create_button(
            thumbnail_btn_frame, "Clear Thumbnail Cache",
            self._clear_thumbnail_cache, "warning", "sm"
        )
        self.clear_thumbnails_btn.pack(side=tk.LEFT)

        self.thumbnail_info_label = tk.Label(
            thumbnail_section,
            text="",
            font=self.theme_provider.small_font,
            bg=self.theme_provider.bg_color,
            fg="#666666"
        )
        self.thumbnail_info_label.pack(anchor='w', pady=(5, 0))

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
            from_=1,
            to=365,
            textvariable=self.cleanup_days_var,
            font=self.theme_provider.normal_font,
            width=10,
            bg="white"
        )
        cleanup_spin.pack(side=tk.LEFT, padx=(0, 5))

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
            if hasattr(self, 'cleanup_resume_callback') and self.cleanup_resume_callback:
                try:
                    count = self.cleanup_resume_callback()
                    messagebox.showinfo("Cleanup Complete", f"Cleaned up {count} old resume entries")
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
            if hasattr(self, 'cleanup_history_callback') and self.cleanup_history_callback:
                try:
                    count = self.cleanup_history_callback()
                    messagebox.showinfo("Cleanup Complete", f"Cleaned up {count} old history entries")
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to cleanup watch history: {e}")
            else:
                messagebox.showwarning("Warning", "History cleanup function not available")

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
                messagebox.showinfo("Success", "Thumbnail cache cleared successfully")
            else:
                if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
                    self.video_preview_manager.clear_cache()
                    self._update_thumbnail_info()
                    messagebox.showinfo("Success", "Thumbnail cache cleared successfully")
                else:
                    messagebox.showwarning("Warning", "Thumbnail cache manager not available")

    def _update_thumbnail_info(self):
        """Update thumbnail cache information"""
        try:
            if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
                stats = self.video_preview_manager.get_cache_stats()
                info_text = f"Cache: {stats.get('total_thumbnails', 0)} thumbnails ({stats.get('cache_size_mb', 0):.1f}MB)"
                self.thumbnail_info_label.config(text=info_text)
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
        self.ai_index_path_var.set(settings.ai_index_path)
        self.workers_var.set(settings.preprocessing_workers)
        self.max_frames_var.set(settings.max_frames_per_video)
        self.cleanup_days_var.set(settings.auto_cleanup_days)
        self.gpu_acceleration_var.set(settings.enable_gpu_acceleration)
        self.incremental_var.set(settings.incremental_preprocessing)
        self.skip_raw_var.set(settings.skip_raw_directories)
        self._update_index_info()

    def _apply_current_settings(self):
        """Apply current UI values to settings object"""
        self.settings.ai_index_path = self.ai_index_path_var.get()
        self.settings.preprocessing_workers = self.workers_var.get()
        self.settings.max_frames_per_video = self.max_frames_var.get()
        self.settings.auto_cleanup_days = self.cleanup_days_var.get()
        self.settings.enable_gpu_acceleration = self.gpu_acceleration_var.get()
        self.settings.incremental_preprocessing = self.incremental_var.get()
        self.settings.skip_raw_directories = self.skip_raw_var.get()

    def _save_settings(self):
        """Save current settings"""
        self._apply_current_settings()

        if self.on_settings_changed:
            self.on_settings_changed(self.settings)

        messagebox.showinfo("Success", "Settings saved successfully!")
        self.settings_window.destroy()


class SettingsManager:
    """Main settings manager following Dependency Inversion Principle"""

    def __init__(self, parent, theme_provider, console_callback: Callable = None):
        self.storage = SettingsStorage()
        self.settings = self.storage.load_settings()
        self.ui = SettingsUI(parent, theme_provider, self.settings, console_callback, self._on_settings_changed)

        self._settings_changed_callbacks = []

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
        self._notify_settings_changed()

    def _notify_settings_changed(self):
        """Notify all callbacks about settings change"""
        for callback in self._settings_changed_callbacks:
            try:
                callback(self.settings)
            except Exception as e:
                print(f"Error in settings callback: {e}")