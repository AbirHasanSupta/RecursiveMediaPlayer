import os
import threading
from tkinter import ttk
import tkinter as tk

from icon_helper import apply_icon
from key_press import reload_hotkeys
from managers.annotation_browser_manager import AnnotationBrowserManager
from managers.dual_player_manager import DualPlayerManager
from managers.favorites_manager import FavoritesManager
from managers.filter_sort_manager import AdvancedFilterSortManager
from managers.filter_sort_ui import FilterSortUI
from managers.google_drive_manager import GoogleDriveManager
from managers.grid_view_manager import GridViewManager
from managers.playlist_manager import PlaylistManager
from managers.resource_manager import ManagedThread
from managers.resume_playback_manager import ResumePlaybackManager
from managers.settings_manager import SettingsManager
from managers.toast_manager import Toast
from managers.video_metadata_manager import VideoAnnotationService
from managers.video_preview_manager import VideoPreviewManager
from managers.video_queue_manager import VideoQueueManager
from managers.watch_history_manager import WatchHistoryManager
from utils import is_video


class FeatureManagerWiring:
    """Coordinates cross-manager callbacks for the composed application."""

    def __init__(self, app):
        self.app = app

    def wire_playlist(self):
        app = self.app
        app.playlist_manager.set_play_callback(app._play_playlist_videos)
        app.playlist_manager.set_log_callback(app.update_console)
        app.playlist_manager.set_video_preview_manager(app.video_preview_manager)
        app.playlist_manager.set_grid_view_manager(app.grid_view_manager)
        app.playlist_manager.set_add_to_favorites_callback(
            lambda videos: app._add_videos_to_favorites_smart(videos)
        )
        app.playlist_manager.set_add_to_queue_callback(
            lambda videos: app.queue_manager.add_to_queue(videos, added_from="playlist")
        )
        app.playlist_manager.ui.video_preview_manager = app.video_preview_manager

    def wire_watch_history(self):
        app = self.app
        app.watch_history_manager.set_settings_manager(app.settings_manager)
        app.watch_history_manager.set_play_callback(app._play_history_videos)
        app.watch_history_manager.set_video_preview_manager(app.video_preview_manager)
        app.watch_history_manager.set_grid_view_manager(app.grid_view_manager)
        app.watch_history_manager.set_add_to_playlist_callback(
            lambda videos: app.playlist_manager.add_videos_to_playlist([], videos)
        )
        app.watch_history_manager.set_add_to_queue_callback(
            lambda videos: app.queue_manager.add_to_queue(videos, added_from="watch_history")
        )
        app.watch_history_manager.set_add_to_favourites_callback(
            lambda videos: app._add_videos_to_favorites_smart(videos)
        )
        app.watch_history_manager.set_remove_from_favourites_callback(
            lambda videos: app._remove_videos_from_favorites_smart(videos)
        )
        app.watch_history_manager.set_is_favourite_callback(
            lambda video_path: app._is_favourite_smart(video_path)
        )

    def wire_queue(self):
        app = self.app
        app.queue_manager.set_play_callback(app._play_queue_videos)
        app.queue_manager.set_video_preview_manager(app.video_preview_manager)
        app.queue_manager.set_grid_view_manager(app.grid_view_manager)
        app.queue_manager.set_add_to_favorites_callback(
            lambda videos: app._add_videos_to_favorites_smart(videos)
        )
        app.queue_manager.set_add_to_playlist_callback(
            lambda videos: app.playlist_manager.add_videos_to_playlist([], videos)
        )

    def wire_favorites(self):
        app = self.app
        app.favorites_manager.set_play_callback(app._play_favorites_videos)
        app.favorites_manager.set_video_preview_manager(app.video_preview_manager)
        app.favorites_manager.set_grid_view_manager(app.grid_view_manager)
        app.favorites_manager.set_on_added_callback(app._on_favorites_added)
        app.favorites_manager.set_on_removed_callback(app._on_favorites_removed)
        app.favorites_manager.set_add_to_queue_callback(
            lambda videos: app.queue_manager.add_to_queue(videos, added_from="favorites")
        )
        app.favorites_manager.set_add_to_playlist_callback(
            lambda videos: app.playlist_manager.add_videos_to_playlist([], videos)
        )

    def wire_annotation_browser(self):
        app = self.app
        app.annotation_browser.set_video_preview_manager(app.video_preview_manager)
        app.annotation_browser.set_grid_view_manager(app.grid_view_manager)
        app.annotation_browser.set_add_to_playlist_callback(
            lambda videos: app.playlist_manager.add_videos_to_playlist([], videos)
        )
        app.annotation_browser.set_add_to_queue_callback(
            lambda videos: app.queue_manager.add_to_queue(videos, added_from="annotation_browser")
        )
        app.annotation_browser.set_add_to_favourites_callback(
            lambda videos: app._add_videos_to_favorites_smart(videos)
        )
        app.annotation_browser.set_remove_from_favourites_callback(
            lambda videos: app._remove_videos_from_favorites_smart(videos)
        )
        app.annotation_browser.set_is_favourite_callback(
            lambda video_path: app._is_favourite_smart(video_path)
        )

    def wire_grid_view(self):
        app = self.app
        app.grid_view_manager.set_add_to_playlist_callback(
            lambda videos: app.playlist_manager.add_videos_to_playlist([], videos)
        )
        app.grid_view_manager.set_add_to_favourites_callback(
            lambda videos: app._add_videos_to_favorites_smart(videos)
        )
        app.grid_view_manager.set_remove_from_favourites_callback(
            lambda videos: app._remove_videos_from_favorites_smart(videos)
        )
        app.grid_view_manager.set_is_favourite_callback(
            lambda video_path: app._is_favourite_smart(video_path)
        )
        app.grid_view_manager.set_add_to_queue_callback(
            lambda videos: app.queue_manager.add_to_queue(videos, added_from="grid_view")
        )
        app.grid_view_manager.set_play_in_dual_player1_callback(
            lambda videos: app.dual_player_manager.load_videos_into_slot(1, 1, videos)
        )
        app.grid_view_manager.set_play_in_dual_player2_callback(
            lambda videos: app.dual_player_manager.load_videos_into_slot(1, 2, videos)
        )
        app.grid_view_manager.set_play_in_dual_player3_callback(
            lambda videos: app.dual_player_manager.load_videos_into_slot(1, 3, videos)
        )
        app.grid_view_manager.set_get_player_count_callback(lambda: 3)

        if app.settings_manager.get_settings().dual_window_enabled:
            app.grid_view_manager.set_play_in_dual_player_win2_1_callback(
                lambda videos: app.dual_player_manager.load_videos_into_slot(2, 1, videos)
            )
            app.grid_view_manager.set_play_in_dual_player_win2_2_callback(
                lambda videos: app.dual_player_manager.load_videos_into_slot(2, 2, videos)
            )
            app.grid_view_manager.set_play_in_dual_player_win2_3_callback(
                lambda videos: app.dual_player_manager.load_videos_into_slot(2, 3, videos)
            )

        app.grid_view_manager.set_open_file_location_callback(app._context_open_location)
        app.grid_view_manager.set_show_properties_callback(app._context_show_properties)
        app.grid_view_manager.set_annotation_service(app.annotation_service)
        app.grid_view_manager.set_exclude_video_callback(app._grid_exclude_video)
        app.grid_view_manager.set_remove_exclusion_video_callback(app._grid_remove_exclusion_video)
        app.grid_view_manager.set_locate_in_panel_callback(app.locate_in_directory_panel)
        app.playlist_manager.set_locate_in_panel_callback(app.locate_in_directory_panel)
        app.watch_history_manager.set_locate_in_panel_callback(app.locate_in_directory_panel)
        app.favorites_manager.set_locate_in_panel_callback(app.locate_in_directory_panel)
        app.queue_manager.set_locate_in_panel_callback(app.locate_in_directory_panel)
        app.annotation_browser.set_locate_in_panel_callback(app.locate_in_directory_panel)

    def wire_settings_panel(self):
        app = self.app
        app.settings_manager.ui.cleanup_resume_callback = lambda: app.resume_manager.service.cleanup_old_positions(
            app.settings_manager.get_settings().auto_cleanup_days)
        app.settings_manager.ui.cleanup_history_callback = lambda: app.watch_history_manager.service.cleanup_old_entries(
            app.settings_manager.get_settings().auto_cleanup_days)
        app.settings_manager.ui.clear_thumbnails_callback = lambda: app._clear_thumbnail_cache()
        app.settings_manager.ui.video_preview_manager = app.video_preview_manager
        app.settings_manager.ui.clear_metadata_callback = lambda: app._clear_metadata_cache()
        app.settings_manager.ui.get_metadata_info_callback = lambda: app._get_metadata_cache_info()
        app.settings_manager.ui.filter_sort_manager = app.filter_sort_manager

    def finish_startup(self):
        app = self.app
        app.root.after(0, app._fix_pill_colors_initial)
        app.root.after(100, app._show_home_view)
        app._setup_periodic_cleanup()
        app.resource_manager.register_cleanup_callback(app._cleanup_managers)


