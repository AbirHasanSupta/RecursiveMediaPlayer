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
        self._mouse_poll_job = None
        self._vol_updating = False   # kept for compat; no longer used by slider

        self.on_video_changed:         Optional[Callable] = None
        self.watch_history_callback:   Optional[Callable] = None
        self.layout_toggle_callback:   Optional[Callable] = None  # set by DualPlayerWindow for slot1

        self._build_ui()

    def _build_ui(self):
        bg     = self.theme.bg_color
        accent = self.theme.accent_color
        text_c = self.theme.text_color

        # ── video container fills everything ──────────────────────────────────
        self.vid_container = tk.Frame(self.parent_frame, bg="black",
                                      highlightthickness=2,
                                      highlightbackground=accent)
        self.vid_container.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.video_canvas = tk.Canvas(self.vid_container, bg="black",
                                      highlightthickness=0)
        self.video_canvas.pack(fill=tk.BOTH, expand=True)

        self._no_video_label = tk.Label(
            self.video_canvas,
            text=f"Player {self.slot_id}\n\nLoad a video",
            font=Font(family="Segoe UI", size=14),
            bg="black", fg="#555555")
        self._no_video_label.place(relx=0.5, rely=0.5, anchor="center")

        # ── floating overlay — child of vid_container, NOT video_canvas ─────
        # VLC owns video_canvas's HWND; anything inside it gets buried.
        # vid_container is a plain tk.Frame that VLC never touches, so
        # children placed on it always render above the video surface.
        self._overlay = tk.Frame(self.vid_container, bg="#1c1c1c",
                                 highlightthickness=0)
        self._overlay_visible = False
        self._hide_job = None

        # ── shared style constants (mirror video_position_overlay.py) ─────────
        PANEL_BG    = "#1c1c1c"
        ACCENT      = self.theme.accent_color
        TEXT_DIM    = "#888888"
        TEXT_BRIGHT = "#dddddd"
        BTN_BG      = "#2e2e2e"
        BTN_HOVER   = "#555555"
        btn_kw = dict(
            bg=BTN_BG, fg="white", bd=0, padx=8, pady=3,
            cursor="hand2", relief=tk.FLAT,
            activebackground=BTN_HOVER, activeforeground="white",
            font=Font(family="Segoe UI", size=11))

        # ── top strip: video name (left) · status (right) ────────────────────
        info_row = tk.Frame(self._overlay, bg=PANEL_BG)
        info_row.pack(fill=tk.X, padx=12, pady=(8, 2))

        self.video_name_label = tk.Label(
            info_row, text="", anchor="w",
            font=Font(family="Segoe UI", size=9),
            bg=PANEL_BG, fg=TEXT_BRIGHT)
        self.video_name_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.status_label = tk.Label(
            info_row, text=f"Player {self.slot_id} · No video",
            font=Font(family="Segoe UI", size=8),
            bg=PANEL_BG, fg=TEXT_DIM)
        self.status_label.pack(side=tk.RIGHT, padx=(6, 0))

        # Loop mode button — right-aligned, subtle
        self.loop_btn = tk.Button(
            info_row, text="↺ Loop",
            font=Font(family="Segoe UI", size=7, weight="bold"),
            bg=BTN_BG, fg=ACCENT, bd=0, padx=6, pady=2,
            cursor="hand2", relief=tk.FLAT,
            activebackground=BTN_HOVER, activeforeground=ACCENT,
            command=self._cycle_loop_mode)
        self.loop_btn.pack(side=tk.RIGHT, padx=(8, 0))

        # ── seek bar row ──────────────────────────────────────────────────────
        seek_frame = tk.Frame(self._overlay, bg=PANEL_BG)
        seek_frame.pack(fill=tk.X, padx=12, pady=(2, 4))

        self.seek_canvas = tk.Canvas(
            seek_frame, height=16, bg=PANEL_BG,
            highlightthickness=0, cursor="hand2")
        self.seek_canvas.pack(fill=tk.X, expand=True)
        self.seek_canvas.bind("<Button-1>",  self._on_seek_click)
        self.seek_canvas.bind("<B1-Motion>", self._on_seek_drag)
        self.seek_canvas.bind("<Configure>", lambda e: self._draw_seek_bar())

        # ── control buttons row ───────────────────────────────────────────────
        ctrl = tk.Frame(self._overlay, bg=PANEL_BG)
        ctrl.pack(fill=tk.X, padx=12, pady=(0, 8))

        tk.Button(ctrl, text="⏮", command=self._prev,          **btn_kw).pack(side=tk.LEFT, padx=2)
        self.play_btn = tk.Button(ctrl, text="▶", command=self._toggle_pause, **btn_kw)
        self.play_btn.pack(side=tk.LEFT, padx=2)
        tk.Button(ctrl, text="⏭", command=self._next,          **btn_kw).pack(side=tk.LEFT, padx=2)
        tk.Button(ctrl, text="■", command=self._stop_playback, **btn_kw).pack(side=tk.LEFT, padx=2)

        # ── volume: mute icon + scroll-wheel + numeric label ──────────────────
        tk.Frame(ctrl, width=16, bg=PANEL_BG).pack(side=tk.LEFT)
        self.mute_btn = tk.Label(
            ctrl, text="🔊", cursor="hand2",
            font=Font(family="Segoe UI", size=11),
            bg=PANEL_BG, fg=TEXT_BRIGHT)
        self.mute_btn.pack(side=tk.LEFT, padx=(0, 2))
        self.mute_btn.bind("<Button-1>",   lambda e: self._toggle_mute())
        self.mute_btn.bind("<MouseWheel>", self._on_vol_scroll)

        self.vol_label = tk.Label(
            ctrl, text=f"{self.volume}%", width=4,
            font=Font(family="Segoe UI", size=8),
            bg=PANEL_BG, fg=TEXT_DIM)
        self.vol_label.pack(side=tk.LEFT)
        self.vol_label.bind("<MouseWheel>", self._on_vol_scroll)

        # ── speed: label scrolls, click resets ───────────────────────────────
        self.spd_label = tk.Label(
            ctrl, text="1.00×", cursor="hand2",
            font=Font(family="Segoe UI", size=8, weight="bold"),
            bg=PANEL_BG, fg=ACCENT)
        self.spd_label.pack(side=tk.RIGHT, padx=(4, 0))
        self.spd_label.bind("<MouseWheel>",      self._on_spd_scroll)
        self.spd_label.bind("<Button-1>",        lambda e: self._increase_speed())
        self.spd_label.bind("<Button-3>",        lambda e: self._decrease_speed())
        self.spd_label.bind("<Double-Button-1>", lambda e: self._reset_speed())

        tk.Label(ctrl, text="", font=Font(family="Segoe UI", size=8),
                 bg=PANEL_BG, fg=TEXT_DIM).pack(side=tk.RIGHT)

        # time label — right of Spd
        self.time_label = tk.Label(
            ctrl, text="0:00 / 0:00",
            font=Font(family="Segoe UI", size=8),
            bg=PANEL_BG, fg=TEXT_DIM)
        self.time_label.pack(side=tk.RIGHT, padx=(0, 12))

        # Stack/Side-by-side layout toggle — wired up by DualPlayerWindow for slot1 only
        self.layout_btn = tk.Button(
            ctrl, text="Stack View",
            font=Font(family="Segoe UI", size=8),
            bg=BTN_BG, fg=TEXT_DIM, bd=0, padx=6, pady=3,
            cursor="hand2", relief=tk.FLAT,
            activebackground=BTN_HOVER, activeforeground="white",
            command=self._on_layout_toggle)
        self.layout_btn.pack(side=tk.RIGHT, padx=(4, 12))

        # ── hover bindings on overlay widgets (for grace-period cancellation) ──
        for widget in [self._overlay, info_row, seek_frame, ctrl,
                       self.seek_canvas, self.video_name_label, self.status_label,
                       self.loop_btn, self.time_label, self.play_btn,
                       self.mute_btn, self.spd_label, self.vol_label, self.layout_btn]:
            widget.bind("<Enter>", self._on_hover_enter, add="+")
            widget.bind("<Leave>", self._on_hover_leave, add="+")

        # position overlay whenever the container resizes
        self.vid_container.bind("<Configure>", self._reposition_overlay, add="+")

        # hide overlay on startup
        self._overlay.place_forget()

        # poll mouse position to detect hover over the video area
        self._start_mouse_poll()

    # ── overlay show / hide ───────────────────────────────────────────────────

    def _reposition_overlay(self, event=None):
        """Keep overlay pinned to bottom of vid_container."""
        try:
            w = self.vid_container.winfo_width()
            h = self.vid_container.winfo_height()
            if w < 2 or h < 2:
                return
            oh = 120
            if self._overlay_visible:
                self._overlay.place(x=0, y=max(0, h - oh), width=w, height=oh)
                self._overlay.lift()
        except Exception:
            pass

    def _show_overlay(self):
        if self._hide_job:
            try:
                self.parent_frame.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None
        if not self._overlay_visible:
            self._overlay_visible = True
            self._reposition_overlay()
            try:
                self._overlay.lift()
            except Exception:
                pass

    def _hide_overlay(self):
        if self._hide_job:
            return
        self._hide_job = self.parent_frame.after(400, self._do_hide)

    def _do_hide(self):
        self._hide_job = None
        self._overlay_visible = False
        try:
            self._overlay.place_forget()
        except Exception:
            pass

    def _on_hover_enter(self, event=None):
        """Called when mouse enters any overlay widget — cancel pending hide."""
        self._show_overlay()

    def _on_hover_leave(self, event=None):
        """Called when mouse leaves an overlay widget — start hide timer."""
        self._hide_overlay()

    def _start_mouse_poll(self):
        """Poll mouse position every 120ms; show/hide overlay based on whether
        the cursor is inside vid_container. Works even when VLC owns the HWND."""
        self._mouse_poll_job = None
        self._do_mouse_poll()

    def _do_mouse_poll(self):
        try:
            # absolute mouse position
            mx = self.vid_container.winfo_pointerx()
            my = self.vid_container.winfo_pointery()
            # absolute position + size of the video container
            wx = self.vid_container.winfo_rootx()
            wy = self.vid_container.winfo_rooty()
            ww = self.vid_container.winfo_width()
            wh = self.vid_container.winfo_height()

            inside = (wx <= mx <= wx + ww) and (wy <= my <= wy + wh)
            if inside:
                self._show_overlay()
            else:
                # only hide if not already scheduled (avoid spamming)
                if self._overlay_visible and not self._hide_job:
                    self._hide_overlay()
        except Exception:
            pass
        # reschedule — use parent_frame so it survives canvas HWND takeover
        try:
            self._mouse_poll_job = self.parent_frame.after(120, self._do_mouse_poll)
        except Exception:
            pass


    def _on_vol_scroll(self, e):
        """Mouse-wheel on the volume icon or label — adjust by ±5."""
        step = 5 if e.delta > 0 else -5
        self.volume = max(0, min(100, self.volume + step))
        self.vol_label.config(text=f"{self.volume}%")
        if self.player:
            try:
                if self.is_muted and self.volume > 0:
                    self.is_muted = False
                    self.player.audio_set_mute(False)
                    self.mute_btn.config(text="🔊")
                self.player.audio_set_volume(self.volume)
            except Exception:
                pass
        self._update_vol_icon()

    def _update_vol_icon(self):
        vol, muted = self.volume, self.is_muted
        if muted or vol == 0:
            icon = "🔇"
        elif vol < 30:
            icon = "🔈"
        elif vol < 70:
            icon = "🔉"
        else:
            icon = "🔊"
        try:
            self.mute_btn.config(text=icon)
        except Exception:
            pass

    def _apply_volume(self):
        """Push stored volume/mute to VLC."""
        if not self.player:
            return
        try:
            self.player.audio_set_mute(self.is_muted)
            if not self.is_muted:
                self.player.audio_set_volume(self.volume)
        except Exception:
            pass
        self.vol_label.config(text=f"{self.volume}%")
        self._update_vol_icon()


    def _on_spd_scroll(self, e):
        """Mouse-wheel on speed label."""
        if e.delta > 0:
            self._increase_speed()
        else:
            self._decrease_speed()

    def _increase_speed(self):
        self.speed = min(self.SPEED_MAX, round((self.speed + 0.25) * 4) / 4)
        self._apply_speed()

    def _decrease_speed(self):
        self.speed = max(self.SPEED_MIN, round((self.speed - 0.25) * 4) / 4)
        self._apply_speed()

    def _reset_speed(self):
        self.speed = 1.0
        self._apply_speed()

    def _apply_speed(self):
        self.spd_label.config(text=f"{self.speed:.2f}×")
        if self.player:
            try:
                self.player.set_rate(self.speed)
            except Exception:
                pass

    def _make_vlc_instance(self) -> vlc.Instance:
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
        # Each slot gets its own independent aspect ratio (native/auto)
        try:
            self.player.video_set_aspect_ratio(None)
            self.player.video_set_scale(0)
        except Exception:
            pass
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

        self._start_polling()

    def load_single_video(self, path: str):
        self.load_videos([path], 0)

    def stop(self):
        self.running = False
        self._cancel_poll()

        # stop mouse-position poll
        try:
            if self._mouse_poll_job:
                self.parent_frame.after_cancel(self._mouse_poll_job)
                self._mouse_poll_job = None
        except Exception:
            pass
        if self._hide_job:
            try:
                self.parent_frame.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None

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
                # Restore native aspect ratio for this player independently
                try:
                    self.player.video_set_aspect_ratio(None)
                    self.player.video_set_scale(0)       # 0 = fit to window preserving AR
                except Exception:
                    pass

            threading.Thread(target=_settle, daemon=True).start()

            name = os.path.basename(path)
            self.video_name_label.config(
                text=(name[:55] + "...") if len(name) > 55 else name)
            self.status_label.config(
                text=f"P{self.slot_id} · {self.index+1}/{len(self.videos)}")
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
                    self.play_btn.config(text="⏸")
                    self.status_label.config(
                        text=f"P{self.slot_id} · {self.index+1}/{len(self.videos)}")
                elif state == vlc.State.Paused:
                    self.play_btn.config(text="▶")
                    self.status_label.config(text=f"P{self.slot_id} · Paused")
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
                self.status_label.config(text=f"P{self.slot_id} · Finished")
                self.play_btn.config(text="Play")
                return
        else:  # shuffle
            self.index = random.randint(0, len(self.videos) - 1)
            self._play_current()
        self._poll_job = self.parent_frame.after(500, self._poll)

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
            r = 6 if getattr(self, '_is_hovering_seek', False) else 4
            c.create_oval(px-r, cy-r, px+r, cy+r, fill="white", outline="")
            try:
                self.time_label.config(text=f"{_fmt_time(cur)} / {_fmt_time(dur)}")
            except Exception:
                pass
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

    def _toggle_pause(self):
        if not self.player:
            return
        if self.player.is_playing():
            self.player.pause()
            self.play_btn.config(text="▶")
            self.status_label.config(text=f"P{self.slot_id} · Paused")
        else:
            self.player.play()
            self.play_btn.config(text="⏸")
            threading.Timer(0.2, self._apply_volume).start()

    def _stop_playback(self):
        if self.player:
            self.player.stop()
        self.play_btn.config(text="▶")
        self.status_label.config(text=f"P{self.slot_id} · Stopped")

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
        self._update_vol_icon()

    def _cycle_loop_mode(self):
        modes  = ["loop_on", "loop_off", "shuffle"]
        labels = {"loop_on": "↺ Loop", "loop_off": "→ Once", "shuffle": "⇄ Shuffle"}
        self.loop_mode = modes[(modes.index(self.loop_mode) + 1) % len(modes)]
        self.loop_btn.config(text=labels[self.loop_mode])

    def _log(self, msg: str):
        if self.logger:
            try:
                self.logger(msg)
            except Exception:
                pass

    def _on_layout_toggle(self):
        if self.layout_toggle_callback:
            self.layout_toggle_callback()


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
        bg = self.theme.bg_color

        self.player_area = tk.Frame(self.window, bg=bg)
        self.player_area.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        self._build_player_frames()

    def _build_player_frames(self):
        bg = self.theme.bg_color

        # Snapshot old slots, cancel their polls, detach from UI — don't block
        old_slots = [s for s in (self.slot1, self.slot2) if s]
        self.slot1 = None
        self.slot2 = None
        for s in old_slots:
            try:
                s.running = False
                s._cancel_poll()
            except Exception:
                pass

        # Destroy old UI frames
        for c in self.player_area.winfo_children():
            c.destroy()

        # Release old VLC instances in background so UI never freezes
        def _release_old():
            for s in old_slots:
                try:
                    s._destroy_player()
                except Exception:
                    pass
        threading.Thread(target=_release_old, daemon=True).start()

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

        # Wire the Stack View button (lives in slot1's ctrl row) to the toggle
        self.slot1.layout_toggle_callback = self._toggle_layout
        # Keep slot2's layout button hidden — only slot1 shows it
        try:
            self.slot2.layout_btn.pack_forget()
        except Exception:
            pass

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
                s.play_btn.config(text="▶")

    def _play_both(self):
        for s in (self.slot1, self.slot2):
            if s and s.player and not s.player.is_playing():
                s.player.play()
                s.play_btn.config(text="⏸")

    def _stop_both(self):
        for s in (self.slot1, self.slot2):
            if s:
                s._stop_playback()

    def _toggle_layout(self):
        self._layout = "stacked" if self._layout == "side_by_side" else "side_by_side"
        v1 = (self.slot1.videos[:], self.slot1.index) if self.slot1 else ([], 0)
        v2 = (self.slot2.videos[:], self.slot2.index) if self.slot2 else ([], 0)
        self._build_player_frames()
        # Update the button label to reflect the current layout
        new_label = "Side by Side" if self._layout == "stacked" else "Stack View"
        try:
            self.slot1.layout_btn.config(text=new_label)
        except Exception:
            pass
        if v1[0]:
            self.window.after(200, lambda: self.slot1.load_videos(v1[0], v1[1]))
        if v2[0]:
            self.window.after(200, lambda: self.slot2.load_videos(v2[0], v2[1]))

    def _on_close(self):
        # Grab slot references and detach from UI immediately
        slots = [s for s in (self.slot1, self.slot2) if s]
        self.slot1 = None
        self.slot2 = None

        # Cancel all polling jobs so nothing touches the destroyed window
        for s in slots:
            try:
                s.running = False
                s._cancel_poll()
            except Exception:
                pass

        # Destroy the window right away — UI stays responsive
        win = self.window
        self.window = None
        if win:
            try:
                win.destroy()
            except Exception:
                pass

        # Release VLC players in the background so the UI never blocks
        def _release():
            for s in slots:
                try:
                    s._destroy_player()
                except Exception:
                    pass

        threading.Thread(target=_release, daemon=True).start()

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
                         font=Font(family="Segoe UI", size=8),
                         bg=c["bg"], fg=c["fg"],
                         activebackground=c["active"], activeforeground=c["fg"],
                         bd=0, padx=6, pady=3, cursor="hand2", relief=tk.FLAT)

    def is_open(self) -> bool:
        return bool(self.window and self.window.winfo_exists())


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