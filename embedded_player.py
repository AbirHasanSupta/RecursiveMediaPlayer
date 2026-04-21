"""
EmbeddedPlayer
==============
A self-contained Toplevel that hosts a VLC instance inside a Tkinter canvas,
modelled exactly on DualPlayerSlot from dual_player_manager.py.

Usage (replaces the thread+controller launch in build_app.py):

    from embedded_player import EmbeddedPlayer

    player = EmbeddedPlayer(
        parent      = root,
        videos      = video_list,
        video_to_dir= video_to_dir,
        directories = directories,
        start_index = idx,
        volume      = cfg_volume,
        is_muted    = cfg_muted,
        logger      = log_fn,
        on_close    = lambda: ...,
    )
    player.play()          # starts playback immediately
"""

import os
import time
import random
import threading
import tkinter as tk
from tkinter import font as tkfont
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Callable

import vlc
try:
    from screeninfo import get_monitors as _get_monitors
except Exception:
    _get_monitors = None


# ─────────────────────────────────────────────────────────────────────────────
# Tiny helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt(ms: int) -> str:
    s = max(0, int(ms / 1000))
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _get_pictures_dir() -> Path:
    import sys
    if os.name == "nt":
        try:
            import ctypes, ctypes.wintypes
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, 0x0027, None, 0, buf)
            if buf.value:
                return Path(buf.value)
        except Exception:
            pass
    elif sys.platform == "darwin":
        return Path.home() / "Pictures"
    xdg = os.environ.get("XDG_PICTURES_DIR")
    return Path(xdg) if xdg else Path.home() / "Pictures"


# ─────────────────────────────────────────────────────────────────────────────
# Theme
# ─────────────────────────────────────────────────────────────────────────────

_BG       = "#0a0a0a"
_CTRL_BG  = "#111111"
_CTRL_BG2 = "#161616"
_ACCENT   = "#e50914"
_TXT      = "#f0f0f0"
_TXT_DIM  = "#666666"
_TXT_MED  = "#aaaaaa"
_BTN      = "#1e1e1e"
_BTN_HVR  = "#2c2c2c"
_BTN_ACT  = "#3a3a3a"
_TRACK    = "#2a2a2a"


# ─────────────────────────────────────────────────────────────────────────────
# EmbeddedPlayer
# ─────────────────────────────────────────────────────────────────────────────

