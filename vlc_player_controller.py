import os
import time
import random
import vlc
import threading
from screeninfo import get_monitors
from datetime import datetime
from pathlib import Path
from key_press import cleanup_hotkeys
import struct

from managers.resource_manager import get_resource_manager
from video_position_overlay import VideoPositionOverlay


def _get_pictures_dir():
    """Return the OS Pictures directory for saving screenshots."""
    import os, sys
    from pathlib import Path
    if os.name == "nt":
        # Windows: use SHGetKnownFolderPath if available, else fall back
        try:
            import ctypes, ctypes.wintypes
            FOLDERID_Pictures = "{33E28130-4E1E-4676-835A-98395C3BC3BB}"
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, 0x0027, None, 0, buf)
            base = Path(buf.value) if buf.value else Path.home() / "Pictures"
        except Exception:
            base = Path.home() / "Pictures"
    elif sys.platform == "darwin":
        base = Path.home() / "Pictures"
    else:
        # Linux: respect XDG
        xdg = os.environ.get("XDG_PICTURES_DIR")
        base = Path(xdg) if xdg else Path.home() / "Pictures"
    return base


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
    def __init__(self, videos, logger=None, volume=50, is_muted=False):
        self.monitor_info = MonitorInfo()
        x, y, width, height = self.monitor_info.monitor1

        self.instance = vlc.Instance(f'--video-x={x}', f'--video-y={y}')
        self.player = self.instance.media_player_new()
        self.volume = volume
        self.is_muted = is_muted
        try:
            self.player.audio_set_mute(self.is_muted)
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
        self.stop_callback = None
        self.position_overlay = None

        self._brightness = 1.0
        self._contrast = 1.0
        self._saturation = 1.0
        self._gamma = 1.0
        self._hue = 0

        self._ab_point_a = None
        self._ab_point_b = None
        self._ab_loop_active = False
        self._ab_monitor_thread = None

        self._rotation_index = 0
        self._zoom_level = 1.0
        self._aspect_ratio = None  # None = auto

        self.resource_manager = get_resource_manager()
        self._is_cleanup = False
        self._cleanup_lock = threading.RLock()
        self.resource_manager.register_vlc_instance(self.instance)

    _ROTATION_STEPS = [0, 90, 180, 270]
    _TRANSFORM_MAP = {0: "identity", 90: "90", 180: "180", 270: "270"}

    def set_aspect_ratio(self, ratio: str):
        with self.lock:
            try:
                # ratio examples: "16:9", "4:3", "21:9", "1:1", None for auto
                if ratio:
                    self.player.video_set_aspect_ratio(ratio)
                    self._aspect_ratio = ratio
                else:
                    self.player.video_set_aspect_ratio(None)
                    self.player.video_set_scale(0)
                    self._aspect_ratio = None
                if self.logger:
                    self.logger(f"Aspect ratio: {ratio or 'Auto'}")
            except Exception as e:
                if self.logger:
                    self.logger(f"Aspect ratio error: {e}")

    def set_ab_point_a(self):
        with self.lock:
            try:
                self._ab_point_a = self.player.get_time()
                self._ab_point_b = None
                self._ab_loop_active = False
                if self.logger:
                    self.logger(f"A-B Loop: Point A set at {self._ab_point_a / 1000:.1f}s")
            except Exception as e:
                if self.logger:
                    self.logger(f"A-B Loop error: {e}")

    def set_ab_point_b(self):
        with self.lock:
            try:
                if self._ab_point_a is None:
                    if self.logger:
                        self.logger("A-B Loop: Set point A first")
                    return
                b = self.player.get_time()
                if b <= self._ab_point_a:
                    if self.logger:
                        self.logger("A-B Loop: Point B must be after point A")
                    return
                self._ab_point_b = b
                self._ab_loop_active = True
                if self.logger:
                    self.logger(f"A-B Loop: Point B set at {self._ab_point_b / 1000:.1f}s — looping")
                self._start_ab_monitor()
            except Exception as e:
                if self.logger:
                    self.logger(f"A-B Loop error: {e}")

    def clear_ab_loop(self):
        with self.lock:
            self._ab_point_a = None
            self._ab_point_b = None
            self._ab_loop_active = False
            if self.logger:
                self.logger("A-B Loop cleared")

    def _start_ab_monitor(self):
        if self._ab_monitor_thread and self._ab_monitor_thread.is_alive():
            return

        def _monitor():
            while self.running and self._ab_loop_active:
                try:
                    current = self.player.get_time()
                    if (self._ab_point_b is not None and
                            current >= self._ab_point_b):
                        self.player.set_time(self._ab_point_a)
                except Exception:
                    pass
                time.sleep(0.1)

        self._ab_monitor_thread = threading.Thread(
            target=_monitor, name="ABLoopMonitor", daemon=True)
        self._ab_monitor_thread.start()


    def set_initial_playback_rate(self, rate):
        self.initial_playback_rate = rate

    def _play_video(self, media):
        self.player.set_media(media)
        try:
            self.player.audio_set_mute(self.is_muted)
        except Exception:
            pass
        self.player.play()
        try:
            if not self.is_muted:
                self.player.audio_set_volume(self.volume)
        except Exception:
            pass

        state = self.player.get_state()
        while state != vlc.State.Playing and self.running:
            time.sleep(0.1)
            state = self.player.get_state()

        try:
            self.player.audio_set_mute(self.is_muted)
            if not self.is_muted:
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

        try:
            em = self.player.event_manager()
            em.event_detach(vlc.EventType.MediaPlayerEndReached)
        except Exception:
            pass
        try:
            em = self.player.event_manager()
            em.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_vlc_stopped)
        except Exception:
            pass

        return True

    def _on_vlc_stopped(self, event):
        if not self.running:
            return
        if self._is_cleanup:
            return

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

    def set_volume_save_callback(self, callback):
        self._volume_save_callback = callback

    def _trigger_config_save(self):
        if hasattr(self, '_volume_save_callback') and self._volume_save_callback:
            try:
                self._volume_save_callback(self.volume, self.is_muted)
            except Exception:
                try:
                    self._volume_save_callback(self.volume)
                except Exception:
                    pass

    def stop(self):
        with self._cleanup_lock:
            if self._is_cleanup:
                return
            self._is_cleanup = True

        self.running = False
        self._trigger_config_save()
        self.stop_position_tracking()

        if self.position_overlay:
            try:
                self.position_overlay.cleanup()
            except Exception:
                pass
            self.position_overlay = None

        if self.player:
            try:
                media = self.player.get_media()
                if media:
                    media.release()
            except Exception:
                pass
            try:
                self.player.stop()
                time.sleep(0.2)
            except Exception:
                pass
            try:
                self.player.release()
            except Exception:
                pass
            self.player = None

        try:
            if self.instance:
                self.instance.release()
                self.instance = None
        except Exception:
            pass

        try:
            cleanup_hotkeys()
        except Exception:
            pass

        self.videos = []

        if self.stop_callback:
            try:
                self.stop_callback()
            except Exception:
                pass

    def toggle_mute(self):
        with self.lock:
            self.is_muted = not self.is_muted
            try:
                self.player.audio_set_mute(self.is_muted)
                if not self.is_muted:
                    self.player.audio_set_volume(self.volume)
                if self.logger:
                    self.logger(f"Audio {'Muted' if self.is_muted else 'Unmuted'}")
                self._trigger_config_save()
            except Exception as e:
                if self.logger:
                    self.logger(f"Error toggling mute: {e}")

    def volume_up(self):
        with self.lock:
            if self.is_muted:
                self.is_muted = False
                try:
                    self.player.audio_set_mute(False)
                    if self.logger:
                        self.logger("Audio Unmuted via Volume Up")
                except Exception:
                    pass
            self.volume = min(100, self.volume + 10)
            self.player.audio_set_volume(self.volume)
            if self.logger:
                self.logger(f"Volume set to: {self.volume}")
            self._trigger_config_save()

    def volume_down(self):
        with self.lock:
            if self.is_muted:
                self.is_muted = False
                try:
                    self.player.audio_set_mute(False)
                    if self.logger:
                        self.logger("Audio Unmuted via Volume Down")
                except Exception:
                    pass
            self.volume = max(0, self.volume - 10)
            self.player.audio_set_volume(self.volume)
            if self.logger:
                self.logger(f"Volume set to: {self.volume}")
            self._trigger_config_save()

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

    def set_resume_manager(self, resume_manager):
        self.resume_manager = resume_manager

    def check_resume_position(self, video_path: str) -> tuple:
        if not hasattr(self, 'resume_manager') or not self.resume_manager:
            return False, False

        position_data = self.resume_manager.should_resume_video(video_path)
        if position_data:
            try:
                from tkinter import messagebox
                result = messagebox.askyesno(
                    "Resume Playback",
                    f"Resume '{os.path.basename(video_path)}' from {position_data.get_position_formatted()}?\n"
                    f"({position_data.percentage:.1f}% complete)\n\n"
                    f"Yes: Resume from saved position\n"
                    f"No: Play from beginning"
                )

                if result:
                    def set_resume_position():
                        max_attempts = 50
                        attempt = 0
                        while attempt < max_attempts and self.running:
                            try:
                                if self.player.get_state() == vlc.State.Playing:
                                    self.player.set_time(position_data.position)
                                    if self.logger:
                                        self.logger(f"Resumed from {position_data.get_position_formatted()}")
                                    return
                            except:
                                pass
                            time.sleep(0.1)
                            attempt += 1

                    threading.Thread(target=set_resume_position, daemon=True).start()
                    return True, True
                else:
                    self.resume_manager.clear_video_position(video_path)
                    return True, False
            except:
                pass

        return False, False

    def start_position_tracking(self, video_path: str):
        if hasattr(self, 'resume_manager') and self.resume_manager:
            self.resume_manager.start_tracking_video(self.player, video_path)

    def stop_position_tracking(self):
        if hasattr(self, 'resume_manager') and self.resume_manager:
            self.resume_manager.stop_tracking_video()

    def run(self):
        self.play_video(self.start_index)
        while self.running:
            try:
                player = self.player  # re-fetch each iteration
                if player is None:
                    time.sleep(0.1)
                    continue
                state = player.get_state()
                if state == vlc.State.Ended:
                    self.next_video()
            except Exception:
                pass
            time.sleep(0.1)

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

            angle = self._ROTATION_STEPS[self._rotation_index]
            transform_type = self._TRANSFORM_MAP[angle]

            instance_args = [f'--video-x={x}', f'--video-y={y}']
            if transform_type != "identity":
                instance_args += [
                    '--video-filter=transform',
                    f'--transform-type={transform_type}',
                ]

            old_player = self.player
            old_instance = self.instance

            self.instance = vlc.Instance(*instance_args)
            self.player = self.instance.media_player_new()
            try:
                self.player.audio_set_mute(self.is_muted)
                if not self.is_muted:
                    self.player.audio_set_volume(self.volume)
            except Exception:
                pass
            self.current_monitor = monitor_number

            try:
                old_player.stop()
                old_player.release()
            except Exception:
                pass
            try:
                old_instance.release()
            except Exception:
                pass

            if current_media:
                self.player.set_media(current_media)
                self.player.play()
                try:
                    self.player.audio_set_mute(self.is_muted)
                    if not self.is_muted:
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

            if self.position_overlay and self.position_overlay.is_visible:
                def update_overlay_position():
                    time.sleep(0.5)
                    if self.position_overlay:
                        self.position_overlay.position_window()
                threading.Thread(target=update_overlay_position, daemon=True).start()

    def take_screenshot(self):
        with self.lock:
            try:
                current_video = self.videos[self.index]
                video_dir = _get_pictures_dir() / "Recursive Media Player" / "Screenshots"
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

                try:
                    import win32clipboard as wcb
                    import win32con
                    wcb.OpenClipboard()
                    wcb.EmptyClipboard()
                    wcb.SetClipboardData(win32con.CF_HDROP, data)
                    wcb.CloseClipboard()
                except:
                    pass

                if self.logger:
                    self.logger(f"Copied to clipboard: {current_video}")
            except Exception as e:
                if self.logger:
                    self.logger(f"Error copying video: {e}")

    def set_start_index(self, index):
        self.start_index = max(0, min(index, len(self.videos) - 1))

    def set_video_change_callback(self, callback):
        self.video_change_callback = callback

    def set_stop_callback(self, callback):
        self.stop_callback = callback

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
        if self.stop_callback:
            try:
                self.stop_callback()
            except Exception:
                pass

    def init_overlay(self):
        if not self.position_overlay:
            self.position_overlay = VideoPositionOverlay(self, self.logger)
            self.position_overlay.create_overlay()

    def toggle_overlay(self):
        if not self.position_overlay:
            self.init_overlay()
        self.position_overlay.toggle()


    def rotate_video(self, direction: str = "right"):
        with self.lock:
            if direction == "right":
                self._rotation_index = (self._rotation_index + 1) % 4
            elif direction == "left":
                self._rotation_index = (self._rotation_index - 1) % 4
            elif direction == "reset":
                self._rotation_index = 0
                self._zoom_level = 1.0

            angle = self._ROTATION_STEPS[self._rotation_index]

            if direction == "flip_h":
                transform_type = "hflip"
                label = "Flip horizontal"
            elif direction == "flip_v":
                transform_type = "vflip"
                label = "Flip vertical"
            elif direction == "reset":
                transform_type = "identity"
                label = "0° (reset)"
            else:
                transform_type = self._TRANSFORM_MAP[angle]
                label = f"{angle}°" if angle else "0° (reset)"

            current_video  = self.videos[self.index]
            snap_volume    = self.volume
            snap_muted     = self.is_muted
            snap_fullscreen = self.fullscreen_enabled

        try:
            position_ms = self.player.get_time()
            was_playing = self.player.is_playing()
            rate        = self.player.get_rate()
        except Exception:
            position_ms = 0
            was_playing = True
            rate        = 1.0

        try:
            x, y, w, h = (self.monitor_info.monitor1
                          if self.current_monitor == 1
                          else self.monitor_info.monitor2)

            instance_args = [f'--video-x={x}', f'--video-y={y}']
            if transform_type != "identity":
                instance_args += [
                    '--video-filter=transform',
                    f'--transform-type={transform_type}',
                ]
            else:
                pass

            new_instance = self.instance.__class__(*instance_args)
            new_player = new_instance.media_player_new()
            media = new_instance.media_new(current_video)

            new_player.set_media(media)
            new_player.play()

            for _ in range(60):
                if new_player.get_state() == vlc.State.Playing:
                    break
                time.sleep(0.05)

            if position_ms > 0:
                new_player.set_time(position_ms)
            new_player.set_rate(rate)
            try:
                new_player.audio_set_mute(snap_muted)
                if not snap_muted:
                    new_player.audio_set_volume(snap_volume)
            except Exception:
                pass
            if not was_playing:
                new_player.pause()
            new_player.set_fullscreen(snap_fullscreen)

            try:
                self.player.stop()
                self.player.release()
            except Exception:
                pass
            try:
                self.instance.release()
            except Exception:
                pass

            with self.lock:
                self.instance = new_instance
                self.player = new_player
            self.resource_manager.register_vlc_instance(self.instance)
        except Exception as e:
            if self.logger:
                self.logger(f"Rotation error: {e}")

    def zoom_video(self, delta: float):
        with self.lock:
            try:
                if delta == 0:
                    self._zoom_level = 1.0
                    self.player.video_set_scale(0.0)
                    return

                if self._zoom_level <= 0:
                    current = self.player.video_get_scale()
                    self._zoom_level = current if current > 0 else 1.0

                step = 0.1 * (1 if delta > 0 else -1)
                self._zoom_level = round(
                    max(0.25, min(4.0, self._zoom_level + step)), 2
                )
                self.player.video_set_scale(self._zoom_level)

            except Exception as e:
                if self.logger:
                    self.logger(f"Zoom error: {e}")

    def next_chapter(self):
        with self.lock:
            try:
                chapter_count = self.player.get_chapter_count()
                if chapter_count <= 0:
                    if self.logger:
                        self.logger("No chapters available")
                    return
                current = self.player.get_chapter()
                if current < chapter_count - 1:
                    self.player.set_chapter(current + 1)
                    if self.logger:
                        self.logger(f"Chapter {current + 2} of {chapter_count}")
                else:
                    self.next_video()
            except Exception as e:
                if self.logger:
                    self.logger(f"Chapter next error: {e}")

    def prev_chapter(self):
        with self.lock:
            try:
                chapter_count = self.player.get_chapter_count()
                if chapter_count <= 0:
                    if self.logger:
                        self.logger("No chapters available")
                    return
                current = self.player.get_chapter()
                if current > 0:
                    self.player.set_chapter(current - 1)
                    if self.logger:
                        self.logger(f"Chapter {current} of {chapter_count}")
                else:
                    self.prev_video()
            except Exception as e:
                if self.logger:
                    self.logger(f"Chapter prev error: {e}")

    def get_chapter_info(self):
        try:
            chapter_count = self.player.get_chapter_count()
            if chapter_count <= 0:
                return None
            current = self.player.get_chapter()
            return {"current": current, "total": chapter_count}
        except Exception:
            return None

    def cycle_subtitle_track(self):
        with self.lock:
            try:
                track_count = self.player.video_get_spu_count()
                if track_count <= 0:
                    if self.logger:
                        self.logger("No subtitle tracks available")
                    return
                current = self.player.video_get_spu()
                tracks = self.player.video_get_spu_description()
                track_ids = [t[0] for t in tracks] if tracks else []
                if not track_ids:
                    return
                if current == -1 or current not in track_ids:
                    self.player.video_set_spu(track_ids[0])
                    track_name = tracks[0][1].decode() if isinstance(tracks[0][1], bytes) else tracks[0][1]
                    if self.logger:
                        self.logger(f"Subtitles: {track_name}")
                else:
                    idx = track_ids.index(current)
                    next_idx = (idx + 1) % len(track_ids)
                    next_id = track_ids[next_idx]
                    self.player.video_set_spu(next_id)
                    track_name = tracks[next_idx][1].decode() if isinstance(tracks[next_idx][1], bytes) else tracks[next_idx][1]
                    if self.logger:
                        self.logger(f"Subtitles: {track_name}")
            except Exception as e:
                if self.logger:
                    self.logger(f"Subtitle error: {e}")

    def disable_subtitles(self):
        with self.lock:
            try:
                self.player.video_set_spu(-1)
                if self.logger:
                    self.logger("Subtitles disabled")
            except Exception as e:
                if self.logger:
                    self.logger(f"Subtitle disable error: {e}")

    def load_subtitle_file(self, path: str):
        with self.lock:
            try:
                result = self.player.add_slave(vlc.MediaSlaveType.subtitle, path, True)
                if result == 0:
                    if self.logger:
                        self.logger(f"Subtitle file loaded: {os.path.basename(path)}")
                else:
                    if self.logger:
                        self.logger(f"Failed to load subtitle file: {os.path.basename(path)}")
            except Exception as e:
                if self.logger:
                    self.logger(f"Subtitle load error: {e}")

    def _enable_adjust(self):
        try:
            self.player.video_set_adjust_int(vlc.VideoAdjustOption.Enable, 1)
        except Exception:
            pass

    def set_brightness(self, value: float):
        self._brightness = round(max(0.0, min(2.0, value)), 2)
        self._enable_adjust()
        try:
            self.player.video_set_adjust_float(vlc.VideoAdjustOption.Brightness, self._brightness)
        except Exception:
            pass

    def set_contrast(self, value: float):
        self._contrast = round(max(0.0, min(2.0, value)), 2)
        self._enable_adjust()
        try:
            self.player.video_set_adjust_float(vlc.VideoAdjustOption.Contrast, self._contrast)
        except Exception:
            pass

    def set_saturation(self, value: float):
        self._saturation = round(max(0.0, min(3.0, value)), 2)
        self._enable_adjust()
        try:
            self.player.video_set_adjust_float(vlc.VideoAdjustOption.Saturation, self._saturation)
        except Exception:
            pass

    def set_gamma(self, value: float):
        self._gamma = round(max(0.01, min(10.0, value)), 2)
        self._enable_adjust()
        try:
            self.player.video_set_adjust_float(vlc.VideoAdjustOption.Gamma, self._gamma)
        except Exception:
            pass

    def reset_video_adjustments(self):
        self._brightness = 1.0
        self._contrast = 1.0
        self._saturation = 1.0
        self._gamma = 1.0
        try:
            self.player.video_set_adjust_int(vlc.VideoAdjustOption.Enable, 0)
        except Exception:
            pass


