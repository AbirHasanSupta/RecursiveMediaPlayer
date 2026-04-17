import os
import time
import random
import threading
import tkinter as tk
from tkinter.font import Font
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

    _ROTATION_STEPS = [0, 90, 180, 270]
    _TRANSFORM_MAP = {0: "identity", 90: "90", 180: "180", 270: "270"}

    _INACTIVITY_TIMEOUT = 2.0

    def __init__(self, parent_frame: tk.Frame, slot_id: int,
                 theme_provider, logger: Callable = None,
                 on_empty_callback: Callable = None,
                 get_other_slots_callback: Callable = None):
        self.parent_frame    = parent_frame
        self.slot_id         = slot_id
        self.theme           = theme_provider
        self.logger          = logger
        self.on_empty_callback = on_empty_callback
        # Callback: () -> dict[slot_id -> DualPlayerSlot]
        self.get_other_slots_callback = get_other_slots_callback

        # VLC state
        self.instance = None
        self.player   = None

        self.videos:    List[str] = []
        self.index:     int   = 0
        self.running:   bool  = False
        self.volume:    int   = 50
        self.is_muted:  bool  = False
        self.speed:     float = 1.0
        self.loop_mode: str   = "loop_on"
        self._rotation_index: int = 0

        self._poll_job        = None
        self._mouse_poll_job  = None
        self._last_mouse_pos  = (None, None)
        self._last_mouse_move_time = 0.0

        self.on_video_changed:       Optional[Callable] = None
        self.watch_history_callback: Optional[Callable] = None

        self._build_ui()

    def _build_ui(self):
        bg     = self.theme.bg_color
        accent = self.theme.accent_color

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

        # Floating overlay — child of vid_container, NOT video_canvas
        self._overlay = tk.Frame(self.vid_container, bg="#1c1c1c",
                                 highlightthickness=0)
        self._overlay_visible = False
        self._hide_job = None

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

        self.loop_btn = tk.Button(
            info_row, text="↺ Loop",
            font=Font(family="Segoe UI", size=7, weight="bold"),
            bg=BTN_BG, fg=ACCENT, bd=0, padx=6, pady=2,
            cursor="hand2", relief=tk.FLAT,
            activebackground=BTN_HOVER, activeforeground=ACCENT,
            command=self._cycle_loop_mode)
        self.loop_btn.pack(side=tk.RIGHT, padx=(8, 0))

        seek_frame = tk.Frame(self._overlay, bg=PANEL_BG)
        seek_frame.pack(fill=tk.X, padx=12, pady=(2, 4))

        self.seek_canvas = tk.Canvas(
            seek_frame, height=16, bg=PANEL_BG,
            highlightthickness=0, cursor="hand2")
        self.seek_canvas.pack(fill=tk.X, expand=True)
        self.seek_canvas.bind("<Button-1>",  self._on_seek_click)
        self.seek_canvas.bind("<B1-Motion>", self._on_seek_drag)
        self.seek_canvas.bind("<Configure>", lambda e: self._draw_seek_bar())

        ctrl = tk.Frame(self._overlay, bg=PANEL_BG)
        ctrl.pack(fill=tk.X, padx=12, pady=(0, 8))

        tk.Button(ctrl, text="⏮", command=self._prev,          **btn_kw).pack(side=tk.LEFT, padx=2)
        self.play_btn = tk.Button(ctrl, text="▶", command=self._toggle_pause, **btn_kw)
        self.play_btn.pack(side=tk.LEFT, padx=2)
        tk.Button(ctrl, text="⏭", command=self._next,          **btn_kw).pack(side=tk.LEFT, padx=2)
        tk.Button(ctrl, text="■", command=self._stop_playback, **btn_kw).pack(side=tk.LEFT, padx=2)

        self.rotate_btn = tk.Button(ctrl, text="⟳", command=self._rotate, **btn_kw)
        self.rotate_btn.pack(side=tk.LEFT, padx=2)

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

        # ── Swap button ────────────────────────────────────────────────────
        self.swap_btn = tk.Button(
            ctrl, text="⇄ Swap",
            font=Font(family="Segoe UI", size=9, weight="bold"),
            bg="#1a2a3a", fg="#5bc8f5", bd=0, padx=7, pady=3,
            cursor="hand2", relief=tk.FLAT,
            activebackground="#2a4a6a", activeforeground="#8de0ff",
            command=self._show_swap_menu)
        self.swap_btn.pack(side=tk.LEFT, padx=(6, 2))
        # ──────────────────────────────────────────────────────────────────

        eject_btn = tk.Button(ctrl, text="✕ Close",
                              font=Font(family="Segoe UI", size=8),
                              bg="#3a1a1a", fg="#ff6666", bd=0, padx=6, pady=3,
                              cursor="hand2", relief=tk.FLAT,
                              activebackground="#551111", activeforeground="#ff9999",
                              command=self._eject)
        eject_btn.pack(side=tk.LEFT, padx=(8, 0))

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

        self.time_label = tk.Label(
            ctrl, text="0:00 / 0:00",
            font=Font(family="Segoe UI", size=8),
            bg=PANEL_BG, fg=TEXT_DIM)
        self.time_label.pack(side=tk.RIGHT, padx=(0, 12))

        # Hover bindings for grace-period cancellation
        for widget in [self._overlay, info_row, seek_frame, ctrl,
                       self.seek_canvas, self.video_name_label, self.status_label,
                       self.loop_btn, self.swap_btn, self.time_label, self.play_btn,
                       self.mute_btn, self.spd_label, self.vol_label,
                       self.rotate_btn]:
            widget.bind("<Enter>", self._on_hover_enter, add="+")
            widget.bind("<Leave>", self._on_hover_leave, add="+")

        self.vid_container.bind("<Configure>", self._reposition_overlay, add="+")

        self._overlay.place_forget()
        self._start_mouse_poll()

    # ── swap logic ────────────────────────────────────────────────────────────

    def _show_swap_menu(self):
        """Show a popup menu listing other active players in this window to swap with."""
        if not self.get_other_slots_callback:
            return

        all_slots = self.get_other_slots_callback()
        other_slots = {sid: s for sid, s in all_slots.items() if sid != self.slot_id}

        if not other_slots:
            self.swap_btn.config(fg="#ff9966")
            self.parent_frame.after(600, lambda: self.swap_btn.config(fg="#5bc8f5"))
            return

        menu = tk.Menu(self.parent_frame, tearoff=0,
                       bg="#1c1c1c", fg="white",
                       activebackground="#2a4a6a", activeforeground="#8de0ff",
                       font=Font(family="Segoe UI", size=9))

        for sid, slot in sorted(other_slots.items()):
            vid_count = len(slot.videos)
            my_count  = len(self.videos)
            label = (
                f"↔  Swap with Player {sid}  "
                f"({my_count} vid{'s' if my_count != 1 else ''} → "
                f"{vid_count} vid{'s' if vid_count != 1 else ''})"
            )
            menu.add_command(
                label=label,
                command=lambda target=slot: self._do_swap(target))

        try:
            x = self.swap_btn.winfo_rootx()
            y = self.swap_btn.winfo_rooty() - 4
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _do_swap(self, other: 'DualPlayerSlot'):
        """
        Exchange the complete playlist state between self and other.
        Each player resumes at the same seek position it was at before the swap.
        """
        self_pos  = 0
        other_pos = 0
        if self.player:
            try:
                self_pos = max(0, self.player.get_time() or 0)
            except Exception:
                pass
        if other.player:
            try:
                other_pos = max(0, other.player.get_time() or 0)
            except Exception:
                pass

        self.videos,    other.videos    = other.videos,    self.videos
        self.index,     other.index     = other.index,     self.index
        self.loop_mode, other.loop_mode = other.loop_mode, self.loop_mode

        def _reload_slot(slot, seek_ms):
            if slot.videos:
                if not slot.player:
                    slot._create_player()
                slot.running = True
                slot._play_current()

                def _seek_after_play(s=slot, ms=seek_ms):
                    if not s.player:
                        return
                    deadline = time.time() + 4.0
                    while time.time() < deadline:
                        if s.player.get_state() == vlc.State.Playing:
                            break
                        time.sleep(0.05)
                    try:
                        if ms > 0:
                            s.player.set_time(ms)
                    except Exception:
                        pass
                    s._apply_volume()
                    try:
                        s.player.set_rate(s.speed)
                    except Exception:
                        pass

                threading.Thread(target=_seek_after_play, daemon=True).start()
                slot._start_polling()
            else:
                slot.stop()
                try:
                    slot._no_video_label.place(relx=0.5, rely=0.5, anchor="center")
                    slot.status_label.config(text=f"Player {slot.slot_id} · No video")
                    slot.video_name_label.config(text="")
                except Exception:
                    pass

        _reload_slot(self,  other_pos)
        _reload_slot(other, self_pos)

        self._log(
            f"Swapped: Player {self.slot_id} ↔ Player {other.slot_id}  "
            f"({len(self.videos)} / {len(other.videos)} videos)")

    # ── eject ─────────────────────────────────────────────────────────────────

    def _eject(self):
        self.stop()
        self.videos = []
        if self.on_empty_callback:
            try:
                self.on_empty_callback(self.slot_id)
            except Exception:
                pass

    def _reposition_overlay(self, event=None):
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
        self._show_overlay()

    def _on_hover_leave(self, event=None):
        self._hide_overlay()

    # ── mouse polling ─────────────────────────────────────────────────────────

    def _start_mouse_poll(self):
        self._mouse_poll_job = None
        self._last_mouse_pos = (None, None)
        self._last_mouse_move_time = time.monotonic()
        self._do_mouse_poll()

    def _do_mouse_poll(self):
        try:
            mx = self.vid_container.winfo_pointerx()
            my = self.vid_container.winfo_pointery()
            wx = self.vid_container.winfo_rootx()
            wy = self.vid_container.winfo_rooty()
            ww = self.vid_container.winfo_width()
            wh = self.vid_container.winfo_height()
            inside = (wx <= mx <= wx + ww) and (wy <= my <= wy + wh)
            if inside:
                if (mx, my) != self._last_mouse_pos:
                    self._last_mouse_pos = (mx, my)
                    self._last_mouse_move_time = time.monotonic()
                    self._show_overlay()
                else:
                    idle = time.monotonic() - self._last_mouse_move_time
                    if idle >= self._INACTIVITY_TIMEOUT:
                        if self._overlay_visible and not self._hide_job:
                            self._hide_overlay()
                    else:
                        if not self._overlay_visible and not self._hide_job:
                            self._show_overlay()
            else:
                if self._overlay_visible and not self._hide_job:
                    self._hide_overlay()
        except Exception:
            pass

        try:
            self._mouse_poll_job = self.parent_frame.after(120, self._do_mouse_poll)
        except Exception:
            pass

    def _on_vol_scroll(self, e):
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

    def _make_vlc_instance(self):
        try:
            args = ['--quiet', '--no-video-title-show']
            if os.name == 'nt':
                args += ['--aout=directsound']
            else:
                args += ['--aout=pulse']
            return vlc.Instance(*args)
        except Exception:
            return None

    def _create_player(self):
        self._destroy_player()
        self.instance = self._make_vlc_instance()
        if not self.instance:
            return
        try:
            self.player = self.instance.media_player_new()
            _embed(self.player, self.video_canvas)
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
                try:
                    self.player.video_set_aspect_ratio(None)
                    self.player.video_set_scale(0)
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
        else:
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

    # ── rotation ──────────────────────────────────────────────────────────────

    def _rotate(self):
        if not self.player or not self.videos:
            return
        try:
            import vlc
            self._rotation_index = (self._rotation_index + 1) % 4
            angle          = self._ROTATION_STEPS[self._rotation_index]
            transform_type = self._TRANSFORM_MAP[angle]

            position_ms = self.player.get_time() or 0
            was_playing = self.player.is_playing()
            path        = self.videos[self.index]

            base_args = ['--quiet', '--no-video-title-show']
            if os.name == 'nt':
                base_args += ['--aout=directsound']
            else:
                base_args += ['--aout=pulse']
            if transform_type != "identity":
                base_args += ['--video-filter=transform',
                              f'--transform-type={transform_type}']

            try:
                self.player.stop()
                self.player.release()
            except Exception:
                pass
            try:
                self.instance.release()
            except Exception:
                pass

            self.instance = vlc.Instance(*base_args)
            self.player   = self.instance.media_player_new()
            _embed(self.player, self.video_canvas)

            media = self.instance.media_new(path)
            self.player.set_media(media)
            self.player.play()

            def _settle():
                if not self.player:
                    return
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    if self.player.get_state() == vlc.State.Playing:
                        break
                    time.sleep(0.05)
                try:
                    if position_ms > 0:
                        self.player.set_time(position_ms)
                    self.player.set_rate(self.speed)
                    self._apply_volume()
                    if not was_playing:
                        self.player.pause()
                except Exception:
                    pass

            threading.Thread(target=_settle, daemon=True).start()
        except Exception as e:
            self._log(f"Player {self.slot_id} rotate error: {e}")

    def _log(self, msg: str):
        if self.logger:
            try:
                self.logger(msg)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# DualPlayerWindow — one independent Toplevel housing up to 3 slots
