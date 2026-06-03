import multiprocessing

from embedded_player import EmbeddedPlayer
from icon_helper import apply_icon
from splash import show_splash
import random as _random

try:
    from version import __version__, __commit__, __build__
except ImportError:
    __version__ = __commit__ = __build__ = "dev"

import threading
import tkinter as tk
from tkinter import filedialog
import os
import sys
from concurrent.futures import ThreadPoolExecutor

from managers.resource_manager import ThreadSafeDict, get_resource_manager, ManagedExecutor
from theme import BehaviorComposer, ThemeSelector
from mixin.backend import BackendMixin
from mixin.frontend import FrontendMixin
from mixin.manager import ManagersMixin
from mixin.theme_core import ThemeCoreMixin
from mixin.ui import UIMixin
from utils import is_video, check_vlc, show_vlc_missing_and_exit
import socket
import time
from tkinterdnd2 import DND_FILES, TkinterDnD


class DirectoryDisplayService:
    def display_name(self, directory):
        if len(directory) <= 60:
            return directory
        display_name = os.path.basename(directory)
        parent = os.path.dirname(directory)
        if parent:
            display_name = f"{os.path.basename(parent)}/{display_name}"
        return f".../{display_name}"

    def add_and_scan(self, app, directory):
        app.dir_listbox.insert(tk.END, self.display_name(directory))
        app._submit_scan(directory)


class PlayerSessionService:
    def make_player(self, app, videos, video_to_dir, directories, start_index=0):
        player = EmbeddedPlayer(
            parent=app.root,
            videos=videos,
            video_to_dir=video_to_dir,
            directories=directories,
            start_index=start_index,
            volume=getattr(app, 'volume', 50),
            is_muted=getattr(app, 'is_muted', False),
            loop_mode=getattr(app, 'loop_mode', 'loop_on'),
            logger=app.update_console,
            on_close=app._on_player_closed,
            on_volume_change=app._save_volume_callback,
            resume_manager=app.resume_manager,
            annotation_service=app.annotation_service,
        )
        player.on_loop_change = app._save_loop_callback
        player.on_close_save = app._on_player_close_save
        player.on_video_changed = app.on_video_changed
        player.on_video_end = app._on_player_video_end
        player.on_add_to_playlist = lambda vids: app.playlist_manager.add_videos_to_playlist([], vids)
        player.on_add_to_queue = lambda vids: app.queue_manager.add_to_queue(vids, added_from="player")
        player.on_add_to_favourites = lambda vids: app.favorites_manager.add_to_favorites(
            vids, app.get_current_selected_directory() or os.path.dirname(vids[0]))
        player.set_hotkeys(app.settings_manager.get_settings().hotkeys)
        player.toast = app.toast
        if hasattr(app, 'video_preview_manager') and app.video_preview_manager:
            player.set_seek_preview_manager(app.video_preview_manager)
        app_settings = app.settings_manager.get_settings()
        if app_settings.gaming_mode:
            player.set_gaming_mode(True)
        return player

    def launch_player(self, app, player):
        if app._active_player is not None:
            try:
                app._active_player._close()
            except Exception:
                pass
            app._active_player = None
        player.play()
        app._active_player = player


class AppStateInitializer:
    def initialize(self, app):
        app.selected_dirs = []
        app.excluded_subdirs = {}
        app._view_tab_labels = {}
        app._media_pill_btns = {}
        app.excluded_videos = {}
        app._is_filtered_mode = False
        app._filtered_videos = []
        app._base_directory = None
        app.controller = None
        app.player_thread = None
        app.keys_thread = None
        app.video_count = 0
        app.current_selected_dir_index = None
        app.current_subdirs_mapping = {}
        app.show_videos = True
        app.show_only_excluded = False
        app.search_query = ""
        app.expanded_paths = set()
        app.collapsed_paths = set()
        app.current_max_depth = 20
        app.loop_mode = "loop_on"
        app._active_player = None
        app._now_playing_video_path = None
        app._global_search_debounce_id = None
        app._dir_search_debounce_id = None


