import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from tkinter.font import Font
import os

from key_press import listen_keys, cleanup_hotkeys
from utils import gather_videos_with_directories, is_video
from vlc_player_controller import VLCPlayerControllerForMultipleDirectory


def select_multiple_folders_and_play():
    class DirectorySelector:
        def __init__(self, root):
            self.root = root
            self.selected_dirs = []
            self.excluded_subdirs = {}
            self.controller = None
            self.player_thread = None
            self.keys_thread = None
            self.video_count = 0
            self.current_selected_dir_index = None
            self.current_subdirs_mapping = {}
            self.setup_theme()

            root.title("Recursive Video Player")
            root.geometry("1600x900")
            root.protocol("WM_DELETE_WINDOW", self.cancel)
            root.configure(bg=self.bg_color)

            self.setup_main_layout()
            self.setup_directory_section()
            self.setup_exclusion_section()
            self.setup_status_section()
            self.setup_console_section()
            self.setup_controls_info()
            self.setup_action_buttons()

        def setup_theme(self):
            self.bg_color = "#f5f5f5"
            self.accent_color = "#3498db"
            self.text_color = "#333333"

            style = ttk.Style()
            style.configure("TFrame", background=self.bg_color)
            style.configure("TLabel", background=self.bg_color, foreground=self.text_color)

            self.create_custom_buttons()

            self.header_font = Font(family="Segoe UI", size=12, weight="bold")
            self.normal_font = Font(family="Segoe UI", size=10)
            self.small_font = Font(family="Segoe UI", size=9)
            self.mono_font = Font(family="Consolas", size=9)

        def create_custom_buttons(self):
            self.button_bg = "#2980b9"
            self.button_fg = "white"
            self.button_active_bg = "#3498db"
            self.accent_button_bg = "#e74c3c"
            self.accent_button_fg = "white"
            self.accent_button_active_bg = "#c0392b"

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

            self.clear_console_button = tk.Button(
                console_button_frame,
                text="Clear Console",
                command=self.clear_console,
                font=self.small_font,
                bg="#34495e",
                fg="white",
                activebackground="#2c3e50",
                activeforeground="white",
                relief=tk.FLAT,
                padx=10,
                pady=3,
                cursor="hand2"
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

            exclusion_header = tk.Label(self.exclusion_section, text="Exclude Subdirectories",
                                        font=self.header_font, bg=self.bg_color, fg=self.text_color)
            exclusion_header.pack(anchor='w', pady=(0, 10))

            self.selected_dir_label = tk.Label(
                self.exclusion_section,
                text="Select a directory to see its subdirectories",
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

            self.exclude_button = tk.Button(
                buttons_row1,
                text="Exclude Selected",
                command=self.exclude_subdirectories,
                font=self.normal_font,
                bg="#e74c3c",
                fg="white",
                activebackground="#c0392b",
                activeforeground="white",
                relief=tk.FLAT,
                padx=10,
                pady=5,
                cursor="hand2"
            )
            self.exclude_button.pack(side=tk.LEFT, padx=(0, 5))

            self.include_button = tk.Button(
                buttons_row1,
                text="Include Selected",
                command=self.include_subdirectories,
                font=self.normal_font,
                bg="#27ae60",
                fg="white",
                activebackground="#229954",
                activeforeground="white",
                relief=tk.FLAT,
                padx=10,
                pady=5,
                cursor="hand2"
            )
            self.include_button.pack(side=tk.LEFT, padx=(0, 5))

            self.exclude_all_button = tk.Button(
                buttons_row1,
                text="Exclude All",
                command=self.exclude_all_subdirectories,
                font=self.normal_font,
                bg="#e67e22",
                fg="white",
                activebackground="#d35400",
                activeforeground="white",
                relief=tk.FLAT,
                padx=10,
                pady=5,
                cursor="hand2"
            )
            self.exclude_all_button.pack(side=tk.LEFT)

            buttons_row2 = tk.Frame(exclusion_buttons_frame, bg=self.bg_color)
            buttons_row2.pack(fill=tk.X)

            self.expand_all_button = tk.Button(
                buttons_row2,
                text="Expand All",
                command=self.expand_all_directories,
                font=self.small_font,
                bg="#95a5a6",
                fg="white",
                activebackground="#7f8c8d",
                activeforeground="white",
                relief=tk.FLAT,
                padx=8,
                pady=3,
                cursor="hand2"
            )
            self.expand_all_button.pack(side=tk.LEFT, padx=(0, 5))

            self.collapse_all_button = tk.Button(
                buttons_row2,
                text="Collapse All",
                command=self.collapse_all_directories,
                font=self.small_font,
                bg="#95a5a6",
                fg="white",
                activebackground="#7f8c8d",
                activeforeground="white",
                relief=tk.FLAT,
                padx=8,
                pady=3,
                cursor="hand2"
            )
            self.collapse_all_button.pack(side=tk.LEFT, padx=(0, 5))

            self.clear_exclusions_button = tk.Button(
                buttons_row2,
                text="Clear All Exclusions",
                command=self.clear_all_exclusions,
                font=self.small_font,
                bg="#f39c12",
                fg="white",
                activebackground="#e67e22",
                activeforeground="white",
                relief=tk.FLAT,
                padx=8,
                pady=3,
                cursor="hand2"
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
            subdirs = []
            try:
                all_subdirs = self.get_all_subdirectories(parent_path)

                target_path_norm = os.path.normpath(target_path)
                for subdir_path, _ in all_subdirs:
                    subdir_path_norm = os.path.normpath(subdir_path)
                    if (subdir_path_norm == target_path_norm or
                            subdir_path_norm.startswith(target_path_norm + os.sep)):
                        subdirs.append(subdir_path)
            except Exception as e:
                self.update_console(f"Error getting subdirectories of {target_path}: {e}")

            return subdirs

        def update_video_count(self):
            total_videos = 0
            total_excluded = 0

            for directory in self.selected_dirs:
                videos, _, _ = gather_videos_with_directories(directory)

                excluded_subdirs = self.excluded_subdirs.get(directory, [])
                if excluded_subdirs:
                    filtered_videos = []
                    for video in videos:
                        if not self.is_video_in_excluded_directory(video, excluded_subdirs):
                            filtered_videos.append(video)
                    total_videos += len(filtered_videos)
                else:
                    total_videos += len(videos)

            self.video_count = total_videos
            self.video_count_label.config(text=f"Total Videos: {self.video_count}")

            if total_excluded > 0:
                self.update_console(
                    f"Total: {total_videos} videos selected, {total_excluded} excluded from {len(self.selected_dirs)} directories")
            else:
                self.update_console(f"Total: {total_videos} videos selected from {len(self.selected_dirs)} directories")

        def play_videos(self):
            if not self.selected_dirs:
                messagebox.showwarning("No Directories", "Please select at least one directory.")
                return

            if self.controller:
                self.controller.stop()
                cleanup_hotkeys()

            all_videos = []
            all_video_to_dir = {}
            all_directories = []

            self.root.config(cursor="wait")
            self.root.update()

            self.update_console("=" * 100)
            self.update_console("STARTING VIDEO PLAYBACK")
            self.update_console("=" * 100)
            try:
                for directory in self.selected_dirs:
                    videos, video_to_dir, directories = gather_videos_with_directories(directory)

                    excluded_subdirs = self.excluded_subdirs.get(directory, [])
                    if excluded_subdirs:
                        filtered_videos = []
                        filtered_video_to_dir = {}
                        filtered_directories = []

                        for video in videos:
                            if not self.is_video_in_excluded_directory(video, excluded_subdirs):
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

                    self.update_console(
                        f"Found {len(videos)} videos in {len(directories)} directories from {directory}")
                    if excluded_subdirs:
                        excluded_count = len(videos) - len(filtered_videos if excluded_subdirs else videos)
                        self.update_console(
                            f"Excluded {excluded_count} videos from {len(excluded_subdirs)} subdirectories")

                all_directories = sorted(list(set(all_directories)))

                if not all_videos:
                    messagebox.showwarning("No Videos", "No videos found in the selected directories.")
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
            finally:
                self.root.config(cursor="")

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
            self.selected_dir_label.config(text="Select a directory to see its subdirectories")
            self.exclusion_listbox.delete(0, tk.END)
            self.current_subdirs_mapping = {}

        def exclude_all_subdirectories(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showinfo("Information", "Please select a directory first.")
                return

            all_subdirs = self.get_all_subdirectories(selected_dir)
            if not all_subdirs:
                messagebox.showinfo("Information", "No subdirectories found in the selected directory.")
                return

            self.excluded_subdirs[selected_dir] = [path for path, _ in all_subdirs]
            self.update_console(
                f"Excluded ALL {len(all_subdirs)} subdirectories from '{os.path.basename(selected_dir)}'")

            self.load_subdirectories(selected_dir)
            self.update_video_count()
            self.exclusion_listbox.selection_clear(0, tk.END)

        def exclude_subdirectories(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showinfo("Information", "Please select a directory first.")
                return

            exclusion_selection = self.exclusion_listbox.curselection()

            if not exclusion_selection:
                messagebox.showinfo("Information", "Please select subdirectories to exclude.")
                return

            if selected_dir not in self.excluded_subdirs:
                self.excluded_subdirs[selected_dir] = []

            try:
                dirs_to_exclude = set()
                selected_names = []

                for index in exclusion_selection:
                    if index in self.current_subdirs_mapping:
                        target_path = self.current_subdirs_mapping[index]
                        nested_dirs = self.get_all_subdirectories_of_path(selected_dir, target_path)
                        dirs_to_exclude.update(nested_dirs)
                        selected_names.append(os.path.basename(target_path))

                excluded_count = 0
                for dir_path in dirs_to_exclude:
                    if dir_path not in self.excluded_subdirs[selected_dir]:
                        self.excluded_subdirs[selected_dir].append(dir_path)
                        excluded_count += 1

                if excluded_count > 0:
                    self.update_console(
                        f"Excluded {excluded_count} subdirectories from '{os.path.basename(selected_dir)}': {', '.join(selected_names)}")

                self.load_subdirectories(selected_dir)
                self.update_video_count()
                self.exclusion_listbox.selection_clear(0, tk.END)

            except Exception as e:
                messagebox.showerror("Error", f"Error excluding subdirectories: {str(e)}")

        def include_subdirectories(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showinfo("Information", "Please select a directory first.")
                return

            exclusion_selection = self.exclusion_listbox.curselection()

            if not exclusion_selection:
                messagebox.showinfo("Information", "Please select subdirectories to include.")
                return

            if selected_dir not in self.excluded_subdirs:
                return

            try:
                dirs_to_include = set()
                selected_names = []

                for index in exclusion_selection:
                    if index in self.current_subdirs_mapping:
                        target_path = self.current_subdirs_mapping[index]
                        nested_dirs = self.get_all_subdirectories_of_path(selected_dir, target_path)
                        dirs_to_include.update(nested_dirs)
                        selected_names.append(os.path.basename(target_path))

                included_count = 0
                for dir_path in dirs_to_include:
                    if dir_path in self.excluded_subdirs[selected_dir]:
                        self.excluded_subdirs[selected_dir].remove(dir_path)
                        included_count += 1

                if included_count > 0:
                    self.update_console(
                        f"Included {included_count} subdirectories in '{os.path.basename(selected_dir)}': {', '.join(selected_names)}")

                if not self.excluded_subdirs[selected_dir]:
                    del self.excluded_subdirs[selected_dir]

                self.load_subdirectories(selected_dir)
                self.update_video_count()
                self.exclusion_listbox.selection_clear(0, tk.END)

            except Exception as e:
                messagebox.showerror("Error", f"Error including subdirectories: {str(e)}")

        def expand_all_directories(self):
            selected_dir = self.get_current_selected_directory()
            if selected_dir:
                self.load_subdirectories(selected_dir, max_depth=20)

        def collapse_all_directories(self):
            selected_dir = self.get_current_selected_directory()
            if selected_dir:
                self.load_subdirectories(selected_dir, max_depth=1)

        def clear_all_exclusions(self):
            selected_dir = self.get_current_selected_directory()
            if not selected_dir:
                messagebox.showinfo("Information", "Please select a directory first.")
                return

            if selected_dir in self.excluded_subdirs:
                excluded_count = len(self.excluded_subdirs[selected_dir])
                result = messagebox.askyesno(
                    "Confirm",
                    f"Clear all exclusions for {os.path.basename(selected_dir)}?"
                )
                if result:
                    del self.excluded_subdirs[selected_dir]
                    self.update_console(
                        f"Cleared all {excluded_count} exclusions for '{os.path.basename(selected_dir)}'")
                    self.load_subdirectories(selected_dir)
                    self.update_video_count()

        def load_subdirectories(self, directory, max_depth=20):
            self.selected_dir_label.config(text=f"All subdirectories in: {os.path.basename(directory)}")
            self.exclusion_listbox.delete(0, tk.END)

            try:
                all_subdirs = self.get_all_subdirectories(directory, max_depth=max_depth)

                if not all_subdirs:
                    self.exclusion_listbox.insert(tk.END, "No subdirectories found")
                    return

                excluded_set = set(self.excluded_subdirs.get(directory, []))

                for subdir_path, display_name in all_subdirs:

                    indent_level = display_name.count('/')
                    indented_name = "  " * indent_level
                    if os.path.isdir(subdir_path):
                        indented_name += '📁' + display_name.split('/')[-1]
                    else:
                        indented_name += '▶' + display_name.split('/')[-1]

                    if subdir_path in excluded_set:
                        indented_name += "🚫[EXCLUDED]"

                    self.exclusion_listbox.insert(tk.END, indented_name)
                self.current_subdirs_mapping = {i: subdir_path for i, (subdir_path, _) in enumerate(all_subdirs)}

            except Exception as e:
                self.exclusion_listbox.insert(tk.END, f"Error loading subdirectories: {str(e)}")
                self.current_subdirs_mapping = {}

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

            self.add_button = tk.Button(
                dir_buttons_frame,
                text="Add Directory",
                command=self.add_directory,
                font=self.normal_font,
                bg=self.button_bg,
                fg=self.button_fg,
                activebackground=self.button_active_bg,
                activeforeground="white",
                relief=tk.FLAT,
                padx=10,
                pady=5,
                cursor="hand2"
            )
            self.add_button.pack(side=tk.LEFT, padx=(0, 5))

            self.remove_button = tk.Button(
                dir_buttons_frame,
                text="Remove Selected",
                command=self.remove_directory,
                font=self.normal_font,
                bg=self.button_bg,
                fg=self.button_fg,
                activebackground=self.button_active_bg,
                activeforeground="white",
                relief=tk.FLAT,
                padx=10,
                pady=5,
                cursor="hand2"
            )
            self.remove_button.pack(side=tk.LEFT)

            action_buttons_frame = tk.Frame(self.button_frame, bg=self.bg_color)
            action_buttons_frame.pack(side=tk.RIGHT)

            self.cancel_button = tk.Button(
                action_buttons_frame,
                text="Close",
                command=self.cancel,
                font=self.normal_font,
                bg=self.button_bg,
                fg=self.button_fg,
                activebackground=self.button_active_bg,
                activeforeground="white",
                relief=tk.FLAT,
                padx=10,
                pady=5,
                cursor="hand2"
            )
            self.cancel_button.pack(side=tk.LEFT, padx=(0, 5))

            self.play_button = tk.Button(
                action_buttons_frame,
                text="▶ Play Videos",
                command=self.play_videos,
                font=(self.normal_font.name, self.normal_font.actual()['size'], 'bold'),
                bg=self.accent_button_bg,
                fg=self.accent_button_fg,
                activebackground=self.accent_button_active_bg,
                activeforeground="white",
                relief=tk.FLAT,
                padx=10,
                pady=5,
                cursor="hand2"
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
                videos, _, _ = gather_videos_with_directories(directory)
                self.update_console(f"Added directory: {directory}")
                self.update_console(f"Found {len(videos)} videos in '{os.path.basename(directory)}'")
                self.update_video_count()

        def remove_directory(self):
            selected_indices = self.dir_listbox.curselection()
            if not selected_indices:
                messagebox.showinfo("Information", "Please select a directory to remove.")
                return

            for i in sorted(selected_indices, reverse=True):
                dir_to_remove = self.selected_dirs[i]
                self.update_console(f"Removed directory: {os.path.basename(dir_to_remove)}")

                if dir_to_remove in self.excluded_subdirs:
                    excluded_count = len(self.excluded_subdirs[dir_to_remove])
                    self.update_console(f"Cleared {excluded_count} exclusions for '{os.path.basename(dir_to_remove)}'")
                    del self.excluded_subdirs[dir_to_remove]

                self.dir_listbox.delete(i)
                self.selected_dirs.pop(i)

            if self.current_selected_dir_index is not None:
                if self.current_selected_dir_index >= len(self.selected_dirs):
                    self.current_selected_dir_index = None

            self.update_video_count()
            self.clear_exclusion_list()

        def cancel(self):
            if self.controller:
                self.controller.stop()
            cleanup_hotkeys()
            self.root.quit()
            self.root.destroy()

    root = tk.Tk()
    app = DirectorySelector(root)
    root.mainloop()


if __name__ == "__main__":
    select_multiple_folders_and_play()
