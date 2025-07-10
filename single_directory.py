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
    return ctypes.windll.user32.SetWindowPos(hwnd, 0, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE)

class VLCPlayerController:
    def __init__(self, videos):
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
        self.index = 0
        self.volume = 100
        self.lock = threading.Lock()
        self.running = True
        self.fullscreen_enabled = False
        self.current_monitor = 2

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
            media = self.instance.media_new(self.videos[self.index])
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
            new_time = current_time + 100
            length = self.player.get_length()
            if length > 0 and new_time > length:
                new_time = length - 10
            self.player.set_time(new_time)
            print(f"Fast forward to {new_time / 10:.1f}s")

    def rewind(self):
        with self.lock:
            current_time = self.player.get_time()
            new_time = max(0, current_time - 100)
            self.player.set_time(new_time)
            print(f"Rewind to {new_time / 10:.1f}s")

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
    keyboard.add_hotkey('right', lambda: controller.next_video())
    keyboard.add_hotkey('left', lambda: controller.prev_video())
    keyboard.add_hotkey('esc', lambda: controller.stop())
    keyboard.add_hotkey('up', lambda: controller.volume_up())
    keyboard.add_hotkey('down', lambda: controller.volume_down())
    keyboard.add_hotkey('f', lambda: controller.toggle_fullscreen())
    keyboard.add_hotkey('space', lambda: controller.toggle_pause())
    keyboard.add_hotkey('1', lambda: controller.switch_to_monitor(1))
    keyboard.add_hotkey('2', lambda: controller.switch_to_monitor(2))
    keyboard.add_hotkey('d', lambda: controller.fast_forward())
    keyboard.add_hotkey('a', lambda: controller.rewind())
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