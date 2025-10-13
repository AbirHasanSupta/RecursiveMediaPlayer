import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from tkinter.font import Font
import os
import sys
import multiprocessing
from concurrent.futures import ProcessPoolExecutor

from key_press import listen_keys, cleanup_hotkeys
from managers.favorites_manager import FavoritesManager
from managers.filter_sort_manager import AdvancedFilterSortManager
from managers.filter_sort_ui import FilterSortUI
from managers.grid_view_manager import GridViewManager
from theme import ThemeSelector
from utils import gather_videos_with_directories, is_video
from vlc_player_controller import VLCPlayerControllerForMultipleDirectory
from managers.playlist_manager import PlaylistManager
from managers.watch_history_manager import WatchHistoryManager
from managers.resume_playback_manager import ResumePlaybackManager
from managers.settings_manager import SettingsManager
from managers.video_preview_manager import VideoPreviewManager
from managers.video_queue_manager import VideoQueueManager
import win32clipboard as wcb
import win32con
import struct
import socket
import time


def select_multiple_folders_and_play():
    port_file = os.path.expanduser("~/.rmp_instance_port")

    if len(sys.argv) > 1:
        arg_path = sys.argv[1]
        if os.path.isdir(arg_path):
            if os.path.exists(port_file):
                try:
                    with open(port_file, 'r') as f:
                        port = int(f.read().strip())

                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    result = sock.connect_ex(("127.0.0.1", port))
                    sock.close()

                    if result == 0:
                        import win32gui
                        import win32con
                        hwnd = win32gui.FindWindow(None, "Recursive Video Player")
                        if hwnd:
                            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                            win32gui.SetForegroundWindow(hwnd)
                            time.sleep(0.5)

                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.connect(("127.0.0.1", port))
                        sock.send(arg_path.encode())
                        sock.close()
                        return
                except:
                    pass

    class DirectorySelector(ThemeSelector):
        def __init__(self, root):
            super().__init__()
            self.root = root
            self.selected_dirs = []
            self.excluded_subdirs = {}
            self.excluded_videos = {}
            self._is_filtered_mode = False
            self._filtered_videos = []
            self._base_directory = None
            self.controller = None
            self.player_thread = None
            self.keys_thread = None
            self.video_count = 0
            self.current_selected_dir_index = None
            self.current_subdirs_mapping = {}
            self.show_videos = True
            self.show_only_excluded = False
            self.search_query = ""
            self.expanded_paths = set()
            self.collapsed_paths = set()
            self.current_max_depth = 20
            self.loop_mode = "loop_on"

            preferences = self.config.load_preferences()
            self.dark_mode = preferences['dark_mode']
            self.show_videos = preferences['show_videos']
            self.expand_all_default = preferences['expand_all']
            self.save_directories = preferences['save_directories']
            self.smart_resume_enabled = preferences['smart_resume_enabled']
            self.start_from_last_played = self.smart_resume_enabled
            self.last_played_video_index = preferences['last_played_video_index']
            self.last_played_video_path = preferences['last_played_video_path']
            self.excluded_subdirs = preferences.get('excluded_subdirs', {})
            self.excluded_videos = preferences.get('excluded_videos', {})
            self.volume = preferences.get('volume', 50)
            self.loop_mode = preferences.get('loop_mode', 'loop_on')

            self.setup_theme()

            root.title("Recursive Video Player")
            root.geometry("1600x900")
            root.state('zoomed')
            root.protocol("WM_DELETE_WINDOW", self.cancel)
            root.configure(bg=self.bg_color)

            self.setup_main_layout()
            self.setup_directory_section()
            self.setup_exclusion_section()
            self.setup_status_section()
            self.setup_console_section()
            self.setup_action_buttons()

            def start_ipc_server():
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]

                port_file = os.path.expanduser("~/.rmp_instance_port")
                with open(port_file, 'w') as f:
                    f.write(str(port))

                sock.listen(1)

                def accept_connections():
                    while True:
                        try:
                            conn, addr = sock.accept()
                            data = conn.recv(1024).decode()
                            conn.close()
                            if data and os.path.isdir(data):
                                self.root.after(0, lambda: self._add_directory_from_ipc(data))
                        except:
                            break

                threading.Thread(target=accept_connections, daemon=True).start()

            start_ipc_server()


            self.scan_cache = {}
            self.pending_scans = set()
            max_workers = min(8, (os.cpu_count() or 4))
            self.executor = ProcessPoolExecutor(max_workers=max_workers)
            self.apply_theme()
            command_line_dir = self._get_command_line_directory()
            if command_line_dir:
                self.selected_dirs = []
                if self.save_directories:
                    self.selected_dirs = preferences.get('selected_dirs', [])

                if command_line_dir not in self.selected_dirs:
                    self.selected_dirs.append(command_line_dir)

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
            elif self.save_directories:
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

            self.playlist_manager = PlaylistManager(self.root, self)
            self.playlist_manager.set_play_callback(self._play_playlist_videos)

            self.watch_history_manager = WatchHistoryManager(self.root, self)
            self.watch_history_manager.set_play_callback(self._play_history_videos)
            self.resume_manager = ResumePlaybackManager()
            self.resume_manager.set_resume_enabled(self.smart_resume_enabled)
            self.settings_manager = SettingsManager(self.root, self, self.update_console)
            self.settings_manager.add_settings_changed_callback(self._on_settings_changed)

            app_settings = self.settings_manager.get_settings()
            self.video_preview_manager = VideoPreviewManager(self.root, self.update_console)
            self.playlist_manager.ui.video_preview_manager = self.video_preview_manager

            self.video_preview_manager.set_preview_duration(app_settings.preview_duration)
            self.video_preview_manager.set_video_preview_enabled(app_settings.use_video_preview)

            self.settings_manager.ui.cleanup_resume_callback = lambda: self.resume_manager.service.cleanup_old_positions(
                self.settings_manager.get_settings().auto_cleanup_days)
            self.settings_manager.ui.cleanup_history_callback = lambda: self.watch_history_manager.service.cleanup_old_entries(
                self.settings_manager.get_settings().auto_cleanup_days)
            self.settings_manager.ui.clear_thumbnails_callback = lambda: self._clear_thumbnail_cache()
            self.settings_manager.ui.video_preview_manager = self.video_preview_manager

            self.grid_view_manager = GridViewManager(self.root, self, self.update_console)
            self.grid_view_manager.set_play_callback(self._play_grid_videos)
            self.queue_manager = VideoQueueManager(self.root, self)
            self.queue_manager.set_play_callback(self._play_queue_videos)
            self.favorites_manager = FavoritesManager(self.root, self)
            self.favorites_manager.set_play_callback(self._play_favorites_videos)

            self.filter_sort_manager = AdvancedFilterSortManager(
                watch_history_manager=self.watch_history_manager
            )

            self.filter_sort_ui = FilterSortUI(
                self.root,
                self,
                self.filter_sort_manager,
                self._apply_filters_and_refresh
            )

        def _add_directory_from_ipc(self, directory):
            if directory not in self.selected_dirs:
                self.selected_dirs.append(directory)
                display_name = directory
                if len(directory) > 60:
                    display_name = os.path.basename(directory)
                    parent = os.path.dirname(directory)
                    if parent:
                        display_name = f"{os.path.basename(parent)}/{display_name}"
                    display_name = f".../{display_name}"
                self.dir_listbox.insert(tk.END, display_name)
                self._submit_scan(directory)
                self.update_video_count()
                self.save_preferences()

        def _get_command_line_directory(self):
            if len(sys.argv) > 1:
                arg_path = sys.argv[1]
                if os.path.isdir(arg_path):
                    return os.path.abspath(arg_path)
            return None

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
            self.search_frame = tk.Frame(self.exclusion_section, bg=self.bg_color)
            self.search_frame.pack(fill=tk.X, pady=(0, 10))

            search_label = tk.Label(self.search_frame, text="Search:",
                                    font=self.small_font, bg=self.bg_color, fg=self.text_color)
            search_label.pack(side=tk.LEFT, padx=(0, 5))

            self.search_entry = tk.Entry(
                self.search_frame,
                font=self.normal_font,
                bg="white",
                fg=self.text_color,
                relief=tk.FLAT,
                bd=1,
                highlightthickness=1,
                highlightbackground="#e0e0e0"
            )
            self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
            self.search_entry.bind('<KeyRelease>', self.on_search_changed)

            clear_search_btn = self.create_button(
                self.search_frame,
                text="Clear",
                command=self.clear_search,
                variant="secondary",
                size="sm"
            )
            clear_search_btn.pack(side=tk.LEFT)

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

            self.exclusion_listbox.bind("<Button-3>", self._show_context_menu)
            self.exclusion_listbox.bind("<Button-1>", self._on_left_click)
            self.exclusion_listbox.bind("<Double-Button-1>", self._on_double_click)
            self._create_context_menu()

            self.exclusion_buttons_frame = tk.Frame(self.exclusion_section, bg=self.bg_color)
            self.exclusion_buttons_frame.pack(fill=tk.X, pady=(10, 0))


            self.normal_mode_frame = tk.Frame(self.exclusion_buttons_frame, bg=self.bg_color)
            self.normal_mode_frame.pack(fill=tk.X)

            checkboxes_row = tk.Frame(self.normal_mode_frame, bg=self.bg_color)
            checkboxes_row.pack(fill=tk.X, pady=(0, 5))

            checkboxes_row = tk.Frame(self.exclusion_buttons_frame, bg=self.bg_color)
            checkboxes_row.pack(fill=tk.X, pady=(0, 5))

            self.show_videos_var = tk.BooleanVar(value=self.show_videos)
            self.excluded_only_var = tk.BooleanVar(value=self.show_only_excluded)
            self.expand_all_var = tk.BooleanVar(value=self.expand_all_default)
            self.save_directories_var = tk.BooleanVar(value=self.save_directories)


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

            self.smart_resume_var = tk.BooleanVar(value=self.smart_resume_enabled)
            self.smart_resume_check = ttk.Checkbutton(
                checkboxes_row,
                text="Resume Playback",
                style="Modern.TCheckbutton",
                variable=self.smart_resume_var,
                command=self.toggle_smart_resume
            )
            self.smart_resume_check.pack(side=tk.LEFT, padx=(15, 0))

            buttons_row = tk.Frame(self.exclusion_buttons_frame, bg=self.bg_color)
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

            buttons_row3 = tk.Frame(self.exclusion_buttons_frame, bg=self.bg_color)
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

            media_section = tk.Frame(self.exclusion_buttons_frame, bg=self.bg_color)
            media_section.pack(fill=tk.X, pady=(10, 0))

            media_label = tk.Label(
                media_section,
                text="Media:",
                font=self.small_font,
                bg=self.bg_color,
                fg="#666666"
            )
            media_label.pack(side=tk.LEFT, padx=(0, 8))

            # self.add_to_playlist_button = self.create_button(
            #     media_section, "Add to Playlist",
            #     self._add_to_playlist, "playlist", "sm"
            # )
            # self.add_to_playlist_button.pack(side=tk.LEFT, padx=(0, 5))

            self.manage_playlist_button = self.create_button(
                media_section, "Manage Playlists",
                self._manage_playlists, "playlist", "sm"
            )
            self.manage_playlist_button.pack(side=tk.LEFT, padx=(0, 5))

            self.queue_manager_button = self.create_button(
                media_section, "Manage Queue",
                self._show_queue_manager, "primary", "sm"
            )
            self.queue_manager_button.pack(side=tk.LEFT, padx=(0, 5))

            self.favorites_button = self.create_button(
                media_section, "Favorites",
                self._show_favorites_manager, "warning", "sm"
            )
            self.favorites_button.pack(side=tk.LEFT, padx=(0, 5))

            self.watch_history_button = self.create_button(
                media_section, "Watch History",
                self._show_watch_history, "history", "sm"
            )
            self.watch_history_button.pack(side=tk.LEFT)

            self.root.after(100, self.draw_slider)


        def _create_context_menu(self):
            self.context_menu = tk.Menu(self.root, tearoff=0)

        def _on_left_click(self, event):
            pass

        def _show_context_menu(self, event):
            listbox = event.widget
            index = listbox.nearest(event.y)
            selection = listbox.curselection()

            if not selection and index >= 0 and index < listbox.size():
                video_path = self.current_subdirs_mapping.get(index)
                if video_path and os.path.isfile(video_path):
                    self.video_preview_manager.right_clicked_item = index
                    self.video_preview_manager._show_video_preview(video_path, event.x_root, event.y_root)
                return

            if not selection:
                return

            self.context_menu.delete(0, tk.END)

            first_index = selection[0]
            first_path = self.current_subdirs_mapping.get(first_index)

            self.context_menu.add_command(
                label="Play Selected",
                command=self.play_videos
            )
            self.context_menu.add_separator()

            total_items = listbox.size()
            selected_count = len(selection)

            if selected_count < total_items:
                self.context_menu.add_command(
                    label="Select All",
                    command=lambda: self._select_all_items(listbox)
                )

            if selected_count > 0:
                self.context_menu.add_command(
                    label="Unselect All",
                    command=lambda: listbox.selection_clear(0, tk.END)
                )

            self.context_menu.add_separator()
            self.context_menu.add_command(
                label="Open in Grid View",
                command=lambda: self._context_open_grid_view(selection)
            )

            self.context_menu.add_separator()
            self.context_menu.add_command(
                label="Exclude Selected",
                command=self.exclude_subdirectories
            )
            self.context_menu.add_command(
                label="Include Selected",
                command=self.include_subdirectories
            )

            self.context_menu.add_separator()
            self.context_menu.add_command(
                label="Add to Playlist",
                command=lambda: self._context_add_to_playlist(selection)
            )

            self.context_menu.add_command(
                label="⭐ Add to Favorites",
                command=lambda: self._context_add_to_favorites(selection)
            )

            self.context_menu.add_command(
                label="★ Remove from Favorites",
                command=lambda: self._context_remove_from_favorites(selection)
            )

            self.context_menu.add_separator()
            self.context_menu.add_command(
                label="Add to Queue",
                command=lambda: self._context_add_to_queue(selection, mode="queue")
            )
            self.context_menu.add_command(
                label="Play Next",
                command=lambda: self._context_add_to_queue(selection, mode="next")
            )

            self.context_menu.add_separator()

            self.context_menu.add_command(
                label=f"Copy ({len(selection)} item{'s' if len(selection) > 1 else ''})",
                command=lambda: self._context_copy_selected(selection)
            )

            if len(selection) == 1 and first_path and os.path.isfile(first_path):
                self.context_menu.add_command(
                    label="Copy Path",
                    command=lambda: self._context_copy_path(first_path)
                )
                self.context_menu.add_command(
                    label="Open File Location",
                    command=lambda: self._context_open_location(first_path)
                )
                self.context_menu.add_command(
                    label="Properties",
                    command=lambda: self._context_show_properties(first_path)
                )

            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()

        def _show_favorites_manager(self):
            selected_dir = self.get_current_selected_directory()
            self.favorites_manager.show_manager(selected_dir)

        def _context_add_to_favorites(self, selection):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                return

            selected_videos = []
            for index in selection:
                item_path = self.current_subdirs_mapping.get(index)
                if item_path and os.path.isfile(item_path) and is_video(item_path):
                    selected_videos.append(item_path)
                elif item_path and os.path.isdir(item_path):
                    for root, dirs, files in os.walk(item_path):
                        for file in files:
                            full_path = os.path.join(root, file)
                            if is_video(full_path):
                                selected_videos.append(full_path)

            if selected_videos:
                count = self.favorites_manager.add_to_favorites(selected_videos, selected_dir)
                self.update_console(f"Added {count} video(s) to favorites")

                scroll_pos = self.exclusion_listbox.yview()
                self.load_subdirectories(selected_dir, restore_scroll=scroll_pos)

        def _context_remove_from_favorites(self, selection):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                return

            selected_videos = []
            for index in selection:
                item_path = self.current_subdirs_mapping.get(index)
                if item_path and os.path.isfile(item_path) and is_video(item_path):
                    selected_videos.append(item_path)

            if selected_videos:
                count = self.favorites_manager.remove_from_favorites(selected_videos, selected_dir)
                self.update_console(f"Removed {count} video(s) from favorites")

                scroll_pos = self.exclusion_listbox.yview()
                self.load_subdirectories(selected_dir, restore_scroll=scroll_pos)

        def _play_favorites_videos(self, videos):
            if not videos:
                return

            if self.controller:
                self.controller.stop()
                cleanup_hotkeys()

            all_video_to_dir = {v: os.path.dirname(v) for v in videos}
            all_directories = sorted(list(set(all_video_to_dir.values())))

            self.update_console(f"Playing {len(videos)} videos from favorites")

            self.controller = VLCPlayerControllerForMultipleDirectory(
                videos, all_video_to_dir, all_directories, self.update_console
            )
            self.controller.set_loop_mode(self.loop_mode)
            self.controller.volume = self.volume
            self.controller.player.audio_set_volume(self.volume)
            self.controller.set_volume_save_callback(self._save_volume_callback)
            self.controller.set_watch_history_callback(self.watch_history_manager.track_video_playback)
            self.controller.set_resume_manager(self.resume_manager)

            initial_speed = self.speed_var.get()
            if initial_speed != 1.0:
                self.controller.set_initial_playback_rate(initial_speed)

            self.controller.set_start_index(0)
            self.controller.set_video_change_callback(self.on_video_changed)

            if self.player_thread and self.player_thread.is_alive():
                self.controller.running = False
                self.player_thread.join(timeout=1.0)

            self.player_thread = threading.Thread(target=self.controller.run, daemon=True)
            self.player_thread.start()

            self.keys_thread = threading.Thread(target=lambda: listen_keys(self.controller), daemon=True)
            self.keys_thread.start()

        def _select_all_items(self, listbox):
            listbox.selection_clear(0, tk.END)
            listbox.selection_set(0, tk.END)

        def _context_open_grid_view(self, selection):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                return

            self.exclusion_listbox.selection_clear(0, tk.END)
            for idx in selection:
                self.exclusion_listbox.selection_set(idx)

            self._show_grid_view()

        def _context_copy_selected(self, selection):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                return

            paths_to_copy = []
            for index in selection:
                item_path = self.current_subdirs_mapping.get(index)
                if item_path:
                    paths_to_copy.append(item_path)

            if paths_to_copy:
                file_list = "\0".join(paths_to_copy) + "\0"
                file_struct = struct.pack("Iiiii", 20, 0, 0, 0, len(paths_to_copy))
                files_encoded = file_list.encode("utf-16le") + b"\0\0"
                data = file_struct + files_encoded

                try:
                    wcb.OpenClipboard()
                    wcb.EmptyClipboard()
                    wcb.SetClipboardData(win32con.CF_HDROP, data)
                    wcb.CloseClipboard()
                    self.update_console(f"Copied {len(paths_to_copy)} item(s) to clipboard")
                except Exception as e:
                    self.update_console(f"Error copying to clipboard: {e}")

        def _context_add_to_playlist(self, selection):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                return

            selected_videos = []
            for index in selection:
                item_path = self.current_subdirs_mapping.get(index)
                if item_path and os.path.isfile(item_path) and is_video(item_path):
                    selected_videos.append(item_path)
                elif item_path and os.path.isdir(item_path):
                    for root, dirs, files in os.walk(item_path):
                        for file in files:
                            full_path = os.path.join(root, file)
                            if is_video(full_path):
                                selected_videos.append(full_path)

            if selected_videos:
                self.playlist_manager.add_videos_to_playlist([], selected_videos)

        def _context_copy_path(self, file_path):
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(file_path)
                self.update_console(f"Copied path: {file_path}")
            except Exception as e:
                self.update_console(f"Error copying path: {e}")

        def _context_open_location(self, file_path):
            try:
                import subprocess
                if os.name == 'nt':
                    subprocess.Popen(f'explorer /select,"{file_path}"')
                elif os.name == 'posix':
                    if sys.platform == 'darwin':
                        subprocess.Popen(['open', '-R', file_path])
                    else:
                        subprocess.Popen(['xdg-open', os.path.dirname(file_path)])
                self.update_console(f"Opened location: {os.path.dirname(file_path)}")
            except Exception as e:
                self.update_console(f"Error opening location: {e}")
                messagebox.showerror("Error", f"Could not open file location: {e}")

        def _context_show_properties(self, file_path):
            try:
                stat_info = os.stat(file_path)
                size_mb = stat_info.st_size / (1024 * 1024)
                modified = datetime.fromtimestamp(stat_info.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

                info = f"File: {os.path.basename(file_path)}\n\n"
                info += f"Path: {file_path}\n\n"
                info += f"Size: {size_mb:.2f} MB ({stat_info.st_size:,} bytes)\n\n"
                info += f"Modified: {modified}\n\n"

                try:
                    import cv2
                    cap = cv2.VideoCapture(file_path)
                    if cap.isOpened():
                        fps = cap.get(cv2.CAP_PROP_FPS)
                        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                        duration = frame_count / fps if fps > 0 else 0
                        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

                        info += f"Duration: {int(duration // 60)}:{int(duration % 60):02d}\n"
                        info += f"Resolution: {width}x{height}\n"
                        info += f"FPS: {fps:.2f}\n"
                        cap.release()
                except:
                    pass

                messagebox.showinfo("Properties", info)
                self.update_console(f"Showing properties for: {os.path.basename(file_path)}")
            except Exception as e:
                messagebox.showerror("Error", f"Could not retrieve properties: {e}")

        def _on_double_click(self, event):
            if not self.current_subdirs_mapping:
                return

            listbox = event.widget
            index = listbox.nearest(event.y)
            if index < 0 or index >= listbox.size():
                return

            target_path = self.current_subdirs_mapping.get(index)
            if not target_path:
                return

            if os.path.isdir(target_path):
                selected_dir = self.get_current_selected_directory()
                if not selected_dir:
                    return

                norm_target = os.path.normpath(target_path)
                if self.expand_all_var.get():
                    if norm_target in self.collapsed_paths:
                        self.collapsed_paths.remove(norm_target)
                    else:
                        self.collapsed_paths.add(norm_target)
                else:
                    if norm_target in self.expanded_paths:
                        self.expanded_paths.remove(norm_target)
                    else:
                        self.expanded_paths.add(norm_target)

                scroll_pos = listbox.yview()
                self.load_subdirectories(selected_dir, max_depth=20, restore_path=norm_target,
                                         restore_scroll=scroll_pos)
                return "break"

            if not os.path.isfile(target_path) or not is_video(target_path):
                return

            listbox.selection_clear(0, tk.END)
            listbox.selection_set(index)
            listbox.activate(index)

            self.root.after(100, self.play_videos)

            return "break"

        def on_search_changed(self, event=None):
            try:
                self.search_query = self.search_entry.get().strip().lower()
            except Exception:
                self.search_query = ""
            selected_dir = self.get_current_selected_directory()
            if selected_dir:
                self.load_subdirectories(selected_dir)

        def clear_search(self):
            if hasattr(self, 'search_entry'):
                self.search_entry.delete(0, tk.END)
                self.on_search_changed()

        def matches_search(self, path, search_query):
            if not search_query:
                return True

            basename = os.path.basename(path).lower()
            if search_query in basename:
                return True

            if os.path.isdir(path):
                try:
                    for root, dirs, files in os.walk(path):
                        for d in dirs:
                            if search_query in d.lower():
                                return True
                        for f in files:
                            if is_video(f) and search_query in f.lower():
                                return True
                except (PermissionError, OSError):
                    pass

            return False

        def is_child_of_matching_parent(self, path, base, search_query):
            if not search_query:
                return False

            current = os.path.dirname(path)
            while current != base and len(current) > len(base):
                if search_query in os.path.basename(current).lower():
                    return True
                current = os.path.dirname(current)
            return False

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

        def _apply_filters_and_refresh(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showwarning("Warning", "Please select a directory first")
                return

            progress_window = tk.Toplevel(self.root)
            progress_window.title("Applying Filters")
            progress_window.geometry("400x150")
            progress_window.configure(bg=self.bg_color)
            progress_window.transient(self.root)
            progress_window.grab_set()

            progress_label = tk.Label(
                progress_window,
                text="Processing videos...",
                font=self.normal_font,
                bg=self.bg_color,
                fg=self.text_color
            )
            progress_label.pack(pady=20)

            progress_bar = ttk.Progressbar(
                progress_window,
                length=350,
                mode='determinate'
            )
            progress_bar.pack(pady=10)

            status_label = tk.Label(
                progress_window,
                text="",
                font=self.small_font,
                bg=self.bg_color,
                fg="#666666"
            )
            status_label.pack()

            def update_progress(current, total):
                if total > 0:
                    progress = (current / total) * 100
                    progress_bar['value'] = progress
                    status_label.config(text=f"Processing {current}/{total} videos...")
                    progress_window.update()

            def process_in_thread():
                try:
                    cache = self.scan_cache.get(selected_dir)
                    if not cache:
                        def show_warning():
                            try:
                                progress_window.destroy()
                            except:
                                pass
                            messagebox.showwarning("Warning", "Directory not scanned yet")

                        self.root.after(0, show_warning)
                        return

                    videos, _, _ = cache

                    filtered_sorted = self.filter_sort_manager.apply_filter_and_sort(
                        videos,
                        load_properties=True,
                        progress_callback=lambda c, t: self.root.after(0, lambda: update_progress(c, t))
                    )

                    def update_ui():
                        try:
                            progress_window.destroy()
                        except:
                            pass

                        self._is_filtered_mode = True
                        self._filtered_videos = filtered_sorted
                        self._base_directory = selected_dir

                        self.exclusion_listbox.delete(0, tk.END)
                        self.current_subdirs_mapping = {}

                        if not filtered_sorted:
                            self.exclusion_listbox.insert(tk.END, "No videos match the current filters")
                            self.update_console("No videos match current filters")
                            return

                        for idx, video_path in enumerate(filtered_sorted):
                            try:
                                rel_path = os.path.relpath(video_path, selected_dir)
                            except ValueError:
                                rel_path = os.path.basename(video_path)

                            display_name = f"▶ {rel_path}"

                            if self.is_video_excluded(selected_dir, video_path):
                                display_name += " 🚫[EXCLUDED]"

                            self.exclusion_listbox.insert(tk.END, display_name)
                            self.current_subdirs_mapping[idx] = video_path

                        self.selected_dir_label.config(
                            text=f"Filtered: {len(filtered_sorted)} videos in '{os.path.basename(selected_dir)}'"
                        )
                        self.update_console(
                            f"Applied filters: {len(filtered_sorted)} videos shown from {len(videos)} total")

                        if hasattr(self, 'video_preview_manager'):
                            self.video_preview_manager.attach_to_listbox(
                                self.exclusion_listbox,
                                self.current_subdirs_mapping
                            )

                    self.root.after(0, update_ui)

                except Exception as e:
                    def show_error():
                        try:
                            progress_window.destroy()
                        except:
                            pass
                        messagebox.showerror("Error", f"Filter error: {e}")

                    self.root.after(0, show_error)

            threading.Thread(target=process_in_thread, daemon=True).start()

        def _reapply_filtered_view(self, scroll_pos=None):
            if not hasattr(self, '_filtered_videos') or not hasattr(self, '_base_directory'):
                return

            selected_dir = self._base_directory
            original_filtered = self._filtered_videos

            filtered_sorted = original_filtered

            self.exclusion_listbox.delete(0, tk.END)
            self.current_subdirs_mapping = {}

            if not filtered_sorted:
                self.exclusion_listbox.insert(tk.END, "No videos match the current filters")
                return

            for idx, video_path in enumerate(filtered_sorted):
                try:
                    rel_path = os.path.relpath(video_path, selected_dir)
                except ValueError:
                    rel_path = os.path.basename(video_path)

                display_name = f"▶ {rel_path}"

                if self.is_video_excluded(selected_dir, video_path):
                    display_name += " 🚫[EXCLUDED]"

                self.exclusion_listbox.insert(tk.END, display_name)
                self.current_subdirs_mapping[idx] = video_path

            self.selected_dir_label.config(
                text=f"Filtered: {len(filtered_sorted)} videos in '{os.path.basename(selected_dir)}'"
            )

            if hasattr(self, 'video_preview_manager'):
                self.video_preview_manager.attach_to_listbox(
                    self.exclusion_listbox,
                    self.current_subdirs_mapping
                )

            if scroll_pos:
                try:
                    self.exclusion_listbox.yview_moveto(scroll_pos[0])
                except:
                    pass

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
                is_filtered_mode = hasattr(self, '_is_filtered_mode') and self._is_filtered_mode

                exclusion_selection = self.exclusion_listbox.curselection()

                if is_filtered_mode and not exclusion_selection:
                    selected_dir = self.get_current_selected_directory()
                    if selected_dir and hasattr(self, '_filtered_videos'):
                        filtered_videos = [v for v in self._filtered_videos
                                           if not self.is_video_excluded(selected_dir, v)]

                        if not filtered_videos:
                            def _show_no_videos():
                                messagebox.showwarning("No Videos", "No filtered videos found (all excluded).")
                                self.root.config(cursor="")

                            self.root.after(0, _show_no_videos)
                            return

                        all_video_to_dir = {}
                        for video_path in filtered_videos:
                            all_video_to_dir[video_path] = os.path.dirname(video_path)

                        all_directories = sorted(list(set(all_video_to_dir.values())))

                        def _start_filtered_player():
                            self.update_console(f"Playing {len(filtered_videos)} filtered videos")
                            self.controller = VLCPlayerControllerForMultipleDirectory(
                                filtered_videos, all_video_to_dir, all_directories, self.update_console
                            )
                            self.controller.set_loop_mode(self.loop_mode)
                            self.controller.volume = self.volume
                            self.controller.player.audio_set_volume(self.volume)
                            self.controller.set_volume_save_callback(self._save_volume_callback)
                            self.controller.set_watch_history_callback(
                                self.watch_history_manager.track_video_playback
                            )
                            self.controller.set_resume_manager(self.resume_manager)

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

                            self.keys_thread = threading.Thread(target=lambda: listen_keys(self.controller),
                                                                daemon=True)
                            self.keys_thread.start()
                            self.root.config(cursor="")

                        self.root.after(0, _start_filtered_player)
                        return

                if is_filtered_mode and exclusion_selection:
                    selected_dir = self.get_current_selected_directory()
                    if selected_dir:
                        self.update_console("Playing selected filtered videos...")

                        selected_videos = []

                        for index in exclusion_selection:
                            item_path = self.current_subdirs_mapping.get(index)
                            if not item_path:
                                continue

                            if self.is_video_excluded(selected_dir, item_path):
                                continue

                            if os.path.isfile(item_path) and is_video(item_path):
                                selected_videos.append(item_path)

                        seen = set()
                        final_videos = []
                        for v in selected_videos:
                            v_norm = os.path.normpath(v)
                            if v_norm not in seen:
                                seen.add(v_norm)
                                final_videos.append(v_norm)

                        if not final_videos:
                            def _show_no_videos():
                                messagebox.showwarning("No Videos", "No valid non-excluded videos found in selection.")
                                self.root.config(cursor="")

                            self.root.after(0, _show_no_videos)
                            return

                        all_video_to_dir = {}
                        for video_path in final_videos:
                            all_video_to_dir[video_path] = os.path.dirname(video_path)

                        all_directories = sorted(list(set(all_video_to_dir.values())))

                        def _start_selected_player():
                            self.update_console(
                                f"Playing {len(final_videos)} selected filtered videos")
                            self.controller = VLCPlayerControllerForMultipleDirectory(
                                final_videos, all_video_to_dir, all_directories, self.update_console
                            )
                            self.controller.set_loop_mode(self.loop_mode)
                            self.controller.volume = self.volume
                            self.controller.player.audio_set_volume(self.volume)
                            self.controller.set_volume_save_callback(self._save_volume_callback)
                            self.controller.set_watch_history_callback(
                                self.watch_history_manager.track_video_playback
                            )
                            self.controller.set_resume_manager(self.resume_manager)

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

                            self.keys_thread = threading.Thread(target=lambda: listen_keys(self.controller),
                                                                daemon=True)
                            self.keys_thread.start()
                            self.root.config(cursor="")

                        self.root.after(0, _start_selected_player)
                        return

                if exclusion_selection:
                    selected_dir = self.get_current_selected_directory()
                    if selected_dir:
                        self.update_console("Playing selected items only...")

                        selected_videos = []
                        selected_folders = []

                        for index in exclusion_selection:
                            item_path = self.current_subdirs_mapping.get(index)
                            if not item_path:
                                continue

                            if os.path.isfile(item_path) and is_video(item_path):
                                if not self.is_video_excluded(selected_dir, item_path):
                                    selected_videos.append(item_path)
                            elif os.path.isdir(item_path):
                                selected_folders.append(item_path)

                        for folder in selected_folders:
                            try:
                                for root, dirs, files in os.walk(folder):
                                    for f in files:
                                        full_path = os.path.join(root, f)
                                        if is_video(full_path):
                                            if not self.is_video_excluded(selected_dir, full_path):
                                                selected_videos.append(full_path)
                            except Exception as e:
                                self.update_console(f"Error reading folder {folder}: {e}")

                        seen = set()
                        final_videos = []
                        for v in selected_videos:
                            v_norm = os.path.normpath(v)
                            if v_norm not in seen:
                                seen.add(v_norm)
                                final_videos.append(v_norm)

                        if not final_videos:
                            def _show_no_videos():
                                messagebox.showwarning("No Videos", "No valid non-excluded videos found in selection.")
                                self.root.config(cursor="")

                            self.root.after(0, _show_no_videos)
                            return

                        all_video_to_dir = {}
                        for video_path in final_videos:
                            all_video_to_dir[video_path] = os.path.dirname(video_path)

                        all_directories = sorted(list(set(all_video_to_dir.values())))

                        def _start_selected_player():
                            self.update_console(
                                f"Playing {len(final_videos)} selected videos")
                            self.controller = VLCPlayerControllerForMultipleDirectory(
                                final_videos, all_video_to_dir, all_directories, self.update_console
                            )
                            self.controller.set_loop_mode(self.loop_mode)
                            self.controller.volume = self.volume
                            self.controller.player.audio_set_volume(self.volume)
                            self.controller.set_volume_save_callback(self._save_volume_callback)
                            self.controller.set_watch_history_callback(
                                self.watch_history_manager.track_video_playback
                            )
                            self.controller.set_resume_manager(self.resume_manager)

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

                            self.keys_thread = threading.Thread(target=lambda: listen_keys(self.controller),
                                                                daemon=True)
                            self.keys_thread.start()
                            self.root.config(cursor="")

                        self.root.after(0, _start_selected_player)
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
                    self.controller.set_loop_mode(self.loop_mode)
                    self.controller.volume = self.volume
                    self.controller.player.audio_set_volume(self.volume)
                    self.controller.set_volume_save_callback(self._save_volume_callback)
                    self.controller.set_watch_history_callback(
                        self.watch_history_manager.track_video_playback
                    )
                    self.controller.set_resume_manager(self.resume_manager)

                    initial_speed = self.speed_var.get()
                    if initial_speed != 1.0:
                        self.controller.set_initial_playback_rate(initial_speed)
                        self.update_console(f"Initial playback speed set to {initial_speed}x")

                    start_index = 0
                    if self.smart_resume_var.get():
                        if self.last_played_video_path and self.last_played_video_path in all_videos:
                            start_index = all_videos.index(self.last_played_video_path)
                            self.update_console(
                                f"Smart Resume: Starting from last played video: {os.path.basename(self.last_played_video_path)}")
                        elif self.save_directories and self.last_played_video_index < len(all_videos):
                            start_index = self.last_played_video_index
                            self.update_console(f"Smart Resume: Starting from last played index: {start_index}")

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
            if hasattr(self, 'filter_sort_manager'):
                self.filter_sort_manager.metadata_cache.update_play_stats(video_path)
            self.last_played_video_index = video_index
            self.last_played_video_path = video_path
            if self.smart_resume_var.get():
                self.save_preferences()

        def on_directory_select(self, event):
            self._is_filtered_mode = False

            selection = self.dir_listbox.curselection()
            if not selection:
                if self.current_selected_dir_index is not None:
                    selected_dir = self.selected_dirs[self.current_selected_dir_index]
                    self.load_subdirectories(selected_dir, max_depth=20)
                else:
                    self.clear_exclusion_list()
                return

            selected_index = selection[0]
            if selected_index >= len(self.selected_dirs):
                return

            self.current_selected_dir_index = selected_index
            selected_dir = self.selected_dirs[selected_index]
            self.expanded_paths.clear()
            self.collapsed_paths.clear()
            self.load_subdirectories(selected_dir, max_depth=20)

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

            is_filtered_mode = hasattr(self, '_is_filtered_mode') and self._is_filtered_mode

            self.exclusion_listbox.delete(0, tk.END)
            self.exclusion_listbox.insert(tk.END, "Excluding all... Please wait")

            def worker(dir_path=selected_dir):
                dir_paths = []
                file_paths = []

                displayed_items = set()
                if hasattr(self, 'search_query') and self.search_query:
                    for idx in range(len(self.current_subdirs_mapping)):
                        if idx in self.current_subdirs_mapping:
                            displayed_items.add(self.current_subdirs_mapping[idx])

                try:
                    base = os.path.normpath(dir_path)
                    for root, dirs, files in os.walk(base):
                        for d in dirs:
                            subdir_path = os.path.join(root, d)
                            if not displayed_items or subdir_path in displayed_items:
                                dir_paths.append(subdir_path)
                        for f in files:
                            full = os.path.join(root, f)
                            if is_video(full):
                                if not displayed_items or full in displayed_items:
                                    file_paths.append(full)
                except Exception as e:
                    self.root.after(0, lambda: self.update_console(f"Error during Exclude All: {e}"))
                    self.root.after(0, lambda: [self.exclusion_listbox.delete(0, tk.END),
                                                self.exclusion_listbox.insert(tk.END, f"Error: {e}")])
                    return

                def apply_and_refresh():
                    if dir_paths:
                        if dir_path not in self.excluded_subdirs:
                            self.excluded_subdirs[dir_path] = []
                        existing = set(self.excluded_subdirs[dir_path])
                        for dp in dir_paths:
                            if dp not in existing:
                                self.excluded_subdirs[dir_path].append(dp)

                    if file_paths:
                        if dir_path not in self.excluded_videos:
                            self.excluded_videos[dir_path] = []
                        existing = set(self.excluded_videos[dir_path])
                        for fp in file_paths:
                            if fp not in existing:
                                self.excluded_videos[dir_path].append(fp)

                    total = len(dir_paths) + len(file_paths)
                    filter_msg = " (matching search filter)" if displayed_items else ""
                    self.update_console(
                        f"Excluded {total} items from '{os.path.basename(dir_path)}'{filter_msg}")

                    scroll_pos = self.exclusion_listbox.yview()

                    if is_filtered_mode and hasattr(self, '_filtered_videos'):
                        self._reapply_filtered_view(scroll_pos)
                    else:
                        self.load_subdirectories(dir_path, restore_scroll=scroll_pos)

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

            is_filtered_mode = hasattr(self, '_is_filtered_mode') and self._is_filtered_mode

            self.exclusion_listbox.insert(tk.END, "\nApplying exclusions... Please wait")
            for btn in [getattr(self, 'exclude_button', None), getattr(self, 'include_button', None),
                        getattr(self, 'exclude_all_button', None), getattr(self, 'clear_exclusions_button', None)]:
                if btn:
                    btn.config(state=tk.DISABLED)

            def worker(dir_path=selected_dir, indices=list(exclusion_selection)):
                dirs_to_exclude = set()
                vids_to_exclude = set()
                selected_names = []

                displayed_items = set()
                if hasattr(self, 'search_query') and self.search_query:
                    for idx in range(len(self.current_subdirs_mapping)):
                        if idx in self.current_subdirs_mapping:
                            displayed_items.add(self.current_subdirs_mapping[idx])

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
                                    subdir_path = os.path.join(root, d)
                                    if not displayed_items or subdir_path in displayed_items:
                                        dirs_to_exclude.add(subdir_path)
                                for f in files:
                                    full = os.path.join(root, f)
                                    if is_video(full):
                                        if not displayed_items or full in displayed_items:
                                            vids_to_exclude.add(full)
                        else:
                            vids_to_exclude.add(target_path)
                        selected_names.append(os.path.basename(target_path))
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror("Error", f"Error excluding items: {e}"))
                    self.root.after(0, lambda: [btn.config(state=tk.NORMAL) for btn in
                                                [getattr(self, 'exclude_button', None),
                                                 getattr(self, 'include_button', None),
                                                 getattr(self, 'exclude_all_button', None),
                                                 getattr(self, 'clear_exclusions_button', None)] if btn])
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

                    first_index = indices[0] if indices else None
                    first_path = self.current_subdirs_mapping.get(first_index) if first_index is not None else None
                    scroll_pos = self.exclusion_listbox.yview()

                    if is_filtered_mode and hasattr(self, '_filtered_videos'):
                        self._reapply_filtered_view(scroll_pos)
                    else:
                        self.load_subdirectories(dir_path, restore_path=first_path, restore_scroll=scroll_pos)

                    self.update_video_count()

                    if self.save_directories:
                        self.save_preferences()

                    for btn in [getattr(self, 'exclude_button', None), getattr(self, 'include_button', None),
                                getattr(self, 'exclude_all_button', None),
                                getattr(self, 'clear_exclusions_button', None)]:
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

            is_filtered_mode = hasattr(self, '_is_filtered_mode') and self._is_filtered_mode

            self.exclusion_listbox.insert(tk.END, "\nApplying includes... Please wait")
            for btn in [getattr(self, 'exclude_button', None), getattr(self, 'include_button', None),
                        getattr(self, 'exclude_all_button', None), getattr(self, 'clear_exclusions_button', None)]:
                if btn:
                    btn.config(state=tk.DISABLED)

            def worker(dir_path=selected_dir, indices=list(exclusion_selection)):
                dirs_to_include = set()
                vids_to_include = set()
                selected_names = []

                displayed_items = set()
                if hasattr(self, 'search_query') and self.search_query:
                    for idx in range(len(self.current_subdirs_mapping)):
                        if idx in self.current_subdirs_mapping:
                            displayed_items.add(self.current_subdirs_mapping[idx])

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
                                    subdir_path = os.path.join(root, d)
                                    if not displayed_items or subdir_path in displayed_items:
                                        dirs_to_include.add(subdir_path)
                                for f in files:
                                    full = os.path.join(root, f)
                                    if is_video(full):
                                        if not displayed_items or full in displayed_items:
                                            vids_to_include.add(full)
                        else:
                            vids_to_include.add(target_path)
                        selected_names.append(os.path.basename(target_path))
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror("Error", f"Error including items: {e}"))
                    self.root.after(0, lambda: [btn.config(state=tk.NORMAL) for btn in
                                                [getattr(self, 'exclude_button', None),
                                                 getattr(self, 'include_button', None),
                                                 getattr(self, 'exclude_all_button', None),
                                                 getattr(self, 'clear_exclusions_button', None)] if btn])
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

                    first_index = indices[0] if indices else None
                    first_path = self.current_subdirs_mapping.get(first_index) if first_index is not None else None
                    scroll_pos = self.exclusion_listbox.yview()

                    if is_filtered_mode and hasattr(self, '_filtered_videos'):
                        self._reapply_filtered_view(scroll_pos)
                    else:
                        self.load_subdirectories(dir_path, restore_path=first_path, restore_scroll=scroll_pos)

                    self.update_video_count()

                    if self.save_directories:
                        self.save_preferences()

                    for btn in [getattr(self, 'exclude_button', None), getattr(self, 'include_button', None),
                                getattr(self, 'exclude_all_button', None),
                                getattr(self, 'clear_exclusions_button', None)]:
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
                self.expanded_paths.clear()
                self.collapsed_paths.clear()
                self.load_subdirectories(selected_dir, max_depth=20)
            else:
                self.expanded_paths.clear()
                self.collapsed_paths.clear()
                self.load_subdirectories(selected_dir, max_depth=20)

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

            is_filtered_mode = hasattr(self, '_is_filtered_mode') and self._is_filtered_mode

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

                    scroll_pos = self.exclusion_listbox.yview()

                    if is_filtered_mode and hasattr(self, '_filtered_videos'):
                        self._reapply_filtered_view(scroll_pos)
                    else:
                        self.load_subdirectories(selected_dir)

                    self.update_video_count()

        def load_subdirectories(self, directory, max_depth=20, restore_path=None, restore_scroll=None):
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

                        norm_root = os.path.normpath(root)
                        norm_base = os.path.normpath(base)

                        if self.expand_all_var.get():
                            if norm_root in self.collapsed_paths:
                                dirs[:] = []
                            can_show_children = norm_root not in self.collapsed_paths
                        else:
                            is_expanded_here = (norm_root == norm_base) or (norm_root in self.expanded_paths)
                            if not is_expanded_here:
                                dirs[:] = []
                            can_show_children = is_expanded_here

                        dir_name_matches = (not getattr(self, 'search_query', None)) or (
                                self.search_query in os.path.basename(root).lower())
                        is_child_of_match = self.is_child_of_matching_parent(root, base,
                                                                             getattr(self, 'search_query', None))
                        dir_has_matching_children = self.matches_search(root,
                                                                        getattr(self, 'search_query', None)) if getattr(
                            self, 'search_query', None) else True
                        show_this_dir = (not getattr(self, 'search_query',
                                                     None)) or dir_name_matches or is_child_of_match or dir_has_matching_children

                        indent_level = 0 if rel == '.' else rel.count(base_sep) + 1
                        name = os.path.basename(root) if rel != '.' else os.path.basename(base)
                        include_dir = (not only_excluded) or (root in excluded_dir_set)

                        if include_dir and show_this_dir:
                            indented_name = ("  " * indent_level) + '📁' + name
                            if root in excluded_dir_set:
                                indented_name += "🚫[EXCLUDED]"
                            items.append((root, indented_name))

                        if show_videos and can_show_children:
                            try:
                                with os.scandir(root) as it:
                                    for entry in it:
                                        if entry.is_file() and is_video(entry.name):
                                            full_path = entry.path
                                            include_vid = (not only_excluded) or (full_path in excluded_vid_set)

                                            video_name_matches = (not getattr(self, 'search_query', None)) or (
                                                    self.search_query in entry.name.lower())
                                            show_this_video = video_name_matches or dir_name_matches or is_child_of_match

                                            if include_vid and show_this_video and show_this_dir:
                                                v_name = ("  " * (indent_level + 1)) + '▶' + entry.name
                                                if self.favorites_manager.is_favorite(full_path, base):
                                                    v_name += " ⭐"
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
                        target_index = None

                        if restore_path:
                            for idx, (path, _) in enumerate(items):
                                if os.path.normpath(path) == restore_path:
                                    target_index = idx
                                    break

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
                                self.video_preview_manager.attach_to_listbox(
                                    self.exclusion_listbox,
                                    self.current_subdirs_mapping
                                )
                                if target_index is not None:
                                    self.exclusion_listbox.selection_clear(0, tk.END)
                                    self.exclusion_listbox.selection_set(target_index)
                                    self.exclusion_listbox.activate(target_index)
                                    self.exclusion_listbox.see(target_index)

                                if restore_scroll:
                                    self.exclusion_listbox.yview_moveto(restore_scroll[0])

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

            self.filter_sort_button = self.create_button(
                theme_frame,
                text="Filter/Sort",
                command=self._show_filter_dialog,
                variant="primary",
                size="md"
            )
            self.filter_sort_button.pack(side=tk.LEFT, padx=(0, 10))

            self.theme_button = self.create_button(
                theme_frame,
                text="Dark Mode" if not self.dark_mode else "Light Mode",
                command=self.toggle_theme,
                variant="theme",
                size="md"
            )
            self.theme_button.pack(side=tk.LEFT, padx=(0, 10))

            self.settings_button = self.create_button(
                theme_frame,
                text="Settings",
                command=self._show_settings,
                variant="settings",
                size="md"
            )
            self.settings_button.pack(side=tk.LEFT, padx=(0, 10))

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

            self.loop_toggle_button = self.create_button(
                action_buttons_frame,
                text=self._get_loop_icon(),
                command=self.toggle_loop_mode,
                variant="danger",
                size="lg",
                font=(self.normal_font.name, self.normal_font.actual()['size'], 'bold')
            )
            self.loop_toggle_button.pack(side=tk.LEFT, padx=(0, 5))

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

        def _show_filter_dialog(self):
            self.filter_sort_ui.show_filter_dialog()

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

        def get_displayed_items(self):
            if not self.current_subdirs_mapping:
                return []

            displayed_items = []
            for idx in sorted(self.current_subdirs_mapping.keys()):
                path = self.current_subdirs_mapping.get(idx)
                if path:
                    displayed_items.append(path)

            return displayed_items

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

        def _show_grid_view(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showwarning("Warning", "Please select a directory first")
                return

            exclusion_selection = self.exclusion_listbox.curselection()

            if exclusion_selection:
                self.update_console("Loading grid view for selected items...")

                def collect_selected_videos():
                    selected_videos = []
                    selected_folders = []

                    for index in exclusion_selection:
                        item_path = self.current_subdirs_mapping.get(index)
                        if not item_path:
                            continue

                        if os.path.isfile(item_path) and is_video(item_path):
                            if not self.is_video_excluded(selected_dir, item_path):
                                selected_videos.append(item_path)
                        elif os.path.isdir(item_path):
                            selected_folders.append(item_path)

                    for folder in selected_folders:
                        try:
                            for root, dirs, files in os.walk(folder):
                                for f in files:
                                    full_path = os.path.join(root, f)
                                    if is_video(full_path):
                                        if not self.is_video_excluded(selected_dir, full_path):
                                            selected_videos.append(full_path)
                        except Exception as e:
                            self.update_console(f"Error reading folder {folder}: {e}")

                    seen = set()
                    final_videos = []
                    for v in selected_videos:
                        v_norm = os.path.normpath(v)
                        if v_norm not in seen:
                            seen.add(v_norm)
                            final_videos.append(v_norm)

                    if final_videos:
                        self.root.after(0, lambda: self._open_grid_view(final_videos))
                    else:
                        self.root.after(0, lambda: messagebox.showwarning("Warning", "No videos found in selection"))

                threading.Thread(target=collect_selected_videos, daemon=True).start()
            else:
                self.update_console("Loading grid view for entire directory...")

                def collect_all_videos():
                    cache = self.scan_cache.get(selected_dir)
                    if cache:
                        videos, _, _ = cache
                        filtered = [v for v in videos if not self.is_video_excluded(selected_dir, v)]
                        self.root.after(0, lambda: self._open_grid_view(filtered))
                    else:
                        self.root.after(0, lambda: messagebox.showwarning("Warning", "No videos found"))

                threading.Thread(target=collect_all_videos, daemon=True).start()

        def _open_grid_view(self, videos):
            if not videos:
                messagebox.showwarning("Warning", "No videos to display")
                return

            self.grid_view_manager.video_preview_manager = self.video_preview_manager
            self.grid_view_manager.show_grid_view(videos, self.video_preview_manager)

        def _play_grid_videos(self, videos):
            if not videos:
                return

            if self.controller:
                self.controller.stop()
                cleanup_hotkeys()

            all_video_to_dir = {v: os.path.dirname(v) for v in videos}
            all_directories = sorted(list(set(all_video_to_dir.values())))

            self.update_console(f"Playing {len(videos)} videos from grid selection")

            self.controller = VLCPlayerControllerForMultipleDirectory(
                videos, all_video_to_dir, all_directories, self.update_console
            )
            self.controller.set_loop_mode(self.loop_mode)
            self.controller.volume = self.volume
            self.controller.player.audio_set_volume(self.volume)
            self.controller.set_volume_save_callback(self._save_volume_callback)
            self.controller.set_watch_history_callback(self.watch_history_manager.track_video_playback)
            self.controller.set_resume_manager(self.resume_manager)
            self.controller.set_start_index(0)
            self.controller.set_video_change_callback(self.on_video_changed)

            if self.player_thread and self.player_thread.is_alive():
                self.controller.running = False
                self.player_thread.join(timeout=1.0)

            self.player_thread = threading.Thread(target=self.controller.run, daemon=True)
            self.player_thread.start()

            self.keys_thread = threading.Thread(target=lambda: listen_keys(self.controller), daemon=True)
            self.keys_thread.start()

        def _add_to_playlist(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showwarning("Warning", "Please select a directory first")
                return

            selection = self.exclusion_listbox.curselection()

            if selection:
                selected_videos = []
                for index in selection:
                    if index in self.current_subdirs_mapping:
                        item_path = self.current_subdirs_mapping[index]
                        if os.path.isfile(item_path) and is_video(item_path):
                            selected_videos.append(item_path)
                        elif os.path.isdir(item_path):
                            try:
                                for root, dirs, files in os.walk(item_path):
                                    for file in files:
                                        full_path = os.path.join(root, file)
                                        if is_video(full_path):
                                            selected_videos.append(full_path)
                            except Exception as e:
                                self.update_console(f"Error reading directory {item_path}: {e}")

                if selected_videos:
                    self.playlist_manager.add_videos_to_playlist([], selected_videos)
                    self.update_console(f"Added {len(selected_videos)} selected videos to playlist")
                else:
                    messagebox.showwarning("Warning", "No videos found in selected items")
            else:
                # self.add_to_playlist_button.config(text="Adding...", state=tk.DISABLED)
                search_active = hasattr(self, 'search_query') and self.search_query
                if search_active:
                    self.update_console("Collecting all search results for playlist...")
                else:
                    self.update_console("Collecting all videos for playlist...")

                def collect_all_videos():
                    try:
                        all_videos = []

                        if search_active and self.current_subdirs_mapping:
                            for i in range(len(self.current_subdirs_mapping)):
                                if i in self.current_subdirs_mapping:
                                    path = self.current_subdirs_mapping[i]
                                    if os.path.isfile(path) and is_video(path):
                                        all_videos.append(path)
                        else:
                            cache = self.scan_cache.get(selected_dir)
                            if cache:
                                videos, _, _ = cache
                                excluded_subdirs = self.excluded_subdirs.get(selected_dir, [])
                                excluded_videos = self.excluded_videos.get(selected_dir, [])

                                for video in videos:
                                    if not self.is_video_excluded(selected_dir, video):
                                        all_videos.append(video)

                        def finish_collection():
                            # self.add_to_playlist_button.config(text="Add to Playlist", state=tk.NORMAL)
                            if all_videos:
                                self.playlist_manager.add_videos_to_playlist([], all_videos)
                                self.update_console(f"Added all {len(all_videos)} videos to playlist")
                            else:
                                messagebox.showwarning("Warning", "No videos found to add to playlist")

                        self.root.after(0, finish_collection)

                    except Exception as e:
                        def show_error():
                            # self.add_to_playlist_button.config(text="Add to Playlist", state=tk.NORMAL)
                            messagebox.showerror("Error", f"Failed to collect videos: {e}")

                        self.root.after(0, show_error)

                threading.Thread(target=collect_all_videos, daemon=True).start()

        def _manage_playlists(self):
            """Open playlist manager window"""
            self.playlist_manager.show_manager()

        def _play_playlist_videos(self, videos):
            """Play videos from playlist"""
            if not videos:
                messagebox.showwarning("Warning", "Playlist is empty")
                return

            if self.controller:
                self.controller.stop()
                cleanup_hotkeys()

            self.update_console("=" * 100)
            self.update_console("STARTING PLAYLIST PLAYBACK")
            self.update_console("=" * 100)

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
                self.controller.set_loop_mode(self.loop_mode)
                self.controller.volume = self.volume
                self.controller.player.audio_set_volume(self.volume)
                self.controller.set_volume_save_callback(self._save_volume_callback)
                self.controller.set_watch_history_callback(
                    self.watch_history_manager.track_video_playback
                )
                self.controller.set_resume_manager(self.resume_manager)

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

        def _show_queue_manager(self):
            self.queue_manager.show_manager()

        def _context_add_to_queue(self, selection, mode="queue"):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                return

            selected_videos = []
            selected_folders = []

            for index in selection:
                item_path = self.current_subdirs_mapping.get(index)
                if not item_path:
                    continue

                if os.path.isfile(item_path) and is_video(item_path):
                    if not self.is_video_excluded(selected_dir, item_path):
                        selected_videos.append(item_path)
                elif os.path.isdir(item_path):
                    selected_folders.append(item_path)

            for folder in selected_folders:
                try:
                    for root, dirs, files in os.walk(folder):
                        for f in files:
                            full_path = os.path.join(root, f)
                            if is_video(full_path):
                                if not self.is_video_excluded(selected_dir, full_path):
                                    selected_videos.append(full_path)
                except Exception as e:
                    self.update_console(f"Error reading folder {folder}: {e}")

            seen = set()
            final_videos = []
            for v in selected_videos:
                v_norm = os.path.normpath(v)
                if v_norm not in seen:
                    seen.add(v_norm)
                    final_videos.append(v_norm)

            if final_videos:
                if mode == "next":
                    count = self.queue_manager.play_next(final_videos, added_from="selection")
                    self.update_console(f"Added {count} videos to play next in queue")
                else:
                    count = self.queue_manager.add_to_queue(final_videos, added_from="selection")
                    self.update_console(f"Added {count} videos to queue")
            else:
                messagebox.showwarning("Warning", "No valid videos found in selection")

        def _play_queue_videos(self, videos):
            if not videos:
                return

            if self.controller:
                self.controller.stop()
                cleanup_hotkeys()

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
                messagebox.showwarning("Warning", "No valid videos found")
                return

            def start_queue_player():
                self.update_console(f"Playing queue with {len(valid_videos)} videos")
                self.controller = VLCPlayerControllerForMultipleDirectory(
                    valid_videos, all_video_to_dir, all_directories, self.update_console
                )
                self.controller.set_loop_mode(self.loop_mode)
                self.controller.volume = self.volume
                self.controller.player.audio_set_volume(self.volume)
                self.controller.set_volume_save_callback(self._save_volume_callback)
                self.controller.set_watch_history_callback(
                    self.watch_history_manager.track_video_playback
                )
                self.controller.set_resume_manager(self.resume_manager)

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

            threading.Thread(target=start_queue_player, daemon=True).start()

        def _show_watch_history(self):
            self.watch_history_manager.show_manager()

        def _play_history_videos(self, videos):
            if not videos:
                messagebox.showwarning("Warning", "No videos to play")
                return

            if self.controller:
                self.controller.stop()
                cleanup_hotkeys()

            self.update_console("=" * 100)
            self.update_console("STARTING HISTORY VIDEO PLAYBACK")
            self.update_console("=" * 100)

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
                messagebox.showwarning("Warning", "No valid videos found")
                return

            def start_history_player():
                self.update_console(f"Playing {len(valid_videos)} videos from history")
                self.controller = VLCPlayerControllerForMultipleDirectory(
                    valid_videos, all_video_to_dir, all_directories, self.update_console
                )
                self.controller.set_loop_mode(self.loop_mode)
                self.controller.volume = self.volume
                self.controller.player.audio_set_volume(self.volume)
                self.controller.set_volume_save_callback(self._save_volume_callback)
                self.controller.set_watch_history_callback(
                    self.watch_history_manager.track_video_playback
                )
                self.controller.set_resume_manager(self.resume_manager)

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

            threading.Thread(target=start_history_player, daemon=True).start()

        def toggle_smart_resume(self):
            enabled = bool(self.smart_resume_var.get())
            self.resume_manager.set_resume_enabled(enabled)
            self.start_from_last_played = enabled
            self.smart_resume_enabled = enabled
            self.save_preferences()

        def _show_settings(self):
            self.settings_manager.show_settings()

        def _save_volume_callback(self, volume):
            self.volume = volume
            self.save_preferences()

        def _on_settings_changed(self, new_settings):
            self.ai_index_path = new_settings.ai_index_path
            self.update_console(f"Settings updated")

            if hasattr(self, 'video_preview_manager'):
                self.video_preview_manager.set_preview_duration(new_settings.preview_duration)
                self.video_preview_manager.set_video_preview_enabled(new_settings.use_video_preview)

            if hasattr(self, 'resume_manager'):
                self.resume_manager._auto_cleanup_days = new_settings.auto_cleanup_days


        def _clear_thumbnail_cache(self):
            try:
                self.video_preview_manager.clear_cache()
                self.update_console(f"Thumbnail cache cleared.")
                return True
            except Exception as e:
                self.update_console(f"Error clearing thumbnail cache: {e}")
                return False

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
            try:
                self.video_preview_manager.tooltip.hide_preview()
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
