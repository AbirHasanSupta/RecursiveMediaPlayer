from embedded_player import EmbeddedPlayer
from icon_helper import apply_icon
from managers.annotation_browser_manager import AnnotationBrowserManager
from managers.video_metadata_manager import VideoAnnotationService
from splash import show_splash
import random as _random

try:
    from version import __version__, __commit__, __build__
except ImportError:
    __version__ = __commit__ = __build__ = "dev"

import threading
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import filedialog, messagebox, ttk
from tkinter.font import Font
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from key_press import reload_hotkeys
from managers.favorites_manager import FavoritesManager
from managers.filter_sort_manager import AdvancedFilterSortManager
from managers.filter_sort_ui import FilterSortUI
from managers.grid_view_manager import GridViewManager
from managers.resource_manager import ThreadSafeDict, get_resource_manager, ManagedExecutor, MemoryMonitor, \
    ManagedThread
from theme import ThemeSelector
from utils import gather_videos_with_directories, is_video, gather_videos
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
            self._view_tab_labels = {}  # will be filled in setup_action_buttons
            self._media_pill_btns = {}
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
            self.expand_all_default = False
            self.save_directories = True
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
            self._qa_seed = _random.randint(0, 10 ** 9)
            self.apply_theme()
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
            _orig_attach = self.video_preview_manager.attach_to_listbox

            def _patched_attach(widget, mapping, _orig=_orig_attach):
                _orig(widget, mapping)
                if widget is self.exclusion_tree:
                    self.exclusion_tree.bind("<Motion>", self._tree_hover_motion, "+")
                    self.exclusion_tree.bind("<Leave>", self._tree_hover_leave)

            self.video_preview_manager.attach_to_listbox = _patched_attach
            self.video_preview_manager.set_preview_duration(app_settings.preview_duration)
            self.video_preview_manager.set_video_preview_enabled(app_settings.use_video_preview)

            self.grid_view_manager = GridViewManager(self.root, self, self.update_console)
            self.grid_view_manager.set_play_callback(self._play_grid_videos)

            self.playlist_manager = PlaylistManager(self.root, self)
            self.playlist_manager.set_play_callback(self._play_playlist_videos)
            self.playlist_manager.set_log_callback(self.update_console)
            self.playlist_manager.set_video_preview_manager(self.video_preview_manager)
            self.playlist_manager.set_grid_view_manager(self.grid_view_manager)
            self.playlist_manager.set_add_to_favorites_callback(
                lambda videos: self._add_videos_to_favorites_smart(videos)
            )
            self.playlist_manager.set_add_to_queue_callback(
                lambda videos: self.queue_manager.add_to_queue(videos, added_from="playlist")
            )
            self.playlist_manager.ui.video_preview_manager = self.video_preview_manager

            self.watch_history_manager = WatchHistoryManager(self.root, self)
            self.watch_history_manager.set_settings_manager(self.settings_manager)
            self.watch_history_manager.set_play_callback(self._play_history_videos)
            self.watch_history_manager.set_video_preview_manager(self.video_preview_manager)
            self.watch_history_manager.set_grid_view_manager(self.grid_view_manager)
            self.watch_history_manager.set_add_to_playlist_callback(
                lambda videos: self.playlist_manager.add_videos_to_playlist([], videos)
            )
            self.watch_history_manager.set_add_to_queue_callback(
                lambda videos: self.queue_manager.add_to_queue(videos, added_from="watch_history")
            )
            self.watch_history_manager.set_add_to_favourites_callback(
                lambda videos: self._add_videos_to_favorites_smart(videos)
            )
            self.watch_history_manager.set_remove_from_favourites_callback(
                lambda videos: self._remove_videos_from_favorites_smart(videos)
            )
            self.watch_history_manager.set_is_favourite_callback(
                lambda video_path: self._is_favourite_smart(video_path)
            )

            self.resume_manager = ResumePlaybackManager()
            self.resume_manager.set_resume_enabled(self.smart_resume_enabled)

            self.queue_manager = VideoQueueManager(self.root, self)
            self.queue_manager.set_play_callback(self._play_queue_videos)
            self.queue_manager.set_video_preview_manager(self.video_preview_manager)
            self.queue_manager.set_grid_view_manager(self.grid_view_manager)
            self.queue_manager.set_add_to_favorites_callback(
                lambda videos: self._add_videos_to_favorites_smart(videos)
            )
            self.queue_manager.set_add_to_playlist_callback(
                lambda videos: self.playlist_manager.add_videos_to_playlist([], videos)
            )

            self.favorites_manager = FavoritesManager(self.root, self)
            self.favorites_manager.set_play_callback(self._play_favorites_videos)
            self.favorites_manager.set_video_preview_manager(self.video_preview_manager)
            self.favorites_manager.set_grid_view_manager(self.grid_view_manager)
            self.favorites_manager.set_on_removed_callback(self._refresh_tree_after_fav_change)
            self.favorites_manager.set_add_to_queue_callback(
                lambda videos: self.queue_manager.add_to_queue(videos, added_from="favorites")
            )
            self.favorites_manager.set_add_to_playlist_callback(
                lambda videos: self.playlist_manager.add_videos_to_playlist([], videos)
            )

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
            self.annotation_browser.set_add_to_playlist_callback(
                lambda videos: self.playlist_manager.add_videos_to_playlist([], videos)
            )
            self.annotation_browser.set_add_to_queue_callback(
                lambda videos: self.queue_manager.add_to_queue(videos, added_from="annotation_browser")
            )
            self.annotation_browser.set_add_to_favourites_callback(
                lambda videos: self._add_videos_to_favorites_smart(videos)
            )
            self.annotation_browser.set_remove_from_favourites_callback(
                lambda videos: self._remove_videos_from_favorites_smart(videos)
            )
            self.annotation_browser.set_is_favourite_callback(
                lambda video_path: self._is_favourite_smart(video_path)
            )

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
                lambda videos: self._add_videos_to_favorites_smart(videos)
            )
            self.grid_view_manager.set_remove_from_favourites_callback(
                lambda videos: self._remove_videos_from_favorites_smart(videos)
            )
            self.grid_view_manager.set_is_favourite_callback(
                lambda video_path: self._is_favourite_smart(video_path)
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
            self.grid_view_manager.set_exclude_video_callback(self._grid_exclude_video)
            self.grid_view_manager.set_remove_exclusion_video_callback(self._grid_remove_exclusion_video)
            self.grid_view_manager.set_locate_in_panel_callback(self.locate_in_directory_panel)
            self.playlist_manager.set_locate_in_panel_callback(self.locate_in_directory_panel)
            self.watch_history_manager.set_locate_in_panel_callback(self.locate_in_directory_panel)
            self.favorites_manager.set_locate_in_panel_callback(self.locate_in_directory_panel)
            self.queue_manager.set_locate_in_panel_callback(self.locate_in_directory_panel)
            self.annotation_browser.set_locate_in_panel_callback(self.locate_in_directory_panel)

            self.settings_manager.ui.cleanup_resume_callback = lambda: self.resume_manager.service.cleanup_old_positions(
                self.settings_manager.get_settings().auto_cleanup_days)
            self.settings_manager.ui.cleanup_history_callback = lambda: self.watch_history_manager.service.cleanup_old_entries(
                self.settings_manager.get_settings().auto_cleanup_days)
            self.settings_manager.ui.clear_thumbnails_callback = lambda: self._clear_thumbnail_cache()
            self.settings_manager.ui.video_preview_manager = self.video_preview_manager
            self.settings_manager.ui.clear_metadata_callback = lambda: self._clear_metadata_cache()
            self.settings_manager.ui.get_metadata_info_callback = lambda: self._get_metadata_cache_info()
            self.settings_manager.ui.filter_sort_manager = self.filter_sort_manager
            self.root.after(0, self._fix_pill_colors_initial)
            self.root.after(100, self._show_home_view)
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
                'dual_player_manager', 'annotation_browser_manager'
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
            # Dashboard-aligned palette (apply_theme refines for dark mode)
            self.bg_color = "#F7F9FC"
            self.surface_color = "#FFFFFF"
            self.accent_color = "#5E81F4"
            self.accent_secondary = "#FF6B6B"
            self.text_color = "#1E2A3A"
            self.text_muted = "#5B6C8F"
            self.border_color = "#E2E8F0"
            self.hover_color = "#EDF2F7"
            self.listbox_bg = "#FFFFFF"
            self.listbox_fg = self.text_color
            self.listbox_select_bg = self.accent_color
            self.console_bg = "#1E2A3A"
            self.console_fg = "#F7F9FC"
            self.frame_border = self.border_color
            self.header_color = self.text_color
            self.entry_bg = "#FFFFFF"
            self.entry_fg = self.text_color
            self.entry_border = "#E2E8F0"
            self.muted_fg = self.text_muted
            self.alt_row_color = "#F7F9FC"
            self.badge_bg = "#EDF2F7"
            self.badge_fg = self.text_color
            self.divider_color = "#E2E8F0"
            self.excluded_color = "#C44A4A"
            self.favorite_color = "#8F6B08"

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
            self.tree_font_excl_video = Font(
                family="Segoe UI", size=10, slant="italic", overstrike=True)

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
                    padx, pady = 12, 6
                elif size == "lg":
                    use_font = Font(family=self.normal_font.actual().get("family", "Segoe UI"),
                                    size=self.normal_font.actual().get("size", 10) + 2,
                                    weight="bold")
                    padx, pady = 16, 10
                else:
                    use_font = self.normal_font
                    padx, pady = 14, 8
            else:
                use_font = font
                padx, pady = (14, 8) if size == "md" else ((12, 6) if size == "sm" else (16, 10))

            btn = tk.Button(
                parent, text=text, command=command, font=use_font,
                bg=bg, fg=fg, activebackground=active_bg, activeforeground=fg,
                relief=tk.FLAT, bd=0, padx=padx, pady=pady,
                cursor="hand2", highlightthickness=0
            )
            btn._variant = variant
            self._bind_button_hover(btn, variant)
            return btn

        def setup_main_layout(self):
            self._active_app_view = "home"
            self.active_embedded_manager = None
            self.embedded_view_frame = None
            self._directory_panel_mode = "expanded"
            self._dir_panel_width = 380
            self.main_frame = tk.Frame(self.root, bg=self.bg_color, padx=16, pady=14)
            self.main_frame.pack(fill=tk.BOTH, expand=True)
            self.content_frame = tk.Frame(self.main_frame, bg=self.bg_color)
            self.content_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

            self._sidebar_panel = tk.Frame(self.content_frame, bg=self.surface_color, width=52)
            self._sidebar_panel.pack(side=tk.LEFT, fill=tk.Y)
            self._sidebar_panel.pack_propagate(False)
            self._sidebar_divider = tk.Frame(self.content_frame, bg=self.border_color, width=1)
            self._sidebar_divider.pack(side=tk.LEFT, fill=tk.Y)

            self.workspace_frame = tk.Frame(self.content_frame, bg=self.bg_color)
            self.workspace_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

            self.workspace_header = tk.Frame(self.workspace_frame, bg=self.bg_color)
            self.workspace_header.pack(fill=tk.X, pady=(0, 10))

            title_block = tk.Frame(self.workspace_header, bg=self.bg_color)
            title_block.pack(side=tk.LEFT, fill=tk.Y)
            self.workspace_title_label = tk.Label(
                title_block, text="Home", font=self.header_font,
                bg=self.bg_color, fg=self.text_color
            )
            # title label intentionally not packed — each view has its own header
            self.workspace_context_label = tk.Label(
                title_block, text="Welcome to Recursive Video Player",
                font=self.normal_font, bg=self.bg_color, fg=self.text_muted
            )
            self.workspace_context_label.pack(anchor="w", pady=(4, 0))

            self.workspace_nav = tk.Frame(self.workspace_header, bg=self.bg_color)
            self.workspace_nav.pack(side=tk.RIGHT, anchor="e")

            self.workspace_body = tk.Frame(self.workspace_frame, bg=self.bg_color)
            self.workspace_body.pack(fill=tk.BOTH, expand=True)

        def _show_home_view(self):
            self._cleanup_active_manager()
            if self.embedded_view_frame and self.embedded_view_frame.winfo_exists():
                self.embedded_view_frame.destroy()
            self.embedded_view_frame = None
            if hasattr(self, 'exclusion_section') and self.exclusion_section.winfo_ismapped():
                self.exclusion_section.pack_forget()
            self._set_workspace_title("Home", "Welcome to Recursive Video Player")
            self._active_app_view = "home"
            self._refresh_media_pill_state()
            self._render_home_dashboard()

        def _render_home_dashboard(self):
            frame = self._ensure_embedded_view_frame()
            for child in frame.winfo_children():
                child.destroy()
            frame.pack(fill=tk.BOTH, expand=True)

            bg = self.bg_color
            surface = self.surface_color
            surface2 = self.alt_row_color
            border = self.border_color
            text_pri = self.text_color
            text_sec = self.text_muted
            accent = self.accent_color
            accent2 = self.accent_secondary

            frame.configure(bg=bg)

            def _bind_hover(card_f, inner_f, cmd, col):
                def _enter(e):
                    card_f.config(bg=self.hover_color, highlightbackground=col)
                    inner_f.config(bg=self.hover_color)
                    for w in inner_f.winfo_children():
                        try:
                            if isinstance(w, tk.Label) and w.cget("bg") == surface:
                                w.config(bg=self.hover_color)
                        except Exception:
                            pass
                def _leave(e):
                    card_f.config(bg=surface, highlightbackground=border)
                    inner_f.config(bg=surface)
                    for w in inner_f.winfo_children():
                        try:
                            if isinstance(w, tk.Label) and w.cget("bg") == self.hover_color:
                                w.config(bg=surface)
                        except Exception:
                            pass
                for w in [card_f, inner_f] + list(inner_f.winfo_children()):
                    try:
                        w.bind("<Button-1>", lambda e, fn=cmd: fn())
                        w.bind("<Enter>", _enter)
                        w.bind("<Leave>", _leave)
                    except Exception:
                        pass

            hist_stats = {}
            all_history = []
            if hasattr(self, 'watch_history_manager'):
                try:
                    hist_stats = self.watch_history_manager.get_history_stats()
                    all_history = self.watch_history_manager.service.get_all_history()
                except Exception:
                    pass

            today_n = hist_stats.get('today_count', 0)
            week_n = hist_stats.get('week_count', 0)
            unique_n = hist_stats.get('unique_videos', 0)

            avg_pct = 0.0
            tracked = [e.completion_percentage for e in all_history if e.completion_percentage > 0]
            if tracked:
                avg_pct = sum(tracked) / len(tracked)

            total_lib_vids = sum(
                sum(1 for v in (self.scan_cache.get(d) or ([],))[0]
                    if not self.is_video_excluded(d, v))
                for d in self.selected_dirs
            ) if hasattr(self, 'scan_cache') else 0

            day_counts = [0] * 7
            today_date = datetime.now().date()
            for e in all_history:
                try:
                    delta = (today_date - datetime.fromisoformat(e.watched_at).date()).days
                    if 0 <= delta < 7:
                        day_counts[6 - delta] += 1
                except Exception:
                    pass

            dir_counts: dict = {}
            for e in all_history:
                dk = os.path.basename(e.directory_path) or e.directory_path
                dir_counts[dk] = dir_counts.get(dk, 0) + 1
            top_dirs = sorted(dir_counts.items(), key=lambda x: x[1], reverse=True)[:4]

            pct_watched = (unique_n / total_lib_vids * 100) if total_lib_vids > 0 else 0

            canvas = tk.Canvas(frame, bg=bg, highlightthickness=0, bd=0)
            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            inner = tk.Frame(canvas, bg=bg)
            inner_win = canvas.create_window((0, 0), window=inner, anchor="nw")

            def _on_inner_configure(e):
                canvas.configure(scrollregion=canvas.bbox("all"))
            def _on_canvas_configure(e):
                canvas.itemconfig(inner_win, width=e.width)
            inner.bind("<Configure>", _on_inner_configure)
            canvas.bind("<Configure>", _on_canvas_configure)
            pad = tk.Frame(inner, bg=bg)
            pad.pack(fill=tk.BOTH, expand=True, padx=30, pady=(35, 20))

            hero = tk.Frame(pad, bg=surface)
            hero.pack(fill=tk.X, pady=(0, 18))
            tk.Frame(hero, bg=accent2, height=3).pack(fill=tk.X, side=tk.TOP)
            hero_inner = tk.Frame(hero, bg=surface)
            hero_inner.pack(fill=tk.X, padx=24, pady=18)

            left_hero = tk.Frame(hero_inner, bg=surface)
            left_hero.pack(side=tk.LEFT, fill=tk.Y)
            tk.Label(left_hero, text="Recursive Video Player",
                     font=Font(family="Segoe UI", size=20, weight="bold"),
                     bg=surface, fg=text_pri).pack(anchor="w")
            tk.Label(left_hero, text="Your personal media library · fast, organised, beautiful",
                     font=Font(family="Segoe UI", size=10),
                     bg=surface, fg=text_sec).pack(anchor="w", pady=(4, 0))

            play_btn = tk.Label(hero_inner, text="▶  Play All",
                                font=Font(family="Segoe UI", size=10, weight="bold"),
                                bg=accent2, fg="#ffffff", padx=16, pady=8, cursor="hand2")
            play_btn.pack(side=tk.RIGHT, anchor="center")
            play_btn.bind("<Button-1>", lambda e: self.play_videos())
            play_btn.bind("<Enter>", lambda e: play_btn.config(bg=accent))
            play_btn.bind("<Leave>", lambda e: play_btn.config(bg=accent2))

            body_row = tk.Frame(pad, bg=bg)
            body_row.pack(fill=tk.BOTH, expand=True)
            body_row.columnconfigure(0, weight=5)
            body_row.columnconfigure(1, weight=3)

            left_col = tk.Frame(body_row, bg=bg)
            left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

            right_col = tk.Frame(body_row, bg=bg)
            right_col.grid(row=0, column=1, sticky="nsew")

            # ── left: stats row ───────────────────────────────────────────
            total_dirs = len(self.selected_dirs)
            total_vids = total_lib_vids

            stat_data = [
                ("📁", str(total_dirs), "Directories", accent, None),
                ("🎬", str(total_vids), "Videos", accent2, None),
                ("📅", str(today_n), "Watched Today", "#06b6d4", self._show_watch_history),
                ("✓", f"{avg_pct:.0f}%", "Avg Completion", "#34c98a", self._show_watch_history),
            ]

            stats_row = tk.Frame(left_col, bg=bg)
            stats_row.pack(fill=tk.X, pady=(0, 14))
            for i in range(4):
                stats_row.columnconfigure(i, weight=1, uniform="sc")

            for i, (icon, val, lbl, col, cmd) in enumerate(stat_data):
                card = tk.Frame(stats_row, bg=surface,
                                highlightbackground=border, highlightthickness=1,
                                cursor="hand2" if cmd else "")
                card.grid(row=0, column=i, padx=(0 if i == 0 else 8, 0), sticky="nsew")
                tk.Frame(card, bg=col, width=4).pack(side=tk.LEFT, fill=tk.Y)
                body = tk.Frame(card, bg=surface)
                body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=12)
                tk.Label(body, text=icon, font=Font(family="Segoe UI Emoji", size=13),
                         bg=surface, fg=col).pack(anchor="w")
                val_lbl = tk.Label(body, text=val,
                                   font=Font(family="Segoe UI", size=16, weight="bold"),
                                   bg=surface, fg=text_pri)
                val_lbl.pack(anchor="w", pady=(2, 0))
                tk.Label(body, text=lbl, font=Font(family="Segoe UI", size=8),
                         bg=surface, fg=text_sec).pack(anchor="w")
                if i == 0: self._home_dirs_label = val_lbl
                if i == 1: self._home_vids_label = val_lbl
                if cmd:
                    for w in (card, body, val_lbl):
                        w.bind("<Button-1>", lambda e, c=cmd: c())
                        w.bind("<Enter>", lambda e, f=card: f.config(bg=self.hover_color, highlightbackground=accent))
                        w.bind("<Leave>", lambda e, f=card: f.config(bg=surface, highlightbackground=border))

            all_actions = [
                ("🖼", "Gallery", "Browse as grid", accent, self._show_grid_view),
                ("🎵", "Playlist", "Manage playlists", "#7c3aed", self._manage_playlists),
                ("⭐", "Favourites", "Your starred videos", "#f5a623", self._show_favorites_manager),
                ("🕐", "History", "Recently watched", "#34c98a", self._show_watch_history),
                ("📋", "Queue", "Up next", "#06b6d4", self._show_queue_manager),
                ("🏷", "Tags & Ratings", "Annotate & filter", accent2, self._show_annotation_browser),
            ]
            rng = _random.Random(self._qa_seed)
            actions = rng.sample(all_actions, 3)

            qa_lbl_row = tk.Frame(left_col, bg=bg)
            qa_lbl_row.pack(fill=tk.X, pady=(0, 10))
            tk.Label(qa_lbl_row, text="Quick Actions",
                     font=Font(family="Segoe UI", size=11, weight="bold"),
                     bg=bg, fg=text_pri).pack(side=tk.LEFT)
            tk.Frame(qa_lbl_row, bg=border, height=1).pack(
                side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 0), pady=6)

            qa_frame = tk.Frame(left_col, bg=bg)
            qa_frame.pack(fill=tk.X)
            for ci in range(3):
                qa_frame.columnconfigure(ci, weight=1, uniform="qa")

            for ci, (icon, title, sub, col, cmd) in enumerate(actions):
                card = tk.Frame(qa_frame, bg=surface,
                                highlightbackground=border, highlightthickness=1,
                                cursor="hand2")
                card.grid(row=0, column=ci, padx=(0 if ci == 0 else 10, 0), sticky="nsew")
                inner_card = tk.Frame(card, bg=surface)
                inner_card.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)
                tk.Label(inner_card, text=icon,
                         font=Font(family="Segoe UI Emoji", size=18),
                         bg=col, fg="#ffffff", width=3, pady=5).pack(anchor="w")
                tk.Label(inner_card, text=title,
                         font=Font(family="Segoe UI", size=11, weight="bold"),
                         bg=surface, fg=text_pri).pack(anchor="w", pady=(7, 0))
                tk.Label(inner_card, text=sub,
                         font=Font(family="Segoe UI", size=9),
                         bg=surface, fg=text_sec).pack(anchor="w", pady=(2, 0))
                _bind_hover(card, inner_card, cmd, col)

            analytics_card = tk.Frame(right_col, bg=surface,
                                      highlightbackground=border, highlightthickness=1)
            analytics_card.pack(fill=tk.BOTH, expand=True)
            tk.Frame(analytics_card, bg=accent, height=3).pack(fill=tk.X, side=tk.TOP)
            ac_inner = tk.Frame(analytics_card, bg=surface)
            ac_inner.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)

            tk.Label(ac_inner, text="Watch Analytics",
                     font=Font(family="Segoe UI", size=10, weight="bold"),
                     bg=surface, fg=text_pri).pack(anchor="w", pady=(0, 10))

            ms_row = tk.Frame(ac_inner, bg=surface)
            ms_row.pack(fill=tk.X, pady=(0, 12))
            ms_row.columnconfigure(0, weight=1)
            ms_row.columnconfigure(1, weight=1)

            for mci, (mv, ml, mc) in enumerate([
                (str(week_n), "This week", "#7c3aed"),
                (f"{pct_watched:.0f}%", "Coverage", accent2),
            ]):
                mf = tk.Frame(ms_row, bg=surface2)
                mf.grid(row=0, column=mci, padx=(0 if mci == 0 else 6, 0), sticky="nsew")
                tk.Label(mf, text=mv,
                         font=Font(family="Segoe UI", size=14, weight="bold"),
                         bg=surface2, fg=mc).pack(padx=10, pady=(8, 0), anchor="w")
                tk.Label(mf, text=ml,
                         font=Font(family="Segoe UI", size=8),
                         bg=surface2, fg=text_sec).pack(padx=10, pady=(0, 8), anchor="w")

            tk.Label(ac_inner, text="Last 7 days",
                     font=Font(family="Segoe UI", size=8, weight="bold"),
                     bg=surface, fg=text_sec).pack(anchor="w", pady=(0, 4))

            bar_h = 40
            bar_canvas = tk.Canvas(ac_inner, bg=surface, height=bar_h + 18,
                                   highlightthickness=0, bd=0)
            bar_canvas.pack(fill=tk.X, pady=(0, 12))

            def _draw_bars(c=bar_canvas, counts=day_counts):
                c.delete("all")
                w = c.winfo_width() or 300
                max_v = max(counts) if any(counts) else 1
                n = len(counts)
                gap = 5
                bw = max(4, (w - gap * (n + 1)) // n)
                today_date_l = datetime.now().date()
                for k, v in enumerate(counts):
                    delta = n - 1 - k
                    dl = (today_date_l - timedelta(days=delta)).strftime("%a")
                    x0 = gap + k * (bw + gap)
                    x1 = x0 + bw
                    y1 = 2 + bar_h
                    filled = max(3, int((v / max_v) * bar_h)) if max_v else 3
                    c.create_rectangle(x0, 2, x1, y1, fill=surface2, outline="", width=0)
                    bcol = accent2 if k == n - 1 else accent
                    c.create_rectangle(x0, y1 - filled, x1, y1, fill=bcol, outline="", width=0)
                    c.create_text(x0 + bw // 2, y1 + 9, text=dl,
                                  fill=text_sec, font=("Segoe UI", 7))

            bar_canvas.bind("<Configure>", lambda e: _draw_bars())
            bar_canvas.after(60, _draw_bars)

            tk.Frame(ac_inner, bg=border, height=1).pack(fill=tk.X, pady=(0, 8))
            tk.Label(ac_inner, text="Top directories",
                     font=Font(family="Segoe UI", size=8, weight="bold"),
                     bg=surface, fg=text_sec).pack(anchor="w", pady=(0, 6))

            bar_colors = [accent, accent2, "#7c3aed", "#06b6d4"]
            if top_dirs:
                max_dc = top_dirs[0][1]
                for ti, (dname, dcount) in enumerate(top_dirs):
                    rf = tk.Frame(ac_inner, bg=surface)
                    rf.pack(fill=tk.X, pady=2)
                    tk.Label(rf, text=dname[:18] + ("…" if len(dname) > 18 else ""),
                             font=Font(family="Segoe UI", size=8),
                             bg=surface, fg=text_pri, anchor="w", width=18).pack(side=tk.LEFT)
                    bg_bar = tk.Frame(rf, bg=surface2, height=8)
                    bg_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
                    bg_bar.pack_propagate(False)
                    _col = bar_colors[ti % len(bar_colors)]
                    _ratio = dcount / max_dc if max_dc else 0
                    def _fill(p=bg_bar, r=_ratio, c=_col):
                        p.update_idletasks()
                        pw = p.winfo_width() or 80
                        tk.Frame(p, bg=c, width=max(4, int(pw * r)), height=8).place(x=0, y=0)
                    bg_bar.after(90, _fill)
                    tk.Label(rf, text=str(dcount),
                             font=Font(family="Segoe UI", size=8),
                             bg=surface, fg=text_sec).pack(side=tk.LEFT)
            else:
                tk.Label(ac_inner,
                         text="No watch history yet.",
                         font=Font(family="Segoe UI", size=8),
                         bg=surface, fg=text_sec).pack(anchor="w")

            _cw_seen = set()
            _cw_entries = []
            for _cw_e in sorted(all_history, key=lambda x: x.watched_at, reverse=True):
                _cw_e_pct = float(_cw_e.completion_percentage or 0)
                if _cw_e.video_path not in _cw_seen and os.path.isfile(_cw_e.video_path) and 5 < _cw_e_pct < 95:
                    _cw_seen.add(_cw_e.video_path)
                    _cw_entries.append(_cw_e)
                if len(_cw_entries) >= 4:
                    break

            if _cw_entries:
                if hasattr(self, 'video_preview_manager') and _cw_entries:
                    self.video_preview_manager.prefetch_cw_previews(
                        [(e.video_path, float(e.duration_watched or 0)) for e in _cw_entries]
                    )
                cw_hdr = tk.Frame(pad, bg=bg)
                cw_hdr.pack(fill=tk.X, pady=(16, 8))
                tk.Label(cw_hdr, text="Continue Watching",
                         font=Font(family="Segoe UI", size=11, weight="bold"),
                         bg=bg, fg=text_pri).pack(side=tk.LEFT)
                tk.Frame(cw_hdr, bg=border, height=1).pack(
                    side=tk.LEFT, fill=tk.X, expand=True, padx=(12, 0), pady=6)
                _see_all_lbl = tk.Label(cw_hdr, text="See all →",
                                        font=Font(family="Segoe UI", size=9),
                                        bg=bg, fg=accent, cursor="hand2")
                _see_all_lbl.pack(side=tk.RIGHT)
                _see_all_lbl.bind("<Button-1>", lambda e: self._show_watch_history())
                _see_all_lbl.bind("<Enter>", lambda e: _see_all_lbl.config(fg=accent2))
                _see_all_lbl.bind("<Leave>", lambda e: _see_all_lbl.config(fg=accent))

                cw_grid = tk.Frame(pad, bg=bg)
                cw_grid.pack(fill=tk.X)
                for _cw_ci in range(len(_cw_entries)):
                    cw_grid.columnconfigure(_cw_ci, weight=1, uniform="cw")

                for _cw_ci, _cw_entry in enumerate(_cw_entries):
                    _cw_fname = os.path.splitext(os.path.basename(_cw_entry.video_path))[0]
                    _cw_name_disp = (_cw_fname[:26] + "…") if len(_cw_fname) > 26 else _cw_fname
                    _cw_pct = min(100.0, max(0.0, float(_cw_entry.completion_percentage or 0)))
                    _cw_dur = _cw_entry.get_duration_formatted() if _cw_entry.duration_watched else ""
                    try:
                        _cw_delta = datetime.now() - datetime.fromisoformat(_cw_entry.watched_at)
                        if _cw_delta.days == 0:
                            _cw_hrs = _cw_delta.seconds // 3600
                            _cw_time = (f"{_cw_delta.seconds // 60}m ago"
                                        if _cw_hrs == 0 else f"{_cw_hrs}h ago")
                        elif _cw_delta.days == 1:
                            _cw_time = "Yesterday"
                        else:
                            _cw_time = f"{_cw_delta.days}d ago"
                    except Exception:
                        _cw_time = ""

                    _cw_bar_col = ("#34c98a" if _cw_pct >= 80
                                   else (accent if _cw_pct >= 35 else accent2))

                    _cw_card = tk.Frame(cw_grid, bg=surface,
                                        highlightbackground=border, highlightthickness=1,
                                        cursor="hand2")
                    _cw_card.grid(row=0, column=_cw_ci,
                                  padx=(0 if _cw_ci == 0 else 8, 0), sticky="nsew")
                    _cw_card.pack_propagate(False)
                    _cw_card.configure(height=110)

                    _accent_bar = tk.Frame(_cw_card, bg=_cw_bar_col, width=4)
                    _accent_bar.pack(side=tk.LEFT, fill=tk.Y)

                    _cw_body = tk.Frame(_cw_card, bg=surface)
                    _cw_body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                                  padx=(10, 10), pady=10)

                    tk.Label(_cw_body, text=_cw_name_disp,
                             font=Font(family="Segoe UI", size=9, weight="bold"),
                             bg=surface, fg=text_pri, anchor="w").pack(fill=tk.X)

                    _cw_meta = tk.Frame(_cw_body, bg=surface)
                    _cw_meta.pack(fill=tk.X, pady=(2, 6))
                    tk.Label(_cw_meta, text=_cw_time,
                             font=Font(family="Segoe UI", size=8),
                             bg=surface, fg=text_sec).pack(side=tk.LEFT)
                    if _cw_dur:
                        tk.Label(_cw_meta, text=f"  ·  {_cw_dur}",
                                 font=Font(family="Segoe UI", size=8),
                                 bg=surface, fg=text_sec).pack(side=tk.LEFT)

                    _cw_prog_bg = tk.Frame(_cw_body, bg=surface2, height=4)
                    _cw_prog_bg.pack(fill=tk.X)
                    _cw_prog_bg.pack_propagate(False)

                    def _fill_cw_prog(p=_cw_prog_bg, r=_cw_pct / 100, c=_cw_bar_col):
                        p.update_idletasks()
                        pw = p.winfo_width() or 80
                        tk.Frame(p, bg=c, width=max(2, int(pw * r)), height=4).place(x=0, y=0)

                    _cw_prog_bg.after(130, _fill_cw_prog)

                    _cw_bot = tk.Frame(_cw_body, bg=surface)
                    _cw_bot.pack(fill=tk.X, pady=(6, 0))
                    tk.Label(_cw_bot, text=f"{_cw_pct:.0f}%",
                             font=Font(family="Segoe UI", size=8, weight="bold"),
                             bg=surface, fg=_cw_bar_col).pack(side=tk.LEFT, anchor="center")
                    _cw_resume = tk.Label(_cw_bot, text="▶  Resume",
                                          font=Font(family="Segoe UI", size=8, weight="bold"),
                                          bg=_cw_bar_col, fg="#ffffff",
                                          padx=10, pady=3, cursor="hand2")
                    _cw_resume.pack(side=tk.RIGHT, anchor="center")

                    def _do_play_cw(path=_cw_entry.video_path):
                        self._play_continue_watching_video(path)

                    for _cw_w in (_cw_card, _cw_body, _cw_resume, _accent_bar):
                        _cw_w.bind("<Button-1>", lambda e, fn=_do_play_cw: fn())

                    def _cw_right_click(e, path=_cw_entry.video_path, entry=_cw_entry):
                        if not hasattr(self, 'video_preview_manager'):
                            return
                        vpm = self.video_preview_manager

                        resume_sec = 0.0
                        try:
                            if entry.duration_watched:
                                resume_sec = float(entry.duration_watched)
                        except Exception:
                            pass

                        cached_td = vpm.cw_preview_cache.get(path, resume_sec)
                        if cached_td:
                            vpm.tooltip.show_preview(path, cached_td, e.x_root, e.y_root)
                        else:
                            vpm.show_preview_at_position(path, resume_sec, e.x_root, e.y_root)

                    def _cw_hide_tooltip(e):
                        if hasattr(self, 'video_preview_manager'):
                            self.video_preview_manager.tooltip.hide_preview()

                    def _bind_cw_rc(w):
                        w.bind("<Button-3>", _cw_right_click)
                        for _ch in w.winfo_children():
                            _bind_cw_rc(_ch)

                    _bind_cw_rc(_cw_card)

                    def _cw_enter(e, card=_cw_card, body=_cw_body,
                                  bc=_cw_bar_col, sf=surface, hc=self.hover_color):
                        card.config(bg=hc, highlightbackground=bc, highlightthickness=2)
                        body.config(bg=hc)
                        for _w in body.winfo_children():
                            try:
                                if isinstance(_w, (tk.Label, tk.Frame)) and _w.cget("bg") == sf:
                                    _w.config(bg=hc)
                            except Exception:
                                pass
                            if isinstance(_w, tk.Frame):
                                for _ww in _w.winfo_children():
                                    try:
                                        if isinstance(_ww, tk.Label) and _ww.cget("bg") == sf:
                                            _ww.config(bg=hc)
                                    except Exception:
                                        pass

                    def _cw_leave(e, card=_cw_card, body=_cw_body,
                                  bd=border, sf=surface, hc=self.hover_color):
                        _cw_hide_tooltip(e)
                        card.config(bg=sf, highlightbackground=bd, highlightthickness=1)
                        body.config(bg=sf)
                        for _w in body.winfo_children():
                            try:
                                if isinstance(_w, (tk.Label, tk.Frame)) and _w.cget("bg") == hc:
                                    _w.config(bg=sf)
                            except Exception:
                                pass
                            if isinstance(_w, tk.Frame):
                                for _ww in _w.winfo_children():
                                    try:
                                        if isinstance(_ww, tk.Label) and _ww.cget("bg") == hc:
                                            _ww.config(bg=sf)
                                    except Exception:
                                        pass

                    for _cw_w in (_cw_card, _cw_body, _accent_bar):
                        _cw_w.bind("<Enter>", _cw_enter)
                        _cw_w.bind("<Leave>", _cw_leave)

            tip_bg = surface2
            tip = tk.Frame(pad, bg=tip_bg,
                           highlightbackground=border, highlightthickness=1)
            tip.pack(fill=tk.X, pady=(14, 0))
            tip_inner = tk.Frame(tip, bg=tip_bg)
            tip_inner.pack(fill=tk.X, padx=14, pady=8)
            tk.Label(tip_inner, text="💡",
                     font=Font(family="Segoe UI Emoji", size=10),
                     bg=tip_bg, fg=accent).pack(side=tk.LEFT, padx=(0, 8))
            tk.Label(tip_inner,
                     text="Click  +  on the panel header to add a folder, then pick any action above to explore your library.",
                     font=Font(family="Segoe UI", size=9),
                     bg=tip_bg, fg=text_sec,
                     wraplength=680, justify="left").pack(side=tk.LEFT)

        def _ensure_embedded_view_frame(self):
            if self.embedded_view_frame and self.embedded_view_frame.winfo_exists():
                return self.embedded_view_frame
            self.embedded_view_frame = tk.Frame(self.workspace_body, bg=self.bg_color)
            return self.embedded_view_frame

        def _cleanup_active_manager(self):
            mgr = getattr(self, 'active_embedded_manager', None)
            if mgr is None:
                return
            self.active_embedded_manager = None
            try:
                if hasattr(mgr, 'cleanup'):  # AnnotationBrowserManager
                    mgr.cleanup()
                elif hasattr(mgr, '_teardown_grid_view'):  # GridViewManager
                    mgr._teardown_grid_view()
            except Exception:
                pass


        def _show_embedded_view(self, view_name, builder):
            self._cleanup_active_manager()
            if hasattr(self, 'exclusion_section') and self.exclusion_section.winfo_ismapped():
                self.exclusion_section.pack_forget()
            frame = self._ensure_embedded_view_frame()
            frame.configure(bg=self.bg_color)
            frame.pack(fill=tk.BOTH, expand=True)
            for child in frame.winfo_children():
                child.destroy()
            self._active_app_view = view_name
            self._set_workspace_title(
                getattr(self, "_view_tab_labels", {}).get(getattr(self, "_active_app_view", "home"), "Home"),
                self._selected_directory_summary()
            )
            self._refresh_media_pill_state()
            self.active_embedded_manager = builder(frame)

        def _set_workspace_title(self, title, subtitle=None):
            if hasattr(self, "workspace_title_label"):
                self.workspace_title_label.config(text=title)
            if hasattr(self, "workspace_context_label"):
                self.workspace_context_label.config(text=subtitle or self._selected_directory_summary())

        def _selected_directory_summary(self):
            if not hasattr(self, "dir_listbox"):
                return "No directory selected"
            selection = self.dir_listbox.curselection()
            if not selection:
                return "No directory selected"
            names = []
            for idx in selection[:2]:
                if idx < len(self.selected_dirs):
                    names.append(os.path.basename(self.selected_dirs[idx]) or self.selected_dirs[idx])
            if len(selection) > 2:
                names.append(f"+{len(selection) - 2} more")
            total = 0
            for idx in selection:
                if idx < len(self.selected_dirs):
                    d = self.selected_dirs[idx]
                    cache = self.scan_cache.get(d)
                    if cache:
                        videos, _, _ = cache
                        total += sum(1 for v in videos if not self.is_video_excluded(d, v))
            return "Directory: " + ", ".join(names) + f"({total} videos)"

        def _refresh_media_pill_state(self):
            active_view = getattr(self, '_active_app_view', 'home')
            active_label = self._view_tab_labels.get(active_view, "Home")
            for lbl, btn in self._media_pill_btns.items():
                is_active = (lbl == active_label)
                container = getattr(btn, '_pill_container', btn.master)
                for child in container.winfo_children():
                    if isinstance(child, tk.Frame) and getattr(child, '_underline', False):
                        child.destroy()
                if is_active:
                    btn.config(
                        bg=self.bg_color, fg=self.accent_color,
                        font=("Segoe UI", 10, "bold"))
                    underline = tk.Frame(container, bg=self.accent_color, height=2)
                    underline._underline = True
                    underline.pack(fill=tk.X)
                else:
                    btn.config(
                        bg=self.bg_color, fg=self.text_muted,
                        font=("Segoe UI", 10, "normal"))
                container.configure(bg=self.bg_color)
                self._bind_media_pill_hover(btn, lbl)

        def global_play(self):
            if self.active_embedded_manager is not None:
                # Attempt to call the manager's play_from_global method
                if hasattr(self.active_embedded_manager, 'play_from_global'):
                    self.active_embedded_manager.play_from_global()
                else:
                    self.play_videos()  # fallback
            else:
                self.play_videos()

        def setup_console_section(self):
            self.console_section = tk.Frame(self.main_frame, bg=self.bg_color)
            if self.show_console:
                self.console_section.pack(fill=tk.X, pady=(0, 15))
            console_section = self.console_section

            self.console_header_frame = tk.Frame(console_section, bg=self.bg_color)
            self.console_header_frame.pack(fill=tk.X, pady=(0, 10))
            console_header_frame = self.console_header_frame

            self.console_header_label = tk.Label(console_header_frame, text="Player Console",
                                                 font=self.header_font, bg=self.bg_color, fg=self.text_color)
            self.console_header_label.pack(side=tk.LEFT, anchor='w')

            self.clear_console_button = self.create_button(
                console_header_frame, text="Clear", command=self.clear_console,
                variant="dark", size="sm"
            )
            self.clear_console_button.pack(side=tk.LEFT, padx=(10, 0), anchor='w')

            # Outer container with subtle border
            self.console_container = tk.Frame(console_section, bg=self.bg_color,
                                         highlightbackground=self.border_color,
                                         highlightthickness=1, bd=0)
            self.console_container.pack(fill=tk.X, pady=(0, 10))
            console_container = self.console_container

            # Inner padding frame
            self.console_inner_pad = tk.Frame(console_container, bg=self.bg_color, padx=8, pady=8)
            self.console_inner_pad.pack(fill=tk.BOTH, expand=True)
            inner_pad = self.console_inner_pad

            self.console_frame = tk.Frame(inner_pad, bg=self.bg_color)
            self.console_frame.pack(fill=tk.BOTH, expand=True)
            console_frame = self.console_frame

            self.console_scrollbar = tk.Scrollbar(console_frame)
            self.console_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            self.console_text = tk.Text(
                console_frame, height=10, wrap=tk.WORD,
                yscrollcommand=self.console_scrollbar.set,
                font=self.mono_font, bg=self.console_bg, fg=self.console_fg,
                insertbackground=self.console_fg, selectbackground="#214283",
                selectforeground="white", relief=tk.FLAT, bd=0,
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

            super().apply_theme()

            self._reapply_tree_columns()

            if dir_w > 10:
                self.dir_section.config(width=dir_w)
                self.dir_section.pack_propagate(False)

        def _reapply_tree_columns(self):
            if not hasattr(self, 'exclusion_tree'):
                return
            self.exclusion_tree.configure(columns=())
            self.exclusion_tree.column("#0", minwidth=200, stretch=True, anchor="w")

        def setup_directory_section(self):
            self.dir_section = tk.Frame(self.content_frame, bg=self.bg_color)
            self.dir_section.pack(side=tk.LEFT, fill=tk.Y, expand=False, padx=(0, 0), before=self.workspace_frame)
            self.dir_section.config(width=self._dir_panel_width)
            self.dir_section.pack_propagate(False)

            self._dir_resizer = tk.Frame(self.content_frame, bg=self.border_color, width=4, cursor="sb_h_double_arrow")
            self._dir_resizer.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10), before=self.workspace_frame)
            self._dir_resizer.pack_propagate(False)

            self._dir_resizer_dragging = False
            self._dir_resizer_start_x = 0
            self._dir_resizer_start_w = 0

            def _on_resizer_enter(e):
                self._dir_resizer.config(bg=self.accent_color)

            def _on_resizer_leave(e):
                self._dir_resizer.config(bg=self.border_color if not self._dir_resizer_dragging else self.accent_color)

            def _on_resizer_press(e):
                self._dir_resizer_dragging = True
                self._dir_resizer_start_x = e.x_root
                self._dir_resizer_start_w = self.dir_section.winfo_width()
                self._dir_resizer.config(bg=self.accent_color)

            def _on_resizer_drag(e):
                if not self._dir_resizer_dragging:
                    return
                delta = e.x_root - self._dir_resizer_start_x
                new_w = max(83, min(700, self._dir_resizer_start_w + delta))
                self._dir_panel_width = new_w
                self.dir_section.config(width=new_w)

            def _on_resizer_release(e):
                self._dir_resizer_dragging = False
                self._dir_resizer.config(bg=self.border_color)

            self._dir_resizer.bind("<Enter>", _on_resizer_enter)
            self._dir_resizer.bind("<Leave>", _on_resizer_leave)
            self._dir_resizer.bind("<ButtonPress-1>", _on_resizer_press)
            self._dir_resizer.bind("<B1-Motion>", _on_resizer_drag)
            self._dir_resizer.bind("<ButtonRelease-1>", _on_resizer_release)

            self._sb_toggle_btn = self._create_sidebar_icon_btn(
                self._sidebar_panel, "◁", self._toggle_directory_panel, tooltip="Toggle Panel")
            self._sb_toggle_btn.pack(fill=tk.X, pady=(12, 0))

            self._sb_add_btn = self._create_sidebar_icon_btn(
                self._sidebar_panel, "+", self.add_directory, tooltip="Add Directory")
            self._sb_add_btn.pack(fill=tk.X, pady=(2, 0))

            dir_header_frame = tk.Frame(self.dir_section, bg=self.bg_color)
            dir_header_frame.pack(fill=tk.X, pady=(0, 6))

            self.dir_header_label = tk.Label(dir_header_frame, text="Directories",
                                             font=self.header_font, bg=self.bg_color, fg=self.text_color)
            self.dir_header_label.pack(side=tk.LEFT, anchor='w')

            _tree_actions = [
                ("▤", "Toggle Videos", self.toggle_videos_visibility),
                ("⊟", "Collapse All", self._collapse_all_tree_nodes),
                ("⊞", "Expand All", self._expand_all_tree_nodes),
                ("−", "Hide Panel", self._toggle_directory_panel),
            ]
            self._dir_action_btns = {}
            for icon, tip, cmd in reversed(_tree_actions):
                b = self._create_panel_action_btn(dir_header_frame, icon, cmd, tip)
                b.pack(side=tk.RIGHT, padx=(0, 2))
                self._dir_action_btns[tip] = b

            self._refresh_dir_action_states()

            # Search bar
            search_wrap = tk.Frame(
                self.dir_section,
                bg=self.entry_bg,
                highlightbackground=self.entry_border,
                highlightthickness=1,
            )
            search_wrap.pack(fill=tk.X, pady=(0, 6), padx=6)

            search_icon = tk.Label(
                search_wrap, text="⌕",
                bg=self.entry_bg, fg=self.text_muted,
                font=("Segoe UI", 11), padx=6, pady=0,
            )
            search_icon.pack(side=tk.LEFT)

            self.search_entry = tk.Entry(
                search_wrap,
                font=self.small_font,
                bg=self.entry_bg, fg=self.entry_fg,
                relief=tk.FLAT, bd=0,
                highlightthickness=0,
                insertbackground=self.accent_color,
            )
            self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=6)
            self.search_entry.bind('<KeyRelease>', self.on_search_changed)

            def _search_focus_in(e):
                search_wrap.config(highlightbackground=self.accent_color, highlightthickness=1)
                search_icon.config(fg=self.accent_color)

            def _search_focus_out(e):
                search_wrap.config(highlightbackground=self.entry_border, highlightthickness=1)
                search_icon.config(fg=self.text_muted)

            self.search_entry.bind('<FocusIn>', _search_focus_in)
            self.search_entry.bind('<FocusOut>', _search_focus_out)
            self._search_wrap = search_wrap
            self._search_icon = search_icon

            self.dir_frame = tk.Frame(self.dir_section, bg=self.bg_color)
            self.dir_frame.pack(fill=tk.BOTH, expand=True)

            self.dir_tree_container = tk.Frame(
                self.dir_frame, bg=self.listbox_bg,
                highlightbackground=self.border_color, highlightthickness=1)
            self.dir_tree_container.pack(fill=tk.BOTH, expand=True)

            self.exclusion_scrollbar = ttk.Scrollbar(
                self.dir_tree_container, orient=tk.VERTICAL,
                style="ExclusionTree.Vertical.TScrollbar")

            style = ttk.Style()
            style.theme_use("clam")
            style.configure(
                "ExclusionTree.Vertical.TScrollbar",
                gripcount=0,
                borderwidth=0,
                relief="flat",
                arrowsize=10,
                width=5
            )

            self.exclusion_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            self.exclusion_tree = ttk.Treeview(
                self.dir_tree_container,
                style="ExclusionTree.Treeview",
                selectmode="extended",
                show="tree",
                columns=(),
                yscrollcommand=self.exclusion_scrollbar.set,
            )
            self.exclusion_scrollbar.config(command=self.exclusion_tree.yview)
            self.exclusion_tree.column("#0", minwidth=200, stretch=True, anchor="w")
            self.exclusion_tree.pack(fill=tk.BOTH, expand=True)

            # Shim: dir_listbox API backed by dir_tree iid->root-dir mapping
            self._dir_root_iids = []   # ordered list of iids for root dirs
            self._dir_iid_selected = set()
            self._dir_iid_counter = 0
            self._tree_iid_counter = 0
            self._dir_iid_selected = set()

            class _DirListboxShim:
                def __init__(shim, owner):
                    shim.owner = owner

                def insert(shim, pos, display_name):
                    idx = len(shim.owner._dir_root_iids)
                    iid = f"__root_{shim.owner._dir_iid_counter}__"
                    shim.owner._dir_iid_counter += 1
                    shim.owner._dir_root_iids.append(iid)
                    shim.owner.exclusion_tree.insert(
                        "", tk.END, iid=iid,
                        text=f"📁 {display_name}", tags=("folder",), open=False
                    )
                    shim.owner.current_subdirs_mapping[iid] = shim.owner.selected_dirs[idx] if idx < len(
                        shim.owner.selected_dirs) else display_name

                def delete(shim, index):
                    if 0 <= index < len(shim.owner._dir_root_iids):
                        iid = shim.owner._dir_root_iids.pop(index)
                        # Collect all descendant iids before deleting
                        def _collect_all(parent):
                            result = []
                            try:
                                for child in shim.owner.exclusion_tree.get_children(parent):
                                    result.append(child)
                                    result.extend(_collect_all(child))
                            except Exception:
                                pass
                            return result
                        descendants = _collect_all(iid)
                        try:
                            shim.owner.exclusion_tree.delete(iid)
                        except Exception:
                            pass
                        for d in descendants + [iid]:
                            if d in shim.owner.current_subdirs_mapping:
                                del shim.owner.current_subdirs_mapping[d]

                def curselection(shim):
                    sel = list(shim.owner.exclusion_tree.selection())
                    result = []
                    for iid in sel:
                        if iid in shim.owner._dir_root_iids:
                            result.append(shim.owner._dir_root_iids.index(iid))
                    return tuple(sorted(set(result)))

                def selection_clear(shim, first, last=None):
                    if last is None:
                        try:
                            shim.owner.exclusion_tree.selection_remove(shim.owner._dir_root_iids[first])
                        except Exception:
                            pass
                    else:
                        for i in range(first, min(last + 1, len(shim.owner._dir_root_iids))):
                            try:
                                shim.owner.exclusion_tree.selection_remove(shim.owner._dir_root_iids[i])
                            except Exception:
                                pass

                def selection_set(shim, index):
                    if 0 <= index < len(shim.owner._dir_root_iids):
                        shim.owner.exclusion_tree.selection_add(shim.owner._dir_root_iids[index])

                def activate(shim, index):
                    if 0 <= index < len(shim.owner._dir_root_iids):
                        shim.owner.exclusion_tree.focus(shim.owner._dir_root_iids[index])

                def nearest(shim, y):
                    iid = shim.owner.exclusion_tree.identify_row(y)
                    if iid and iid in shim.owner._dir_root_iids:
                        return shim.owner._dir_root_iids.index(iid)
                    return -1

                def size(shim):
                    return len(shim.owner._dir_root_iids)

                def get(shim, index):
                    if 0 <= index < len(shim.owner._dir_root_iids):
                        iid = shim.owner._dir_root_iids[index]
                        return shim.owner.exclusion_tree.item(iid, "text")
                    return ""

                def yview(shim):
                    return shim.owner.exclusion_tree.yview()

                def bind(shim, *args, **kwargs):
                    pass  # bindings handled on exclusion_tree directly

                def configure(shim, **kwargs):
                    pass  # tree is a Treeview; theme applies via _configure_tree_style

                config = configure  # tk alias

            self.dir_listbox = _DirListboxShim(self)

            # Bind events on the tree
            self._selection_anchor = None
            self.exclusion_tree.bind("<Button-1>", self._on_tree_left_click_unified)
            self.exclusion_tree.bind("<Double-Button-1>", self._on_double_click)
            self.exclusion_tree.bind("<Button-3>", self._on_tree_right_click_unified)
            self.exclusion_tree.bind("<<TreeviewOpen>>", self._on_tree_open)
            self.exclusion_tree.bind("<<TreeviewClose>>", self._on_tree_close)
            self.exclusion_tree.bind("<Control-a>",
                                     lambda e: (self.exclusion_tree.selection_set(self._tree_get_all_iids()), "break")[1])
            self.exclusion_tree.bind("<Control-A>",
                                     lambda e: (self.exclusion_tree.selection_set(self._tree_get_all_iids()), "break")[1])
            self.exclusion_tree.bind("<Delete>", self._on_key_toggle_exclusion)
            self.exclusion_tree.bind("<space>", self._on_key_toggle_exclusion)
            self._drag_root_iid = None
            self._drag_start_y = None
            self.exclusion_tree.bind("<B1-Motion>", self._on_drag_motion)
            self.exclusion_tree.bind("<ButtonRelease-1>", self._on_drag_release)

            self._hovered_iid = None

            def _on_tree_motion(e):
                iid = self.exclusion_tree.identify_row(e.y)
                if iid == self._hovered_iid:
                    return
                if self._hovered_iid:
                    tags = list(self.exclusion_tree.item(self._hovered_iid, "tags"))
                    if "hover" in tags:
                        tags.remove("hover")
                        self.exclusion_tree.item(self._hovered_iid, tags=tags)
                self._hovered_iid = iid
                if iid:
                    tags = list(self.exclusion_tree.item(iid, "tags"))
                    if "hover" not in tags:
                        tags.append("hover")
                        self.exclusion_tree.item(iid, tags=tags)

            def _on_tree_leave(e):
                if self._hovered_iid:
                    tags = list(self.exclusion_tree.item(self._hovered_iid, "tags"))
                    if "hover" in tags:
                        tags.remove("hover")
                        self.exclusion_tree.item(self._hovered_iid, tags=tags)
                self._hovered_iid = None

            self._tree_hover_motion = _on_tree_motion
            self._tree_hover_leave = _on_tree_leave
            self.exclusion_tree.bind("<Motion>", _on_tree_motion)
            self.exclusion_tree.bind("<Leave>", _on_tree_leave)

            self.exclusion_buttons_frame = tk.Frame(self.dir_section, bg=self.bg_color)
            self.exclusion_buttons_frame.pack(fill=tk.X, pady=(6, 0))

            self.search_frame = tk.Frame(self.dir_section, bg=self.bg_color)  # kept for compat

        def _on_drag_start(self, event):
            iid = self.exclusion_tree.identify_row(event.y)
            region = self.exclusion_tree.identify_region(event.x, event.y)
            if iid and iid in self._dir_root_iids and region != "tree":
                self._drag_root_iid = iid
            else:
                self._drag_root_iid = None

        def _on_drag_motion(self, event):
            if not self._drag_root_iid:
                return
            if abs(event.y - self._drag_start_y) < 4:
                return
            self.exclusion_tree.configure(cursor="fleur")
            # clear old indicator
            try:
                self.exclusion_tree.delete("__drag_ind__")
            except Exception:
                pass
            target = self.exclusion_tree.identify_row(event.y)
            if not target or target == self._drag_root_iid:
                return
            # find which root we're hovering over or under
            if target in self._dir_root_iids:
                hover_root = target
            else:
                p = self.exclusion_tree.parent(target)
                while p and p not in self._dir_root_iids:
                    p = self.exclusion_tree.parent(p)
                hover_root = p if p in self._dir_root_iids else None
            if not hover_root or hover_root == self._drag_root_iid:
                return
            insert_pos = self.exclusion_tree.index(hover_root)
            try:
                self.exclusion_tree.insert("", insert_pos, iid="__drag_ind__",
                                           text="  ── drop here ──────────────",
                                           tags=("drag_indicator",))
                self.exclusion_tree.tag_configure("drag_indicator", foreground=self.accent_color)
            except Exception:
                pass

        def _on_drag_release(self, event):
            self.exclusion_tree.configure(cursor="")
            try:
                self.exclusion_tree.delete("__drag_ind__")
            except Exception:
                pass

            src = self._drag_root_iid
            self._drag_root_iid = None
            if not src:
                return
            if abs(event.y - self._drag_start_y) < 4:
                return

            target = self.exclusion_tree.identify_row(event.y)
            if not target or target == src:
                return

            # resolve destination root
            if target in self._dir_root_iids:
                dst_root = target
            else:
                p = self.exclusion_tree.parent(target)
                while p and p not in self._dir_root_iids:
                    p = self.exclusion_tree.parent(p)
                dst_root = p if p in self._dir_root_iids else None
            if not dst_root or dst_root == src:
                return

            src_idx = self._dir_root_iids.index(src)
            dst_idx = self._dir_root_iids.index(dst_root)

            # reorder both lists
            self.selected_dirs.insert(dst_idx, self.selected_dirs.pop(src_idx))
            self._dir_root_iids.insert(dst_idx, self._dir_root_iids.pop(src_idx))

            # move node in tree
            self.exclusion_tree.move(src, "", dst_idx)

            self.exclusion_tree.selection_set(src)
            self._trigger_root_selection(src)
            if self.save_directories:
                self.save_preferences()
            self.update_video_count()

        def _on_tree_left_click_unified(self, event):
            iid = self.exclusion_tree.identify_row(event.y)
            region = self.exclusion_tree.identify_region(event.x, event.y)

            self._drag_root_iid = iid if (iid and iid in self._dir_root_iids and region == "tree") else None
            self._drag_start_y = event.y

            if region == "tree":
                return

            if not iid:
                self.exclusion_tree.selection_remove(self.exclusion_tree.selection())
                self._selection_anchor = None
                return

            is_root = iid in self._dir_root_iids

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
                if is_root:
                    self._trigger_root_selection(iid)
                return "break"

            if ctrl_held:
                if iid in current:
                    self.exclusion_tree.selection_remove(iid)
                else:
                    self.exclusion_tree.selection_add(iid)
                self._selection_anchor = iid
                if is_root:
                    self._trigger_root_selection(iid)
                return "break"

            # Plain click
            if is_root:
                if current == [iid]:
                    # toggle off
                    self.exclusion_tree.selection_remove(iid)
                    self.current_selected_dir_index = None
                    self.clear_exclusion_children(iid)
                    self._is_filtered_mode = False
                    self._selection_anchor = None
                    return "break"
                self.exclusion_tree.selection_set(iid)
                self._selection_anchor = iid
                self._trigger_root_selection(iid)
                return "break"

            # Non-root item
            self.exclusion_tree.selection_set(iid)
            self._selection_anchor = iid
            return "break"

        def _trigger_root_selection(self, iid):
            if iid not in self._dir_root_iids:
                return
            idx = self._dir_root_iids.index(iid)
            self._is_filtered_mode = False
            self.current_selected_dir_index = idx
            selected_dir = self.selected_dirs[idx] if idx < len(self.selected_dirs) else None
            if not selected_dir:
                return
            self._set_workspace_title(
                getattr(self, "_view_tab_labels", {}).get(getattr(self, "_active_app_view", "home"), "Home"),
                self._selected_directory_summary()
            )
            self._refresh_active_manager_for_directory_context()
            self.expanded_paths.clear()
            self.collapsed_paths.clear()
            self._load_root_children(iid, selected_dir)

        def _load_root_children(self, root_iid, directory):
            # Remove existing children of this root node, then populate via load_subdirectories
            for child in self.exclusion_tree.get_children(root_iid):
                self.exclusion_tree.delete(child)
                # clean mapping
                if child in self.current_subdirs_mapping:
                    del self.current_subdirs_mapping[child]
            self.load_subdirectories(directory, max_depth=20, _root_iid=root_iid)

        def clear_exclusion_children(self, root_iid):
            for child in list(self.exclusion_tree.get_children(root_iid)):
                try:
                    self.exclusion_tree.delete(child)
                except Exception:
                    pass

        def _on_tree_right_click_unified(self, event):
            iid = self.exclusion_tree.identify_row(event.y)
            if iid and iid in self._dir_root_iids:
                # Right-click on a root dir: show root dir context menu
                if iid not in self.exclusion_tree.selection():
                    self.exclusion_tree.selection_set(iid)
                idx = self._dir_root_iids.index(iid)
                self._show_main_dir_context_menu_for_index(event, idx)
            else:
                # Delegate to existing exclusion tree context menu
                self._show_context_menu(event)

        def _create_panel_action_btn(self, parent, icon, command, tooltip=None):
            btn = tk.Label(
                parent, text=icon,
                bg=self.bg_color, fg=self.text_muted,
                font=("Segoe UI", 12), pady=3, padx=4,
                cursor="hand2", relief=tk.FLAT, bd=0,
            )
            btn._active = False

            def _on_enter(_e):
                btn.config(bg=self.hover_color, fg=self.accent_color)

            def _on_leave(_e):
                if btn._active:
                    btn.config(bg=self.hover_color, fg=self.accent_color)
                else:
                    btn.config(bg=self.bg_color, fg=self.text_muted)

            def _on_click(_e):
                command()
                self._refresh_dir_action_states()

            btn.bind("<Enter>", _on_enter)
            btn.bind("<Leave>", _on_leave)
            btn.bind("<Button-1>", _on_click)

            if tooltip:
                import tkinter as _tk
                _tip = [None]

                def _show(e):
                    if _tip[0]: return
                    x = btn.winfo_rootx()
                    y = btn.winfo_rooty() + btn.winfo_height() + 2
                    tw = _tk.Toplevel(btn)
                    tw.wm_overrideredirect(True)
                    tw.wm_geometry(f"+{x}+{y}")
                    _tk.Label(tw, text=tooltip, bg=self.console_bg, fg=self.console_fg,
                              font=("Segoe UI", 9), padx=7, pady=3).pack()
                    _tip[0] = tw

                def _hide(e):
                    if _tip[0]:
                        try:
                            _tip[0].destroy()
                        except:
                            pass
                        _tip[0] = None

                btn.bind("<Enter>", lambda e: (_show(e), _on_enter(e)))
                btn.bind("<Leave>", lambda e: (_hide(e), _on_leave(e)))
            return btn

        def _refresh_dir_action_states(self):
            if not hasattr(self, '_dir_action_btns'):
                return
            btn = self._dir_action_btns.get("Toggle Videos")
            if btn:
                active = getattr(self, 'show_videos', True)
                btn._active = active
                btn.config(
                    fg=self.accent_color if active else self.text_muted,
                    bg=self.hover_color if active else self.bg_color,
                )

        def shrink_directory_panel(self):
            self._set_directory_panel_mode("compact")

        def _toggle_directory_panel(self):
            if self._directory_panel_mode == "compact":
                self.expand_directory_panel()
            else:
                self.shrink_directory_panel()

        def expand_directory_panel(self):
            self._set_directory_panel_mode("expanded")

        def _set_directory_panel_mode(self, mode):
            self._directory_panel_mode = mode
            if not hasattr(self, "dir_section"):
                return

            if mode == "compact":
                self.dir_section.pack_forget()
                if hasattr(self, '_dir_resizer'):
                    self._dir_resizer.pack_forget()
                if hasattr(self, '_sb_toggle_btn'):
                    self._sb_toggle_btn.config(text="▷")
                self.workspace_frame.pack_configure(padx=(10, 0))
                return

            if not self.dir_section.winfo_ismapped():
                self.dir_section.pack(side=tk.LEFT, fill=tk.Y, expand=False, padx=(0, 0), before=self.workspace_frame)
            self.dir_section.config(width=self._dir_panel_width)
            if hasattr(self, '_dir_resizer') and not self._dir_resizer.winfo_ismapped():
                self._dir_resizer.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10), before=self.workspace_frame)
            if hasattr(self, '_sb_toggle_btn'):
                self._sb_toggle_btn.config(text="◁")
            self.workspace_frame.pack_configure(padx=(0, 0))

        def on_directory_focus_out(self, event):
            selection = self.dir_listbox.curselection()
            if selection:
                self.current_selected_dir_index = selection[0]

        def on_directory_focus_in(self, event):
            if self.current_selected_dir_index is not None and self.current_selected_dir_index < self.dir_listbox.size():
                self.dir_listbox.selection_clear(0, tk.END)
                self.dir_listbox.selection_set(self.current_selected_dir_index)
                self.dir_listbox.activate(self.current_selected_dir_index)

        def _configure_tree_style(self):
            self._configure_directory_ttk_styles()

        def setup_exclusion_section(self):
            self._set_workspace_title("Home", self._selected_directory_summary())

            self._reapply_tree_columns()
            self._configure_tree_style()

            self.show_videos_var = tk.BooleanVar(value=self.show_videos)
            self.excluded_only_var = tk.BooleanVar(value=self.show_only_excluded)
            self.expand_all_var = tk.BooleanVar(value=self.expand_all_default)
            self.save_directories_var = tk.BooleanVar(value=True)
            self.speed_var = tk.DoubleVar(value=1.0)


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

        def _lazy_expand_node(self, iid, directory):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                return

            existing = self.exclusion_tree.get_children(iid)
            placeholder_only = (
                len(existing) == 1 and
                self.exclusion_tree.item(existing[0], "tags") == ("placeholder",)
            )
            if existing and not placeholder_only:
                self.exclusion_tree.item(iid, open=True)
                return

            for child in existing:
                try:
                    self.exclusion_tree.delete(child)
                    self.current_subdirs_mapping.pop(child, None)
                except Exception:
                    pass

            ph = f"__lz_loading_{iid}__"
            self.exclusion_tree.insert(iid, tk.END, iid=ph, text="  Loading…", tags=("placeholder",))
            self.exclusion_tree.item(iid, open=True)

            excluded_dir_set = set(os.path.normpath(p) for p in self.excluded_subdirs.get(selected_dir, []))
            excluded_vid_set = set(os.path.normpath(p) for p in self.excluded_videos.get(selected_dir, []))
            show_videos = self.show_videos
            only_excl = self.show_only_excluded
            base = selected_dir
            node_dir = os.path.abspath(directory)

            def build():
                items = []
                iid_counter = [0]

                def next_iid():
                    iid_counter[0] += 1
                    return f"lz_{iid}_{iid_counter[0]}"

                try:
                    with os.scandir(node_dir) as it:
                        entries = sorted(it, key=lambda e: (not e.is_dir(), e.name.lower()))
                    for entry in entries:
                        full = entry.path
                        norm_full = os.path.normpath(full)
                        if entry.is_dir():
                            child_iid = next_iid()
                            items.append((child_iid, full, True))
                        elif show_videos and entry.is_file() and is_video(entry.name):
                            is_excl_v = norm_full in excluded_vid_set
                            if only_excl and not is_excl_v:
                                continue
                            child_iid = next_iid()
                            items.append((child_iid, full, False))
                except PermissionError:
                    pass

                def post():
                    try:
                        self.exclusion_tree.delete(ph)
                    except Exception:
                        pass

                    if not items:
                        self.exclusion_tree.insert(iid, tk.END,
                            iid=f"__lz_empty_{iid}__",
                            text="  Empty", tags=("placeholder",))
                        return

                    for child_iid, path, is_dir in items:
                        tag = self._tag_for_item(path, base, excluded_dir_set, excluded_vid_set)
                        label = self._label_for_item(path, is_dir, excluded_dir_set, excluded_vid_set, base)
                        if is_dir:
                            ph2 = f"__lz_ph_{child_iid}__"
                            self.exclusion_tree.insert(iid, tk.END, iid=child_iid,
                                text=label, tags=(tag,), open=False, values=())
                            self.exclusion_tree.insert(child_iid, tk.END,
                                iid=ph2, text="  Loading…", tags=("placeholder",))
                        else:
                            self.exclusion_tree.insert(iid, tk.END, iid=child_iid,
                                text=label, tags=(tag,), values=())
                        self.current_subdirs_mapping[child_iid] = path

                    if hasattr(self, 'video_preview_manager') and self.video_preview_manager:
                        self.video_preview_manager.attach_to_listbox(
                            self.exclusion_tree, self.current_subdirs_mapping)

                self.root.after(0, post)

            ManagedThread(target=build, name="LazyExpand").start()

        def _on_tree_open(self, event):
            iid = self.exclusion_tree.focus()
            path = self.current_subdirs_mapping.get(iid)
            if path and os.path.isdir(path):
                norm = os.path.normpath(path)
                self.expanded_paths.add(norm)
                self.collapsed_paths.discard(norm)
                existing = self.exclusion_tree.get_children(iid)
                placeholder_only = (
                    len(existing) == 1 and
                    self.exclusion_tree.item(existing[0], 'tags') == ('placeholder',)
                )
                if not existing or placeholder_only:
                    self._lazy_expand_node(iid, path)

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
                norm_target = os.path.normpath(target_path)
                if self.exclusion_tree.item(iid, "open"):
                    self.exclusion_tree.item(iid, open=False)
                    self.collapsed_paths.add(norm_target)
                    self.expanded_paths.discard(norm_target)
                else:
                    self.expanded_paths.add(norm_target)
                    self.collapsed_paths.discard(norm_target)
                    self._lazy_expand_node(iid, target_path)
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
                context_menu.add_command(label="Clear Selection",
                    command=lambda: self.exclusion_tree.selection_remove(self._tree_get_all_iids()))

            context_menu.add_separator()
            context_menu.add_command(label="Open in Gallery",
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
            """Remove all non-root rows from the Treeview and reset non-root mapping entries."""
            root_iids = set(getattr(self, '_dir_root_iids', []))
            # Clear children of each root node
            for riid in root_iids:
                try:
                    for child in list(self.exclusion_tree.get_children(riid)):
                        self.exclusion_tree.delete(child)
                except Exception:
                    pass
            # Remove any top-level items that are NOT root dir nodes (placeholders etc.)
            for iid in list(self.exclusion_tree.get_children()):
                if iid not in root_iids:
                    try:
                        self.exclusion_tree.delete(iid)
                    except Exception:
                        pass
            # Rebuild mapping keeping only root entries
            new_mapping = {}
            for riid in root_iids:
                if riid in self.current_subdirs_mapping:
                    new_mapping[riid] = self.current_subdirs_mapping[riid]
            self.current_subdirs_mapping = new_mapping

        def load_subdirectories(self, directory, max_depth=20, restore_path=None, restore_scroll=None, _root_iid=None):
            self.current_max_depth = max_depth
            # Auto-resolve root iid from directory path
            if _root_iid is None and hasattr(self, '_dir_root_iids') and hasattr(self, 'selected_dirs'):
                for i, d in enumerate(self.selected_dirs):
                    if d == directory and i < len(self._dir_root_iids):
                        _root_iid = self._dir_root_iids[i]
                        break

            if _root_iid is not None:
                # Scoped load: populate under a specific root node, don't clear whole tree
                # Remove existing children first
                for child in list(self.exclusion_tree.get_children(_root_iid)):
                    try:
                        self.exclusion_tree.delete(child)
                        if child in self.current_subdirs_mapping:
                            del self.current_subdirs_mapping[child]
                    except Exception:
                        pass
                loading_iid = f"__loading_{_root_iid}__"
                self.exclusion_tree.insert(_root_iid, tk.END, iid=loading_iid,
                                           text="  Loading…", tags=("placeholder",))
                self.exclusion_tree.item(_root_iid, open=True)
            else:
                self._clear_tree()
                self.exclusion_tree.insert("", tk.END, iid="__loading__",
                                           text="  Loading…ª", tags=("placeholder",))

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

                    def next_iid():
                        self._tree_iid_counter += 1
                        return f"t{self._tree_iid_counter}"

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
                            if _root_iid is not None:
                                path_to_iid[norm_root] = _root_iid
                            else:
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

                        if _root_iid is not None:
                            # Remove loading placeholder under root node
                            loading_iid = f"__loading_{_root_iid}__"
                            try:
                                self.exclusion_tree.delete(loading_iid)
                            except Exception:
                                pass
                            if not items:
                                self.exclusion_tree.insert(_root_iid, tk.END,
                                                           iid=f"__empty_{_root_iid}__",
                                                           text="  No items found", tags=("placeholder",))
                                return
                        else:
                            self._clear_tree()

                        mapping      = {} if _root_iid is None else dict(self.current_subdirs_mapping)
                        target_iid   = None
                        restore_norm = os.path.normpath(restore_path) if restore_path else None

                        if _root_iid is None and not items:
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
                                rating_str = tags_str = ""

                                self.exclusion_tree.insert(
                                    parent_iid, tk.END, iid=iid,
                                    text=label, tags=(tag,),
                                    open=open_state,
                                    values=()
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

                        # self.selected_dir_label.config(
                        #     text=f"Filtered: {len(filtered_sorted)} videos in '{os.path.basename(selected_dir)}'"
                        # )
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

            # self.selected_dir_label.config(
            #     text=f"Filtered: {len(filtered_sorted)} videos in '{os.path.basename(selected_dir)}'"
            # )

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
            player.on_video_end          = self._on_player_video_end
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
            selected_dirs = self._get_effective_selected_dirs()
            self._show_embedded_view(
                "tags",
                lambda frame: self._show_annotation_browser_embedded(frame, selected_dirs)
            )

        def _show_annotation_browser_embedded(self, frame, selected_dirs):
            ui = self.annotation_browser.show_embedded(
                frame,
                close_callback=self._show_home_view
            )
            if hasattr(ui, "set_directory_filter"):
                ui.set_directory_filter(selected_dirs)
                ui.refresh()
            return ui

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
            if getattr(self, '_active_app_view', None) == 'home':
                self.root.after(150, self._render_home_dashboard)

        def _save_loop_callback(self, loop_mode: str):
            self.loop_mode = loop_mode
            if hasattr(self, 'loop_toggle_button'):
                try: self.loop_toggle_button.config(text=self._get_loop_icon())
                except Exception: pass
            if hasattr(self, '_loop_mode_var'):
                try: self._loop_mode_var.set(loop_mode)
                except Exception: pass
            self.save_preferences()

        def _on_player_video_end(self, path: str, pos: int, dur: int):
            if hasattr(self, 'watch_history_manager') and path:
                self.watch_history_manager.track_video_end(path, pos // 1000, dur // 1000)

        def _on_player_close_save(self, index, path, loop_mode, volume, is_muted, duration_watched=0, total_duration=0):
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
                self.watch_history_manager.track_video_end(path, duration_watched // 1000, total_duration // 1000)

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
            self._set_workspace_title(
                getattr(self, "_view_tab_labels", {}).get(getattr(self, "_active_app_view", "home"), "Home"),
                self._selected_directory_summary()
            )
            self._refresh_active_manager_for_directory_context(selected_dir)
            self.expanded_paths.clear()
            self.collapsed_paths.clear()
            self.load_subdirectories(selected_dir, max_depth=20)

        def _refresh_active_manager_for_directory_context(self, forced_dir=None):
            active = getattr(self, "_active_app_view", "home")
            if active == "favourites":
                self._show_favorites_manager()
            elif active == "gallery":
                self._show_grid_view_for_current_directory(forced_dir=forced_dir)
            elif active == "home":
                pass
            elif active == "history" and getattr(self, "active_embedded_manager", None):
                try:
                    self.active_embedded_manager.set_directory_filter(self._get_effective_selected_dirs())
                    self.active_embedded_manager.refresh()
                except Exception:
                    pass
            elif active == "tags" and getattr(self, "active_embedded_manager", None):
                try:
                    self.active_embedded_manager.set_directory_filter(self._get_effective_selected_dirs())
                    self.active_embedded_manager.refresh()
                except Exception:
                    pass

        def _show_grid_view_for_current_directory(self, forced_dir=None):
            selected_dirs = self.get_selected_directories()
            selected_dir = forced_dir or self.get_current_selected_directory()
            if not selected_dirs and selected_dir:
                selected_dirs = [selected_dir]
            if forced_dir and forced_dir not in selected_dirs:
                selected_dirs = [forced_dir]
            if not selected_dirs:
                selected_dirs = list(self.selected_dirs)
            if not selected_dirs:
                return

            def collect_all():
                all_videos = []
                seen = set()
                for directory in selected_dirs:
                    cache = self.scan_cache.get(directory)
                    if not cache:
                        continue
                    videos, _, _ = cache
                    for video in videos:
                        if self.is_video_excluded(directory, video):
                            continue
                        norm = os.path.normpath(video)
                        if norm not in seen:
                            seen.add(norm)
                            all_videos.append(video)
                if all_videos:
                    self.root.after(0, lambda: self._open_grid_view(all_videos))

            self._wait_for_scans_then(
                selected_dirs,
                lambda: threading.Thread(target=collect_all, daemon=True).start()
            )

        def get_selected_directories(self):
            if not hasattr(self, "dir_listbox"):
                return []
            return [
                self.selected_dirs[i]
                for i in self.dir_listbox.curselection()
                if i < len(self.selected_dirs)
            ]

        def clear_exclusion_list(self):
            # self.selected_dir_label.config(text="Select a directory to see its folders and videos")
            self._clear_tree()

        def on_search_changed(self, event=None):
            try:
                new_query = self.search_entry.get().strip().lower()
            except Exception:
                new_query = ""
            if new_query == self.search_query:
                return
            if hasattr(self, '_search_debounce_id'):
                self.root.after_cancel(self._search_debounce_id)

            def _do_search():
                self.search_query = new_query
                selected_dir = self.get_current_selected_directory()
                if selected_dir:
                    self.load_subdirectories(selected_dir)

            self._search_debounce_id = self.root.after(300, _do_search)

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

            return None

        def _get_effective_selected_dirs(self):
            selected = self.get_selected_directories()
            return selected if selected else list(self.selected_dirs)

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
            pending = 0

            for directory in self.selected_dirs:
                cache = self.scan_cache.get(directory)
                if not cache:
                    pending += 1
                    continue
                videos, _, _ = cache
                total_videos += sum(1 for v in videos if not self.is_video_excluded(directory, v))

            self.video_count = total_videos

            if hasattr(self, 'workspace_context_label'):
                suffix = f" (scanning {pending}…)" if pending else ""
                self.workspace_context_label.config(
                    text=self._selected_directory_summary() if not pending else
                    f"{total_videos} videos{suffix}"
                )

            if (not pending and
                    not hasattr(self, '_last_reported_video_count') or
                    (not pending and getattr(self, '_last_reported_video_count', None) != total_videos)):
                self._last_reported_video_count = total_videos
                self.update_console(
                    f"Total: {total_videos} videos from {len(self.selected_dirs)} "
                    f"director{'ies' if len(self.selected_dirs) != 1 else 'y'}")
            if getattr(self, '_active_app_view', None) == 'home':
                if hasattr(self, '_home_dirs_label') and self._home_dirs_label.winfo_exists():
                    self._home_dirs_label.config(text=str(len(self.selected_dirs)))
                if hasattr(self, '_home_vids_label') and self._home_vids_label.winfo_exists():
                    self._home_vids_label.config(text=str(total_videos))

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
            self.save_preferences()
            if self.expand_all_var.get():
                self._expand_all_tree_nodes()
            else:
                self._collapse_all_tree_nodes()

        def _collapse_all_tree_nodes(self):
            self.expanded_paths.clear()
            self.collapsed_paths.clear()
            # Remove all children from every root node — only root dirs remain visible
            root_iids = set(self._dir_root_iids)
            for root_iid in self._dir_root_iids:
                for child in list(self.exclusion_tree.get_children(root_iid)):
                    try:
                        self.exclusion_tree.delete(child)
                    except Exception:
                        pass
            # Rebuild mapping: keep only root entries
            self.current_subdirs_mapping = {
                iid: path for iid, path in self.current_subdirs_mapping.items()
                if iid in root_iids
            }

        def _expand_all_tree_nodes(self):
            self.expanded_paths.clear()
            self.collapsed_paths.clear()
            show_videos = self.show_videos
            only_excl = self.show_only_excluded
            iid_counter = [0]

            def next_iid():
                iid_counter[0] += 1
                return f"ea_{iid_counter[0]}"

            def fmt_size(b):
                if b >= 1024 ** 3:
                    return f"{b / 1024 ** 3:.2f} GB"
                elif b >= 1024 ** 2:
                    return f"{b / 1024 ** 2:.1f} MB"
                return f"{b // 1024} KB"

            def expand_recursive(parent_iid, directory, root_dir):
                excluded_dir_set = set(os.path.normpath(p) for p in self.excluded_subdirs.get(root_dir, []))
                excluded_vid_set = set(os.path.normpath(p) for p in self.excluded_videos.get(root_dir, []))

                # Clear existing children (placeholder or stale)
                for child in list(self.exclusion_tree.get_children(parent_iid)):
                    try:
                        self.exclusion_tree.delete(child)
                        self.current_subdirs_mapping.pop(child, None)
                    except Exception:
                        pass

                try:
                    with os.scandir(directory) as it:
                        entries = sorted(it, key=lambda e: (not e.is_dir(), e.name.lower()))
                except PermissionError:
                    return

                for entry in entries:
                    full = entry.path
                    norm_full = os.path.normpath(full)
                    child_iid = next_iid()
                    tag = self._tag_for_item(full, root_dir, excluded_dir_set, excluded_vid_set)
                    label = self._label_for_item(full, entry.is_dir(), excluded_dir_set, excluded_vid_set, root_dir)
                    if entry.is_dir():
                        try:
                            size_str = fmt_size(sum(
                                os.path.getsize(os.path.join(dp, fn))
                                for dp, _, fnames in os.walk(full) for fn in fnames
                            ))
                        except Exception:
                            size_str = ""
                        vals = ()
                        self.exclusion_tree.insert(parent_iid, tk.END, iid=child_iid,
                            text=label, tags=(tag,), open=True, values=vals)
                        self.current_subdirs_mapping[child_iid] = full
                        expand_recursive(child_iid, full, root_dir)
                    elif show_videos and entry.is_file() and is_video(entry.name):
                        norm_full = os.path.normpath(full)
                        is_excl_v = norm_full in excluded_vid_set
                        if only_excl and not is_excl_v:
                            continue
                        try:
                            size_str = fmt_size(os.path.getsize(full))
                        except Exception:
                            size_str = ""
                        rating_str = ""
                        tags_str = ""
                        vals = ()
                        self.exclusion_tree.insert(parent_iid, tk.END, iid=child_iid,
                            text=label, tags=(tag,), values=vals)
                        self.current_subdirs_mapping[child_iid] = full

                self.exclusion_tree.item(parent_iid, open=True)

            def worker():
                # Collect (root_iid, root_path) pairs for all main dirs
                pairs = []
                for i, root_iid in enumerate(self._dir_root_iids):
                    root_path = self.selected_dirs[i] if i < len(self.selected_dirs) else None
                    if root_path and os.path.isdir(root_path):
                        pairs.append((root_iid, root_path))

                def do_expand():
                    for root_iid, root_path in pairs:
                        expand_recursive(root_iid, root_path, root_path)
                    if hasattr(self, "video_preview_manager") and self.video_preview_manager:
                        self.video_preview_manager.attach_to_listbox(
                            self.exclusion_tree, self.current_subdirs_mapping)

                self.root.after(0, do_expand)

            ManagedThread(target=worker, name="ExpandAll").start()

        def toggle_videos_visibility(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showinfo("Information", "Please select a directory first.")
                return
            self.show_videos = not self.show_videos  # flip directly
            if hasattr(self, 'show_videos_var'):
                self.show_videos_var.set(self.show_videos)  # keep var in sync
            self._refresh_dir_action_states()
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

            self._show_main_dir_context_menu_for_index(event, selection[0])

        def _show_main_dir_context_menu_for_index(self, event, index):
            context_menu = self._make_context_menu()
            context_menu.add_command(label="Play Selected",      command=self._play_selected_main_dirs)
            context_menu.add_command(label="Open in Gallery",  command=self._open_grid_view_main_dirs)
            context_menu.add_separator()
            context_menu.add_command(label="Remove Selected",    command=self.remove_directory)
            try:
                context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                context_menu.grab_release()

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
            selected_dirs = self.get_selected_directories()
            selected_scope = selected_dirs if len(selected_dirs) > 1 else self.get_current_selected_directory()
            if not selected_scope:
                selected_scope = list(self.selected_dirs)
            self._show_embedded_view(
                "favourites",
                lambda frame: self.favorites_manager.show_embedded(
                    frame,
                    selected_scope,
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

        def locate_in_directory_panel(self, video_path):
            if not video_path or not os.path.isfile(video_path):
                return
            norm_target = os.path.normpath(video_path)

            for iid, path in list(self.current_subdirs_mapping.items()):
                if os.path.normpath(path) == norm_target:
                    self._tree_reveal_item(iid)
                    return

            root_iid, root_dir = None, None
            for i, d in enumerate(self.selected_dirs):
                if norm_target.startswith(os.path.normpath(d) + os.sep):
                    root_dir = d
                    if i < len(self._dir_root_iids):
                        root_iid = self._dir_root_iids[i]
                    break

            if root_iid is None:
                return

            norm_root = os.path.normpath(root_dir)
            parts = os.path.relpath(norm_target, norm_root).split(os.sep)
            current_iid = root_iid
            current_dir = norm_root

            for part in parts:
                target_path = os.path.normpath(os.path.join(current_dir, part))
                found_iid = next(
                    (c for c in self.exclusion_tree.get_children(current_iid)
                     if os.path.normpath(self.current_subdirs_mapping.get(c, '')) == target_path),
                    None
                )
                if found_iid is None:
                    for ch in list(self.exclusion_tree.get_children(current_iid)):
                        if self.exclusion_tree.item(ch, 'tags') == ('placeholder',):
                            try:
                                self.exclusion_tree.delete(ch)
                                self.current_subdirs_mapping.pop(ch, None)
                            except Exception:
                                pass
                    try:
                        with os.scandir(current_dir) as it:
                            entries = sorted(it, key=lambda e: (not e.is_dir(), e.name.lower()))
                        existing_paths = {
                            os.path.normpath(self.current_subdirs_mapping.get(c, ''))
                            for c in self.exclusion_tree.get_children(current_iid)
                        }
                        for entry in entries:
                            ep = os.path.normpath(entry.path)
                            if ep in existing_paths:
                                continue
                            if not entry.is_dir() and not is_video(entry.name):
                                continue
                            self._tree_iid_counter += 1
                            new_iid = f"loc_{self._tree_iid_counter}"
                            if entry.is_dir():
                                self.exclusion_tree.insert(current_iid, tk.END, iid=new_iid,
                                                           text=f"📁 {entry.name}", tags=("folder",))
                                self._tree_iid_counter += 1
                                self.exclusion_tree.insert(new_iid, tk.END,
                                                           iid=f"loc_ph_{self._tree_iid_counter}",
                                                           text="  Loading…", tags=("placeholder",))
                            else:
                                self.exclusion_tree.insert(current_iid, tk.END, iid=new_iid,
                                                           text=f"🎬 {entry.name}", tags=("video",))
                            self.current_subdirs_mapping[new_iid] = entry.path
                            if ep == target_path:
                                found_iid = new_iid
                    except Exception:
                        pass

                if found_iid is None:
                    return
                self.exclusion_tree.item(current_iid, open=True)
                current_iid = found_iid
                current_dir = target_path

            self._tree_reveal_item(current_iid)

        def _tree_reveal_item(self, iid):
            self.exclusion_tree.selection_set(iid)
            self.exclusion_tree.focus(iid)
            self.exclusion_tree.see(iid)

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

        def _add_videos_to_favorites_smart(self, videos):
            cur_dir = self.get_current_selected_directory()
            if cur_dir:
                self.favorites_manager.add_to_favorites(videos, cur_dir)
                return
            by_dir = {}
            for v in videos:
                d = self._find_root_dir_for_video(v) or os.path.dirname(v)
                by_dir.setdefault(d, []).append(v)
            for d, vids in by_dir.items():
                self.favorites_manager.add_to_favorites(vids, d)

        def _remove_videos_from_favorites_smart(self, videos):
            cur_dir = self.get_current_selected_directory()
            if cur_dir:
                self.favorites_manager.remove_from_favorites(videos, cur_dir)
                return
            by_dir = {}
            for v in videos:
                d = self._find_root_dir_for_video(v) or os.path.dirname(v)
                by_dir.setdefault(d, []).append(v)
            for d, vids in by_dir.items():
                self.favorites_manager.remove_from_favorites(vids, d)

        def _is_favourite_smart(self, video_path):
            cur_dir = self.get_current_selected_directory()
            if cur_dir:
                return self.favorites_manager.is_favorite(video_path, cur_dir)
            d = self._find_root_dir_for_video(video_path) or os.path.dirname(video_path)
            return self.favorites_manager.is_favorite(video_path, d)

        def _find_root_dir_for_video(self, video_path):
            """Return the selected_dirs root that owns video_path, or None."""
            norm_vp = os.path.normpath(video_path)
            best = None
            best_len = -1
            for rd in self.selected_dirs:
                norm_rd = os.path.normpath(rd)
                try:
                    if norm_vp.startswith(norm_rd + os.sep) or norm_vp == norm_rd:
                        if len(norm_rd) > best_len:
                            best = rd
                            best_len = len(norm_rd)
                except Exception:
                    pass
            return best

        def _grid_exclude_video(self, video_path):
            root_dir = self._find_root_dir_for_video(video_path)
            if not root_dir:
                return
            norm_vp = os.path.normpath(video_path)
            if root_dir not in self.excluded_videos:
                self.excluded_videos[root_dir] = []
            if norm_vp not in (os.path.normpath(v) for v in self.excluded_videos[root_dir]):
                self.excluded_videos[root_dir].append(video_path)
            self.update_console(f"Excluded: {os.path.basename(video_path)}")
            self.update_video_count()
            self._retag_video_in_tree(video_path, root_dir)
            if self.save_directories:
                self.save_preferences()

        def _grid_remove_exclusion_video(self, video_path):
            root_dir = self._find_root_dir_for_video(video_path)
            if not root_dir:
                return
            if root_dir in self.excluded_videos:
                norm_vp = os.path.normpath(video_path)
                self.excluded_videos[root_dir] = [
                    v for v in self.excluded_videos[root_dir]
                    if os.path.normpath(v) != norm_vp
                ]
                if not self.excluded_videos[root_dir]:
                    del self.excluded_videos[root_dir]
            self.update_console(f"Removed exclusion: {os.path.basename(video_path)}")
            self.update_video_count()
            self._retag_video_in_tree(video_path, root_dir)
            if self.save_directories:
                self.save_preferences()

        def _retag_video_in_tree(self, video_path, root_dir):
            """Update the tag and label of a single video item in the exclusion tree."""
            if not hasattr(self, 'exclusion_tree') or not hasattr(self, 'current_subdirs_mapping'):
                return
            norm_vp = os.path.normpath(video_path)
            excluded_dir_set = set(os.path.normpath(p) for p in self.excluded_subdirs.get(root_dir, []))
            excluded_vid_set = set(os.path.normpath(p) for p in self.excluded_videos.get(root_dir, []))
            for iid, path in list(self.current_subdirs_mapping.items()):
                if os.path.normpath(path) == norm_vp:
                    try:
                        tag   = self._tag_for_item(path, root_dir, excluded_dir_set, excluded_vid_set)
                        label = self._label_for_item(path, False, excluded_dir_set, excluded_vid_set, root_dir)
                        self.exclusion_tree.item(iid, text=label, tags=(tag,))
                    except Exception:
                        pass
                    break

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
            all_directories = []
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

            original_on_video_changed = player.on_video_changed

            def on_queue_video_changed(video_index, video_path):
                if original_on_video_changed:
                    original_on_video_changed(video_index, video_path)
                norm_path = os.path.normpath(video_path)
                with self.queue_manager.service._lock:
                    for qi, entry in enumerate(self.queue_manager.service._queue):
                        if os.path.normpath(entry.video_path) == norm_path:
                            for j in range(qi):
                                self.queue_manager.service._queue[j].played = True
                            self.queue_manager.service._current_index = qi
                            self.queue_manager.service.storage.save_queue(
                                self.queue_manager.service._queue,
                                qi
                            )
                            break
                if hasattr(self.queue_manager, 'ui') and self.queue_manager.ui:
                    self.queue_manager.ui._refresh_queue()

            player.on_video_changed = on_queue_video_changed
            original_on_close_save = player.on_close_save

            def on_queue_close_save(index, path, loop_mode, volume, is_muted):
                if original_on_close_save:
                    original_on_close_save(index, path, loop_mode, volume, is_muted)
                norm_path = os.path.normpath(path) if path else None
                if norm_path:
                    with self.queue_manager.service._lock:
                        for entry in self.queue_manager.service._queue:
                            if os.path.normpath(entry.video_path) == norm_path:
                                entry.played = True
                                self.queue_manager.service.storage.save_queue(
                                    self.queue_manager.service._queue,
                                    self.queue_manager.service._current_index
                                )
                                break
                if hasattr(self.queue_manager, 'ui') and self.queue_manager.ui:
                    self.queue_manager.ui._refresh_queue()

            player.on_close_save = on_queue_close_save
            self._launch_player(player)

        def _show_watch_history(self):
            selected_dirs = self._get_effective_selected_dirs()
            self._show_embedded_view(
                "history",
                lambda frame: self._show_history_embedded(frame, selected_dirs)
            )

        def _show_history_embedded(self, frame, selected_dirs):
            ui = self.watch_history_manager.show_embedded(
                frame,
                close_callback=self._show_home_view
            )
            if hasattr(ui, "set_directory_filter"):
                ui.set_directory_filter(selected_dirs)
                ui.refresh()
            return ui

        def _play_continue_watching_video(self, video_path):
            if not video_path or not os.path.isfile(video_path):
                return

            norm_path = os.path.normpath(video_path)

            saved_pos = self.resume_manager.service.get_resume_position(norm_path)

            if saved_pos is None and hasattr(self, 'watch_history_manager'):
                try:
                    all_hist = self.watch_history_manager.service.get_all_history()
                    for _he in sorted(all_hist, key=lambda x: x.watched_at, reverse=True):
                        if os.path.normpath(_he.video_path) == norm_path:
                            if _he.duration_watched > 0 and _he.total_duration > 0:
                                _pos_ms = int(_he.duration_watched * 1000)
                                _dur_ms = int(_he.total_duration * 1000)
                                self.resume_manager.service.update_position(
                                    norm_path, _pos_ms, _dur_ms)
                                saved_pos = self.resume_manager.service.get_resume_position(
                                    norm_path)
                            break
                except Exception:
                    pass

            if hasattr(self, 'watch_history_manager'):
                try:
                    all_hist = self.watch_history_manager.service.get_all_history()
                    for _he in sorted(all_hist, key=lambda x: x.watched_at, reverse=True):
                        if os.path.normpath(_he.video_path) == norm_path:
                            self.watch_history_manager.set_resume_entry(norm_path, _he.id)
                            break
                except Exception:
                    pass

            vdir = os.path.dirname(video_path)
            player = self._make_player(
                [video_path], {video_path: vdir}, [vdir], 0)

            _orig_enabled = self.resume_manager._resume_enabled
            if saved_pos is not None:
                self.resume_manager.set_resume_enabled(True)

            self._launch_player(player)

            if saved_pos is not None and not _orig_enabled:
                self.root.after(3000,
                                lambda: self.resume_manager.set_resume_enabled(_orig_enabled))

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
            selected_dirs = self.get_selected_directories()
            selected_dir = self.get_current_selected_directory()
            if not selected_dirs and selected_dir:
                selected_dirs = [selected_dir]
            if not selected_dirs:
                selected_dirs = list(self.selected_dirs)
            if not selected_dirs:
                self._set_workspace_title("Gallery", "No directory selected")
                return
            selected_dir = selected_dirs[0]

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
                scope_text = "selected directories" if len(selected_dirs) > 1 else "entire directory"
                self.update_console(f"Loading grid view for {scope_text}...")

                def collect_all():
                    all_videos = []
                    seen = set()
                    for directory in selected_dirs:
                        cache = self.scan_cache.get(directory)
                        if not cache:
                            continue
                        videos, _, _ = cache
                        for video in videos:
                            if self.is_video_excluded(directory, video):
                                continue
                            norm = os.path.normpath(video)
                            if norm not in seen:
                                seen.add(norm)
                                all_videos.append(video)
                    if all_videos:
                        self.root.after(0, lambda: self._open_grid_view(all_videos))
                    else:
                        self.root.after(0, lambda: messagebox.showwarning("Warning", "No videos found"))

                self._wait_for_scans_then(selected_dirs,
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
                new_idx = len(self.selected_dirs) - 1
                self._dir_root_iids_select_and_trigger(new_idx)

        def _dir_root_iids_select_and_trigger(self, idx):
            if not hasattr(self, '_dir_root_iids') or idx >= len(self._dir_root_iids):
                self.root.after(300, lambda: self._dir_root_iids_select_and_trigger(idx))
                return
            iid = self._dir_root_iids[idx]
            self.exclusion_tree.selection_set(iid)
            self.exclusion_tree.see(iid)
            self._trigger_root_selection(iid)

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
            pass

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

        def _make_media_pill(self, label):
            container = tk.Frame(self.workspace_nav, bg=self.bg_color)
            container.pack(side=tk.LEFT, padx=2)

            btn = tk.Label(container, text=label,
                           bg=self.bg_color, fg=self.text_muted,
                           font=("Segoe UI", 10, "normal"),
                           padx=14, pady=3, cursor="hand2")
            btn.pack(fill=tk.X)
            btn._pill_container = container

            def on_press(_e):
                btn.config(fg=self.accent_color, font=("Segoe UI", 10, "bold"))

            def on_release(_e):
                cmd = {
                    "Home": self._show_home_view,
                    "Gallery": self._show_grid_view,
                    "Playlist": self._manage_playlists,
                    "Queue": self._show_queue_manager,
                    "Favourites": self._show_favorites_manager,
                    "Tags & Ratings": self._show_annotation_browser,
                    "History": self._show_watch_history,
                }[label]
                cmd()

            btn.bind("<ButtonPress-1>", on_press)
            btn.bind("<ButtonRelease-1>", on_release)
            self._bind_media_pill_hover(btn, label)

            self._media_pill_btns[label] = btn
            return btn

        def setup_action_buttons(self):
            self._view_tab_labels = {
                "home": "Home",
                "gallery": "Gallery",
                "playlist": "Playlist",
                "queue": "Queue",
                "favourites": "Favourites",
                "history": "History",
                "tags": "Tags & Ratings",
            }

            def _tb_colors():
                return {
                    "bg": self.surface_color,
                    "fg": self.text_color,
                    "hover": self.hover_color,
                    "hover_bg": self.hover_color,
                    "hover_fg": self.text_color,
                    "active": self.accent_color,
                    "border": self.border_color,
                    "play_fg": self.accent_secondary,
                    "play_hover_bg": "#FF5555",
                    "play_active_bg": "#E04444",
                    "play_text": self.accent_secondary,
                    "play_text_hover": "#FF8A8A" if self.dark_mode else "#E85555",
                    "play_text_active": "#A83C3C" if self.dark_mode else "#9E3333",
                }

            self._tb_colors = _tb_colors
            self.toolbar = tk.Frame(self.root, bg=_tb_colors()["bg"])
            self.toolbar.pack_propagate(False)
            self._toolbar_btns = {}
            self._toolbar_menus = {}
            self._toolbar_commands = {}

            for pill_label in ["Home", "Gallery", "Tags & Ratings", "Playlist", "Favourites", "Queue", "History"]:
                self._make_media_pill(pill_label)

            sb = self._sidebar_panel

            def make_dropdown_menu(entries):
                c = _tb_colors()
                menu = tk.Menu(self.root, tearoff=0,
                               bg=c["bg"], fg=c["fg"],
                               activebackground=c["hover"],
                               activeforeground=c["fg"],
                               relief="flat", bd=1, font=("Segoe UI", 10))
                for entry in entries:
                    if entry is None:
                        menu.add_separator()
                    else:
                        lbl, cmd = entry
                        menu.add_command(label=lbl, command=cmd)
                return menu

            def _sb_sep():
                tk.Frame(sb, bg=self.border_color, height=1).pack(fill=tk.X, padx=10, pady=(5, 5))

            def _sb_btn(icon, tip, menu=None, command=None):
                btn = tk.Label(
                    sb, text=icon,
                    bg=self.surface_color, fg=self.text_color,
                    font=("Segoe UI", 15, "bold"), anchor="center",
                    pady=10, cursor="hand2",
                    relief=tk.FLAT, bd=0, highlightthickness=0,
                )
                btn.pack(fill=tk.X, pady=(2, 0))
                _tip_win = [None]

                def _show_tip(e):
                    if _tip_win[0]: return
                    x = btn.winfo_rootx() + btn.winfo_width() + 6
                    y = btn.winfo_rooty() + 4
                    tw = tk.Toplevel(btn)
                    tw.wm_overrideredirect(True)
                    tw.wm_geometry(f"+{x}+{y}")
                    tk.Label(tw, text=tip, bg=self.console_bg, fg=self.console_fg,
                             font=("Segoe UI", 9), padx=8, pady=4, relief="flat").pack()
                    _tip_win[0] = tw

                def _hide_tip(e):
                    if _tip_win[0]:
                        try: _tip_win[0].destroy()
                        except: pass
                        _tip_win[0] = None

                def on_enter(e):
                    btn.config(bg=self.accent_color, fg="#ffffff")
                    _show_tip(e)

                def on_leave(e):
                    btn.config(bg=self.surface_color, fg=self.text_color)
                    _hide_tip(e)

                def on_press(e):
                    btn.config(bg=self.accent_color, fg="#ffffff")

                def on_release(e):
                    btn.config(bg=self.accent_color, fg="#ffffff")
                    if menu is not None:
                        try:
                            menu.tk_popup(btn.winfo_rootx() + btn.winfo_width() + 4, btn.winfo_rooty())
                        finally:
                            menu.grab_release()
                    elif command is not None:
                        command()

                btn.bind("<Enter>", on_enter)
                btn.bind("<Leave>", on_leave)
                btn.bind("<ButtonPress-1>", on_press)
                btn.bind("<ButtonRelease-1>", on_release)
                return btn

            _sb_sep()

            file_menu = make_dropdown_menu([

                ("Add Directory", self.add_directory),
                ("Add Google Drive Link", self.add_drive_link),
            ])
            self._toolbar_menus["File"] = file_menu
            self._toolbar_btns["File"] = _sb_btn("📁", "File", menu=file_menu)

            self._view_menu = make_dropdown_menu([
                ("Hide Console" if self.show_console else "Show Console", self.toggle_console),
                None,
                ("Filter / Sort", self._show_filter_dialog),
            ])
            self._toolbar_menus["View"] = self._view_menu
            self._toolbar_btns["View"] = _sb_btn("☰", "View", menu=self._view_menu)

            self._loop_mode_var = tk.StringVar(value=self.loop_mode)
            c = _tb_colors()
            _sel_color = self.accent_color
            loop_sub = tk.Menu(self.root, tearoff=0,
                               bg=c["bg"], fg=c["fg"],
                               activebackground=c["hover"],
                               activeforeground=c["fg"],
                               selectcolor=_sel_color,
                               relief="flat", bd=1, font=("Segoe UI", 10))
            for mode, lbl in [("loop_on", "Loop On"), ("loop_off", "Loop Off"), ("shuffle", "Shuffle")]:
                loop_sub.add_radiobutton(label=lbl, variable=self._loop_mode_var, value=mode,
                                         command=lambda m=mode: self._set_loop_mode_menu(m))
            playback_menu = tk.Menu(self.root, tearoff=0,
                                    bg=c["bg"], fg=c["fg"],
                                    activebackground=c["hover"],
                                    activeforeground=c["fg"],
                                    relief="flat", bd=1, font=("Segoe UI", 10))
            playback_menu.add_cascade(label="Loop Mode", menu=loop_sub)
            playback_menu.add_separator()
            self.smart_resume_var = tk.BooleanVar(value=self.smart_resume_enabled)
            playback_menu.add_checkbutton(
                label="Smart Resume",
                variable=self.smart_resume_var,
                command=self.toggle_smart_resume,
                selectcolor=_sel_color,
            )
            self._toolbar_menus["Playback"] = playback_menu
            self._toolbar_btns["Playback"] = _sb_btn("↺", "Playback", menu=playback_menu)

            _sb_sep()

            self._toolbar_btns["Settings"] = _sb_btn("⚙", "Settings", command=self._show_settings)

            _sb_sep()

            self.theme_toolbar_btn = tk.Label(
                sb, text="🌙" if not self.dark_mode else "☀",
                bg=self.surface_color, fg=self.text_color,
                font=("Segoe UI", 15, "bold"), pady=10, cursor="hand2",
                relief=tk.FLAT, bd=0, highlightthickness=0, anchor="center"
            )
            self.theme_toolbar_btn.pack(fill=tk.X, pady=(2, 0))
            self._bind_theme_toolbar_hover()

            _sb_sep()

            self._ensure_play_toolbar_fonts()
            self.play_toolbar_btn = tk.Label(
                sb, text="▶",
                bg=self.surface_color, fg="#2ecc71",
                font=("Segoe UI", 20, "bold"), pady=12, cursor="hand2",
                relief=tk.FLAT, bd=0, highlightthickness=0, anchor="center"
            )
            self.play_toolbar_btn.pack(fill=tk.X, pady=(6, 10))
            self._bind_play_toolbar_hover()

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