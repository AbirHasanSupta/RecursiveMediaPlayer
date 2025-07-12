import os
import time

import vlc
import threading
from screeninfo import get_monitors
from datetime import datetime



class MonitorInfo:
    def __init__(self):
        monitors = get_monitors()

        if len(monitors) >= 1:
            mon1 = monitors[0]
            self.monitor1 = (mon1.x, mon1.y, mon1.width, mon1.height)
        else:
            self.monitor1 = (0, 0, 800, 600)

        if len(monitors) >= 2:
            mon2 = monitors[1]
            self.monitor2 = (mon2.x, mon2.y, mon2.width, mon2.height)
        else:
            self.monitor2 = self.monitor1



class BaseVLCPlayerController:
    def __init__(self, videos):
        self.monitor_info = MonitorInfo()

        x, y, width, height = self.monitor_info.monitor1

        self.instance = vlc.Instance(f'--video-x={x}', f'--video-y={y}')

        self.player = self.instance.media_player_new()
        self.videos = videos
        self.index = 0
        self.volume = 50
        self.lock = threading.Lock()
        self.running = True
        self.fullscreen_enabled = False
        self.current_monitor = 1


    def _play_video(self, media):
        self.player.set_media(media)
        self.player.play()
        self.player.audio_set_volume(self.volume)

        state = self.player.get_state()
        while state != vlc.State.Playing and self.running:
            time.sleep(0.1)
            state = self.player.get_state()

        self.player.set_fullscreen(self.fullscreen_enabled)
        return True


    def play_video(self, index):
        with self.lock:
            if index < 0 or index >= len(self.videos):
                return False
            self.index = index
            media = self.instance.media_new(self.videos[self.index])
            return self._play_video(media)


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
            if 0 < length < new_time:
                new_time = length - 20
            self.player.set_time(new_time)
            print(f"Fast forward to {new_time / 20:.1f}s")


    def rewind(self):
        with self.lock:
            current_time = self.player.get_time()
            new_time = max(0, current_time - 200)
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
                x, y, height, width = self.monitor_info.monitor1
            else:
                x, y, height, width = self.monitor_info.monitor2

            self.instance = vlc.Instance(f'--video-x={x}', f'--video-y={y}')
            self.player = self.instance.media_player_new()
            self.current_monitor = monitor_number

            if current_media:
                self.player.set_media(current_media)
                self.player.play()
                self.player.set_time(current_position)

                if self.fullscreen_enabled:
                    self.player.set_fullscreen(True)

                if not was_playing:
                    time.sleep(0.02)
                    self.player.pause()

            print(f"Switched to monitor {monitor_number}")


    def take_screenshot(self):
        with self.lock:
            try:
                current_video = self.videos[self.index]
                video_dir = os.path.dirname(current_video)
                video_name = os.path.splitext(os.path.basename(current_video))[0]

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_filename = f"{video_name}_screenshot_{timestamp}.png"
                screenshot_path = os.path.join(video_dir, screenshot_filename)

                self.player.video_take_snapshot(0, screenshot_path, 0, 0)
                print(f"Screenshot saved: {screenshot_path}")

            except Exception as e:
                print(f"Error taking screenshot: {e}")



    def stop_video(self):
        with self.lock:
            self.player.stop()
            print("Video stopped")


class VLCPlayerControllerForMultipleDirectory(BaseVLCPlayerController):
    def __init__(self, videos, video_to_dir, directories):
        super(VLCPlayerControllerForMultipleDirectory, self).__init__(videos)
        self.video_to_dir = video_to_dir
        self.directories = directories


    def get_current_directory(self):
        if self.index < len(self.videos):
            return self.video_to_dir.get(self.videos[self.index])
        return None


    def find_next_directory_video(self):
        current_dir = self.get_current_directory()
        if not current_dir:
            return None
        try:
            current_dir_index = self.directories.index(current_dir)
            next_dir_index = (current_dir_index + 1) % len(self.directories)
            next_dir = self.directories[next_dir_index]

            for i, video in enumerate(self.videos):
                if self.video_to_dir[video] == next_dir:
                    return i
        except (ValueError, IndexError):
            pass
        return None


    def find_prev_directory_video(self):
        current_dir = self.get_current_directory()
        if not current_dir:
            return None
        try:
            current_dir_index = self.directories.index(current_dir)
            prev_dir_index = (current_dir_index - 1) % len(self.directories)
            prev_dir = self.directories[prev_dir_index]

            for i, video in enumerate(self.videos):
                if self.video_to_dir[video] == prev_dir:
                    return i
        except (ValueError, IndexError):
            pass
        return None


    def next_directory(self):
        next_index = self.find_next_directory_video()
        if next_index is not None:
            next_dir = self.video_to_dir[self.videos[next_index]]
            print(f"Skipping to next directory: {next_dir}")
            self.play_video(next_index)
        else:
            print("No next directory found")


    def prev_directory(self):
        prev_index = self.find_prev_directory_video()
        if prev_index is not None:
            prev_dir = self.video_to_dir[self.videos[prev_index]]
            print(f"Skipping to previous directory: {prev_dir}")
            self.play_video(prev_index)
        else:
            print("No previous directory found")


    def play_video(self, index):
        with self.lock:
            if index < 0 or index >= len(self.videos):
                return False
            self.index = index
            current_video = self.videos[self.index]
            current_dir = self.video_to_dir[current_video]
            print(f"Playing: {os.path.basename(current_video)} from {current_dir}")

            media = self.instance.media_new(current_video)
            return self._play_video(media)


