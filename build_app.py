try:
    from version import __version__, __commit__, __build__
except ImportError:
    __version__ = __commit__ = __build__ = "dev"

import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from tkinter.font import Font
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from key_press import listen_keys, cleanup_hotkeys, reload_hotkeys
from managers.favorites_manager import FavoritesManager
from managers.filter_sort_manager import AdvancedFilterSortManager
from managers.filter_sort_ui import FilterSortUI
from managers.grid_view_manager import GridViewManager
from managers.resource_manager import ThreadSafeDict, get_resource_manager, ManagedExecutor, MemoryMonitor, \
    ManagedThread
from theme import ThemeSelector
from utils import gather_videos_with_directories, is_video, gather_videos
from vlc_player_controller import VLCPlayerControllerForMultipleDirectory
from managers.playlist_manager import PlaylistManager
from managers.watch_history_manager import WatchHistoryManager
from managers.resume_playback_manager import ResumePlaybackManager
from managers.settings_manager import SettingsManager
from managers.video_preview_manager import VideoPreviewManager
from managers.video_queue_manager import VideoQueueManager
from managers.google_drive_manager import GoogleDriveManager
from managers.dual_player_manager import DualPlayerManager
import struct
import socket
import time
from tkinterdnd2 import DND_FILES, TkinterDnD

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
                        try:
                            import win32gui
                            import win32con
                            hwnd = win32gui.FindWindow(None, "Recursive Video Player")
                            if hwnd:
                                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                                win32gui.SetForegroundWindow(hwnd)
                                time.sleep(0.5)
                        except:
                            pass

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
            self._sleep_timer_job = None
            self._sleep_countdown_job = None
            self._sleep_timer_end = None
            self._active_player = None

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
            self.is_muted = preferences.get('is_muted', False)
            self.loop_mode = preferences.get('loop_mode', 'loop_on')
            self.show_console = preferences.get('show_console', True)

            self.setup_theme()

            root.title("Recursive Video Player")
            root.geometry("1600x900")
            try:
                root.state('zoomed')
            except:
                pass
            root.protocol("WM_DELETE_WINDOW", self.cancel)
            root.configure(bg=self.bg_color)

            try:
                self.drive_manager = GoogleDriveManager()
            except Exception as e:
                self.drive_manager = None
                self.update_console(f"Google Drive integration unavailable: {e}")

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

            self.scan_cache = ThreadSafeDict()
            self.pending_scans = set()
            self._pending_scans_lock = threading.RLock()
            max_workers = min(8, (os.cpu_count() or 4))
            self.executor = ManagedExecutor(ThreadPoolExecutor, max_workers=max_workers)
            self.resource_manager = get_resource_manager()
            self.resource_manager.register_cleanup_callback(self._cleanup_scan_cache)
            self.resource_manager.register_cleanup_callback(self._cleanup_player_threads)
            self.apply_theme()
            # Deferred: re-lock pill colors after tkinter's first render pass
            self.root.after(0, self._fix_pill_colors_initial)
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self._on_drop_files)
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

            self.settings_manager = SettingsManager(self.root, self, self.update_console, enable_ai=False)
            self.settings_manager.add_settings_changed_callback(self._on_settings_changed)
            self.settings_manager.set_hotkey_reload_callback(
                lambda hk: reload_hotkeys(self.controller, hk)
            )
            app_settings = self.settings_manager.get_settings()

            self.video_preview_manager = VideoPreviewManager(self.root, self.update_console)
            self.video_preview_manager.set_preview_duration(app_settings.preview_duration)
            self.video_preview_manager.set_video_preview_enabled(app_settings.use_video_preview)

            self.grid_view_manager = GridViewManager(self.root, self, self.update_console)
            self.grid_view_manager.set_play_callback(self._play_grid_videos)

            self.playlist_manager = PlaylistManager(self.root, self)
            self.playlist_manager.set_play_callback(self._play_playlist_videos)
            self.playlist_manager.set_log_callback(self.update_console)
            self.playlist_manager.set_video_preview_manager(self.video_preview_manager)
            self.playlist_manager.set_grid_view_manager(self.grid_view_manager)
            self.playlist_manager.ui.video_preview_manager = self.video_preview_manager

            self.watch_history_manager = WatchHistoryManager(self.root, self)
            self.watch_history_manager.set_settings_manager(self.settings_manager)
            self.watch_history_manager.set_play_callback(self._play_history_videos)
            self.watch_history_manager.set_video_preview_manager(self.video_preview_manager)

            self.resume_manager = ResumePlaybackManager()
            self.resume_manager.set_resume_enabled(self.smart_resume_enabled)

            self.queue_manager = VideoQueueManager(self.root, self)
            self.queue_manager.set_play_callback(self._play_queue_videos)
            self.queue_manager.set_video_preview_manager(self.video_preview_manager)
            self.queue_manager.set_grid_view_manager(self.grid_view_manager)

            self.favorites_manager = FavoritesManager(self.root, self)
            self.favorites_manager.set_play_callback(self._play_favorites_videos)
            self.favorites_manager.set_video_preview_manager(self.video_preview_manager)
            self.favorites_manager.set_grid_view_manager(self.grid_view_manager)
            self.favorites_manager.set_on_removed_callback(self._refresh_tree_after_fav_change)

            self.dual_player_manager = DualPlayerManager(
                self.root,
                self,
                self.update_console,
                watch_history_callback=self.watch_history_manager.track_video_playback,
                player_count=3
            )

            self.filter_sort_manager = AdvancedFilterSortManager(
                watch_history_manager=self.watch_history_manager
            )

            self.filter_sort_ui = FilterSortUI(
                self.root,
                self,
                self.filter_sort_manager,
                self._apply_filters_and_refresh
            )
            self.filter_sort_ui.app_instance = self

            self.grid_view_manager.set_add_to_playlist_callback(
                lambda videos: self.playlist_manager.add_videos_to_playlist([], videos)
            )
            self.grid_view_manager.set_add_to_favourites_callback(
                lambda videos: self.favorites_manager.add_to_favorites(videos, self.get_current_selected_directory())
            )
            self.grid_view_manager.set_remove_from_favourites_callback(
                lambda videos: self.favorites_manager.remove_from_favorites(videos,
                                                                            self.get_current_selected_directory())
            )
            self.grid_view_manager.set_is_favourite_callback(
                lambda video_path: self.favorites_manager.is_favorite(video_path, self.get_current_selected_directory())
            )
            self.grid_view_manager.set_add_to_queue_callback(
                lambda videos: self.queue_manager.add_to_queue(videos, added_from="grid_view")
            )
            self.grid_view_manager.set_play_in_dual_player1_callback(
                lambda videos: self.dual_player_manager.load_videos_into_slot(1, 1, videos)
            )
            self.grid_view_manager.set_play_in_dual_player2_callback(
                lambda videos: self.dual_player_manager.load_videos_into_slot(1, 2, videos)
            )
            self.grid_view_manager.set_play_in_dual_player3_callback(
                lambda videos: self.dual_player_manager.load_videos_into_slot(1, 3, videos)
            )

            # Player count per window is always 3 (dynamic/fixed).
            # Win 2 availability is controlled via dual_window_enabled setting.
            self.grid_view_manager.set_get_player_count_callback(lambda: 3)

            if self.settings_manager.get_settings().dual_window_enabled:
                self.grid_view_manager.set_play_in_dual_player_win2_1_callback(
                    lambda videos: self.dual_player_manager.load_videos_into_slot(2, 1, videos)
                )
                self.grid_view_manager.set_play_in_dual_player_win2_2_callback(
                    lambda videos: self.dual_player_manager.load_videos_into_slot(2, 2, videos)
                )
                self.grid_view_manager.set_play_in_dual_player_win2_3_callback(
                    lambda videos: self.dual_player_manager.load_videos_into_slot(2, 3, videos)
                )

            self.grid_view_manager.set_open_file_location_callback(self._context_open_location)
            self.grid_view_manager.set_show_properties_callback(self._context_show_properties)

            self.settings_manager.ui.cleanup_resume_callback = lambda: self.resume_manager.service.cleanup_old_positions(
                self.settings_manager.get_settings().auto_cleanup_days)
            self.settings_manager.ui.cleanup_history_callback = lambda: self.watch_history_manager.service.cleanup_old_entries(
                self.settings_manager.get_settings().auto_cleanup_days)
            self.settings_manager.ui.clear_thumbnails_callback = lambda: self._clear_thumbnail_cache()
            self.settings_manager.ui.video_preview_manager = self.video_preview_manager
            self.settings_manager.ui.clear_metadata_callback = lambda: self._clear_metadata_cache()
            self.settings_manager.ui.get_metadata_info_callback = lambda: self._get_metadata_cache_info()
            self.settings_manager.ui.filter_sort_manager = self.filter_sort_manager
            self._setup_periodic_cleanup()
            self.resource_manager.register_cleanup_callback(self._cleanup_managers)

        def _refresh_tree_after_fav_change(self):
            selected_dir = self.get_current_selected_directory()
            if selected_dir:
                scroll_pos = self.exclusion_listbox.yview()
                self.load_subdirectories(selected_dir, max_depth=self.current_max_depth, restore_scroll=scroll_pos)

        def _setup_periodic_cleanup(self):
            self.memory_monitor = MemoryMonitor(threshold_mb=1200)

            def periodic_cleanup():
                if hasattr(self, 'root') and self.root.winfo_exists():
                    self.memory_monitor.cleanup_if_needed()
                    self.root.after(300000, periodic_cleanup)

            self.root.after(300000, periodic_cleanup)

        def _cleanup_managers(self):
            managers = [
                'video_preview_manager',
                'grid_view_manager',
                'playlist_manager',
                'watch_history_manager',
                'queue_manager',
                'favorites_manager',
                'filter_sort_manager',
                'settings_manager',
                'resume_manager',
                'dual_player_manager',
            ]

            for manager_name in managers:
                if hasattr(self, manager_name):
                    manager = getattr(self, manager_name)
                    if hasattr(manager, 'cleanup'):
                        try:
                            manager.cleanup()
                        except Exception as e:
                            print(f"Error cleaning up {manager_name}: {e}")

        def __del__(self):
            try:
                if hasattr(self, 'resource_manager'):
                    self.resource_manager.cleanup_all()
            except:
                pass

        def _cleanup_scan_cache(self):
            try:
                if hasattr(self, 'scan_cache'):
                    self.scan_cache.clear()
                if hasattr(self, 'pending_scans'):
                    self.pending_scans.clear()
            except Exception as e:
                print(f"Error cleaning scan cache: {e}")

        def _cleanup_player_threads(self):
            try:
                if hasattr(self, 'controller') and self.controller:
                    self.controller.running = False

                if hasattr(self, 'player_thread') and self.player_thread:
                    try:
                        if self.player_thread.is_alive():
                            self.player_thread.join(timeout=2.0)
                    except Exception:
                        pass

                if hasattr(self, 'keys_thread') and self.keys_thread:
                    try:
                        if self.keys_thread.is_alive():
                            self.keys_thread.join(timeout=1.0)
                    except Exception:
                        pass
            except Exception as e:
                print(f"Error cleaning player threads: {e}")

        def _clear_metadata_cache(self):
            try:
                count = self.filter_sort_manager.metadata_cache.clear_cache()
                self.update_console(f"Cleared {count} video metadata cache entries")
                return count
            except Exception as e:
                self.update_console(f"Error clearing metadata cache: {e}")
                return 0

        def _get_metadata_cache_info(self):
            try:
                return self.filter_sort_manager.metadata_cache.get_cache_info()
            except Exception as e:
                self.update_console(f"Error getting metadata cache info: {e}")
                return {
                    'total_entries': 0,
                    'cache_size_bytes': 0,
                    'cache_size_mb': 0,
                    'cache_file': ''
                }

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

        def _on_drop_files(self, event):
            import re
            raw = event.data.strip()
            # handles: {path with spaces} path_without_spaces {another path}
            paths = []
            i = 0
            while i < len(raw):
                if raw[i] == '{':
                    end = raw.find('}', i)
                    if end == -1:
                        break
                    paths.append(raw[i + 1:end])
                    i = end + 1
                elif raw[i] == ' ':
                    i += 1
                else:
                    end = raw.find(' ', i)
                    if end == -1:
                        paths.append(raw[i:])
                        break
                    paths.append(raw[i:end])
                    i = end + 1

            added = 0
            played = []
            for path in paths:
                path = path.strip()
                if not path:
                    continue
                if os.path.isdir(path):
                    self._add_directory_from_ipc(path)
                    added += 1
                elif os.path.isfile(path) and is_video(path):
                    played.append(path)

            if played:
                self._play_grid_videos(played)
            if added:
                self.update_console(f"Dropped {added} director{'ies' if added > 1 else 'y'}")

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
                "danger": {"bg": "#e74c3c", "fg": "white", "active": "#c0392b"},
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
            self.console_section = tk.Frame(self.main_frame, bg=self.bg_color)
            if self.show_console:
                self.console_section.pack(fill=tk.X, pady=(0, 15))
            console_section = self.console_section

            console_header_frame = tk.Frame(console_section, bg=self.bg_color)
            console_header_frame.pack(fill=tk.X, pady=(0, 10))

            console_header = tk.Label(console_header_frame, text="Player Console",
                                      font=self.header_font, bg=self.bg_color, fg=self.text_color)
            console_header.pack(side=tk.LEFT, anchor='w')

            self.clear_console_button = self.create_button(
                console_header_frame,
                text="Clear",
                command=self.clear_console,
                variant="dark",
                size="sm"
            )
            self.clear_console_button.pack(side=tk.LEFT, padx=(10, 0), anchor='w')

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
                height=10,
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

            self.update_console("Video Player Console Ready")
            self.update_console(f"version:{__version__}  commit:{__commit__}  built:{__build__}")
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

        def toggle_console(self):
            self.show_console = not self.show_console
            if self.show_console:
                self.console_section.pack(fill=tk.X, pady=(0, 15), before=self.button_frame)
            else:
                self.console_section.pack_forget()
            self.save_preferences()

        def _submit_scan(self, directory):
            cache_result = self.scan_cache.get(directory)
            if cache_result is not None:
                return

            with self._pending_scans_lock:
                if directory in self.pending_scans:
                    return
                self.pending_scans.add(directory)

            future = self.executor.submit(gather_videos_with_directories, directory)

            def on_done(fut, dir_path=directory):
                try:
                    res = fut.result()
                    self.scan_cache.set(dir_path, res)
                    videos, _, directories = res
                    self.update_console(
                        f"Found {len(videos)} videos in '{os.path.basename(dir_path)}' ({len(directories)} subdirs)")

                    # Kick off background thumbnail prefetch so Grid View
                    # opens instantly instead of generating on demand.
                    # Delayed 500 ms so the UI finishes updating first.
                    if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
                        self.root.after(
                            500,
                            lambda vids=list(videos), d=dir_path: (
                                self.video_preview_manager.prefetch_for_directory(d, vids)
                                if hasattr(self, 'video_preview_manager') and self.video_preview_manager
                                else None
                            )
                        )
                except Exception as e:
                    self.update_console(f"Error scanning {dir_path}: {e}")
                finally:
                    with self._pending_scans_lock:
                        self.pending_scans.discard(dir_path)
                    try:
                        self.root.after(0, self.update_video_count)
                    except:
                        pass

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
                selectmode=tk.EXTENDED,
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
            self.dir_listbox.bind('<Button-1>', self._on_main_dir_left_click)
            self.dir_listbox.bind('<Button-3>', self._show_main_dir_context_menu)
            self.dir_listbox.bind('<Control-a>', self._select_all_main_dirs)
            self.dir_listbox.bind('<Control-A>', self._select_all_main_dirs)
            self.dir_listbox.bind('<B1-Motion>', self._on_drag)
            self.dir_listbox.bind('<ButtonRelease-1>', self._on_drop)
            self.scrollbar.config(command=self.dir_listbox.yview)

            # media_section = tk.Frame(self.dir_section, bg=self.bg_color)
            # media_section.pack(fill=tk.X, pady=(10, 0))
            #
            # media_label = tk.Label(
            #     media_section,
            #     text="Media:",
            #     font=self.small_font,
            #     bg=self.bg_color,
            #     fg="#666666"
            # )
            # media_label.pack(side=tk.LEFT, padx=(0, 8))
            #
            # self.manage_playlist_button = self.create_button(
            #     media_section, "Manage Playlists",
            #     self._manage_playlists, "playlist", "sm"
            # )
            # self.manage_playlist_button.pack(side=tk.LEFT, padx=(0, 5))
            #
            # self.queue_manager_button = self.create_button(
            #     media_section, "Manage Queue",
            #     self._show_queue_manager, "primary", "sm"
            # )
            # self.queue_manager_button.pack(side=tk.LEFT, padx=(0, 5))
            #
            # self.favorites_button = self.create_button(
            #     media_section, "Favorites",
            #     self._show_favorites_manager, "warning", "sm"
            # )
            # self.favorites_button.pack(side=tk.LEFT, padx=(0, 5))
            #
            # self.watch_history_button = self.create_button(
            #     media_section, "Watch History",
            #     self._show_watch_history, "history", "sm"
            # )
            # self.watch_history_button.pack(side=tk.LEFT)

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

            exclusion_header_frame = tk.Frame(self.exclusion_section, bg=self.bg_color)
            exclusion_header_frame.pack(fill=tk.X, pady=(0, 10))

            exclusion_header = tk.Label(exclusion_header_frame, text="Subdirectories and Videos",
                                        font=self.header_font, bg=self.bg_color, fg=self.text_color)
            exclusion_header.pack(side=tk.LEFT, anchor='w')

            self.video_count_label = tk.Label(
                exclusion_header_frame,
                text="  —  0 videos",
                font=self.normal_font,
                bg=self.bg_color,
                fg="#888888"
            )
            self.video_count_label.pack(side=tk.LEFT, anchor='w')

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
            self._selection_anchor = None
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
            self.smart_resume_check.pack(side=tk.LEFT, padx=(0, 0))

            self.speed_var = tk.DoubleVar(value=1.0)


        def _create_context_menu(self):
            pass

        def _select_all_main_dirs(self, event=None):
            self.dir_listbox.selection_set(0, tk.END)
            self.on_directory_select(None)
            return "break"

        def _on_main_dir_left_click(self, event):
            index = self.dir_listbox.nearest(event.y)
            if index < 0 or index >= self.dir_listbox.size():
                return

            self._drag_start_index = index
            ctrl_held = bool(event.state & 0x4)
            shift_held = bool(event.state & 0x1)
            current_selection = list(self.dir_listbox.curselection())

            if not ctrl_held and not shift_held:
                if current_selection == [index]:
                    self.dir_listbox.selection_clear(0, tk.END)
                    self.current_selected_dir_index = None
                    self.clear_exclusion_list()
                    self._is_filtered_mode = False
                    return "break"

            if shift_held:
                if not hasattr(self, '_main_dir_anchor') or self._main_dir_anchor is None:
                    self._main_dir_anchor = current_selection[0] if current_selection else 0
                self.dir_listbox.selection_clear(0, tk.END)
                start = min(self._main_dir_anchor, index)
                end = max(self._main_dir_anchor, index)
                for i in range(start, end + 1):
                    self.dir_listbox.selection_set(i)
                self.dir_listbox.activate(index)
                self.on_directory_select(None)
                return "break"
            elif ctrl_held:
                if index in current_selection:
                    self.dir_listbox.selection_clear(index)
                else:
                    self.dir_listbox.selection_set(index)
                self._main_dir_anchor = index
                self.dir_listbox.activate(index)
                self.on_directory_select(None)
                return "break"
            else:
                if current_selection == [index]:
                    self.dir_listbox.selection_clear(0, tk.END)
                    self.current_selected_dir_index = None
                    self._is_filtered_mode = False
                    self.clear_exclusion_list()
                    return "break"

                self.dir_listbox.selection_clear(0, tk.END)
                self.dir_listbox.selection_set(index)
                self.dir_listbox.activate(index)
                self._main_dir_anchor = index
                self.on_directory_select(None)
                return "break"

        def _on_drag(self, event):
            pass

        def _on_drop(self, event):
            if not hasattr(self, '_drag_start_index') or self._drag_start_index is None:
                return

            drop_index = self.dir_listbox.nearest(event.y)
            if drop_index < 0:
                drop_index = 0
            if drop_index >= self.dir_listbox.size():
                drop_index = self.dir_listbox.size() - 1

            if drop_index != self._drag_start_index:
                # Reorder selected_dirs
                dir_to_move = self.selected_dirs.pop(self._drag_start_index)
                self.selected_dirs.insert(drop_index, dir_to_move)

                # Reorder listbox items
                text = self.dir_listbox.get(self._drag_start_index)
                self.dir_listbox.delete(self._drag_start_index)
                self.dir_listbox.insert(drop_index, text)

                # Keep the moved item selected
                self.dir_listbox.selection_clear(0, tk.END)
                self.dir_listbox.selection_set(drop_index)
                self.dir_listbox.activate(drop_index)
                self.current_selected_dir_index = drop_index

                # Trigger directory select to update other UI parts
                self.on_directory_select(None)

            self._drag_start_index = None

        def _show_main_dir_context_menu(self, event):
            index = self.dir_listbox.nearest(event.y)
            selection = self.dir_listbox.curselection()

            if index >= 0 and index not in selection:
                self.dir_listbox.selection_clear(0, tk.END)
                self.dir_listbox.selection_set(index)
                self.dir_listbox.activate(index)
                self._main_dir_anchor = index
                self.on_directory_select(None)
                selection = self.dir_listbox.curselection()

            if not selection:
                return

            context_menu = tk.Menu(self.root, tearoff=0)
            context_menu.add_command(label="Play Selected", command=self._play_selected_main_dirs)
            context_menu.add_command(label="Open in Grid View", command=self._open_grid_view_main_dirs)
            context_menu.add_separator()
            context_menu.add_command(label="Remove Selected", command=self.remove_directory)

            context_menu.post(event.x_root, event.y_root)

        def _play_selected_main_dirs(self):
            selection = self.dir_listbox.curselection()
            if not selection:
                return

            all_videos = []
            all_video_to_dir = {}
            for i in selection:
                if i < len(self.selected_dirs):
                    root_dir = self.selected_dirs[i]
                    cache = self.scan_cache.get(root_dir)
                    if cache:
                        videos, video_to_dir, _ = cache
                    else:
                        from utils import gather_videos_with_directories
                        videos, video_to_dir, _ = gather_videos_with_directories(root_dir)
                    filtered_videos = [
                        v for v in videos
                        if not self.is_video_excluded(root_dir, v)
                    ]
                    all_videos.extend(filtered_videos)
                    all_video_to_dir.update({v: video_to_dir.get(v, os.path.dirname(v)) for v in filtered_videos})

            if not all_videos:
                messagebox.showinfo("Information", "No videos found in selected directories.")
                return

            from embedded_player import EmbeddedPlayer
            all_directories = sorted(list(dict.fromkeys(all_video_to_dir[v] for v in all_videos)))

            # Start from the first selected main directory
            idx = 0
            try:
                if selection and selection[0] < len(self.selected_dirs):
                    target_dir = os.path.normpath(self.selected_dirs[selection[0]])
                    for i, v in enumerate(all_videos):
                        if os.path.normpath(all_video_to_dir.get(v, "")).startswith(target_dir):
                            idx = i
                            break
            except Exception:
                pass

            player = EmbeddedPlayer(
                parent=self.root,
                videos=all_videos,
                video_to_dir=all_video_to_dir,
                directories=all_directories,
                start_index=idx,
                volume=getattr(self, 'volume', 50),
                is_muted=getattr(self, 'is_muted', False),
                loop_mode=getattr(self, 'loop_mode', 'loop_on'),
                logger=self.update_console,
                on_close=self._on_player_closed,
                on_volume_change=self._save_volume_callback,
            )
            player.on_loop_change = self._save_loop_callback
            player.on_close_save  = self._on_player_close_save
            player.on_video_changed = self.on_video_changed
            player.on_add_to_playlist = lambda vids: self.playlist_manager.add_videos_to_playlist([], vids)
            player.on_add_to_queue = lambda vids: self.queue_manager.add_to_queue(vids, added_from="player")
            player.on_add_to_favourites = lambda vids: self.favorites_manager.add_to_favorites(vids, self.get_current_selected_directory() or os.path.dirname(vids[0]))
            player.set_hotkeys(self.settings_manager.get_settings().hotkeys)

            player.play()
            self._active_player = player

        def _open_grid_view_main_dirs(self):
            selection = self.dir_listbox.curselection()
            if not selection:
                return

            all_videos = []
            for i in selection:
                if i < len(self.selected_dirs):
                    root_dir = self.selected_dirs[i]
                    cache = self.scan_cache.get(root_dir)
                    if cache:
                        videos, _, _ = cache
                        filtered_videos = [
                            v for v in videos
                            if not self.is_video_excluded(root_dir, v)
                        ]
                    else:
                        videos = gather_videos(root_dir)
                        filtered_videos = [
                            v for v in videos
                            if not self.is_video_excluded(root_dir, v)
                        ]
                    all_videos.extend(filtered_videos)

            if not all_videos:
                messagebox.showinfo("Information", "No videos found in selected directories.")
                return

            self._open_grid_view(all_videos)

        def _on_left_click(self, event):
            index = self.exclusion_listbox.nearest(event.y)

            if index < 0 or index >= self.exclusion_listbox.size():
                return

            ctrl_held = bool(event.state & 0x4)
            shift_held = bool(event.state & 0x1)
            current_selection = list(self.exclusion_listbox.curselection())

            if shift_held:
                if self._selection_anchor is None:
                    self._selection_anchor = current_selection[0] if current_selection else 0

                self.exclusion_listbox.selection_clear(0, tk.END)

                start = min(self._selection_anchor, index)
                end = max(self._selection_anchor, index)

                for i in range(start, end + 1):
                    self.exclusion_listbox.selection_set(i)

                self.exclusion_listbox.activate(index)
                return "break"

            elif ctrl_held:
                if index in current_selection:
                    self.exclusion_listbox.selection_clear(index)
                    if index == self._selection_anchor:
                        remaining = self.exclusion_listbox.curselection()
                        self._selection_anchor = remaining[-1] if remaining else None
                else:
                    self.exclusion_listbox.selection_set(index)
                    self._selection_anchor = index

                self.exclusion_listbox.activate(index)
                return "break"

            else:
                self.exclusion_listbox.selection_clear(0, tk.END)
                self.exclusion_listbox.selection_set(index)
                self.exclusion_listbox.activate(index)

                self._selection_anchor = index
                return "break"

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

            if index >= 0 and index < listbox.size() and index not in selection:
                video_path = self.current_subdirs_mapping.get(index)
                if video_path and os.path.isfile(video_path) and is_video(video_path):
                    self.video_preview_manager.right_clicked_item = index
                    self.video_preview_manager._show_video_preview(video_path, event.x_root, event.y_root)
                    return
                return

            context_menu = tk.Menu(self.root, tearoff=0)

            first_index = selection[0]
            first_path = self.current_subdirs_mapping.get(first_index)

            context_menu.add_command(
                label="Play Selected",
                command=self.play_selected_videos
            )
            context_menu.add_separator()

            total_items = listbox.size()
            selected_count = len(selection)

            if selected_count < total_items:
                context_menu.add_command(
                    label="Select All",
                    command=lambda: self._select_all_items(listbox)
                )

            if selected_count > 0:
                context_menu.add_command(
                    label="Unselect All",
                    command=lambda: listbox.selection_clear(0, tk.END)
                )

            context_menu.add_separator()
            context_menu.add_command(
                label="Open in Grid View",
                command=lambda: self._context_open_grid_view(selection)
            )

            context_menu.add_separator()
            context_menu.add_command(
                label="Exclude Selected",
                command=self.exclude_subdirectories
            )
            context_menu.add_command(
                label="Include Selected",
                command=self.include_subdirectories
            )
            context_menu.add_command(
                label="Exclude All",
                command=self.exclude_all_subdirectories
            )
            context_menu.add_command(
                label="Clear All Exclusions",
                command=self.clear_all_exclusions
            )

            context_menu.add_separator()
            context_menu.add_command(
                label="Add to Playlist",
                command=lambda: self._context_add_to_playlist(selection)
            )

            context_menu.add_command(
                label="⭐ Add to Favorites",
                command=lambda: self._context_add_to_favorites(selection)
            )

            context_menu.add_command(
                label="★ Remove from Favorites",
                command=lambda: self._context_remove_from_favorites(selection)
            )

            context_menu.add_separator()
            context_menu.add_command(
                label="Add to Queue",
                command=lambda: self._context_add_to_queue(selection, mode="queue")
            )
            context_menu.add_command(
                label="Play Next",
                command=lambda: self._context_add_to_queue(selection, mode="next")
            )

            context_menu.add_separator()
            # ── Window 1 — always available, always 3 players ─────────────
            context_menu.add_command(
                label="▶ Win 1 › Player 1",
                command=lambda: self._context_play_in_dual_player(selection, win_id=1, slot=1)
            )
            context_menu.add_command(
                label="▶ Win 1 › Player 2",
                command=lambda: self._context_play_in_dual_player(selection, win_id=1, slot=2)
            )
            context_menu.add_command(
                label="▶ Win 1 › Player 3",
                command=lambda: self._context_play_in_dual_player(selection, win_id=1, slot=3)
            )
            # ── Window 2 — only shown when enabled in Settings ────────────
            if (getattr(self, 'settings_manager', None) and
                    self.settings_manager.get_settings().dual_window_enabled):
                context_menu.add_separator()
                context_menu.add_command(
                    label="▶ Win 2 › Player 1",
                    command=lambda: self._context_play_in_dual_player(selection, win_id=2, slot=1)
                )
                context_menu.add_command(
                    label="▶ Win 2 › Player 2",
                    command=lambda: self._context_play_in_dual_player(selection, win_id=2, slot=2)
                )
                context_menu.add_command(
                    label="▶ Win 2 › Player 3",
                    command=lambda: self._context_play_in_dual_player(selection, win_id=2, slot=3)
                )

            context_menu.add_separator()

            context_menu.add_command(
                label=f"Copy ({len(selection)} item{'s' if len(selection) > 1 else ''})",
                command=lambda: self._context_copy_selected(selection)
            )

            if len(selection) == 1 and first_path and os.path.isfile(first_path):
                context_menu.add_command(
                    label="Copy Path",
                    command=lambda: self._context_copy_path(first_path)
                )
                context_menu.add_command(
                    label="Open File Location",
                    command=lambda: self._context_open_location(first_path)
                )
                context_menu.add_command(
                    label="Properties",
                    command=lambda: self._context_show_properties(first_path)
                )

            try:
                context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                context_menu.grab_release()
                try:
                    self.root.after(100, lambda: context_menu.destroy())
                except:
                    pass

        def _context_play_in_dual_player(self, selection, win_id: int, slot: int):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                return

            final_videos = self._resolve_selection_indices_to_videos(selected_dir, selection)
            if not final_videos:
                messagebox.showwarning("No Videos", "No valid non-excluded videos found in selection.")
                return

            self.dual_player_manager.load_videos_into_slot(win_id, slot, final_videos)
            self.update_console(f"Sent {len(final_videos)} video(s) to Window {win_id} · Player {slot}")

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
                    if not self.is_video_excluded(selected_dir, item_path):
                        selected_videos.append(item_path)
                elif item_path and os.path.isdir(item_path):
                    for root, dirs, files in os.walk(item_path):
                        for file in files:
                            full_path = os.path.join(root, file)
                            if is_video(full_path):
                                if not self.is_video_excluded(selected_dir, full_path):
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
                elif item_path and os.path.isdir(item_path):
                    for root, dirs, files in os.walk(item_path):
                        for file in files:
                            full_path = os.path.join(root, file)
                            if is_video(full_path):
                                selected_videos.append(full_path)

            if selected_videos:
                count = self.favorites_manager.remove_from_favorites(selected_videos, selected_dir)
                self.update_console(f"Removed {count} video(s) from favorites")

                scroll_pos = self.exclusion_listbox.yview()
                self.load_subdirectories(selected_dir, max_depth=self.current_max_depth, restore_scroll=scroll_pos)

        def _play_favorites_videos(self, videos):
            if not videos:
                return

            if self._active_player is not None:
                try:
                    self._active_player._close()
                except Exception:
                    pass
                self._active_player = None

            all_video_to_dir = {v: os.path.dirname(v) for v in videos}
            all_directories = sorted(list(set(all_video_to_dir.values())))

            self.update_console(f"Playing {len(videos)} videos from favorites")

            from embedded_player import EmbeddedPlayer
            player = EmbeddedPlayer(
                parent=self.root,
                videos=videos,
                video_to_dir=all_video_to_dir,
                directories=all_directories,
                start_index=0,
                volume=self.volume,
                is_muted=self.is_muted,
                loop_mode=self.loop_mode,
                logger=self.update_console,
                on_close=self._on_player_closed,
                on_volume_change=self._save_volume_callback,
            )
            player.on_video_changed = self.on_video_changed
            player.on_add_to_playlist = lambda vids: self.playlist_manager.add_videos_to_playlist([], vids)
            player.on_add_to_queue = lambda vids: self.queue_manager.add_to_queue(vids, added_from="player")
            player.on_add_to_favourites = lambda vids: self.favorites_manager.add_to_favorites(vids,
                                                                                               self.get_current_selected_directory() or os.path.dirname(
                                                                                                   vids[0]))
            player.set_hotkeys(self.settings_manager.get_settings().hotkeys)

            player.play()
            self._active_player = player

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
                    if not self.is_video_excluded(selected_dir, item_path):
                        selected_videos.append(item_path)
                elif item_path and os.path.isdir(item_path):
                    for root, dirs, files in os.walk(item_path):
                        for file in files:
                            full_path = os.path.join(root, file)
                            if is_video(full_path):
                                if not self.is_video_excluded(selected_dir, full_path):
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

            is_filtered_mode = hasattr(self, '_is_filtered_mode') and self._is_filtered_mode

            if is_filtered_mode:
                if os.path.isfile(target_path) and is_video(target_path):
                    listbox.selection_clear(0, tk.END)
                    listbox.selection_set(index)
                    listbox.activate(index)
                    self.root.after(100, self.play_videos)
                return "break"

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
                new_query = self.search_entry.get().strip().lower()
            except Exception:
                new_query = ""
            if new_query == self.search_query:
                return
            self.search_query = new_query
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

        def get_all_videos_for_statistics(self):
            all_videos = []
            for directory in self.selected_dirs:
                cache = self.scan_cache.get(directory)
                if cache:
                    videos, _, _ = cache
                    for video in videos:
                        if not self.is_video_excluded(directory, video):
                            all_videos.append(video)
            return all_videos

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
            suffix = f" (scanning {pending}…)" if pending else ""
            self.video_count_label.config(text=f"  —  {self.video_count} videos{suffix}")

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

        def _build_video_list(self):
            """
            Assemble (videos, video_to_dir, directories) from scan_cache,
            applying all active exclusions.  In filtered mode the already-
            filtered list is used but exclusions are still honoured.
            Returns (videos, video_to_dir, directories) — all three may be
            empty lists / dicts if no videos are available yet.
            """
            if getattr(self, '_is_filtered_mode', False) and getattr(self, '_filtered_videos', None):
                # Pull video_to_dir entries from cache for these specific paths
                all_v2d = {}
                for directory in self.selected_dirs:
                    cache = self.scan_cache.get(directory)
                    if cache:
                        _, dir_v2d, _ = cache
                        all_v2d.update(dir_v2d)
                # Still honour exclusions even inside a filtered view
                videos = [
                    v for v in self._filtered_videos
                    if not any(
                        self.is_video_excluded(d, v)
                        for d in self.selected_dirs
                        if self.scan_cache.get(d)
                    )
                ]
                video_to_dir = {v: all_v2d.get(v, os.path.dirname(v)) for v in videos}
            else:
                videos = []
                video_to_dir = {}
                for directory in self.selected_dirs:
                    cache = self.scan_cache.get(directory)
                    if not cache:
                        continue
                    dir_videos, dir_v2d, _ = cache
                    for v in dir_videos:
                        if not self.is_video_excluded(directory, v):
                            videos.append(v)
                            video_to_dir[v] = dir_v2d.get(v, os.path.dirname(v))

            directories = list(dict.fromkeys(video_to_dir[v] for v in videos))
            return videos, video_to_dir, directories

        def play_videos(self):
            """Launch EmbeddedPlayer for the full video list."""
            from embedded_player import EmbeddedPlayer

            videos, video_to_dir, directories = self._build_video_list()

            if not videos:
                self.update_console("No videos to play.")
                return

            # ── Resolve start index ───────────────────────────────────────────
            # Priority 1: smart-resume — jump back to the last-played video.
            # Priority 2: start from the first video that belongs to the
            #             currently selected main directory (dir_listbox selection).
            # Priority 3: fall back to 0.
            idx = 0

            if getattr(self, 'start_from_last_played', False) and getattr(self, 'last_played_video_path', ''):
                resume_path = os.path.normpath(self.last_played_video_path)
                for i, v in enumerate(videos):
                    if os.path.normpath(v) == resume_path:
                        idx = i
                        break
                else:
                    # Path not found — fall through to directory-based start
                    try:
                        sel = self.dir_listbox.curselection()
                        if sel and sel[0] < len(self.selected_dirs):
                            target_dir = self.selected_dirs[sel[0]]
                            for i, v in enumerate(videos):
                                if os.path.normpath(video_to_dir.get(v, "")).startswith(
                                        os.path.normpath(target_dir)):
                                    idx = i
                                    break
                    except Exception:
                        pass
            else:
                # No smart-resume: start from the selected main directory
                try:
                    sel = self.dir_listbox.curselection()
                    if not sel and self.current_selected_dir_index is not None:
                        sel = (self.current_selected_dir_index,)
                    if sel and sel[0] < len(self.selected_dirs):
                        target_dir = os.path.normpath(self.selected_dirs[sel[0]])
                        for i, v in enumerate(videos):
                            if os.path.normpath(video_to_dir.get(v, "")).startswith(target_dir):
                                idx = i
                                break
                except Exception:
                    pass

            vol      = getattr(self, 'volume', 50)
            is_muted = getattr(self, 'is_muted', False)
            loop     = getattr(self, 'loop_mode', 'loop_on')

            player = EmbeddedPlayer(
                parent=self.root,
                videos=videos,
                video_to_dir=video_to_dir,
                directories=directories,
                start_index=idx,
                volume=vol,
                is_muted=is_muted,
                loop_mode=loop,
                logger=self.update_console,
                on_close=self._on_player_closed,
                on_volume_change=self._save_volume_callback,
            )
            player.on_loop_change = self._save_loop_callback
            player.on_close_save  = self._on_player_close_save
            player.on_video_changed = self.on_video_changed
            player.on_add_to_playlist = lambda vids: self.playlist_manager.add_videos_to_playlist([], vids)
            player.on_add_to_queue = lambda vids: self.queue_manager.add_to_queue(vids, added_from="player")
            player.on_add_to_favourites = lambda vids: self.favorites_manager.add_to_favorites(vids,
                                                                                               self.get_current_selected_directory() or os.path.dirname(
                                                                                                   vids[0]))
            player.set_hotkeys(self.settings_manager.get_settings().hotkeys)

            player.play()
            self._active_player = player

        def play_selected_videos(self):
            """Launch EmbeddedPlayer for the videos currently selected in the listbox,
            honouring all active exclusions and expanding folder selections."""
            from embedded_player import EmbeddedPlayer

            selected_dir = self.get_current_selected_directory()

            try:
                selected_indices = list(self.exclusion_listbox.curselection())
            except Exception:
                selected_indices = []

            if not selected_indices:
                self.update_console("No videos selected.")
                return

            selected_videos = []
            seen = set()

            for i in selected_indices:
                path = self.current_subdirs_mapping.get(i)
                if not path:
                    continue

                if os.path.isfile(path) and is_video(path):
                    # Single video — honour exclusion
                    if selected_dir and self.is_video_excluded(selected_dir, path):
                        continue
                    norm = os.path.normpath(path)
                    if norm not in seen:
                        seen.add(norm)
                        selected_videos.append(path)

                elif os.path.isdir(path):
                    # Folder selected — walk it and collect non-excluded videos
                    try:
                        for root, dirs, files in os.walk(path):
                            for f in sorted(files):
                                full = os.path.join(root, f)
                                if is_video(full):
                                    if selected_dir and self.is_video_excluded(selected_dir, full):
                                        continue
                                    norm = os.path.normpath(full)
                                    if norm not in seen:
                                        seen.add(norm)
                                        selected_videos.append(full)
                    except (PermissionError, OSError):
                        pass

            if not selected_videos:
                self.update_console("No valid non-excluded video files in selection.")
                return

            # Build video_to_dir by looking up each path in scan_cache
            all_v2d = {}
            for directory in self.selected_dirs:
                cache = self.scan_cache.get(directory)
                if cache:
                    _, dir_v2d, _ = cache
                    all_v2d.update(dir_v2d)

            sel_v2d  = {v: all_v2d.get(v, os.path.dirname(v)) for v in selected_videos}
            sel_dirs = list(dict.fromkeys(sel_v2d[v] for v in selected_videos))

            vol      = getattr(self, 'volume', 50)
            is_muted = getattr(self, 'is_muted', False)
            loop     = getattr(self, 'loop_mode', 'loop_on')

            self.update_console(f"Playing {len(selected_videos)} selected video(s)")

            player = EmbeddedPlayer(
                parent=self.root,
                videos=selected_videos,
                video_to_dir=sel_v2d,
                directories=sel_dirs,
                start_index=0,
                volume=vol,
                is_muted=is_muted,
                loop_mode=loop,
                logger=self.update_console,
                on_close=self._on_player_closed,
                on_volume_change=self._save_volume_callback,
            )
            player.on_loop_change = self._save_loop_callback
            player.on_close_save  = self._on_player_close_save
            player.on_video_changed = self.on_video_changed
            player.on_add_to_playlist = lambda vids: self.playlist_manager.add_videos_to_playlist([], vids)
            player.on_add_to_queue = lambda vids: self.queue_manager.add_to_queue(vids, added_from="player")
            player.on_add_to_favourites = lambda vids: self.favorites_manager.add_to_favorites(vids,
                                                                                               self.get_current_selected_directory() or os.path.dirname(
                                                                                                   vids[0]))
            player.set_hotkeys(self.settings_manager.get_settings().hotkeys)

            player.play()
            self._active_player = player

        def _on_player_closed(self):
            """Called when the EmbeddedPlayer window is closed."""
            self._active_player = None
            self.update_console("Player closed.")
            self._on_player_stopped()

        def _save_loop_callback(self, loop_mode: str):
            """Fired by EmbeddedPlayer whenever the user cycles the loop mode."""
            self.loop_mode = loop_mode
            if hasattr(self, 'loop_toggle_button'):
                try:
                    self.loop_toggle_button.config(text=self._get_loop_icon())
                except Exception:
                    pass
            self.save_preferences()

        def _on_player_close_save(self, index: int, path: str,
                                  loop_mode: str, volume: int, is_muted: bool):
            """Called by EmbeddedPlayer._close() with the final playback state."""
            self.loop_mode               = loop_mode
            self.volume                  = volume
            self.is_muted                = is_muted
            self.last_played_video_index = index
            self.last_played_video_path  = path
            if hasattr(self, 'loop_toggle_button'):
                try:
                    self.loop_toggle_button.config(text=self._get_loop_icon())
                except Exception:
                    pass
            self.save_preferences()
            if hasattr(self, 'watch_history_manager') and path:
                self.watch_history_manager.track_video_end(path)

        def on_video_changed(self, video_index, video_path):
            if hasattr(self, 'filter_sort_manager'):
                self.filter_sort_manager.metadata_cache.update_play_stats(video_path)
            self.last_played_video_index = video_index
            self.last_played_video_path = video_path
            if self.smart_resume_var.get():
                self.save_preferences()

            self.grid_view_manager.mark_now_playing(video_path)
            self._now_playing_video_path = os.path.normpath(video_path) if video_path else None
            self._update_tree_now_playing()
            if hasattr(self, 'watch_history_manager'):
                self.watch_history_manager.track_video_start(video_path)

        def _on_player_stopped(self):
            self._now_playing_video_path = None
            self.root.after(0, self._clear_now_playing)

        def _clear_now_playing(self):
            self.grid_view_manager.mark_now_playing(None)
            self._update_tree_now_playing()

        def _update_tree_now_playing(self):
            try:
                if not hasattr(self, 'current_subdirs_mapping') or not self.current_subdirs_mapping:
                    return
                now = getattr(self, '_now_playing_video_path', None)
                for idx in range(self.exclusion_listbox.size()):
                    item_path = self.current_subdirs_mapping.get(idx)
                    if not item_path:
                        continue
                    current_text = self.exclusion_listbox.get(idx)
                    is_now = (now and os.path.normpath(item_path) == now)
                    had_tag = " ▶▶▶" in current_text
                    if is_now and not had_tag:
                        self.exclusion_listbox.delete(idx)
                        self.exclusion_listbox.insert(idx, current_text + " ▶▶▶")
                        self.exclusion_listbox.itemconfig(idx, fg="#00aa44")
                    elif not is_now and had_tag:
                        self.exclusion_listbox.delete(idx)
                        self.exclusion_listbox.insert(idx, current_text.replace(" ▶▶▶", ""))
                        self.exclusion_listbox.itemconfig(idx, fg=self.text_color)
                    elif is_now and had_tag:
                        self.exclusion_listbox.itemconfig(idx, fg="#00aa44")
            except Exception:
                pass

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

            ManagedThread(target=worker, name="ExcludeAllWorker").start()

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

            ManagedThread(target=worker, name="ExcludeWorker").start()

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

            ManagedThread(target=worker, name="IncludeWorker").start()

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
                _cache = self.scan_cache.get(directory)
                if _cache:
                    _videos, _, _ = _cache
                    _excluded_subdirs = self.excluded_subdirs.get(directory, [])
                    _excluded_videos = self.excluded_videos.get(directory, [])
                    if _excluded_subdirs or _excluded_videos:
                        _count = sum(1 for v in _videos if not self.is_video_excluded(directory, v))
                    else:
                        _count = len(_videos)
                    self.selected_dir_label.config(text=f"All items in: {os.path.basename(directory)} ({_count} videos)")
                else:
                    self.selected_dir_label.config(text=f"All items in: {os.path.basename(directory)}")
            self.exclusion_listbox.delete(0, tk.END)
            self.exclusion_listbox.insert(tk.END, "Loading...")
            self.current_subdirs_mapping = {}

            try:
                if isinstance(directory, str) and directory.startswith("gdrive://"):
                    cache = self.scan_cache.get(directory)
                    items = []
                    if cache:
                        videos, video_to_dir, directories = cache

                        if directory.startswith("gdrive://folder/"):
                            tree = None
                            try:
                                if self.drive_manager:
                                    tree = self.drive_manager.get_folder_tree(directory)
                            except Exception:
                                tree = None

                            dir_prefix = directory.rstrip('/')
                            subdirs = []
                            for d in directories:
                                if d.startswith(dir_prefix):
                                    subdirs.append(d)
                            subdirs = sorted(subdirs, key=lambda s: (s.count('/'), s))

                            base_depth = dir_prefix.count('/')

                            for d in subdirs:
                                rel_depth = d.count('/') - base_depth
                                name = os.path.basename(d)
                                if tree and 'dir_names' in tree:
                                    name = tree['dir_names'].get(d, name)
                                if d != dir_prefix:
                                    indented = ("  " * rel_depth) + '📁' + name
                                    items.append((d, indented))

                                if self.show_videos:
                                    for v in videos:
                                        parent = video_to_dir.get(v)
                                        if parent == d:
                                            vname = None
                                            if tree and 'file_names' in tree:
                                                vname = tree['file_names'].get(v)
                                            if not vname:
                                                vname = 'Drive Stream'
                                            ind = ("  " * (rel_depth + 1)) + '▶ ' + vname
                                            items.append((v, ind))
                        else:
                            for v in videos:
                                display = '▶ Drive Stream'
                                items.append((v, display))

                    def _post_drive_items():
                        self.exclusion_listbox.delete(0, tk.END)
                        if not items:
                            self.exclusion_listbox.insert(tk.END, "No items")
                            self.current_subdirs_mapping = {}
                        else:
                            self.current_subdirs_mapping = {}
                            for idx, (p, name) in enumerate(items):
                                self.exclusion_listbox.insert(tk.END, name)
                                self.current_subdirs_mapping[idx] = p
                        if restore_scroll:
                            try:
                                self.exclusion_listbox.yview_moveto(restore_scroll[0])
                            except Exception:
                                pass

                    self.root.after(0, _post_drive_items)
                    return
            except Exception:
                pass

            if not hasattr(self, '_subdir_load_token'):
                self._subdir_load_token = None
                self._subdir_load_lock = threading.RLock()

            with self._subdir_load_lock:
                token = object()
                self._subdir_load_token = token

            excluded_dir_set = set(self.excluded_subdirs.get(directory, []))
            excluded_vid_set = set(self.excluded_videos.get(directory, []))
            show_videos = self.show_videos
            only_excluded = self.show_only_excluded

            def build_and_post():
                try:
                    if self.resource_manager.is_shutting_down():
                        return
                    with self._subdir_load_lock:
                        if self._subdir_load_token is not token:
                            return
                    base = os.path.abspath(directory)
                    base_sep = os.sep
                    items = []

                    for root, dirs, files in os.walk(base):
                        if self.resource_manager.is_shutting_down():
                            break
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

                                self._update_tree_now_playing()

                        insert_chunk(0)

                    self.root.after(0, post_chunks)

                except Exception as e:
                    err_msg = str(e)
                    def post_error(msg=err_msg):
                        if self._subdir_load_token is not token:
                            return
                        self.exclusion_listbox.delete(0, tk.END)
                        self.exclusion_listbox.insert(tk.END, f"Error loading subdirectories: {msg}")
                        self.current_subdirs_mapping = {}
                    self.root.after(0, post_error)

            ManagedThread(target=build_and_post, name="LoadSubdirs").start()

        def setup_action_buttons(self):
            # ── Custom toolbar frame packed above main_frame ──────────────────────
            def _tb_colors():
                if self.dark_mode:
                    return {
                        "bg":        "#1E1F22",
                        "fg":        "#A9B7C6",
                        "hover_bg":  "#2D5A8E",
                        "hover_fg":  "#FFFFFF",
                        "active_bg": "#1A4070",
                        "active_fg": "#FFFFFF",
                        "play_fg":   "#FF6B6B",
                        "play_hover":"#C0392B",
                        "sep":       "#3A3B3E",
                    }
                else:
                    return {
                        "bg":        "#ECECEC",
                        "fg":        "#2B2B2B",
                        "hover_bg":  "#DCDCDC",
                        "hover_fg":  "#000000",
                        "active_bg": "#CCCCCC",
                        "active_fg": "#000000",
                        "play_fg":   "#c0392b",
                        "play_hover":"#992d22",
                        "play_hover_bg": "#c0392b",
                        "sep":       "#E0E0E0",
                    }

            self._tb_colors = _tb_colors

            self.toolbar = tk.Frame(self.root, bg=_tb_colors()["bg"], height=28)
            self.toolbar.pack(side=tk.TOP, fill=tk.X, before=self.main_frame)
            self.toolbar.pack_propagate(False)

            self._toolbar_btns = {}   # label -> tk.Label widget

            def make_dropdown_menu(entries):
                """entries: list of (label, command) or None for separator."""
                c = _tb_colors()
                menu = tk.Menu(self.root, tearoff=0,
                               bg=c["bg"], fg=c["fg"],
                               activebackground=c["hover_bg"],
                               activeforeground=c["hover_fg"],
                               relief="flat", bd=1,
                               font=("Segoe UI", 9))
                for entry in entries:
                    if entry is None:
                        menu.add_separator()
                    else:
                        lbl, cmd = entry
                        menu.add_command(label=lbl, command=cmd)
                return menu

            def make_toolbar_btn(text, command=None, menu=None, is_action=False, play=False):
                c = _tb_colors()
                fg = c["play_fg"] if play else c["fg"]
                font_weight = "bold" if play else "normal"
                btn = tk.Label(
                    self.toolbar,
                    text=text,
                    bg=c["bg"],
                    fg=fg,
                    font=("Segoe UI", 9, font_weight),
                    padx=10, pady=4,
                    cursor="hand2"
                )
                btn.pack(side=tk.LEFT)
                self._toolbar_btns[text] = btn

                def on_enter(e, b=btn):
                    cc = _tb_colors()
                    b.config(bg=cc["hover_bg"], fg=cc["hover_fg"])

                def on_leave(e, b=btn, p=play):
                    cc = _tb_colors()
                    b.config(bg=cc["bg"], fg=cc["play_fg"] if p else cc["fg"])

                def on_press(e, b=btn):
                    cc = _tb_colors()
                    b.config(bg=cc["active_bg"], fg=cc["active_fg"])

                def on_release(e, b=btn, m=menu, cmd=command):
                    cc = _tb_colors()
                    b.config(bg=cc["hover_bg"], fg=cc["hover_fg"])
                    if m:
                        try:
                            m.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())
                        finally:
                            m.grab_release()
                    elif cmd:
                        cmd()

                btn.bind("<Enter>",          on_enter)
                btn.bind("<Leave>",          on_leave)
                btn.bind("<ButtonPress-1>",  on_press)
                btn.bind("<ButtonRelease-1>",on_release)
                return btn

            # ── File ──────────────────────────────────────────────────────────────
            file_menu = make_dropdown_menu([
                ("Add Directory",           self.add_directory),
                ("Add Google Drive Link",   self.add_drive_link),
                None,
                ("Exit",                    self.cancel),
            ])
            make_toolbar_btn("File", menu=file_menu)

            # ── View ──────────────────────────────────────────────────────────────
            view_menu = make_dropdown_menu([
                ("Show/Hide Console",       self.toggle_console),
                None,
                ("Filter / Sort",           self._show_filter_dialog),
            ])
            make_toolbar_btn("View", menu=view_menu)

            # ── Playback ──────────────────────────────────────────────────────────
            self._loop_mode_var = tk.StringVar(value=self.loop_mode)
            c = _tb_colors()
            _sel_color = "#4A9EFF" if self.dark_mode else "#2d89ef"
            loop_sub = tk.Menu(self.root, tearoff=0,
                               bg=c["bg"], fg=c["fg"],
                               activebackground=c["hover_bg"],
                               activeforeground=c["hover_fg"],
                               selectcolor=_sel_color,
                               relief="flat", bd=1,
                               font=("Segoe UI", 9))
            for mode, lbl in [("loop_on", "Loop On"), ("loop_off", "Loop Off"), ("shuffle", "Shuffle")]:
                loop_sub.add_radiobutton(
                    label=lbl,
                    variable=self._loop_mode_var,
                    value=mode,
                    command=lambda m=mode: self._set_loop_mode_menu(m))
            self._loop_sub_menu = loop_sub

            playback_menu = tk.Menu(self.root, tearoff=0,
                                    bg=c["bg"], fg=c["fg"],
                                    activebackground=c["hover_bg"],
                                    activeforeground=c["hover_fg"],
                                    relief="flat", bd=1,
                                    font=("Segoe UI", 9))
            playback_menu.add_cascade(label="Loop Mode", menu=loop_sub)
            playback_menu.add_separator()
            playback_menu.add_command(label="Sleep Timer", command=self._show_sleep_timer_dialog)
            make_toolbar_btn("Playback", menu=playback_menu)

            make_toolbar_btn("Settings", command=self._show_settings)

            _media_pill_commands = {
                "🎵 Playlist":   self._manage_playlists,
                "⬛ Queue":      self._show_queue_manager,
                "♥ Favourites": self._show_favorites_manager,
                "🕐 History":   self._show_watch_history,
            }

            self._media_pill_btns = {}

            def _make_media_pill(label):
                a = self.pill_accents(label)  # palette lives in ThemeSelector
                c = _tb_colors()
                btn = tk.Label(
                    self.toolbar,
                    text=label,
                    bg=c["bg"],
                    fg=a[0],
                    font=("Segoe UI", 9, "bold"),
                    padx=9, pady=3,
                    cursor="hand2",
                    relief="flat",
                    highlightthickness=1,
                    highlightbackground=a[0],
                    highlightcolor=a[0],
                )
                btn.pack(side=tk.LEFT, padx=(0, 3), pady=2)
                self._media_pill_btns[label] = btn

                def on_enter(e, b=btn, lbl=label):
                    a = self.pill_accents(lbl)
                    b.config(bg=a[1], fg=a[2], highlightbackground=a[1])
                def on_leave(e, b=btn, lbl=label):
                    a = self.pill_accents(lbl); cc = _tb_colors()
                    b.config(bg=cc["bg"], fg=a[0], highlightbackground=a[0])
                def on_press(e, b=btn, lbl=label):
                    a = self.pill_accents(lbl)
                    b.config(bg=a[3], fg=a[2], highlightbackground=a[3])
                def on_release(e, b=btn, lbl=label, cmd=_media_pill_commands[label]):
                    a = self.pill_accents(lbl)
                    b.config(bg=a[1], fg=a[2], highlightbackground=a[1])
                    cmd()

                btn.bind("<Enter>",           on_enter)
                btn.bind("<Leave>",           on_leave)
                btn.bind("<ButtonPress-1>",   on_press)
                btn.bind("<ButtonRelease-1>", on_release)

            for _pill_label in ["🎵 Playlist", "⬛ Queue", "♥ Favourites", "🕐 History"]:
                _make_media_pill(_pill_label)

            self.sleep_countdown_label = tk.Label(
                self.toolbar,
                text="",
                bg=_tb_colors()["bg"],
                fg=_tb_colors()["fg"],
                font=("Segoe UI", 9),
                padx=8, pady=4,
                cursor="hand2"
            )
            self.sleep_countdown_label.pack(side=tk.RIGHT, padx=(0, 2))

            def _sleep_label_click(e):
                if not getattr(self, '_sleep_timer_end', None):
                    return
                try:
                    if getattr(self, '_sleep_timer_paused', False):
                        # resume: restart the after job and countdown
                        import time as _time
                        remaining_ms = int(self._sleep_timer_remaining * 1000)
                        self._sleep_timer_end = _time.time() + self._sleep_timer_remaining
                        self._sleep_timer_job = self.root.after(remaining_ms, self._sleep_timer_fired)
                        self._sleep_timer_paused = False
                        self._start_sleep_countdown()
                        if self.controller:
                            self.controller.player.pause()
                    else:
                        # pause: cancel the after job, store remaining
                        import time as _time
                        if self._sleep_timer_job:
                            self.root.after_cancel(self._sleep_timer_job)
                            self._sleep_timer_job = None
                        if hasattr(self, '_sleep_countdown_job') and self._sleep_countdown_job:
                            self.root.after_cancel(self._sleep_countdown_job)
                            self._sleep_countdown_job = None
                        self._sleep_timer_remaining = max(0, self._sleep_timer_end - _time.time())
                        self._sleep_timer_paused = True
                        if hasattr(self, 'sleep_countdown_label'):
                            mins = int(self._sleep_timer_remaining) // 60
                            secs = int(self._sleep_timer_remaining) % 60
                            self.sleep_countdown_label.config(text=f"⏸ {mins}:{secs:02d}")
                        if self.controller:
                            self.controller.player.pause()
                except Exception:
                    pass

            self.sleep_countdown_label.bind("<ButtonRelease-1>", _sleep_label_click)

            # theme toggle
            self.theme_toolbar_btn = tk.Label(
                self.toolbar,
                text="🌙" if not self.dark_mode else "☀",
                bg=_tb_colors()["bg"],
                fg=_tb_colors()["fg"],
                font=("Segoe UI", 10),
                padx=8, pady=4,
                cursor="hand2"
            )
            self.theme_toolbar_btn.pack(side=tk.RIGHT, padx=(0, 2))

            def _theme_enter(e):
                cc = _tb_colors(); self.theme_toolbar_btn.config(bg=cc["hover_bg"], fg=cc["hover_fg"])
            def _theme_leave(e):
                cc = _tb_colors(); self.theme_toolbar_btn.config(bg=cc["bg"], fg=cc["fg"])
            def _theme_press(e):
                cc = _tb_colors(); self.theme_toolbar_btn.config(bg=cc["active_bg"], fg=cc["active_fg"])
            def _theme_release(e):
                cc = _tb_colors(); self.theme_toolbar_btn.config(bg=cc["hover_bg"], fg=cc["hover_fg"])
                self._toggle_theme_menu()
            self.theme_toolbar_btn.bind("<Enter>",          _theme_enter)
            self.theme_toolbar_btn.bind("<Leave>",          _theme_leave)
            self.theme_toolbar_btn.bind("<ButtonPress-1>",  _theme_press)
            self.theme_toolbar_btn.bind("<ButtonRelease-1>",_theme_release)

            # play button
            self.play_toolbar_btn = tk.Label(
                self.toolbar,
                text="▶  Play Videos",
                bg=_tb_colors()["bg"],
                fg=_tb_colors()["play_fg"],
                font=("Segoe UI", 9, "bold"),
                padx=12, pady=4,
                cursor="hand2"
            )
            self.play_toolbar_btn.pack(side=tk.RIGHT, padx=(0, 6))

            def _play_enter(e):
                cc = _tb_colors(); self.play_toolbar_btn.config(bg=cc.get("play_hover_bg", cc["hover_bg"]), fg="#FFFFFF")
            def _play_leave(e):
                cc = _tb_colors(); self.play_toolbar_btn.config(bg=cc["bg"], fg=cc["play_fg"])
            def _play_press(e):
                cc = _tb_colors(); self.play_toolbar_btn.config(bg=cc.get("play_hover_bg", cc["active_bg"]), fg="#FFFFFF")
            def _play_release(e):
                cc = _tb_colors(); self.play_toolbar_btn.config(bg=cc["hover_bg"], fg="#FFFFFF")
                self.play_videos()
            self.play_toolbar_btn.bind("<Enter>",          _play_enter)
            self.play_toolbar_btn.bind("<Leave>",          _play_leave)
            self.play_toolbar_btn.bind("<ButtonPress-1>",  _play_press)
            self.play_toolbar_btn.bind("<ButtonRelease-1>",_play_release)

            # placeholder so toggle_console's before= ref works
            self.button_frame = tk.Frame(self.main_frame, bg=self.bg_color)
            self.button_frame.pack(fill=tk.X)

        def _show_sleep_timer_dialog(self):
            # if timer already running, cancel it
            if getattr(self, '_sleep_timer_job', None):
                self.root.after_cancel(self._sleep_timer_job)
                self._sleep_timer_job = None
                if hasattr(self, '_sleep_countdown_job') and self._sleep_countdown_job:
                    self.root.after_cancel(self._sleep_countdown_job)
                    self._sleep_countdown_job = None
                self._sleep_timer_end = None
                self._sleep_timer_paused = False
                if hasattr(self, 'sleep_countdown_label'):
                    self.sleep_countdown_label.config(text="")
                self.update_console("Sleep timer cancelled")
                return

            dlg = tk.Toplevel(self.root)
            dlg.title("Sleep Timer")
            dlg.geometry("300x160")
            dlg.configure(bg=self.bg_color)
            dlg.transient(self.root)
            dlg.grab_set()
            dlg.resizable(False, False)

            tk.Label(dlg, text="Stop playback after (minutes):",
                     font=self.normal_font, bg=self.bg_color,
                     fg=self.text_color).pack(pady=(20, 8))

            minutes_var = tk.IntVar(value=30)
            spin = tk.Spinbox(dlg, from_=1, to=300,
                              textvariable=minutes_var,
                              font=self.normal_font, width=8,
                              bg=self.bg_color, fg=self.text_color)
            spin.pack()

            def start():
                import time as _time
                minutes = minutes_var.get()
                ms = minutes * 60 * 1000
                self._sleep_timer_end = _time.time() + (minutes * 60)
                self._sleep_timer_job = self.root.after(ms, self._sleep_timer_fired)
                self._start_sleep_countdown()
                self.update_console(f"Sleep timer set for {minutes} minutes")
                dlg.destroy()

            self.create_button(dlg, "Set Timer", start, "primary", "md").pack(pady=15)
            dlg.bind("<Return>", lambda e: start())

        def _start_sleep_countdown(self):
            import time as _time

            def tick():
                if not getattr(self, '_sleep_timer_end', None):
                    return
                if getattr(self, '_sleep_timer_paused', False):
                    return
                remaining = int(self._sleep_timer_end - _time.time())
                if remaining <= 0:
                    return
                mins = remaining // 60
                secs = remaining % 60
                if hasattr(self, 'sleep_countdown_label'):
                    self.sleep_countdown_label.config(text=f"⏾ {mins}:{secs:02d}")
                self._sleep_countdown_job = self.root.after(1000, tick)

            self._sleep_countdown_job = None
            tick()

        def _sleep_timer_fired(self):
            self._sleep_timer_job = None
            self._sleep_timer_end = None
            self._sleep_timer_paused = False
            if hasattr(self, '_sleep_countdown_job') and self._sleep_countdown_job:
                self.root.after_cancel(self._sleep_countdown_job)
                self._sleep_countdown_job = None
            if hasattr(self, 'sleep_countdown_label'):
                self.sleep_countdown_label.config(text="")
            self.update_console("Sleep timer: stopping playback")
            if self._active_player is not None:
                try:
                    self._active_player._close()
                except Exception:
                    pass
                self._active_player = None

        def setup_status_section(self):
            # Video count is now shown inline in the exclusion section header
            pass

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

                if hasattr(self, 'scan_cache') and self.scan_cache.get(dir_to_remove) is not None:
                    self.scan_cache.delete(dir_to_remove)
                if hasattr(self, 'pending_scans'):
                    self.pending_scans.discard(dir_to_remove)

                # Remove cached thumbnail blobs for this directory
                if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
                    self.video_preview_manager.evict_for_directory(dir_to_remove)

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

            from embedded_player import EmbeddedPlayer

            if self._active_player is not None:
                try:
                    self._active_player._close()
                except Exception:
                    pass
                self._active_player = None

            all_video_to_dir = {}
            for directory in self.selected_dirs:
                cache = self.scan_cache.get(directory)
                if cache:
                    _, v2d, _ = cache
                    all_video_to_dir.update(v2d)
            for v in videos:
                if v not in all_video_to_dir:
                    all_video_to_dir[v] = os.path.dirname(v)

            all_directories = list(dict.fromkeys(all_video_to_dir[v] for v in videos))

            self.update_console(f"Playing {len(videos)} videos from grid selection")

            vol      = getattr(self, 'volume', 50)
            is_muted = getattr(self, 'is_muted', False)
            loop     = getattr(self, 'loop_mode', 'loop_on')

            player = EmbeddedPlayer(
                parent=self.root,
                videos=videos,
                video_to_dir=all_video_to_dir,
                directories=all_directories,
                start_index=0,
                volume=vol,
                is_muted=is_muted,
                loop_mode=loop,
                logger=self.update_console,
                on_close=self._on_player_closed,
                on_volume_change=self._save_volume_callback,
            )
            player.on_video_changed = self.on_video_changed
            player.on_add_to_playlist = lambda vids: self.playlist_manager.add_videos_to_playlist([], vids)
            player.on_add_to_queue = lambda vids: self.queue_manager.add_to_queue(vids, added_from="player")
            player.on_add_to_favourites = lambda vids: self.favorites_manager.add_to_favorites(vids,
                                                                                               self.get_current_selected_directory() or os.path.dirname(
                                                                                                   vids[0]))
            player.set_hotkeys(self.settings_manager.get_settings().hotkeys)

            player.play()
            self._active_player = player

        def _add_to_playlist(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showwarning("Warning", "Please select a directory first")
                return

            selection = self.exclusion_listbox.curselection()

            if selection:
                selected_videos = self._resolve_selection_indices_to_videos(selected_dir, selection)

                if selected_videos:
                    self.playlist_manager.add_videos_to_playlist([], selected_videos)
                    self.update_console(f"Added {len(selected_videos)} selected videos to playlist")
                else:
                    messagebox.showwarning("Warning", "No videos found in selected items")
            else:
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
                            if all_videos:
                                self.playlist_manager.add_videos_to_playlist([], all_videos)
                                self.update_console(f"Added all {len(all_videos)} videos to playlist")
                            else:
                                messagebox.showwarning("Warning", "No videos found to add to playlist")

                        self.root.after(0, finish_collection)

                    except Exception as e:
                        def show_error():
                            messagebox.showerror("Error", f"Failed to collect videos: {e}")

                        self.root.after(0, show_error)

                threading.Thread(target=collect_all_videos, daemon=True).start()

        def _manage_playlists(self):
            self.playlist_manager.show_manager()

        def _play_playlist_videos(self, videos):
            if not videos:
                messagebox.showwarning("Warning", "Playlist is empty")
                return

            if self._active_player is not None:
                try:
                    self._active_player._close()
                except Exception:
                    pass
                self._active_player = None

            self.update_console("=" * 100)
            self.update_console("STARTING PLAYLIST PLAYBACK")
            self.update_console("=" * 100)

            all_video_to_dir = {}
            all_directories = []

            for video_path in videos:
                if self._is_stream_url(video_path):
                    video_dir = "STREAMS"
                    all_video_to_dir[video_path] = video_dir
                    if video_dir not in all_directories:
                        all_directories.append(video_dir)
                elif os.path.isfile(video_path):
                    video_dir = os.path.dirname(video_path)
                    all_video_to_dir[video_path] = video_dir
                    if video_dir not in all_directories:
                        all_directories.append(video_dir)

            all_directories.sort()
            valid_videos = list(all_video_to_dir.keys())

            if not valid_videos:
                messagebox.showwarning("Warning", "No valid videos found in playlist")
                return

            self.update_console(f"Playing playlist with {len(valid_videos)} videos")
            from embedded_player import EmbeddedPlayer
            player = EmbeddedPlayer(
                parent=self.root,
                videos=valid_videos,
                video_to_dir=all_video_to_dir,
                directories=all_directories,
                start_index=0,
                volume=self.volume,
                is_muted=self.is_muted,
                loop_mode=self.loop_mode,
                logger=self.update_console,
                on_close=self._on_player_closed,
                on_volume_change=self._save_volume_callback,
            )
            player.on_video_changed = self.on_video_changed
            player.on_add_to_playlist = lambda vids: self.playlist_manager.add_videos_to_playlist([], vids)
            player.on_add_to_queue = lambda vids: self.queue_manager.add_to_queue(vids, added_from="player")
            player.on_add_to_favourites = lambda vids: self.favorites_manager.add_to_favorites(vids,
                                                                                               self.get_current_selected_directory() or os.path.dirname(
                                                                                                   vids[0]))
            player.set_hotkeys(self.settings_manager.get_settings().hotkeys)

            player.play()
            self._active_player = player

        def _show_queue_manager(self):
            self.queue_manager.show_manager()

        def _context_add_to_queue(self, selection, mode="queue"):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                return

            final_videos = self._resolve_selection_indices_to_videos(selected_dir, selection)

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

            if self._active_player is not None:
                try:
                    self._active_player._close()
                except Exception:
                    pass
                self._active_player = None

            all_video_to_dir = {}
            all_directories = []

            for video_path in videos:
                if self._is_stream_url(video_path):
                    video_dir = "STREAMS"
                    all_video_to_dir[video_path] = video_dir
                    if video_dir not in all_directories:
                        all_directories.append(video_dir)
                elif os.path.isfile(video_path):
                    video_dir = os.path.dirname(video_path)
                    all_video_to_dir[video_path] = video_dir
                    if video_dir not in all_directories:
                        all_directories.append(video_dir)

            all_directories.sort()
            valid_videos = list(all_video_to_dir.keys())

            if not valid_videos:
                messagebox.showwarning("Warning", "No valid videos found")
                return

            self.update_console(f"Playing queue with {len(valid_videos)} videos")
            from embedded_player import EmbeddedPlayer
            player = EmbeddedPlayer(
                parent=self.root,
                videos=valid_videos,
                video_to_dir=all_video_to_dir,
                directories=all_directories,
                start_index=0,
                volume=self.volume,
                is_muted=self.is_muted,
                loop_mode="loop_off",
                logger=self.update_console,
                on_close=self._on_player_closed,
                on_volume_change=self._save_volume_callback,
            )
            player.on_video_changed = self.on_video_changed
            player.on_add_to_playlist = lambda vids: self.playlist_manager.add_videos_to_playlist([], vids)
            player.on_add_to_queue = lambda vids: self.queue_manager.add_to_queue(vids, added_from="player")
            player.on_add_to_favourites = lambda vids: self.favorites_manager.add_to_favorites(vids,
                                                                                               self.get_current_selected_directory() or os.path.dirname(
                                                                                                   vids[0]))
            player.set_hotkeys(self.settings_manager.get_settings().hotkeys)

            player.play()
            self._active_player = player

        def _show_watch_history(self):
            self.watch_history_manager.show_manager()

        def _play_history_videos(self, videos):
            if not videos:
                messagebox.showwarning("Warning", "No videos to play")
                return

            if self._active_player is not None:
                try:
                    self._active_player._close()
                except Exception:
                    pass
                self._active_player = None

            self.update_console("=" * 100)
            self.update_console("STARTING HISTORY VIDEO PLAYBACK")
            self.update_console("=" * 100)

            all_video_to_dir = {}
            all_directories = []

            for video_path in videos:
                if self._is_stream_url(video_path):
                    video_dir = "STREAMS"
                    all_video_to_dir[video_path] = video_dir
                    if video_dir not in all_directories:
                        all_directories.append(video_dir)
                elif os.path.isfile(video_path):
                    video_dir = os.path.dirname(video_path)
                    all_video_to_dir[video_path] = video_dir
                    if video_dir not in all_directories:
                        all_directories.append(video_dir)

            all_directories.sort()
            valid_videos = list(all_video_to_dir.keys())

            if not valid_videos:
                messagebox.showwarning("Warning", "No valid videos found")
                return

            self.update_console(f"Playing {len(valid_videos)} videos from history")
            from embedded_player import EmbeddedPlayer
            player = EmbeddedPlayer(
                parent=self.root,
                videos=valid_videos,
                video_to_dir=all_video_to_dir,
                directories=all_directories,
                start_index=0,
                volume=self.volume,
                is_muted=self.is_muted,
                loop_mode=self.loop_mode,
                logger=self.update_console,
                on_close=self._on_player_closed,
                on_volume_change=self._save_volume_callback,
            )
            player.on_video_changed = self.on_video_changed
            player.on_add_to_playlist = lambda vids: self.playlist_manager.add_videos_to_playlist([], vids)
            player.on_add_to_queue = lambda vids: self.queue_manager.add_to_queue(vids, added_from="player")
            player.on_add_to_favourites = lambda vids: self.favorites_manager.add_to_favorites(vids,
                                                                                               self.get_current_selected_directory() or os.path.dirname(
                                                                                                   vids[0]))
            player.set_hotkeys(self.settings_manager.get_settings().hotkeys)

            player.play()
            self._active_player = player

        def toggle_smart_resume(self):
            enabled = bool(self.smart_resume_var.get())
            self.resume_manager.set_resume_enabled(enabled)
            self.start_from_last_played = enabled
            self.smart_resume_enabled = enabled
            self.save_preferences()

        def _show_settings(self):
            self.settings_manager.show_settings()

        def _open_dual_player(self, win_id: int = 1):
            selected_dir = self.get_current_selected_directory()
            if selected_dir:
                cache = self.scan_cache.get(selected_dir)
                if cache:
                    videos, _, _ = cache
                    filtered = [v for v in videos
                                if not self.is_video_excluded(selected_dir, v)]
                    if filtered:
                        self.dual_player_manager.load_videos_into_slot(win_id, 1, filtered[:200])
                        return
            self.dual_player_manager.show(win_id)

        def _save_volume_callback(self, volume, is_muted=None):
            self.volume = volume
            if is_muted is not None:
                self.is_muted = is_muted
            self.save_preferences()

        def _is_stream_url(self, path: str) -> bool:
            return isinstance(path, str) and (path.startswith("http://") or path.startswith("https://"))

        def _collect_videos_from_pseudo_dir(self, root_pseudo_dir: str, pseudo_dir: str) -> list:
            cache = self.scan_cache.get(root_pseudo_dir)
            if not cache:
                return []
            videos, video_to_dir, directories = cache
            results = []
            prefix = pseudo_dir.rstrip('/') + '/'
            for v in videos:
                parent = video_to_dir.get(v)
                if not parent:
                    continue
                if parent == pseudo_dir or parent.startswith(prefix):
                    results.append(v)
            return results

        def _resolve_selection_indices_to_videos(self, selected_dir, indices) -> list:
            collected = []
            for index in indices:
                item_path = self.current_subdirs_mapping.get(index)
                if not item_path:
                    continue

                if self._is_stream_url(item_path):
                    if not self.is_video_excluded(selected_dir, item_path):
                        collected.append(item_path)
                    continue

                if isinstance(item_path, str) and item_path.startswith("gdrive://folder/"):
                    root_pseudo = None
                    for d in self.selected_dirs:
                        if isinstance(d, str) and d.startswith("gdrive://folder/") and item_path.startswith(d):
                            root_pseudo = d
                            break
                    if root_pseudo:
                        for v in self._collect_videos_from_pseudo_dir(root_pseudo, item_path):
                            if not self.is_video_excluded(root_pseudo, v):
                                collected.append(v)
                    continue

                if os.path.isfile(item_path) and is_video(item_path):
                    if not self.is_video_excluded(selected_dir, item_path):
                        collected.append(item_path)
                    continue

                if os.path.isdir(item_path):
                    try:
                        for root, dirs, files in os.walk(item_path):
                            for f in files:
                                full_path = os.path.join(root, f)
                                if is_video(full_path) and not self.is_video_excluded(selected_dir, full_path):
                                    collected.append(full_path)
                    except Exception as e:
                        self.update_console(f"Error reading folder {item_path}: {e}")

            seen = set()
            final_videos = []
            for v in collected:
                v_norm = v if self._is_stream_url(v) else os.path.normpath(v)
                if v_norm not in seen:
                    seen.add(v_norm)
                    final_videos.append(v_norm)
            return final_videos

        def _ask_drive_link_dialog(self):
            dlg = tk.Toplevel(self.root)
            dlg.title("Add Google Drive Link")
            dlg.configure(bg=self.bg_color)
            dlg.transient(self.root)
            dlg.grab_set()

            dlg.geometry("560x260")
            try:
                dlg.update_idletasks()
                x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (560 // 2)
                y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (260 // 2)
                dlg.geometry(f"+{x}+{y}")
            except Exception:
                pass

            result = {"url": None}

            container = tk.Frame(dlg, bg=self.bg_color)
            container.pack(fill=tk.BOTH, expand=True, padx=18, pady=16)

            header = tk.Label(
                container,
                text="Add Google Drive Link",
                font=self.header_font,
                bg=self.bg_color,
                fg=self.text_color
            )
            header.pack(anchor="w")

            helper = tk.Label(
                container,
                text="Paste a public Google Drive folder or file link. The folder structure will be preserved.",
                font=self.small_font,
                bg=self.bg_color,
                fg=self.accent_color,
                wraplength=520,
                justify=tk.LEFT
            )
            helper.pack(anchor="w", pady=(6, 10))

            entry_frame = tk.Frame(container, bg=self.bg_color)
            entry_frame.pack(fill=tk.X)

            url_var = tk.StringVar()
            entry = tk.Entry(
                entry_frame,
                textvariable=url_var,
                font=self.normal_font,
                bg=self.listbox_bg,
                fg=self.listbox_fg,
                relief=tk.FLAT,
                insertbackground=self.text_color,
                highlightthickness=1,
                highlightbackground=self.accent_color,
                highlightcolor=self.accent_color
            )
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6)

            def paste_clipboard():
                try:
                    import win32clipboard as wcb
                    import win32con
                    wcb.OpenClipboard()
                    data = wcb.GetClipboardData(win32con.CF_UNICODETEXT)
                    wcb.CloseClipboard()
                    if data:
                        url_var.set(data.strip())
                        entry.icursor(tk.END)
                        validate_now()
                except Exception:
                    pass

            paste_btn = self.create_button(
                entry_frame,
                text="Paste",
                command=paste_clipboard,
                variant="secondary",
                size="sm"
            )
            paste_btn.pack(side=tk.LEFT, padx=(8, 0))

            validate_lbl = tk.Label(
                container,
                text="",
                font=self.small_font,
                bg=self.bg_color,
                fg="#e17055"
            )
            validate_lbl.pack(anchor="w", pady=(6, 0))

            btns = tk.Frame(container, bg=self.bg_color)
            btns.pack(anchor="e", pady=(14, 0))

            def validate_url(u: str) -> bool:
                if not u:
                    return False
                try:
                    return self.drive_manager is not None and (self.drive_manager._extract_id_and_type(u) is not None)
                except Exception:
                    return "drive.google.com" in u

            def validate_now():
                u = url_var.get().strip()
                if not u:
                    validate_lbl.config(text="Please enter a link.")
                    return False
                if not validate_url(u):
                    validate_lbl.config(text="This doesn't look like a public Google Drive link.")
                    return False
                validate_lbl.config(text="")
                return True

            def on_submit():
                if validate_now():
                    result["url"] = url_var.get().strip()
                    dlg.destroy()

            def on_cancel():
                result["url"] = None
                dlg.destroy()

            add_btn = self.create_button(
                btns,
                text="Add Link",
                command=on_submit,
                variant="primary",
                size="md"
            )
            add_btn.pack(side=tk.RIGHT, padx=(8, 0))

            cancel_btn = self.create_button(
                btns,
                text="Cancel",
                command=on_cancel,
                variant="secondary",
                size="md"
            )
            cancel_btn.pack(side=tk.RIGHT)

            try:
                import win32clipboard as wcb
                import win32con
                wcb.OpenClipboard()
                data = wcb.GetClipboardData(win32con.CF_UNICODETEXT)
                wcb.CloseClipboard()
                if data and ("drive.google.com" in data or "id=" in data):
                    url_var.set(data.strip())
                    entry.icursor(tk.END)
            except Exception:
                pass

            dlg.bind("<Return>", lambda _e: on_submit())
            dlg.bind("<Escape>", lambda _e: on_cancel())

            entry.focus_set()
            self.root.wait_window(dlg)
            return result["url"]

        def add_drive_link(self):
            if not self.drive_manager:
                messagebox.showerror("Google Drive", "Google Drive integration is unavailable.")
                return

            url = self._ask_drive_link_dialog()
            if not url:
                return

            self.update_console("Processing Google Drive link for streaming…")

            progress_window = tk.Toplevel(self.root)
            progress_window.title("Google Drive")
            progress_window.geometry("420x140")
            progress_window.configure(bg=self.bg_color)
            progress_window.transient(self.root)
            progress_window.grab_set()

            lbl = tk.Label(
                progress_window,
                text="Fetching contents… Large Drive folders can take a while…",
                font=self.normal_font,
                bg=self.bg_color,
                fg=self.text_color,
                wraplength=380,
                justify=tk.LEFT,
            )
            lbl.pack(padx=16, pady=(16, 8), anchor="w")

            bar = ttk.Progressbar(progress_window, mode='indeterminate', length=380)
            bar.pack(padx=16, pady=(0, 8))
            try:
                bar.start(10)
            except Exception:
                pass

            status_lbl = tk.Label(
                progress_window,
                text="Starting…",
                font=self.small_font,
                bg=self.bg_color,
                fg="#666666",
                wraplength=380,
                justify=tk.LEFT,
            )
            status_lbl.pack(padx=16, pady=(0, 8), anchor="w")

            try:
                if hasattr(self, 'add_drive_button') and self.add_drive_button:
                    self.add_drive_button.configure(state=tk.DISABLED)
            except Exception:
                pass

            def set_status(msg: str):
                try:
                    status_lbl.config(text=msg)
                    self.update_console(msg)
                except Exception:
                    pass

            def finish_cleanup():
                try:
                    bar.stop()
                except Exception:
                    pass
                try:
                    progress_window.destroy()
                except Exception:
                    pass
                try:
                    if hasattr(self, 'add_drive_button') and self.add_drive_button:
                        self.add_drive_button.configure(state=tk.NORMAL)
                except Exception:
                    pass

            try:
                source = self.drive_manager.make_source_from_url(url)
                if not source:
                    raise ValueError("Unrecognized Google Drive link.")
            except Exception as e:
                finish_cleanup()
                messagebox.showerror("Google Drive", str(e))
                self.update_console(f"Google Drive error: {e}")
                return

            def worker():
                try:
                    kind = source.get("kind")
                    if kind == "folder":
                        folder_id = source["id"]
                        pseudo_dir = f"gdrive://folder/{folder_id}"
                        # Duplicate check on UI thread state snapshot
                        if pseudo_dir in self.selected_dirs:
                            self.root.after(0, lambda: (set_status("Drive link already added."), finish_cleanup()))
                            return
                        self.root.after(0, lambda: set_status("Listing folder recursively…"))
                        videos, video_to_dir, directories = self.drive_manager.gather_videos_with_directories_for_source(
                            source)

                        def apply_folder():
                            self.scan_cache.set(pseudo_dir, (videos, video_to_dir, directories))
                            self.selected_dirs.append(pseudo_dir)
                            display_name = f"Drive Folder {folder_id}"
                            self.dir_listbox.insert(tk.END, display_name)
                            self.update_console(
                                f"Added Google Drive folder for streaming: {folder_id} with {len(videos)} videos")
                            self.update_video_count()
                            self.save_preferences()
                            finish_cleanup()

                        self.root.after(0, apply_folder)
                    else:
                        file_id = source["id"]
                        pseudo_dir = f"gdrive://file/{file_id}"
                        if pseudo_dir in self.selected_dirs:
                            self.root.after(0, lambda: (set_status("Drive link already added."), finish_cleanup()))
                            return
                        self.root.after(0, lambda: set_status("Preparing file stream…"))
                        videos, video_to_dir, directories = self.drive_manager.gather_videos_with_directories_for_source(
                            source)

                        def apply_file():
                            self.scan_cache.set(pseudo_dir, (videos, video_to_dir, directories))
                            self.selected_dirs.append(pseudo_dir)
                            display_name = f"Drive File {file_id}"
                            self.dir_listbox.insert(tk.END, display_name)
                            self.update_console(f"Added Google Drive file for streaming: {file_id}")
                            self.update_video_count()
                            self.save_preferences()
                            finish_cleanup()

                        self.root.after(0, apply_file)
                except Exception as e:
                    def on_err():
                        finish_cleanup()
                        messagebox.showerror("Google Drive", f"Failed to add link: {e}")
                        self.update_console(f"Google Drive error: {e}")

                    self.root.after(0, on_err)

            ManagedThread(target=worker, name="AddDriveLink").start()

        def _on_settings_changed(self, new_settings):
            self.update_console(f"Settings updated")

            if hasattr(self, 'video_preview_manager'):
                self.video_preview_manager.set_preview_duration(new_settings.preview_duration)
                self.video_preview_manager.set_video_preview_enabled(new_settings.use_video_preview)

            if hasattr(self, 'resume_manager'):
                self.resume_manager._auto_cleanup_days = new_settings.auto_cleanup_days

            # Live-reload hotkeys in any open EmbeddedPlayer window
            if getattr(self, '_active_player', None) is not None:
                try:
                    self._active_player.set_hotkeys(new_settings.hotkeys)
                except Exception as e:
                    self.update_console(f"Hotkey reload error: {e}")

            if hasattr(self, 'dual_player_manager'):
                # Player count per window is always 3; no need to call set_player_count.
                # Toggle Win 2 grid-view callbacks based on the dual_window_enabled setting.
                if new_settings.dual_window_enabled:
                    self.grid_view_manager.set_play_in_dual_player_win2_1_callback(
                        lambda videos: self.dual_player_manager.load_videos_into_slot(2, 1, videos)
                    )
                    self.grid_view_manager.set_play_in_dual_player_win2_2_callback(
                        lambda videos: self.dual_player_manager.load_videos_into_slot(2, 2, videos)
                    )
                    self.grid_view_manager.set_play_in_dual_player_win2_3_callback(
                        lambda videos: self.dual_player_manager.load_videos_into_slot(2, 3, videos)
                    )
                else:
                    self.grid_view_manager.set_play_in_dual_player_win2_1_callback(None)
                    self.grid_view_manager.set_play_in_dual_player_win2_2_callback(None)
                    self.grid_view_manager.set_play_in_dual_player_win2_3_callback(None)


        def _clear_thumbnail_cache(self):
            try:
                self.video_preview_manager.clear_cache()
                self.update_console(f"Thumbnail cache cleared.")
                return True
            except Exception as e:
                self.update_console(f"Error clearing thumbnail cache: {e}")
                return False

        def cancel(self):
            # Snapshot state from EmbeddedPlayer if one is open
            if self._active_player is not None:
                try:
                    p = self._active_player
                    self.last_played_video_index = p.index
                    self.last_played_video_path  = p.videos[p.index] if p.videos else ""
                    self.loop_mode               = p.loop_mode
                    self.volume                  = p.volume
                    self.is_muted                = p.is_muted
                    self.save_preferences()
                except Exception:
                    pass

            if self.controller:
                if self.start_from_last_played and hasattr(self.controller, 'index'):
                    self.last_played_video_index = self.controller.index
                    if self.controller.index < len(self.controller.videos):
                        self.last_played_video_path = self.controller.videos[self.controller.index]
                    self.save_preferences()

                self.controller.stop()
            # cleanup_hotkeys()
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

            try:
                self._cleanup_managers()
            except Exception:
                pass

            try:
                if hasattr(self, 'memory_monitor'):
                    self.memory_monitor.cleanup_if_needed()
                self.resource_manager.cleanup_all()
            except Exception:
                pass

            try:
                self.root.quit()
                self.root.destroy()
            except Exception:
                pass

            try:
                sys.exit(0)
            except:
                os._exit(0)

    root = TkinterDnD.Tk()
    app = DirectorySelector(root)
    root.mainloop()


if __name__ == "__main__":
    select_multiple_folders_and_play()