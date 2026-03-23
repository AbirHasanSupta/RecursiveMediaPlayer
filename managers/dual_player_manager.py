import os
import time
import random
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.font import Font
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, List
import vlc


def _embed(player: vlc.MediaPlayer, canvas: tk.Canvas):
    """Attach a VLC MediaPlayer to a tk Canvas."""
    canvas.update_idletasks()
    wid = canvas.winfo_id()
    if os.name == 'nt':
        player.set_hwnd(wid)
    else:
        player.set_xwindow(wid)


def _fmt_time(ms: int) -> str:
    s = int(ms / 1000)
    return f"{s // 60}:{s % 60:02d}"


# ---------------------------------------------------------------------------
# DualPlayerSlot
# ---------------------------------------------------------------------------

class DualPlayerSlot:
    SPEED_MIN = 0.25
    SPEED_MAX = 2.0

    def __init__(self, parent_frame: tk.Frame, slot_id: int,
                 theme_provider, logger: Callable = None):
        self.parent_frame = parent_frame
        self.slot_id = slot_id
        self.theme = theme_provider
        self.logger = logger

        # VLC state
        self.instance: Optional[vlc.Instance] = None
        self.player:   Optional[vlc.MediaPlayer] = None

        self.videos:    List[str] = []
        self.index:     int  = 0
        self.running:   bool = False
        self.volume:    int  = 50
        self.is_muted:  bool = False
        self.speed:     float = 1.0
        self.loop_mode: str  = "loop_on"

        # misc
        self._poll_job = None
        self._vol_updating = False   # re-entrancy guard for volume slider

        self.on_video_changed:       Optional[Callable] = None
        self.watch_history_callback: Optional[Callable] = None

        self._build_ui()

    # -----------------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------------

    def _build_ui(self):
        bg     = self.theme.bg_color
        accent = self.theme.accent_color
        text_c = self.theme.text_color

        # title row
        title_row = tk.Frame(self.parent_frame, bg=bg)
        title_row.pack(fill=tk.X, padx=8, pady=(6, 0))

        tk.Label(title_row,
                 text=f"Player {self.slot_id}",
                 font=Font(family="Segoe UI", size=11, weight="bold"),
                 bg=bg, fg=accent).pack(side=tk.LEFT)

        self.status_label = tk.Label(title_row, text="No video loaded",
                                     font=Font(family="Segoe UI", size=9),
                                     bg=bg, fg="#888888")
        self.status_label.pack(side=tk.LEFT, padx=(10, 0))

        self.loop_btn = tk.Button(
            title_row, text="Loop ON",
            font=Font(family="Segoe UI", size=8),
            bg=self.theme.get_button_colors("warning")["bg"],
            fg="white", bd=0, padx=6, pady=2,
            cursor="hand2", relief=tk.FLAT,
            command=self._cycle_loop_mode)
        self.loop_btn.pack(side=tk.RIGHT, padx=(4, 0))

        # embedded video canvas
        vid_container = tk.Frame(self.parent_frame, bg="black",
                                 highlightthickness=2,
                                 highlightbackground=accent)
        vid_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self.video_canvas = tk.Canvas(vid_container, bg="black",
                                      highlightthickness=0)
        self.video_canvas.pack(fill=tk.BOTH, expand=True)

        self._no_video_label = tk.Label(
            self.video_canvas,
            text=f"Player {self.slot_id}\n\nLoad a video",
            font=Font(family="Segoe UI", size=14),
            bg="black", fg="#555555")
        self._no_video_label.place(relx=0.5, rely=0.5, anchor="center")

        # video name
        self.video_name_label = tk.Label(self.parent_frame, text="",
                                         font=Font(family="Segoe UI", size=9),
                                         bg=bg, fg=text_c, anchor="w")
        self.video_name_label.pack(fill=tk.X, padx=10)

        # seek bar
        seek_frame = tk.Frame(self.parent_frame, bg=bg)
        seek_frame.pack(fill=tk.X, padx=8, pady=(4, 0))

        self.time_label = tk.Label(seek_frame, text="0:00 / 0:00",
                                   font=Font(family="Segoe UI", size=8),
                                   bg=bg, fg="#888888")
        self.time_label.pack(side=tk.LEFT)

        self.seek_canvas = tk.Canvas(seek_frame, height=14, bg=bg,
                                     highlightthickness=0, cursor="hand2")
        self.seek_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.seek_canvas.bind("<Button-1>",   self._on_seek_click)
        self.seek_canvas.bind("<B1-Motion>",  self._on_seek_drag)
        self.seek_canvas.bind("<Configure>",  lambda e: self._draw_seek_bar())

        # playback controls
        ctrl = tk.Frame(self.parent_frame, bg=bg)
        ctrl.pack(fill=tk.X, padx=8, pady=4)

        btn_kw = dict(bg="#303030", fg="white", bd=0, padx=8, pady=4,
                      cursor="hand2", relief=tk.FLAT,
                      activebackground="#505050", activeforeground="white",
                      font=Font(family="Segoe UI", size=12))

        tk.Button(ctrl, text="Prev", command=self._prev, **btn_kw).pack(side=tk.LEFT, padx=2)
        self.play_btn = tk.Button(ctrl, text="Play", command=self._toggle_pause, **btn_kw)
        self.play_btn.pack(side=tk.LEFT, padx=2)
        tk.Button(ctrl, text="Next", command=self._next, **btn_kw).pack(side=tk.LEFT, padx=2)
        tk.Button(ctrl, text="Stop", command=self._stop_playback, **btn_kw).pack(side=tk.LEFT, padx=2)

        # MUTE button
        self.mute_btn = tk.Button(ctrl, text="Mute", command=self._toggle_mute, **btn_kw)
        self.mute_btn.pack(side=tk.LEFT, padx=(10, 2))

        # VOLUME slider - plain tk.Scale, command= receives the string value
        # _vol_updating flag prevents the callback firing on programmatic .set()
        self.vol_scale = tk.Scale(
            ctrl, from_=0, to=100, orient=tk.HORIZONTAL,
            length=80, showvalue=False,
            bg=bg, fg=text_c, troughcolor="#404040",
            highlightthickness=0, bd=0,
            command=self._on_vol_scale)
        self.vol_scale.set(self.volume)
        self.vol_scale.pack(side=tk.LEFT, padx=2)

        self.vol_label = tk.Label(ctrl, text=f"{self.volume}%",
                                  font=Font(family="Segoe UI", size=8),
                                  bg=bg, fg=text_c, width=4)
        self.vol_label.pack(side=tk.LEFT)

        # SPEED slider  (25-200 represents 0.25x-2.00x)
        tk.Label(ctrl, text="  Speed:",
                 font=Font(family="Segoe UI", size=8),
                 bg=bg, fg=text_c).pack(side=tk.LEFT)

        self.spd_scale = tk.Scale(
            ctrl, from_=25, to=200, orient=tk.HORIZONTAL,
            length=70, showvalue=False,
            bg=bg, fg=text_c, troughcolor="#404040",
            highlightthickness=0, bd=0,
            command=self._on_spd_scale)
        self.spd_scale.set(100)
        self.spd_scale.pack(side=tk.LEFT, padx=2)

        self.spd_label = tk.Label(ctrl, text="1.00x",
                                  font=Font(family="Segoe UI", size=8),
                                  bg=bg, fg=accent, width=5)
        self.spd_label.pack(side=tk.LEFT)

        misc = tk.Frame(self.parent_frame, bg=bg)
        misc.pack(fill=tk.X, padx=8, pady=(0, 4))

        tk.Button(misc, text="Screenshot",
                  font=Font(family="Segoe UI", size=8),
                  bg=self.theme.get_button_colors("secondary")["bg"],
                  fg="white", bd=0, padx=6, pady=3,
                  cursor="hand2", relief=tk.FLAT,
                  command=self._screenshot).pack(side=tk.LEFT, padx=(0, 4))

        self.playlist_label = tk.Label(misc, text="0 videos",
                                       font=Font(family="Segoe UI", size=8),
                                       bg=bg, fg="#888888")
        self.playlist_label.pack(side=tk.RIGHT)

    # -----------------------------------------------------------------------
    # Volume  (FIX: completely isolated per-slot via tk.Scale command=)
    # -----------------------------------------------------------------------

    def _on_vol_scale(self, val_str: str):
        """Called by THIS slot's tk.Scale only - never touches the other slot."""
        if self._vol_updating:
            return
        try:
            val = int(float(val_str))
        except (ValueError, TypeError):
            return
        val = max(0, min(100, val))
        self.volume = val
        self.vol_label.config(text=f"{val}%")
        if self.player:
            try:
                self.player.audio_set_volume(val)
                # Auto-unmute if user drags volume up from zero
                if self.is_muted and val > 0:
                    self.is_muted = False
                    self.player.audio_set_mute(False)
                    self.mute_btn.config(text="Mute")
            except Exception:
                pass

    def _apply_volume(self):
        """Push stored volume/mute to VLC without triggering the slider callback."""
        if not self.player:
            return
        try:
            self.player.audio_set_mute(self.is_muted)
            if not self.is_muted:
                self.player.audio_set_volume(self.volume)
        except Exception:
            pass
        # Sync the slider without re-triggering _on_vol_scale
        self._vol_updating = True
        try:
            self.vol_scale.set(self.volume)
        finally:
            self._vol_updating = False
        self.vol_label.config(text=f"{self.volume}%")

    # -----------------------------------------------------------------------
    # Speed
    # -----------------------------------------------------------------------

    def _on_spd_scale(self, val_str: str):
        try:
            raw = int(float(val_str))
        except (ValueError, TypeError):
            return
        speed = round((raw / 100.0) * 4) / 4          # snap to 0.25 steps
        speed = max(self.SPEED_MIN, min(self.SPEED_MAX, speed))
        self.speed = speed
        self.spd_label.config(text=f"{speed:.2f}x")
        if self.player:
            try:
                self.player.set_rate(speed)
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # VLC lifecycle
    # -----------------------------------------------------------------------

    def _make_vlc_instance(self) -> vlc.Instance:
        """
        Create a fully isolated VLC instance.
        '--aout=directsound' on Windows forces each instance to open its own
        audio output stream so audio_set_volume() is per-player, not global.
        """
        args = ['--quiet', '--no-video-title-show']
        if os.name == 'nt':
            args += ['--aout=directsound']
        else:
            args += ['--aout=pulse']
        return vlc.Instance(*args)

    def _create_player(self):
        self._destroy_player()
        self.instance = self._make_vlc_instance()
        self.player   = self.instance.media_player_new()
        _embed(self.player, self.video_canvas)
        self._apply_volume()

    def _destroy_player(self):
        if self.player:
            try:
                self.player.stop()
                time.sleep(0.05)
                self.player.release()
            except Exception:
                pass
            self.player = None
        if self.instance:
            try:
                self.instance.release()
            except Exception:
                pass
            self.instance = None

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def load_videos(self, videos: List[str], start_index: int = 0):
        if not videos:
            return
        self.videos  = list(videos)
        self.index   = max(0, min(start_index, len(videos) - 1))
        self.running = True
        if not self.player:
            self._create_player()
        self._play_current()
        try:
            self._no_video_label.place_forget()
        except Exception:
            pass
        self.playlist_label.config(
            text=f"{len(videos)} video{'s' if len(videos) != 1 else ''}")
        self._start_polling()

    def load_single_video(self, path: str):
        self.load_videos([path], 0)

    def stop(self):
        self.running = False
        self._cancel_poll()

        if self.player:
            try:
                self.player.stop()
            except Exception:
                pass
        self._destroy_player()
        try:
            self.status_label.config(text="Stopped")
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Playback helpers
    # -----------------------------------------------------------------------

    def _play_current(self):
        if not self.player or not self.videos:
            return
        try:
            path  = self.videos[self.index]
            media = self.instance.media_new(path)
            self.player.set_media(media)
            self.player.play()

            # Re-apply audio & speed once VLC settles
            def _settle():
                if not self.player:
                    return
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    if self.player.get_state() == vlc.State.Playing:
                        break
                    time.sleep(0.05)
                self._apply_volume()
                try:
                    self.player.set_rate(self.speed)
                except Exception:
                    pass

            threading.Thread(target=_settle, daemon=True).start()

            name = os.path.basename(path)
            self.video_name_label.config(
                text=(name[:60] + "...") if len(name) > 60 else name)
            self.status_label.config(
                text=f"Playing ({self.index+1}/{len(self.videos)})")
            self._log(f"Player {self.slot_id}: {name}")

            if self.on_video_changed:
                try:
                    self.on_video_changed(self.index, path)
                except Exception:
                    pass
            if self.watch_history_callback and os.path.isfile(path):
                threading.Timer(2.0, lambda p=path: self._track_history(p)).start()

        except Exception as e:
            self._log(f"Player {self.slot_id} play error: {e}")

    def _track_history(self, path: str):
        if self.watch_history_callback and self.player:
            try:
                dw = int((self.player.get_time()   or 0) / 1000)
                td = int((self.player.get_length() or 0) / 1000)
                self.watch_history_callback(path, dw, td)
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # Polling
    # -----------------------------------------------------------------------

    def _start_polling(self):
        self._cancel_poll()
        self._poll()

    def _cancel_poll(self):
        if self._poll_job:
            try:
                self.parent_frame.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None

    def _poll(self):
        if not self.running:
            return
        try:
            if self.player:
                state = self.player.get_state()
                if state == vlc.State.Playing:
                    self.play_btn.config(text="Pause")
                    self.status_label.config(
                        text=f"Playing ({self.index+1}/{len(self.videos)})")
                elif state == vlc.State.Paused:
                    self.play_btn.config(text="Play")
                    self.status_label.config(text="Paused")
                elif state == vlc.State.Ended:
                    self._on_ended()
                    return
                self._draw_seek_bar()
        except Exception:
            pass
        self._poll_job = self.parent_frame.after(500, self._poll)

    def _on_ended(self):
        if not self.running:
            return
        if self.loop_mode == "loop_on":
            self.index = (self.index + 1) % len(self.videos)
            self._play_current()
        elif self.loop_mode == "loop_off":
            if self.index < len(self.videos) - 1:
                self.index += 1
                self._play_current()
            else:
                self.status_label.config(text="Finished")
                self.play_btn.config(text="Play")
                return
        else:  # shuffle
            self.index = random.randint(0, len(self.videos) - 1)
            self._play_current()
        self._poll_job = self.parent_frame.after(500, self._poll)

    # -----------------------------------------------------------------------
    # Seek bar
    # -----------------------------------------------------------------------

    def _draw_seek_bar(self):
        try:
            c = self.seek_canvas
            c.delete("all")
            w, h = c.winfo_width(), c.winfo_height()
            if w <= 1:
                return
            cy = h // 2
            c.create_rectangle(0, cy-2, w, cy+2, fill="#404040", outline="")
            cur, dur = 0, 1
            if self.player:
                cur = max(0, self.player.get_time()   or 0)
                dur = max(1, self.player.get_length() or 1)
            px = int((cur / dur) * w)
            c.create_rectangle(0, cy-2, px, cy+2,
                                fill=self.theme.accent_color, outline="")
            c.create_oval(px-5, cy-5, px+5, cy+5, fill="white", outline="")
            self.time_label.config(text=f"{_fmt_time(cur)} / {_fmt_time(dur)}")
        except Exception:
            pass

    def _seek_from_x(self, x: int):
        try:
            w = self.seek_canvas.winfo_width()
            if w <= 1 or not self.player:
                return
            frac = max(0.0, min(1.0, x / w))
            self.player.set_time(int(frac * (self.player.get_length() or 0)))
        except Exception:
            pass

    def _on_seek_click(self, e): self._seek_from_x(e.x)
    def _on_seek_drag(self,  e): self._seek_from_x(e.x)

    # -----------------------------------------------------------------------
    # Controls
    # -----------------------------------------------------------------------

    def _toggle_pause(self):
        if not self.player:
            return
        if self.player.is_playing():
            self.player.pause()
            self.play_btn.config(text="Play")
            self.status_label.config(text="Paused")
        else:
            self.player.play()
            self.play_btn.config(text="Pause")
            # Re-apply volume after resume (VLC can drift on some drivers)
            threading.Timer(0.2, self._apply_volume).start()

    def _stop_playback(self):
        if self.player:
            self.player.stop()
        self.play_btn.config(text="Play")
        self.status_label.config(text="Stopped")

    def _next(self):
        if not self.videos:
            return
        if self.player:
            self._track_history(self.videos[self.index])
        self.index = (self.index + 1) % len(self.videos)
        self._play_current()

    def _prev(self):
        if not self.videos:
            return
        self.index = (self.index - 1) % len(self.videos)
        self._play_current()

    def _toggle_mute(self):
        if not self.player:
            return
        self.is_muted = not self.is_muted
        self.player.audio_set_mute(self.is_muted)
        if not self.is_muted:
            self.player.audio_set_volume(self.volume)
        self.mute_btn.config(text="Unmute" if self.is_muted else "Mute")


    def _screenshot(self):
        if not self.player or not self.videos:
            return
        try:
            path    = self.videos[self.index]
            out_dir = Path.home() / "Documents" / "Recursive Media Player" / "Screenshots"
            out_dir.mkdir(parents=True, exist_ok=True)
            name = os.path.splitext(os.path.basename(path))[0]
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            out  = out_dir / f"P{self.slot_id}_{name}_{ts}.png"
            self.player.video_take_snapshot(0, str(out), 0, 0)
            self._log(f"Player {self.slot_id} screenshot: {out}")
        except Exception as e:
            self._log(f"Screenshot error: {e}")

    def _cycle_loop_mode(self):
        modes = ["loop_on", "loop_off", "shuffle"]
        labels = {"loop_on": "Loop ON", "loop_off": "Loop OFF", "shuffle": "Shuffle"}
        self.loop_mode = modes[(modes.index(self.loop_mode) + 1) % len(modes)]
        self.loop_btn.config(text=labels[self.loop_mode])

    def _log(self, msg: str):
        if self.logger:
            try:
                self.logger(msg)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# DualPlayerWindow
