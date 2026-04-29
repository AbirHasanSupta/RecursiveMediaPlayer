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

    CTRL_H       = 100           # px — height of the slide-up control bar
    INACTIVITY_S = 2.0           # seconds before auto-hiding the bar
    SEEK_PX      = 200           # ms per arrow-key seek (matches vlc_player_controller)
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
        logger:          Optional[Callable] = None,
        on_close:        Optional[Callable] = None,
        on_volume_change: Optional[Callable] = None,
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
        self.on_volume_change = on_volume_change
        self.on_loop_change   = None   # set by caller after construction if needed
        self.on_close_save    = None   # called with (index, path, loop_mode) on close
        self.on_video_changed = None  # called with (index, path) on every track change
        self.on_add_to_playlist = None  # called with (video_path)
        self.on_add_to_queue = None
        self.on_add_to_favourites = None

        self._running        = True
        self._lock           = threading.Lock()
        self._played_indices = set()
        self._speed_idx      = self.SPEED_STEPS.index(1.0)
        self._rotation_index = 0          # index into _ROTATION_STEPS: 0/1/2/3
        self._flip_h         = False      # horizontal flip toggled
        self._borderless     = False
        self._pre_bl_geo     = "1280x720"
        self._chapters_visible = True     # initially assume chapters exist (packed in UI)

        # A-B loop
        self._ab_point_a     = None
        self._ab_point_b     = None
        self._ab_loop_active = False
        self._ab_monitor_job = None   # Tk after() job id

        # Sleep timer
        self._sleep_timer_job = None   # Tk after() job id
        self._sleep_remaining = 0      # seconds remaining

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
        self._holding = False
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
        self._win = tk.Toplevel()
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
        # Keep bar out of the pack/grid layout so it never influences window geometry.
        # It is shown exclusively via place() when needed.
        self._bar.place_forget()

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
        # Force initial chapter visibility check after UI is fully built
        self._win.after(100, lambda: self._refresh_display())

    def _build_bar(self):
        bar = self._bar

        F_SM  = tkfont.Font(family="Segoe UI", size=8)
        F_MD  = tkfont.Font(family="Segoe UI", size=10)
        F_ICO = tkfont.Font(family="Segoe UI", size=12)
        F_ACC = tkfont.Font(family="Segoe UI", size=8, weight="bold")
        F_XS  = tkfont.Font(family="Segoe UI", size=7)
        F_AB  = tkfont.Font(family="Segoe UI", size=8, weight="bold")

        # ── helper: styled button ──────────────────────────────────────
        def _btn(parent, text, cmd, font=None, fg=_TXT, padx=8, pady=4):
            b = tk.Button(parent, text=text, command=cmd,
                          font=font or F_MD,
                          bg=_BTN, fg=fg, bd=0,
                          padx=padx, pady=pady,
                          relief=tk.FLAT, cursor="hand2",
                          activebackground=_BTN_ACT,
                          activeforeground=_TXT)
            b.bind("<Enter>", lambda e, w=b: w.configure(bg=_BTN_HVR))
            b.bind("<Leave>", lambda e, w=b: w.configure(bg=_BTN))
            b.bind("<Enter>", lambda e: self._cancel_hide(), add="+")
            b.bind("<Leave>", lambda e: self._schedule_hide(), add="+")
            return b

        # ═══════════════════════════════════════════════════════════════
        # ROW 1 — info strip: title · status badges · time
        # ═══════════════════════════════════════════════════════════════
        info = tk.Frame(bar, bg=_CTRL_BG)
        info.pack(fill=tk.X, padx=12, pady=(4, 1))

        self._lbl_title = tk.Label(info, text="", anchor="w",
                                   font=F_SM, bg=_CTRL_BG, fg=_TXT)
        self._lbl_title.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # right-side status badges (packed right-to-left)
        self._lbl_time = tk.Label(info, text="0:00 / 0:00",
                                  font=F_SM, bg=_CTRL_BG, fg=_TXT_MED)
        self._lbl_time.pack(side=tk.RIGHT, padx=(8, 0))

        self._lbl_idx = tk.Label(info, text="",
                                 font=F_SM, bg=_CTRL_BG, fg=_TXT_DIM)
        self._lbl_idx.pack(side=tk.RIGHT, padx=(0, 4))

        # chapter badge — only visible when chapters exist
        self._lbl_chapter = tk.Label(info, text="",
                                     font=F_XS, bg="#1e2a1e", fg="#66cc66",
                                     padx=4, pady=1, relief=tk.FLAT)
        self._lbl_chapter.pack(side=tk.RIGHT, padx=(0, 4))

        # A-B loop badge — only visible when A or A+B are set
        self._lbl_ab = tk.Label(info, text="",
                                font=F_AB, bg="#0d1f2d", fg="#00BFFF",
                                padx=4, pady=1, relief=tk.FLAT)
        self._lbl_ab.pack(side=tk.RIGHT, padx=(0, 4))

        # sleep timer countdown badge
        self._lbl_sleep = tk.Label(info, text="",
                                   font=F_XS, bg="#2a1e0d", fg="#FFA500",
                                   padx=4, pady=1, relief=tk.FLAT)
        self._lbl_sleep.pack(side=tk.RIGHT, padx=(0, 4))

        # directory name (dim, right of title)
        self._lbl_dir = tk.Label(info, text="",
                                 font=F_XS, bg=_CTRL_BG, fg=_TXT_DIM)
        self._lbl_dir.pack(side=tk.RIGHT, padx=(0, 6))

        # ═══════════════════════════════════════════════════════════════
        # ROW 2 — seek bar
        # ═══════════════════════════════════════════════════════════════
        seek_row = tk.Frame(bar, bg=_CTRL_BG)
        seek_row.pack(fill=tk.X, padx=12, pady=(2, 2))

        self._seek = tk.Canvas(seek_row, height=18, bg=_CTRL_BG,
                               highlightthickness=0, cursor="hand2")
        self._seek.pack(fill=tk.X, expand=True)
        self._seek.bind("<Button-1>",        self._seek_click)
        self._seek.bind("<B1-Motion>",       self._seek_drag)
        self._seek.bind("<ButtonRelease-1>", self._seek_release)
        self._seek.bind("<Configure>",       lambda e: self._draw_seek())
        self._seek.bind("<Enter>",  lambda e: (self._set_seek_hover(True),  self._cancel_hide()))
        self._seek.bind("<Leave>",  lambda e: (self._set_seek_hover(False), self._schedule_hide()))

        # ═══════════════════════════════════════════════════════════════
        # ROW 3 — control buttons
        # Three zones: LEFT (transport + nav), CENTRE (loop), RIGHT (vol/speed/tools)
        # ═══════════════════════════════════════════════════════════════
        btn_row = tk.Frame(bar, bg=_CTRL_BG2)
        btn_row.pack(fill=tk.X)

        # ── LEFT: core transport ──────────────────────────────────────
        lg = tk.Frame(btn_row, bg=_CTRL_BG2)
        lg.pack(side=tk.LEFT, padx=(8, 0), pady=2)

        # ⏮ / ⏭ — single click = prev/next video; hold = rewind/fast-forward
        btn_prev = _btn(lg, "⏮", None, font=F_ICO)
        btn_prev.pack(side=tk.LEFT, padx=1)
        self._btn_play = _btn(lg, "⏸", self._toggle_pause, font=F_ICO)
        self._btn_play.pack(side=tk.LEFT, padx=1)
        btn_next = _btn(lg, "⏭", None, font=F_ICO)
        btn_next.pack(side=tk.LEFT, padx=1)
        _btn(lg, "■",  self._stop, font=F_MD).pack(side=tk.LEFT, padx=(1, 8))

        self._setup_hold_button(btn_prev, on_click=self._prev, on_hold=self._rewind)
        self._setup_hold_button(btn_next, on_click=self._next, on_hold=self._fast_forward)

        # thin divider
        tk.Frame(lg, width=1, bg="#333333").pack(side=tk.LEFT, fill=tk.Y, pady=3)

        # Directory skip — text-only, compact
        _btn(lg, "◀ Dir", self._prev_dir, font=F_SM, padx=6).pack(side=tk.LEFT, padx=(6, 1))
        _btn(lg, "Dir ▶", self._next_dir, font=F_SM, padx=6).pack(side=tk.LEFT, padx=(1, 8))

        tk.Frame(lg, width=1, bg="#333333").pack(side=tk.LEFT, fill=tk.Y, pady=3)

        # Zoom menu (includes rotate)
        _btn(lg, "🔍", self._show_zoom_menu, font=F_MD, padx=6).pack(side=tk.LEFT, padx=(6, 8))

        tk.Frame(lg, width=1, bg="#333333").pack(side=tk.LEFT, fill=tk.Y, pady=3)

        # Chapter buttons — compact symbols only, tooltip via logger
        self._btn_prev_chapter = _btn(lg, "❮Ch", self._prev_chapter, font=F_SM, padx=5)
        self._btn_prev_chapter.pack(side=tk.LEFT, padx=(6, 1))
        self._btn_next_chapter = _btn(lg, "Ch❯", self._next_chapter, font=F_SM, padx=5)
        self._btn_next_chapter.pack(side=tk.LEFT, padx=(1, 8))

        # This divider sits between chapter buttons and A-B loop buttons.
        # We keep a reference so we can re-pack chapter buttons correctly.
        self._divider_before_ab = tk.Frame(lg, width=1, bg="#333333")
        self._divider_before_ab.pack(side=tk.LEFT, fill=tk.Y, pady=3)

        # A-B loop — three compact tagged buttons
        self._btn_ab_a = _btn(lg, "A", self._set_ab_a, font=F_ACC,
                              fg="#00BFFF", padx=6)
        self._btn_ab_a.pack(side=tk.LEFT, padx=(6, 1))

        self._btn_ab_b = _btn(lg, "B", self._set_ab_b, font=F_ACC,
                              fg="#00BFFF", padx=6)
        self._btn_ab_b.pack(side=tk.LEFT, padx=1)

        self._btn_ab_clr = _btn(lg, "✕", self._clear_ab, font=F_XS,
                                fg=_TXT_DIM, padx=5)
        self._btn_ab_clr.pack(side=tk.LEFT, padx=(1, 6))

        # ── CENTRE: loop mode ─────────────────────────────────────────
        mg = tk.Frame(btn_row, bg=_CTRL_BG2)
        mg.pack(side=tk.LEFT, expand=True, pady=2)   # expand to push left/right apart

        self._btn_loop = _btn(mg, "↺  Loop", self._cycle_loop,
                              font=F_ACC, fg=_ACCENT, padx=10)
        self._btn_loop.pack()

        # ── RIGHT: volume · speed · sleep · fullscreen · overflow ─────
        rg = tk.Frame(btn_row, bg=_CTRL_BG2)
        rg.pack(side=tk.RIGHT, padx=(0, 8), pady=2)

        # Fullscreen (rightmost, most-used secondary action)
        _btn(rg, "⛶", self._toggle_borderless, font=F_ICO, padx=7).pack(side=tk.RIGHT, padx=(4, 0))

        # Overflow menu (context / playlist / add-to)
        _btn(rg, "⋮", self._show_context_menu_from_btn, font=F_ICO, padx=6).pack(side=tk.RIGHT, padx=1)

        # Sleep timer — badge-style: shows icon only; countdown appears in info strip
        self._btn_sleep = _btn(rg, "⏻", self._show_sleep_menu,
                               font=F_MD, fg="#FFA500", padx=6)
        self._btn_sleep.pack(side=tk.RIGHT, padx=(1, 4))

        tk.Frame(rg, width=1, bg="#333333").pack(side=tk.RIGHT, fill=tk.Y, pady=3, padx=4)

        # Speed label (interactive)
        self._lbl_speed = tk.Label(rg, text="1.00×", cursor="hand2",
                                   font=F_ACC, bg=_CTRL_BG2, fg=_ACCENT)
        self._lbl_speed.pack(side=tk.RIGHT, padx=(0, 2))
        self._lbl_speed.bind("<Button-1>",        lambda e: self._speed_up())
        self._lbl_speed.bind("<Button-3>",        lambda e: self._speed_down())
        self._lbl_speed.bind("<Double-Button-1>", lambda e: self._speed_reset())
        self._lbl_speed.bind("<MouseWheel>",      lambda e: self._speed_up() if e.delta > 0 else self._speed_down())
        self._lbl_speed.bind("<Enter>", lambda e: self._cancel_hide())
        self._lbl_speed.bind("<Leave>", lambda e: self._schedule_hide())

        tk.Frame(rg, width=1, bg="#333333").pack(side=tk.RIGHT, fill=tk.Y, pady=3, padx=4)

        # Volume
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

        # ── keep bar alive while mouse is over any widget ─────────────
        _all = [bar, info, seek_row, btn_row, lg, mg, rg,
                self._lbl_title, self._lbl_dir, self._lbl_idx, self._lbl_time,
                self._lbl_ab, self._lbl_sleep, self._lbl_chapter]
        for w in _all:
            w.bind("<Enter>", lambda e: self._cancel_hide(), add="+")
            w.bind("<Leave>", lambda e: self._schedule_hide(), add="+")

    # ═══════════════════════════════════════════════════════════════════
    # KEY BINDINGS — hotkey-driven, live-reloadable
    # ═══════════════════════════════════════════════════════════════════

    # Default hotkeys — kept in sync with DEFAULT_HOTKEYS in settings_manager.py
    _DEFAULT_HOTKEYS: Dict[str, str] = {
        "toggle_pause":      "space",
        "stop_video":        "esc",
        "fast_forward":      "right",
        "rewind":            "left",
        "next_video":        "d",
        "prev_video":        "a",
        "next_directory":    "e",
        "prev_directory":    "q",
        "volume_up":         "w",
        "volume_down":       "s",
        "toggle_mute":       "m",
        "increase_speed":    "=",
        "decrease_speed":    "-",
        "reset_speed":       "0",
        "toggle_fullscreen": "f",
        "rotate_right":      "r",
        "flip_h":             "h",
        "zoom_in":           "ctrl+=",
        "zoom_out":          "ctrl+-",
        "zoom_reset":        "ctrl+0",
        "take_screenshot":   "t",
        "copy_video_path":   "ctrl+c",
        "next_chapter":      "n",
        "prev_chapter":      "b",
        "cycle_subtitle":    "u",
        "disable_subtitles": "ctrl+u",
        "ab_set_a":          "[",
        "ab_set_b":          "]",
        "ab_clear":          "\\",
    }

    # Maps action_id -> (method_name, extra_args)
    _ACTION_MAP: Dict[str, tuple] = {
        "toggle_pause":      ("_toggle_pause",      ()),
        # stop_video handled by static <Escape> bind — excluded from _rebind_keys
        "fast_forward":      ("_fast_forward",     ()),
        "rewind":            ("_rewind",           ()),
        "next_video":        ("_next",              ()),
        "prev_video":        ("_prev",              ()),
        "next_directory":    ("_next_dir",          ()),
        "prev_directory":    ("_prev_dir",          ()),
        "volume_up":         ("_vol_change",        (5,)),
        "volume_down":       ("_vol_change",        (-5,)),
        "toggle_mute":       ("_toggle_mute",       ()),
        "increase_speed":    ("_speed_up",          ()),
        "decrease_speed":    ("_speed_down",        ()),
        "reset_speed":       ("_speed_reset",       ()),
        "toggle_fullscreen": ("_toggle_borderless", ()),
        "rotate_right":      ("_rotate_right",      ()),
        "flip_h":            ("_toggle_flip_h",      ()),
        "zoom_in":           ("_zoom_in",           ()),
        "zoom_out":          ("_zoom_out",          ()),
        "zoom_reset":        ("_zoom",              (0,)),
        "take_screenshot":   ("_screenshot",        ()),
        "copy_video_path":   ("_copy_video_path",   ()),
        "next_chapter":      ("_next_chapter",      ()),
        "prev_chapter":      ("_prev_chapter",      ()),
        "cycle_subtitle":    ("_cycle_subtitle",    ()),
        "disable_subtitles": ("_disable_subtitle",  ()),
        "ab_set_a":          ("_set_ab_a",          ()),
        "ab_set_b":          ("_set_ab_b",          ()),
        "ab_clear":          ("_clear_ab",          ()),
    }

    def set_hotkeys(self, hotkeys: dict):
        """Live-reload key bindings from a new hotkeys dict (called on settings save)."""
        self._hotkeys = dict(hotkeys) if hotkeys else dict(self._DEFAULT_HOTKEYS)
        self._rebind_keys()

    def _bind_keys(self):
        """Initial key setup — called once from _build_ui."""
        self._hotkeys = dict(self._DEFAULT_HOTKEYS)
        self._registered_cbids: list = []   # [(seq, cbid), …] for safe per-cbid unbind

        # Register hotkey-driven bindings
        self._rebind_keys()

        # ── Static convenience binds (not in hotkey map, always active) ──────
        # All use add=True so they stack beside _rebind_keys bindings without
        # overwriting them.
        w = self._win
        w.bind("<Shift-Left>",    lambda e: self._seek_rel(-60_000),        add=True)
        w.bind("<Shift-Right>",   lambda e: self._seek_rel(+60_000),        add=True)
        w.bind("<Control-Left>",  lambda e: self._seek_rel(-5_000),         add=True)
        w.bind("<Control-Right>", lambda e: self._seek_rel(+5_000),         add=True)
        w.bind("<Prior>",         lambda e: self._next(),                   add=True)
        w.bind("<Next>",          lambda e: self._prev(),                   add=True)
        w.bind("<Return>",        lambda e: self._toggle_borderless(),      add=True)
        w.bind("<KP_0>",          lambda e: self._speed_reset(),            add=True)
        w.bind("<plus>",          lambda e: self._speed_up(),               add=True)
        w.bind("<underscore>",    lambda e: self._speed_down(),             add=True)
        # Loop / zoom / rotate extras that are not in the hotkey table
        w.bind("<o>",             lambda e: self._cycle_loop(),             add=True)
        w.bind("<O>",             lambda e: self._cycle_loop(),             add=True)
        w.bind("<z>",             lambda e: self._zoom(+0.1),               add=True)
        w.bind("<Z>",             lambda e: self._zoom(-0.1),               add=True)
        w.bind("<x>",             lambda e: self._zoom(0),                  add=True)
        w.bind("<X>",             lambda e: self._zoom(0),                  add=True)
        w.bind("<Up>",            lambda e: self._vol_change(+self.VOL_STEP), add=True)
        w.bind("<Down>",          lambda e: self._vol_change(-self.VOL_STEP), add=True)
        # Escape always calls _escape (exit borderless or close) — NOT overrideable
        # via hotkeys so it is registered once here without add=True, taking priority.
        w.bind("<Escape>",        lambda e: self._escape())

    def _rebind_keys(self):
        """Remove previously registered hotkey cbids and re-register from self._hotkeys."""
        w = self._win

        # Safely unbind only the specific callbacks we registered before
        for seq, cbid in getattr(self, '_registered_cbids', []):
            try:
                w.unbind(seq, cbid)
            except Exception:
                pass
        self._registered_cbids = []

        hk = self._hotkeys

        # Keys that must not be overridden via hotkey map (handled by static binds)
        _EXCLUDED = {"stop_video"}

        def _to_tk_seq(combo: str) -> Optional[str]:
            """Convert a keyboard-library combo string to a Tk bind sequence."""
            if not combo:
                return None
            parts = combo.lower().split('+')
            key   = parts[-1]
            mods  = parts[:-1]
            _key_map = {
                'space': 'space', 'esc': 'Escape', 'escape': 'Escape',
                'enter': 'Return', 'return': 'Return',
                'left': 'Left', 'right': 'Right', 'up': 'Up', 'down': 'Down',
                'page_up': 'Prior', 'page_down': 'Next',
                'delete': 'Delete', 'backspace': 'BackSpace',
                'insert': 'Insert', 'home': 'Home', 'end': 'End',
                'tab': 'Tab',
                '=': 'equal', '-': 'minus', '+': 'plus',
                '[': 'bracketleft', ']': 'bracketright',
                '\\': 'backslash', ';': 'semicolon', "'": 'apostrophe',
                ',': 'comma', '.': 'period', '/': 'slash', '`': 'grave',
                '0': '0', '1': '1', '2': '2',
                **{f'f{i}': f'F{i}' for i in range(1, 13)},
            }
            tk_key  = _key_map.get(key, key)
            mod_map = {'ctrl': 'Control', 'shift': 'Shift', 'alt': 'Alt'}
            tk_mods = [mod_map.get(m, m.capitalize()) for m in mods]
            inner   = '-'.join(tk_mods + [tk_key]) if tk_mods else tk_key
            return f'<{inner}>'

        def _make_cb(method, args):
            def _cb(e, _m=method, _a=args):
                try:
                    _m(*_a)
                except Exception:
                    pass
            return _cb

        for action_id, (method_name, extra_args) in self._ACTION_MAP.items():
            if action_id in _EXCLUDED:
                continue
            combo = hk.get(action_id) or self._DEFAULT_HOTKEYS.get(action_id)
            if not combo:
                continue
            seq = _to_tk_seq(combo)
            if not seq:
                continue
            method = getattr(self, method_name, None)
            if method is None:
                continue
            try:
                cbid = w.bind(seq, _make_cb(method, extra_args), add=True)
                self._registered_cbids.append((seq, cbid))
                # Also bind the uppercase variant for bare single-letter keys
                if len(seq) == 3 and seq[1].isalpha() and seq[1].islower():
                    upper_seq = f'<{seq[1].upper()}>'
                    cbid2 = w.bind(upper_seq, _make_cb(method, extra_args), add=True)
                    self._registered_cbids.append((upper_seq, cbid2))
            except Exception:
                pass

    # ── Extra action methods referenced by _ACTION_MAP ────────────────────────

    def _copy_video_path(self):
        """Copy the current video path to clipboard."""
        try:
            import struct
            path = self.videos[self.index]
            # Try Windows CF_HDROP first (copies as a file, not just text)
            try:
                import win32clipboard as wcb
                import win32con
                file_struct = struct.pack("Iiiii", 20, 0, 0, 0, 1)
                files = (path + "\0").encode("utf-16le") + b"\0\0"
                data  = file_struct + files
                wcb.OpenClipboard()
                wcb.EmptyClipboard()
                wcb.SetClipboardData(win32con.CF_HDROP, data)
                wcb.CloseClipboard()
            except Exception:
                self._win.clipboard_clear()
                self._win.clipboard_append(path)
            if self.logger:
                self.logger(f"Copied: {path}")
        except Exception as e:
            if self.logger:
                self.logger(f"Copy error: {e}")

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

        self._clear_ab()
        self._embed()
        media = self._instance.media_new(path)
        self._player.set_media(media)
        self._player.play()
        if self.on_video_changed:
            try:
                self._win.after(0, lambda p=path, i=idx: self.on_video_changed(i, p))
            except Exception:
                pass

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
        # If sleep-at-end-of-video was requested, close the player now.
        if self._sleep_remaining == -1:
            self._sleep_remaining = 0
            if self.logger:
                self.logger("Sleep timer: closing after video ended")
            self._win.after(0, self._close)
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

    def _setup_hold_button(self, btn: tk.Button,
                           on_click: Callable,
                           on_hold:  Callable,
                           hold_delay_ms: int = 500,
                           repeat_ms:     int = 100):
        """
        Wire a button so that:
          • a short press  (<hold_delay_ms) fires on_click  (prev / next video)
          • holding down   (≥hold_delay_ms) fires on_hold repeatedly every
            repeat_ms ms   (rewind / fast-forward)

        The distinction is made entirely on the client side using Tk after() jobs,
        so no threading is needed.
        """
        state = {"hold_job": None, "fired": False}

        def _start_hold():
            state["fired"] = True
            on_hold()
            state["hold_job"] = btn.after(repeat_ms, _start_hold)

        def _on_press(e):
            state["fired"] = False
            self._holding = True
            self._cancel_hide()
            state["hold_job"] = btn.after(hold_delay_ms, _start_hold)

        def _on_release(e):
            self._holding = False
            if state["hold_job"] is not None:
                btn.after_cancel(state["hold_job"])
                state["hold_job"] = None
            if not state["fired"]:
                on_click()
            self._schedule_hide()

        btn.config(command=None)
        btn.bind("<ButtonPress-1>",   _on_press,   add=True)
        btn.bind("<ButtonRelease-1>", _on_release, add=True)

    def _fast_forward(self):
        """Seek +200 ms — mirrors vlc_player_controller.fast_forward."""
        try:
            current_time = self._player.get_time()
            new_time = current_time + 200
            length = self._player.get_length()
            if 0 < length < new_time:
                new_time = length - 20
            self._player.set_time(new_time)
            if self.logger:
                self.logger(f"Fast forward to {new_time / 1000:.1f}s")
        except Exception:
            pass

    def _rewind(self):
        """Seek -200 ms — mirrors vlc_player_controller.rewind."""
        try:
            current_time = self._player.get_time()
            new_time = max(0, current_time - 200)
            self._player.set_time(new_time)
            if self.logger:
                self.logger(f"Rewind to {new_time / 1000:.1f}s")
        except Exception:
            pass

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
        if self.on_volume_change:
            try:
                self.on_volume_change(self.volume, self.is_muted)
            except Exception:
                pass

    def _toggle_mute(self):
        self.is_muted = not self.is_muted
        self._player.audio_set_mute(self.is_muted)
        if not self.is_muted:
            self._player.audio_set_volume(self.volume)
        self._refresh_vol()
        if self.on_volume_change:
            try:
                self.on_volume_change(self.volume, self.is_muted)
            except Exception:
                pass

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
        if self.on_loop_change:
            try:
                self.on_loop_change(self.loop_mode)
            except Exception:
                pass

    # ═══════════════════════════════════════════════════════════════════
    # ROTATE
    # ═══════════════════════════════════════════════════════════════════

    def _rotate_right(self):
        self._rotation_index = (self._rotation_index + 1) % 4
        self._apply_transforms(rotation_only=True)

    def _toggle_flip_h(self):
        self._flip_h = not self._flip_h
        self._apply_transforms()

    def _apply_transforms(self, rotation_only=False):
        if not self._player or not self.videos:
            return
        try:
            angle = self._ROTATION_STEPS[self._rotation_index]
            position_ms = self._player.get_time() or 0
            was_playing = self._player.is_playing()
            path = self.videos[self.index]
            base_args = ['--quiet', '--no-video-title-show']
            if os.name == 'nt':
                base_args += ['--aout=directsound']
            else:
                base_args += ['--aout=pulse']
            if rotation_only:
                transform_type = self._TRANSFORM_MAP[angle]
                if transform_type != "identity":
                    base_args += ['--video-filter=transform',
                                  f'--transform-type={transform_type}']
            else:
                transform_type = None
                if self._flip_h:
                    transform_type = "hflip"
                filters = []
                filter_opts = []
                if angle != 0:
                    filters.append("rotate")
                    filter_opts.append(f"--rotate-angle={angle}")
                if transform_type:
                    filters.append("transform")
                    filter_opts.append(f"--transform-type={transform_type}")

                if filters:
                    base_args.append(f"--video-filter={','.join(filters)}")
                    base_args.extend(filter_opts)

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

    def _zoom_in(self):
        self._zoom(+0.1)

    def _zoom_out(self):
        self._zoom(-0.1)

    def _show_zoom_menu(self):
        menu = tk.Menu(self._win, tearoff=0, bg=_BTN, fg=_TXT,
                       activebackground=_BTN_HVR, activeforeground=_TXT,
                       bd=0, relief=tk.FLAT)
        menu.add_command(label="🔍+  Zoom In", command=self._zoom_in)
        menu.add_command(label="🔍−  Zoom Out", command=self._zoom_out)
        menu.add_command(label="🔍1  Reset Zoom", command=lambda: self._zoom(0))
        menu.add_separator()
        menu.add_command(label="⟳  Rotate", command=self._rotate_right)
        menu.add_separator()
        menu.add_command(label="↔  Flip Horizontal", command=self._toggle_flip_h)
        menu.add_command(label="⟳⟲  Reset Rotate/Flip",
                         command=lambda: (setattr(self, '_rotation_index', 0),
                                          setattr(self, '_flip_h', False),
                                          self._apply_transforms()))
        try:
            x = self._win.winfo_pointerx()
            y = self._win.winfo_pointery()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

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
    # CHAPTER NAVIGATION  (mirrors vlc_player_controller.py)
    # ═══════════════════════════════════════════════════════════════════

    def _next_chapter(self):
        try:
            ch_count = self._player.get_chapter_count()
            if ch_count and ch_count > 0:
                cur = self._player.get_chapter()
                if cur < ch_count - 1:
                    self._player.set_chapter(cur + 1)
                    if self.logger:
                        self.logger(f"Chapter {cur + 2} of {ch_count}")
                else:
                    self._next()          # last chapter → advance to next video
            else:
                if self.logger:
                    self.logger("No chapters in this file")
        except Exception as e:
            if self.logger:
                self.logger(f"Chapter next error: {e}")

    def _prev_chapter(self):
        try:
            ch_count = self._player.get_chapter_count()
            if ch_count and ch_count > 0:
                cur = self._player.get_chapter()
                if cur > 0:
                    self._player.set_chapter(cur - 1)
                    if self.logger:
                        self.logger(f"Chapter {cur} of {ch_count}")
                else:
                    self._prev()          # first chapter → go to previous video
            else:
                if self.logger:
                    self.logger("No chapters in this file")
        except Exception as e:
            if self.logger:
                self.logger(f"Chapter prev error: {e}")

    # ═══════════════════════════════════════════════════════════════════
    # SUBTITLES  (mirrors vlc_player_controller.py)
    # ═══════════════════════════════════════════════════════════════════

    def _toggle_subtitle(self):
        """If subtitles are currently off, enable the first (or next) track.
        If a track is already active, disable subtitles."""
        try:
            current = self._player.video_get_spu()
            if current == -1:
                self._cycle_subtitle()   # off → turn on (first/next track)
            else:
                self._disable_subtitle() # on  → turn off
        except Exception as e:
            if self.logger:
                self.logger(f"Subtitle toggle error: {e}")

    def _cycle_subtitle(self):
        try:
            track_count = self._player.video_get_spu_count()
            if not track_count or track_count <= 0:
                if self.logger:
                    self.logger("No subtitle tracks available")
                return
            current = self._player.video_get_spu()
            tracks  = self._player.video_get_spu_description()
            track_ids = [t[0] for t in tracks] if tracks else []
            if not track_ids:
                return
            if current == -1 or current not in track_ids:
                self._player.video_set_spu(track_ids[0])
                name = tracks[0][1]
                name = name.decode() if isinstance(name, bytes) else name
            else:
                idx      = track_ids.index(current)
                next_idx = (idx + 1) % len(track_ids)
                self._player.video_set_spu(track_ids[next_idx])
                name = tracks[next_idx][1]
                name = name.decode() if isinstance(name, bytes) else name
            if self.logger:
                self.logger(f"Subtitles: {name}")
        except Exception as e:
            if self.logger:
                self.logger(f"Subtitle error: {e}")

    def _disable_subtitle(self):
        try:
            self._player.video_set_spu(-1)
            if self.logger:
                self.logger("Subtitles disabled")
        except Exception as e:
            if self.logger:
                self.logger(f"Subtitle disable error: {e}")

    def load_subtitle_file(self, path: str):
        """External API: load an external subtitle file."""
        try:
            result = self._player.add_slave(vlc.MediaSlaveType.subtitle, path, True)
            if self.logger:
                status = "loaded" if result == 0 else "failed"
                self.logger(f"Subtitle file {status}: {os.path.basename(path)}")
        except Exception as e:
            if self.logger:
                self.logger(f"Subtitle load error: {e}")

    # ═══════════════════════════════════════════════════════════════════
    # A-B LOOP  (mirrors vlc_player_controller.py, Tk-based monitor)
    # ═══════════════════════════════════════════════════════════════════

    def _set_ab_a(self):
        self._ab_point_a    = self._player.get_time()
        self._ab_point_b    = None
        self._ab_loop_active = False
        self._cancel_ab_monitor()
        if self.logger:
            self.logger(f"A-B: A set at {_fmt(self._ab_point_a)}")

    def _set_ab_b(self):
        if self._ab_point_a is None:
            if self.logger:
                self.logger("A-B: set point A first")
            return
        b = self._player.get_time()
        if b <= self._ab_point_a:
            if self.logger:
                self.logger("A-B: point B must be after A")
            return
        self._ab_point_b    = b
        self._ab_loop_active = True
        if self.logger:
            self.logger(f"A-B: B set at {_fmt(self._ab_point_b)} — looping")
        self._start_ab_monitor()

    def _clear_ab(self):
        self._ab_point_a    = None
        self._ab_point_b    = None
        self._ab_loop_active = False
        self._cancel_ab_monitor()
        try:
            self._lbl_ab.config(text="")
            self._btn_ab_a.config(bg=_BTN)
            self._btn_ab_b.config(bg=_BTN)
            self._btn_ab_clr.config(fg=_TXT_DIM)
        except Exception:
            pass
        if self.logger:
            self.logger("A-B loop cleared")

    def _start_ab_monitor(self):
        self._cancel_ab_monitor()
        self._ab_monitor_tick()

    def _ab_monitor_tick(self):
        if not self._running or not self._ab_loop_active:
            return
        try:
            if (self._ab_point_b is not None and
                    self._player.get_time() >= self._ab_point_b):
                self._player.set_time(self._ab_point_a)
        except Exception:
            pass
        try:
            self._ab_monitor_job = self._win.after(100, self._ab_monitor_tick)
        except Exception:
            pass

    def _cancel_ab_monitor(self):
        if self._ab_monitor_job:
            try:
                self._win.after_cancel(self._ab_monitor_job)
            except Exception:
                pass
            self._ab_monitor_job = None

    # ═══════════════════════════════════════════════════════════════════
    # SLEEP TIMER
    # ═══════════════════════════════════════════════════════════════════

    def _show_sleep_menu(self):
        """Pop a small menu to choose a sleep duration."""
        menu = tk.Menu(self._win, tearoff=0, bg=_BTN, fg=_TXT,
                       activebackground=_BTN_HVR, activeforeground=_TXT,
                       bd=0, relief=tk.FLAT)
        options = [
            ("1 minute",   1 * 60),
            ("5 minutes",  5 * 60),
            ("10 minutes", 10 * 60),
            ("15 minutes", 15 * 60),
            ("30 minutes", 30 * 60),
            ("45 minutes", 45 * 60),
            ("60 minutes", 60 * 60),
            ("End of video", -1),
        ]
        for label, secs in options:
            menu.add_command(
                label=label,
                command=lambda s=secs: self._start_sleep_timer(s))
        if self._sleep_timer_job is not None:
            menu.add_separator()
            menu.add_command(label="✕  Cancel timer", command=self._cancel_sleep_timer)
        try:
            x = self._win.winfo_pointerx()
            y = self._win.winfo_pointery()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _start_sleep_timer(self, seconds: int):
        self._cancel_sleep_timer()
        if seconds == -1:
            # sleep at end of current video — handled by _on_media_ended override
            self._sleep_remaining = -1
            try:
                self._lbl_sleep.config(text="⏻ end")
            except Exception:
                pass
            if self.logger:
                self.logger("Sleep timer: will pause after current video")
        else:
            self._sleep_remaining = seconds
            self._sleep_tick()
            if self.logger:
                self.logger(f"Sleep timer: {seconds // 60} min")

    def _sleep_tick(self):
        if not self._running or self._sleep_remaining <= 0:
            return
        self._sleep_remaining -= 1
        m, s = divmod(self._sleep_remaining, 60)
        try:
            self._lbl_sleep.config(text=f"⏻ {m}:{s:02d}")
        except Exception:
            pass
        if self._sleep_remaining == 0:
            self._do_sleep_pause()
        else:
            try:
                self._sleep_timer_job = self._win.after(1000, self._sleep_tick)
            except Exception:
                pass

    def _do_sleep_pause(self):
        self._sleep_remaining = 0
        self._sleep_timer_job = None
        try:
            self._lbl_sleep.config(text="")
        except Exception:
            pass
        if self.logger:
            self.logger("Sleep timer: closing player")
        self._close()

    def _cancel_sleep_timer(self):
        if self._sleep_timer_job:
            try:
                self._win.after_cancel(self._sleep_timer_job)
            except Exception:
                pass
            self._sleep_timer_job = None
        self._sleep_remaining = 0
        try:
            self._lbl_sleep.config(text="")
        except Exception:
            pass
        if self.logger:
            self.logger("Sleep timer cancelled")

    def _show_context_menu_from_btn(self):
        try:
            x = self._win.winfo_pointerx()
            y = self._win.winfo_pointery()
        except Exception:
            x, y = self._win.winfo_rootx() + 100, self._win.winfo_rooty() + 100

        class _FakeEvent:
            pass
        e = _FakeEvent()
        e.x_root = x
        e.y_root = y
        self._show_context_menu(e)

    def _show_context_menu(self, event):
        if not self.videos:
            return
        menu = tk.Menu(self._win, tearoff=0, bg=_BTN, fg=_TXT,
                       activebackground=_BTN_HVR, activeforeground=_TXT,
                       bd=0, relief=tk.FLAT)
        path = self.videos[self.index]
        if self.on_add_to_playlist:
            menu.add_command(label="➕  Add to Playlist",
                             command=lambda: self.on_add_to_playlist([path]))
        if self.on_add_to_queue:
            menu.add_command(label="🎵  Add to Queue",
                             command=lambda: self.on_add_to_queue([path]))
        if self.on_add_to_favourites:
            menu.add_command(label="★  Add to Favourites",
                             command=lambda: self.on_add_to_favourites([path]))
        menu.add_separator()
        menu.add_command(label="📸  Screenshot",      command=self._screenshot)
        try:
            has_subtitles = False
            spu_count = self._player.video_get_spu_count()
            if spu_count and spu_count > 0:
                tracks = self._player.video_get_spu_description()
                if tracks and len(tracks) > 0:
                    has_subtitles = True
        except Exception:
            has_subtitles = False

        if has_subtitles:
            menu.add_separator()
            menu.add_command(label="💬  Subtitle", command=self._toggle_subtitle)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ═══════════════════════════════════════════════════════════════════
    # FULLSCREEN / BORDERLESS
    # ═══════════════════════════════════════════════════════════════════

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
                        if idle >= self.INACTIVITY_S and self._ctrl_visible and not self._hide_job and not self._holding:
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
            # A-B loop region
            try:
                pt_a = self._ab_point_a
                pt_b = self._ab_point_b
                if pt_a is not None:
                    ax = int((pt_a / dur) * w)
                    if pt_b is not None:
                        bx = int((pt_b / dur) * w)
                        sc.create_rectangle(ax, cy - 2, bx, cy + 2,
                                            fill="#00BFFF", outline="", stipple="gray50")
                    sc.create_line(ax, 0, ax, h, fill="#00BFFF", width=2)
                    sc.create_text(ax + 2, 2, text="A", anchor="nw",
                                   font=("Segoe UI", 7, "bold"), fill="#00BFFF")
                if pt_b is not None:
                    bx = int((pt_b / dur) * w)
                    sc.create_line(bx, 0, bx, h, fill="#00BFFF", width=2)
                    sc.create_text(bx - 2, 2, text="B", anchor="ne",
                                   font=("Segoe UI", 7, "bold"), fill="#00BFFF")
            except Exception:
                pass
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
        # Chapter info badge
        try:
            ch_count = self._player.get_chapter_count()
            if ch_count and ch_count > 0:
                ch_cur = self._player.get_chapter()
                self._lbl_chapter.config(text=f"Ch {ch_cur + 1}/{ch_count}")
                if not self._chapters_visible:
                    # Show chapter navigation buttons
                    self._btn_prev_chapter.pack(side=tk.LEFT, padx=(6, 1),
                                                before=self._divider_before_ab)
                    self._btn_next_chapter.pack(side=tk.LEFT, padx=(1, 8),
                                                before=self._divider_before_ab)
                    self._chapters_visible = True
            else:
                self._lbl_chapter.config(text="")
                if self._chapters_visible:
                    # Hide chapter navigation buttons
                    self._btn_prev_chapter.pack_forget()
                    self._btn_next_chapter.pack_forget()
                    self._chapters_visible = False
        except Exception:
            self._lbl_chapter.config(text="")
        # A-B loop badge + button highlight states
        try:
            if self._ab_loop_active and self._ab_point_a is not None and self._ab_point_b is not None:
                self._lbl_ab.config(text=f"⟳ {_fmt(self._ab_point_a)}–{_fmt(self._ab_point_b)}")
                self._btn_ab_a.config(bg="#003d5c", fg="#00BFFF")
                self._btn_ab_b.config(bg="#003d5c", fg="#00BFFF")
                self._btn_ab_clr.config(fg=_TXT)
            elif self._ab_point_a is not None:
                self._lbl_ab.config(text=f"A {_fmt(self._ab_point_a)}…")
                self._btn_ab_a.config(bg="#003d5c", fg="#00BFFF")
                self._btn_ab_b.config(bg=_BTN, fg="#00BFFF")
                self._btn_ab_clr.config(fg=_TXT_DIM)
            else:
                self._lbl_ab.config(text="")
                self._btn_ab_a.config(bg=_BTN, fg="#00BFFF")
                self._btn_ab_b.config(bg=_BTN, fg="#00BFFF")
                self._btn_ab_clr.config(fg=_TXT_DIM)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════
    # CLOSE
    # ═══════════════════════════════════════════════════════════════════

    def _close(self):
        # Snapshot current playback state before any teardown so the host can
        # persist it (last-played index, path, loop mode, volume, mute).
        if self.on_close_save:
            try:
                cur_path = self.videos[self.index] if self.videos else ""
                self.on_close_save(self.index, cur_path, self.loop_mode,
                                   self.volume, self.is_muted)
            except Exception:
                pass

        self._running = False
        # Stop A-B loop monitor
        self._ab_loop_active = False

        # Unbind hotkey cbids we registered so nothing fires after destroy
        for seq, cbid in getattr(self, '_registered_cbids', []):
            try:
                self._win.unbind(seq, cbid)
            except Exception:
                pass
        self._registered_cbids = []

        # cancel pending jobs
        for attr in ("_hide_job", "_poll_job", "_update_job",
                     "_ab_monitor_job", "_sleep_timer_job"):
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