import os
import random as _random
import socket
import struct
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from tkinter import filedialog, messagebox, ttk
from tkinter.font import Font
import tkinter as tk

from embedded_player import EmbeddedPlayer
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
from managers.resource_manager import ThreadSafeDict, get_resource_manager, ManagedExecutor, MemoryMonitor, ManagedThread
from managers.resume_playback_manager import ResumePlaybackManager
from managers.settings_manager import SettingsManager
from managers.toast_manager import Toast
from managers.video_metadata_manager import VideoAnnotationService
from managers.video_preview_manager import VideoPreviewManager
from managers.video_queue_manager import VideoQueueManager
from managers.watch_history_manager import WatchHistoryManager
from tkinterdnd2 import DND_FILES, TkinterDnD
from utils import gather_videos_with_directories, is_video, gather_videos, check_vlc, show_vlc_missing_and_exit


class FrontendMixin:
    def _handle_global_click(self, event):
        if not hasattr(self, 'global_search_entry'):
            return
        
        focused = self.root.focus_get()
        if not focused:
            return
        
        # Global Search Bar focus out
        if focused == self.global_search_entry:
            clicked_widget = event.widget
            is_search_component = (
                clicked_widget == self.global_search_entry or
                (hasattr(self, '_global_search_wrap') and clicked_widget == self._global_search_wrap) or
                (hasattr(self, 'global_search_icon') and clicked_widget == self.global_search_icon)
            )
            if not is_search_component:
                self.root.focus()
        
        # Directory Panel Search focus out
        elif hasattr(self, 'search_entry') and focused == self.search_entry:
            clicked_widget = event.widget
            is_dir_search_component = (
                clicked_widget == self.search_entry or
                (hasattr(self, '_search_wrap') and clicked_widget == self._search_wrap) or
                (hasattr(self, '_search_icon') and clicked_widget == self._search_icon)
            )
            if not is_dir_search_component:
                self.root.focus()
        
        # Active Manager Search focus out (Annotation Browser, Grid View, etc.)
        elif self.active_embedded_manager and hasattr(self.active_embedded_manager, 'search_entry'):
            if focused == self.active_embedded_manager.search_entry:
                clicked_widget = event.widget
                # Note: We don't necessarily know all components of manager search bars, 
                # but checking the entry itself is a good start.
                if clicked_widget != self.active_embedded_manager.search_entry:
                    self.root.focus()

    def _on_global_search_changed(self, event=None):
        if hasattr(self, '_global_search_debounce_id') and self._global_search_debounce_id:
            self.root.after_cancel(self._global_search_debounce_id)

        def _do_search():
            query = self.global_search_entry.get().strip().lower()
            if self.active_embedded_manager:
                if hasattr(self.active_embedded_manager, 'apply_search'):
                    self.active_embedded_manager.apply_search(query)
                elif hasattr(self.active_embedded_manager, 'apply_filter_sort'):
                    # Fallback for managers that use apply_filter_sort but don't have apply_search
                    self.active_embedded_manager.apply_filter_sort()
            self._global_search_debounce_id = None

        self._global_search_debounce_id = self.root.after(300, _do_search)

    def _on_tree_left_click_unified(self, event):
        iid = self.exclusion_tree.identify_row(event.y)
        region = self.exclusion_tree.identify_region(event.x, event.y)

        self._drag_root_iid = iid if (iid and iid in self._dir_root_iids and region == "tree") else None
        self._drag_start_y = event.y

        if region == "tree":
            return

        if not iid:
            self.clear_tree_selection()
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
                self._is_filtered_mode = False
                self._selection_anchor = None
                self._refresh_active_manager_for_directory_context()
                if getattr(self, 'search_query', ''):
                    self.refresh_search_results(auto_expand=False)
                else:
                    self.clear_exclusion_children(iid)
                return "break"
            self.exclusion_tree.selection_set(iid)
            self._selection_anchor = iid
            self._trigger_root_selection(iid)
            return "break"

        # Non-root item
        self.exclusion_tree.selection_set(iid)
        self._selection_anchor = iid
        return "break"

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

        context_menu = self.create_manager_context_menu(self.root)
        context_menu.add_command(label="Play Selected", command=self.play_selected_videos)
        context_menu.add_separator()

        total_items    = self._tree_size()
        selected_count = len(selection)

        if selected_count < total_items:
            context_menu.add_command(label="Select All",
                command=lambda: self.exclusion_tree.selection_set(self._tree_get_all_iids()))
        if selected_count > 0:
            context_menu.add_command(label="Clear Selection",
                command=self.clear_tree_selection)

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
        context_menu = self.create_manager_context_menu(self.root)
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
            self.toast.info("Information", "No videos found in selected directories.")
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
                self.toast.info("Information", "No videos found in selected directories.")
                return
            self._open_grid_view(all_videos)

        self._wait_for_scans_then(selected_dirs, _open)

    def _context_play_in_dual_player(self, selection, win_id, slot):
        selected_dir = self.get_current_selected_directory()
        if not selected_dir:
            return
        final_videos = self._resolve_iids_to_paths(selection)
        if not final_videos:
            self.toast.warning("No Videos", "No valid non-excluded videos found in selection.")
            return
        self.dual_player_manager.load_videos_into_slot(win_id, slot, final_videos)
        self.update_console(f"Sent {len(final_videos)} video(s) to Window {win_id} · Player {slot}")

    def _context_add_to_favorites(self, selection):
        selected_dir = self.get_current_selected_directory()
        if not selected_dir:
            return

        # Save current tree selection
        current_selection = list(self.exclusion_tree.selection())

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
            if count > 0:
                self.toast.success("Favorites", f"{count} video{'s' if count != 1 else ''} added to favorites")
            self.update_console(f"Added {count} video(s) to favorites")

            # Update each affected row
            for video in selected_videos:
                self._refresh_video_row(video, selected_dir)

            # Restore selection
            if current_selection:
                valid = [iid for iid in current_selection if self.exclusion_tree.exists(iid)]
                if valid:
                    self.exclusion_tree.selection_set(valid)
                    self.exclusion_tree.focus(valid[0])
                    self._selection_anchor = valid[0]
                    # Re-establish directory index from first selected item's root
                    root_iid = self._get_root_iid_from_iid(valid[0])
                    if root_iid and root_iid in self._dir_root_iids:
                        self.current_selected_dir_index = self._dir_root_iids.index(root_iid)

    def _context_remove_from_favorites(self, selection):
        selected_dir = self.get_current_selected_directory()
        if not selected_dir:
            return

        current_selection = list(self.exclusion_tree.selection())

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
            if count > 0:
                self.toast.success("Favorites",
                                   f"{count} video{'s' if count != 1 else ''} removed from favorites")

            # Update each affected row (tree still intact, iids valid)
            for video in selected_videos:
                self._refresh_video_row(video, selected_dir)

            # Restore selection
            if current_selection:
                valid = [iid for iid in current_selection if self.exclusion_tree.exists(iid)]
                if valid:
                    self.exclusion_tree.selection_set(valid)
                    self.exclusion_tree.focus(valid[0])
                    self._selection_anchor = valid[0]
                    root_iid = self._get_root_iid_from_iid(valid[0])
                    if root_iid and root_iid in self._dir_root_iids:
                        self.current_selected_dir_index = self._dir_root_iids.index(root_iid)

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
            added = self.playlist_manager.add_videos_to_playlist([], selected_videos)
            if added:
                self.toast.success("Playlist",
                               f"{len(selected_videos)} video{'s' if len(selected_videos) != 1 else ''} added to playlist")

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
                self.toast.success("Copied",
                                   f"{len(paths_to_copy)} item{'s' if len(paths_to_copy) != 1 else ''} copied to clipboard")
            except Exception as e:
                self.update_console(f"Error copying to clipboard: {e}")
                self.toast.error("Copy Failed", f"Could not copy to clipboard: {e}")

    def _context_copy_path(self, file_path):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(file_path)
            self.update_console(f"Copied path: {file_path}")
            self.toast.success("Copied", "Path copied to clipboard")
        except Exception as e:
            self.update_console(f"Error copying path: {e}")
            self.toast.error("Copy Failed", f"Could not copy path: {e}")

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
            self.toast.error("Error", f"Could not open file location: {e}")

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
            self.toast.error("Error", f"Could not retrieve properties: {e}")

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
            self.toast.error("Error", f"Could not get folder properties: {e}")

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
            self.toast.error("Error", f"Could not open folder location: {e}")

    def _grid_exclude_video(self, video_path):
        root_dir = self._find_root_dir_for_video(video_path)
        if not root_dir:
            return
        norm_vp = os.path.normpath(video_path)
        if root_dir not in self.excluded_videos:
            self.excluded_videos[root_dir] = []
        if norm_vp not in (os.path.normpath(v) for v in self.excluded_videos[root_dir]):
            self.excluded_videos[root_dir].append(norm_vp)
        self.update_console(f"Excluded: {os.path.basename(video_path)}")
        self.update_video_count()
        scroll_pos = self._tree_yview()
        if getattr(self, '_is_filtered_mode', False) and hasattr(self, '_filtered_videos'):
            self._reapply_filtered_view(scroll_pos)
        else:
            self.load_subdirectories(root_dir, restore_scroll=scroll_pos)
        if self.save_directories:
            self.save_preferences()

    def _grid_remove_exclusion_video(self, video_path):
        root_dir = self._find_root_dir_for_video(video_path)
        if not root_dir:
            return
        norm_vp = os.path.normpath(video_path)
        if root_dir in self.excluded_videos:
            self.excluded_videos[root_dir] = [
                v for v in self.excluded_videos[root_dir]
                if os.path.normpath(v) != norm_vp
            ]
            if not self.excluded_videos[root_dir]:
                del self.excluded_videos[root_dir]
        self.update_console(f"Removed exclusion: {os.path.basename(video_path)}")
        self.update_video_count()
        scroll_pos = self._tree_yview()
        if getattr(self, '_is_filtered_mode', False) and hasattr(self, '_filtered_videos'):
            self._reapply_filtered_view(scroll_pos)
        else:
            self.load_subdirectories(root_dir, restore_scroll=scroll_pos)
        if self.save_directories:
            self.save_preferences()

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

    def _on_drag_start(self, event):
        iid = self.exclusion_tree.identify_row(event.y)
        region = self.exclusion_tree.identify_region(event.x, event.y)
        if iid and iid in self._dir_root_iids and region != "tree":
            self._drag_root_iid = iid
        else:
            self._drag_root_iid = None

    def clear_tree_selection(self):
        if hasattr(self, 'exclusion_tree'):
            self.exclusion_tree.selection_remove(self.exclusion_tree.selection())
        self._selection_anchor = None
        self.current_selected_dir_index = None
        self._refresh_active_manager_for_directory_context()
        self.clear_exclusion_list()

    def clear_exclusion_list(self):
        # self.selected_dir_label.config(text="Select a directory to see its folders and videos")
        if getattr(self, 'search_query', ''):
            self.refresh_search_results(auto_expand=False)
        else:
            self._clear_tree()

    def refresh_search_results(self, auto_expand=True):
        selected_dir = self.get_current_selected_directory()
        search_query = getattr(self, 'search_query', '')
        if selected_dir:
            self.load_subdirectories(selected_dir, auto_expand=auto_expand)
        else:
            if search_query:
                for idx, directory in enumerate(self.selected_dirs):
                    if idx < len(self._dir_root_iids):
                        root_iid = self._dir_root_iids[idx]
                        self.load_subdirectories(directory, _root_iid=root_iid, auto_expand=auto_expand)
            else:
                self._clear_tree()
                for riid in getattr(self, '_dir_root_iids', []):
                    try:
                        self.exclusion_tree.item(riid, open=False)
                    except Exception:
                        pass

    def on_search_changed(self, event=None):
        try:
            new_query = self.search_entry.get().strip().lower()
        except Exception:
            new_query = ""
        if new_query == self.search_query:
            return
        if hasattr(self, '_dir_search_debounce_id') and self._dir_search_debounce_id:
            self.root.after_cancel(self._dir_search_debounce_id)

        def _do_search():
            self.search_query = new_query
            self.refresh_search_results()
            self._dir_search_debounce_id = None

        self._dir_search_debounce_id = self.root.after(300, _do_search)

    def clear_search(self):
        if hasattr(self, 'search_entry'):
            self.search_entry.delete(0, tk.END)
            self.on_search_changed()

    def get_current_selected_directory(self):
        selection = self.dir_listbox.curselection()
        if selection:
            idx = selection[0]
            if idx < len(self.selected_dirs):
                self.current_selected_dir_index = idx
                return self.selected_dirs[idx]
        tree_sel = list(self.exclusion_tree.selection())
        if tree_sel:
            iid = tree_sel[0]
            root_iid = self._get_root_iid_from_iid(iid)
            if root_iid and root_iid in self._dir_root_iids:
                idx = self._dir_root_iids.index(root_iid)
                self.current_selected_dir_index = idx
                return self.selected_dirs[idx]
        if self.current_selected_dir_index is not None and self.current_selected_dir_index < len(
                self.selected_dirs):
            return self.selected_dirs[self.current_selected_dir_index]
        return None

    def _get_root_iid_from_iid(self, iid):
        """Return the root iid (top-level directory node) for a given iid."""
        if iid in self._dir_root_iids:
            return iid
        parent = self.exclusion_tree.parent(iid)
        while parent:
            if parent in self._dir_root_iids:
                return parent
            parent = self.exclusion_tree.parent(parent)
        return None

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

    def _toggle_directory_panel(self):
        if self._directory_panel_mode == "compact":
            self.expand_directory_panel()
        else:
            self.shrink_directory_panel()

    def shrink_directory_panel(self):
        self._set_directory_panel_mode("compact")

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
            self.toast.info("Information", "Please select a directory first.")
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
            self.toast.info("Information", "Please select a directory first.")
            return
        self.show_only_excluded = bool(self.excluded_only_var.get())
        self.load_subdirectories(selected_dir, max_depth=self.current_max_depth)

    def exclude_subdirectories(self):
        selected_dir = self.get_current_selected_directory()
        if not selected_dir:
            self.toast.info("Information", "Please select a directory first.")
            return

        selection = self._tree_selection_indices()
        if not selection:
            self.toast.info("Information", "Please select items to exclude.")
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
                self.root.after(0, lambda: self.toast.error("Error", f"Error excluding: {e}"))
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
            self.toast.info("Information", "Please select a directory first.")
            return

        selection = self._tree_selection_indices()
        if not selection:
            self.toast.info("Information", "Please select items to include.")
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
                self.root.after(0, lambda: self.toast.error("Error", f"Error including: {e}"))
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

    def exclude_all_subdirectories(self):
        selected_dir = self.get_current_selected_directory()
        if not selected_dir:
            self.toast.info("Information", "Please select a directory first.")
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

    def clear_all_exclusions(self):
        selected_dir = self.get_current_selected_directory()
        if not selected_dir:
            self.toast.info("Information", "Please select a directory first.")
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
                self.toast.success("Exclusions Cleared",
                                   f"Cleared {count} exclusion{'s' if count != 1 else ''} for '{os.path.basename(selected_dir)}'")
                self.update_console(f"Cleared all {count} exclusions for '{os.path.basename(selected_dir)}'")
                if self.save_directories:
                    self.save_preferences()

                scroll_pos = self._tree_yview()
                if is_filtered_mode and hasattr(self, '_filtered_videos'):
                    self._reapply_filtered_view(scroll_pos)
                else:
                    self.load_subdirectories(selected_dir)
                self.update_video_count()

    def load_subdirectories(self, directory, max_depth=20, restore_path=None, restore_scroll=None, _root_iid=None, auto_expand=True):
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
            self.exclusion_tree.item(_root_iid, open=auto_expand)
        else:
            self._clear_tree()
            self.exclusion_tree.insert("", tk.END, iid="__loading__",
                                       text="  Loading…ª", tags=("placeholder",))

        if not hasattr(self, '_subdir_load_tokens'):
            self._subdir_load_tokens = {}
            self._subdir_load_lock  = threading.RLock()

        with self._subdir_load_lock:
            token = object()
            if _root_iid is None:
                self._subdir_load_tokens.clear()
                self._subdir_load_tokens["global"] = token
                scope_key = "global"
            else:
                self._subdir_load_tokens[_root_iid] = token
                scope_key = _root_iid

        # Handle Google Drive pseudo-paths
        try:
            if isinstance(directory, str) and directory.startswith("gdrive://"):
                self._load_drive_tree(directory, token, restore_scroll, scope_key=scope_key)
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
                    if self._subdir_load_tokens.get(scope_key) is not token:
                        return

                path_to_iid = {}
                items       = []
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
                    elif search_query:
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
                        if self._subdir_load_tokens.get(scope_key) is not token:
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
                        if self._subdir_load_tokens.get(scope_key) is not token:
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
                                if search_query:
                                    dir_name_match = search_query in os.path.basename(path).lower()
                                    has_match_children = self.matches_search(path, search_query)
                                    open_state = (has_match_children and not dir_name_match) if auto_expand else False
                                elif expand_all:
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
                        if self._subdir_load_tokens.get(scope_key) is not token:
                            return
                    self._clear_tree()
                    self.exclusion_tree.insert("", tk.END, iid="__error__",
                                               text=f"  Error: {msg}", tags=("placeholder",))
                    self.current_subdirs_mapping = {}
                self.root.after(0, post_error)

        ManagedThread(target=build_and_post, name="LoadSubdirs").start()

    def _lazy_expand_node(self, iid, directory):
        selected_dir = self.get_current_selected_directory() or self._get_root_directory_of_node(iid)
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

    def _refresh_video_row(self, path, selected_dir=None):
        """Update the tree row for a specific video path without reloading."""
        if selected_dir is None:
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                return
        excluded_dir_set = set(os.path.normpath(p) for p in self.excluded_subdirs.get(selected_dir, []))
        excluded_vid_set = set(os.path.normpath(p) for p in self.excluded_videos.get(selected_dir, []))
        norm_path = os.path.normpath(path)
        for iid, p in self.current_subdirs_mapping.items():
            if os.path.normpath(p) == norm_path:
                try:
                    size_str = self._get_video_size_str(path)
                    rating_str = self._get_rating_stars(path)
                    tags_str = self._get_tags_str(path)
                    self.exclusion_tree.item(iid, values=(rating_str, tags_str, size_str))
                    tag = self._tag_for_item(path, selected_dir, excluded_dir_set, excluded_vid_set)
                    label = self._label_for_item(path, False, excluded_dir_set, excluded_vid_set, selected_dir)
                    self.exclusion_tree.item(iid, text=label, tags=(tag,))
                except tk.TclError:
                    pass
                break

    def _get_root_directory_of_node(self, iid):
        current = iid
        while current:
            if hasattr(self, '_dir_root_iids') and current in self._dir_root_iids:
                idx = self._dir_root_iids.index(current)
                if idx < len(self.selected_dirs):
                    return self.selected_dirs[idx]
            parent = self.exclusion_tree.parent(current)
            if not parent or parent == current:
                break
            current = parent
        return None