# ---------------------------------------------------------------------------

class DualPlayerWindow:
    """
    One independent player window that houses 1-3 side-by-side slot panes.
    Two instances can be sent to two separate monitors.
    """

    MAX_SLOTS = 3

    def __init__(self, parent: tk.Tk, win_id: int, theme_provider,
                 logger: Callable = None,
                 watch_history_callback: Callable = None,
                 player_count: int = 2):
        self.parent                  = parent
        self.win_id                  = win_id       # 1 or 2
        self.theme                   = theme_provider
        self.logger                  = logger
        self.watch_history_callback  = watch_history_callback
        self.player_count            = max(2, min(3, player_count))

        self._slots: dict            = {}           # slot_id -> DualPlayerSlot
        self._slot_frames: dict      = {}           # slot_id -> tk.Frame

        self.window: Optional[tk.Toplevel] = None
        self._player_area: Optional[tk.Frame] = None
        self._placeholder: Optional[tk.Frame] = None

    # ── public ────────────────────────────────────────────────────────────────

    def show(self):
        if self.window and self.window.winfo_exists():
            self.window.lift()
            return
        self._build_window()

    def get_slot(self, slot_id: int) -> Optional[DualPlayerSlot]:
        return self._slots.get(slot_id)

    def get_or_create_slot(self, slot_id: int) -> DualPlayerSlot:
        self.show()
        if slot_id not in self._slots:
            self._add_slot(slot_id)
        return self._slots[slot_id]

    def set_player_count(self, count: int):
        self.player_count = max(2, min(3, count))

    def is_open(self) -> bool:
        return bool(self.window and self.window.winfo_exists())

    # ── window build ──────────────────────────────────────────────────────────

    def _build_window(self):
        bg = self.theme.bg_color
        self.window = tk.Toplevel(self.parent)
        self.window.title(f"Video Player — Window {self.win_id}")
        self.window.geometry("1200x700")
        self.window.configure(bg=bg)
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        self._borderless = False
        self.window.bind("<F>",      lambda e: self._toggle_borderless())
        self.window.bind("<Escape>", lambda e: self._exit_borderless())

        self._player_area = tk.Frame(self.window, bg=bg)
        self._player_area.pack(fill=tk.BOTH, expand=True)

        self._show_placeholder()

    def _toggle_borderless(self):
        self._borderless = not self._borderless
        self._apply_borderless()

    def _exit_borderless(self):
        if self._borderless:
            self._borderless = False
            self._apply_borderless()

    def _apply_borderless(self):
        if not self.window or not self.window.winfo_exists():
            return
        if self._borderless:
            self._pre_borderless_geo = self.window.geometry()
            self.window.overrideredirect(True)
            sw = self.window.winfo_screenwidth()
            sh = self.window.winfo_screenheight()
            self.window.geometry(f"{sw}x{sh}+0+0")
        else:
            self.window.overrideredirect(False)
            geo = getattr(self, '_pre_borderless_geo', "1200x700")
            self.window.geometry(geo)
        self.window.lift()
        self.window.focus_force()

    def _show_placeholder(self):
        if self._placeholder and self._placeholder.winfo_exists():
            return
        bg = self.theme.bg_color
        self._placeholder = tk.Frame(self._player_area, bg=bg)
        self._placeholder.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(
            self._placeholder,
            text=(
                f"Player Window {self.win_id} — no videos loaded yet.\n\n"
                f"Right-click a video or folder in the main window\n"
                f"and choose  ▶ Win {self.win_id} › Player 1 / 2 / 3."
            ),
            font=Font(family="Segoe UI", size=13),
            bg=bg, fg="#888888",
            justify="center").pack()

    def _hide_placeholder(self):
        if self._placeholder and self._placeholder.winfo_exists():
            try:
                self._placeholder.place_forget()
                self._placeholder.destroy()
            except Exception:
                pass
            self._placeholder = None

    # ── slot management ───────────────────────────────────────────────────────

    def _add_slot(self, slot_id: int):
        self._hide_placeholder()
        bg = self.theme.bg_color
        frame = tk.Frame(self._player_area, bg=bg,
                         highlightthickness=1,
                         highlightbackground="#555555")
        self._slot_frames[slot_id] = frame

        slot = DualPlayerSlot(
            frame, slot_id, self.theme, self.logger,
            on_empty_callback=self._on_slot_empty,
            get_other_slots_callback=lambda: dict(self._slots))
        if self.watch_history_callback:
            slot.watch_history_callback = self.watch_history_callback
        self._slots[slot_id] = slot

        self._repack_slots()
        self._update_title()

    def _remove_slot(self, slot_id: int):
        slot  = self._slots.pop(slot_id, None)
        frame = self._slot_frames.pop(slot_id, None)

        if slot:
            try:
                slot.running = False
                slot._cancel_poll()
            except Exception:
                pass
            threading.Thread(target=lambda s=slot: s._destroy_player(),
                             daemon=True).start()

        if frame:
            try:
                frame.pack_forget()
                frame.destroy()
            except Exception:
                pass

        if not self._slots:
            self._show_placeholder()

        self._repack_slots()
        self._update_title()

    def _on_slot_empty(self, slot_id: int):
        if self.window and self.window.winfo_exists():
            self.window.after(0, lambda: self._remove_slot(slot_id))

    def _repack_slots(self):
        if not self._player_area or not self._player_area.winfo_exists():
            return
        for frame in self._slot_frames.values():
            try:
                frame.pack_forget()
            except Exception:
                pass
        ordered = sorted(self._slot_frames.keys())
        n = len(ordered)
        for i, sid in enumerate(ordered):
            frame = self._slot_frames[sid]
            padx_l = 0 if i == 0     else 3
            padx_r = 0 if i == n - 1 else 3
            frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                       padx=(padx_l, padx_r))

    def _update_title(self):
        n = len(self._slots)
        if n == 0:
            title = f"Video Player — Window {self.win_id}"
        elif n == 1:
            sid = list(self._slots.keys())[0]
            title = f"Win {self.win_id} · Player {sid}"
        elif n == 2:
            title = f"Win {self.win_id} · Dual Player"
        else:
            title = f"Win {self.win_id} · Triple Player"
        try:
            if self.window:
                self.window.title(title)
        except Exception:
            pass

    # ── slot accessors ────────────────────────────────────────────────────────

    @property
    def slot1(self) -> Optional[DualPlayerSlot]:
        return self._slots.get(1)

    @property
    def slot2(self) -> Optional[DualPlayerSlot]:
        return self._slots.get(2)

    @property
    def slot3(self) -> Optional[DualPlayerSlot]:
        return self._slots.get(3)

    # ── close ─────────────────────────────────────────────────────────────────

    def _on_close(self):
        slots = list(self._slots.values())
        self._slots.clear()
        self._slot_frames.clear()

        for s in slots:
            try:
                s.running = False
                s._cancel_poll()
            except Exception:
                pass

        win = self.window
        self.window = None
        if win:
            try:
                win.destroy()
            except Exception:
                pass

        threading.Thread(
            target=lambda: [s._destroy_player() for s in slots],
            daemon=True).start()


