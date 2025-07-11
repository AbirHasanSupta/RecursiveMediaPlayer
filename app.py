import threading
from tkinter import filedialog
import tkinter as tk

from key_press import listen_keys
from utils import gather_videos_with_directories
from vlc_player_controller import VLCPlayerControllerForMultipleDirectory


def select_multiple_folders_and_play():
    class DirectorySelector:
        def __init__(self, root):
            self.root = root
            self.selected_dirs = []

            root.title("Select Video Directories")
            root.geometry("800x600")

            main_frame = tk.Frame(root)
            main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            self.list_frame = tk.Frame(main_frame)
            self.list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

            tk.Label(self.list_frame, text="Selected Directories:", font=('Arial', 10, 'bold')).pack(anchor='w')

            list_container = tk.Frame(self.list_frame)
            list_container.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

            self.scrollbar = tk.Scrollbar(list_container)
            self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

            self.dir_listbox = tk.Listbox(list_container, selectmode=tk.MULTIPLE,
                                          yscrollcommand=self.scrollbar.set)
            self.dir_listbox.pack(fill=tk.BOTH, expand=True)
            self.scrollbar.config(command=self.dir_listbox.yview)

            controls_frame = tk.Frame(main_frame)
            controls_frame.pack(fill=tk.X, pady=(0, 10))

            tk.Label(controls_frame, text="Video Player Controls:", font=('Arial', 10, 'bold')).pack(anchor='w')

            controls_text = """
Navigation:
  • D/A: Next/Previous video
  • E: Next directory
  • Q: Previous directory

Playback:
  • Space: Play/Pause
  • Right/Left Arrow: Fast forward/Rewind (10 seconds)
  • F: Toggle fullscreen
  • T: Take ScreenShot

Audio & Display:
  • W/S: Volume up/down
  • 1/2: Switch to monitor 1/2

System:
  • Esc: Exit player
            """

            controls_label = tk.Label(controls_frame, text=controls_text.strip(),
                                      font=('Courier', 9), justify=tk.LEFT,
                                      relief=tk.SUNKEN, padx=10, pady=5)
            controls_label.pack(fill=tk.X, pady=(5, 0))

            self.button_frame = tk.Frame(main_frame)
            self.button_frame.pack(fill=tk.X)

            self.add_button = tk.Button(self.button_frame, text="Add Directory",
                                        command=self.add_directory)
            self.add_button.pack(side=tk.LEFT, padx=5)

            self.remove_button = tk.Button(self.button_frame, text="Remove Selected",
                                           command=self.remove_directory)
            self.remove_button.pack(side=tk.LEFT, padx=5)

            self.play_button = tk.Button(self.button_frame, text="Play Videos",
                                         command=self.play_videos, font=('Arial', 10, 'bold'))
            self.play_button.pack(side=tk.RIGHT, padx=5)

            self.cancel_button = tk.Button(self.button_frame, text="Cancel",
                                           command=self.cancel)
            self.cancel_button.pack(side=tk.RIGHT, padx=5)

            self.result = None

            self.video_count = 0
            self.video_count_frame = tk.Frame(main_frame)
            self.video_count_frame.pack(fill=tk.X, pady=(5, 10))
            self.video_count_label = tk.Label(self.video_count_frame, 
                                              text="Total Videos: 0", 
                                              font=('Arial', 10, 'bold'))
            self.video_count_label.pack(side=tk.LEFT)
            

        def add_directory(self):
            directory = filedialog.askdirectory(title="Select a Directory")
            if directory and directory not in self.selected_dirs:
                self.selected_dirs.append(directory)
                self.dir_listbox.insert(tk.END, directory)
                
                videos, _, _ = gather_videos_with_directories(directory)
                self.video_count += len(videos)
                self.video_count_label.config(text=f"Total Videos: {self.video_count}")

        def remove_directory(self):
            selected_indices = self.dir_listbox.curselection()
            for i in sorted(selected_indices, reverse=True):
                dir_to_remove = self.selected_dirs[i]
                
                videos, _, _ = gather_videos_with_directories(dir_to_remove)
                self.video_count -= len(videos)
                
                self.dir_listbox.delete(i)
                self.selected_dirs.pop(i)
                
                self.video_count_label.config(text=f"Total Videos: {self.video_count}")

        def play_videos(self):
            if self.selected_dirs:
                self.result = self.selected_dirs.copy()
                self.root.destroy()
            else:
                tk.messagebox.showwarning("No Directories", "Please select at least one directory.")

        def cancel(self):
            self.root.destroy()

    root = tk.Tk()
    selector = DirectorySelector(root)

    root.mainloop()

    if not hasattr(selector, 'result') or not selector.result:
        print("No directories selected.")
        return

    all_videos = []
    all_video_to_dir = {}
    all_directories = []

    for directory in selector.result:
        videos, video_to_dir, directories = gather_videos_with_directories(directory)
        all_videos.extend(videos)
        all_video_to_dir.update(video_to_dir)
        all_directories.extend(directories)
        print(f"Found {len(videos)} videos in {len(directories)} directories from {directory}")

    all_directories = sorted(list(set(all_directories)))

    if not all_videos:
        print("No videos found in the selected directories.")
        return

    controller = VLCPlayerControllerForMultipleDirectory(all_videos, all_video_to_dir, all_directories)
    player_thread = threading.Thread(target=controller.run, daemon=True)
    player_thread.start()

    listen_keys(controller)

    print("Exiting player...")


if __name__ == "__main__":
    select_multiple_folders_and_play()