class PlaybackScopeBuilder:
    """Builds player input collections from candidate video paths."""

    def __init__(self, stream_detector):
        self.stream_detector = stream_detector

    def build(self, video_paths, *, include_streams=True):
        video_to_dir = {}
        directories = []

        for video_path in video_paths:
            if include_streams and self.stream_detector(video_path):
                video_dir = "STREAMS"
            else:
                video_dir = os.path.dirname(video_path) if os.path.isfile(video_path) else None

            if not video_dir:
                continue

            video_to_dir[video_path] = video_dir
            if video_dir not in directories:
                directories.append(video_dir)

        directories.sort()
        return list(video_to_dir.keys()), video_to_dir, directories


class ManagersMixin:
    def _initialize_drive_manager(self):
        try:
            self.drive_manager = GoogleDriveManager()
        except Exception as e:
            self.drive_manager = None
            self.update_console(f"Google Drive integration unavailable: {e}")


    def _initialize_base_managers(self):
        self.settings_manager = SettingsManager(self.root, self, self.update_console, enable_ai=False)
        self.toast = Toast(self.root, self)

    def _initialize_feature_managers(self):
        self.settings_manager.add_settings_changed_callback(self._on_settings_changed)
        self.settings_manager.set_hotkey_reload_callback(
            lambda hk: reload_hotkeys(self.controller, hk)
        )
        self.root.bind("<Button-1>", self._handle_global_click)
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

        self.watch_history_manager = WatchHistoryManager(self.root, self)

        self.resume_manager = ResumePlaybackManager()
        self.resume_manager.set_resume_enabled(self.smart_resume_enabled)

        self.queue_manager = VideoQueueManager(self.root, self)

        self.favorites_manager = FavoritesManager(self.root, self)

        self.annotation_service = VideoAnnotationService()
        self.annotation_service.subscribe(self._on_any_annotation_changed)

        self.annotation_browser = AnnotationBrowserManager(
            root=self.root,
            theme_provider=self,
            annotation_service=self.annotation_service,
            play_callback=self._play_annotated_videos,
            logger=self.update_console,
        )

        self.dual_player_manager = DualPlayerManager(
            self.root,
            self,
            self.update_console,
            watch_history_callback=self.watch_history_manager.track_video_playback,
            player_count=3
        )
        if hasattr(self, 'video_preview_manager'):
            self.dual_player_manager.set_seek_preview_manager(self.video_preview_manager)

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
        self.playback_scope_builder = PlaybackScopeBuilder(self._is_stream_url)

        wiring = FeatureManagerWiring(self)
        wiring.wire_playlist()
        wiring.wire_watch_history()
        wiring.wire_queue()
        wiring.wire_favorites()
        wiring.wire_annotation_browser()
        wiring.wire_grid_view()
        wiring.wire_settings_panel()
        wiring.finish_startup()


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

    def _on_favorites_added(self, added_videos):
        """Called when videos are added to favorites."""
        if not added_videos:
            return
        selected_dir = self.get_current_selected_directory()
        if selected_dir:
            for video in added_videos:
                if os.path.normpath(video).startswith(os.path.normpath(selected_dir) + os.sep):
                    self._refresh_video_row(video, selected_dir)
        if hasattr(self, 'grid_view_manager') and self.grid_view_manager:
            self.grid_view_manager.refresh_favorite_state_for_videos(added_videos)

    def _on_favorites_removed(self, removed_videos):
        """Called when videos are removed from favorites."""
        if not removed_videos:
            return
        selected_dir = self.get_current_selected_directory()
        if selected_dir:
            for video in removed_videos:
                if os.path.normpath(video).startswith(os.path.normpath(selected_dir) + os.sep):
                    self._refresh_video_row(video, selected_dir)
        if hasattr(self, 'grid_view_manager') and self.grid_view_manager:
            self.grid_view_manager.refresh_favorite_state_for_videos(removed_videos)

    def _play_favorites_videos(self, videos):
        if not videos:
            return
        all_video_to_dir = {v: os.path.dirname(v) for v in videos}
        all_directories  = sorted(list(set(all_video_to_dir.values())))
        self.update_console(f"Playing {len(videos)} videos from favorites")
        self._launch_player(self._make_player(videos, all_video_to_dir, all_directories, 0))

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
        valid_videos, all_video_to_dir, all_directories = self.playback_scope_builder.build(videos)
        if not valid_videos:
            self.toast.warning("Warning", "No valid videos found")
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

    def _play_history_videos(self, videos):
        if not videos:
            self.toast.warning("Warning", "No videos to play")
            return
        self.update_console("=" * 60)
        self.update_console("STARTING HISTORY VIDEO PLAYBACK")
        self.update_console("=" * 60)
        valid_videos, all_video_to_dir, all_directories = self.playback_scope_builder.build(videos)
        if not valid_videos:
            self.toast.warning("Warning", "No valid videos found")
            return
        self.update_console(f"Playing {len(valid_videos)} videos from history")
        self._launch_player(self._make_player(valid_videos, all_video_to_dir, all_directories, 0))

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

    def _manage_playlists(self):
        self._show_embedded_view(
            "playlist",
            lambda frame: self.playlist_manager.show_embedded(
                frame,
                close_callback=self._show_home_view
            )
        )

    def _play_playlist_videos(self, videos):
        if not videos:
            self.toast.warning("Warning", "Playlist is empty")
            return
        self.update_console("=" * 60)
        self.update_console("STARTING PLAYLIST PLAYBACK")
        self.update_console("=" * 60)
        valid_videos, all_video_to_dir, all_directories = self.playback_scope_builder.build(videos)
        if not valid_videos:
            self.toast.warning("Warning", "No valid videos found in playlist")
            return
        self.update_console(f"Playing playlist with {len(valid_videos)} videos")
        self._launch_player(self._make_player(valid_videos, all_video_to_dir, all_directories, 0))

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
                    self.root.after(0, lambda: self.toast.warning("Warning", "No videos found in selection"))

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
                    self.root.after(0, lambda: self.toast.warning("Warning", "No videos found"))

            self._wait_for_scans_then(selected_dirs,
                                      lambda: threading.Thread(target=collect_all, daemon=True).start())

    def _open_grid_view(self, videos):
        if not videos:
            self.toast.warning("Warning", "No videos to display")
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
        valid_videos, all_video_to_dir, all_directories = self.playback_scope_builder.build(
            video_paths,
            include_streams=False,
        )
        if not valid_videos:
            return
        self._launch_player(self._make_player(valid_videos, all_video_to_dir, all_directories, 0))

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

    def _show_filter_dialog(self):
        active = getattr(self, '_active_app_view', 'home')
        mgr = getattr(self, 'active_embedded_manager', None)
        if active == 'gallery':
            def _apply_gallery_filters():
                if hasattr(self, 'grid_view_manager'):
                    self.grid_view_manager.apply_filter_sort(self.filter_sort_manager)
            self.filter_sort_ui.on_apply_callback = _apply_gallery_filters
        elif active in ('favourites', 'queue', 'playlist', 'tags') and mgr and hasattr(mgr, 'apply_filter_sort'):
            def _apply_manager_filters(m=mgr):
                m.apply_filter_sort(self.filter_sort_manager)
            self.filter_sort_ui.on_apply_callback = _apply_manager_filters
        else:
            self.toast.info("Filter / Sort", "Switch to Gallery, Favourites, Queue, Playlist, or Tags to apply filters.")
            return
        self.filter_sort_ui.show_filter_dialog()

    def _apply_filters_and_refresh(self):
        selected_dir = self.get_current_selected_directory()
        if not selected_dir:
            self.toast.warning("Warning", "Please select a directory first")
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
                        self.toast.warning("Warning", "Directory not scanned yet")
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
                    self.toast.error("Error", f"Filter error: {e}")
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

    def _on_any_annotation_changed(self):
        if hasattr(self, 'current_subdirs_mapping'):
            for iid, path in list(self.current_subdirs_mapping.items()):
                if os.path.isfile(path):
                    self._refresh_video_row(path)

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

    def _show_settings(self):
        self.settings_manager.show_settings()

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
            self.toast.error("Google Drive", "Google Drive integration is unavailable.")
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
            self.toast.error("Google Drive", str(e))
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
                    self.toast.error("Google Drive", f"Failed to add link: {e}")
                    self.update_console(f"Google Drive error: {e}")
                self.root.after(0, on_err)

        ManagedThread(target=worker, name="AddDriveLink").start()