# ---------------------------------------------------------------------------
# DualPlayerManager — manages TWO independent player windows
# ---------------------------------------------------------------------------

class DualPlayerManager:
    """
    Manages two completely independent player windows (win_id 1 and 2).

    Each window can hold up to 3 side-by-side slot panes (slot_id 1-3).
    Windows are fully independent — drag them to different monitors.

    API used by build_app.py
    ────────────────────────
    load_videos_into_slot(win_id, slot_id, videos)
        Open win_id's window (if not visible), create the slot pane
        (if not present), and load the video list into it.

    player_count                →  slots-per-window setting (2 or 3)
    set_player_count(n)         →  update for both windows
    show(win_id=1)              →  open a specific window
    cleanup()                   →  close both windows
    is_open(win_id=None)        →  True if the given (or any) window is open
    """

    NUM_WINDOWS = 2

    def __init__(self, root: tk.Tk, theme_provider,
                 logger: Callable = None,
                 watch_history_callback: Callable = None,
                 player_count: int = 2):
        self._root   = root
        self._logger = logger

        # Two independent windows keyed by win_id (1, 2)
        self._windows: dict = {
            wid: DualPlayerWindow(
                root, wid, theme_provider, logger,
                watch_history_callback, player_count)
            for wid in range(1, self.NUM_WINDOWS + 1)
        }

    # ── public API ────────────────────────────────────────────────────────────

    @property
    def player_count(self) -> int:
        return self._windows[1].player_count

    def set_player_count(self, count: int):
        for w in self._windows.values():
            w.set_player_count(count)

    def show(self, win_id: int = 1):
        """Open the given window (default: window 1)."""
        w = self._windows.get(win_id)
        if w:
            w.show()

    def load_videos_into_slot(self, win_id: int, slot_id: int,
                              videos: List[str]):
        """
        Load *videos* into slot *slot_id* of player window *win_id*.
        The window and slot pane are created on demand.
        """
        if not videos:
            return
        w = self._windows.get(win_id)
        if not w:
            return
        slot = w.get_or_create_slot(slot_id)
        self._root.after(200, lambda s=slot, v=videos: s.load_videos(v))

    def cleanup(self):
        for w in self._windows.values():
            try:
                w._on_close()
            except Exception:
                pass

    def is_open(self, win_id: int = None) -> bool:
        if win_id is not None:
            w = self._windows.get(win_id)
            return w.is_open() if w else False
        return any(w.is_open() for w in self._windows.values())

    def _get_window(self, win_id: int = 1) -> Optional[DualPlayerWindow]:
        """Internal access to a window object."""
        return self._windows.get(win_id)