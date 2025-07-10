import os
import fnmatch
import time
import tkinter as tk
from tkinter import filedialog, messagebox
import vlc
import keyboard
import threading
import ctypes
from screeninfo import get_monitors

VIDEO_EXTENSIONS = ['*.mp4', '*.mkv', '*.avi', '*.mov', '*.wmv', '*.flv']


def is_video(file_name):
    return any(fnmatch.fnmatch(file_name.lower(), ext) for ext in VIDEO_EXTENSIONS)


def gather_videos_with_directories(directory):
    """Gather videos and track which directory each video belongs to"""
    videos = []
    video_to_dir = {}
    directories = []

    # First, gather all directories (including nested ones)
    for root, dirs, files in os.walk(directory):
        if any(is_video(file) for file in files):
            directories.append(root)

    # Sort directories to ensure consistent ordering
    directories.sort()

    # Now gather videos from each directory
    for dir_path in directories:
        dir_videos = []
        for file in os.listdir(dir_path):
            full_path = os.path.join(dir_path, file)
            if os.path.isfile(full_path) and is_video(file):
                dir_videos.append(full_path)

        # Sort videos within each directory
        dir_videos.sort()

        # Add to main list and track directory mapping
        for video in dir_videos:
            videos.append(video)
            video_to_dir[video] = dir_path

    return videos, video_to_dir, directories


def gather_videos(directory):
    """Legacy function for backward compatibility"""
    videos, _, _ = gather_videos_with_directories(directory)
    return videos


def set_window_pos(hwnd, x, y, w, h):
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    return ctypes.windll.user32.SetWindowPos(hwnd, 0, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE)