class PreferenceHydrator:
    def hydrate(self, app):
        preferences = app.config.load_preferences()
        app.dark_mode = preferences['dark_mode']
        app.show_videos = preferences['show_videos']
        app.expand_all_default = False
        app.save_directories = True
        app.smart_resume_enabled = preferences['smart_resume_enabled']
        app.start_from_last_played = app.smart_resume_enabled
        app.last_played_video_index = preferences['last_played_video_index']
        app.last_played_video_path = preferences['last_played_video_path']
        app.excluded_subdirs = preferences.get('excluded_subdirs', {})
        app.excluded_videos = preferences.get('excluded_videos', {})
        app.volume = preferences.get('volume', 50)
        app.is_muted = preferences.get('is_muted', False)
        app.loop_mode = preferences.get('loop_mode', 'loop_on')
        app.show_console = preferences.get('show_console', True)
        return preferences


class MainWindowConfigurator:
    def configure(self, app):
        root = app.root
        root.title("Recursive Video Player")
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        restore_w = max(1280, int(sw * 0.75))
        restore_h = max(720, int(sh * 0.75))
        cx = (sw - restore_w) // 2
        cy = (sh - restore_h) // 2
        root.geometry(f"{restore_w}x{restore_h}+{cx}+{cy}")
        root.minsize(900, 600)
        root.protocol("WM_DELETE_WINDOW", app.cancel)
        root.configure(bg=app.bg_color)
        apply_icon(root)


class LayoutInitializer:
    def build(self, app):
        app._initialize_drive_manager()
        app.setup_main_layout()
        app.setup_directory_section()
        app.setup_status_section()
        app.setup_console_section()
        app.setup_action_buttons()
        app._initialize_base_managers()
        app.setup_exclusion_section()


class IpcServer:
    def start(self, app):
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
                        app.root.after(0, lambda path=data: app._add_directory_from_ipc(path))
                except:
                    break

        threading.Thread(target=accept_connections, daemon=True).start()


class ScanRuntimeInitializer:
    def initialize(self, app):
        app.scan_cache = ThreadSafeDict()
        app.pending_scans = set()
        app._pending_scans_lock = threading.RLock()
        max_workers = min(8, (os.cpu_count() or 4))
        app.executor = ManagedExecutor(ThreadPoolExecutor, max_workers=max_workers)
        app.resource_manager = get_resource_manager()
        app.resource_manager.register_cleanup_callback(app._cleanup_scan_cache)
        app.resource_manager.register_cleanup_callback(app._cleanup_player_threads)
        app._qa_seed = _random.randint(0, 10 ** 9)


class StartupDirectoryLoader:
    def __init__(self, directory_display=None):
        self.directory_display = directory_display or DirectoryDisplayService()

    def load(self, app, preferences):
        command_line_dir = app._get_command_line_directory()
        if command_line_dir:
            app.selected_dirs = []
            if app.save_directories:
                app.selected_dirs = preferences.get('selected_dirs', [])
            if command_line_dir not in app.selected_dirs:
                app.selected_dirs.append(command_line_dir)
        elif app.save_directories:
            app.selected_dirs = preferences.get('selected_dirs', [])
        else:
            app.selected_dirs = []

        for directory in app.selected_dirs:
            self.directory_display.add_and_scan(app, directory)


class DragDropBinder:
    def bind(self, app):
        app.root.drop_target_register(DND_FILES)
        app.root.dnd_bind('<<Drop>>', app._on_drop_files)


