import tkinter as tk
from tkinter import ttk
import threading
import time
from datetime import timedelta
import ctypes
import ctypes.wintypes


class VideoPositionOverlay:
    def __init__(self, controller, logger=None):
        self.controller = controller
        self.logger = logger
        self.overlay_window = None
        self.is_visible = False
        self.is_dragging = False
        self.update_timer = None
        self.position_update_timer = None
        self.position_lock_timer = None
        self.is_hovering = False
        self.last_player_hwnd = None
        self.target_x = 0
        self.target_y = 0
        self.position_locked = False

        self.bg_color = "#000000"
        self.overlay_alpha = 0.85
        self.progress_bg = "#404040"
        self.progress_fg = "#E50914"
        self.buffered_color = "#808080"
        self.text_color = "#FFFFFF"
        self.handle_color = "#FFFFFF"

    def get_vlc_window_position(self):
        """Get VLC player window position and size"""
        try:
            user32 = ctypes.windll.user32

            hwnd = user32.GetForegroundWindow()

            if not hwnd:
                hwnd = user32.FindWindowW(None, "VLC media player")

            if not hwnd:
                def enum_windows_callback(hwnd, windows):
                    if user32.IsWindowVisible(hwnd):
                        length = user32.GetWindowTextLengthW(hwnd)
                        if length > 0:
                            buff = ctypes.create_unicode_buffer(length + 1)
                            user32.GetWindowTextW(hwnd, buff, length + 1)
                            title = buff.value
                            if "vlc" in title.lower():
                                windows.append(hwnd)
                    return True

                windows = []
                EnumWindowsProc = ctypes.WINFUNCTYPE(
                    ctypes.c_bool,
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(ctypes.c_int))
                user32.EnumWindows(EnumWindowsProc(enum_windows_callback), ctypes.pointer(ctypes.c_int(0)))

                if windows:
                    hwnd = windows[0]

            if hwnd and user32.IsWindowVisible(hwnd):
                self.last_player_hwnd = hwnd
                rect = ctypes.wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))

                return {
                    'x': rect.left,
                    'y': rect.top,
                    'width': rect.right - rect.left,
                    'height': rect.bottom - rect.top,
                    'hwnd': hwnd
                }

            if self.last_player_hwnd and user32.IsWindowVisible(self.last_player_hwnd):
                rect = ctypes.wintypes.RECT()
                user32.GetWindowRect(self.last_player_hwnd, ctypes.byref(rect))
                return {
                    'x': rect.left,
                    'y': rect.top,
                    'width': rect.right - rect.left,
                    'height': rect.bottom - rect.top,
                    'hwnd': self.last_player_hwnd
                }

        except Exception as e:
            if self.logger:
                self.logger(f"Error getting VLC window: {e}")

        return None

    def get_monitor_from_position(self, x, y):
        """Determine which monitor a position is on"""
        try:
            from screeninfo import get_monitors
            monitors = get_monitors()

            for i, monitor in enumerate(monitors, 1):
                if (monitor.x <= x < monitor.x + monitor.width and
                        monitor.y <= y < monitor.y + monitor.height):
                    return i, monitor

            if monitors:
                return 1, monitors[0]
        except Exception as e:
            if self.logger:
                self.logger(f"Error detecting monitor: {e}")

        return 1, None

    def create_overlay(self):
        """Create the floating overlay window"""
        if self.overlay_window:
            return

        self.overlay_window = tk.Toplevel()
        self.overlay_window.title("Video Controls")

        self.overlay_window.overrideredirect(True)
        self.overlay_window.attributes('-topmost', True)

        try:
            self.overlay_window.attributes('-alpha', self.overlay_alpha)
        except:
            pass

        self.container = tk.Frame(
            self.overlay_window,
            bg=self.bg_color,
            padx=20,
            pady=15
        )
        self.container.pack(fill=tk.BOTH, expand=True)

        info_frame = tk.Frame(self.container, bg=self.bg_color)
        info_frame.pack(fill=tk.X, pady=(0, 10))

        self.title_label = tk.Label(
            info_frame,
            text="Video Title",
            font=("Segoe UI", 11, "bold"),
            bg=self.bg_color,
            fg=self.text_color,
            anchor='w'
        )
        self.title_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        progress_frame = tk.Frame(self.container, bg=self.bg_color)
        progress_frame.pack(fill=tk.X, pady=(0, 8))

        time_frame = tk.Frame(progress_frame, bg=self.bg_color)
        time_frame.pack(fill=tk.X, pady=(0, 5))

        self.current_time_label = tk.Label(
            time_frame,
            text="0:00",
            font=("Segoe UI", 9),
            bg=self.bg_color,
            fg=self.text_color
        )
        self.current_time_label.pack(side=tk.LEFT)

        self.duration_label = tk.Label(
            time_frame,
            text="0:00",
            font=("Segoe UI", 9),
            bg=self.bg_color,
            fg=self.text_color
        )
        self.duration_label.pack(side=tk.RIGHT)

        self.progress_canvas = tk.Canvas(
            progress_frame,
            height=8,
            bg=self.bg_color,
            highlightthickness=0,
            cursor="hand2"
        )
        self.progress_canvas.pack(fill=tk.X)

        self.progress_canvas.bind("<Button-1>", self.on_progress_click)
        self.progress_canvas.bind("<B1-Motion>", self.on_progress_drag)
        self.progress_canvas.bind("<ButtonRelease-1>", self.on_progress_release)
        self.progress_canvas.bind("<Enter>", self.on_progress_enter)
        self.progress_canvas.bind("<Leave>", self.on_progress_leave)
        self.progress_canvas.bind("<Motion>", self.on_progress_hover)
        self.progress_canvas.bind("<Configure>", lambda e: self.draw_progress())

        controls_frame = tk.Frame(self.container, bg=self.bg_color)
        controls_frame.pack(fill=tk.X)

        self.play_pause_btn = tk.Button(
            controls_frame,
            text="⏸",
            font=("Segoe UI", 14),
            bg="#303030",
            fg=self.text_color,
            activebackground="#404040",
            bd=0,
            padx=10,
            pady=5,
            cursor="hand2",
            command=self.toggle_pause
        )
        self.play_pause_btn.pack(side=tk.LEFT, padx=(0, 5))

        prev_btn = tk.Button(
            controls_frame,
            text="⏮",
            font=("Segoe UI", 12),
            bg="#303030",
            fg=self.text_color,
            activebackground="#404040",
            bd=0,
            padx=8,
            pady=5,
            cursor="hand2",
            command=self.previous_video
        )
        prev_btn.pack(side=tk.LEFT, padx=(0, 5))

        next_btn = tk.Button(
            controls_frame,
            text="⏭",
            font=("Segoe UI", 12),
            bg="#303030",
            fg=self.text_color,
            activebackground="#404040",
            bd=0,
            padx=8,
            pady=5,
            cursor="hand2",
            command=self.next_video
        )
        next_btn.pack(side=tk.LEFT, padx=(0, 5))

        volume_frame = tk.Frame(controls_frame, bg=self.bg_color)
        volume_frame.pack(side=tk.LEFT, padx=(10, 0))

        self.volume_label = tk.Label(
            volume_frame,
            text="🔊",
            font=("Segoe UI", 11),
            bg=self.bg_color,
            fg=self.text_color,
            cursor="hand2"
        )
        self.volume_label.pack(side=tk.LEFT, padx=(0, 5))
        self.volume_label.bind("<Button-1>", lambda e: self.volume_up())
        self.volume_label.bind("<Button-3>", lambda e: self.volume_down())
        self.volume_label.bind("<MouseWheel>", self.on_volume_scroll)

        self.volume_value_label = tk.Label(
            volume_frame,
            text="50%",
            font=("Segoe UI", 9),
            bg=self.bg_color,
            fg=self.text_color,
            width=4
        )
        self.volume_value_label.pack(side=tk.LEFT)

        speed_frame = tk.Frame(controls_frame, bg=self.bg_color)
        speed_frame.pack(side=tk.RIGHT)

        self.speed_label = tk.Label(
            speed_frame,
            text="1.0×",
            font=("Segoe UI", 9, "bold"),
            bg=self.bg_color,
            fg=self.text_color,
            cursor="hand2"
        )
        self.speed_label.pack(side=tk.LEFT)
        self.speed_label.bind("<Button-1>", lambda e: self.increase_speed())
        self.speed_label.bind("<Button-3>", lambda e: self.decrease_speed())
        self.speed_label.bind("<Double-Button-1>", lambda e: self.reset_speed())
        self.speed_label.bind("<MouseWheel>", self.on_speed_scroll)

        self.create_tooltip()

        self.overlay_window.withdraw()

    def create_tooltip(self):
        """Create hover tooltip for preview time"""
        self.tooltip = tk.Toplevel(self.overlay_window)
        self.tooltip.overrideredirect(True)
        self.tooltip.attributes('-topmost', True)

        try:
            self.tooltip.attributes('-alpha', 0.9)
        except:
            pass

        self.tooltip_label = tk.Label(
            self.tooltip,
            text="0:00",
            font=("Segoe UI", 9, "bold"),
            bg="#202020",
            fg=self.text_color,
            padx=8,
            pady=4
        )
        self.tooltip_label.pack()

        self.tooltip.withdraw()

    def position_window(self):
        """Position overlay in top-left of the monitor where VLC is playing"""
        if not self.overlay_window:
            return

        self.overlay_window.update_idletasks()

        overlay_width = 600
        overlay_height = self.overlay_window.winfo_reqheight()

        x = 20
        y = 20

        vlc_pos = self.get_vlc_window_position()
        if vlc_pos:
            vlc_center_x = vlc_pos['x'] + vlc_pos['width'] // 2
            vlc_center_y = vlc_pos['y'] + vlc_pos['height'] // 2

            monitor_num, monitor = self.get_monitor_from_position(vlc_center_x, vlc_center_y)

            if monitor:
                x = monitor.x + 20
                y = monitor.y + 20

        self.target_x = x
        self.target_y = y

        self.overlay_window.geometry(f"{overlay_width}x{overlay_height}+{x}+{y}")

    def lock_position(self):
        """Continuously enforce the window position"""
        if not self.is_visible or not self.overlay_window or not self.position_locked:
            return

        try:
            current_x = self.overlay_window.winfo_x()
            current_y = self.overlay_window.winfo_y()

            if abs(current_x - self.target_x) > 2 or abs(current_y - self.target_y) > 2:
                self.overlay_window.geometry(f"+{self.target_x}+{self.target_y}")
        except:
            pass

        if self.is_visible and self.position_locked:
            self.position_lock_timer = self.overlay_window.after(50, self.lock_position)

    def show(self):
        """Show the overlay"""
        if not self.overlay_window:
            self.create_overlay()

        self.is_visible = True
        self.overlay_window.deiconify()
        self.overlay_window.update()

        self.position_window()
        self.overlay_window.update()

        self.position_locked = True
        self.lock_position()

        self.update_display()
        self.start_updates()
        self.start_position_tracking()

    def hide(self):
        """Hide the overlay"""
        self.is_visible = False
        self.position_locked = False

        if self.position_lock_timer:
            try:
                self.overlay_window.after_cancel(self.position_lock_timer)
            except:
                pass
            self.position_lock_timer = None

        if self.overlay_window:
            self.overlay_window.withdraw()
        if self.tooltip:
            self.tooltip.withdraw()
        self.stop_updates()
        self.stop_position_tracking()

    def toggle(self):
        """Toggle overlay visibility"""
        if self.is_visible:
            self.hide()
        else:
            self.show()

    def update_display(self):
        """Update all display elements"""
        if not self.is_visible or not self.controller:
            return

        try:
            if self.controller.index < len(self.controller.videos):
                import os
                video_path = self.controller.videos[self.controller.index]
                video_name = os.path.basename(video_path)
                if len(video_name) > 50:
                    video_name = video_name[:47] + "..."
                self.title_label.config(text=video_name)

            if self.controller.player.is_playing():
                self.play_pause_btn.config(text="⏸")
            else:
                self.play_pause_btn.config(text="▶")

            volume = self.controller.volume
            self.volume_value_label.config(text=f"{volume}%")

            if volume == 0:
                self.volume_label.config(text="🔇")
            elif volume < 30:
                self.volume_label.config(text="🔈")
            elif volume < 70:
                self.volume_label.config(text="🔉")
            else:
                self.volume_label.config(text="🔊")

            try:
                speed = self.controller.player.get_rate()
                self.speed_label.config(text=f"{speed:.2f}×")
            except:
                pass

            self.draw_progress()

        except Exception as e:
            if self.logger:
                self.logger(f"Error updating overlay: {e}")

    def draw_progress(self):
        """Draw the progress bar"""
        if not self.progress_canvas:
            return

        try:
            self.progress_canvas.delete("all")

            canvas_width = self.progress_canvas.winfo_width()
            if canvas_width <= 1:
                return

            canvas_height = self.progress_canvas.winfo_height()

            current_time = self.controller.player.get_time()
            duration = self.controller.player.get_length()

            if duration <= 0:
                duration = 1

            self.current_time_label.config(text=self.format_time(current_time))
            self.duration_label.config(text=self.format_time(duration))

            progress = current_time / duration if duration > 0 else 0
            progress_x = int(progress * canvas_width)

            track_height = 4
            track_y = canvas_height // 2
            self.progress_canvas.create_rectangle(
                0, track_y - track_height // 2,
                canvas_width, track_y + track_height // 2,
                fill=self.progress_bg,
                outline="",
                tags="track"
            )

            if progress_x > 0:
                self.progress_canvas.create_rectangle(
                    0, track_y - track_height // 2,
                    progress_x, track_y + track_height // 2,
                    fill=self.progress_fg,
                    outline="",
                    tags="progress"
                )

            handle_radius = 6 if self.is_hovering else 4
            self.progress_canvas.create_oval(
                progress_x - handle_radius,
                track_y - handle_radius,
                progress_x + handle_radius,
                track_y + handle_radius,
                fill=self.handle_color,
                outline="",
                tags="handle"
            )

        except Exception as e:
            if self.logger:
                self.logger(f"Error drawing progress: {e}")

    def format_time(self, milliseconds):
        """Format time in MM:SS or HH:MM:SS"""
        seconds = int(milliseconds / 1000)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"

    def on_progress_click(self, event):
        """Handle progress bar click"""
        self.is_dragging = True
        self.seek_to_position(event.x)

    def on_progress_drag(self, event):
        """Handle progress bar drag"""
        if self.is_dragging:
            self.seek_to_position(event.x)

    def on_progress_release(self, event):
        """Handle progress bar release"""
        self.is_dragging = False

    def on_progress_enter(self, event):
        """Handle mouse enter progress bar"""
        self.is_hovering = True
        self.draw_progress()

    def on_progress_leave(self, event):
        """Handle mouse leave progress bar"""
        self.is_hovering = False
        self.tooltip.withdraw()
        self.draw_progress()

    def on_progress_hover(self, event):
        """Handle mouse hover on progress bar"""
        if not self.is_hovering:
            return

        try:
            canvas_width = self.progress_canvas.winfo_width()
            if canvas_width <= 1:
                return

            duration = self.controller.player.get_length()
            hover_time = int((event.x / canvas_width) * duration)

            self.tooltip_label.config(text=self.format_time(hover_time))

            x = self.progress_canvas.winfo_rootx() + event.x - 20
            y = self.progress_canvas.winfo_rooty() - 30

            self.tooltip.geometry(f"+{x}+{y}")
            self.tooltip.deiconify()

        except Exception:
            pass

    def seek_to_position(self, x):
        """Seek video to position based on x coordinate"""
        try:
            canvas_width = self.progress_canvas.winfo_width()
            if canvas_width <= 1:
                return

            progress = max(0, min(1, x / canvas_width))
            duration = self.controller.player.get_length()
            new_time = int(progress * duration)

            self.controller.player.set_time(new_time)

            self.draw_progress()

        except Exception as e:
            if self.logger:
                self.logger(f"Error seeking: {e}")

    def set_speed_from_position(self, x):
        """Set playback speed based on slider position"""
        try:
            canvas_width = self.speed_canvas.winfo_width()
            if canvas_width <= 1:
                return

            min_speed = 0.25
            max_speed = 2.0

            progress = max(0, min(1, x / canvas_width))
            new_speed = min_speed + progress * (max_speed - min_speed)

            new_speed = round(new_speed * 4) / 4
            new_speed = max(min_speed, min(max_speed, new_speed))

            self.controller.set_playback_rate(new_speed)
            self.speed_label.config(text=f"{new_speed:.2f}×")

        except Exception as e:
            if self.logger:
                self.logger(f"Error setting speed: {e}")

    def volume_up(self):
        """Increase volume"""
        if self.controller:
            self.controller.volume_up()
            self.update_display()

    def volume_down(self):
        """Decrease volume"""
        if self.controller:
            self.controller.volume_down()
            self.update_display()

    def on_volume_scroll(self, event):
        """Handle mouse wheel on volume label"""
        if event.delta > 0:
            self.volume_up()
        else:
            self.volume_down()

    def increase_speed(self):
        """Increase playback speed"""
        if self.controller:
            self.controller.increase_speed()
            self.update_display()

    def decrease_speed(self):
        """Decrease playback speed"""
        if self.controller:
            self.controller.decrease_speed()
            self.update_display()

    def reset_speed(self):
        """Reset speed to 1.0x"""
        if self.controller:
            self.controller.set_playback_rate(1.0)
            self.update_display()

    def on_speed_scroll(self, event):
        """Handle mouse wheel on speed label"""
        if event.delta > 0:
            self.increase_speed()
        else:
            self.decrease_speed()

    def toggle_pause(self):
        """Toggle play/pause"""
        if self.controller:
            self.controller.toggle_pause()
            self.update_display()

    def previous_video(self):
        """Play previous video"""
        if self.controller:
            if hasattr(self.controller, 'previous_video'):
                self.controller.previous_video()
            else:
                self.controller.prev_video()
            self.update_display()

    def next_video(self):
        """Play next video"""
        if self.controller:
            self.controller.next_video()
            self.update_display()

    def start_updates(self):
        """Start periodic updates"""
        self.stop_updates()
        self.update_loop()

    def update_loop(self):
        """Update loop for progress bar"""
        if self.is_visible and not self.is_dragging:
            if not self._is_player_active():
                self.hide()
                return
            self.update_display()

        if self.is_visible:
            self.update_timer = threading.Timer(0.5, self.update_loop)
            self.update_timer.daemon = True
            self.update_timer.start()

    def _is_player_active(self):
        """Check if the player is still active"""
        try:
            if not self.controller:
                return False
            if not hasattr(self.controller, 'running') or not self.controller.running:
                return False
            if not hasattr(self.controller, 'player') or not self.controller.player:
                return False
            return True
        except:
            return False

    def stop_updates(self):
        """Stop periodic updates"""
        if self.update_timer:
            self.update_timer.cancel()
            self.update_timer = None

    def start_position_tracking(self):
        """Start tracking VLC window position"""
        self.stop_position_tracking()
        self.position_tracking_loop()

    def position_tracking_loop(self):
        """Loop to track VLC window position and update overlay position when monitor changes"""
        if self.is_visible:
            if not self._is_player_active():
                self.hide()
                return

            vlc_pos = self.get_vlc_window_position()
            if vlc_pos:
                vlc_center_x = vlc_pos['x'] + vlc_pos['width'] // 2
                vlc_center_y = vlc_pos['y'] + vlc_pos['height'] // 2

                monitor_num, monitor = self.get_monitor_from_position(vlc_center_x, vlc_center_y)
                if monitor:
                    new_x = monitor.x + 20
                    new_y = monitor.y + 20

                    if abs(self.target_x - new_x) > 100 or abs(self.target_y - new_y) > 100:
                        self.target_x = new_x
                        self.target_y = new_y
                        try:
                            self.overlay_window.geometry(f"+{new_x}+{new_y}")
                        except:
                            pass

            self.position_update_timer = threading.Timer(1.0, self.position_tracking_loop)
            self.position_update_timer.daemon = True
            self.position_update_timer.start()

    def stop_position_tracking(self):
        """Stop tracking VLC window position"""
        if self.position_update_timer:
            self.position_update_timer.cancel()
            self.position_update_timer = None

    def cleanup(self):
        self.position_locked = False
        self.is_visible = False
        self.running = False

        if self.update_timer:
            try:
                self.update_timer.cancel()
            except:
                pass
            self.update_timer = None

        if self.position_update_timer:
            try:
                self.position_update_timer.cancel()
            except:
                pass
            self.position_update_timer = None

        if self.position_lock_timer:
            try:
                if self.overlay_window and self.overlay_window.winfo_exists():
                    self.overlay_window.after_cancel(self.position_lock_timer)
            except:
                pass
            self.position_lock_timer = None

        self.stop_updates()
        self.stop_position_tracking()

        if self.tooltip:
            try:
                self.tooltip.withdraw()
                self.tooltip.destroy()
            except:
                pass
            self.tooltip = None

        if self.overlay_window:
            try:
                self.overlay_window.withdraw()
                self.overlay_window.destroy()
            except:
                pass
            self.overlay_window = None