class VLCPlayerController:
    def __init__(self, videos, video_to_dir, directories):
        monitors = get_monitors()

        if len(monitors) >= 1:
            mon1 = monitors[0]
            print(f"Monitor 1: {mon1.name} at ({mon1.x}, {mon1.y}), {mon1.width}x{mon1.height}")
            self.monitor1_x = mon1.x
            self.monitor1_y = mon1.y
            self.monitor1_width = mon1.width
            self.monitor1_height = mon1.height
        else:
            print("No monitors detected!")
            self.monitor1_x = 0
            self.monitor1_y = 0
            self.monitor1_width = 800
            self.monitor1_height = 600

        if len(monitors) >= 2:
            mon2 = monitors[1]
            print(f"Monitor 2: {mon2.name} at ({mon2.x}, {mon2.y}), {mon2.width}x{mon2.height}")
            self.monitor2_x = mon2.x
            self.monitor2_y = mon2.y
            self.monitor2_width = mon2.width
            self.monitor2_height = mon2.height
            # Use monitor 2 as default
            self.instance = vlc.Instance(f'--video-x={mon2.x}', f'--video-y={mon2.y}')
        else:
            print("Only one monitor detected, second monitor features disabled.")
            # Set monitor 2 same as monitor 1 if not available
            self.monitor2_x = self.monitor1_x
            self.monitor2_y = self.monitor1_y
            self.monitor2_width = self.monitor1_width
            self.monitor2_height = self.monitor1_height
            self.instance = vlc.Instance()

        self.player = self.instance.media_player_new()
        self.videos = videos
        self.video_to_dir = video_to_dir
        self.directories = directories
        self.index = 0
        self.volume = 100
        self.lock = threading.Lock()
        self.running = True
        self.fullscreen_enabled = False
        self.current_monitor = 2

    def get_current_directory(self):
        """Get the directory of the currently playing video"""
        if self.index < len(self.videos):
            return self.video_to_dir.get(self.videos[self.index])
        return None

    def find_next_directory_video(self):
        """Find the first video in the next directory"""
        current_dir = self.get_current_directory()
        if not current_dir:
            return None

        try:
            current_dir_index = self.directories.index(current_dir)
            next_dir_index = (current_dir_index + 1) % len(self.directories)
            next_dir = self.directories[next_dir_index]

            # Find first video in the next directory
            for i, video in enumerate(self.videos):
                if self.video_to_dir[video] == next_dir:
                    return i
        except (ValueError, IndexError):
            pass

        return None

    def find_prev_directory_video(self):
        """Find the first video in the previous directory"""
        current_dir = self.get_current_directory()
        if not current_dir:
            return None

        try:
            current_dir_index = self.directories.index(current_dir)
            prev_dir_index = (current_dir_index - 1) % len(self.directories)
            prev_dir = self.directories[prev_dir_index]

            # Find first video in the previous directory
            for i, video in enumerate(self.videos):
                if self.video_to_dir[video] == prev_dir:
                    return i
        except (ValueError, IndexError):
            pass

        return None

    def next_directory(self):
        """Skip to the next directory"""
        next_index = self.find_next_directory_video()
        if next_index is not None:
            next_dir = self.video_to_dir[self.videos[next_index]]
            print(f"Skipping to next directory: {next_dir}")
            self.play_video(next_index)
        else:
            print("No next directory found")

    def prev_directory(self):
        """Skip to the previous directory"""
        prev_index = self.find_prev_directory_video()
        if prev_index is not None:
            prev_dir = self.video_to_dir[self.videos[prev_index]]
            print(f"Skipping to previous directory: {prev_dir}")
            self.play_video(prev_index)
        else:
            print("No previous directory found")

    def position_on_monitor1(self):
        time.sleep(0.5)
        hwnd = self.player.get_hwnd()
        if hwnd:
            print(f"Window handle: {hwnd}")
            result = set_window_pos(hwnd, self.monitor1_x, self.monitor1_y,
                                    self.monitor1_width, self.monitor1_height)
            print(f"SetWindowPos result on monitor 1: {result}")
            self.current_monitor = 1

    def position_on_monitor2(self):
        time.sleep(0.5)
        hwnd = self.player.get_hwnd()
        if hwnd:
            print(f"Window handle: {hwnd}")
            result = set_window_pos(hwnd, self.monitor2_x, self.monitor2_y,
                                    self.monitor2_width, self.monitor2_height)
            print(f"SetWindowPos result on monitor 2: {result}")
            self.current_monitor = 2

    def play_video(self, index):
        with self.lock:
            if index < 0 or index >= len(self.videos):
                return False
            self.index = index
            current_video = self.videos[self.index]
            current_dir = self.video_to_dir[current_video]
            print(f"Playing: {os.path.basename(current_video)} from {current_dir}")

            media = self.instance.media_new(current_video)
            self.player.set_media(media)
            self.player.play()
            self.player.audio_set_volume(self.volume)

            state = self.player.get_state()
            while state != vlc.State.Playing and self.running:
                time.sleep(0.1)
                state = self.player.get_state()

            self.position_on_monitor2()
            self.player.set_fullscreen(self.fullscreen_enabled)

            return True

    def next_video(self):
        with self.lock:
            next_index = (self.index + 1) % len(self.videos)
        self.play_video(next_index)

    def prev_video(self):
        with self.lock:
            prev_index = (self.index - 1) % len(self.videos)
        self.play_video(prev_index)

    def stop(self):
        with self.lock:
            self.running = False
            self.player.stop()

    def volume_up(self):
        with self.lock:
            self.volume = min(100, self.volume + 10)
            self.player.audio_set_volume(self.volume)
            print(f"Volume: {self.volume}")

    def volume_down(self):
        with self.lock:
            self.volume = max(0, self.volume - 10)
            self.player.audio_set_volume(self.volume)
            print(f"Volume: {self.volume}")

    def toggle_fullscreen(self):
        with self.lock:
            self.fullscreen_enabled = not self.fullscreen_enabled
            self.player.set_fullscreen(self.fullscreen_enabled)
            if not self.fullscreen_enabled:
                if self.current_monitor == 1:
                    self.position_on_monitor1()
                else:
                    self.position_on_monitor2()
            print(f"Fullscreen set to {self.fullscreen_enabled}")

    def toggle_pause(self):
        with self.lock:
            if self.player.is_playing():
                self.player.pause()
                print("Paused")
            else:
                self.player.play()
                print("Resumed")

    def fast_forward(self):
        with self.lock:
            current_time = self.player.get_time()
            new_time = current_time + 200
            length = self.player.get_length()
            if length > 0 and new_time > length:
                new_time = length - 20
            self.player.set_time(new_time)
            print(f"Fast forward to {new_time / 20:.1f}s")

    def rewind(self):
        with self.lock:
            current_time = self.player.get_time()
            new_time = max(0, current_time - 200)  # 10 seconds
            self.player.set_time(new_time)
            print(f"Rewind to {new_time / 20:.1f}s")

    def run(self):
        self.play_video(self.index)
        while self.running:
            state = self.player.get_state()
            if state == vlc.State.Ended:
                self.next_video()

    def switch_to_monitor(self, monitor_number):
        with self.lock:
            print(f"Switching to monitor {monitor_number} by recreating player")

            current_position = self.player.get_time()
            current_media = self.player.get_media()
            was_playing = self.player.is_playing()

            self.player.stop()

            if monitor_number == 1:
                self.instance = vlc.Instance(f'--video-x={self.monitor1_x}', f'--video-y={self.monitor1_y}')
                self.current_monitor = 1
            else:
                self.instance = vlc.Instance(f'--video-x={self.monitor2_x}', f'--video-y={self.monitor2_y}')
                self.current_monitor = 2

            self.player = self.instance.media_player_new()

            if current_media:
                self.player.set_media(current_media)
                if was_playing:
                    self.player.play()
                    time.sleep(0.5)
                    self.player.set_time(current_position)
                    if self.fullscreen_enabled:
                        self.player.set_fullscreen(True)

            print(f"Switched to monitor {monitor_number}")


