from embedded_player import EmbeddedPlayer
from icon_helper import apply_icon
from managers.annotation_browser_manager import AnnotationBrowserManager
from managers.video_metadata_manager import VideoAnnotationService
from splash import show_splash

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
            self.current_subdirs_mapping = {}  # iid -> path
            self.show_videos = True
            self.show_only_excluded = False
            self.search_query = ""
            self.expanded_paths = set()
            self.collapsed_paths = set()
            self.current_max_depth = 20
            self.loop_mode = "loop_on"
            self._active_player = None
            self._now_playing_video_path = None

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
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            restore_w = max(1280, int(sw * 0.75))
            restore_h = max(720, int(sh * 0.75))
            cx = (sw - restore_w) // 2
            cy = (sh - restore_h) // 2
            root.geometry(f"{restore_w}x{restore_h}+{cx}+{cy}")

            try:
                root.state('zoomed')
            except:
                pass

            root.minsize(900, 600)
            root.protocol("WM_DELETE_WINDOW", self.cancel)
            root.configure(bg=self.bg_color)
            apply_icon(root)

            try:
                self.drive_manager = GoogleDriveManager()
            except Exception as e:
                self.drive_manager = None
                self.update_console(f"Google Drive integration unavailable: {e}")

            self.setup_main_layout()
            self.setup_directory_section()
            self.setup_status_section()
            self.setup_console_section()
            self.setup_action_buttons()
            self.settings_manager = SettingsManager(self.root, self, self.update_console, enable_ai=False)
            self.setup_exclusion_section()

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

            self.annotation_service = VideoAnnotationService()
            self.annotation_service.subscribe(self._on_any_annotation_changed)

            self.annotation_browser = AnnotationBrowserManager(
                root=self.root,
                theme_provider=self,
                annotation_service=self.annotation_service,
                play_callback=self._play_annotated_videos,
                logger=self.update_console,
            )
            self.annotation_browser.set_video_preview_manager(self.video_preview_manager)
            self.annotation_browser.set_grid_view_manager(self.grid_view_manager)

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
            self.grid_view_manager.set_annotation_service(self.annotation_service)

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
                scroll_pos = self.exclusion_tree.yview()
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
                'video_preview_manager', 'grid_view_manager', 'playlist_manager',
                'watch_history_manager', 'queue_manager', 'favorites_manager',
                'filter_sort_manager', 'settings_manager', 'resume_manager',
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
                return {'total_entries': 0, 'cache_size_bytes': 0, 'cache_size_mb': 0, 'cache_file': ''}

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
            raw = event.data.strip()
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
            self.tree_font = Font(family="Segoe UI", size=10)
            self.tree_font_bold = Font(family="Segoe UI", size=10, weight="bold")
            self.tree_font_italic = Font(family="Segoe UI", size=10, slant="italic")

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
                parent, text=text, command=command, font=use_font,
                bg=bg, fg=fg, activebackground=active_bg, activeforeground=fg,
                relief=tk.FLAT, bd=0, padx=padx, pady=pady,
                cursor="hand2", highlightthickness=0
            )
            btn._variant = variant

            def on_enter(e): btn.configure(bg=active_bg)
            def on_leave(e): btn.configure(bg=bg)

            btn.bind("<Enter>", on_enter)
            btn.bind("<Leave>", on_leave)
            return btn

        def setup_main_layout(self):
            self._active_app_view = "home"
            self.embedded_view_frame = None
            self.main_frame = tk.Frame(self.root, bg=self.bg_color, padx=20, pady=20)
            self.main_frame.pack(fill=tk.BOTH, expand=True)
            self.content_frame = tk.Frame(self.main_frame, bg=self.bg_color)
            self.content_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        def _ensure_embedded_view_frame(self):
            if self.embedded_view_frame and self.embedded_view_frame.winfo_exists():
                return self.embedded_view_frame
            self.embedded_view_frame = tk.Frame(self.root, bg=self.bg_color)
            return self.embedded_view_frame

        def _show_home_view(self):
            if self.embedded_view_frame and self.embedded_view_frame.winfo_exists():
                self.embedded_view_frame.pack_forget()
                for child in self.embedded_view_frame.winfo_children():
                    child.destroy()
            if not self.main_frame.winfo_ismapped():
                self.main_frame.pack(fill=tk.BOTH, expand=True)
            self._active_app_view = "home"
            self._refresh_media_pill_state()

        def _show_embedded_view(self, view_name, builder):
            self.main_frame.pack_forget()
            frame = self._ensure_embedded_view_frame()
            frame.configure(bg=self.bg_color)
            frame.pack(fill=tk.BOTH, expand=True)
            for child in frame.winfo_children():
                child.destroy()
            self._active_app_view = view_name
            self._refresh_media_pill_state()
            builder(frame)

        def _refresh_media_pill_state(self):
            if not hasattr(self, "_media_pill_btns") or not hasattr(self, "_tb_colors"):
                return
            active_label = getattr(self, "_view_tab_labels", {}).get(getattr(self, "_active_app_view", "home"))
            for label, btn in self._media_pill_btns.items():
                try:
                    a = self.pill_accents(label)
                    if label == active_label:
                        btn.config(bg=a[1], fg=a[2], highlightbackground=a[1])
                    else:
                        cc = self._tb_colors()
                        btn.config(bg=cc["bg"], fg=a[0], highlightbackground=a[0])
                except Exception:
                    pass

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
                console_header_frame, text="Clear", command=self.clear_console,
                variant="dark", size="sm"
            )
            self.clear_console_button.pack(side=tk.LEFT, padx=(10, 0), anchor='w')

            console_container = tk.Frame(console_section, bg=self.bg_color,
                                         highlightbackground="#cccccc", highlightthickness=1)
            console_container.pack(fill=tk.X, pady=(0, 10))

            console_frame = tk.Frame(console_container, bg=self.bg_color)
            console_frame.pack(fill=tk.BOTH, expand=True)

            self.console_scrollbar = tk.Scrollbar(console_frame)
            self.console_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            self.console_text = tk.Text(
                console_frame, height=10, wrap=tk.WORD,
                yscrollcommand=self.console_scrollbar.set,
                font=self.mono_font, bg="#2c3e50", fg="#ecf0f1",
                insertbackground="#ecf0f1", selectbackground="#34495e",
                selectforeground="#ecf0f1", relief=tk.FLAT, bd=0,
                padx=10, pady=10, state=tk.DISABLED
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
                self.console_text.insert(tk.END, f"[{timestamp}] {message}\n")
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
            try:
                self._view_menu.entryconfig(0, label="Hide Console" if self.show_console else "Show Console")
            except Exception:
                pass
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

        def apply_theme(self):
            dir_w = self.dir_section.winfo_width() if hasattr(self, 'dir_section') else 0
            exc_w = self.exclusion_section.winfo_width() if hasattr(self, 'exclusion_section') else 0

            super().apply_theme()

            self._reapply_tree_columns()

            style = ttk.Style()
            style.configure("ExclusionTree.Treeview.Heading",
                            background=self.bg_color,
                            foreground=self.text_color,
                            relief="flat",
                            borderwidth=1)
            style.map("ExclusionTree.Treeview.Heading",
                      background=[('active', self.bg_color), ('pressed', self.bg_color), ('focus', self.bg_color)],
                      foreground=[('active', self.text_color), ('pressed', self.text_color),
                                  ('focus', self.text_color)])

            if dir_w > 10 and exc_w > 10:
                self.dir_section.config(width=dir_w)
                self.exclusion_section.config(width=exc_w)
                self.dir_section.pack_propagate(False)
                self.exclusion_section.pack_propagate(False)

        def _reapply_tree_columns(self):
            """Reconfigure treeview columns (preserves size column, toggles annotation columns)."""
            if not hasattr(self, 'exclusion_tree'):
                return
            show_ann = self.settings_manager.get_settings().show_video_annotations_in_tree

            if show_ann:
                self.exclusion_tree.configure(columns=("rating", "tags", "size"))
                self.exclusion_tree.column("rating", width=100, minwidth=100, stretch=False, anchor="center")
                self.exclusion_tree.column("tags", width=180, minwidth=120, stretch=False, anchor="w")
                self.exclusion_tree.column("size", width=90, minwidth=90, stretch=False, anchor="e")
                self.exclusion_tree.heading("rating", text="Rating", anchor="center")
                self.exclusion_tree.heading("tags", text="Tags", anchor="w")
                self.exclusion_tree.heading("size", text="Size", anchor="e")
            else:
                self.exclusion_tree.configure(columns=("size",))
                self.exclusion_tree.column("size", width=90, minwidth=90, stretch=False, anchor="e")
                self.exclusion_tree.heading("size", text="Size", anchor="e")

            # Name column (always present)
            self.exclusion_tree.column("#0", width=400, minwidth=200, stretch=True, anchor="w")
            self.exclusion_tree.heading("#0", text="Name", anchor="w")

        def setup_directory_section(self):
            self.dir_section = tk.Frame(self.content_frame, bg=self.bg_color)
            self.dir_section.pack(side=tk.LEFT, fill=tk.Y, expand=False, padx=(0, 10))
            self.dir_section.config(width=550)
            self.dir_section.pack_propagate(False)

            dir_header = tk.Label(self.dir_section, text="Selected Directories",
                                  font=self.header_font, bg=self.bg_color, fg=self.text_color)
            dir_header.pack(anchor='w', pady=(0, 10))

            self.dir_frame = tk.Frame(self.dir_section, bg=self.bg_color)
            self.dir_frame.pack(fill=tk.BOTH, expand=True)

            list_container = tk.Frame(self.dir_frame, bg=self.bg_color,
                                      highlightbackground="#cccccc", highlightthickness=1)
            list_container.pack(fill=tk.BOTH, expand=True)

            self.scrollbar = tk.Scrollbar(list_container)
            self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            self.dir_listbox = tk.Listbox(
                list_container, selectmode=tk.EXTENDED,
                yscrollcommand=self.scrollbar.set,
                font=self.normal_font, bg="white", fg=self.text_color,
                selectbackground=self.accent_color, selectforeground="white",
                activestyle="none", relief=tk.FLAT, highlightthickness=1,
                highlightbackground="#e0e0e0", bd=0
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

        def on_directory_focus_out(self, event):
            selection = self.dir_listbox.curselection()
            if selection:
                self.current_selected_dir_index = selection[0]

        def on_directory_focus_in(self, event):
            if self.current_selected_dir_index is not None and self.current_selected_dir_index < self.dir_listbox.size():
                self.dir_listbox.selection_clear(0, tk.END)
                self.dir_listbox.selection_set(self.current_selected_dir_index)
                self.dir_listbox.activate(self.current_selected_dir_index)

        # ------------------------------------------------------------------
        # Treeview setup — replaces tk.Listbox for the exclusion panel
        # ------------------------------------------------------------------

        def _configure_tree_style(self):
            """
            Build the ttk.Style entries that drive Treeview row appearance.
            Called once during setup and again on every theme change.
            """
            style = ttk.Style()
            is_dark = self.dark_mode

            tree_bg       = getattr(self, 'listbox_bg',  "#313335" if is_dark else "white")
            tree_fg       = getattr(self, 'listbox_fg',  "#A9B7C6" if is_dark else "#333333")
            tree_sel_bg   = "#CC7832"
            tree_sel_fg   = "white"
            heading_bg    = getattr(self, 'bg_color',    "#2B2B2B" if is_dark else "#f5f5f5")
            heading_fg    = getattr(self, 'text_color',  "#A9B7C6" if is_dark else "#333333")
            odd_row_bg    = getattr(self, 'alt_row_color', "#313335" if is_dark else "#ebebeb")

            style.configure(
                "ExclusionTree.Treeview",
                background=tree_bg,
                foreground=tree_fg,
                fieldbackground=tree_bg,
                rowheight=26,
                font=self.tree_font,
                borderwidth=0,
                relief="flat",
            )
            try:
                style.element_create("ExclusionTree.treearea", "from", "default")
            except Exception:
                pass
            style.layout("ExclusionTree.Treeview", [
                ("ExclusionTree.Treeview.treearea", {"sticky": "nswe"})
            ])
            try:
                style.element_create("ExclusionTree.Heading.border", "from", "clam", "Heading.border")
            except Exception:
                pass
            style.layout("ExclusionTree.Treeview.Heading", [
                ("ExclusionTree.Heading.border", {"sticky": "nswe", "children": [
                    ("Treeview.Heading.padding", {"sticky": "nswe", "children": [
                        ("Treeview.Heading.image", {"side": "right", "sticky": ""}),
                        ("Treeview.Heading.label", {"sticky": "we"})
                    ]})
                ]})
            ])
            style.configure(
                "ExclusionTree.Treeview.Heading",
                background=heading_bg,
                foreground=heading_fg,
                relief="flat",
                borderwidth=1,
            )
            style.map(
                "ExclusionTree.Treeview",
                background=[("selected", tree_sel_bg)],
                foreground=[("selected", tree_sel_fg)],
            )

            # Per-row tags — applied via tree.tag_configure()
            fav_gold    = "#d4a017" if not is_dark else "#FFD700"
            excl_red    = "#c0392b" if not is_dark else "#E06862"
            play_green  = "#1a7a3a" if not is_dark else "#4CAF50"
            play_bg     = "#d4edda" if not is_dark else "#1b3a24"
            folder_blue = "#1a5fa8" if not is_dark else "#4A9EFF"
            muted       = "#999999" if not is_dark else "#666666"
            rating_gold = "#c8a000" if not is_dark else "#f5c518"
            tag_blue = "#1a6dc8" if not is_dark else "#4A9EFF"
            bm_teal = "#1a7a6e" if not is_dark else "#4fd1c5"

            self.exclusion_tree.tag_configure("folder",          foreground=folder_blue, font=self.tree_font_bold)
            self.exclusion_tree.tag_configure("folder_excl",     foreground=excl_red,   font=self.tree_font_bold)
            self.exclusion_tree.tag_configure("video",           foreground=tree_fg,    font=self.tree_font)
            self.exclusion_tree.tag_configure("video_fav",       foreground=fav_gold,   font=self.tree_font_bold)
            self.exclusion_tree.tag_configure("video_excl",      foreground=muted,      font=self.tree_font_italic)
            self.exclusion_tree.tag_configure("video_fav_excl",  foreground=muted,      font=self.tree_font_italic)
            self.exclusion_tree.tag_configure("now_playing",     foreground=play_green, font=self.tree_font_bold,
                                              background=play_bg)
            self.exclusion_tree.tag_configure("placeholder",     foreground=muted,      font=self.tree_font_italic)
            self.exclusion_tree.tag_configure("ann_rating", foreground=rating_gold)
            self.exclusion_tree.tag_configure("ann_tag", foreground=tag_blue)
            self.exclusion_tree.tag_configure("ann_bookmark", foreground=bm_teal)

        def setup_exclusion_section(self):
            self.exclusion_section = tk.Frame(self.content_frame, bg=self.bg_color)
            self.exclusion_section.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))

            exclusion_header_frame = tk.Frame(self.exclusion_section, bg=self.bg_color)
            exclusion_header_frame.pack(fill=tk.X, pady=(0, 10))

            exclusion_header = tk.Label(exclusion_header_frame, text="Subdirectories and Videos",
                                        font=self.header_font, bg=self.bg_color, fg=self.text_color)
            exclusion_header.pack(side=tk.LEFT, anchor='w')

            self.video_count_label = tk.Label(
                exclusion_header_frame, text="  —  0 videos",
                font=self.normal_font, bg=self.bg_color, fg="#888888"
            )
            self.video_count_label.pack(side=tk.LEFT, anchor='w')

            self.selected_dir_label = tk.Label(
                self.exclusion_section,
                text="Select a directory to see its folders and videos",
                font=self.small_font, bg=self.bg_color, fg="#666666"
            )
            self.selected_dir_label.pack(anchor='w', pady=(0, 10))

            self.search_frame = tk.Frame(self.exclusion_section, bg=self.bg_color)
            self.search_frame.pack(fill=tk.X, pady=(0, 10))

            search_label = tk.Label(self.search_frame, text="Search:",
                                    font=self.small_font, bg=self.bg_color, fg=self.text_color)
            search_label.pack(side=tk.LEFT, padx=(0, 5))

            self.search_entry = tk.Entry(
                self.search_frame, font=self.normal_font, bg="white", fg=self.text_color,
                relief=tk.FLAT, bd=1, highlightthickness=1, highlightbackground="#e0e0e0"
            )
            self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
            self.search_entry.bind('<KeyRelease>', self.on_search_changed)

            clear_search_btn = self.create_button(
                self.search_frame, text="Clear", command=self.clear_search,
                variant="secondary", size="sm"
            )
            clear_search_btn.pack(side=tk.LEFT)

            # ── Treeview container ─────────────────────────────────────────────
            self.exclusion_frame = tk.Frame(self.exclusion_section, bg=self.bg_color)
            self.exclusion_frame.pack(fill=tk.BOTH, expand=True)

            exclusion_container = tk.Frame(
                self.exclusion_frame, bg=self.bg_color,
                highlightbackground="#cccccc", highlightthickness=1
            )
            exclusion_container.pack(fill=tk.BOTH, expand=True)

            # Scrollbars
            self.exclusion_scrollbar = ttk.Scrollbar(exclusion_container, orient=tk.VERTICAL)
            self.exclusion_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            # Treeview
            self.exclusion_tree = ttk.Treeview(
                exclusion_container,
                style="ExclusionTree.Treeview",
                selectmode="extended",
                show="tree headings",
                columns=("rating", "tags", "size"),
                yscrollcommand=self.exclusion_scrollbar.set,
            )

            self.exclusion_scrollbar.config(command=self.exclusion_tree.yview)

            show_ann = self.settings_manager.get_settings().show_video_annotations_in_tree

            if show_ann:
                self.exclusion_tree.configure(columns=("rating", "tags", "size"))
                self.exclusion_tree.column("rating", width=100, minwidth=100, stretch=False, anchor="center")
                self.exclusion_tree.column("tags", width=180, minwidth=120, stretch=False, anchor="w")
                self.exclusion_tree.column("size", width=90, minwidth=90, stretch=False, anchor="e")
                self.exclusion_tree.heading("rating", text="Rating", anchor="center")
                self.exclusion_tree.heading("tags", text="Tags", anchor="w")
                self.exclusion_tree.heading("size", text="Size", anchor="e")
            else:
                self.exclusion_tree.configure(columns=("size",))
                self.exclusion_tree.column("size", width=90, minwidth=90, stretch=False, anchor="e")
                self.exclusion_tree.heading("size", text="Size", anchor="e")

            self.exclusion_tree.column("#0", width=400, minwidth=200, stretch=True, anchor="w")
            self.exclusion_tree.heading("#0", text="Name", anchor="w")

            # Tag for rating stars (yellow)
            self.exclusion_tree.tag_configure("rating_star", foreground="#f5c518")

            self.exclusion_tree.pack(fill=tk.BOTH, expand=True)

            # Bind events
            self._selection_anchor = None
            self.exclusion_tree.bind("<Button-1>", self._on_left_click)
            self.exclusion_tree.bind("<Double-Button-1>", self._on_double_click)
            self.exclusion_tree.bind("<Button-3>", self._show_context_menu)
            self.exclusion_tree.bind("<<TreeviewOpen>>", self._on_tree_open)
            self.exclusion_tree.bind("<<TreeviewClose>>", self._on_tree_close)
            self.exclusion_tree.bind("<Control-a>",
                                     lambda e: (self.exclusion_tree.selection_set(self._tree_get_all_iids()), "break")[
                                         1])
            self.exclusion_tree.bind("<Control-A>",
                                     lambda e: (self.exclusion_tree.selection_set(self._tree_get_all_iids()), "break")[
                                         1])
            self.exclusion_tree.bind("<Delete>", self._on_key_toggle_exclusion)
            self.exclusion_tree.bind("<space>", self._on_key_toggle_exclusion)

            # ── Checkboxes row ────────────────────────────────────────────────
            self.exclusion_buttons_frame = tk.Frame(self.exclusion_section, bg=self.bg_color)
            self.exclusion_buttons_frame.pack(fill=tk.X, pady=(10, 0))

            checkboxes_row = tk.Frame(self.exclusion_buttons_frame, bg=self.bg_color)
            checkboxes_row.pack(fill=tk.X, pady=(0, 5))

            self.show_videos_var = tk.BooleanVar(value=self.show_videos)
            self.excluded_only_var = tk.BooleanVar(value=self.show_only_excluded)
            self.expand_all_var = tk.BooleanVar(value=self.expand_all_default)
            self.save_directories_var = tk.BooleanVar(value=self.save_directories)

            self.toggle_videos_check = ttk.Checkbutton(
                checkboxes_row, text="Show Videos",
                style="Modern.TCheckbutton", variable=self.show_videos_var,
                command=self.toggle_videos_visibility
            )
            self.toggle_videos_check.pack(side=tk.LEFT, padx=(0, 10))

            self.expand_all_check = ttk.Checkbutton(
                checkboxes_row, text="Expand All",
                style="Modern.TCheckbutton", variable=self.expand_all_var,
                command=self.toggle_expand_all
            )
            self.expand_all_check.pack(side=tk.LEFT, padx=(0, 10))

            self.toggle_excluded_only_check = ttk.Checkbutton(
                checkboxes_row, text="Excluded Only",
                style="Modern.TCheckbutton", variable=self.excluded_only_var,
                command=self.toggle_excluded_only
            )
            self.toggle_excluded_only_check.pack(side=tk.LEFT, padx=(0, 10))

            self.save_directories_check = ttk.Checkbutton(
                checkboxes_row, text="Save Directories",
                style="Modern.TCheckbutton", variable=self.save_directories_var,
                command=self.toggle_save_directories
            )
            self.save_directories_check.pack(side=tk.LEFT, padx=(0, 10))

            self.smart_resume_var = tk.BooleanVar(value=self.smart_resume_enabled)
            self.speed_var = tk.DoubleVar(value=1.0)

        # ------------------------------------------------------------------
        # Treeview expand/collapse event handlers
        # ------------------------------------------------------------------

        def _get_video_size_str(self, path):
            try:
                size = os.path.getsize(path)
                if size >= 1024 ** 3:
                    return f"{size / 1024 ** 3:.2f} GB"
                elif size >= 1024 ** 2:
                    return f"{size / 1024 ** 2:.1f} MB"
                else:
                    return f"{size // 1024} KB"
            except:
                return ""

        def _get_rating_stars(self, path):
            rating = self.annotation_service.get_rating(path)
            return "★" * rating + "☆" * (5 - rating)

        def _get_tags_str(self, path):
            tags = self.annotation_service.get_tags(path)
            return " ".join(f"#{t}" for t in tags[:5]) + (" …" if len(tags) > 5 else "")

        def _fmt_ms(self, ms: int) -> str:
            s = ms // 1000
            h, r = divmod(s, 3600)
            m, sec = divmod(r, 60)
            return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

        def _refresh_video_row(self, path):
            """Update the tree row for a specific video path without reloading everything."""
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                return
            excluded_dir_set = set(os.path.normpath(p) for p in self.excluded_subdirs.get(selected_dir, []))
            excluded_vid_set = set(os.path.normpath(p) for p in self.excluded_videos.get(selected_dir, []))
            for iid, p in self.current_subdirs_mapping.items():
                if os.path.normpath(p) == os.path.normpath(path):
                    size_str = self._get_video_size_str(path)
                    rating_str = self._get_rating_stars(path)
                    tags_str = self._get_tags_str(path)
                    # Update columns
                    self.exclusion_tree.item(iid, values=(rating_str, tags_str, size_str))
                    # Update tag and label for now‑playing / fav / excl
                    tag = self._tag_for_item(path, selected_dir, excluded_dir_set, excluded_vid_set)
                    label = self._label_for_item(path, False, excluded_dir_set, excluded_vid_set, selected_dir)
                    self.exclusion_tree.item(iid, text=label, tags=(tag,))
                    break

        def _on_tree_open(self, event):
            iid = self.exclusion_tree.focus()
            path = self.current_subdirs_mapping.get(iid)
            if path:
                norm = os.path.normpath(path)
                self.expanded_paths.add(norm)
                self.collapsed_paths.discard(norm)

        def _on_tree_close(self, event):
            iid = self.exclusion_tree.focus()
            path = self.current_subdirs_mapping.get(iid)
            if path:
                norm = os.path.normpath(path)
                self.collapsed_paths.add(norm)
                self.expanded_paths.discard(norm)

        # ------------------------------------------------------------------
        # Selection helpers — mirror the old curselection() API
        # ------------------------------------------------------------------

        def _tree_selection_indices(self):
            """Return list of selected iids."""
            return list(self.exclusion_tree.selection())

        def _tree_get_all_iids(self):
            """Return all top-level and child iids in display order."""
            result = []
            def _walk(parent):
                for iid in self.exclusion_tree.get_children(parent):
                    result.append(iid)
                    _walk(iid)
            _walk("")
            return result

        def _tree_size(self):
            return len(self._tree_get_all_iids())

        def _tree_yview(self):
            return self.exclusion_tree.yview()

        def _tree_yview_moveto(self, fraction):
            try:
                self.exclusion_tree.yview_moveto(fraction)
            except Exception:
                pass

        # ------------------------------------------------------------------
        # Click / double-click on Treeview
        # ------------------------------------------------------------------

        def _on_left_click(self, event):
            iid = self.exclusion_tree.identify_row(event.y)
            region = self.exclusion_tree.identify_region(event.x, event.y)

            # Clicking the expand/collapse arrow — let Treeview handle it
            if region == "tree":
                return

            if not iid:
                self.exclusion_tree.selection_remove(self.exclusion_tree.selection())
                self._selection_anchor = None
                return

            ctrl_held  = bool(event.state & 0x4)
            shift_held = bool(event.state & 0x1)
            current    = list(self.exclusion_tree.selection())

            if shift_held:
                if self._selection_anchor is None:
                    self._selection_anchor = current[0] if current else iid
                all_iids = self._tree_get_all_iids()
                try:
                    a = all_iids.index(self._selection_anchor)
                    b = all_iids.index(iid)
                except ValueError:
                    a = b = 0
                start, end = min(a, b), max(a, b)
                self.exclusion_tree.selection_set(all_iids[start:end + 1])
                return "break"

            if ctrl_held:
                if iid in current:
                    self.exclusion_tree.selection_remove(iid)
                else:
                    self.exclusion_tree.selection_add(iid)
                self._selection_anchor = iid
                return "break"

            self.exclusion_tree.selection_set(iid)
            self._selection_anchor = iid
            return "break"

        def _on_key_toggle_exclusion(self, event):
            selection = list(self.exclusion_tree.selection())
            if not selection:
                return "break"
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                return "break"
            excluded_dir_set = set(os.path.normpath(p) for p in self.excluded_subdirs.get(selected_dir, []))
            sel_paths = [self.current_subdirs_mapping.get(iid) for iid in selection]
            sel_paths = [p for p in sel_paths if p]
            has_non_excluded = any(
                not (self.is_video_excluded(selected_dir, p) if os.path.isfile(p) else os.path.normpath(
                    p) in excluded_dir_set)
                for p in sel_paths
            )
            if has_non_excluded:
                self.exclude_subdirectories()
            else:
                self.include_subdirectories()
            return "break"

        def _on_double_click(self, event):
            iid = self.exclusion_tree.identify_row(event.y)
            if not iid:
                return

            target_path = self.current_subdirs_mapping.get(iid)
            if not target_path:
                return

            is_filtered_mode = getattr(self, '_is_filtered_mode', False)

            if is_filtered_mode:
                if os.path.isfile(target_path) and is_video(target_path):
                    self.exclusion_tree.selection_set(iid)
                    self.root.after(100, lambda p=target_path: self._play_from_double_click(p))
                return "break"

            if os.path.isdir(target_path):
                # toggle expand/collapse
                norm_target = os.path.normpath(target_path)
                if self.exclusion_tree.item(iid, "open"):
                    self.exclusion_tree.item(iid, open=False)
                    self.collapsed_paths.add(norm_target)
                    self.expanded_paths.discard(norm_target)
                else:
                    self.exclusion_tree.item(iid, open=True)
                    self.expanded_paths.add(norm_target)
                    self.collapsed_paths.discard(norm_target)
                return "break"

            if not os.path.isfile(target_path) or not is_video(target_path):
                return

            self.exclusion_tree.selection_set(iid)
            self.root.after(100, lambda: self._play_from_double_click(target_path))
            return "break"

        # ------------------------------------------------------------------
        # Context menu
        # ------------------------------------------------------------------

        def _make_context_menu(self):
            if self.dark_mode:
                return tk.Menu(self.root, tearoff=0,
                               bg="#313335", fg="#A9B7C6",
                               activebackground="#2D5A8E", activeforeground="#FFFFFF",
                               relief="flat", bd=1, font=("Segoe UI", 9))
            else:
                return tk.Menu(self.root, tearoff=0,
                               bg="#f5f5f5", fg="#333333",
                               activebackground="#3498db", activeforeground="#FFFFFF",
                               relief="flat", bd=1, font=("Segoe UI", 9))

        def _tree_remove_annotation(self, paths, rating=False, tags=False, tag=None, bookmarks=False):
            for p in paths:
                if rating:
                    self.annotation_service.set_rating(p, 0)
                if tags:
                    for t in list(self.annotation_service.get_tags(p)):
                        self.annotation_service.remove_tag(p, t)
                if tag:
                    self.annotation_service.remove_tag(p, tag)
                if bookmarks:
                    for bm in list(self.annotation_service.get_bookmarks(p)):
                        self.annotation_service.remove_bookmark(p, bm["ms"])
            selected_dir = self.get_current_selected_directory()
            if selected_dir:
                self.load_subdirectories(selected_dir)

        def _set_rating_for_path(self, path, rating):
            self.annotation_service.set_rating(path, rating)
            self._refresh_video_row(path)

        def _remove_tag_from_path(self, path, tag):
            self.annotation_service.remove_tag(path, tag)
            self._refresh_video_row(path)

        def _remove_bookmark_from_path(self, path, ms):
            self.annotation_service.remove_bookmark(path, ms)
            self._refresh_video_row(path)

        def _add_current_bookmark(self, path):
            if self._active_player and hasattr(self._active_player, 'current_time_ms'):
                ms = self._active_player.current_time_ms()
                if ms is not None:
                    self.annotation_service.add_bookmark(path, ms)
                    self._refresh_video_row(path)
                    self.update_console(f"Bookmark added at {self._fmt_ms(ms)}")

        def _on_any_annotation_changed(self):
            # Refresh only visible rows (performance)
            if hasattr(self, 'current_subdirs_mapping'):
                for iid, path in list(self.current_subdirs_mapping.items()):
                    if os.path.isfile(path):
                        self._refresh_video_row(path)

        def _show_context_menu(self, event):
            iid = self.exclusion_tree.identify_row(event.y)
            selection = list(self.exclusion_tree.selection())

            if iid and iid not in selection:
                path = self.current_subdirs_mapping.get(iid)
                if path and os.path.isfile(path) and is_video(path):
                    self.video_preview_manager.right_clicked_item = iid
                    self.video_preview_manager._show_video_preview(path, event.x_root, event.y_root)
                    return
                # Non-video unselected row: select it then show menu
                self.exclusion_tree.selection_set(iid)
                selection = [iid]

            if not selection:
                # Right-click on empty space → show tooltip for nearest video
                if iid:
                    path = self.current_subdirs_mapping.get(iid)
                    if path and os.path.isfile(path) and is_video(path):
                        self.video_preview_manager.right_clicked_item = iid
                        self.video_preview_manager._show_video_preview(path, event.x_root, event.y_root)
                return

            first_iid  = selection[0]
            first_path = self.current_subdirs_mapping.get(first_iid)

            context_menu = self._make_context_menu()
            context_menu.add_command(label="Play Selected", command=self.play_selected_videos)
            context_menu.add_separator()

            total_items    = self._tree_size()
            selected_count = len(selection)

            if selected_count < total_items:
                context_menu.add_command(label="Select All",
                    command=lambda: self.exclusion_tree.selection_set(self._tree_get_all_iids()))
            if selected_count > 0:
                context_menu.add_command(label="Unselect All",
                    command=lambda: self.exclusion_tree.selection_remove(self._tree_get_all_iids()))

            context_menu.add_separator()
            context_menu.add_command(label="Open in Grid View",
                command=lambda: self._context_open_grid_view(selection))

            selected_dir = self.get_current_selected_directory()
            excluded_dir_set = set(os.path.normpath(p) for p in self.excluded_subdirs.get(selected_dir, [])) if selected_dir else set()

            sel_paths = [self.current_subdirs_mapping.get(iid) for iid in selection]
            sel_paths = [p for p in sel_paths if p]

            has_non_excluded = any(
                not (self.is_video_excluded(selected_dir, p) if (selected_dir and os.path.isfile(p)) else os.path.normpath(p) in excluded_dir_set)
                for p in sel_paths
            )
            has_excluded = any(
                (self.is_video_excluded(selected_dir, p) if (selected_dir and os.path.isfile(p)) else os.path.normpath(p) in excluded_dir_set)
                for p in sel_paths
            )

            sel_video_paths = [p for p in sel_paths if os.path.isfile(p) and is_video(p)]
            has_non_fav_videos = (selected_dir and hasattr(self, 'favorites_manager') and sel_video_paths and
                any(not self.favorites_manager.is_favorite(p, selected_dir) for p in sel_video_paths))
            has_fav = (selected_dir and hasattr(self, 'favorites_manager') and sel_video_paths and
                any(self.favorites_manager.is_favorite(p, selected_dir) for p in sel_video_paths))

            context_menu.add_separator()
            if has_non_excluded:
                context_menu.add_command(label="Exclude Selected", command=self.exclude_subdirectories)
            if has_excluded:
                context_menu.add_command(label="Include Selected", command=self.include_subdirectories)
            context_menu.add_command(label="Exclude All",       command=self.exclude_all_subdirectories)
            context_menu.add_command(label="Clear All Exclusions", command=self.clear_all_exclusions)

            context_menu.add_separator()
            context_menu.add_command(label="🎵 Add to Playlist",
                command=lambda: self._context_add_to_playlist(selection))
            if has_non_fav_videos:
                context_menu.add_command(label="⭐ Add to Favorites",
                    command=lambda: self._context_add_to_favorites(selection))
            if has_fav:
                context_menu.add_command(label="★ Remove from Favorites",
                    command=lambda: self._context_remove_from_favorites(selection))

            context_menu.add_separator()
            context_menu.add_command(label="Add to Queue",
                command=lambda: self._context_add_to_queue(selection, mode="queue"))
            context_menu.add_command(label="Play Next",
                command=lambda: self._context_add_to_queue(selection, mode="next"))

            context_menu.add_separator()
            context_menu.add_command(label="▶ Win 1 › Player 1",
                command=lambda: self._context_play_in_dual_player(selection, win_id=1, slot=1))
            context_menu.add_command(label="▶ Win 1 › Player 2",
                command=lambda: self._context_play_in_dual_player(selection, win_id=1, slot=2))
            context_menu.add_command(label="▶ Win 1 › Player 3",
                command=lambda: self._context_play_in_dual_player(selection, win_id=1, slot=3))

            if (getattr(self, 'settings_manager', None) and
                    self.settings_manager.get_settings().dual_window_enabled):
                context_menu.add_separator()
                context_menu.add_command(label="▶ Win 2 › Player 1",
                    command=lambda: self._context_play_in_dual_player(selection, win_id=2, slot=1))
                context_menu.add_command(label="▶ Win 2 › Player 2",
                    command=lambda: self._context_play_in_dual_player(selection, win_id=2, slot=2))
                context_menu.add_command(label="▶ Win 2 › Player 3",
                    command=lambda: self._context_play_in_dual_player(selection, win_id=2, slot=3))

            context_menu.add_separator()
            context_menu.add_command(
                label=f"Copy ({len(selection)} item{'s' if len(selection) > 1 else ''})",
                command=lambda: self._context_copy_selected(selection))

            if len(selection) == 1 and first_path and os.path.isfile(first_path):
                context_menu.add_command(label="Copy Path",
                    command=lambda: self._context_copy_path(first_path))
                context_menu.add_command(label="Open File Location",
                    command=lambda: self._context_open_location(first_path))
                context_menu.add_command(label="Properties",
                    command=lambda: self._context_show_properties(first_path))

            if len(selection) == 1 and first_path and os.path.isdir(first_path):
                context_menu.add_command(label="Open Folder Location",
                                         command=lambda: self._context_open_folder_location(first_path))
                context_menu.add_command(label="Properties",
                                         command=lambda: self._context_show_folder_properties(first_path))

            if first_path and os.path.isfile(first_path):
                show_ann = self.settings_manager.get_settings().show_video_annotations_in_tree
                if show_ann:
                    context_menu.add_separator()
                    rating = self.annotation_service.get_rating(first_path)
                    tags = self.annotation_service.get_tags(first_path)
                    bookmarks = self.annotation_service.get_bookmarks(first_path)
                    if rating > 0:
                        context_menu.add_command(
                            label="☆ Remove Rating",
                            command=lambda p=first_path: self._set_rating_for_path(p, 0)
                        )
                    if tags:
                        context_menu.add_command(
                            label="🏷 Remove All Tags",
                            command=lambda p=first_path: self._remove_all_tags_from_path(p)
                        )
                    if bookmarks:
                        context_menu.add_command(
                            label="🔖 Remove All Bookmarks",
                            command=lambda p=first_path: self._remove_all_bookmarks_from_path(p)
                        )

            try:
                context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                context_menu.grab_release()
                try:
                    self.root.after(100, lambda: context_menu.destroy())
                except:
                    pass

        def _remove_all_tags_from_path(self, path):
            for tag in list(self.annotation_service.get_tags(path)):
                self.annotation_service.remove_tag(path, tag)
            self._refresh_video_row(path)

        def _remove_all_bookmarks_from_path(self, path):
            for bm in list(self.annotation_service.get_bookmarks(path)):
                self.annotation_service.remove_bookmark(path, bm["ms"])
            self._refresh_video_row(path)

        # ------------------------------------------------------------------
        # Tree population — replaces load_subdirectories
        # ------------------------------------------------------------------

        def _tag_for_item(self, path, base, excluded_dir_set, excluded_vid_set, is_now_playing=False):
            """Return the correct Treeview tag string for a path."""
            if os.path.isdir(path):
                norm = os.path.normpath(path)
                return "folder_excl" if norm in excluded_dir_set else "folder"

            # It is a video file
            is_excl = path in excluded_vid_set or self.is_video_excluded(base, path)
            is_fav  = (hasattr(self, 'favorites_manager') and
                       self.favorites_manager.is_favorite(path, base))
            is_now  = is_now_playing or (
                getattr(self, '_now_playing_video_path', None) is not None
                and os.path.normpath(path) == self._now_playing_video_path
            )

            if is_now:
                return "now_playing"
            if is_excl and is_fav:
                return "video_fav_excl"
            if is_excl:
                return "video_excl"
            if is_fav:
                return "video_fav"
            return "video"

        def _label_for_item(self, path, is_dir, excluded_dir_set, excluded_vid_set, base=None):
            """Return the display text for a tree row."""
            name = os.path.basename(path) if path != os.path.normpath(path) else os.path.basename(path)

            if is_dir:
                norm = os.path.normpath(path)
                prefix = "📁 "
                suffix = "  ⊘ excluded" if norm in excluded_dir_set else ""
                return f"{prefix}{name}{suffix}"

            # video
            is_excl = path in excluded_vid_set
            is_fav  = (hasattr(self, 'favorites_manager') and
                       self.favorites_manager.is_favorite(path, base if base else os.path.dirname(path)))
            is_now  = (
                getattr(self, '_now_playing_video_path', None) is not None
                and os.path.normpath(path) == self._now_playing_video_path
            )

            prefix = "🎬 " if not is_now else "▶▶ "
            fav = " ⭐" if is_fav else ""
            excl   = "  ⊘ excluded" if is_excl else ""
            now    = "  ▮▮▮" if is_now else ""
            return f"{prefix}{name}{fav}{excl}{now}"

        def _clear_tree(self):
            """Remove all rows from the Treeview and reset the mapping."""
            for iid in self.exclusion_tree.get_children():
                self.exclusion_tree.delete(iid)
            self.current_subdirs_mapping = {}

        def load_subdirectories(self, directory, max_depth=20, restore_path=None, restore_scroll=None):
            self.current_max_depth = max_depth
            show_ann = self.settings_manager.get_settings().show_video_annotations_in_tree

            if self.show_only_excluded:
                self.selected_dir_label.config(text=f"Excluded items in: {os.path.basename(directory)}")
            else:
                _cache = self.scan_cache.get(directory)
                if _cache:
                    _videos, _, _ = _cache
                    _count = sum(1 for v in _videos if not self.is_video_excluded(directory, v))
                    self.selected_dir_label.config(
                        text=f"All items in: {os.path.basename(directory)} ({_count} videos)")
                else:
                    self.selected_dir_label.config(text=f"All items in: {os.path.basename(directory)}")

            self._clear_tree()
            self.exclusion_tree.insert("", tk.END, iid="__loading__",
                                       text="  Loading…", tags=("placeholder",))

            if not hasattr(self, '_subdir_load_token'):
                self._subdir_load_token = None
                self._subdir_load_lock  = threading.RLock()

            with self._subdir_load_lock:
                token = object()
                self._subdir_load_token = token

            # Handle Google Drive pseudo-paths
            try:
                if isinstance(directory, str) and directory.startswith("gdrive://"):
                    self._load_drive_tree(directory, token, restore_scroll)
                    return
            except Exception:
                pass

            excluded_dir_set = set(os.path.normpath(p) for p in self.excluded_subdirs.get(directory, []))
            excluded_vid_set = set(os.path.normpath(p) for p in self.excluded_videos.get(directory, []))
            show_videos  = self.show_videos
            only_excl    = self.show_only_excluded
            search_query = getattr(self, 'search_query', '')
            base         = os.path.abspath(directory)
            base_norm    = os.path.normpath(base)
            expand_all   = self.expand_all_var.get()
            expanded     = set(self.expanded_paths)
            collapsed    = set(self.collapsed_paths)

            def build_and_post():
                try:
                    if self.resource_manager.is_shutting_down():
                        return
                    with self._subdir_load_lock:
                        if self._subdir_load_token is not token:
                            return

                    # Each item: (parent_iid, path, is_dir, depth)
                    # We do a single os.walk and build a flat list that maps
                    # path -> iid so we can attach children to the right parent.
                    path_to_iid = {}   # norm_path -> iid assigned in this batch
                    items       = []   # (parent_iid, path, is_dir)
                    iid_counter = [0]

                    def next_iid():
                        iid_counter[0] += 1
                        return f"t{iid_counter[0]}"

                    for root, dirs, files in os.walk(base):
                        if self.resource_manager.is_shutting_down():
                            break
                        rel   = os.path.relpath(root, base)
                        depth = 0 if rel == '.' else rel.count(os.sep) + 1

                        if depth > max_depth:
                            dirs[:] = []
                            continue

                        norm_root = os.path.normpath(root)

                        # Expand / collapse logic
                        if norm_root == base_norm:
                            can_show_children = True
                        elif expand_all:
                            can_show_children = norm_root not in collapsed
                            if norm_root in collapsed:
                                dirs[:] = []
                        else:
                            is_exp = norm_root in expanded
                            can_show_children = is_exp
                            if not is_exp:
                                dirs[:] = []

                        # Search filter
                        if search_query:
                            dir_name_matches   = search_query in os.path.basename(root).lower()
                            is_child_of_match  = self.is_child_of_matching_parent(root, base, search_query)
                            has_match_children = self.matches_search(root, search_query)
                            show_this_dir      = dir_name_matches or is_child_of_match or has_match_children
                        else:
                            show_this_dir = True

                        is_excl_dir = norm_root in excluded_dir_set
                        include_dir = (not only_excl) or is_excl_dir

                        if norm_root == base_norm:
                            iid = next_iid()
                            path_to_iid[norm_root] = iid
                            items.append(("", root, True, iid))
                        elif include_dir and show_this_dir:
                            parent_norm = os.path.normpath(os.path.dirname(root))
                            parent_iid = path_to_iid.get(parent_norm, "")
                            iid = next_iid()
                            path_to_iid[norm_root] = iid
                            items.append((parent_iid, root, True, iid))

                        if show_videos and can_show_children and show_this_dir:
                            try:
                                with os.scandir(root) as it:
                                    for entry in sorted(it, key=lambda e: e.name.lower()):
                                        if not entry.is_file():
                                            continue
                                        if not is_video(entry.name):
                                            continue
                                        full_path = entry.path
                                        norm_full = os.path.normpath(full_path)
                                        is_excl_v = norm_full in excluded_vid_set
                                        include_v = (not only_excl) or is_excl_v

                                        vid_name_ok = (not search_query) or (
                                            search_query in entry.name.lower()
                                            or dir_name_matches if search_query else True
                                        )
                                        if include_v and vid_name_ok:
                                            parent_iid = path_to_iid.get(norm_root, "")
                                            iid        = next_iid()
                                            path_to_iid[norm_full] = iid
                                            items.append((parent_iid, full_path, False, iid))
                            except PermissionError:
                                pass

                    def post_tree():
                        with self._subdir_load_lock:
                            if self._subdir_load_token is not token:
                                return

                        self._clear_tree()
                        mapping      = {}
                        target_iid   = None
                        restore_norm = os.path.normpath(restore_path) if restore_path else None

                        if not items:
                            self.exclusion_tree.insert("", tk.END, iid="__empty__",
                                                       text="  No items found", tags=("placeholder",))
                            self.current_subdirs_mapping = {}
                            return

                        chunk_size = 300
                        total      = len(items)

                        def insert_chunk(start):
                            nonlocal target_iid
                            if self._subdir_load_token is not token:
                                return
                            end = min(start + chunk_size, total)
                            for i in range(start, end):
                                parent_iid, path, is_dir, iid = items[i]
                                norm_p = os.path.normpath(path)
                                tag    = self._tag_for_item(path, base, excluded_dir_set, excluded_vid_set)
                                label  = self._label_for_item(path, is_dir, excluded_dir_set, excluded_vid_set, base)

                                # Determine initial open state for folders
                                open_state = False
                                if is_dir:
                                    if expand_all:
                                        open_state = norm_p not in collapsed
                                    else:
                                        open_state = norm_p in expanded

                                def fmt_size(b):
                                    if b >= 1024 ** 3:
                                        return f"{b / 1024 ** 3:.2f} GB"
                                    elif b >= 1024 ** 2:
                                        return f"{b / 1024 ** 2:.1f} MB"
                                    return f"{b // 1024} KB"

                                if is_dir:
                                    try:
                                        total_size = 0
                                        for dp, _, fnames in os.walk(path):
                                            for fn in fnames:
                                                try:
                                                    total_size += os.path.getsize(os.path.join(dp, fn))
                                                except Exception:
                                                    pass
                                        meta_size = fmt_size(total_size)
                                    except Exception:
                                        meta_size = ""
                                else:
                                    try:
                                        meta_size = fmt_size(os.path.getsize(path))
                                    except Exception:
                                        meta_size = ""
                                if is_dir:
                                    size_str = meta_size
                                else:
                                    size_str = self._get_video_size_str(path)
                                if show_ann:
                                    rating_str = self._get_rating_stars(path) if not is_dir else ""
                                    tags_str = self._get_tags_str(path) if not is_dir else ""
                                else:
                                    rating_str = tags_str = ""

                                self.exclusion_tree.insert(
                                    parent_iid, tk.END, iid=iid,
                                    text=label, tags=(tag,),
                                    open=open_state,
                                    values=(rating_str, tags_str, size_str) if show_ann else (size_str,)
                                )
                                mapping[iid] = path
                                if restore_norm and norm_p == restore_norm:
                                    target_iid = iid

                            if end < total:
                                self.root.after(1, lambda: insert_chunk(end))
                            else:
                                self.current_subdirs_mapping = mapping

                                # Attach preview manager to new tree
                                if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
                                    self.video_preview_manager.attach_to_listbox(
                                        self.exclusion_tree, self.current_subdirs_mapping
                                    )

                                if target_iid:
                                    self.exclusion_tree.selection_set(target_iid)
                                    self.exclusion_tree.see(target_iid)

                                if restore_scroll:
                                    self._tree_yview_moveto(restore_scroll[0])

                                self._update_tree_now_playing()

                        insert_chunk(0)

                    self.root.after(0, post_tree)

                except Exception as e:
                    err = str(e)
                    def post_error(msg=err):
                        with self._subdir_load_lock:
                            if self._subdir_load_token is not token:
                                return
                        self._clear_tree()
                        self.exclusion_tree.insert("", tk.END, iid="__error__",
                                                   text=f"  Error: {msg}", tags=("placeholder",))
                        self.current_subdirs_mapping = {}
                    self.root.after(0, post_error)

            ManagedThread(target=build_and_post, name="LoadSubdirs").start()

        def _load_drive_tree(self, directory, token, restore_scroll):
            """Populate the tree for a Google Drive pseudo-directory."""
            cache = self.scan_cache.get(directory)
            if not cache:
                self._clear_tree()
                self.exclusion_tree.insert("", tk.END, iid="__empty__",
                                           text="  No items found", tags=("placeholder",))
                return

            videos, video_to_dir, directories = cache

            def post_drive():
                with self._subdir_load_lock:
                    if self._subdir_load_token is not token:
                        return
                self._clear_tree()
                mapping = {}
                iid_n   = [0]

                def nxt():
                    iid_n[0] += 1
                    return f"gd{iid_n[0]}"

                if directory.startswith("gdrive://folder/"):
                    tree_info = None
                    try:
                        if self.drive_manager:
                            tree_info = self.drive_manager.get_folder_tree(directory)
                    except Exception:
                        pass

                    dir_prefix  = directory.rstrip('/')
                    base_depth  = dir_prefix.count('/')
                    subdirs     = sorted(
                        [d for d in directories if d.startswith(dir_prefix)],
                        key=lambda s: (s.count('/'), s)
                    )
                    dir_iids    = {}
                    for d in subdirs:
                        if d == dir_prefix:
                            dir_iids[d] = ""
                            continue
                        name       = os.path.basename(d)
                        if tree_info and 'dir_names' in tree_info:
                            name = tree_info['dir_names'].get(d, name)
                        parent_d   = d.rsplit('/', 1)[0] if '/' in d else dir_prefix
                        parent_iid = dir_iids.get(parent_d, "")
                        iid        = nxt()
                        dir_iids[d] = iid
                        self.exclusion_tree.insert(parent_iid, tk.END, iid=iid,
                                                   text=f"📁 {name}", tags=("folder",), open=True)
                        mapping[iid] = d

                    for v in videos:
                        vname = 'Drive Stream'
                        if tree_info and 'file_names' in tree_info:
                            vname = tree_info['file_names'].get(v, vname)
                        parent_d   = video_to_dir.get(v, dir_prefix)
                        parent_iid = dir_iids.get(parent_d, "")
                        iid        = nxt()
                        self.exclusion_tree.insert(parent_iid, tk.END, iid=iid,
                                                   text=f"🎬 {vname}", tags=("video",))
                        mapping[iid] = v
                else:
                    for v in videos:
                        iid = nxt()
                        self.exclusion_tree.insert("", tk.END, iid=iid,
                                                   text="🎬 Drive Stream", tags=("video",))
                        mapping[iid] = v

                self.current_subdirs_mapping = mapping
                if restore_scroll:
                    self._tree_yview_moveto(restore_scroll[0])
        def _context_show_folder_properties(self, folder_path):
            try:
                total_size = 0
                file_count = 0
                video_count = 0
                for dirpath, _, filenames in os.walk(folder_path):
                    for f in filenames:
                        try:
                            fp = os.path.join(dirpath, f)
                            total_size += os.path.getsize(fp)
                            file_count += 1
                            if is_video(fp):
                                video_count += 1
                        except Exception:
                            pass
                size_mb = total_size / (1024 * 1024)
                stat_info = os.stat(folder_path)
                modified = datetime.fromtimestamp(stat_info.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                info = (
                    f"Folder: {os.path.basename(folder_path)}\n\n"
                    f"Path: {folder_path}\n\n"
                    f"Total Files: {file_count}\n\n"
                    f"Video Files: {video_count}\n\n"
                    f"Total Size: {size_mb:.2f} MB ({total_size:,} bytes)\n\n"
                    f"Modified: {modified}"
                )
                messagebox.showinfo("Folder Properties", info)
            except Exception as e:
                self.update_console(f"Error getting folder properties: {e}")
                messagebox.showerror("Error", f"Could not get folder properties: {e}")

        def _context_open_folder_location(self, folder_path):
            try:
                import subprocess
                if os.name == 'nt':
                    subprocess.Popen(f'explorer /select,"{folder_path}"')
                elif os.name == 'posix':
                    if sys.platform == 'darwin':
                        subprocess.Popen(['open', '-R', folder_path])
                    else:
                        subprocess.Popen(['xdg-open', os.path.dirname(folder_path)])
                self.update_console(f"Opened location: {os.path.dirname(folder_path)}")
            except Exception as e:
                self.update_console(f"Error opening location: {e}")
                messagebox.showerror("Error", f"Could not open folder location: {e}")

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

            self.root.after(0, post_drive)

        # ------------------------------------------------------------------
        # Now-playing indicator
        # ------------------------------------------------------------------

        def _update_tree_now_playing(self):
            """
            Walk all iids and update tags/labels to reflect the currently-
            playing video.  Because Treeview uses tags for styling, we simply
            re-tag each relevant row.
            """
            try:
                if not hasattr(self, 'current_subdirs_mapping') or not self.current_subdirs_mapping:
                    return
                now = getattr(self, '_now_playing_video_path', None)

                selected_dir = self.get_current_selected_directory()
                if not selected_dir:
                    return

                excluded_dir_set = set(os.path.normpath(p) for p in self.excluded_subdirs.get(selected_dir, []))
                excluded_vid_set = set(os.path.normpath(p) for p in self.excluded_videos.get(selected_dir, []))

                for iid, path in self.current_subdirs_mapping.items():
                    if not os.path.isfile(path):
                        continue
                    is_now = now and os.path.normpath(path) == now
                    tag    = self._tag_for_item(path, selected_dir,
                                                excluded_dir_set, excluded_vid_set,
                                                is_now_playing=bool(is_now))
                    label  = self._label_for_item(path, False, excluded_dir_set, excluded_vid_set, selected_dir)
                    try:
                        self.exclusion_tree.item(iid, text=label, tags=(tag,))
                    except tk.TclError:
                        pass
            except Exception:
                pass

        # ------------------------------------------------------------------
        # Filtered view (used by filter_sort_ui)
        # ------------------------------------------------------------------

        def _apply_filters_and_refresh(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showwarning("Warning", "Please select a directory first")
                return

            progress_window = tk.Toplevel(self.root)
            apply_icon(progress_window)
            progress_window.title("Applying Filters")
            progress_window.geometry("400x150")
            progress_window.configure(bg=self.bg_color)
            progress_window.transient(self.root)
            progress_window.grab_set()

            progress_label = tk.Label(progress_window, text="Processing videos…",
                                      font=self.normal_font, bg=self.bg_color, fg=self.text_color)
            progress_label.pack(pady=20)

            progress_bar = ttk.Progressbar(progress_window, length=350, mode='determinate')
            progress_bar.pack(pady=10)

            status_label = tk.Label(progress_window, text="",
                                    font=self.small_font, bg=self.bg_color, fg="#666666")
            status_label.pack()

            def update_progress(current, total):
                if total > 0:
                    progress_bar['value'] = (current / total) * 100
                    status_label.config(text=f"Processing {current}/{total} videos…")
                    progress_window.update()

            def process_in_thread():
                try:
                    cache = self.scan_cache.get(selected_dir)
                    if not cache:
                        def show_warning():
                            try: progress_window.destroy()
                            except: pass
                            messagebox.showwarning("Warning", "Directory not scanned yet")
                        self.root.after(0, show_warning)
                        return

                    videos, _, _ = cache
                    filtered_sorted = self.filter_sort_manager.apply_filter_and_sort(
                        videos, load_properties=True,
                        progress_callback=lambda c, t: self.root.after(0, lambda: update_progress(c, t))
                    )

                    def update_ui():
                        try: progress_window.destroy()
                        except: pass

                        self._is_filtered_mode = True
                        self._filtered_videos  = filtered_sorted
                        self._base_directory   = selected_dir

                        self._clear_tree()

                        if not filtered_sorted:
                            self.exclusion_tree.insert("", tk.END, iid="__nores__",
                                                       text="  No videos match the current filters",
                                                       tags=("placeholder",))
                            self.update_console("No videos match current filters")
                            return

                        for idx, video_path in enumerate(filtered_sorted):
                            try:
                                rel_path = os.path.relpath(video_path, selected_dir)
                            except ValueError:
                                rel_path = os.path.basename(video_path)

                            is_excl = self.is_video_excluded(selected_dir, video_path)
                            is_fav  = (hasattr(self, 'favorites_manager') and
                                       self.favorites_manager.is_favorite(video_path, selected_dir))

                            if is_excl:
                                tag   = "video_fav_excl" if is_fav else "video_excl"
                                label = f"🎬 {rel_path}  ⊘ excluded"
                            elif is_fav:
                                tag   = "video_fav"
                                label = f"🎬 {rel_path} ⭐"
                            else:
                                tag   = "video"
                                label = f"🎬 {rel_path}"

                            iid = f"f{idx}"
                            self.exclusion_tree.insert("", tk.END, iid=iid,
                                                       text=label, tags=(tag,))
                            self.current_subdirs_mapping[iid] = video_path

                        self.selected_dir_label.config(
                            text=f"Filtered: {len(filtered_sorted)} videos in '{os.path.basename(selected_dir)}'"
                        )
                        self.update_console(
                            f"Applied filters: {len(filtered_sorted)} videos shown from {len(videos)} total")

                        if hasattr(self, 'video_preview_manager'):
                            self.video_preview_manager.attach_to_listbox(
                                self.exclusion_tree, self.current_subdirs_mapping)

                    self.root.after(0, update_ui)

                except Exception as e:
                    def show_error():
                        try: progress_window.destroy()
                        except: pass
                        messagebox.showerror("Error", f"Filter error: {e}")
                    self.root.after(0, show_error)

            threading.Thread(target=process_in_thread, daemon=True).start()

        def _reapply_filtered_view(self, scroll_pos=None):
            if not hasattr(self, '_filtered_videos') or not hasattr(self, '_base_directory'):
                return

            selected_dir    = self._base_directory
            filtered_sorted = self._filtered_videos

            self._clear_tree()

            if not filtered_sorted:
                self.exclusion_tree.insert("", tk.END, iid="__nores__",
                                           text="  No videos match the current filters",
                                           tags=("placeholder",))
                return

            for idx, video_path in enumerate(filtered_sorted):
                try:
                    rel_path = os.path.relpath(video_path, selected_dir)
                except ValueError:
                    rel_path = os.path.basename(video_path)

                is_excl = self.is_video_excluded(selected_dir, video_path)
                is_fav  = (hasattr(self, 'favorites_manager') and
                           self.favorites_manager.is_favorite(video_path, selected_dir))

                if is_excl:
                    tag   = "video_fav_excl" if is_fav else "video_excl"
                    label = f"🎬 {rel_path}  ⊘ excluded"
                elif is_fav:
                    tag   = "video_fav"
                    label = f"🎬 {rel_path} ⭐"
                else:
                    tag   = "video"
                    label = f"🎬 {rel_path}"

                iid = f"f{idx}"
                self.exclusion_tree.insert("", tk.END, iid=iid, text=label, tags=(tag,))
                self.current_subdirs_mapping[iid] = video_path

            self.selected_dir_label.config(
                text=f"Filtered: {len(filtered_sorted)} videos in '{os.path.basename(selected_dir)}'"
            )

            if hasattr(self, 'video_preview_manager'):
                self.video_preview_manager.attach_to_listbox(
                    self.exclusion_tree, self.current_subdirs_mapping)

            if scroll_pos:
                self._tree_yview_moveto(scroll_pos[0])

        # ------------------------------------------------------------------
        # Helpers used by many callers below
        # ------------------------------------------------------------------

        def _resolve_iids_to_paths(self, iids):
            """Expand selected iids to a flat deduplicated list of video paths."""
            selected_dir = self.get_current_selected_directory()
            collected = []
            for iid in iids:
                path = self.current_subdirs_mapping.get(iid)
                if not path:
                    continue
                if self._is_stream_url(path):
                    if not (selected_dir and self.is_video_excluded(selected_dir, path)):
                        collected.append(path)
                    continue
                if isinstance(path, str) and path.startswith("gdrive://folder/"):
                    root_pseudo = None
                    for d in self.selected_dirs:
                        if isinstance(d, str) and d.startswith("gdrive://folder/") and path.startswith(d):
                            root_pseudo = d
                            break
                    if root_pseudo:
                        for v in self._collect_videos_from_pseudo_dir(root_pseudo, path):
                            if not self.is_video_excluded(root_pseudo, v):
                                collected.append(v)
                    continue
                if os.path.isfile(path) and is_video(path):
                    if not (selected_dir and self.is_video_excluded(selected_dir, path)):
                        collected.append(path)
                    continue
                if os.path.isdir(path):
                    try:
                        for root, dirs, files in os.walk(path):
                            for f in files:
                                full = os.path.join(root, f)
                                if is_video(full):
                                    if not (selected_dir and self.is_video_excluded(selected_dir, full)):
                                        collected.append(full)
                    except Exception as e:
                        self.update_console(f"Error reading folder {path}: {e}")

            seen  = set()
            final = []
            for v in collected:
                k = v if self._is_stream_url(v) else os.path.normpath(v)
                if k not in seen:
                    seen.add(k)
                    final.append(k)
            return final

        # ------------------------------------------------------------------
        # Everything below is functionally identical to original; only the
        # listbox API calls are updated to use the tree / iid-based mapping.
        # ------------------------------------------------------------------

        def _build_video_list(self):
            if getattr(self, '_is_filtered_mode', False) and getattr(self, '_filtered_videos', None):
                all_v2d = {}
                for directory in self.selected_dirs:
                    cache = self.scan_cache.get(directory)
                    if cache:
                        _, dir_v2d, _ = cache
                        all_v2d.update(dir_v2d)
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
                videos      = []
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

        def _make_player(self, videos, video_to_dir, directories, start_index=0):
            """Create and return a configured EmbeddedPlayer (not yet played)."""
            player = EmbeddedPlayer(
                parent=self.root,
                videos=videos,
                video_to_dir=video_to_dir,
                directories=directories,
                start_index=start_index,
                volume=getattr(self, 'volume', 50),
                is_muted=getattr(self, 'is_muted', False),
                loop_mode=getattr(self, 'loop_mode', 'loop_on'),
                logger=self.update_console,
                on_close=self._on_player_closed,
                on_volume_change=self._save_volume_callback,
                resume_manager=self.resume_manager,
                annotation_service=self.annotation_service,
            )
            player.on_loop_change        = self._save_loop_callback
            player.on_close_save         = self._on_player_close_save
            player.on_video_changed      = self.on_video_changed
            player.on_add_to_playlist    = lambda vids: self.playlist_manager.add_videos_to_playlist([], vids)
            player.on_add_to_queue       = lambda vids: self.queue_manager.add_to_queue(vids, added_from="player")
            player.on_add_to_favourites  = lambda vids: self.favorites_manager.add_to_favorites(
                vids, self.get_current_selected_directory() or os.path.dirname(vids[0]))
            player.set_hotkeys(self.settings_manager.get_settings().hotkeys)
            if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
                player.set_seek_preview_manager(self.video_preview_manager)
            app_settings = self.settings_manager.get_settings()
            if app_settings.gaming_mode:
                player.set_gaming_mode(True)
            return player

        def _launch_player(self, player):
            if self._active_player is not None:
                try:
                    self._active_player._close()
                except Exception:
                    pass
                self._active_player = None
            player.play()
            self._active_player = player

        def _show_annotation_browser(self):
            self._show_embedded_view(
                "tags",
                lambda frame: self.annotation_browser.show_embedded(
                    frame,
                    close_callback=self._show_home_view
                )
            )

        def _play_annotated_videos(self, video_paths: list):
            if not video_paths:
                return
            all_video_to_dir = {}
            all_directories = []
            for vp in video_paths:
                vdir = os.path.dirname(vp) if os.path.isfile(vp) else None
                if vdir:
                    all_video_to_dir[vp] = vdir
                    if vdir not in all_directories:
                        all_directories.append(vdir)
            all_directories.sort()
            valid_videos = list(all_video_to_dir.keys())
            if not valid_videos:
                return
            self._launch_player(self._make_player(valid_videos, all_video_to_dir, all_directories, 0))

        def play_videos(self):
            videos, video_to_dir, directories = self._build_video_list()
            if not videos:
                self.update_console("No videos to play.")
                return

            idx = 0
            if getattr(self, 'start_from_last_played', False) and getattr(self, 'last_played_video_path', ''):
                resume_path = os.path.normpath(self.last_played_video_path)
                for i, v in enumerate(videos):
                    if os.path.normpath(v) == resume_path:
                        idx = i
                        break
                else:
                    try:
                        sel = self.dir_listbox.curselection()
                        if sel and sel[0] < len(self.selected_dirs):
                            target_dir = self.selected_dirs[sel[0]]
                            for i, v in enumerate(videos):
                                if os.path.normpath(video_to_dir.get(v, "")).startswith(os.path.normpath(target_dir)):
                                    idx = i
                                    break
                    except Exception:
                        pass
            else:
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

            self._launch_player(self._make_player(videos, video_to_dir, directories, idx))

        def _play_from_double_click(self, target_path):
            videos       = [target_path]
            video_to_dir = {target_path: os.path.dirname(target_path)}
            directories  = [os.path.dirname(target_path)]
            self._launch_player(self._make_player(videos, video_to_dir, directories, 0))

        def play_selected_videos(self):
            selected_dir = self.get_current_selected_directory()
            selection    = self._tree_selection_indices()

            if not selection:
                self.update_console("No videos selected.")
                return

            selected_videos = []
            seen = set()

            for iid in selection:
                path = self.current_subdirs_mapping.get(iid)
                if not path:
                    continue
                if os.path.isfile(path) and is_video(path):
                    if selected_dir and self.is_video_excluded(selected_dir, path):
                        continue
                    norm = os.path.normpath(path)
                    if norm not in seen:
                        seen.add(norm)
                        selected_videos.append(path)
                elif os.path.isdir(path):
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

            all_v2d = {}
            for directory in self.selected_dirs:
                cache = self.scan_cache.get(directory)
                if cache:
                    _, dir_v2d, _ = cache
                    all_v2d.update(dir_v2d)

            sel_v2d  = {v: all_v2d.get(v, os.path.dirname(v)) for v in selected_videos}
            sel_dirs = list(dict.fromkeys(sel_v2d[v] for v in selected_videos))

            self.update_console(f"Playing {len(selected_videos)} selected video(s)")
            self._launch_player(self._make_player(selected_videos, sel_v2d, sel_dirs, 0))

        def _on_player_closed(self):
            self._active_player = None
            self.update_console("Player closed.")
            self._on_player_stopped()

        def _save_loop_callback(self, loop_mode: str):
            self.loop_mode = loop_mode
            if hasattr(self, 'loop_toggle_button'):
                try: self.loop_toggle_button.config(text=self._get_loop_icon())
                except Exception: pass
            if hasattr(self, '_loop_mode_var'):
                try: self._loop_mode_var.set(loop_mode)
                except Exception: pass
            self.save_preferences()

        def _on_player_close_save(self, index, path, loop_mode, volume, is_muted):
            self.loop_mode               = loop_mode
            self.volume                  = volume
            self.is_muted                = is_muted
            self.last_played_video_index = index
            self.last_played_video_path  = path
            if hasattr(self, 'loop_toggle_button'):
                try: self.loop_toggle_button.config(text=self._get_loop_icon())
                except Exception: pass
            self.save_preferences()
            if hasattr(self, 'watch_history_manager') and path:
                self.watch_history_manager.track_video_end(path)

        def on_video_changed(self, video_index, video_path):
            if hasattr(self, 'filter_sort_manager'):
                self.filter_sort_manager.metadata_cache.update_play_stats(video_path)
            self.last_played_video_index = video_index
            self.last_played_video_path  = video_path
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

        def clear_exclusion_list(self):
            self.selected_dir_label.config(text="Select a directory to see its folders and videos")
            self._clear_tree()

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
                idx = selection[0]
                if idx < len(self.selected_dirs):
                    self.current_selected_dir_index = idx
                    return self.selected_dirs[idx]
            if self.current_selected_dir_index is not None and self.current_selected_dir_index < len(self.selected_dirs):
                return self.selected_dirs[self.current_selected_dir_index]
            if self.selected_dirs:
                return self.selected_dirs[-1]
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
                excluded_subdir   = os.path.normpath(excluded_subdir)
                video_dir_norm    = os.path.normpath(video_dir)
                if video_dir_norm == excluded_subdir:
                    return True
                if video_dir_norm.startswith(excluded_subdir + os.sep):
                    return True
            return False

        def is_video_excluded(self, root_dir, video_path):
            excluded_videos = self.excluded_videos.get(root_dir, [])
            video_path      = os.path.normpath(video_path)
            if video_path in excluded_videos:
                return True
            excluded_subdirs = self.excluded_subdirs.get(root_dir, [])
            return self.is_video_in_excluded_directory(video_path, excluded_subdirs)

        def is_directory_excluded(self, directory_path, excluded_subdirs):
            for excluded_subdir in excluded_subdirs:
                excluded_subdir       = os.path.normpath(excluded_subdir)
                directory_path_norm   = os.path.normpath(directory_path)
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
            pending      = 0

            for directory in self.selected_dirs:
                cache = self.scan_cache.get(directory)
                if not cache:
                    pending += 1
                    continue
                videos, _, _ = cache
                total_videos += sum(1 for v in videos if not self.is_video_excluded(directory, v))

            self.video_count = total_videos
            suffix = f" (scanning {pending}…)" if pending else ""
            self.video_count_label.config(text=f"  —  {self.video_count} videos{suffix}")

            if (not pending and
                    not hasattr(self, '_last_reported_video_count') or
                    (not pending and getattr(self, '_last_reported_video_count', None) != total_videos)):
                self._last_reported_video_count = total_videos
                self.update_console(
                    f"Total: {total_videos} videos from {len(self.selected_dirs)} "
                    f"director{'ies' if len(self.selected_dirs) != 1 else 'y'}")

        def exclude_all_subdirectories(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showinfo("Information", "Please select a directory first.")
                return

            is_filtered_mode = getattr(self, '_is_filtered_mode', False)
            self._clear_tree()
            self.exclusion_tree.insert("", tk.END, iid="__excl_wait__",
                                       text="  Excluding all… Please wait", tags=("placeholder",))

            def worker(dir_path=selected_dir):
                dir_paths  = []
                file_paths = []
                displayed  = set(self.current_subdirs_mapping.values()) if (
                    hasattr(self, 'search_query') and self.search_query) else set()

                try:
                    base = os.path.normpath(dir_path)
                    for root, dirs, files in os.walk(base):
                        for d in dirs:
                            sp = os.path.join(root, d)
                            if not displayed or sp in displayed:
                                dir_paths.append(sp)
                        for f in files:
                            full = os.path.join(root, f)
                            if is_video(full) and (not displayed or full in displayed):
                                file_paths.append(full)
                except Exception as e:
                    self.root.after(0, lambda: self.update_console(f"Error during Exclude All: {e}"))
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
                    self.update_console(f"Excluded {total} items from '{os.path.basename(dir_path)}'")

                    scroll_pos = self._tree_yview()
                    if is_filtered_mode and hasattr(self, '_filtered_videos'):
                        self._reapply_filtered_view(scroll_pos)
                    else:
                        self.load_subdirectories(dir_path, restore_scroll=scroll_pos)

                    self.update_video_count()
                    self.exclusion_tree.selection_remove(self._tree_get_all_iids())
                    if self.save_directories:
                        self.save_preferences()

                self.root.after(0, apply_and_refresh)

            ManagedThread(target=worker, name="ExcludeAllWorker").start()

        def exclude_subdirectories(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showinfo("Information", "Please select a directory first.")
                return

            selection = self._tree_selection_indices()
            if not selection:
                messagebox.showinfo("Information", "Please select items to exclude.")
                return

            is_filtered_mode = getattr(self, '_is_filtered_mode', False)

            def worker(dir_path=selected_dir, iids=list(selection)):
                dirs_to_exclude = set()
                vids_to_exclude = set()
                names           = []
                displayed       = set(self.current_subdirs_mapping.values()) if (
                    hasattr(self, 'search_query') and self.search_query) else set()

                try:
                    for iid in iids:
                        target_path = self.current_subdirs_mapping.get(iid)
                        if not target_path:
                            continue
                        if os.path.isdir(target_path):
                            base = os.path.normpath(target_path)
                            dirs_to_exclude.add(base)
                            for root, dirs, files in os.walk(base):
                                for d in dirs:
                                    sp = os.path.join(root, d)
                                    if not displayed or sp in displayed:
                                        dirs_to_exclude.add(sp)
                                for f in files:
                                    full = os.path.join(root, f)
                                    if is_video(full) and (not displayed or full in displayed):
                                        vids_to_exclude.add(full)
                        else:
                            vids_to_exclude.add(target_path)
                        names.append(os.path.basename(target_path))
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror("Error", f"Error excluding: {e}"))
                    return

                def apply_and_refresh():
                    if dir_path not in self.excluded_subdirs:
                        self.excluded_subdirs[dir_path] = []
                    if dir_path not in self.excluded_videos:
                        self.excluded_videos[dir_path] = []

                    count = 0
                    existing_d = set(self.excluded_subdirs[dir_path])
                    for d in dirs_to_exclude:
                        if d not in existing_d:
                            self.excluded_subdirs[dir_path].append(d)
                            count += 1
                    existing_v = set(self.excluded_videos[dir_path])
                    for vp in vids_to_exclude:
                        if vp not in existing_v:
                            self.excluded_videos[dir_path].append(vp)
                            count += 1

                    if count:
                        self.update_console(f"Excluded {count} item(s): {', '.join(names)}")

                    first_path = self.current_subdirs_mapping.get(iids[0]) if iids else None
                    scroll_pos = self._tree_yview()
                    if is_filtered_mode and hasattr(self, '_filtered_videos'):
                        self._reapply_filtered_view(scroll_pos)
                    else:
                        self.load_subdirectories(dir_path, restore_path=(
                            os.path.normpath(first_path) if first_path else None),
                            restore_scroll=scroll_pos)

                    self.update_video_count()
                    if self.save_directories:
                        self.save_preferences()

                self.root.after(0, apply_and_refresh)

            ManagedThread(target=worker, name="ExcludeWorker").start()

        def include_subdirectories(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showinfo("Information", "Please select a directory first.")
                return

            selection = self._tree_selection_indices()
            if not selection:
                messagebox.showinfo("Information", "Please select items to include.")
                return

            if selected_dir not in self.excluded_subdirs and selected_dir not in self.excluded_videos:
                return

            is_filtered_mode = getattr(self, '_is_filtered_mode', False)

            def worker(dir_path=selected_dir, iids=list(selection)):
                dirs_to_include = set()
                vids_to_include = set()
                names           = []
                displayed       = set(self.current_subdirs_mapping.values()) if (
                    hasattr(self, 'search_query') and self.search_query) else set()

                try:
                    for iid in iids:
                        target_path = self.current_subdirs_mapping.get(iid)
                        if not target_path:
                            continue
                        if os.path.isdir(target_path):
                            base = os.path.normpath(target_path)
                            dirs_to_include.add(base)
                            for root, dirs, files in os.walk(base):
                                for d in dirs:
                                    sp = os.path.join(root, d)
                                    if not displayed or sp in displayed:
                                        dirs_to_include.add(sp)
                                for f in files:
                                    full = os.path.join(root, f)
                                    if is_video(full) and (not displayed or full in displayed):
                                        vids_to_include.add(full)
                        else:
                            vids_to_include.add(target_path)
                        names.append(os.path.basename(target_path))
                except Exception as e:
                    self.root.after(0, lambda: messagebox.showerror("Error", f"Error including: {e}"))
                    return

                def apply_and_refresh():
                    count = 0
                    if dir_path in self.excluded_subdirs:
                        remaining = [d for d in self.excluded_subdirs[dir_path] if d not in dirs_to_include]
                        count += len(self.excluded_subdirs[dir_path]) - len(remaining)
                        if remaining:
                            self.excluded_subdirs[dir_path] = remaining
                        else:
                            del self.excluded_subdirs[dir_path]

                    if dir_path in self.excluded_videos:
                        remaining_v = [v for v in self.excluded_videos[dir_path] if v not in vids_to_include]
                        count += len(self.excluded_videos[dir_path]) - len(remaining_v)
                        if remaining_v:
                            self.excluded_videos[dir_path] = remaining_v
                        else:
                            del self.excluded_videos[dir_path]

                    if count:
                        self.update_console(f"Included {count} item(s): {', '.join(names)}")

                    first_path = self.current_subdirs_mapping.get(iids[0]) if iids else None
                    scroll_pos = self._tree_yview()
                    if is_filtered_mode and hasattr(self, '_filtered_videos'):
                        self._reapply_filtered_view(scroll_pos)
                    else:
                        self.load_subdirectories(dir_path, restore_path=(
                            os.path.normpath(first_path) if first_path else None),
                            restore_scroll=scroll_pos)

                    self.update_video_count()
                    if self.save_directories:
                        self.save_preferences()

                self.root.after(0, apply_and_refresh)

            ManagedThread(target=worker, name="IncludeWorker").start()

        def clear_all_exclusions(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showinfo("Information", "Please select a directory first.")
                return

            is_filtered_mode = getattr(self, '_is_filtered_mode', False)
            had_subdir = selected_dir in self.excluded_subdirs
            had_video  = selected_dir in self.excluded_videos

            if had_subdir or had_video:
                count = (len(self.excluded_subdirs.get(selected_dir, [])) +
                         len(self.excluded_videos.get(selected_dir, [])))
                if messagebox.askyesno("Confirm", f"Clear all exclusions for {os.path.basename(selected_dir)}?"):
                    if had_subdir: del self.excluded_subdirs[selected_dir]
                    if had_video:  del self.excluded_videos[selected_dir]
                    self.update_console(f"Cleared all {count} exclusions for '{os.path.basename(selected_dir)}'")
                    if self.save_directories:
                        self.save_preferences()

                    scroll_pos = self._tree_yview()
                    if is_filtered_mode and hasattr(self, '_filtered_videos'):
                        self._reapply_filtered_view(scroll_pos)
                    else:
                        self.load_subdirectories(selected_dir)
                    self.update_video_count()

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

        # ------------------------------------------------------------------
        # Dir listbox helpers (unchanged API)
        # ------------------------------------------------------------------

        def _select_all_main_dirs(self, event=None):
            self.dir_listbox.selection_set(0, tk.END)
            self.on_directory_select(None)
            return "break"

        def _on_main_dir_left_click(self, event):
            index = self.dir_listbox.nearest(event.y)
            if index < 0 or index >= self.dir_listbox.size():
                return

            self._drag_start_index = index
            ctrl_held  = bool(event.state & 0x4)
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
                end   = max(self._main_dir_anchor, index)
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
            if drop_index < 0: drop_index = 0
            if drop_index >= self.dir_listbox.size(): drop_index = self.dir_listbox.size() - 1

            if drop_index != self._drag_start_index:
                dir_to_move = self.selected_dirs.pop(self._drag_start_index)
                self.selected_dirs.insert(drop_index, dir_to_move)
                text = self.dir_listbox.get(self._drag_start_index)
                self.dir_listbox.delete(self._drag_start_index)
                self.dir_listbox.insert(drop_index, text)
                self.dir_listbox.selection_clear(0, tk.END)
                self.dir_listbox.selection_set(drop_index)
                self.dir_listbox.activate(drop_index)
                self.current_selected_dir_index = drop_index
                self.on_directory_select(None)

            self._drag_start_index = None

        def _show_main_dir_context_menu(self, event):
            index     = self.dir_listbox.nearest(event.y)
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

            context_menu = self._make_context_menu()
            context_menu.add_command(label="Play Selected",      command=self._play_selected_main_dirs)
            context_menu.add_command(label="Open in Grid View",  command=self._open_grid_view_main_dirs)
            context_menu.add_separator()
            context_menu.add_command(label="Remove Selected",    command=self.remove_directory)
            context_menu.post(event.x_root, event.y_root)

        def _play_selected_main_dirs(self):
            selection = self.dir_listbox.curselection()
            if not selection:
                return

            all_videos     = []
            all_video_to_dir = {}
            for i in selection:
                if i < len(self.selected_dirs):
                    root_dir = self.selected_dirs[i]
                    cache    = self.scan_cache.get(root_dir)
                    if cache:
                        videos, video_to_dir, _ = cache
                    else:
                        videos, video_to_dir, _ = gather_videos_with_directories(root_dir)
                    filtered = [v for v in videos if not self.is_video_excluded(root_dir, v)]
                    all_videos.extend(filtered)
                    all_video_to_dir.update({v: video_to_dir.get(v, os.path.dirname(v)) for v in filtered})

            if not all_videos:
                messagebox.showinfo("Information", "No videos found in selected directories.")
                return

            all_directories = sorted(list(dict.fromkeys(all_video_to_dir[v] for v in all_videos)))
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

            self._launch_player(self._make_player(all_videos, all_video_to_dir, all_directories, idx))

        def _open_grid_view_main_dirs(self):
            selection = self.dir_listbox.curselection()
            if not selection:
                return

            selected_dirs = [self.selected_dirs[i] for i in selection if i < len(self.selected_dirs)]

            def _open():
                all_videos = []
                for root_dir in selected_dirs:
                    cache = self.scan_cache.get(root_dir)
                    if cache:
                        videos, _, _ = cache
                        all_videos.extend(v for v in videos if not self.is_video_excluded(root_dir, v))
                    else:
                        all_videos.extend(v for v in gather_videos(root_dir)
                                          if not self.is_video_excluded(root_dir, v))

                if not all_videos:
                    messagebox.showinfo("Information", "No videos found in selected directories.")
                    return
                self._open_grid_view(all_videos)

            self._wait_for_scans_then(selected_dirs, _open)

        # ------------------------------------------------------------------
        # Context menu actions — updated to use _resolve_iids_to_paths
        # ------------------------------------------------------------------

        def _context_play_in_dual_player(self, selection, win_id, slot):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                return
            final_videos = self._resolve_iids_to_paths(selection)
            if not final_videos:
                messagebox.showwarning("No Videos", "No valid non-excluded videos found in selection.")
                return
            self.dual_player_manager.load_videos_into_slot(win_id, slot, final_videos)
            self.update_console(f"Sent {len(final_videos)} video(s) to Window {win_id} · Player {slot}")

        def _show_favorites_manager(self):
            selected_dir = self.get_current_selected_directory()
            self._show_embedded_view(
                "favourites",
                lambda frame: self.favorites_manager.show_embedded(
                    frame,
                    selected_dir,
                    close_callback=self._show_home_view
                )
            )

        def _context_add_to_favorites(self, selection):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                return
            selected_videos = []
            for iid in selection:
                item_path = self.current_subdirs_mapping.get(iid)
                if not item_path:
                    continue
                if os.path.isfile(item_path) and is_video(item_path):
                    if not self.is_video_excluded(selected_dir, item_path):
                        selected_videos.append(item_path)
                elif os.path.isdir(item_path):
                    for root, dirs, files in os.walk(item_path):
                        for f in files:
                            full = os.path.join(root, f)
                            if is_video(full) and not self.is_video_excluded(selected_dir, full):
                                selected_videos.append(full)
            if selected_videos:
                count = self.favorites_manager.add_to_favorites(selected_videos, selected_dir)
                self.update_console(f"Added {count} video(s) to favorites")
                scroll_pos = self._tree_yview()
                self.load_subdirectories(selected_dir, restore_scroll=scroll_pos)

        def _context_remove_from_favorites(self, selection):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                return
            selected_videos = []
            for iid in selection:
                item_path = self.current_subdirs_mapping.get(iid)
                if not item_path:
                    continue
                if os.path.isfile(item_path) and is_video(item_path):
                    selected_videos.append(item_path)
                elif os.path.isdir(item_path):
                    for root, dirs, files in os.walk(item_path):
                        for f in files:
                            full = os.path.join(root, f)
                            if is_video(full):
                                selected_videos.append(full)
            if selected_videos:
                count = self.favorites_manager.remove_from_favorites(selected_videos, selected_dir)
                self.update_console(f"Removed {count} video(s) from favorites")
                scroll_pos = self._tree_yview()
                self.load_subdirectories(selected_dir, max_depth=self.current_max_depth, restore_scroll=scroll_pos)

        def _play_favorites_videos(self, videos):
            if not videos:
                return
            all_video_to_dir = {v: os.path.dirname(v) for v in videos}
            all_directories  = sorted(list(set(all_video_to_dir.values())))
            self.update_console(f"Playing {len(videos)} videos from favorites")
            self._launch_player(self._make_player(videos, all_video_to_dir, all_directories, 0))

        def _context_add_to_playlist(self, selection):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                return
            selected_videos = []
            for iid in selection:
                item_path = self.current_subdirs_mapping.get(iid)
                if not item_path:
                    continue
                if os.path.isfile(item_path) and is_video(item_path):
                    if not self.is_video_excluded(selected_dir, item_path):
                        selected_videos.append(item_path)
                elif os.path.isdir(item_path):
                    for root, dirs, files in os.walk(item_path):
                        for f in files:
                            full = os.path.join(root, f)
                            if is_video(full) and not self.is_video_excluded(selected_dir, full):
                                selected_videos.append(full)
            if selected_videos:
                self.playlist_manager.add_videos_to_playlist([], selected_videos)

        def _context_copy_selected(self, selection):
            paths_to_copy = [self.current_subdirs_mapping[iid]
                             for iid in selection if iid in self.current_subdirs_mapping]
            if paths_to_copy:
                file_list    = "\0".join(paths_to_copy) + "\0"
                file_struct  = struct.pack("Iiiii", 20, 0, 0, 0, len(paths_to_copy))
                files_encoded = file_list.encode("utf-16le") + b"\0\0"
                data = file_struct + files_encoded
                try:
                    import win32clipboard as wcb
                    import win32con
                    wcb.OpenClipboard()
                    wcb.EmptyClipboard()
                    wcb.SetClipboardData(win32con.CF_HDROP, data)
                    wcb.CloseClipboard()
                    self.update_console(f"Copied {len(paths_to_copy)} item(s) to clipboard")
                except Exception as e:
                    self.update_console(f"Error copying to clipboard: {e}")

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
                stat_info  = os.stat(file_path)
                size_mb    = stat_info.st_size / (1024 * 1024)
                modified   = datetime.fromtimestamp(stat_info.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                info       = f"File: {os.path.basename(file_path)}\n\n"
                info      += f"Path: {file_path}\n\n"
                info      += f"Size: {size_mb:.2f} MB ({stat_info.st_size:,} bytes)\n\n"
                info      += f"Modified: {modified}\n\n"
                try:
                    import cv2
                    cap = cv2.VideoCapture(file_path)
                    if cap.isOpened():
                        fps         = cap.get(cv2.CAP_PROP_FPS)
                        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                        duration    = frame_count / fps if fps > 0 else 0
                        width       = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        height      = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        info       += f"Duration: {int(duration // 60)}:{int(duration % 60):02d}\n"
                        info       += f"Resolution: {width}x{height}\n"
                        info       += f"FPS: {fps:.2f}\n"
                        cap.release()
                except:
                    pass
                messagebox.showinfo("Properties", info)
            except Exception as e:
                messagebox.showerror("Error", f"Could not retrieve properties: {e}")

        def _context_open_grid_view(self, selection):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                return
            self._show_grid_view()

        def _select_all_items(self, widget=None):
            self.exclusion_tree.selection_set(self._tree_get_all_iids())

        def _context_add_to_queue(self, selection, mode="queue"):
            selected_dir  = self.get_current_selected_directory()
            if not selected_dir:
                return
            final_videos = self._resolve_iids_to_paths(selection)
            if final_videos:
                if mode == "next":
                    count = self.queue_manager.play_next(final_videos, added_from="selection")
                    self.update_console(f"Added {count} videos to play next in queue")
                else:
                    count = self.queue_manager.add_to_queue(final_videos, added_from="selection")
                    self.update_console(f"Added {count} videos to queue")
            else:
                messagebox.showwarning("Warning", "No valid videos found in selection")

        # ------------------------------------------------------------------
        # Playlist / Queue / History play callbacks
        # ------------------------------------------------------------------

        def _play_playlist_videos(self, videos):
            if not videos:
                messagebox.showwarning("Warning", "Playlist is empty")
                return
            self.update_console("=" * 60)
            self.update_console("STARTING PLAYLIST PLAYBACK")
            self.update_console("=" * 60)
            all_video_to_dir = {}
            all_directories  = []
            for vp in videos:
                vdir = "STREAMS" if self._is_stream_url(vp) else (
                    os.path.dirname(vp) if os.path.isfile(vp) else None)
                if vdir:
                    all_video_to_dir[vp] = vdir
                    if vdir not in all_directories:
                        all_directories.append(vdir)
            all_directories.sort()
            valid_videos = list(all_video_to_dir.keys())
            if not valid_videos:
                messagebox.showwarning("Warning", "No valid videos found in playlist")
                return
            self.update_console(f"Playing playlist with {len(valid_videos)} videos")
            self._launch_player(self._make_player(valid_videos, all_video_to_dir, all_directories, 0))

        def _show_queue_manager(self):
            self._show_embedded_view(
                "queue",
                lambda frame: self.queue_manager.show_embedded(
                    frame,
                    close_callback=self._show_home_view
                )
            )

        def _play_queue_videos(self, videos):
            if not videos:
                return
            all_video_to_dir = {}
            all_directories  = []
            for vp in videos:
                vdir = "STREAMS" if self._is_stream_url(vp) else (
                    os.path.dirname(vp) if os.path.isfile(vp) else None)
                if vdir:
                    all_video_to_dir[vp] = vdir
                    if vdir not in all_directories:
                        all_directories.append(vdir)
            all_directories.sort()
            valid_videos = list(all_video_to_dir.keys())
            if not valid_videos:
                messagebox.showwarning("Warning", "No valid videos found")
                return
            self.update_console(f"Playing queue with {len(valid_videos)} videos")
            player = self._make_player(valid_videos, all_video_to_dir, all_directories, 0)
            player.loop_mode = "loop_off"
            self._launch_player(player)

        def _show_watch_history(self):
            self._show_embedded_view(
                "history",
                lambda frame: self.watch_history_manager.show_embedded(
                    frame,
                    close_callback=self._show_home_view
                )
            )

        def _play_history_videos(self, videos):
            if not videos:
                messagebox.showwarning("Warning", "No videos to play")
                return
            self.update_console("=" * 60)
            self.update_console("STARTING HISTORY VIDEO PLAYBACK")
            self.update_console("=" * 60)
            all_video_to_dir = {}
            all_directories  = []
            for vp in videos:
                vdir = "STREAMS" if self._is_stream_url(vp) else (
                    os.path.dirname(vp) if os.path.isfile(vp) else None)
                if vdir:
                    all_video_to_dir[vp] = vdir
                    if vdir not in all_directories:
                        all_directories.append(vdir)
            all_directories.sort()
            valid_videos = list(all_video_to_dir.keys())
            if not valid_videos:
                messagebox.showwarning("Warning", "No valid videos found")
                return
            self.update_console(f"Playing {len(valid_videos)} videos from history")
            self._launch_player(self._make_player(valid_videos, all_video_to_dir, all_directories, 0))

        # ------------------------------------------------------------------
        # Grid view
        # ------------------------------------------------------------------

        def _show_grid_view(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showwarning("Warning", "Please select a directory first")
                return

            selection = self._tree_selection_indices()

            if selection:
                self.update_console("Loading grid view for selected items…")

                def collect_selected():
                    selected_videos = []
                    selected_folders = []
                    for iid in selection:
                        item_path = self.current_subdirs_mapping.get(iid)
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
                                    full = os.path.join(root, f)
                                    if is_video(full) and not self.is_video_excluded(selected_dir, full):
                                        selected_videos.append(full)
                        except Exception as e:
                            self.update_console(f"Error reading folder {folder}: {e}")

                    seen  = set()
                    final = []
                    for v in selected_videos:
                        k = os.path.normpath(v)
                        if k not in seen:
                            seen.add(k)
                            final.append(k)

                    if final:
                        self.root.after(0, lambda: self._open_grid_view(final))
                    else:
                        self.root.after(0, lambda: messagebox.showwarning("Warning", "No videos found in selection"))

                relevant_dirs = list({os.path.dirname(self.current_subdirs_mapping.get(i, ''))
                                      for i in selection})
                cur = self.get_current_selected_directory()
                if cur:
                    relevant_dirs.append(cur)
                relevant_dirs = list(set(d for d in relevant_dirs if d))
                self._wait_for_scans_then(relevant_dirs,
                                          lambda: threading.Thread(target=collect_selected, daemon=True).start())
            else:
                self.update_console("Loading grid view for entire directory…")

                def collect_all():
                    cache = self.scan_cache.get(selected_dir)
                    if cache:
                        videos, _, _ = cache
                        filtered = [v for v in videos if not self.is_video_excluded(selected_dir, v)]
                        self.root.after(0, lambda: self._open_grid_view(filtered))
                    else:
                        self.root.after(0, lambda: messagebox.showwarning("Warning", "No videos found"))

                self._wait_for_scans_then([selected_dir],
                                          lambda: threading.Thread(target=collect_all, daemon=True).start())

        def _open_grid_view(self, videos):
            if not videos:
                messagebox.showwarning("Warning", "No videos to display")
                return
            self.grid_view_manager.video_preview_manager = self.video_preview_manager
            self._show_embedded_view(
                "gallery",
                lambda frame: self.grid_view_manager.show_grid_view_embedded(
                    frame,
                    videos,
                    self.video_preview_manager,
                    close_callback=self._show_home_view
                )
            )

        def _play_grid_videos(self, videos, start_index=0):
            if not videos:
                return
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
            self._launch_player(self._make_player(videos, all_video_to_dir, all_directories, start_index))

        def _add_to_playlist(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showwarning("Warning", "Please select a directory first")
                return
            selection = self._tree_selection_indices()
            if selection:
                selected_videos = self._resolve_iids_to_paths(selection)
                if selected_videos:
                    self.playlist_manager.add_videos_to_playlist([], selected_videos)
                    self.update_console(f"Added {len(selected_videos)} selected videos to playlist")
                else:
                    messagebox.showwarning("Warning", "No videos found in selected items")
            else:
                search_active = hasattr(self, 'search_query') and self.search_query

                def collect_all_videos():
                    try:
                        all_videos = []
                        if search_active and self.current_subdirs_mapping:
                            for iid, path in self.current_subdirs_mapping.items():
                                if os.path.isfile(path) and is_video(path):
                                    all_videos.append(path)
                        else:
                            cache = self.scan_cache.get(selected_dir)
                            if cache:
                                videos, _, _ = cache
                                all_videos = [v for v in videos if not self.is_video_excluded(selected_dir, v)]

                        def finish():
                            if all_videos:
                                self.playlist_manager.add_videos_to_playlist([], all_videos)
                                self.update_console(f"Added all {len(all_videos)} videos to playlist")
                            else:
                                messagebox.showwarning("Warning", "No videos found to add to playlist")

                        self.root.after(0, finish)
                    except Exception as e:
                        self.root.after(0, lambda: messagebox.showerror("Error", f"Failed to collect videos: {e}"))

                threading.Thread(target=collect_all_videos, daemon=True).start()

        def _manage_playlists(self):
            self._show_embedded_view(
                "playlist",
                lambda frame: self.playlist_manager.show_embedded(
                    frame,
                    close_callback=self._show_home_view
                )
            )

        # ------------------------------------------------------------------
        # Misc
        # ------------------------------------------------------------------

        def setup_status_section(self):
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
                self.update_console(f"Scanning '{os.path.basename(directory)}' for videos…")
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
            return [self.current_subdirs_mapping[iid]
                    for iid in self._tree_get_all_iids()
                    if iid in self.current_subdirs_mapping]

        def toggle_smart_resume(self):
            enabled = bool(self.smart_resume_var.get())
            self.resume_manager.set_resume_enabled(enabled)
            self.start_from_last_played = enabled
            self.smart_resume_enabled   = enabled
            self.save_preferences()

        def _show_settings(self):
            self._show_embedded_view(
                "settings",
                lambda frame: self.settings_manager.show_embedded(
                    frame,
                    close_callback=self._show_home_view
                )
            )

        def _open_dual_player(self, win_id=1):
            selected_dir = self.get_current_selected_directory()
            if selected_dir:
                cache = self.scan_cache.get(selected_dir)
                if cache:
                    videos, _, _ = cache
                    filtered = [v for v in videos if not self.is_video_excluded(selected_dir, v)]
                    if filtered:
                        self.dual_player_manager.load_videos_into_slot(win_id, 1, filtered[:200])
                        return
            self.dual_player_manager.show(win_id)

        def _save_volume_callback(self, volume, is_muted=None):
            self.volume = volume
            if is_muted is not None:
                self.is_muted = is_muted
            self.save_preferences()

        def _is_stream_url(self, path):
            return isinstance(path, str) and (path.startswith("http://") or path.startswith("https://"))

        def _collect_videos_from_pseudo_dir(self, root_pseudo_dir, pseudo_dir):
            cache = self.scan_cache.get(root_pseudo_dir)
            if not cache:
                return []
            videos, video_to_dir, directories = cache
            prefix = pseudo_dir.rstrip('/') + '/'
            return [v for v in videos
                    if (p := video_to_dir.get(v)) and (p == pseudo_dir or p.startswith(prefix))]

        def _resolve_selection_indices_to_videos(self, selected_dir, indices):
            """Legacy shim — indices here are iids (strings)."""
            return self._resolve_iids_to_paths(indices)

        def _wait_for_scans_then(self, directories, callback):
            def _wait():
                deadline = time.time() + 15.0
                while time.time() < deadline:
                    with self._pending_scans_lock:
                        still_pending = [d for d in directories if d in self.pending_scans]
                    if not still_pending:
                        break
                    time.sleep(0.1)
                self.root.after(0, callback)
            ManagedThread(target=_wait, name="WaitForScans").start()

        # ------------------------------------------------------------------
        # draw_slider + speed helpers (unchanged)
        # ------------------------------------------------------------------

        def draw_slider(self):
            if not hasattr(self, 'speed_canvas'):
                return
            self.speed_canvas.delete("all")
            canvas_width = self.speed_canvas.winfo_width()
            if canvas_width <= 1:
                canvas_width = self.slider_width
            canvas_height = 6
            track_y = canvas_height // 2
            self.speed_canvas.create_rectangle(0, track_y - 1, canvas_width, track_y + 1,
                                               fill="#e0e0e0", outline="", tags="track")
            progress = (self.slider_current - self.slider_min) / (self.slider_max - self.slider_min)
            handle_x = progress * canvas_width
            self.speed_canvas.create_rectangle(0, track_y - 1, handle_x, track_y + 1,
                                               fill=self.accent_color, outline="", tags="progress")
            handle_radius = 8
            self.speed_canvas.create_oval(
                handle_x - handle_radius, track_y - handle_radius,
                handle_x + handle_radius, track_y + handle_radius,
                fill="gray", outline=self.accent_color, width=2, tags="handle"
            )
            for speed in [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]:
                marker_progress = (speed - self.slider_min) / (self.slider_max - self.slider_min)
                marker_x = marker_progress * canvas_width
                if speed == 1.0:
                    self.speed_canvas.create_oval(marker_x - 2, track_y - 2, marker_x + 2, track_y + 2,
                                                  fill=self.accent_color, outline="", tags="marker")
                else:
                    self.speed_canvas.create_oval(marker_x - 1, track_y - 1, marker_x + 1, track_y + 1,
                                                  fill="#cccccc", outline="", tags="marker")

        def on_slider_configure(self, event):   self.draw_slider()
        def on_slider_click(self, event):       self.dragging = True; self.update_slider_from_mouse(event.x)
        def on_slider_drag(self, event):
            if self.dragging: self.update_slider_from_mouse(event.x)
        def on_slider_release(self, event):     self.dragging = False

        def update_slider_from_mouse(self, x):
            canvas_width = self.speed_canvas.winfo_width()
            if canvas_width <= 1:
                return
            progress  = max(0, min(1, x / canvas_width))
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

        # ------------------------------------------------------------------
        # Settings changed callback
        # ------------------------------------------------------------------

        def _on_settings_changed(self, new_settings):
            self.update_console("Settings updated")
            if hasattr(self, 'video_preview_manager'):
                self.video_preview_manager.set_preview_duration(new_settings.preview_duration)
                self.video_preview_manager.set_video_preview_enabled(new_settings.use_video_preview)
            if hasattr(self, 'resume_manager'):
                self.resume_manager._auto_cleanup_days = new_settings.auto_cleanup_days
            if getattr(self, '_active_player', None) is not None:
                try:
                    self._active_player.set_hotkeys(new_settings.hotkeys)
                except Exception as e:
                    self.update_console(f"Hotkey reload error: {e}")
            if getattr(self, '_active_player', None) is not None:
                try:
                    self._active_player.set_gaming_mode(new_settings.gaming_mode)
                except Exception:
                    pass
            if hasattr(self, 'dual_player_manager'):
                if new_settings.dual_window_enabled:
                    self.grid_view_manager.set_play_in_dual_player_win2_1_callback(
                        lambda videos: self.dual_player_manager.load_videos_into_slot(2, 1, videos))
                    self.grid_view_manager.set_play_in_dual_player_win2_2_callback(
                        lambda videos: self.dual_player_manager.load_videos_into_slot(2, 2, videos))
                    self.grid_view_manager.set_play_in_dual_player_win2_3_callback(
                        lambda videos: self.dual_player_manager.load_videos_into_slot(2, 3, videos))
                else:
                    self.grid_view_manager.set_play_in_dual_player_win2_1_callback(None)
                    self.grid_view_manager.set_play_in_dual_player_win2_2_callback(None)
                    self.grid_view_manager.set_play_in_dual_player_win2_3_callback(None)

            if hasattr(self, 'exclusion_tree'):
                old_show = getattr(self, '_last_show_annotations', None)
                new_show = new_settings.show_video_annotations_in_tree
                if old_show is None or old_show != new_show:
                    self._last_show_annotations = new_show
                    self._toggle_annotation_columns(new_show)

        def _toggle_annotation_columns(self, enabled):
            left_width = self.dir_section.winfo_width() if hasattr(self, 'dir_section') else 0

            if enabled:
                self.exclusion_tree.configure(columns=("rating", "tags", "size"))
                self.exclusion_tree.column("rating", width=100, minwidth=100, stretch=False, anchor="center")
                self.exclusion_tree.column("tags", width=180, minwidth=120, stretch=False, anchor="w")
                self.exclusion_tree.column("size", width=90, minwidth=90, stretch=False, anchor="e")
                self.exclusion_tree.heading("rating", text="Rating", anchor="center")
                self.exclusion_tree.heading("tags", text="Tags", anchor="w")
                self.exclusion_tree.heading("size", text="Size", anchor="e")
            else:
                self.exclusion_tree.configure(columns=("size",))
                self.exclusion_tree.column("size", width=90, minwidth=90, stretch=False, anchor="e")
                self.exclusion_tree.heading("size", text="Size", anchor="e")

            cur = self.get_current_selected_directory()
            if cur:
                self.load_subdirectories(cur)

            if left_width > 10:
                self.dir_section.config(width=left_width)
                self.dir_section.pack_propagate(False)

        def _clear_thumbnail_cache(self):
            try:
                self.video_preview_manager.clear_cache()
                self.update_console("Thumbnail cache cleared.")
                return True
            except Exception as e:
                self.update_console(f"Error clearing thumbnail cache: {e}")
                return False

        # ------------------------------------------------------------------
        # Action buttons (toolbar) — identical to original
        # ------------------------------------------------------------------

        def setup_action_buttons(self):
            def _tb_colors():
                if self.dark_mode:
                    return {
                        "bg": "#1E1F22", "fg": "#A9B7C6",
                        "hover_bg": "#2D5A8E", "hover_fg": "#FFFFFF",
                        "active_bg": "#1A4070", "active_fg": "#FFFFFF",
                        "play_fg": "#FF6B6B", "play_hover": "#C0392B",
                        "sep": "#3A3B3E",
                    }
                else:
                    return {
                        "bg": "#ECECEC", "fg": "#2B2B2B",
                        "hover_bg": "#DCDCDC", "hover_fg": "#000000",
                        "active_bg": "#CCCCCC", "active_fg": "#000000",
                        "play_fg": "#c0392b", "play_hover": "#992d22",
                        "play_hover_bg": "#c0392b",
                        "sep": "#E0E0E0",
                    }

            self._tb_colors = _tb_colors
            self.toolbar = tk.Frame(self.root, bg=_tb_colors()["bg"], height=28)
            self.toolbar.pack(side=tk.TOP, fill=tk.X, before=self.main_frame)
            self.toolbar.pack_propagate(False)
            self._toolbar_btns = {}

            def make_dropdown_menu(entries):
                c    = _tb_colors()
                menu = tk.Menu(self.root, tearoff=0,
                               bg=c["bg"], fg=c["fg"],
                               activebackground=c["hover_bg"],
                               activeforeground=c["hover_fg"],
                               relief="flat", bd=1, font=("Segoe UI", 9))
                for entry in entries:
                    if entry is None:
                        menu.add_separator()
                    else:
                        lbl, cmd = entry
                        menu.add_command(label=lbl, command=cmd)
                return menu

            def make_toolbar_btn(text, command=None, menu=None, play=False):
                c          = _tb_colors()
                fg         = c["play_fg"] if play else c["fg"]
                font_weight = "bold" if play else "normal"
                btn = tk.Label(self.toolbar, text=text,
                               bg=c["bg"], fg=fg,
                               font=("Segoe UI", 9, font_weight),
                               padx=10, pady=4, cursor="hand2")
                btn.pack(side=tk.LEFT)
                self._toolbar_btns[text] = btn

                def on_enter(e, b=btn):
                    b.config(bg=_tb_colors()["hover_bg"], fg=_tb_colors()["hover_fg"])
                def on_leave(e, b=btn, p=play):
                    cc = _tb_colors(); b.config(bg=cc["bg"], fg=cc["play_fg"] if p else cc["fg"])
                def on_press(e, b=btn):
                    b.config(bg=_tb_colors()["active_bg"], fg=_tb_colors()["active_fg"])
                def on_release(e, b=btn, m=menu, cmd=command):
                    b.config(bg=_tb_colors()["hover_bg"], fg=_tb_colors()["hover_fg"])
                    if m:
                        try: m.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())
                        finally: m.grab_release()
                    elif cmd:
                        cmd()

                btn.bind("<Enter>",           on_enter)
                btn.bind("<Leave>",           on_leave)
                btn.bind("<ButtonPress-1>",   on_press)
                btn.bind("<ButtonRelease-1>", on_release)

                return btn

            file_menu = make_dropdown_menu([
                ("Add Directory",         self.add_directory),
                ("Add Google Drive Link", self.add_drive_link),
                None,
                ("Exit",                  self.cancel),
            ])
            make_toolbar_btn("File", menu=file_menu)

            self._view_menu = make_dropdown_menu([
                ("Hide Console" if self.show_console else "Show Console", self.toggle_console),
                None,
                ("Filter / Sort",     self._show_filter_dialog),
            ])
            make_toolbar_btn("View", menu=self._view_menu)

            self._loop_mode_var = tk.StringVar(value=self.loop_mode)
            c = _tb_colors()
            _sel_color = "#4A9EFF" if self.dark_mode else "#2d89ef"
            loop_sub = tk.Menu(self.root, tearoff=0,
                               bg=c["bg"], fg=c["fg"],
                               activebackground=c["hover_bg"],
                               activeforeground=c["hover_fg"],
                               selectcolor=_sel_color,
                               relief="flat", bd=1, font=("Segoe UI", 9))
            for mode, lbl in [("loop_on", "Loop On"), ("loop_off", "Loop Off"), ("shuffle", "Shuffle")]:
                loop_sub.add_radiobutton(
                    label=lbl, variable=self._loop_mode_var, value=mode,
                    command=lambda m=mode: self._set_loop_mode_menu(m))
            self._loop_sub_menu = loop_sub

            playback_menu = tk.Menu(self.root, tearoff=0,
                                    bg=c["bg"], fg=c["fg"],
                                    activebackground=c["hover_bg"],
                                    activeforeground=c["hover_fg"],
                                    relief="flat", bd=1, font=("Segoe UI", 9))
            playback_menu.add_cascade(label="Loop Mode", menu=loop_sub)
            make_toolbar_btn("Playback", menu=playback_menu)
            make_toolbar_btn("Settings", command=self._show_settings)

            _media_pill_commands = {
                "🎵 Playlist":   self._manage_playlists,
                "⬛ Queue":      self._show_queue_manager,
                "♥ Favourites": self._show_favorites_manager,
                "🕐 History":   self._show_watch_history,
                "🏷 Tags & Ratings": self._show_annotation_browser,
            }
            _media_pill_commands.update({
                "Home": self._show_home_view,
                "Gallery": self._show_grid_view,
            })
            self._view_tab_labels = {
                "home": "Home",
                "gallery": "Gallery",
                "playlist": "ðŸŽµ Playlist",
                "queue": "â¬› Queue",
                "favourites": "â™¥ Favourites",
                "history": "ðŸ• History",
                "tags": "ðŸ· Tags & Ratings",
            }
            for _view_name, _needle in [
                ("playlist", "Playlist"),
                ("queue", "Queue"),
                ("favourites", "Favourites"),
                ("history", "History"),
                ("tags", "Tags & Ratings"),
            ]:
                self._view_tab_labels[_view_name] = next(
                    (lbl for lbl in _media_pill_commands if _needle in lbl),
                    self._view_tab_labels[_view_name]
                )
            self._media_pill_btns = {}

            def _make_media_pill(label):
                a   = self.pill_accents(label)
                c   = _tb_colors()
                btn = tk.Label(self.toolbar, text=label,
                               bg=c["bg"], fg=a[0],
                               font=("Segoe UI", 9, "bold"),
                               padx=9, pady=3, cursor="hand2",
                               relief="flat", highlightthickness=1,
                               highlightbackground=a[0], highlightcolor=a[0])
                btn.pack(side=tk.LEFT, padx=(0, 3), pady=2)
                self._media_pill_btns[label] = btn

                def on_enter(e, b=btn, lbl=label):
                    a = self.pill_accents(lbl); b.config(bg=a[1], fg=a[2], highlightbackground=a[1])
                def on_leave(e, b=btn, lbl=label):
                    if getattr(self, "_view_tab_labels", {}).get(getattr(self, "_active_app_view", "home")) == lbl:
                        return
                    a = self.pill_accents(lbl); cc = _tb_colors()
                    b.config(bg=cc["bg"], fg=a[0], highlightbackground=a[0])
                def on_press(e, b=btn, lbl=label):
                    a = self.pill_accents(lbl); b.config(bg=a[3], fg=a[2], highlightbackground=a[3])
                def on_release(e, b=btn, lbl=label, cmd=_media_pill_commands[label]):
                    a = self.pill_accents(lbl); b.config(bg=a[1], fg=a[2], highlightbackground=a[1]); cmd()

                btn.bind("<Enter>",           on_enter)
                btn.bind("<Leave>",           on_leave)
                btn.bind("<ButtonPress-1>",   on_press)
                btn.bind("<ButtonRelease-1>", on_release)

            for _pill_label in ["🎵 Playlist", "⬛ Queue", "♥ Favourites", "🕐 History", "🏷 Tags & Ratings"]:
                _make_media_pill(_pill_label)

            _make_media_pill("Home")
            _make_media_pill("Gallery")
            try:
                first_media = self._media_pill_btns[self._view_tab_labels["playlist"]]
                self._media_pill_btns["Home"].pack_configure(before=first_media)
                self._media_pill_btns["Gallery"].pack_configure(before=first_media)
            except Exception:
                pass
            self._refresh_media_pill_state()

            self.theme_toolbar_btn = tk.Label(
                self.toolbar, text="🌙" if not self.dark_mode else "☀",
                bg=_tb_colors()["bg"], fg=_tb_colors()["fg"],
                font=("Segoe UI", 10), padx=8, pady=4, cursor="hand2")
            self.theme_toolbar_btn.pack(side=tk.RIGHT, padx=(0, 2))

            def _theme_enter(e):  self.theme_toolbar_btn.config(bg=_tb_colors()["hover_bg"],  fg=_tb_colors()["hover_fg"])
            def _theme_leave(e):  self.theme_toolbar_btn.config(bg=_tb_colors()["bg"],         fg=_tb_colors()["fg"])
            def _theme_press(e):  self.theme_toolbar_btn.config(bg=_tb_colors()["active_bg"], fg=_tb_colors()["active_fg"])
            def _theme_release(e):
                self.theme_toolbar_btn.config(bg=_tb_colors()["hover_bg"], fg=_tb_colors()["hover_fg"])
                self._toggle_theme_menu()
            self.theme_toolbar_btn.bind("<Enter>",           _theme_enter)
            self.theme_toolbar_btn.bind("<Leave>",           _theme_leave)
            self.theme_toolbar_btn.bind("<ButtonPress-1>",   _theme_press)
            self.theme_toolbar_btn.bind("<ButtonRelease-1>", _theme_release)

            self.play_toolbar_btn = tk.Label(
                self.toolbar, text="▶  Play Videos",
                bg=_tb_colors()["bg"], fg=_tb_colors()["play_fg"],
                font=("Segoe UI", 9, "bold"), padx=12, pady=4, cursor="hand2")
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
            self.play_toolbar_btn.bind("<Enter>",           _play_enter)
            self.play_toolbar_btn.bind("<Leave>",           _play_leave)
            self.play_toolbar_btn.bind("<ButtonPress-1>",   _play_press)
            self.play_toolbar_btn.bind("<ButtonRelease-1>", _play_release)

            self.button_frame = tk.Frame(self.main_frame, bg=self.bg_color)
            self.button_frame.pack(fill=tk.X)

        # ------------------------------------------------------------------
        # Cancel / shutdown
        # ------------------------------------------------------------------

        def cancel(self):
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

        # ------------------------------------------------------------------
        # Google Drive dialog (unchanged)
        # ------------------------------------------------------------------

        def _ask_drive_link_dialog(self):
            dlg = tk.Toplevel(self.root)
            dlg.withdraw()
            dlg.title("Add Google Drive Link")
            dlg.configure(bg=self.bg_color)
            dlg.transient(self.root)
            dlg.grab_set()
            dlg.geometry("560x260")
            try:
                dlg.update_idletasks()
                x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 280
                y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 130
                dlg.geometry(f"+{x}+{y}")
            except Exception:
                pass

            result = {"url": None}
            container = tk.Frame(dlg, bg=self.bg_color)
            container.pack(fill=tk.BOTH, expand=True, padx=18, pady=16)

            tk.Label(container, text="Add Google Drive Link",
                     font=self.header_font, bg=self.bg_color, fg=self.text_color).pack(anchor="w")
            tk.Label(container,
                     text="Paste a public Google Drive folder or file link.",
                     font=self.small_font, bg=self.bg_color, fg=self.accent_color,
                     wraplength=520, justify=tk.LEFT).pack(anchor="w", pady=(6, 10))

            entry_frame = tk.Frame(container, bg=self.bg_color)
            entry_frame.pack(fill=tk.X)

            url_var = tk.StringVar()
            entry = tk.Entry(entry_frame, textvariable=url_var,
                             font=self.normal_font, bg=self.listbox_bg, fg=self.listbox_fg,
                             relief=tk.FLAT, insertbackground=self.text_color,
                             highlightthickness=1,
                             highlightbackground=self.accent_color, highlightcolor=self.accent_color)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6)

            def paste_clipboard():
                try:
                    import win32clipboard as wcb, win32con
                    wcb.OpenClipboard()
                    data = wcb.GetClipboardData(win32con.CF_UNICODETEXT)
                    wcb.CloseClipboard()
                    if data:
                        url_var.set(data.strip())
                        entry.icursor(tk.END)
                        validate_now()
                except Exception:
                    pass

            self.create_button(entry_frame, text="Paste", command=paste_clipboard,
                               variant="secondary", size="sm").pack(side=tk.LEFT, padx=(8, 0))

            validate_lbl = tk.Label(container, text="", font=self.small_font,
                                    bg=self.bg_color, fg="#e17055")
            validate_lbl.pack(anchor="w", pady=(6, 0))

            btns = tk.Frame(container, bg=self.bg_color)
            btns.pack(anchor="e", pady=(14, 0))

            def validate_url(u):
                if not u: return False
                try:
                    return (self.drive_manager is not None and
                            self.drive_manager._extract_id_and_type(u) is not None)
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

            self.create_button(btns, text="Add Link", command=on_submit,
                               variant="primary", size="md").pack(side=tk.RIGHT, padx=(8, 0))
            self.create_button(btns, text="Cancel", command=on_cancel,
                               variant="secondary", size="md").pack(side=tk.RIGHT)

            try:
                import win32clipboard as wcb, win32con
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
            apply_icon(dlg)
            dlg.deiconify()
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
            progress_window.withdraw()
            progress_window.title("Google Drive")
            progress_window.geometry("420x140")
            progress_window.configure(bg=self.bg_color)
            progress_window.transient(self.root)
            progress_window.grab_set()

            lbl = tk.Label(progress_window,
                           text="Fetching contents… Large Drive folders can take a while…",
                           font=self.normal_font, bg=self.bg_color, fg=self.text_color,
                           wraplength=380, justify=tk.LEFT)
            lbl.pack(padx=16, pady=(16, 8), anchor="w")

            bar = ttk.Progressbar(progress_window, mode='indeterminate', length=380)
            bar.pack(padx=16, pady=(0, 8))
            try: bar.start(10)
            except Exception: pass

            status_lbl = tk.Label(progress_window, text="Starting…",
                                  font=self.small_font, bg=self.bg_color, fg="#666666",
                                  wraplength=380, justify=tk.LEFT)
            status_lbl.pack(padx=16, pady=(0, 8), anchor="w")
            apply_icon(progress_window)
            progress_window.deiconify()

            def set_status(msg):
                try: status_lbl.config(text=msg); self.update_console(msg)
                except Exception: pass

            def finish_cleanup():
                try: bar.stop()
                except Exception: pass
                try: progress_window.destroy()
                except Exception: pass

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
                        folder_id  = source["id"]
                        pseudo_dir = f"gdrive://folder/{folder_id}"
                        if pseudo_dir in self.selected_dirs:
                            self.root.after(0, lambda: (set_status("Drive link already added."), finish_cleanup()))
                            return
                        self.root.after(0, lambda: set_status("Listing folder recursively…"))
                        videos, video_to_dir, directories = \
                            self.drive_manager.gather_videos_with_directories_for_source(source)

                        def apply_folder():
                            self.scan_cache.set(pseudo_dir, (videos, video_to_dir, directories))
                            self.selected_dirs.append(pseudo_dir)
                            self.dir_listbox.insert(tk.END, f"Drive Folder {folder_id}")
                            self.update_console(
                                f"Added Google Drive folder: {folder_id} with {len(videos)} videos")
                            self.update_video_count()
                            self.save_preferences()
                            finish_cleanup()

                        self.root.after(0, apply_folder)
                    else:
                        file_id    = source["id"]
                        pseudo_dir = f"gdrive://file/{file_id}"
                        if pseudo_dir in self.selected_dirs:
                            self.root.after(0, lambda: (set_status("Drive link already added."), finish_cleanup()))
                            return
                        self.root.after(0, lambda: set_status("Preparing file stream…"))
                        videos, video_to_dir, directories = \
                            self.drive_manager.gather_videos_with_directories_for_source(source)

                        def apply_file():
                            self.scan_cache.set(pseudo_dir, (videos, video_to_dir, directories))
                            self.selected_dirs.append(pseudo_dir)
                            self.dir_listbox.insert(tk.END, f"Drive File {file_id}")
                            self.update_console(f"Added Google Drive file: {file_id}")
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

    root = TkinterDnD.Tk()
    root.withdraw()

    def _launch():
        DirectorySelector(root)
        root.update_idletasks()
        root.deiconify()

    show_splash(root, on_done=_launch, duration_ms=1500)
    root.mainloop()


if __name__ == "__main__":
    select_multiple_folders_and_play()
