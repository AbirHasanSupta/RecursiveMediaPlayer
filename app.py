import os
import fnmatch
import time
import tkinter as tk
from tkinter import filedialog
import vlc
import keyboard
import threading
import ctypes
from screeninfo import get_monitors

VIDEO_EXTENSIONS = ['*.mp4', '*.mkv', '*.avi', '*.mov', '*.wmv', '*.flv']

def is_video(file_name):
    return any(fnmatch.fnmatch(file_name.lower(), ext) for ext in VIDEO_EXTENSIONS)

def gather_videos(directory):
    videos = []
    for file in os.listdir(directory):
        full_path = os.path.join(directory, file)
        if os.path.isfile(full_path) and is_video(file):
            videos.append(full_path)
    for root, dirs, files in os.walk(directory):
        if root == directory:
            continue
        for file in files:
            if is_video(file):
                videos.append(os.path.join(root, file))
    return videos

def set_window_pos(hwnd, x, y, w, h):
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    ctypes.windll.user32.SetWindowPos(hwnd, 0, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE)

class VLCPlayerController:
    def __init__(self, videos):
        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()
        self.videos = videos
        self.index = 0
        self.volume = 100
        self.lock = threading.Lock()
        self.running = True
        self.fullscreen_enabled = False

        # Get monitors info dynamically
        monitors = get_monitors()
        if len(monitors) > 1:
            mon = monitors[1]  # second monitor
            print(f"Using second monitor: {mon.name} at ({mon.x}, {mon.y}), {mon.width}x{mon.height}")
        else:
            mon = monitors[0]
            print(f"Only one monitor detected: {mon.name} at ({mon.x}, {mon.y}), {mon.width}x{mon.height}")

        self.monitor2_x = mon.x
        self.monitor2_y = mon.y
        self.monitor2_width = mon.width
        self.monitor2_height = mon.height

    def position_on_monitor2(self):
        hwnd = self.player.get_hwnd()
        if hwnd:
            set_window_pos(hwnd, self.monitor2_x, self.monitor2_y,
                          self.monitor2_width, self.monitor2_height)

    def play_video(self, index):
        with self.lock:
            if index < 0 or index >= len(self.videos):
                return False
            self.index = index
            media = self.instance.media_new(self.videos[self.index])
            self.player.set_media(media)
            self.player.play()
            self.player.audio_set_volume(self.volume)

            # Wait until playing
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
                self.position_on_monitor2()
            print(f"Fullscreen set to {self.fullscreen_enabled}")

    def run(self):
        self.play_video(self.index)
        while self.running:
            state = self.player.get_state()
            if state == vlc.State.Ended:
                self.next_video()
            time.sleep(0.5)

def listen_keys(controller):
    keyboard.add_hotkey('right', lambda: controller.next_video())
    keyboard.add_hotkey('left', lambda: controller.prev_video())
    keyboard.add_hotkey('esc', lambda: controller.stop())
    keyboard.add_hotkey('up', lambda: controller.volume_up())
    keyboard.add_hotkey('down', lambda: controller.volume_down())
    keyboard.add_hotkey('f', lambda: controller.toggle_fullscreen())
    keyboard.wait('esc')

def select_folder_and_play():
    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="Select Folder Containing Videos")
    if not folder:
        print("No folder selected.")
        return

    videos = gather_videos(folder)
    if not videos:
        print("No videos found.")
        return

    controller = VLCPlayerController(videos)

    player_thread = threading.Thread(target=controller.run, daemon=True)
    player_thread.start()

    listen_keys(controller)

    print("Exiting player...")

if __name__ == "__main__":
    select_folder_and_play()
