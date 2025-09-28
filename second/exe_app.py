import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from tkinter.font import Font
import os
import multiprocessing
from concurrent.futures import ProcessPoolExecutor

from key_press import listen_keys, cleanup_hotkeys
from theme import ThemeSelector
from utils import gather_videos_with_directories, is_video
from vlc_player_controller import VLCPlayerControllerForMultipleDirectory
from playlist_manager import PlaylistManager
from watch_history_manager import WatchHistoryManager
from resume_playback_manager import ResumePlaybackManager
from settings_manager import SettingsManager


def select_multiple_folders_and_play():
    class DirectorySelector(ThemeSelector):
        def __init__(self, root):
            super().__init__()
            self.root = root
            self.selected_dirs = []
            self.excluded_subdirs = {}
            self.excluded_videos = {}
            self.controller = None
            self.player_thread = None
            self.keys_thread = None
            self.video_count = 0
            self.current_selected_dir_index = None
            self.current_subdirs_mapping = {}
            self.show_videos = True
            self.show_only_excluded = False
            self.ai_mode = False
            self.ai_searcher = None
            self.ai_index_path = None
            self.current_max_depth = 20

            preferences = self.config.load_preferences()
            self.dark_mode = preferences['dark_mode']
            self.show_videos = preferences['show_videos']
            self.expand_all_default = preferences['expand_all']
            self.save_directories = preferences['save_directories']
            self.start_from_last_played = preferences['start_from_last_played']
            self.resume_from_position = preferences.get('resume_from_position', True)
            self.last_played_video_index = preferences['last_played_video_index']
            self.last_played_video_path = preferences['last_played_video_path']
            self.excluded_subdirs = preferences.get('excluded_subdirs', {})
            self.excluded_videos = preferences.get('excluded_videos', {})

            self.setup_theme()

            root.title("Recursive Video Player")
            root.geometry("1200x800")
            root.protocol("WM_DELETE_WINDOW", self.cancel)
            root.configure(bg=self.bg_color)

            self.setup_main_layout()
            self.setup_directory_section()
            self.setup_exclusion_section()
            self.setup_status_section()
            self.setup_console_section()
            self.setup_action_buttons()

            self.scan_cache = {}
            self.pending_scans = set()
            max_workers = min(8, (os.cpu_count() or 4))
            self.executor = ProcessPoolExecutor(max_workers=max_workers)
            self.update_console(f"Scanner ready (process workers: {max_workers})")
            self.apply_theme()
            if self.save_directories:
                self.selected_dirs = preferences.get('selected_dirs', [])
                for directory in self.selected_dirs:
                    display_name = directory
                    if len(directory) > 60:
                        display_name = os.path.basename(directory)
                        parent = os.path.dirname(directory)
                        if parent:
                            display_name = f"{os.path.basename(parent)}/{display_name}"
                        display_name = f".../{display_name}"
                    self.dir_listbox.insert(tk.END, display_name)
                    self._submit_scan(directory)
            else:
                self.selected_dirs = []

            self.update_ui_for_mode()
            self.playlist_manager = PlaylistManager(self.root, self)
            self.playlist_manager.set_play_callback(self._play_playlist_videos)
            self.watch_history_manager = WatchHistoryManager(self.root, self)
            self.resume_manager = ResumePlaybackManager()
            self.resume_manager.set_resume_enabled(True)
            self.settings_manager = SettingsManager(self.root, self, self.update_console)
            self.settings_manager.add_settings_changed_callback(self._on_settings_changed)

            app_settings = self.settings_manager.get_settings()
            self.ai_index_path = app_settings.ai_index_path
            self.settings_manager.ui.cleanup_resume_callback = lambda: self.resume_manager.cleanup_old_positions()
            self.settings_manager.ui.cleanup_history_callback = lambda: self._cleanup_watch_history_data()

        def setup_theme(self):
            self.bg_color = "#f5f5f5"
            self.accent_color = "#3498db"
            self.text_color = "#333333"

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
                foreground=[("active", self.text_color)],
                background=[("active", self.bg_color)]
            )

            self.create_custom_buttons()

            self.header_font = Font(family="Segoe UI", size=12, weight="bold")
            self.normal_font = Font(family="Segoe UI", size=10)
            self.small_font = Font(family="Segoe UI", size=9)
            self.mono_font = Font(family="Consolas", size=9)

        def create_custom_buttons(self):
            self.button_variants = {
                "primary": {"bg": "#2d89ef", "fg": "white", "active": "#1e70cf"},
                "success": {"bg": "#27ae60", "fg": "white", "active": "#229954"},
                "danger":  {"bg": "#e74c3c", "fg": "white", "active": "#c0392b"},
                "warning": {"bg": "#f39c12", "fg": "white", "active": "#e67e22"},
                "secondary": {"bg": "#95a5a6", "fg": "white", "active": "#7f8c8d"},
                "dark": {"bg": "#34495e", "fg": "white", "active": "#2c3e50"}
            }

            self.button_bg = self.button_variants["primary"]["bg"]
            self.button_fg = self.button_variants["primary"]["fg"]
            self.button_active_bg = self.button_variants["primary"]["active"]
            self.accent_button_bg = self.button_variants["danger"]["bg"]
            self.accent_button_fg = self.button_variants["danger"]["fg"]
            self.accent_button_active_bg = self.button_variants["danger"]["active"]

        def create_button(self, parent, text, command, variant="primary", size="md", font=None):
            colors = self.get_button_colors(variant)
            bg = colors["bg"]
            fg = colors["fg"]
            active_bg = colors["active"]

            if font is None:
                if size == "sm":
                    use_font = self.small_font
                    padx, pady = 8, 3
                elif size == "lg":
                    use_font = Font(family=self.normal_font.actual().get("family", "Segoe UI"),
                                    size=self.normal_font.actual().get("size", 10) + 2, weight="bold")
                    padx, pady = 12, 7
                else:
                    use_font = self.normal_font
                    padx, pady = 10, 5
            else:
                use_font = font
                if size == "sm":
                    padx, pady = 8, 3
                elif size == "lg":
                    padx, pady = 12, 7
                else:
                    padx, pady = 10, 5

            btn = tk.Button(
                parent,
                text=text,
                command=command,
                font=use_font,
                bg=bg,
                fg=fg,
                activebackground=active_bg,
                activeforeground=fg,
                relief=tk.FLAT,
                bd=0,
                padx=padx,
                pady=pady,
                cursor="hand2",
                highlightthickness=0
            )

            btn._variant = variant

            def on_enter(e):
                btn.configure(bg=active_bg)
            def on_leave(e):
                btn.configure(bg=bg)
            btn.bind("<Enter>", on_enter)
            btn.bind("<Leave>", on_leave)

            return btn

        def setup_main_layout(self):
            self.main_frame = tk.Frame(self.root, bg=self.bg_color, padx=20, pady=20)
            self.main_frame.pack(fill=tk.BOTH, expand=True)

            self.content_frame = tk.Frame(self.main_frame, bg=self.bg_color)
            self.content_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        def setup_console_section(self):
            console_section = tk.Frame(self.main_frame, bg=self.bg_color)
            console_section.pack(fill=tk.X, pady=(0, 15))

            console_header = tk.Label(console_section, text="Player Console",
                                      font=self.header_font, bg=self.bg_color, fg=self.text_color)
            console_header.pack(anchor='w', pady=(0, 10))

            console_container = tk.Frame(console_section, bg=self.bg_color,
                                         highlightbackground="#cccccc",
                                         highlightthickness=1)
            console_container.pack(fill=tk.X, pady=(0, 10))

            console_frame = tk.Frame(console_container, bg=self.bg_color)
            console_frame.pack(fill=tk.BOTH, expand=True)

            self.console_scrollbar = tk.Scrollbar(console_frame)
            self.console_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            self.console_text = tk.Text(
                console_frame,
                height=8,
                wrap=tk.WORD,
                yscrollcommand=self.console_scrollbar.set,
                font=self.mono_font,
                bg="#2c3e50",
                fg="#ecf0f1",
                insertbackground="#ecf0f1",
                selectbackground="#34495e",
                selectforeground="#ecf0f1",
                relief=tk.FLAT,
                bd=0,
                padx=10,
                pady=10,
                state=tk.DISABLED
            )
            self.console_text.pack(fill=tk.BOTH, expand=True)
            self.console_scrollbar.config(command=self.console_text.yview)

            console_button_frame = tk.Frame(console_section, bg=self.bg_color)
            console_button_frame.pack(fill=tk.X)

            self.clear_console_button = self.create_button(
                console_button_frame,
                text="Clear Console",
                command=self.clear_console,
                variant="dark",
                size="sm"
            )
            self.clear_console_button.pack(side=tk.LEFT)

            self.update_console("Video Player Console Ready")
            self.update_console("Select directories and click 'Play Videos' to start")

        def update_console(self, message):
            def _update():
                self.console_text.config(state=tk.NORMAL)
                timestamp = datetime.now().strftime("%H:%M:%S")
                formatted_message = f"[{timestamp}] {message}\n"
                self.console_text.insert(tk.END, formatted_message)
                self.console_text.see(tk.END)
                self.console_text.config(state=tk.DISABLED)

            self.root.after(0, _update)

        def clear_console(self):
            self.console_text.config(state=tk.NORMAL)
            self.console_text.delete(1.0, tk.END)
            self.console_text.config(state=tk.DISABLED)
            self.update_console("Console cleared")

        def _submit_scan(self, directory):
            if directory in self.scan_cache or directory in self.pending_scans:
                return
            self.pending_scans.add(directory)
            future = self.executor.submit(gather_videos_with_directories, directory)

            def on_done(fut, dir_path=directory):
                try:
                    res = fut.result()
                    self.scan_cache[dir_path] = res
                    videos, _, directories = res
                    self.update_console(
                        f"Found {len(videos)} videos in '{os.path.basename(dir_path)}' ({len(directories)} subdirs)")
                except Exception as e:
                    self.update_console(f"Error scanning {dir_path}: {e}")
                finally:
                    self.pending_scans.discard(dir_path)
                    self.root.after(0, self.update_video_count)

            future.add_done_callback(on_done)

        def setup_directory_section(self):
            self.dir_section = tk.Frame(self.content_frame, bg=self.bg_color)
            self.dir_section.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

            dir_header = tk.Label(self.dir_section, text="Selected Directories",
                                  font=self.header_font, bg=self.bg_color, fg=self.text_color)
            dir_header.pack(anchor='w', pady=(0, 10))

            self.dir_frame = tk.Frame(self.dir_section, bg=self.bg_color)
            self.dir_frame.pack(fill=tk.BOTH, expand=True)

            list_container = tk.Frame(self.dir_frame, bg=self.bg_color,
                                      highlightbackground="#cccccc",
                                      highlightthickness=1)
            list_container.pack(fill=tk.BOTH, expand=True)

            self.scrollbar = tk.Scrollbar(list_container)
            self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)



            self.dir_listbox = tk.Listbox(
                list_container,
                selectmode=tk.SINGLE,
                yscrollcommand=self.scrollbar.set,
                font=self.normal_font,
                bg="white",
                fg=self.text_color,
                selectbackground=self.accent_color,
                selectforeground="white",
                activestyle="none",
                relief=tk.FLAT,
                highlightthickness=1,
                highlightbackground="#e0e0e0",
                bd=0
            )
            self.dir_listbox.pack(fill=tk.BOTH, expand=True)
            self.dir_listbox.bind('<<ListboxSelect>>', self.on_directory_select)
            self.dir_listbox.bind('<FocusOut>', self.on_directory_focus_out)
            self.dir_listbox.bind('<FocusIn>', self.on_directory_focus_in)
            self.scrollbar.config(command=self.dir_listbox.yview)

        def toggle_ai_mode(self):
            if self.ai_mode:
                self.ai_mode = False
                self.ai_button.config(text="AI Mode")
                self.update_console("Normal mode enabled")
                self.clear_exclusion_list()
                self.update_ui_for_mode()
                self.save_preferences()
                return

            app_settings = self.settings_manager.get_settings()
            self.ai_index_path = app_settings.ai_index_path

            required_files = ["clip_index.faiss", "text_index.faiss", "metadata.pkl", "tfidf_index.pkl"]
            files_exist = all(os.path.exists(os.path.join(self.ai_index_path, f)) for f in required_files)

            if not os.path.exists(self.ai_index_path) or not files_exist:
                result = messagebox.askyesno(
                    "AI Index Not Found",
                    f"AI index files not found in:\n{self.ai_index_path}\n\n"
                    "Would you like to open Settings to configure the AI index path or run preprocessing?"
                )
                if result:
                    self.settings_manager.show_settings()
                return

            self.ai_button.config(text="Loading...", state=tk.DISABLED)
            self.show_ai_loading_progress()
            self.update_console("Initializing AI models in background... UI remains responsive.")

            def load_ai_models():
                try:
                    from enhanced_model import HighAccuracyVideoSearcher

                    clip_index_path = os.path.join(self.ai_index_path, "clip_index.faiss")
                    text_index_path = os.path.join(self.ai_index_path, "text_index.faiss")
                    metadata_path = os.path.join(self.ai_index_path, "metadata.pkl")
                    tfidf_path = os.path.join(self.ai_index_path, "tfidf_index.pkl")

                    searcher = HighAccuracyVideoSearcher(clip_index_path, text_index_path, metadata_path, tfidf_path)

                    def finalize_ai_mode():
                        self.ai_searcher = searcher
                        self.ai_mode = True
                        self.ai_button.config(text="Normal Mode", state=tk.NORMAL)
                        self.update_console("AI Mode enabled - Search functionality ready")
                        self.update_ui_for_mode()
                        self.save_preferences()

                    self.root.after(0, finalize_ai_mode)

                except ImportError as e:
                    def show_import_error():
                        messagebox.showerror("Error", f"Missing dependencies for AI search: {e}")
                        self.ai_button.config(text="AI Mode", state=tk.NORMAL)

                    self.root.after(0, show_import_error)

                except Exception as e:
                    def show_general_error():
                        messagebox.showerror("Error", f"Failed to initialize AI searcher: {e}")
                        self.ai_button.config(text="AI Mode", state=tk.NORMAL)

                    self.root.after(0, show_general_error)

            threading.Thread(target=load_ai_models, daemon=True).start()

        def show_ai_loading_progress(self):
            """Show loading progress for AI model initialization"""
            if not hasattr(self, '_ai_loading_dots'):
                self._ai_loading_dots = 0

            if hasattr(self, 'ai_button') and self.ai_button.cget('text') == "Loading...":
                dots = "." * (self._ai_loading_dots % 4)
                self.ai_button.config(text=f"Loading{dots}")
                self._ai_loading_dots += 1

                self.root.after(500, self.show_ai_loading_progress)

        def update_ui_for_mode(self):
            if self.ai_mode:
                self.ai_search_frame.pack(fill=tk.X, pady=(0, 10))
                self.normal_mode_frame.pack_forget()

                self.exclude_button.pack_forget()
                self.include_button.pack_forget()
                self.exclude_all_button.pack_forget()
                self.clear_exclusions_button.pack_forget()
                self.toggle_excluded_only_check.pack_forget()

                self.selected_dir_label.config(text="AI Search Mode - Enter query to search videos")
            else:
                self.ai_search_frame.pack_forget()
                self.normal_mode_frame.pack(fill=tk.X)

                self.exclude_button.pack(side=tk.LEFT, padx=(0, 5))
                self.include_button.pack(side=tk.LEFT, padx=(0, 5))
                self.exclude_all_button.pack(side=tk.LEFT, padx=(0, 5))
                self.clear_exclusions_button.pack(side=tk.LEFT)
                self.toggle_excluded_only_check.pack(side=tk.LEFT, padx=(0, 10))

                selected_dir = self.get_current_selected_directory()
                if selected_dir:
                    self.load_subdirectories(selected_dir)
                else:
                    self.clear_exclusion_list()

        def perform_ai_search(self):
            if not self.ai_searcher:
                messagebox.showerror("Error", "AI searcher not initialized")
                return

            query = self.ai_search_entry.get().strip()
            if not query:
                messagebox.showwarning("Warning", "Please enter a search query")
                return

            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showwarning("Warning", "Please select a directory first")
                return

            self.ai_search_button.config(text="Searching...", state=tk.DISABLED)
            self.exclusion_listbox.delete(0, tk.END)
            self.exclusion_listbox.insert(tk.END, "Searching...")

            self.update_console(f"Searching for: '{query}' in background...")

            def search_worker():
                try:
                    if not self.ai_searcher.has_videos_from_directory(selected_dir):
                        def show_warning():
                            messagebox.showwarning("Warning",
                                                   f"No videos from '{os.path.basename(selected_dir)}' found in AI index")
                            self.ai_search_button.config(text="Search", state=tk.NORMAL)

                        self.root.after(0, show_warning)
                        return

                    total_videos = self.ai_searcher.get_video_count_for_directory(selected_dir)
                    self.root.after(0, lambda: self.update_console(
                        f"Searching {total_videos} indexed videos from '{os.path.basename(selected_dir)}'..."))

                    filtered_results = self.ai_searcher.query_filtered_by_directory(
                        query, selected_dir, top_k=100,
                        clip_weight=0.35, text_weight=0.35, tfidf_weight=0.3
                    )

                    def update_ui():
                        self.ai_search_button.config(text="Search", state=tk.NORMAL)
                        self.exclusion_listbox.delete(0, tk.END)
                        self.current_subdirs_mapping = {}

                        if not filtered_results:
                            self.exclusion_listbox.insert(tk.END,
                                                          f"No videos from '{os.path.basename(selected_dir)}' match '{query}'")
                            self.exclusion_listbox.insert(tk.END,
                                                          "Try a different search term or check if this directory was included in AI preprocessing")
                            self.update_console("No matching videos found in selected directory")
                            return

                        try:
                            min_score = float(self.min_score_entry.get().strip())
                        except (ValueError, AttributeError):
                            min_score = 0.0

                        final_results = [r for r in filtered_results if r.get('score', 0) >= min_score]

                        if not final_results:
                            self.exclusion_listbox.insert(tk.END, f"No results with score >= {min_score}")
                            self.update_console(f"No results found with minimum score {min_score}")
                            return

                        self.selected_dir_label.config(
                            text=f"AI Search: '{query}' - {len(final_results)} results (score >= {min_score})")

                        for idx, result in enumerate(final_results):
                            try:
                                video_path = result['video_path']
                                rel_path = os.path.relpath(video_path, selected_dir)
                            except ValueError:
                                video_path = result['video_path']
                                rel_path = os.path.basename(video_path)

                            score = result.get('score', 0)
                            frame_count = result.get('frame_count', 0)
                            display_name = f"▶ {rel_path} (score: {score:.3f}, frames: {frame_count})"
                            self.exclusion_listbox.insert(tk.END, display_name)
                            self.current_subdirs_mapping[idx] = video_path

                        self.update_console(f"Found {len(final_results)} videos with score >= {min_score}")

                    self.root.after(0, update_ui)

                except Exception as e:
                    def show_error():
                        self.ai_search_button.config(text="Search", state=tk.NORMAL)
                        self.exclusion_listbox.delete(0, tk.END)
                        self.exclusion_listbox.insert(tk.END, f"Search error: {e}")
                        self.update_console(f"AI search error: {e}")

                    self.root.after(0, show_error)

            threading.Thread(target=search_worker, daemon=True).start()

        def on_directory_focus_out(self, event):
            selection = self.dir_listbox.curselection()
            if selection:
                self.current_selected_dir_index = selection[0]

        def on_directory_focus_in(self, event):
            if self.current_selected_dir_index is not None and self.current_selected_dir_index < self.dir_listbox.size():
                self.dir_listbox.selection_clear(0, tk.END)
                self.dir_listbox.selection_set(self.current_selected_dir_index)
                self.dir_listbox.activate(self.current_selected_dir_index)

        def setup_exclusion_section(self):
            self.exclusion_section = tk.Frame(self.content_frame, bg=self.bg_color)
            self.exclusion_section.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))

            exclusion_header = tk.Label(self.exclusion_section, text="Exclude Subdirectories and Videos",
                                        font=self.header_font, bg=self.bg_color, fg=self.text_color)
            exclusion_header.pack(anchor='w', pady=(0, 10))

            self.selected_dir_label = tk.Label(
                self.exclusion_section,
                text="Select a directory to see its folders and videos",
                font=self.small_font,
                bg=self.bg_color,
                fg="#666666"
            )
            self.selected_dir_label.pack(anchor='w', pady=(0, 10))

            self.exclusion_frame = tk.Frame(self.exclusion_section, bg=self.bg_color)
            self.exclusion_frame.pack(fill=tk.BOTH, expand=True)

            exclusion_container = tk.Frame(self.exclusion_frame, bg=self.bg_color,
                                           highlightbackground="#cccccc",
                                           highlightthickness=1)
            exclusion_container.pack(fill=tk.BOTH, expand=True)

            self.exclusion_scrollbar = tk.Scrollbar(exclusion_container)
            self.exclusion_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            self.exclusion_listbox = tk.Listbox(
                exclusion_container,
                selectmode=tk.MULTIPLE,
                yscrollcommand=self.exclusion_scrollbar.set,
                font=self.normal_font,
                bg="white",
                fg=self.text_color,
                selectbackground="#e74c3c",
                selectforeground="white",
                activestyle="none",
                relief=tk.FLAT,
                highlightthickness=1,
                highlightbackground="#e0e0e0",
                bd=0
            )
            self.exclusion_listbox.pack(fill=tk.BOTH, expand=True)
            self.exclusion_scrollbar.config(command=self.exclusion_listbox.yview)

            exclusion_buttons_frame = tk.Frame(self.exclusion_section, bg=self.bg_color)
            exclusion_buttons_frame.pack(fill=tk.X, pady=(10, 0))

            self.ai_search_frame = tk.Frame(exclusion_buttons_frame, bg=self.bg_color)
            self.ai_search_frame.pack(fill=tk.X, pady=(0, 10))

            search_label = tk.Label(self.ai_search_frame, text="AI Search:",
                                    font=self.normal_font, bg=self.bg_color, fg=self.text_color)
            search_label.pack(anchor='w', pady=(0, 5))

            # Replace the existing search_input_frame section with this:
            search_input_frame = tk.Frame(self.ai_search_frame, bg=self.bg_color)
            search_input_frame.pack(fill=tk.X, pady=(0, 5))

            self.ai_search_entry = tk.Entry(
                search_input_frame,
                font=self.normal_font,
                bg="white",
                fg=self.text_color,
                relief=tk.FLAT,
                bd=1,
                highlightthickness=1,
                highlightbackground="#e0e0e0"
            )
            self.ai_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
            self.ai_search_entry.bind('<Return>', lambda e: self.perform_ai_search())

            score_label = tk.Label(search_input_frame, text="Min Score:",
                                   font=self.small_font, bg=self.bg_color, fg=self.text_color)
            score_label.pack(side=tk.LEFT, padx=(0, 2))

            self.min_score_entry = tk.Entry(
                search_input_frame,
                font=self.normal_font,
                bg="white",
                fg=self.text_color,
                relief=tk.FLAT,
                bd=1,
                highlightthickness=1,
                highlightbackground="#e0e0e0",
                width=6
            )
            self.min_score_entry.pack(side=tk.LEFT, padx=(0, 5))
            self.min_score_entry.insert(0, "0.0")  # Default value
            self.min_score_entry.bind('<Return>', lambda e: self.perform_ai_search())

            self.ai_search_button = self.create_button(
                search_input_frame,
                text="Search",
                command=self.perform_ai_search,
                variant="primary",
                size="sm"
            )
            self.ai_search_button.pack(side=tk.RIGHT)

            self.normal_mode_frame = tk.Frame(exclusion_buttons_frame, bg=self.bg_color)
            self.normal_mode_frame.pack(fill=tk.X)

            checkboxes_row = tk.Frame(self.normal_mode_frame, bg=self.bg_color)
            checkboxes_row.pack(fill=tk.X, pady=(0, 5))

            checkboxes_row = tk.Frame(exclusion_buttons_frame, bg=self.bg_color)
            checkboxes_row.pack(fill=tk.X, pady=(0, 5))

            self.show_videos_var = tk.BooleanVar(value=self.show_videos)
            self.excluded_only_var = tk.BooleanVar(value=self.show_only_excluded)
            self.expand_all_var = tk.BooleanVar(value=self.expand_all_default)
            self.save_directories_var = tk.BooleanVar(value=self.save_directories)
            self.start_from_last_played_var = tk.BooleanVar(value=self.start_from_last_played)

            self.toggle_videos_check = ttk.Checkbutton(
                checkboxes_row,
                text="Show Videos",
                style="Modern.TCheckbutton",
                variable=self.show_videos_var,
                command=self.toggle_videos_visibility
            )
            self.toggle_videos_check.pack(side=tk.LEFT, padx=(0, 10))

            self.expand_all_check = ttk.Checkbutton(
                checkboxes_row,
                text="Expand All",
                style="Modern.TCheckbutton",
                variable=self.expand_all_var,
                command=self.toggle_expand_all
            )
            self.expand_all_check.pack(side=tk.LEFT, padx=(0, 10))

            self.toggle_excluded_only_check = ttk.Checkbutton(
                checkboxes_row,
                text="Excluded Only",
                style="Modern.TCheckbutton",
                variable=self.excluded_only_var,
                command=self.toggle_excluded_only
            )
            self.toggle_excluded_only_check.pack(side=tk.LEFT, padx=(0, 10))

            self.save_directories_check = ttk.Checkbutton(
                checkboxes_row,
                text="Save Directories",
                style="Modern.TCheckbutton",
                variable=self.save_directories_var,
                command=self.toggle_save_directories
            )
            self.save_directories_check.pack(side=tk.LEFT, padx=(0, 10))

            self.start_from_last_played_check = ttk.Checkbutton(
                checkboxes_row,
                text="Resume Playback",
                style="Modern.TCheckbutton",
                variable=self.start_from_last_played_var,
                command=self.toggle_start_from_last_played
            )
            self.start_from_last_played_check.pack(side=tk.LEFT)
            self.resume_playback_var = tk.BooleanVar(value=True)
            self.resume_playback_check = ttk.Checkbutton(
                checkboxes_row,
                text="Resume from Last Position",
                style="Modern.TCheckbutton",
                variable=self.resume_playback_var,
                command=self.toggle_resume_playback
            )
            self.resume_playback_check.pack(side=tk.LEFT, padx=(15, 0))

            buttons_row = tk.Frame(exclusion_buttons_frame, bg=self.bg_color)
            buttons_row.pack(fill=tk.X, pady=(5, 0))

            self.exclude_button = self.create_button(
                buttons_row,
                text="Exclude Selected",
                command=self.exclude_subdirectories,
                variant="danger",
                size="sm"
            )
            self.exclude_button.pack(side=tk.LEFT, padx=(0, 5))

            self.include_button = self.create_button(
                buttons_row,
                text="Include Selected",
                command=self.include_subdirectories,
                variant="success",
                size="sm"
            )
            self.include_button.pack(side=tk.LEFT, padx=(0, 5))

            self.exclude_all_button = self.create_button(
                buttons_row,
                text="Exclude All",
                command=self.exclude_all_subdirectories,
                variant="warning",
                size="sm"
            )
            self.exclude_all_button.pack(side=tk.LEFT, padx=(0, 5))

            self.clear_exclusions_button = self.create_button(
                buttons_row,
                text="Clear All Exclusions",
                command=self.clear_all_exclusions,
                variant="secondary",
                size="sm"
            )
            self.clear_exclusions_button.pack(side=tk.LEFT)

            buttons_row3 = tk.Frame(exclusion_buttons_frame, bg=self.bg_color)
            buttons_row3.pack(fill=tk.X, pady=(10, 0))

            speed_container = tk.Frame(buttons_row3, bg=self.bg_color, relief=tk.FLAT)
            speed_container.pack(fill=tk.X)

            speed_label = tk.Label(speed_container, text="Speed:",
                                   font=self.small_font, bg=self.bg_color, fg="#666666")
            speed_label.pack(side=tk.LEFT, padx=(0, 8))

            slider_frame = tk.Frame(speed_container, bg=self.bg_color, height=30)
            slider_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
            slider_frame.pack_propagate(False)

            self.speed_var = tk.DoubleVar(value=1.0)
            self.speed_canvas = tk.Canvas(
                slider_frame,
                height=6,
                bg=self.bg_color,
                highlightthickness=0,
                relief=tk.FLAT
            )
            self.speed_canvas.pack(fill=tk.X, pady=12)

            self.slider_width = 200
            self.slider_min = 0.25
            self.slider_max = 2.0
            self.slider_current = 1.0
            self.dragging = False

            self.speed_canvas.bind("<Button-1>", self.on_slider_click)
            self.speed_canvas.bind("<B1-Motion>", self.on_slider_drag)
            self.speed_canvas.bind("<ButtonRelease-1>", self.on_slider_release)
            self.speed_canvas.bind("<Configure>", self.on_slider_configure)

            self.speed_display = tk.Label(
                speed_container,
                text="1.0×",
                font=Font(family=self.small_font.actual().get("family", "Segoe UI"),
                          size=self.small_font.actual().get("size", 9), weight="bold"),
                bg=self.bg_color,
                fg=self.accent_color,
                width=5
            )
            self.speed_display.pack(side=tk.LEFT, padx=(0, 8))

            self.reset_speed_button = self.create_button(
                speed_container,
                text="1×",
                command=self.reset_speed,
                variant="secondary",
                size="sm"
            )
            self.reset_speed_button.pack(side=tk.LEFT)

            self.root.after(100, self.draw_slider)

        def toggle_start_from_last_played(self):
            self.start_from_last_played = bool(self.start_from_last_played_var.get())
            self.save_preferences()

        def get_current_selected_directory(self):
            selection = self.dir_listbox.curselection()
            if selection:
                return self.selected_dirs[selection[0]]
            elif self.current_selected_dir_index is not None and self.current_selected_dir_index < len(
                    self.selected_dirs):
                return self.selected_dirs[self.current_selected_dir_index]
            return None

        def is_video_in_excluded_directory(self, video_path, excluded_subdirs):
            video_dir = os.path.dirname(video_path)

            for excluded_subdir in excluded_subdirs:
                excluded_subdir = os.path.normpath(excluded_subdir)
                video_dir_norm = os.path.normpath(video_dir)

                if video_dir_norm == excluded_subdir:
                    return True

                if video_dir_norm.startswith(excluded_subdir + os.sep):
                    return True

            return False

        def is_video_excluded(self, root_dir, video_path):
            excluded_videos = self.excluded_videos.get(root_dir, [])
            video_path = os.path.normpath(video_path)
            if video_path in excluded_videos:
                return True
            excluded_subdirs = self.excluded_subdirs.get(root_dir, [])
            return self.is_video_in_excluded_directory(video_path, excluded_subdirs)

        def is_directory_excluded(self, directory_path, excluded_subdirs):
            for excluded_subdir in excluded_subdirs:
                excluded_subdir = os.path.normpath(excluded_subdir)
                directory_path_norm = os.path.normpath(directory_path)

                if directory_path_norm == excluded_subdir:
                    return True

                if directory_path_norm.startswith(excluded_subdir + os.sep):
                    return True

            return False

        def get_all_subdirectories_of_path(self, parent_path, target_path):
            subpaths = []
            try:
                base = os.path.normpath(target_path)
                subpaths.append(base)
                for root, dirs, files in os.walk(base):
                    for d in dirs:
                        subpaths.append(os.path.join(root, d))
                    for f in files:
                        full = os.path.join(root, f)
                        if is_video(full):
                            subpaths.append(full)
            except Exception as e:
                self.update_console(f"Error getting subdirectories of {target_path}: {e}")

            return subpaths

        def update_video_count(self):
            total_videos = 0
            total_excluded = 0
            pending = 0

            for directory in self.selected_dirs:
                cache = self.scan_cache.get(directory)
                if not cache:
                    pending += 1
                    continue
                videos, _, _ = cache

                excluded_subdirs = self.excluded_subdirs.get(directory, [])
                excluded_videos = self.excluded_videos.get(directory, [])
                if excluded_subdirs or excluded_videos:
                    filtered_videos = []
                    for video in videos:
                        if not self.is_video_excluded(directory, video):
                            filtered_videos.append(video)
                    total_videos += len(filtered_videos)
                else:
                    total_videos += len(videos)

            self.video_count = total_videos
            suffix = f" (scanning {pending} dir(s)...)" if pending else ""
            self.video_count_label.config(text=f"Total Videos: {self.video_count}{suffix}")

            if total_excluded > 0:
                self.update_console(
                    f"Total: {total_videos} videos selected, {total_excluded} excluded from {len(self.selected_dirs)} directories")
            elif not pending:
                self.update_console(f"Total: {total_videos} videos selected from {len(self.selected_dirs)} directories")

        def play_videos(self):
            if not self.selected_dirs:
                messagebox.showwarning("No Directories", "Please select at least one directory.")
                return

            if self.controller:
                self.controller.stop()
                cleanup_hotkeys()

            self.root.config(cursor="wait")
            self.root.update()

            self.update_console("=" * 100)
            self.update_console("STARTING VIDEO PLAYBACK")
            self.update_console("=" * 100)

            def _run():
                if self.ai_mode and self.current_subdirs_mapping:
                    self.update_console("Using AI search results for playback order")

                    ai_video_paths = []
                    for i in range(len(self.current_subdirs_mapping)):
                        if i in self.current_subdirs_mapping:
                            path = self.current_subdirs_mapping[i]
                            if os.path.isfile(path) and is_video(path):
                                ai_video_paths.append(path)

                    if not ai_video_paths:
                        def _show_no_videos():
                            messagebox.showwarning("No Videos", "No valid videos found in AI search results.")
                            self.root.config(cursor="")

                        self.root.after(0, _show_no_videos)
                        return

                    all_videos = ai_video_paths
                    all_video_to_dir = {}
                    selected_dir = self.get_current_selected_directory()

                    for video_path in ai_video_paths:
                        all_video_to_dir[video_path] = os.path.dirname(video_path)

                    all_directories = list(set(all_video_to_dir.values()))
                    all_directories.sort()

                    def _start_ai_player():
                        self.update_console(f"Playing {len(all_videos)} videos from AI search results")
                        self.controller = VLCPlayerControllerForMultipleDirectory(
                            all_videos, all_video_to_dir, all_directories, self.update_console
                        )
                        self.controller.set_watch_history_callback(
                            self.watch_history_manager.track_video_playback
                        )
                        # Set resume playback manager
                        self.controller.set_resume_manager(self.resume_manager)


                        initial_speed = self.speed_var.get()
                        if initial_speed != 1.0:
                            self.controller.set_initial_playback_rate(initial_speed)
                            self.update_console(f"Initial playback speed set to {initial_speed}x")

                        start_index = 0
                        self.controller.set_start_index(start_index)
                        self.controller.set_video_change_callback(self.on_video_changed)

                        if self.player_thread and self.player_thread.is_alive():
                            self.controller.running = False
                            self.player_thread.join(timeout=1.0)

                        self.player_thread = threading.Thread(target=self.controller.run, daemon=True)
                        self.player_thread.start()

                        self.keys_thread = threading.Thread(target=lambda: listen_keys(self.controller), daemon=True)
                        self.keys_thread.start()
                        self.root.config(cursor="")

                    self.root.after(0, _start_ai_player)
                    return

                futures = {}
                for directory in self.selected_dirs:
                    if directory not in self.scan_cache and directory not in self.pending_scans:
                        self.pending_scans.add(directory)
                        futures[directory] = self.executor.submit(gather_videos_with_directories, directory)
                for directory, future in list(futures.items()):
                    try:
                        result = future.result()
                        self.scan_cache[directory] = result
                        self.update_console(f"Scan completed: {directory}")
                    except Exception as e:
                        self.update_console(f"Error scanning {directory}: {e}")
                    finally:
                        self.pending_scans.discard(directory)

                all_videos = []
                all_video_to_dir = {}
                all_directories = []
                for directory in self.selected_dirs:
                    cache = self.scan_cache.get(directory)
                    if not cache:
                        continue
                    videos, video_to_dir, directories = cache
                    videos = [os.path.normpath(v) for v in videos]
                    video_to_dir = {os.path.normpath(k): v for k, v in video_to_dir.items()}

                    excluded_subdirs = self.excluded_subdirs.get(directory, [])
                    excluded_videos = self.excluded_videos.get(directory, [])
                    if excluded_subdirs or excluded_videos:
                        filtered_videos = []
                        filtered_video_to_dir = {}
                        filtered_directories = []

                        for video in videos:
                            if not self.is_video_excluded(directory, video):
                                filtered_videos.append(video)
                                filtered_video_to_dir[video] = video_to_dir[video]

                        for dir_path in directories:
                            if not self.is_directory_excluded(dir_path, excluded_subdirs):
                                filtered_directories.append(dir_path)

                        all_videos.extend(filtered_videos)
                        all_video_to_dir.update(filtered_video_to_dir)
                        all_directories.extend(filtered_directories)
                    else:
                        all_videos.extend(videos)
                        all_video_to_dir.update(video_to_dir)
                        all_directories.extend(directories)

                all_directories = sorted(list(set(all_directories)))

                def _start_player():
                    if not all_videos:
                        messagebox.showwarning("No Videos", "No videos found in the selected directories.")
                        self.root.config(cursor="")
                        return

                    self.update_console(f"Playing from {len(all_directories)} directories")
                    self.controller = VLCPlayerControllerForMultipleDirectory(all_videos, all_video_to_dir,
                                                                              all_directories, self.update_console)
                    self.controller.set_watch_history_callback(
                        self.watch_history_manager.track_video_playback
                    )
                    # Set resume playback manager
                    self.controller.set_resume_manager(self.resume_manager)

                    initial_speed = self.speed_var.get()
                    if initial_speed != 1.0:
                        self.controller.set_initial_playback_rate(initial_speed)
                        self.update_console(f"Initial playback speed set to {initial_speed}x")

                    start_index = 0
                    if self.start_from_last_played:
                        if self.last_played_video_path and self.last_played_video_path in all_videos:
                            start_index = all_videos.index(self.last_played_video_path)
                            self.update_console(
                                f"Starting from last played video: {os.path.basename(self.last_played_video_path)}")
                        elif self.save_directories and self.last_played_video_index < len(all_videos):
                            start_index = self.last_played_video_index
                            self.update_console(f"Starting from last played index: {start_index}")

                    self.controller.set_start_index(start_index)

                    self.controller.set_video_change_callback(self.on_video_changed)

                    if self.player_thread and self.player_thread.is_alive():
                        self.controller.running = False
                        self.player_thread.join(timeout=1.0)

                    self.player_thread = threading.Thread(target=self.controller.run, daemon=True)
                    self.player_thread.start()

                    self.keys_thread = threading.Thread(target=lambda: listen_keys(self.controller), daemon=True)
                    self.keys_thread.start()
                    self.root.config(cursor="")

                self.root.after(0, _start_player)

            threading.Thread(target=_run, daemon=True).start()

        def on_video_changed(self, video_index, video_path):
            self.last_played_video_index = video_index
            self.last_played_video_path = video_path
            if self.start_from_last_played:
                self.save_preferences()

        def on_directory_select(self, event):
            selection = self.dir_listbox.curselection()
            if not selection:
                if self.current_selected_dir_index is not None:
                    selected_dir = self.selected_dirs[self.current_selected_dir_index]
                    max_depth = 20 if self.expand_all_var.get() else 1
                    self.load_subdirectories(selected_dir, max_depth=max_depth)
                else:
                    self.clear_exclusion_list()
                return

            selected_index = selection[0]
            if selected_index >= len(self.selected_dirs):
                return

            self.current_selected_dir_index = selected_index
            selected_dir = self.selected_dirs[selected_index]
            max_depth = 20 if self.expand_all_var.get() else 1
            self.load_subdirectories(selected_dir, max_depth=max_depth)

        def get_all_subdirectories(self, directory, prefix="", max_depth=20, current_depth=0):
            if current_depth >= max_depth:
                return []

            subdirs = []
            try:
                items = sorted(os.listdir(directory))
                for item in items:
                    item_path = os.path.join(directory, item)
                    if os.path.isdir(item_path) or is_video(item_path):
                        display_name = prefix + item
                        subdirs.append((item_path, display_name))

                        nested_subdirs = self.get_all_subdirectories(
                            item_path,
                            prefix + item + "/",
                            max_depth,
                            current_depth + 1
                        )
                        subdirs.extend(nested_subdirs)
            except (PermissionError, OSError):
                pass

            return subdirs

        def clear_exclusion_list(self):
            self.selected_dir_label.config(text="Select a directory to see its folders and videos")
            self.exclusion_listbox.delete(0, tk.END)
            self.current_subdirs_mapping = {}

        def exclude_all_subdirectories(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showinfo("Information", "Please select a directory first.")
                return

            self.exclusion_listbox.delete(0, tk.END)
            self.exclusion_listbox.insert(tk.END, "Excluding all... Please wait")

            def worker(dir_path=selected_dir):
                dir_paths = []
                file_paths = []
                try:
                    base = os.path.normpath(dir_path)
                    dir_paths.append(base)
                    for root, dirs, files in os.walk(base):
                        for d in dirs:
                            dir_paths.append(os.path.join(root, d))
                        for f in files:
                            full = os.path.join(root, f)
                            if is_video(full):
                                file_paths.append(full)
                except Exception as e:
                    self.root.after(0, lambda: self.update_console(f"Error during Exclude All: {e}"))
                    self.root.after(0, lambda: [self.exclusion_listbox.delete(0, tk.END),
                                                self.exclusion_listbox.insert(tk.END, f"Error: {e}")])
                    return

                def apply_and_refresh():
                    if dir_paths:
                        self.excluded_subdirs[dir_path] = dir_paths
                    if file_paths:
                        if dir_path not in self.excluded_videos:
                            self.excluded_videos[dir_path] = []
                        existing = set(self.excluded_videos[dir_path])
                        for fp in file_paths:
                            if fp not in existing:
                                self.excluded_videos[dir_path].append(fp)
                    total = len(dir_paths) + len(file_paths)
                    self.update_console(
                        f"Excluded ALL {total} items from '{os.path.basename(dir_path)}'")
                    self.load_subdirectories(dir_path)
                    self.update_video_count()
                    self.exclusion_listbox.selection_clear(0, tk.END)
                    if self.save_directories:
                        self.save_preferences()

                self.root.after(0, apply_and_refresh)

            threading.Thread(target=worker, daemon=True).start()

        def exclude_subdirectories(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showinfo("Information", "Please select a directory first.")
                return

            exclusion_selection = self.exclusion_listbox.curselection()

            if not exclusion_selection:
                messagebox.showinfo("Information", "Please select items to exclude.")
                return

            self.exclusion_listbox.insert(tk.END, "\nApplying exclusions... Please wait")
            for btn in [getattr(self, 'exclude_button', None), getattr(self, 'include_button', None), getattr(self, 'exclude_all_button', None), getattr(self, 'clear_exclusions_button', None)]:
                if btn:
                    btn.config(state=tk.DISABLED)

            def worker(dir_path=selected_dir, indices=list(exclusion_selection)):
                dirs_to_exclude = set()
                vids_to_exclude = set()
                selected_names = []
                try:
                    for index in indices:
                        target_path = self.current_subdirs_mapping.get(index)
                        if not target_path:
                            continue
                        if os.path.isdir(target_path):
                            base = os.path.normpath(target_path)
                            dirs_to_exclude.add(base)
                            for root, dirs, files in os.walk(base):
                                for d in dirs:
                                    dirs_to_exclude.add(os.path.join(root, d))
                                for f in files:
                                    full = os.path.join(root, f)
                                    if is_video(full):
                                        vids_to_exclude.add(full)
                        else:
                            vids_to_exclude.add(target_path)
                        selected_names.append(os.path.basename(target_path))
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror("Error", f"Error excluding items: {e}"))
                    self.root.after(0, lambda: [btn.config(state=tk.NORMAL) for btn in [getattr(self, 'exclude_button', None), getattr(self, 'include_button', None), getattr(self, 'exclude_all_button', None), getattr(self, 'clear_exclusions_button', None)] if btn])
                    return

                def apply_and_refresh():
                    if dir_path not in self.excluded_subdirs:
                        self.excluded_subdirs[dir_path] = []
                    if dir_path not in self.excluded_videos:
                        self.excluded_videos[dir_path] = []

                    excluded_count = 0
                    existing_dirs = set(self.excluded_subdirs[dir_path])
                    for d in dirs_to_exclude:
                        if d not in existing_dirs:
                            self.excluded_subdirs[dir_path].append(d)
                            excluded_count += 1
                    existing_vids = set(self.excluded_videos[dir_path])
                    for vp in vids_to_exclude:
                        if vp not in existing_vids:
                            self.excluded_videos[dir_path].append(vp)
                            excluded_count += 1

                    if excluded_count > 0:
                        self.update_console(
                            f"Excluded {excluded_count} item(s) from '{os.path.basename(dir_path)}': {', '.join(selected_names)}")

                    self.load_subdirectories(dir_path)
                    self.update_video_count()
                    self.exclusion_listbox.selection_clear(0, tk.END)
                    if self.save_directories:
                        self.save_preferences()
                    for btn in [getattr(self, 'exclude_button', None), getattr(self, 'include_button', None), getattr(self, 'exclude_all_button', None), getattr(self, 'clear_exclusions_button', None)]:
                        if btn:
                            btn.config(state=tk.NORMAL)

                self.root.after(0, apply_and_refresh)

            threading.Thread(target=worker, daemon=True).start()

        def include_subdirectories(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showinfo("Information", "Please select a directory first.")
                return

            exclusion_selection = self.exclusion_listbox.curselection()

            if not exclusion_selection:
                messagebox.showinfo("Information", "Please select items to include.")
                return

            if selected_dir not in self.excluded_subdirs and selected_dir not in self.excluded_videos:
                return

            self.exclusion_listbox.insert(tk.END, "\nApplying includes... Please wait")
            for btn in [getattr(self, 'exclude_button', None), getattr(self, 'include_button', None), getattr(self, 'exclude_all_button', None), getattr(self, 'clear_exclusions_button', None)]:
                if btn:
                    btn.config(state=tk.DISABLED)

            def worker(dir_path=selected_dir, indices=list(exclusion_selection)):
                dirs_to_include = set()
                vids_to_include = set()
                selected_names = []
                try:
                    for index in indices:
                        target_path = self.current_subdirs_mapping.get(index)
                        if not target_path:
                            continue
                        if os.path.isdir(target_path):
                            base = os.path.normpath(target_path)
                            dirs_to_include.add(base)
                            for root, dirs, files in os.walk(base):
                                for d in dirs:
                                    dirs_to_include.add(os.path.join(root, d))
                                for f in files:
                                    full = os.path.join(root, f)
                                    if is_video(full):
                                        vids_to_include.add(full)
                        else:
                            vids_to_include.add(target_path)
                        selected_names.append(os.path.basename(target_path))
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror("Error", f"Error including items: {e}"))
                    self.root.after(0, lambda: [btn.config(state=tk.NORMAL) for btn in [getattr(self, 'exclude_button', None), getattr(self, 'include_button', None), getattr(self, 'exclude_all_button', None), getattr(self, 'clear_exclusions_button', None)] if btn])
                    return

                def apply_and_refresh():
                    included_count = 0

                    if dir_path in self.excluded_subdirs:
                        remaining = [d for d in self.excluded_subdirs[dir_path] if d not in dirs_to_include]
                        removed = len(self.excluded_subdirs[dir_path]) - len(remaining)
                        if removed:
                            included_count += removed
                        if remaining:
                            self.excluded_subdirs[dir_path] = remaining
                        else:
                            del self.excluded_subdirs[dir_path]

                    if dir_path in self.excluded_videos:
                        remaining_v = [v for v in self.excluded_videos[dir_path] if v not in vids_to_include]
                        removed_v = len(self.excluded_videos[dir_path]) - len(remaining_v)
                        if removed_v:
                            included_count += removed_v
                        if remaining_v:
                            self.excluded_videos[dir_path] = remaining_v
                        else:
                            del self.excluded_videos[dir_path]

                    if included_count > 0:
                        self.update_console(
                            f"Included {included_count} item(s) in '{os.path.basename(dir_path)}': {', '.join(selected_names)}")

                    self.load_subdirectories(dir_path)
                    self.update_video_count()
                    self.exclusion_listbox.selection_clear(0, tk.END)
                    if self.save_directories:
                        self.save_preferences()
                    for btn in [getattr(self, 'exclude_button', None), getattr(self, 'include_button', None), getattr(self, 'exclude_all_button', None), getattr(self, 'clear_exclusions_button', None)]:
                        if btn:
                            btn.config(state=tk.NORMAL)

                self.root.after(0, apply_and_refresh)

            threading.Thread(target=worker, daemon=True).start()

        def expand_all_directories(self):
            selected_dir = self.get_current_selected_directory()
            if selected_dir:
                self.load_subdirectories(selected_dir, max_depth=20)

        def collapse_all_directories(self):
            selected_dir = self.get_current_selected_directory()
            if selected_dir:
                self.load_subdirectories(selected_dir, max_depth=1)

        def toggle_expand_all(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showinfo("Information", "Please select a directory first.")
                self.expand_all_var.set(self.expand_all_default)
                return
            self.save_preferences()
            if self.expand_all_var.get():
                self.load_subdirectories(selected_dir, max_depth=20)
            else:
                self.load_subdirectories(selected_dir, max_depth=1)

        def toggle_videos_visibility(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showinfo("Information", "Please select a directory first.")
                return
            self.show_videos = bool(self.show_videos_var.get())
            self.save_preferences()
            self.load_subdirectories(selected_dir, max_depth=self.current_max_depth)

        def toggle_excluded_only(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showinfo("Information", "Please select a directory first.")
                return
            self.show_only_excluded = bool(self.excluded_only_var.get())
            self.load_subdirectories(selected_dir, max_depth=self.current_max_depth)

        def toggle_save_directories(self):
            self.save_directories = bool(self.save_directories_var.get())
            self.save_preferences()

        def clear_all_exclusions(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showinfo("Information", "Please select a directory first.")
                return

            had_subdir_excl = selected_dir in self.excluded_subdirs
            had_video_excl = selected_dir in self.excluded_videos
            if had_subdir_excl or had_video_excl:
                excluded_count = (len(self.excluded_subdirs.get(selected_dir, [])) +
                                  len(self.excluded_videos.get(selected_dir, [])))
                result = messagebox.askyesno(
                    "Confirm",
                    f"Clear all exclusions for {os.path.basename(selected_dir)}?"
                )
                if result:
                    if had_subdir_excl:
                        del self.excluded_subdirs[selected_dir]
                    if had_video_excl:
                        del self.excluded_videos[selected_dir]
                    self.update_console(
                        f"Cleared all {excluded_count} exclusions for '{os.path.basename(selected_dir)}'")
                    if self.save_directories:
                        self.save_preferences()
                    self.load_subdirectories(selected_dir)
                    self.update_video_count()

        def load_subdirectories(self, directory, max_depth=20):
            self.current_max_depth = max_depth
            if self.show_only_excluded:
                self.selected_dir_label.config(text=f"Excluded items in: {os.path.basename(directory)}")
            else:
                self.selected_dir_label.config(text=f"All items in: {os.path.basename(directory)}")
            self.exclusion_listbox.delete(0, tk.END)
            self.exclusion_listbox.insert(tk.END, "Loading...")
            self.current_subdirs_mapping = {}

            if not hasattr(self, '_subdir_load_token'):
                self._subdir_load_token = None
            token = object()
            self._subdir_load_token = token

            excluded_dir_set = set(self.excluded_subdirs.get(directory, []))
            excluded_vid_set = set(self.excluded_videos.get(directory, []))
            show_videos = self.show_videos
            only_excluded = self.show_only_excluded

            def build_and_post():
                try:
                    base = os.path.abspath(directory)
                    base_sep = os.sep
                    items = []

                    for root, dirs, files in os.walk(base):
                        rel = os.path.relpath(root, base)
                        depth = 0 if rel == '.' else rel.count(base_sep) + 1
                        if depth > max_depth:
                            dirs[:] = []
                            continue

                        indent_level = 0 if rel == '.' else rel.count(base_sep) + 1
                        name = os.path.basename(root) if rel != '.' else os.path.basename(base)
                        include_dir = (not only_excluded) or (root in excluded_dir_set)
                        if include_dir:
                            indented_name = ("  " * indent_level) + '📁' + name
                            if root in excluded_dir_set:
                                indented_name += "🚫[EXCLUDED]"
                            items.append((root, indented_name))

                        if show_videos:
                            try:
                                with os.scandir(root) as it:
                                    for entry in it:
                                        if entry.is_file() and is_video(entry.name):
                                            full_path = entry.path
                                            include_vid = (not only_excluded) or (full_path in excluded_vid_set)
                                            if include_vid:
                                                v_name = ("  " * (indent_level + 1)) + '▶' + entry.name
                                                if full_path in excluded_vid_set:
                                                    v_name += "🚫[EXCLUDED]"
                                                items.append((full_path, v_name))
                            except PermissionError:
                                pass

                    def post_chunks():
                        if self._subdir_load_token is not token:
                            return
                        self.exclusion_listbox.delete(0, tk.END)
                        if not items:
                            self.exclusion_listbox.insert(tk.END, "No items found")
                            self.current_subdirs_mapping = {}
                            return

                        chunk_size = 500
                        total = len(items)
                        mapping = {}

                        def insert_chunk(start):
                            if self._subdir_load_token is not token:
                                return
                            end = min(start + chunk_size, total)
                            for i in range(start, end):
                                _, indented_name = items[i]
                                self.exclusion_listbox.insert(tk.END, indented_name)
                            for idx in range(start, end):
                                mapping[idx] = items[idx][0]
                            if end < total:
                                self.root.after(1, lambda: insert_chunk(end))
                            else:
                                self.current_subdirs_mapping = mapping

                        insert_chunk(0)

                    self.root.after(0, post_chunks)

                except Exception as e:
                    def post_error():
                        if self._subdir_load_token is not token:
                            return
                        self.exclusion_listbox.delete(0, tk.END)
                        self.exclusion_listbox.insert(tk.END, f"Error loading subdirectories: {str(e)}")
                        self.current_subdirs_mapping = {}
                    self.root.after(0, post_error)

            threading.Thread(target=build_and_post, daemon=True).start()

        def setup_action_buttons(self):
            self.button_frame = tk.Frame(self.main_frame, bg=self.bg_color)
            self.button_frame.pack(fill=tk.X, pady=(0, 15))

            dir_buttons_frame = tk.Frame(self.button_frame, bg=self.bg_color)
            dir_buttons_frame.pack(side=tk.LEFT)

            self.add_button = self.create_button(
                dir_buttons_frame,
                text="Add Directory",
                command=self.add_directory,
                variant="primary",
                size="md"
            )
            self.add_button.pack(side=tk.LEFT, padx=(0, 5))

            self.remove_button = self.create_button(
                dir_buttons_frame,
                text="Remove Selected",
                command=self.remove_directory,
                variant="secondary",
                size="md"
            )
            self.remove_button.pack(side=tk.LEFT)

            theme_frame = tk.Frame(self.button_frame, bg=self.bg_color)
            theme_frame.pack(side=tk.LEFT, expand=True)

            self.ai_button = self.create_button(
                theme_frame,
                text="AI Mode" if not self.ai_mode else "Normal Mode",
                command=self.toggle_ai_mode,
                variant="warning",
                size="md"
            )
            self.ai_button.pack(side=tk.LEFT, padx=(0, 10))
            self.add_to_playlist_button = self.create_button(
                theme_frame,
                text="Add to Playlist",
                command=self._add_to_playlist,
                variant="warning",
                size="md"
            )
            self.add_to_playlist_button.pack(side=tk.LEFT, padx=(0, 5))

            self.manage_playlist_button = self.create_button(
                theme_frame,
                text="Manage Playlists",
                command=self._manage_playlists,
                variant="secondary",
                size="md"
            )
            self.manage_playlist_button.pack(side=tk.LEFT, padx=(0, 10))
            self.watch_history_button = self.create_button(
                theme_frame,
                text="Watch History",
                command=self._show_watch_history,
                variant="secondary",
                size="md"
            )
            self.watch_history_button.pack(side=tk.LEFT, padx=(0, 10))
            self.settings_button = self.create_button(
                theme_frame,
                text="Settings",
                command=self._show_settings,
                variant="secondary",
                size="md"
            )
            self.settings_button.pack(side=tk.LEFT, padx=(0, 10))

            self.theme_button = self.create_button(
                theme_frame,
                text="Dark Mode" if not self.dark_mode else "Light Mode",
                command=self.toggle_theme,
                variant="theme",
                size="md"
            )
            self.theme_button.pack(side=tk.LEFT)

            action_buttons_frame = tk.Frame(self.button_frame, bg=self.bg_color)
            action_buttons_frame.pack(side=tk.RIGHT)

            self.cancel_button = self.create_button(
                action_buttons_frame,
                text="Close",
                command=self.cancel,
                variant="secondary",
                size="md"
            )
            self.cancel_button.pack(side=tk.LEFT, padx=(0, 5))

            self.play_button = self.create_button(
                action_buttons_frame,
                text="▶ Play Videos",
                command=self.play_videos,
                variant="danger",
                size="lg",
                font=(self.normal_font.name, self.normal_font.actual()['size'], 'bold')
            )
            self.play_button.pack(side=tk.LEFT)

        def setup_status_section(self):
            self.status_frame = tk.Frame(self.main_frame, bg=self.bg_color)
            self.status_frame.pack(fill=tk.X)

            self.video_count_label = tk.Label(
                self.status_frame,
                text="Total Videos: 0",
                font=self.normal_font,
                bg=self.bg_color,
                fg=self.text_color
            )
            self.video_count_label.pack(side=tk.LEFT)

        def add_directory(self):
            directory = filedialog.askdirectory(title="Select a Directory")
            if directory and directory not in self.selected_dirs:
                self.selected_dirs.append(directory)

                display_name = directory
                if len(directory) > 60:
                    display_name = os.path.basename(directory)
                    parent = os.path.dirname(directory)
                    if parent:
                        display_name = f"{os.path.basename(parent)}/{display_name}"
                    display_name = f".../{display_name}"

                self.dir_listbox.insert(tk.END, display_name)
                self.update_console(f"Added directory: {directory}")
                self.update_console(f"Scanning '{os.path.basename(directory)}' for videos...")
                self._submit_scan(directory)
                self.update_video_count()
                self.save_preferences()

        def remove_directory(self):
            selected_indices = self.dir_listbox.curselection()
            if not selected_indices:
                messagebox.showinfo("Information", "Please select a directory to remove.")
                return

            for i in sorted(selected_indices, reverse=True):
                dir_to_remove = self.selected_dirs[i]
                self.update_console(f"Removed directory: {os.path.basename(dir_to_remove)}")

                total_cleared = 0
                if dir_to_remove in self.excluded_subdirs:
                    total_cleared += len(self.excluded_subdirs[dir_to_remove])
                    del self.excluded_subdirs[dir_to_remove]
                if dir_to_remove in self.excluded_videos:
                    total_cleared += len(self.excluded_videos[dir_to_remove])
                    del self.excluded_videos[dir_to_remove]
                if total_cleared:
                    self.update_console(f"Cleared {total_cleared} exclusions for '{os.path.basename(dir_to_remove)}'")

                if hasattr(self, 'scan_cache') and dir_to_remove in self.scan_cache:
                    del self.scan_cache[dir_to_remove]
                if hasattr(self, 'pending_scans'):
                    self.pending_scans.discard(dir_to_remove)

                self.dir_listbox.delete(i)
                self.selected_dirs.pop(i)

            if self.current_selected_dir_index is not None:
                if self.current_selected_dir_index >= len(self.selected_dirs):
                    self.current_selected_dir_index = None

            self.update_video_count()
            self.clear_exclusion_list()
            self.save_preferences()

        def draw_slider(self):
            if not hasattr(self, 'speed_canvas'):
                return

            self.speed_canvas.delete("all")
            canvas_width = self.speed_canvas.winfo_width()
            if canvas_width <= 1:
                canvas_width = self.slider_width

            canvas_height = 6

            track_y = canvas_height // 2
            self.speed_canvas.create_rectangle(
                0, track_y - 1, canvas_width, track_y + 1,
                fill="#e0e0e0", outline="", tags="track"
            )

            progress = (self.slider_current - self.slider_min) / (self.slider_max - self.slider_min)
            handle_x = progress * canvas_width

            self.speed_canvas.create_rectangle(
                0, track_y - 1, handle_x, track_y + 1,
                fill=self.accent_color, outline="", tags="progress"
            )

            handle_radius = 8
            self.speed_canvas.create_oval(
                handle_x - handle_radius, track_y - handle_radius,
                handle_x + handle_radius, track_y + handle_radius,
                fill="gray", outline=self.accent_color, width=2, tags="handle"
            )

            speeds = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
            for speed in speeds:
                marker_progress = (speed - self.slider_min) / (self.slider_max - self.slider_min)
                marker_x = marker_progress * canvas_width

                if speed == 1.0:
                    self.speed_canvas.create_oval(
                        marker_x - 2, track_y - 2, marker_x + 2, track_y + 2,
                        fill=self.accent_color, outline="", tags="marker"
                    )
                else:
                    self.speed_canvas.create_oval(
                        marker_x - 1, track_y - 1, marker_x + 1, track_y + 1,
                        fill="#cccccc", outline="", tags="marker"
                    )

        def on_slider_configure(self, event):
            self.draw_slider()

        def on_slider_click(self, event):
            self.dragging = True
            self.update_slider_from_mouse(event.x)

        def on_slider_drag(self, event):
            if self.dragging:
                self.update_slider_from_mouse(event.x)

        def on_slider_release(self, event):
            self.dragging = False

        def update_slider_from_mouse(self, x):
            canvas_width = self.speed_canvas.winfo_width()
            if canvas_width <= 1:
                return

            progress = max(0, min(1, x / canvas_width))
            new_value = self.slider_min + progress * (self.slider_max - self.slider_min)

            new_value = round(new_value * 4) / 4
            new_value = max(self.slider_min, min(self.slider_max, new_value))

            if new_value != self.slider_current:
                self.slider_current = new_value
                self.speed_var.set(new_value)
                self.speed_display.config(text=f"{new_value}×")

                if self.controller:
                    self.controller.set_playback_rate(new_value)
                    self.update_console(f"Playback speed set to {new_value}×")

                self.draw_slider()

        def reset_speed(self):
            self.slider_current = 1.0
            self.speed_var.set(1.0)
            self.speed_display.config(text="1.0×")
            if self.controller:
                self.controller.set_playback_rate(1.0)
                self.update_console("Playback speed reset to 1.0×")
            self.draw_slider()

        def _add_to_playlist(self):
            """Add selected or all videos to playlist"""
            if self.ai_mode and self.current_subdirs_mapping:
                # AI mode - add search results
                ai_video_paths = []
                for i in range(len(self.current_subdirs_mapping)):
                    if i in self.current_subdirs_mapping:
                        path = self.current_subdirs_mapping[i]
                        if os.path.isfile(path) and is_video(path):
                            ai_video_paths.append(path)

                if ai_video_paths:
                    self.playlist_manager.add_videos_to_playlist([], ai_video_paths)
                    self.update_console(f"Added {len(ai_video_paths)} AI search results to playlist")
                else:
                    messagebox.showwarning("Warning", "No valid videos found in AI search results")
                return

            # Normal mode - collect videos from selected directories
            if not self.selected_dirs:
                messagebox.showwarning("Warning", "Please select directories first")
                return

            self.add_to_playlist_button.config(text="Adding...", state=tk.DISABLED)
            self.update_console("Collecting videos for playlist...")

            def collect_videos():
                try:
                    # Get all videos from selected directories
                    all_videos = []
                    for directory in self.selected_dirs:
                        cache = self.scan_cache.get(directory)
                        if cache:
                            videos, _, _ = cache
                            # Apply exclusion filters
                            excluded_subdirs = self.excluded_subdirs.get(directory, [])
                            excluded_videos = self.excluded_videos.get(directory, [])

                            for video in videos:
                                if not self.is_video_excluded(directory, video):
                                    all_videos.append(video)

                    def finish_collection():
                        self.add_to_playlist_button.config(text="Add to Playlist", state=tk.NORMAL)
                        if all_videos:
                            self.playlist_manager.add_videos_to_playlist(all_videos)
                            self.update_console(f"Processed {len(all_videos)} videos for playlist")
                        else:
                            messagebox.showwarning("Warning", "No videos found to add to playlist")

                    self.root.after(0, finish_collection)

                except Exception as e:
                    def show_error():
                        self.add_to_playlist_button.config(text="Add to Playlist", state=tk.NORMAL)
                        messagebox.showerror("Error", f"Failed to collect videos: {e}")

                    self.root.after(0, show_error)

            threading.Thread(target=collect_videos, daemon=True).start()

        def _manage_playlists(self):
            """Open playlist manager window"""
            self.playlist_manager.show_manager()

        def _play_playlist_videos(self, videos):
            """Play videos from playlist"""
            if not videos:
                messagebox.showwarning("Warning", "Playlist is empty")
                return

            # Stop current player if running
            if self.controller:
                self.controller.stop()
                cleanup_hotkeys()

            self.update_console("=" * 100)
            self.update_console("STARTING PLAYLIST PLAYBACK")
            self.update_console("=" * 100)

            # Create video mapping for playlist
            all_video_to_dir = {}
            all_directories = []

            for video_path in videos:
                if os.path.isfile(video_path):
                    video_dir = os.path.dirname(video_path)
                    all_video_to_dir[video_path] = video_dir
                    if video_dir not in all_directories:
                        all_directories.append(video_dir)

            all_directories.sort()
            valid_videos = list(all_video_to_dir.keys())

            if not valid_videos:
                messagebox.showwarning("Warning", "No valid videos found in playlist")
                return

            def start_playlist_player():
                self.update_console(f"Playing playlist with {len(valid_videos)} videos")
                self.controller = VLCPlayerControllerForMultipleDirectory(
                    valid_videos, all_video_to_dir, all_directories, self.update_console
                )
                # Set watch history tracking
                self.controller.set_watch_history_callback(
                    self.watch_history_manager.track_video_playback
                )
                # Set resume playback manager
                self.controller.set_resume_manager(self.resume_manager)

                # Apply current speed setting
                initial_speed = self.speed_var.get()
                if initial_speed != 1.0:
                    self.controller.set_initial_playback_rate(initial_speed)
                    self.update_console(f"Initial playback speed set to {initial_speed}x")

                self.controller.set_start_index(0)
                self.controller.set_video_change_callback(self.on_video_changed)

                if self.player_thread and self.player_thread.is_alive():
                    self.controller.running = False
                    self.player_thread.join(timeout=1.0)

                self.player_thread = threading.Thread(target=self.controller.run, daemon=True)
                self.player_thread.start()

                self.keys_thread = threading.Thread(target=lambda: listen_keys(self.controller), daemon=True)
                self.keys_thread.start()

            threading.Thread(target=start_playlist_player, daemon=True).start()

        def _show_watch_history(self):
            """Open watch history manager window"""
            self.watch_history_manager.show_manager()

        def toggle_resume_playback(self):
            """Toggle resume from last position feature"""
            enabled = bool(self.resume_playback_var.get())
            self.resume_manager.set_resume_enabled(enabled)
            self.save_preferences()

            status = "enabled" if enabled else "disabled"
            self.update_console(f"Resume from last position {status}")

        def _show_settings(self):
            """Open application settings window"""
            self.settings_manager.show_settings()

        def _on_settings_changed(self, new_settings):
            """Handle settings changes"""
            self.ai_index_path = new_settings.ai_index_path
            self.update_console(f"Settings updated - AI index path: {new_settings.ai_index_path}")

            # Update resume manager cleanup settings
            if hasattr(self, 'resume_manager'):
                self.resume_manager._auto_cleanup_days = new_settings.auto_cleanup_days

            # If AI mode is active, check if index path is still valid
            if self.ai_mode:
                required_files = ["clip_index.faiss", "text_index.faiss", "metadata.pkl", "tfidf_index.pkl"]
                files_exist = all(os.path.exists(os.path.join(new_settings.ai_index_path, f)) for f in required_files)

                if not files_exist:
                    self.ai_mode = False
                    self.ai_button.config(text="AI Mode")
                    self.update_console("AI mode disabled - index files not found at new path")
                    self.update_ui_for_mode()

        def _cleanup_watch_history_data(self):
            """Helper method to cleanup watch history data"""
            try:
                # This would need to call the watch history manager's cleanup method
                # For now, return 0 as placeholder
                return 0
            except Exception:
                return 0

        def cancel(self):
            if self.controller:
                if self.start_from_last_played and hasattr(self.controller, 'index'):
                    self.last_played_video_index = self.controller.index
                    if self.controller.index < len(self.controller.videos):
                        self.last_played_video_path = self.controller.videos[self.controller.index]
                    self.save_preferences()

                self.controller.stop()
            cleanup_hotkeys()
            try:
                if hasattr(self, 'executor'):
                    self.executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            try:
                self.resume_manager.force_save_positions()
            except Exception:
                pass
            self.root.quit()
            self.root.destroy()

    root = tk.Tk()
    app = DirectorySelector(root)
    root.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    select_multiple_folders_and_play()