class DirectorySelectorBootstrapper:
    def __init__(self, app, root, behaviors):
        self.app = app
        self.root = root
        self.behaviors = behaviors
        self.state = AppStateInitializer()
        self.preferences = PreferenceHydrator()
        self.window = MainWindowConfigurator()
        self.layout = LayoutInitializer()
        self.ipc = IpcServer()
        self.scan_runtime = ScanRuntimeInitializer()
        self.drag_drop = DragDropBinder()
        self.directory_display = DirectoryDisplayService()
        self.player_sessions = PlayerSessionService()
        self.startup_dirs = StartupDirectoryLoader(self.directory_display)

    def bootstrap(self):
        app = self.app
        app.theme = ThemeSelector(app)
        app._app_components = BehaviorComposer(app)
        app._app_components.install(*self.behaviors)
        app.root = self.root
        app.directory_display = self.directory_display
        app.player_sessions = self.player_sessions
        self.state.initialize(app)
        preferences = self.preferences.hydrate(app)
        app.setup_theme()
        self.window.configure(app)
        self.layout.build(app)
        self.ipc.start(app)
        self.scan_runtime.initialize(app)
        app.apply_theme()
        self.drag_drop.bind(app)
        self.startup_dirs.load(app, preferences)
        app._initialize_feature_managers()


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

    class DirectorySelector:
        _APP_BEHAVIORS = (
            BackendMixin,
            UIMixin,
            FrontendMixin,
            ManagersMixin,
        )

        def __init__(self, root):
            DirectorySelectorBootstrapper(self, root, self._APP_BEHAVIORS).bootstrap()


        def apply_theme(self):
            dir_w = self.dir_section.winfo_width() if hasattr(self, 'dir_section') else 0
            ThemeCoreMixin.apply_theme(self)
            self._reapply_tree_columns()
            if dir_w > 10:
                self.dir_section.config(width=dir_w)
                self.dir_section.pack_propagate(False)


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

            # Re-apply global search to new manager if query exists
            if hasattr(self, 'global_search_entry'):
                query = self.global_search_entry.get().strip().lower()
                if query and hasattr(self.active_embedded_manager, 'apply_search'):
                    self.active_embedded_manager.apply_search(query)


        def global_play(self):
            if self.active_embedded_manager is not None:
                # Attempt to call the manager's play_from_global method
                if hasattr(self.active_embedded_manager, 'play_from_global'):
                    self.active_embedded_manager.play_from_global()
                else:
                    self.play_videos()  # fallback
            else:
                self.play_videos()


        def clear_exclusion_children(self, root_iid):
            for child in list(self.exclusion_tree.get_children(root_iid)):
                try:
                    self.exclusion_tree.delete(child)
                except Exception:
                    pass


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


        def on_directory_focus_out(self, event):
            selection = self.dir_listbox.curselection()
            if selection:
                self.current_selected_dir_index = selection[0]

        def on_directory_focus_in(self, event):
            if self.current_selected_dir_index is not None and self.current_selected_dir_index < self.dir_listbox.size():
                self.dir_listbox.selection_clear(0, tk.END)
                self.dir_listbox.selection_set(self.current_selected_dir_index)
                self.dir_listbox.activate(self.current_selected_dir_index)


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

        def _make_player(self, videos, video_to_dir, directories, start_index=0):
            return self.player_sessions.make_player(
                self, videos, video_to_dir, directories, start_index=start_index)

        def _launch_player(self, player):
            self.player_sessions.launch_player(self, player)


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
                    if getattr(self, 'search_query', ''):
                        self.refresh_search_results(auto_expand=False)
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



        def toggle_save_directories(self):
            self.save_directories = bool(self.save_directories_var.get())
            self.save_preferences()

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
                    self.toast.success("Play Next", f"{count} video{'s' if count != 1 else ''} added to play next")
                else:
                    count = self.queue_manager.add_to_queue(final_videos, added_from="selection")
                    self.toast.success("Queue", f"{count} video{'s' if count != 1 else ''} added to queue")
                    self.update_console(f"Added {count} videos to queue")
            else:
                self.toast.warning("Warning", "No valid videos found in selection")

        def _show_history_embedded(self, frame, selected_dirs):
            ui = self.watch_history_manager.show_embedded(
                frame,
                close_callback=self._show_home_view
            )
            if hasattr(ui, "set_directory_filter"):
                ui.set_directory_filter(selected_dirs)
                ui.refresh()
            return ui

        def _add_to_playlist(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                self.toast.warning("Warning", "Please select a directory first")
                return
            selection = self._tree_selection_indices()
            if selection:
                selected_videos = self._resolve_iids_to_paths(selection)
                if selected_videos:
                    self.playlist_manager.add_videos_to_playlist([], selected_videos)
                    self.update_console(f"Added {len(selected_videos)} selected videos to playlist")
                else:
                    self.toast.warning("Warning", "No videos found in selected items")
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
                                self.toast.warning("Warning", "No videos found to add to playlist")

                        self.root.after(0, finish)
                    except Exception as e:
                        self.root.after(0, lambda: self.toast.error("Error", f"Failed to collect videos: {e}"))

                threading.Thread(target=collect_all_videos, daemon=True).start()

        def add_directory(self):
            directory = filedialog.askdirectory(title="Select a Directory")
            if directory and directory not in self.selected_dirs:
                self.selected_dirs.append(directory)
                self.directory_display.add_and_scan(self, directory)
                self.update_console(f"Added directory: {directory}")
                self.update_console(f"Scanning '{os.path.basename(directory)}' for videos…")
                self.toast.success("Directory Added", f"'{os.path.basename(directory)}' added — scanning…")
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
                self.toast.info("Information", "Please select a directory to remove.")
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

            self.toast.success("Removed",
                               f"Removed {len(selected_indices)} director{'ies' if len(selected_indices) > 1 else 'y'}")
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


        def _save_volume_callback(self, volume, is_muted=None):
            self.volume = volume
            if is_muted is not None:
                self.is_muted = is_muted
            self.save_preferences()

        def _is_stream_url(self, path):
            return isinstance(path, str) and (path.startswith("http://") or path.startswith("https://"))


        def _resolve_selection_indices_to_videos(self, selected_dir, indices):
            """Legacy shim — indices here are iids (strings)."""
            return self._resolve_iids_to_paths(indices)


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
                from managers.video_preview_manager import shutdown_thumb_pool
                shutdown_thumb_pool()
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
    root.withdraw()

    _ready = {"app": False, "splash": False}
    _app_instance = [None]
    _splash_start_time = None

    def _try_show():
        if _ready["app"] and _ready["splash"]:
            try:
                root.state('zoomed')
            except Exception:
                root.deiconify()

    def _on_splash_done():
        _ready["splash"] = True
        root.after(0, _try_show)

    def _wait_for_scans():
        app = _app_instance[0]
        try:
            n = len(app.pending_scans)
            total = len(app.selected_dirs)
            done = total - n
            if total > 0:
                progress = 25 + int(70 * (done / total))
                splash_ctrl.set_progress(progress, f"Scanning… {done}/{total}")
        except:
            pass
        try:
            with app._pending_scans_lock:
                pending = len(app.pending_scans)
        except Exception:
            pending = 0
        if pending > 0:
            root.after(150, _wait_for_scans)
        else:
            splash_ctrl.set_progress(100, "Ready!")
            elapsed = int((time.time() - _splash_start_time) * 1000)
            min_duration = 2500
            if elapsed < min_duration:
                root.after(min_duration - elapsed, lambda: splash_ctrl.close())
            else:
                splash_ctrl.close()
            _ready["app"] = True
            root.after(0, _try_show)


    def _build_app():
        splash_ctrl.set_progress(5, "Initializing UI…")
        _orig_state = root.state
        root.state = lambda s=None: _orig_state() if s is None else None
        splash_ctrl.set_progress(15, "Creating main window…")
        _app_instance[0] = DirectorySelector(root)
        root.state = _orig_state
        root.update_idletasks()
        root.withdraw()
        splash_ctrl.set_progress(25, "Scanning directories…")
        root.after(150, _wait_for_scans)

    splash_ctrl = show_splash(root, on_done=_on_splash_done)
    _splash_start_time = time.time()

    root.after(10, _build_app)
    root.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if not check_vlc():
        show_vlc_missing_and_exit()
    select_multiple_folders_and_play()
