from qt_app import run_qt_app
import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from tkinter.font import Font
import os
import multiprocessing
from concurrent.futures import ProcessPoolExecutor

from key_press import listen_keys, cleanup_hotkeys
from utils import gather_videos_with_directories, is_video
from vlc_player_controller import VLCPlayerControllerForMultipleDirectory
from config_util import load_config, save_config


def select_multiple_folders_and_play():
    class DirectorySelector:
        def __init__(self, root):
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
            self.current_max_depth = 20
            self.setup_theme()
            config = load_config()
            self.last_dir = config.get("last_dir", os.path.expanduser("~"))

            root.title("Recursive Video Player")
            root.geometry("1200x800")
            root.protocol("WM_DELETE_WINDOW", self.cancel)
            root.configure(bg=self.bg_color)

            self.setup_main_layout()
            self.setup_directory_section()
            self.setup_exclusion_section()
            self.setup_status_section()
            self.setup_console_section()
            # self.setup_controls_info()
            self.setup_action_buttons()

            self.scan_cache = {}
            self.pending_scans = set()
            max_workers = min(8, (os.cpu_count() or 4))
            self.executor = ProcessPoolExecutor(max_workers=max_workers)
            self.update_console(f"Scanner ready (process workers: {max_workers})")

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
            v = self.button_variants.get(variant, self.button_variants["primary"])
            bg = v["bg"]
            fg = v["fg"]
            active_bg = v["active"]

            if font is None:
                if size == "sm":
                    use_font = self.small_font
                    padx, pady = 8, 3
                elif size == "lg":
                    use_font = Font(family=self.normal_font.actual().get("family", "Segoe UI"), size=self.normal_font.actual().get("size", 10) + 2, weight="bold")
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

            buttons_row1 = tk.Frame(exclusion_buttons_frame, bg=self.bg_color)
            buttons_row1.pack(fill=tk.X, pady=(0, 5))

            self.exclude_button = self.create_button(
                buttons_row1,
                text="Exclude Selected",
                command=self.exclude_subdirectories,
                variant="danger",
                size="md"
            )
            self.exclude_button.pack(side=tk.LEFT, padx=(0, 5))

            self.include_button = self.create_button(
                buttons_row1,
                text="Include Selected",
                command=self.include_subdirectories,
                variant="success",
                size="md"
            )
            self.include_button.pack(side=tk.LEFT, padx=(0, 5))

            self.exclude_all_button = self.create_button(
                buttons_row1,
                text="Exclude All",
                command=self.exclude_all_subdirectories,
                variant="warning",
                size="md"
            )
            self.exclude_all_button.pack(side=tk.LEFT)

            buttons_row2 = tk.Frame(exclusion_buttons_frame, bg=self.bg_color)
            buttons_row2.pack(fill=tk.X)

            self.show_videos_var = tk.BooleanVar(value=self.show_videos)
            self.excluded_only_var = tk.BooleanVar(value=self.show_only_excluded)
            self.expand_all_var = tk.BooleanVar(value=True)

            self.toggle_videos_check = ttk.Checkbutton(
                buttons_row2,
                text="Show Videos",
                style="Modern.TCheckbutton",
                variable=self.show_videos_var,
                command=self.toggle_videos_visibility
            )
            self.toggle_videos_check.pack(side=tk.LEFT, padx=(0, 5))

            self.expand_all_check = ttk.Checkbutton(
                buttons_row2,
                text="Expand All",
                style="Modern.TCheckbutton",
                variable=self.expand_all_var,
                command=self.toggle_expand_all
            )
            self.expand_all_check.pack(side=tk.LEFT, padx=(0, 5))

            self.toggle_excluded_only_check = ttk.Checkbutton(
                buttons_row2,
                text="Excluded Only",
                style="Modern.TCheckbutton",
                variable=self.excluded_only_var,
                command=self.toggle_excluded_only
            )
            self.toggle_excluded_only_check.pack(side=tk.LEFT, padx=(0, 5))

            self.clear_exclusions_button = self.create_button(
                buttons_row2,
                text="Clear All Exclusions",
                command=self.clear_all_exclusions,
                variant="warning",
                size="sm"
            )
            self.clear_exclusions_button.pack(side=tk.LEFT)

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
                    self.controller = VLCPlayerControllerForMultipleDirectory(all_videos, all_video_to_dir, all_directories,
                                                                              self.update_console)

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

        def on_directory_select(self, event):
            selection = self.dir_listbox.curselection()
            if not selection:
                if self.current_selected_dir_index is not None:
                    selected_dir = self.selected_dirs[self.current_selected_dir_index]
                    self.load_subdirectories(selected_dir)
                else:
                    self.clear_exclusion_list()
                return

            selected_index = selection[0]
            if selected_index >= len(self.selected_dirs):
                return

            self.current_selected_dir_index = selected_index
            selected_dir = self.selected_dirs[selected_index]
            self.load_subdirectories(selected_dir)

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
                self.expand_all_var.set(False)
                return
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
            self.load_subdirectories(selected_dir, max_depth=self.current_max_depth)

        def toggle_excluded_only(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showinfo("Information", "Please select a directory first.")
                return
            self.show_only_excluded = bool(self.excluded_only_var.get())
            self.load_subdirectories(selected_dir, max_depth=self.current_max_depth)

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

        def setup_controls_info(self):
            controls_header = tk.Label(self.main_frame, text="Keyboard Controls",
                                       font=self.header_font, bg=self.bg_color, fg=self.text_color)
            controls_header.pack(anchor='w', pady=(0, 10))

            controls_frame = tk.Frame(self.main_frame, bg=self.bg_color)
            controls_frame.pack(fill=tk.X, pady=(0, 15))

            nav_frame = tk.Frame(controls_frame, bg=self.bg_color)
            nav_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

            nav_label = tk.Label(nav_frame, text="Navigation", font=self.normal_font,
                                 bg=self.bg_color, fg=self.text_color)
            nav_label.pack(anchor='w', pady=(0, 5))

            nav_controls = [
                "D: Next video",
                "A: Previous video",
                "E: Next directory",
                "Q: Previous directory",
                "Esc: Stop current video"
            ]

            for control in nav_controls:
                tk.Label(nav_frame, text=control, font=self.small_font,
                         bg=self.bg_color, fg=self.text_color).pack(anchor='w', padx=10)

            playback_frame = tk.Frame(controls_frame, bg=self.bg_color)
            playback_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            playback_label = tk.Label(playback_frame, text="Playback", font=self.normal_font,
                                      bg=self.bg_color, fg=self.text_color)
            playback_label.pack(anchor='w', pady=(0, 5))

            playback_controls = [
                "Space: Play/Pause",
                "→/←: Fast forward/Rewind (10s)",
                "F: Toggle fullscreen",
                "W/S: Volume up/down",
                "1/2: Switch to monitor 1/2",
                "T: Take screenshot"
            ]

            for control in playback_controls:
                tk.Label(playback_frame, text=control, font=self.small_font,
                         bg=self.bg_color, fg=self.text_color).pack(anchor='w', padx=10)

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

            action_buttons_frame = tk.Frame(self.button_frame, bg=self.bg_color)
            action_buttons_frame.pack(side=tk.RIGHT)
            self.switch_to_qt_button = self.create_button(
                action_buttons_frame,
                text="Dark Mode",
                command=self.switch_to_qt_gui,
                variant="primary",
                size="md"
            )
            self.switch_to_qt_button.pack(side=tk.LEFT, padx=(0, 5))

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

        def switch_to_qt_gui(self):
            config = load_config()
            config["last_mode"] = "qt"
            config["switch_requested"] = True
            save_config(config)

            try:
                if hasattr(self, 'executor'):
                    self.executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

            self.cancel()

        def cancel(self):
            if self.controller:
                self.controller.stop()
            try:
                cleanup_hotkeys()
            except Exception:
                pass
            try:
                if hasattr(self, 'executor'):
                    self.executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            self.root.quit()
            self.root.destroy()

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
            directory = filedialog.askdirectory(title="Select a Directory", initialdir=self.last_dir)
            if directory and directory not in self.selected_dirs:
                self.selected_dirs.append(directory)
                self.last_dir = directory
                config = load_config()
                config["last_dir"] = directory
                save_config(config)

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


    root = tk.Tk()
    app = DirectorySelector(root)
    root.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    select_multiple_folders_and_play()
