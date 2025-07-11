import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.font import Font
import os

from key_press import listen_keys
from utils import gather_videos_with_directories
from vlc_player_controller import VLCPlayerControllerForMultipleDirectory


def select_multiple_folders_and_play():
    class DirectorySelector:
        def __init__(self, root):
            self.root = root
            self.selected_dirs = []
            self.controller = None
            self.player_thread = None
            self.keys_thread = None
            self.video_count = 0

            self.setup_theme()

            root.title("Video Player")
            root.geometry("900x700")
            root.protocol("WM_DELETE_WINDOW", self.cancel)
            root.configure(bg=self.bg_color)

            self.setup_main_layout()

            self.setup_directory_section()

            self.setup_controls_info()

            self.setup_action_buttons()

            self.setup_status_section()

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

        def setup_directory_section(self):
            dir_header = tk.Label(self.main_frame, text="Selected Directories",
                                  font=self.header_font, bg=self.bg_color, fg=self.text_color)
            dir_header.pack(anchor='w', pady=(0, 10))

            self.dir_frame = tk.Frame(self.main_frame, bg=self.bg_color)
            self.dir_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

            list_container = tk.Frame(self.dir_frame, bg=self.bg_color,
                                      highlightbackground="#cccccc",
                                      highlightthickness=1)
            list_container.pack(fill=tk.BOTH, expand=True)

            self.scrollbar = tk.Scrollbar(list_container)
            self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            self.dir_listbox = tk.Listbox(
                list_container,
                selectmode=tk.MULTIPLE,
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
            self.scrollbar.config(command=self.dir_listbox.yview)

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
                self.video_count += len(videos)
                self.video_count_label.config(text=f"Total Videos: {self.video_count}")

        def remove_directory(self):
            selected_indices = self.dir_listbox.curselection()
            if not selected_indices:
                messagebox.showinfo("Information", "Please select directories to remove.")
                return

            for i in sorted(selected_indices, reverse=True):
                dir_to_remove = self.selected_dirs[i]
                
                videos, _, _ = gather_videos_with_directories(dir_to_remove)
                self.video_count -= len(videos)
                
                self.dir_listbox.delete(i)
                self.selected_dirs.pop(i)
                
                self.video_count_label.config(text=f"Total Videos: {self.video_count}")

        def play_videos(self):
            if not self.selected_dirs:
                messagebox.showwarning("No Directories", "Please select at least one directory.")
                return

            if self.controller:
                self.controller.stop()
                
            all_videos = []
            all_video_to_dir = {}
            all_directories = []

            self.root.config(cursor="wait")
            self.root.update()

            try:
                for directory in self.selected_dirs:
                    videos, video_to_dir, directories = gather_videos_with_directories(directory)
                    all_videos.extend(videos)
                    all_video_to_dir.update(video_to_dir)
                    all_directories.extend(directories)
                    print(f"Found {len(videos)} videos in {len(directories)} directories from {directory}")

                all_directories = sorted(list(set(all_directories)))

                if not all_videos:
                    print("No videos found in the selected directories.")
                    messagebox.showwarning("No Videos", "No videos found in the selected directories.")
                    return

                self.controller = VLCPlayerControllerForMultipleDirectory(all_videos, all_video_to_dir, all_directories)

                if self.player_thread and self.player_thread.is_alive():
                    self.controller.running = False
                    self.player_thread.join(timeout=1.0)

                self.player_thread = threading.Thread(target=self.controller.run, daemon=True)
                self.player_thread.start()

                if self.keys_thread and self.keys_thread.is_alive():
                    pass
                else:
                    self.keys_thread = threading.Thread(target=lambda: listen_keys(self.controller), daemon=True)
                    self.keys_thread.start()
            finally:
                self.root.config(cursor="")

        def cancel(self):
            if self.controller:
                self.controller.stop()
            self.root.quit()
            self.root.destroy()

    root = tk.Tk()
    app = DirectorySelector(root)
    root.mainloop()


if __name__ == "__main__":
    select_multiple_folders_and_play()