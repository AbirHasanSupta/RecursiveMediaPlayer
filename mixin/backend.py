import os
import sys
import time
import tkinter as tk
from managers.resource_manager import MemoryMonitor, ManagedThread
from utils import gather_videos_with_directories, is_video


class BackendMixin:
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
                self.root.after(0, lambda: self.toast.error("Scan Failed",
                                                            f"Error scanning '{os.path.basename(dir_path)}'"))
            finally:
                with self._pending_scans_lock:
                    self.pending_scans.discard(dir_path)
                try:
                    self.root.after(0, self.update_video_count)
                except:
                    pass

        future.add_done_callback(on_done)

    def _cleanup_scan_cache(self):
        try:
            if hasattr(self, 'scan_cache'):
                self.scan_cache.clear()
            if hasattr(self, 'pending_scans'):
                self.pending_scans.clear()
        except Exception as e:
            print(f"Error cleaning scan cache: {e}")

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
            if hasattr(self, 'directory_display'):
                self.directory_display.add_and_scan(self, directory)
            else:
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
            self.toast.success("Dropped", f"{added} director{'ies' if added > 1 else 'y'} Dropped")

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

    def _collect_videos_from_pseudo_dir(self, root_pseudo_dir, pseudo_dir):
        cache = self.scan_cache.get(root_pseudo_dir)
        if not cache:
            return []
        videos, video_to_dir, directories = cache
        prefix = pseudo_dir.rstrip('/') + '/'
        return [v for v in videos
                if (p := video_to_dir.get(v)) and (p == pseudo_dir or p.startswith(prefix))]

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

    def _clear_thumbnail_cache(self):
        try:
            self.video_preview_manager.clear_cache()
            self.update_console("Thumbnail cache cleared.")
            return True
        except Exception as e:
            self.update_console(f"Error clearing thumbnail cache: {e}")
            return False

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

    def _remove_all_tags_from_path(self, path):
        for tag in list(self.annotation_service.get_tags(path)):
            self.annotation_service.remove_tag(path, tag)
        self._refresh_video_row(path)

    def _remove_all_bookmarks_from_path(self, path):
        for bm in list(self.annotation_service.get_bookmarks(path)):
            self.annotation_service.remove_bookmark(path, bm["ms"])
        self._refresh_video_row(path)

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

    def _load_drive_tree(self, directory, token, restore_scroll, scope_key="global"):
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
                if self._subdir_load_tokens.get(scope_key) is not token:
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

    def _setup_periodic_cleanup(self):
        self.memory_monitor = MemoryMonitor(threshold_mb=1200)

        def periodic_cleanup():
            if hasattr(self, 'root') and self.root.winfo_exists():
                self.memory_monitor.cleanup_if_needed()
                self.root.after(300000, periodic_cleanup)

        self.root.after(300000, periodic_cleanup)

    def __del__(self):
        try:
            if hasattr(self, 'resource_manager'):
                self.resource_manager.cleanup_all()
        except:
            pass