def listen_keys(controller):
    keyboard.add_hotkey('d', lambda: controller.next_video())
    keyboard.add_hotkey('a', lambda: controller.prev_video())
    keyboard.add_hotkey('esc', lambda: controller.stop())
    keyboard.add_hotkey('w', lambda: controller.volume_up())
    keyboard.add_hotkey('s', lambda: controller.volume_down())
    keyboard.add_hotkey('f', lambda: controller.toggle_fullscreen())
    keyboard.add_hotkey('space', lambda: controller.toggle_pause())
    keyboard.add_hotkey('1', lambda: controller.switch_to_monitor(1))
    keyboard.add_hotkey('2', lambda: controller.switch_to_monitor(2))
    keyboard.add_hotkey('right', lambda: controller.fast_forward())
    keyboard.add_hotkey('left', lambda: controller.rewind())
    # New hotkeys for directory navigation
    keyboard.add_hotkey('e', lambda: controller.next_directory())
    keyboard.add_hotkey('q', lambda: controller.prev_directory())
    keyboard.wait('esc')


def select_multiple_folders_and_play():
    class DirectorySelector:
        def __init__(self, root):
            self.root = root
            self.selected_dirs = []

            root.title("Select Video Directories")
            root.geometry("800x650")

            # Main content frame
            main_frame = tk.Frame(root)
            main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            # Directory selection frame
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

            # Controls information frame
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

            # Button frame
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

        def add_directory(self):
            directory = filedialog.askdirectory(title="Select a Directory")
            if directory and directory not in self.selected_dirs:
                self.selected_dirs.append(directory)
                self.dir_listbox.insert(tk.END, directory)

        def remove_directory(self):
            selected_indices = self.dir_listbox.curselection()
            for i in sorted(selected_indices, reverse=True):
                self.dir_listbox.delete(i)
                self.selected_dirs.pop(i)

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

    # Remove duplicates from directories and sort
    all_directories = sorted(list(set(all_directories)))

    if not all_videos:
        print("No videos found in the selected directories.")
        return

    print(f"Total videos to play: {len(all_videos)}")
    print(f"Total directories: {len(all_directories)}")
    print("Controls:")
    print("  D/A: Next/Previous video")
    print("  E: Next directory")
    print("  Q: Previous directory")
    print("  Space: Play/Pause")
    print("  F: Toggle fullscreen")
    print("  W/S: Volume up/down")
    print("  1/2: Switch to monitor 1/2")
    print("  Right/Left Arrow: Fast forward/Rewind")
    print("  Esc: Exit")

    controller = VLCPlayerController(all_videos, all_video_to_dir, all_directories)
    player_thread = threading.Thread(target=controller.run, daemon=True)
    player_thread.start()

    listen_keys(controller)

    print("Exiting player...")


if __name__ == "__main__":
    select_multiple_folders_and_play()