class VLCPlayerControllerForMultipleDirectory(BaseVLCPlayerController):
    def __init__(self, videos, video_to_dir, directories, logger=None, volume=50, is_muted=False):
        super(VLCPlayerControllerForMultipleDirectory, self).__init__(videos, logger, volume, is_muted)
        self.video_to_dir = video_to_dir
        self.directories = directories
        self.watch_history_callback = None
        self.loop_mode = "loop_on"
        self.original_video_order = videos.copy()
        self.played_indices = set()

    def set_watch_history_callback(self, callback):
        self.watch_history_callback = callback

    def _track_video_playback(self, video_path):
        if self.watch_history_callback:
            try:
                duration_watched = 0
                total_duration = 0
                try:
                    duration_watched = int(self.player.get_time() / 1000)
                    total_duration = int(self.player.get_length() / 1000)
                except:
                    pass
                self.watch_history_callback(video_path, duration_watched, total_duration)
            except Exception:
                pass

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

            self.stop_position_tracking()

            self._rotation_index = 0
            self._zoom_level = 1.0

            self.index = index
            current_video = self.videos[self.index]
            current_dir = os.path.normpath(self.video_to_dir[current_video])

            if self.logger:
                self.logger(f"Playing: {os.path.basename(current_video)} from {current_dir}")

            media = self.instance.media_new(current_video)
            resume_video, resume_position = self.check_resume_position(current_video)

            result = self._play_video(media)
            if result:
                self.start_position_tracking(current_video)
                self._notify_video_change()
            return result

    def set_loop_mode(self, mode):
        self.loop_mode = mode
        if mode == "shuffle" and not hasattr(self, 'played_indices'):
            self.played_indices = set()

    def next_video(self):
        if self.index < len(self.videos):
            current_video = self.videos[self.index]
            self._track_video_playback(current_video)

        if hasattr(self, 'queue_manager') and self.queue_manager:
            current_video = self.videos[self.index]
            queue_current = self.queue_manager.get_current_video()

            if queue_current and os.path.normpath(current_video) == os.path.normpath(queue_current):
                next_video_path = self.queue_manager.advance_queue()

                if hasattr(self, 'queue_ui_refresh_callback') and self.queue_ui_refresh_callback:
                    try:
                        self.queue_ui_refresh_callback()
                    except Exception:
                        pass

                if next_video_path and os.path.isfile(next_video_path):
                    try:
                        next_index = self.videos.index(next_video_path)
                        self.play_video(next_index)
                        if self.logger:
                            self.logger(f"Playing next from queue: {os.path.basename(next_video_path)}")
                        return
                    except ValueError:
                        pass
                elif next_video_path is None:
                    if self.logger:
                        self.logger("Reached end of queue")
                    self.player.pause()
                    return

        if self.loop_mode == "shuffle":
            self._next_video_shuffle()
        elif self.loop_mode == "loop_off":
            self._next_video_no_loop()
        else:
            self._next_video_loop()

    def _next_video_loop(self):
        self.index = (self.index + 1) % len(self.videos)
        self.play_video(self.index)

    def _next_video_no_loop(self):
        if self.index < len(self.videos) - 1:
            self.index += 1
            self.play_video(self.index)
        else:
            self.player.pause()
            self.running = False
            if self.stop_callback:
                try:
                    self.stop_callback()
                except Exception:
                    pass

    def _next_video_shuffle(self):
        self.played_indices.add(self.index)
        unplayed = [i for i in range(len(self.videos)) if i not in self.played_indices]
        if not unplayed:
            self.played_indices.clear()
            self.player.pause()
            self.running = False
            if self.stop_callback:
                try:
                    self.stop_callback()
                except Exception:
                    pass
            return
        self.index = random.choice(unplayed)
        self.play_video(self.index)

    def previous_video(self):
        if self.loop_mode == "shuffle":
            self._next_video_shuffle()
        else:
            self.index = (self.index - 1) % len(self.videos)
            self.play_video(self.index)

    def set_queue_manager(self, queue_manager):
        self.queue_manager = queue_manager

    def set_queue_ui_refresh_callback(self, callback):
        self.queue_ui_refresh_callback = callback

    def play_video_by_path(self, video_path):
        try:
            index = self.videos.index(video_path)
            self.play_video(index)
            return True
        except ValueError:
            if self.logger:
                self.logger(f"Video not found in playlist: {os.path.basename(video_path)}")
            return False

    def cleanup(self):
        self.stop_position_tracking()

        if hasattr(self, 'video_to_dir'):
            self.video_to_dir.clear()
        if hasattr(self, 'directories'):
            self.directories.clear()
        if hasattr(self, 'original_video_order'):
            self.original_video_order.clear()
        if hasattr(self, 'played_indices'):
            self.played_indices.clear()

        self.watch_history_callback = None
        self.queue_manager = None
        self.queue_ui_refresh_callback = None

        self.stop()