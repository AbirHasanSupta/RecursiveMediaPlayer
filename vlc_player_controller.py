import os
import time

import vlc
import threading
from screeninfo import get_monitors
from datetime import datetime
from pathlib import Path
from key_press import cleanup_hotkeys
import win32clipboard as wcb
import win32con
import struct


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
    def __init__(self, videos, logger=None):
        self.monitor_info = MonitorInfo()
        x, y, width, height = self.monitor_info.monitor1

        self.instance = vlc.Instance(f'--video-x={x}', f'--video-y={y}')
        self.player = self.instance.media_player_new()
        self.volume = 50
        try:
            self.player.audio_set_mute(False)
            self.player.audio_set_volume(self.volume)
        except Exception:
            pass
        self.videos = videos
        self.index = 0
        self.lock = threading.Lock()
        self.running = True
        self.fullscreen_enabled = False
        self.current_monitor = 1
        self.logger = logger
        self.initial_playback_rate = 1.0

    def set_initial_playback_rate(self, rate):
        self.initial_playback_rate = rate

    def _play_video(self, media):
        self.player.set_media(media)
        try:
            self.player.audio_set_mute(False)
        except Exception:
            pass
        self.player.play()
        try:
            self.player.audio_set_volume(self.volume)
        except Exception:
            pass

        state = self.player.get_state()
        while state != vlc.State.Playing and self.running:
            time.sleep(0.1)
            state = self.player.get_state()

        try:
            self.player.audio_set_mute(False)
            self.player.audio_set_volume(self.volume)
            try:
                track_count = self.player.audio_get_track_count()
                if track_count and track_count > 0:
                    current_track = self.player.audio_get_track()
                    if current_track == -1:
                        self.player.audio_set_track(1)
            except Exception:
                pass

            if hasattr(self, 'initial_playback_rate') and self.initial_playback_rate != 1.0:
                self.player.set_rate(self.initial_playback_rate)

        except Exception:
            pass

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
            cleanup_hotkeys()

    def volume_up(self):
        with self.lock:
            self.volume = min(100, self.volume + 10)
            self.player.audio_set_volume(self.volume)
            if self.logger:
                self.logger(f"Volume set to: {self.volume}")

    def volume_down(self):
        with self.lock:
            self.volume = max(0, self.volume - 10)
            self.player.audio_set_volume(self.volume)
            if self.logger:
                self.logger(f"Volume set to: {self.volume}")

    def toggle_fullscreen(self):
        with self.lock:
            self.fullscreen_enabled = not self.fullscreen_enabled
            self.player.set_fullscreen(self.fullscreen_enabled)

            if self.logger:
                self.logger(f"Fullscreen Mode is {'On' if self.fullscreen_enabled else 'Off'}")

    def toggle_pause(self):
        with self.lock:
            if self.player.is_playing():
                self.player.pause()
                if self.logger:
                    self.logger("Video Paused")
            else:
                self.player.play()
                if self.logger:
                    self.logger("Video Resumed")

    def fast_forward(self):
        with self.lock:
            current_time = self.player.get_time()
            new_time = current_time + 200
            length = self.player.get_length()
            if 0 < length < new_time:
                new_time = length - 20
            self.player.set_time(new_time)
            if self.logger:
                self.logger(f"Fast forward to {new_time / 1000:.1f}s")

    def rewind(self):
        with self.lock:
            current_time = self.player.get_time()
            new_time = max(0, current_time - 200)
            self.player.set_time(new_time)
            if self.logger:
                self.logger(f"Rewind to {new_time / 1000:.1f}s")

    def set_playback_rate(self, rate):
        with self.lock:
            try:
                self.player.set_rate(rate)
                self.initial_playback_rate = rate
                if self.logger:
                    self.logger(f"Playback rate set to {rate}x")
            except Exception as e:
                if self.logger:
                    self.logger(f"Error setting playback rate: {e}")

    def increase_speed(self):
        with self.lock:
            current_rate = self.player.get_rate()
            new_rate = min(2.0, round((current_rate + 0.25) * 4) / 4)
            self.player.set_rate(new_rate)
            if self.logger:
                self.logger(f"Speed increased to {new_rate}×")

    def decrease_speed(self):
        with self.lock:
            current_rate = self.player.get_rate()
            new_rate = max(0.25, round((current_rate - 0.25) * 4) / 4)
            self.player.set_rate(new_rate)
            if self.logger:
                self.logger(f"Speed decreased to {new_rate}×")

    def reset_speed_hotkey(self):
        with self.lock:
            self.player.set_rate(1.0)
            if self.logger:
                self.logger("Speed reset to 1.0×")

    def run(self):
        self.play_video(self.index)
        while self.running:
            state = self.player.get_state()
            if state == vlc.State.Ended:
                self.next_video()

    def switch_to_monitor(self, monitor_number):
        with self.lock:
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
            try:
                self.player.audio_set_mute(False)
                self.player.audio_set_volume(self.volume)
            except Exception:
                pass
            self.current_monitor = monitor_number

            if current_media:
                self.player.set_media(current_media)
                self.player.play()
                try:
                    self.player.audio_set_mute(False)
                    self.player.audio_set_volume(self.volume)
                except Exception:
                    pass
                self.player.set_time(current_position)
                if self.fullscreen_enabled:
                    self.player.set_fullscreen(True)

                if not was_playing:
                    time.sleep(0.02)
                    self.player.pause()

            if self.logger:
                self.logger(f"Switched to monitor {monitor_number}")

    def take_screenshot(self):
        with self.lock:
            try:
                current_video = self.videos[self.index]
                video_dir = Path.home() / "Documents" / "Recursive Media Player" / "Screenshots"
                video_dir.mkdir(parents=True, exist_ok=True)

                video_name = os.path.splitext(os.path.basename(current_video))[0]

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_filename = f"{video_name}_screenshot_{timestamp}.png"
                screenshot_path = video_dir / screenshot_filename

                self.player.video_take_snapshot(0, str(screenshot_path), 0, 0)
                if self.logger:
                    self.logger(f"Screenshot saved: {screenshot_path}")

            except Exception as e:
                if self.logger:
                    self.logger(f"Error taking screenshot: {e}")

    def copy_current_video(self):
        with self.lock:
            try:
                current_video = self.videos[self.index]
                file_struct = struct.pack("Iiiii", 20, 0, 0, 0, 1)
                files = (current_video + "\0").encode("utf-16le") + b"\0\0"
                data = file_struct + files

                wcb.OpenClipboard()
                wcb.EmptyClipboard()
                wcb.SetClipboardData(win32con.CF_HDROP, data)
                wcb.CloseClipboard()

                if self.logger:
                    self.logger(f"Copied to clipboard: {current_video}")

            except Exception as e:
                if self.logger:
                    self.logger(f"Error copying video: {e}")

    def stop_video(self):
        with self.lock:
            self.running = False
            self.player.stop()
            if self.logger:
                self.logger("Video player stopped")
            cleanup_hotkeys()


class VLCPlayerControllerForMultipleDirectory(BaseVLCPlayerController):
    def __init__(self, videos, video_to_dir, directories, logger=None):
        super(VLCPlayerControllerForMultipleDirectory, self).__init__(videos, logger)
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
            if self.logger:
                self.logger(f"Skipping to next directory: {next_dir}")
            self.play_video(next_index)
        else:
            if self.logger:
                self.logger("No next directory found")

    def prev_directory(self):
        prev_index = self.find_prev_directory_video()
        if prev_index is not None:
            prev_dir = self.video_to_dir[self.videos[prev_index]]
            if self.logger:
                self.logger(f"Skipping to previous directory: {prev_dir}")
            self.play_video(prev_index)
        else:
            if self.logger:
                self.logger("No previous directory found")

    def play_video(self, index):
        with self.lock:
            if index < 0 or index >= len(self.videos):
                return False
            self.index = index
            current_video = self.videos[self.index]
            current_dir = self.video_to_dir[current_video]
            if self.logger:
                self.logger(f"Playing: {os.path.basename(current_video)} from {current_dir}")

            media = self.instance.media_new(current_video)
            return self._play_video(media)
