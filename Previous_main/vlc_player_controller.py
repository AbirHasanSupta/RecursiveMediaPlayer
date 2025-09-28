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
import tkinter as tk
from tkinter import messagebox
import threading
from enhanced_features import ResumePlaybackManager


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
        self.start_index = 0
        self.video_change_callback = None
        self.resume_manager = ResumePlaybackManager()
        self.position_save_thread = None
        self.position_save_running = False

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
            result = self._play_video(media)
            if result:
                self._notify_video_change()
            return result

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
            self.stop_position_saving()  # ADD THIS LINE

            # Clear resume position for completed videos
            if hasattr(self, 'videos') and self.index < len(self.videos):
                current_video = self.videos[self.index]
                try:
                    duration = self.player.get_length() / 1000.0
                    current_time = self.player.get_time() / 1000.0

                    # If we're near the end, clear the resume position
                    if duration > 0 and current_time > (duration * 0.95):
                        self.resume_manager.clear_resume_position(current_video)
                except:
                    pass

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
        self.play_video(self.start_index)
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

    def set_start_index(self, index):
        self.start_index = max(0, min(index, len(self.videos) - 1))

    def set_video_change_callback(self, callback):
        self.video_change_callback = callback

    def _notify_video_change(self):
        if self.video_change_callback:
            try:
                self.video_change_callback(self.index, self.videos[self.index])
            except Exception:
                pass

    def stop_video(self):
        with self.lock:
            self.running = False
            self.player.stop()
            if self.logger:
                self.logger("Video player stopped")
            cleanup_hotkeys()

    def start_position_saving(self, video_path):
        """Start periodic position saving for resume functionality"""
        # Stop previous position saving
        self.position_save_running = False
        if self.position_save_thread and self.position_save_thread.is_alive():
            self.position_save_thread.join(timeout=1.0)

        # Start new position saving
        self.position_save_running = True

        def save_position_periodically():
            save_interval = 15  # Save every 15 seconds
            last_save_time = 0

            while self.position_save_running and self.running:
                try:
                    if self.player.is_playing():
                        current_time = self.player.get_time() / 1000.0  # Convert to seconds
                        duration = self.player.get_length() / 1000.0

                        # Only save if position has changed significantly and after 30 seconds
                        if (current_time > 30 and
                                abs(current_time - last_save_time) > 10 and
                                duration > 0):
                            self.resume_manager.save_position(video_path, current_time, duration)
                            last_save_time = current_time

                    time.sleep(save_interval)

                except Exception as e:
                    if self.logger:
                        self.logger(f"Error saving position: {e}")
                    time.sleep(save_interval)

        self.position_save_thread = threading.Thread(target=save_position_periodically, daemon=True)
        self.position_save_thread.start()

    def stop_position_saving(self):
        """Stop position saving thread"""
        self.position_save_running = False


class VLCPlayerControllerForMultipleDirectory(BaseVLCPlayerController):
    def __init__(self, videos, video_to_dir, directories, logger=None):
        super(VLCPlayerControllerForMultipleDirectory, self).__init__(videos, logger)
        self.video_to_dir = video_to_dir
        self.directories = directories
        self.watch_history = None  # Will be set from main app
        self.video_start_time = None

    def set_watch_history(self, watch_history):
        """Set watch history manager"""
        self.watch_history = watch_history

    def play_video(self, index):
        with self.lock:
            if index < 0 or index >= len(self.videos):
                return False

            # Record watch history for previous video
            if hasattr(self, 'video_start_time') and self.video_start_time and self.watch_history:
                try:
                    prev_video = self.videos[self.index] if self.index < len(self.videos) else None
                    if prev_video:
                        watch_duration = time.time() - self.video_start_time
                        duration = self.player.get_length() / 1000.0 if self.player.get_length() > 0 else 0
                        completed = duration > 0 and watch_duration > (duration * 0.8)  # 80% watched = completed
                        self.watch_history.add_watch_entry(prev_video, watch_duration, completed)
                except:
                    pass

            self.index = index
            current_video = self.videos[self.index]
            self.video_start_time = time.time()

            # Check for resume position
            resume_position = self.resume_manager.get_resume_position(current_video)

            media = self.instance.media_new(current_video)
            result = self._play_video(media)

            if result:
                # Handle resume playback with better UI
                if resume_position:
                    def show_resume_dialog():
                        try:
                            root = tk.Tk()
                            root.withdraw()
                            root.lift()
                            root.attributes('-topmost', True)
                            root.after(100, root.focus_force)  # Better focus handling

                            minutes = int(resume_position // 60)
                            seconds = int(resume_position % 60)
                            time_str = f"{minutes}:{seconds:02d}"

                            video_name = os.path.basename(current_video)
                            if len(video_name) > 40:
                                video_name = video_name[:37] + "..."

                            result = messagebox.askyesno(
                                "Resume Playback",
                                f"Resume '{video_name}' from {time_str}?",
                                default='yes'
                            )
                            root.destroy()

                            if result:
                                def set_position():
                                    # Wait for video to load properly
                                    max_wait = 5
                                    wait_time = 0
                                    while wait_time < max_wait and self.running:
                                        if self.player.is_playing() and self.player.get_length() > 0:
                                            self.player.set_time(int(resume_position * 1000))
                                            if self.logger:
                                                self.logger(
                                                    f"Resumed '{os.path.basename(current_video)}' from {time_str}")
                                            break
                                        time.sleep(0.3)
                                        wait_time += 0.3

                                threading.Thread(target=set_position, daemon=True).start()
                            else:
                                self.resume_manager.clear_resume_position(current_video)

                        except Exception as e:
                            if self.logger:
                                self.logger(f"Error showing resume dialog: {e}")

                    threading.Thread(target=show_resume_dialog, daemon=True).start()

                # Start position saving and add to watch history
                self.start_position_saving(current_video)
                if self.watch_history:
                    # Don't add to history yet - wait until video actually plays
                    pass

                self._notify_video_change()

            return result

    def stop(self):
        # Record final watch entry before stopping
        if hasattr(self, 'video_start_time') and self.video_start_time and self.watch_history:
            try:
                current_video = self.videos[self.index] if self.index < len(self.videos) else None
                if current_video:
                    watch_duration = time.time() - self.video_start_time
                    duration = self.player.get_length() / 1000.0 if self.player.get_length() > 0 else 0
                    completed = duration > 0 and watch_duration > (duration * 0.8)
                    self.watch_history.add_watch_entry(current_video, watch_duration, completed)
            except:
                pass

        super().stop()  # Call parent stop method

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