class EmbeddedPlayer:
    """
    Standalone embedded VLC player.  Manages its own vlc.Instance and
    vlc.MediaPlayer.  The video canvas is the *only* render target — VLC
    never opens its own window.
    """

    CTRL_H       = 132           # px — height of the slide-up control bar
    INACTIVITY_S = 3.0           # seconds before auto-hiding the bar
    SEEK_PX      = 10_000        # ms per arrow-key seek
    VOL_STEP     = 5             # % per scroll / key press
    SPEED_STEPS  = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]

    _ROTATION_STEPS = [0, 90, 180, 270]
    _TRANSFORM_MAP  = {0: "identity", 90: "90", 180: "180", 270: "270"}

    # ------------------------------------------------------------------
    def __init__(
        self,
        parent,
        videos:        List[str],
        video_to_dir:  Dict[str, str],
        directories:   List[str],
        start_index:   int  = 0,
        volume:        int  = 50,
        is_muted:      bool = False,
        loop_mode:     str  = "loop_on",
        logger:        Optional[Callable] = None,
        on_close:      Optional[Callable] = None,
    ):
        self.parent      = parent
        self.videos      = list(videos)
        self.video_to_dir = video_to_dir
        self.directories = list(directories)
        self.index       = max(0, min(start_index, len(videos) - 1))
        self.volume      = volume
        self.is_muted    = is_muted
        self.loop_mode   = loop_mode
        self.logger      = logger
        self.on_close    = on_close

        self._running        = True
        self._lock           = threading.Lock()
        self._played_indices = set()
        self._speed_idx      = self.SPEED_STEPS.index(1.0)
        self._rotation_index = 0          # index into _ROTATION_STEPS: 0/1/2/3
        self._current_monitor = 1
        self._borderless     = False
        self._pre_bl_geo     = "1280x720"

        # VLC
        self._instance = vlc.Instance("--no-video-title-show", "--quiet")
        self._player   = self._instance.media_player_new()
        self._player.audio_set_mute(self.is_muted)
        self._player.audio_set_volume(self.volume)

        # Tk state
        self._ctrl_visible  = False
        self._hide_job      = None
        self._poll_job      = None
        self._update_job    = None
        self._drag_seek     = False
        self._seek_hover    = False
        self._last_mouse    = (-1, -1)
        self._last_move_t   = 0.0

        # Build UI (synchronous — must be on main thread)
        self._build_ui()

        # Attach end-of-media handler
        em = self._player.event_manager()
        em.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_media_ended)

    # ═══════════════════════════════════════════════════════════════════
    # UI BUILD
    # ═══════════════════════════════════════════════════════════════════

    def _build_ui(self):
        self._win = tk.Toplevel(self.parent)
        self._win.title("Recursive Video Player")
        self._win.geometry("1280x720+80+50")
        self._win.configure(bg=_BG)
        self._win.minsize(640, 400)
        self._win.protocol("WM_DELETE_WINDOW", self._close)

        # ── video canvas ──────────────────────────────────────────────
        self._canvas = tk.Canvas(self._win, bg="black",
                                 highlightthickness=0, cursor="none")
        self._canvas.pack(fill=tk.BOTH, expand=True)

        # ── floating control bar ──────────────────────────────────────
        self._bar = tk.Frame(self._win, bg=_CTRL_BG, highlightthickness=0)
        self._build_bar()

        # ── canvas bindings ───────────────────────────────────────────
        self._canvas.bind("<Motion>",          lambda e: self._show_bar())
        self._canvas.bind("<Button-1>",        lambda e: self._toggle_pause())
        self._canvas.bind("<Double-Button-1>", lambda e: self._toggle_borderless())
        self._canvas.bind("<MouseWheel>",      self._canvas_wheel)
        self._canvas.bind("<Configure>",       lambda e: self._place_bar())

        # ── window-level key bindings (all shortcuts) ─────────────────
        self._bind_keys()

        # Realize HWND before any play() call
        self._win.update_idletasks()

        self._start_poll()
        self._schedule_refresh()

    def _build_bar(self):
        bar = self._bar

        F_SM  = tkfont.Font(family="Segoe UI", size=8)
        F_MD  = tkfont.Font(family="Segoe UI", size=10)
        F_ICO = tkfont.Font(family="Segoe UI", size=12)
        F_ACC = tkfont.Font(family="Segoe UI", size=8, weight="bold")
        F_XS  = tkfont.Font(family="Segoe UI", size=7)

        # ── info row ──────────────────────────────────────────────────
        info = tk.Frame(bar, bg=_CTRL_BG)
        info.pack(fill=tk.X, padx=12, pady=(7, 2))

        self._lbl_title = tk.Label(info, text="", anchor="w",
                                   font=F_SM, bg=_CTRL_BG, fg=_TXT)
        self._lbl_title.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._lbl_idx = tk.Label(info, text="", font=F_SM,
                                 bg=_CTRL_BG, fg=_TXT_DIM)
        self._lbl_idx.pack(side=tk.LEFT, padx=(6, 10))

        self._lbl_dir = tk.Label(info, text="", font=F_SM,
                                 bg=_CTRL_BG, fg=_TXT_DIM)
        self._lbl_dir.pack(side=tk.LEFT, padx=(0, 12))

        self._lbl_time = tk.Label(info, text="0:00 / 0:00",
                                  font=F_SM, bg=_CTRL_BG, fg=_TXT_MED)
        self._lbl_time.pack(side=tk.RIGHT)

        # ── seek bar ──────────────────────────────────────────────────
        seek_row = tk.Frame(bar, bg=_CTRL_BG)
        seek_row.pack(fill=tk.X, padx=12, pady=(2, 5))

        self._seek = tk.Canvas(seek_row, height=20, bg=_CTRL_BG,
                               highlightthickness=0, cursor="hand2")
        self._seek.pack(fill=tk.X, expand=True)
        self._seek.bind("<Button-1>",        self._seek_click)
        self._seek.bind("<B1-Motion>",       self._seek_drag)
        self._seek.bind("<ButtonRelease-1>", self._seek_release)
        self._seek.bind("<Configure>",       lambda e: self._draw_seek())
        self._seek.bind("<Enter>",  lambda e: (self._set_seek_hover(True),  self._cancel_hide()))
        self._seek.bind("<Leave>",  lambda e: (self._set_seek_hover(False), self._schedule_hide()))

        # ── button row ────────────────────────────────────────────────
        btn_row = tk.Frame(bar, bg=_CTRL_BG2)
        btn_row.pack(fill=tk.X)

        def _btn(parent, text, cmd, font=None, fg=_TXT, padx=9):
            b = tk.Button(parent, text=text, command=cmd,
                          font=font or F_MD,
                          bg=_BTN, fg=fg, bd=0,
                          padx=padx, pady=5,
                          relief=tk.FLAT, cursor="hand2",
                          activebackground=_BTN_ACT,
                          activeforeground=_TXT)
            b.bind("<Enter>", lambda e, w=b: w.configure(bg=_BTN_HVR))
            b.bind("<Leave>", lambda e, w=b: w.configure(bg=_BTN))
            b.bind("<Enter>", lambda e: self._cancel_hide(), add="+")
            b.bind("<Leave>", lambda e: self._schedule_hide(), add="+")
            return b

        # Left — transport
        lg = tk.Frame(btn_row, bg=_CTRL_BG2)
        lg.pack(side=tk.LEFT, padx=(8, 0), pady=2)

        _btn(lg, "⏮", self._prev, font=F_ICO).pack(side=tk.LEFT, padx=1)
        self._btn_play = _btn(lg, "⏸", self._toggle_pause, font=F_ICO)
        self._btn_play.pack(side=tk.LEFT, padx=1)
        _btn(lg, "⏭", self._next, font=F_ICO).pack(side=tk.LEFT, padx=1)
        _btn(lg, "■",  self._stop, font=F_MD).pack(side=tk.LEFT, padx=(1, 10))

        _btn(lg, "◀ Dir", self._prev_dir, font=F_SM).pack(side=tk.LEFT, padx=1)
        _btn(lg, "Dir ▶", self._next_dir, font=F_SM).pack(side=tk.LEFT, padx=(1, 10))

        _btn(lg, "⟳ Rotate", self._rotate_right, font=F_SM).pack(side=tk.LEFT, padx=1)
        _btn(lg, "📸",        self._screenshot,   font=F_MD).pack(side=tk.LEFT, padx=1)

        # Centre — loop mode
        mg = tk.Frame(btn_row, bg=_CTRL_BG2)
        mg.pack(side=tk.LEFT, padx=12, pady=2)

        self._btn_loop = _btn(mg, "↺  Loop", self._cycle_loop,
                              font=F_ACC, fg=_ACCENT)
        self._btn_loop.pack(side=tk.LEFT)

        # Right — volume · speed · fullscreen
        rg = tk.Frame(btn_row, bg=_CTRL_BG2)
        rg.pack(side=tk.RIGHT, padx=(0, 8), pady=2)

        _btn(rg, "⛶", self._toggle_borderless, font=F_ICO).pack(side=tk.RIGHT, padx=(6, 0))

        self._lbl_speed = tk.Label(rg, text="1.00×", cursor="hand2",
                                   font=F_ACC, bg=_CTRL_BG2, fg=_ACCENT)
        self._lbl_speed.pack(side=tk.RIGHT, padx=(0, 4))
        self._lbl_speed.bind("<Button-1>",        lambda e: self._speed_up())
        self._lbl_speed.bind("<Button-3>",        lambda e: self._speed_down())
        self._lbl_speed.bind("<Double-Button-1>", lambda e: self._speed_reset())
        self._lbl_speed.bind("<MouseWheel>",      lambda e: self._speed_up() if e.delta > 0 else self._speed_down())
        self._lbl_speed.bind("<Enter>", lambda e: self._cancel_hide())
        self._lbl_speed.bind("<Leave>", lambda e: self._schedule_hide())

        tk.Label(rg, text="spd", font=F_XS, bg=_CTRL_BG2, fg=_TXT_DIM).pack(side=tk.RIGHT)
        tk.Frame(rg, width=12, bg=_CTRL_BG2).pack(side=tk.RIGHT)

        self._lbl_vol = tk.Label(rg, text=f"{self.volume}%", width=4,
                                 font=F_SM, bg=_CTRL_BG2, fg=_TXT_MED)
        self._lbl_vol.pack(side=tk.RIGHT)
        self._lbl_vol.bind("<MouseWheel>", self._vol_scroll)
        self._lbl_vol.bind("<Enter>", lambda e: self._cancel_hide())
        self._lbl_vol.bind("<Leave>", lambda e: self._schedule_hide())

        self._lbl_mute = tk.Label(rg, text="🔊", cursor="hand2",
                                  font=F_ICO, bg=_CTRL_BG2, fg=_TXT)
        self._lbl_mute.pack(side=tk.RIGHT, padx=(0, 2))
        self._lbl_mute.bind("<Button-1>",   lambda e: self._toggle_mute())
        self._lbl_mute.bind("<MouseWheel>", self._vol_scroll)
        self._lbl_mute.bind("<Enter>", lambda e: self._cancel_hide())
        self._lbl_mute.bind("<Leave>", lambda e: self._schedule_hide())

        # keep bar alive while hovering any part of it
        for w in [bar, info, seek_row, btn_row, lg, mg, rg,
                  self._lbl_title, self._lbl_dir, self._lbl_idx, self._lbl_time]:
            w.bind("<Enter>", lambda e: self._cancel_hide(), add="+")
            w.bind("<Leave>", lambda e: self._schedule_hide(), add="+")

    # ═══════════════════════════════════════════════════════════════════
    # KEY BINDINGS  — all shortcuts from the original key_press.py
    # ═══════════════════════════════════════════════════════════════════

    def _bind_keys(self):
        w = self._win
        # Pause / resume
        w.bind("<space>",         lambda e: self._toggle_pause())
        w.bind("<p>",             lambda e: self._toggle_pause())
        w.bind("<P>",             lambda e: self._toggle_pause())
        # Seek
        w.bind("<Left>",          lambda e: self._seek_rel(-self.SEEK_PX))
        w.bind("<Right>",         lambda e: self._seek_rel(+self.SEEK_PX))
        w.bind("<Shift-Left>",    lambda e: self._seek_rel(-60_000))
        w.bind("<Shift-Right>",   lambda e: self._seek_rel(+60_000))
        w.bind("<Control-Left>",  lambda e: self._seek_rel(-5_000))
        w.bind("<Control-Right>", lambda e: self._seek_rel(+5_000))
        # Video navigation — d=next, a=prev  (matches key_press.py)
        w.bind("<d>",             lambda e: self._next())
        w.bind("<D>",             lambda e: self._next())
        w.bind("<a>",             lambda e: self._prev())
        w.bind("<A>",             lambda e: self._prev())
        w.bind("<Prior>",         lambda e: self._next())   # Page Up
        w.bind("<Next>",          lambda e: self._prev())   # Page Down
        # Directory navigation — e=next dir, q=prev dir  (matches key_press.py)
        w.bind("<e>",             lambda e: self._next_dir())
        w.bind("<E>",             lambda e: self._next_dir())
        w.bind("<q>",             lambda e: self._prev_dir())
        w.bind("<Q>",             lambda e: self._prev_dir())
        # Volume — w=up, s=down  (matches key_press.py)
        w.bind("<Up>",            lambda e: self._vol_change(+self.VOL_STEP))
        w.bind("<Down>",          lambda e: self._vol_change(-self.VOL_STEP))
        w.bind("<w>",             lambda e: self._vol_change(+self.VOL_STEP))
        w.bind("<W>",             lambda e: self._vol_change(+self.VOL_STEP))
        w.bind("<s>",             lambda e: self._vol_change(-self.VOL_STEP))
        w.bind("<S>",             lambda e: self._vol_change(-self.VOL_STEP))
        w.bind("<m>",             lambda e: self._toggle_mute())
        w.bind("<M>",             lambda e: self._toggle_mute())
        # Screenshot — t  (matches key_press.py)
        w.bind("<t>",             lambda e: self._screenshot())
        w.bind("<T>",             lambda e: self._screenshot())
        # Speed — = / -  (matches key_press.py)
        w.bind("<equal>",         lambda e: self._speed_up())
        w.bind("<plus>",          lambda e: self._speed_up())
        w.bind("<minus>",         lambda e: self._speed_down())
        w.bind("<underscore>",    lambda e: self._speed_down())
        w.bind("<0>",             lambda e: self._speed_reset())
        w.bind("<KP_0>",          lambda e: self._speed_reset())
        # Fullscreen / borderless — f  (matches key_press.py)
        w.bind("<f>",             lambda e: self._toggle_borderless())
        w.bind("<F>",             lambda e: self._toggle_borderless())
        w.bind("<Return>",        lambda e: self._toggle_borderless())
        w.bind("<Escape>",        lambda e: self._escape())
        # Rotate — r  (matches key_press.py)
        w.bind("<r>",             lambda e: self._rotate_right())
        w.bind("<R>",             lambda e: self._rotate_right())
        w.bind("<l>",             lambda e: self._rotate_left())
        w.bind("<L>",             lambda e: self._rotate_left())
        # Loop
        w.bind("<o>",             lambda e: self._cycle_loop())
        w.bind("<O>",             lambda e: self._cycle_loop())
        # Zoom
        w.bind("<z>",             lambda e: self._zoom(+0.1))
        w.bind("<Z>",             lambda e: self._zoom(-0.1))
        w.bind("<x>",             lambda e: self._zoom(0))
        w.bind("<X>",             lambda e: self._zoom(0))

    # ═══════════════════════════════════════════════════════════════════
    # CORE EMBED — dual_player_manager pattern exactly
    # ═══════════════════════════════════════════════════════════════════

    def _embed(self):
        """Bind VLC output to the canvas.  Called before every play()."""
        try:
            self._canvas.update_idletasks()
            wid = self._canvas.winfo_id()
            if os.name == "nt":
                self._player.set_hwnd(wid)
            else:
                self._player.set_xwindow(wid)
        except Exception as e:
            if self.logger:
                self.logger(f"[embed] {e}")

    # ═══════════════════════════════════════════════════════════════════
    # PLAYBACK
    # ═══════════════════════════════════════════════════════════════════

    def play(self):
        """Start playback at self.index — deferred so the window is fully painted before VLC embeds."""
        self._win.update()
        self._win.after(150, lambda: self._play_index(self.index))

    def _play_index(self, idx: int):
        if not self._running or not self.videos:
            return
        idx = max(0, min(idx, len(self.videos) - 1))
        self.index = idx
        path = self.videos[idx]

        self._embed()
        media = self._instance.media_new(path)
        self._player.set_media(media)
        self._player.play()

        # Audio
        threading.Thread(target=self._post_play_audio, daemon=True).start()

        if self.logger:
            d = self.video_to_dir.get(path, "")
            self.logger(
                f"[{idx+1}/{len(self.videos)}] "
                f"{os.path.basename(path)}"
                + (f"  •  {os.path.basename(d)}" if d else "")
            )

    def _post_play_audio(self):
        """Wait for Playing state then set volume/mute/rate."""
        for _ in range(50):
            if not self._running:
                return
            if self._player.get_state() == vlc.State.Playing:
                break
            time.sleep(0.1)
        try:
            self._player.audio_set_mute(self.is_muted)
            if not self.is_muted:
                self._player.audio_set_volume(self.volume)
            tc = self._player.audio_get_track_count()
            if tc and tc > 0 and self._player.audio_get_track() == -1:
                self._player.audio_set_track(1)
            rate = self.SPEED_STEPS[self._speed_idx]
            if rate != 1.0:
                self._player.set_rate(rate)
        except Exception:
            pass

    def _on_media_ended(self, event):
        if not self._running:
            return
        # Schedule next video on the Tk main thread
        try:
            self._win.after(0, self._advance)
        except Exception:
            pass

    def _advance(self):
        if not self._running:
            return
        if self.loop_mode == "shuffle":
            self._played_indices.add(self.index)
            unplayed = [i for i in range(len(self.videos))
                        if i not in self._played_indices]
            if not unplayed:
                self._played_indices.clear()
                return
            self._play_index(random.choice(unplayed))
        elif self.loop_mode == "loop_off":
            if self.index < len(self.videos) - 1:
                self._play_index(self.index + 1)
        else:
            self._play_index((self.index + 1) % len(self.videos))

    # ═══════════════════════════════════════════════════════════════════
    # TRANSPORT CONTROLS
    # ═══════════════════════════════════════════════════════════════════

    def _toggle_pause(self):
        if self._player.is_playing():
            self._player.pause()
        else:
            self._player.play()

    def _next(self):
        self._play_index((self.index + 1) % len(self.videos))

    def _prev(self):
        self._play_index((self.index - 1) % len(self.videos))

    def _stop(self):
        self._player.stop()

    def _next_dir(self):
        cur = self.video_to_dir.get(self.videos[self.index])
        if not cur or cur not in self.directories:
            return
        nxt_dir = self.directories[(self.directories.index(cur) + 1) % len(self.directories)]
        for i, v in enumerate(self.videos):
            if self.video_to_dir.get(v) == nxt_dir:
                self._play_index(i)
                return

    def _prev_dir(self):
        cur = self.video_to_dir.get(self.videos[self.index])
        if not cur or cur not in self.directories:
            return
        prv_dir = self.directories[(self.directories.index(cur) - 1) % len(self.directories)]
        for i, v in enumerate(self.videos):
            if self.video_to_dir.get(v) == prv_dir:
                self._play_index(i)
                return

    def _seek_rel(self, delta_ms: int):
        t   = self._player.get_time() or 0
        dur = self._player.get_length() or 0
        new = max(0, min(t + delta_ms, dur - 100 if dur > 0 else 0))
        self._player.set_time(new)

    # ═══════════════════════════════════════════════════════════════════
    # VOLUME / MUTE
    # ═══════════════════════════════════════════════════════════════════

    def _vol_change(self, delta: int):
        if self.is_muted:
            self.is_muted = False
            self._player.audio_set_mute(False)
        self.volume = max(0, min(100, self.volume + delta))
        self._player.audio_set_volume(self.volume)
        self._refresh_vol()

    def _toggle_mute(self):
        self.is_muted = not self.is_muted
        self._player.audio_set_mute(self.is_muted)
        if not self.is_muted:
            self._player.audio_set_volume(self.volume)
        self._refresh_vol()

    def _vol_scroll(self, e):
        self._vol_change(+self.VOL_STEP if e.delta > 0 else -self.VOL_STEP)

    def _canvas_wheel(self, e):
        self._vol_change(+self.VOL_STEP if e.delta > 0 else -self.VOL_STEP)

    def _refresh_vol(self):
        vol  = self.volume
        mute = self.is_muted
        icon = "🔇" if (mute or vol == 0) else "🔈" if vol < 30 else "🔉" if vol < 70 else "🔊"
        try:
            self._lbl_mute.config(text=icon)
            self._lbl_vol.config(text=f"{vol}%")
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════
    # SPEED
    # ═══════════════════════════════════════════════════════════════════

    def _speed_up(self):
        self._speed_idx = min(len(self.SPEED_STEPS) - 1, self._speed_idx + 1)
        self._apply_speed()

    def _speed_down(self):
        self._speed_idx = max(0, self._speed_idx - 1)
        self._apply_speed()

    def _speed_reset(self):
        self._speed_idx = self.SPEED_STEPS.index(1.0)
        self._apply_speed()

    def _apply_speed(self):
        r = self.SPEED_STEPS[self._speed_idx]
        self._player.set_rate(r)
        try:
            self._lbl_speed.config(text=f"{r:.2f}×")
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════
    # LOOP
    # ═══════════════════════════════════════════════════════════════════

    def _cycle_loop(self):
        modes = ["loop_on", "loop_off", "shuffle"]
        self.loop_mode = modes[(modes.index(self.loop_mode) + 1) % len(modes)]
        labels = {"loop_on": "↺  Loop", "loop_off": "→  Once", "shuffle": "⇄  Shuffle"}
        try:
            self._btn_loop.config(text=labels[self.loop_mode])
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════
    # ROTATE
    # ═══════════════════════════════════════════════════════════════════

    def _rotate_right(self):
        self._rotation_index = (self._rotation_index + 1) % 4
        self._apply_rotation()

    def _rotate_left(self):
        self._rotation_index = (self._rotation_index - 1) % 4
        self._apply_rotation()

    def _apply_rotation(self):
        if not self._player or not self.videos:
            return
        try:
            angle          = self._ROTATION_STEPS[self._rotation_index]
            transform_type = self._TRANSFORM_MAP[angle]

            position_ms = self._player.get_time() or 0
            was_playing = self._player.is_playing()
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
                self._player.stop()
                self._player.release()
            except Exception:
                pass
            try:
                self._instance.release()
            except Exception:
                pass

            self._instance = vlc.Instance(*base_args)
            self._player   = self._instance.media_player_new()
            self._embed()

            media = self._instance.media_new(path)
            self._player.set_media(media)
            self._player.play()

            # Reattach end-of-media event on new player.
            em = self._player.event_manager()
            em.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_media_ended)

            def _settle():
                if not self._player:
                    return
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    if self._player.get_state() == vlc.State.Playing:
                        break
                    time.sleep(0.05)
                try:
                    if position_ms > 0:
                        self._player.set_time(position_ms)
                    self._player.set_rate(self.SPEED_STEPS[self._speed_idx])
                    self._player.audio_set_mute(self.is_muted)
                    if not self.is_muted:
                        self._player.audio_set_volume(self.volume)
                    if not was_playing:
                        self._player.pause()
                    self._player.video_set_aspect_ratio(None)
                    self._player.video_set_scale(0)
                except Exception:
                    pass

            threading.Thread(target=_settle, daemon=True).start()
        except Exception as e:
            if self.logger:
                self.logger(f"Rotate error: {e}")

    # ═══════════════════════════════════════════════════════════════════
    # ZOOM
    # ═══════════════════════════════════════════════════════════════════

    def _zoom(self, delta: float):
        if delta == 0:
            self._player.video_set_scale(0.0)
            return
        cur = self._player.video_get_scale()
        cur = cur if cur > 0 else 1.0
        self._player.video_set_scale(round(max(0.25, min(4.0, cur + delta)), 2))

    # ═══════════════════════════════════════════════════════════════════
    # SCREENSHOT
    # ═══════════════════════════════════════════════════════════════════

    def _screenshot(self):
        try:
            vid     = self.videos[self.index]
            out_dir = _get_pictures_dir() / "Recursive Media Player" / "Screenshots"
            out_dir.mkdir(parents=True, exist_ok=True)
            stem    = os.path.splitext(os.path.basename(vid))[0]
            ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
            path    = out_dir / f"{stem}_{ts}.png"
            self._player.video_take_snapshot(0, str(path), 0, 0)
            if self.logger:
                self.logger(f"Screenshot: {path}")
        except Exception as e:
            if self.logger:
                self.logger(f"Screenshot error: {e}")

    # ═══════════════════════════════════════════════════════════════════
    # FULLSCREEN / BORDERLESS
    # ═══════════════════════════════════════════════════════════════════

    def _get_monitor_geometry(self, monitor_number: int):
        try:
            if _get_monitors:
                monitors = _get_monitors()
                idx = monitor_number - 1
                if idx < len(monitors):
                    m = monitors[idx]
                    return m.x, m.y, m.width, m.height
        except Exception:
            pass
        return 0, 0, self._win.winfo_screenwidth(), self._win.winfo_screenheight()

    def _toggle_borderless(self):
        self._borderless = not self._borderless
        if self._borderless:
            self._pre_bl_geo = self._win.geometry()
            self._win.overrideredirect(True)
            sw = self._win.winfo_screenwidth()
            sh = self._win.winfo_screenheight()
            self._win.geometry(f"{sw}x{sh}+0+0")
            self._force_hide_bar()
        else:
            self._win.overrideredirect(False)
            self._win.geometry(self._pre_bl_geo)
        self._win.lift()
        self._win.focus_force()
        # Re-bind VLC after geometry change
        self._embed()

    def _escape(self):
        if self._borderless:
            self._borderless = False
            self._win.overrideredirect(False)
            self._win.geometry(self._pre_bl_geo)
            self._win.lift()
            self._win.focus_force()
            self._embed()
        else:
            self._close()

    # ═══════════════════════════════════════════════════════════════════
    # CONTROL BAR SHOW / HIDE
    # ═══════════════════════════════════════════════════════════════════

    def _show_bar(self):
        self._cancel_hide()
        if not self._ctrl_visible:
            self._ctrl_visible = True
            self._place_bar()
            self._bar.lift()
        try:
            self._win.configure(cursor="")
            self._canvas.configure(cursor="")
        except Exception:
            pass

    def _hide_bar(self):
        self._hide_job     = None
        self._ctrl_visible = False
        try:
            self._bar.place_forget()
        except Exception:
            pass
        try:
            self._win.configure(cursor="none")
            self._canvas.configure(cursor="none")
        except Exception:
            pass

    def _force_hide_bar(self):
        self._cancel_hide()
        self._hide_bar()

    def _schedule_hide(self, delay: int = 2200):
        if self._hide_job or not self._win:
            return
        self._hide_job = self._win.after(delay, self._hide_bar)

    def _cancel_hide(self):
        if self._hide_job:
            try:
                self._win.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None

    def _place_bar(self):
        try:
            ww = self._win.winfo_width()
            wh = self._win.winfo_height()
            if ww < 10 or wh < 10:
                return
            if self._ctrl_visible:
                self._bar.place(x=0, y=max(0, wh - self.CTRL_H),
                                width=ww, height=self.CTRL_H)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════
    # MOUSE POLL — show bar on any mouse movement
    # ═══════════════════════════════════════════════════════════════════

    def _start_poll(self):
        self._do_poll()

    def _do_poll(self):
        if not self._running or not self._win.winfo_exists():
            return
        if self._player is not None:      # skip mouse-tracking during monitor switch
            try:
                mx = self._win.winfo_pointerx()
                my = self._win.winfo_pointery()
                wx = self._win.winfo_rootx()
                wy = self._win.winfo_rooty()
                ww = self._win.winfo_width()
                wh = self._win.winfo_height()
                inside = (wx <= mx <= wx + ww) and (wy <= my <= wy + wh)
                if inside:
                    if (mx, my) != self._last_mouse:
                        self._last_mouse  = (mx, my)
                        self._last_move_t = time.monotonic()
                        self._show_bar()
                    else:
                        idle = time.monotonic() - self._last_move_t
                        if idle >= self.INACTIVITY_S and self._ctrl_visible and not self._hide_job:
                            self._schedule_hide(100)
                else:
                    if self._ctrl_visible and not self._hide_job:
                        self._schedule_hide(500)
            except Exception:
                pass
        try:
            self._poll_job = self._win.after(120, self._do_poll)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════
    # SEEK BAR
    # ═══════════════════════════════════════════════════════════════════

    def _set_seek_hover(self, val: bool):
        self._seek_hover = val
        self._draw_seek()

    def _draw_seek(self):
        sc = self._seek
        try:
            sc.delete("all")
            w = sc.winfo_width()
            h = sc.winfo_height()
            if w <= 1:
                return
            cy = h // 2
            sc.create_rectangle(0, cy - 2, w, cy + 2, fill=_TRACK, outline="")
            cur = max(0, self._player.get_time() or 0)
            dur = max(1, self._player.get_length() or 1)
            px  = int((cur / dur) * w)
            sc.create_rectangle(0, cy - 2, px, cy + 2, fill=_ACCENT, outline="")
            r = 7 if self._seek_hover else 5
            sc.create_oval(px - r, cy - r, px + r, cy + r,
                           fill="white", outline="")
        except Exception:
            pass

    def _seek_from_x(self, x: int):
        try:
            w = self._seek.winfo_width()
            if w <= 1:
                return
            frac = max(0.0, min(1.0, x / w))
            self._player.set_time(int(frac * (self._player.get_length() or 0)))
            self._draw_seek()
        except Exception:
            pass

    def _seek_click(self, e):
        self._drag_seek = True
        self._seek_from_x(e.x)

    def _seek_drag(self, e):
        if self._drag_seek:
            self._seek_from_x(e.x)

    def _seek_release(self, e):
        self._drag_seek = False

    # ═══════════════════════════════════════════════════════════════════
    # DISPLAY REFRESH
    # ═══════════════════════════════════════════════════════════════════

    def _schedule_refresh(self):
        self._update_job = self._win.after(500, self._refresh_tick)

    def _refresh_tick(self):
        if not self._running or not self._win.winfo_exists():
            return
        if self._player is None:          # mid-monitor-switch — skip this tick
            try:
                self._update_job = self._win.after(500, self._refresh_tick)
            except Exception:
                pass
            return
        if self._ctrl_visible and not self._drag_seek:
            self._refresh_display()
        try:
            self._update_job = self._win.after(500, self._refresh_tick)
        except Exception:
            pass

    def _refresh_display(self):
        try:
            name = os.path.basename(self.videos[self.index])
            self._lbl_title.config(text=name[:74] + ("…" if len(name) > 74 else ""))
            d = self.video_to_dir.get(self.videos[self.index], "")
            self._lbl_dir.config(text=os.path.basename(d) if d else "")
            self._lbl_idx.config(text=f"{self.index + 1} / {len(self.videos)}")
        except Exception:
            pass
        try:
            cur = self._player.get_time() or 0
            dur = self._player.get_length() or 0
            self._lbl_time.config(text=f"{_fmt(cur)} / {_fmt(dur)}")
        except Exception:
            pass
        try:
            self._btn_play.config(text="⏸" if self._player.is_playing() else "▶")
        except Exception:
            pass
        self._refresh_vol()
        try:
            self._lbl_speed.config(text=f"{self._player.get_rate():.2f}×")
        except Exception:
            pass
        _L = {"loop_on": "↺  Loop", "loop_off": "→  Once", "shuffle": "⇄  Shuffle"}
        try:
            self._btn_loop.config(text=_L.get(self.loop_mode, "↺  Loop"))
        except Exception:
            pass
        self._draw_seek()

    # ═══════════════════════════════════════════════════════════════════
    # CLOSE
    # ═══════════════════════════════════════════════════════════════════

    def _close(self):
        self._running = False
        # cancel pending jobs
        for attr in ("_hide_job", "_poll_job", "_update_job"):
            job = getattr(self, attr, None)
            if job:
                try:
                    self._win.after_cancel(job)
                except Exception:
                    pass
            setattr(self, attr, None)

        # Snapshot the VLC objects so the teardown thread owns them.
        player   = self._player
        instance = self._instance
        self._player   = None
        self._instance = None

        # Destroy the Tk window immediately — keeps the UI responsive.
        try:
            self._win.destroy()
        except Exception:
            pass

        if self.on_close:
            try:
                self.on_close()
            except Exception:
                pass

        # Release VLC off the main thread; stop() can block for several seconds.
        def _vlc_teardown():
            try:
                if player:
                    player.stop()
                    player.release()
            except Exception:
                pass
            try:
                if instance:
                    instance.release()
            except Exception:
                pass

        threading.Thread(target=_vlc_teardown, daemon=True).start()