# ---------------------------------------------------------------------------

class DualPlayerWindow:

    def __init__(self, parent: tk.Tk, theme_provider,
                 logger: Callable = None,
                 watch_history_callback: Callable = None):
        self.parent   = parent
        self.theme    = theme_provider
        self.logger   = logger
        self.watch_history_callback = watch_history_callback

        self.window: Optional[tk.Toplevel] = None
        self.slot1:  Optional[DualPlayerSlot] = None
        self.slot2:  Optional[DualPlayerSlot] = None
        self._layout = "side_by_side"

    def show(self):
        if self.window and self.window.winfo_exists():
            self.window.lift()
            return
        bg = self.theme.bg_color
        self.window = tk.Toplevel(self.parent)
        self.window.title("Dual Video Player")
        self.window.geometry("1500x900")
        self.window.configure(bg=bg)
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_window()

    def _build_window(self):
        bg     = self.theme.bg_color
        accent = self.theme.accent_color

        toolbar = tk.Frame(self.window, bg=bg, pady=6)
        toolbar.pack(fill=tk.X, padx=10)

        tk.Label(toolbar, text="Dual Video Player",
                 font=Font(family="Segoe UI", size=13, weight="bold"),
                 bg=bg, fg=accent).pack(side=tk.LEFT)

        for sid in (1, 2):
            self._make_btn(
                toolbar,
                f"Load -> Player {sid}",
                lambda s=sid: self._load_videos(s),
                "primary"
            ).pack(side=tk.LEFT, padx=(16 if sid == 1 else 4, 0))

        self._make_btn(toolbar, "Pause Both",
                       self._pause_both, "secondary").pack(side=tk.LEFT, padx=4)
        self._make_btn(toolbar, "Play Both",
                       self._play_both,  "success" ).pack(side=tk.LEFT, padx=4)
        self._make_btn(toolbar, "Stop Both",
                       self._stop_both,  "danger"  ).pack(side=tk.LEFT, padx=4)

        self.layout_btn = self._make_btn(
            toolbar, "Stack View", self._toggle_layout, "secondary")
        self.layout_btn.pack(side=tk.RIGHT, padx=4)

        tk.Frame(self.window, height=1, bg="#444444").pack(fill=tk.X, padx=10)

        self.player_area = tk.Frame(self.window, bg=bg)
        self.player_area.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        self._build_player_frames()

    def _build_player_frames(self):
        bg = self.theme.bg_color
        if self.slot1:
            self.slot1.stop()
        if self.slot2:
            self.slot2.stop()
        for c in self.player_area.winfo_children():
            c.destroy()

        kw = dict(bg=bg, highlightthickness=1, highlightbackground="#555555")
        if self._layout == "side_by_side":
            f1 = tk.Frame(self.player_area, **kw)
            f1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 3))
            f2 = tk.Frame(self.player_area, **kw)
            f2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(3, 0))
        else:
            f1 = tk.Frame(self.player_area, **kw)
            f1.pack(fill=tk.BOTH, expand=True, pady=(0, 3))
            f2 = tk.Frame(self.player_area, **kw)
            f2.pack(fill=tk.BOTH, expand=True, pady=(3, 0))

        self.slot1 = DualPlayerSlot(f1, 1, self.theme, self.logger)
        self.slot2 = DualPlayerSlot(f2, 2, self.theme, self.logger)

        if self.watch_history_callback:
            self.slot1.watch_history_callback = self.watch_history_callback
            self.slot2.watch_history_callback = self.watch_history_callback

    def _load_videos(self, slot_id: int):
        answer = messagebox.askquestion(
            "Load Videos",
            "Load a directory (all videos inside)?\n\n"
            "Yes = pick a folder\nNo = pick individual video files",
            parent=self.window)
        slot = self.slot1 if slot_id == 1 else self.slot2

        if answer == "yes":
            d = filedialog.askdirectory(
                title=f"Select folder for Player {slot_id}", parent=self.window)
            if not d:
                return
            from utils import gather_videos
            videos = gather_videos(d)
            if not videos:
                messagebox.showwarning("No Videos", f"No videos found in:\n{d}",
                                       parent=self.window)
                return
            slot.load_videos(videos)
        else:
            files = filedialog.askopenfilenames(
                title=f"Select videos for Player {slot_id}",
                parent=self.window,
                filetypes=[
                    ("Video files", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.m4v *.webm"),
                    ("All files",   "*.*")])
            if not files:
                return
            slot.load_videos(list(files))

    def _pause_both(self):
        for s in (self.slot1, self.slot2):
            if s and s.player and s.player.is_playing():
                s.player.pause()
                s.play_btn.config(text="Play")

    def _play_both(self):
        for s in (self.slot1, self.slot2):
            if s and s.player and not s.player.is_playing():
                s.player.play()
                s.play_btn.config(text="Pause")

    def _stop_both(self):
        for s in (self.slot1, self.slot2):
            if s:
                s._stop_playback()

    def _toggle_layout(self):
        self._layout = "stacked" if self._layout == "side_by_side" else "side_by_side"
        self.layout_btn.config(
            text="Side by Side" if self._layout == "stacked" else "Stack View")
        v1 = (self.slot1.videos[:], self.slot1.index) if self.slot1 else ([], 0)
        v2 = (self.slot2.videos[:], self.slot2.index) if self.slot2 else ([], 0)
        self._build_player_frames()
        if v1[0]:
            self.window.after(200, lambda: self.slot1.load_videos(v1[0], v1[1]))
        if v2[0]:
            self.window.after(200, lambda: self.slot2.load_videos(v2[0], v2[1]))

    def _on_close(self):
        for s in (self.slot1, self.slot2):
            if s:
                s.stop()
        if self.window:
            try:
                self.window.destroy()
            except Exception:
                pass
        self.window = None

    def preload(self, videos1: List[str] = None, videos2: List[str] = None):
        if not self.window:
            return
        if videos1:
            self.window.after(300, lambda: self.slot1.load_videos(videos1))
        if videos2:
            self.window.after(300, lambda: self.slot2.load_videos(videos2))

    def _make_btn(self, parent, text, command, variant="primary"):
        c = self.theme.get_button_colors(variant)
        return tk.Button(parent, text=text, command=command,
                         font=Font(family="Segoe UI", size=9),
                         bg=c["bg"], fg=c["fg"],
                         activebackground=c["active"], activeforeground=c["fg"],
                         bd=0, padx=8, pady=4, cursor="hand2", relief=tk.FLAT)

    def is_open(self) -> bool:
        return bool(self.window and self.window.winfo_exists())


# ---------------------------------------------------------------------------
# Public facade
# ---------------------------------------------------------------------------

class DualPlayerManager:
    """
    Thin facade for the main application.

    Usage:
        mgr = DualPlayerManager(root, theme, logger)
        mgr.show()
        mgr.preload(videos_a, videos_b)
    """

    def __init__(self, root: tk.Tk, theme_provider,
                 logger: Callable = None,
                 watch_history_callback: Callable = None):
        self._window = DualPlayerWindow(root, theme_provider,
                                        logger, watch_history_callback)

    def show(self):
        self._window.show()

    def preload(self, videos1: List[str] = None, videos2: List[str] = None):
        self._window.preload(videos1, videos2)

    def cleanup(self):
        self._window._on_close()

    def is_open(self) -> bool:
        return self._window.is_open()