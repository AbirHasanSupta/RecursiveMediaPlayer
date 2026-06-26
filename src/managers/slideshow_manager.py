import tkinter as tk
from tkinter import filedialog
from tkinter import font as tkfont
from PIL import Image, ImageTk, ImageEnhance, ImageFilter
import os
import threading
import time
import random
import glob

from utils import is_photo, is_audio, PHOTO_EXTENSIONS, AUDIO_EXTENSIONS
from managers.settings_manager import DEFAULT_HOTKEYS
from managers.resource_manager import get_resource_manager


# Fixed dark palette — always matches embedded player (not app light/dark toggle).
_BG       = "#0F1217"
_CTRL_BG  = "#0F1217"
_CTRL_BG2 = "#1A1E26"
_ACCENT   = "#7B9CFF"
_ACCENT_HVR = "#9BB0FF"
_TXT      = "#E2E8F0"
_TXT_MED  = "#8A99B5"
_TXT_DIM  = "#4A5568"
_BTN      = "#1A1E26"
_BTN_HVR  = "#252C38"
_BTN_ACT  = "#2F3849"
_TRACK    = "#252C38"
_BORDER   = "#2A303C"
_PLAY_FG  = "#0F1217"
_SUCCESS  = "#34c98a"


def _init_pygame():
    try:
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
        return pygame
    except Exception:
        return None


class SlideshowManager:
    """
    Photo slideshow window with:
    - Configurable duration per slide
    - Transitions: fade, slide_left, slide_right, zoom_in, zoom_out, none
    - Ken Burns effect (slow pan + zoom)
    - Prev / Next / Pause / Play controls
    - Audio playlist: add individual songs or full folder, prev/next/mute/volume
    - Loop audio playlist continuously
    """

    TRANSITIONS = ["fade", "slide_left", "slide_right", "zoom_in", "zoom_out", "none"]
    TRANSITION_LABELS = {
        "fade":       "Fade",
        "slide_left": "Slide Left",
        "slide_right":"Slide Right",
        "zoom_in":    "Zoom In",
        "zoom_out":   "Zoom Out",
        "none":       "Cut",
    }

    INACTIVITY_S = 2.0

    def __init__(self, root, theme_provider, logger=None):
        self.root         = root
        self.theme_provider = theme_provider
        self.logger       = logger or (lambda m: None)

        # Slideshow state
        self.photos             = []
        self.index              = 0
        self.playing            = False
        self.duration           = 4.0
        self.transition         = "fade"
        self.ken_burns          = True
        self.transition_duration = 0.6
        self._trans_display_var = None

        # Audio state
        self._songs             = []
        self._song_index        = 0
        self._audio_volume      = 0.7
        self._audio_muted       = False
        self._pygame            = None
        self._audio_monitor_id  = None

        # Internal
        self._win               = None
        self._canvas            = None
        self._current_pil       = None
        self._photo_img         = None
        self._canvas_img_id     = None
        self._after_id          = None
        self._transition_after  = None
        self._kb_after          = None
        self._kb_start          = None
        self._kb_params         = None
        self._preload_cache     = {}
        self._closing           = False

        # ── Photo editing state ───────────────────────────────────────────────
        # Per-photo transform dict: stores cumulative edits applied in memory.
        # Keyed by photo path so edits survive photo navigation within the session.
        self._edit_transforms   = {}   # {path: transform_dict}
        self._edit_history      = {}   # {path: [list of transform_dict snapshots]}
        self._edit_redo_stack   = {}   # {path: [list of transform_dict snapshots]}
        self._edit_mode         = False
        self._crop_active       = False
        self._crop_start        = None  # (canvas_x, canvas_y)
        self._crop_rect_id      = None
        # Zoom & Temporary Rotate state
        self._zoom_factor       = 1.0
        self._zoom_offset_x     = 0.0
        self._zoom_offset_y     = 0.0
        self._temp_rotation     = 0
        # Edit bar widget refs
        self._edit_bar          = None
        self._edit_btn          = None  # the ✏ Edit toggle button in the main bar
        self._undo_btn          = None
        self._redo_btn          = None
        self._save_btn          = None

        # UI widget refs (set in _build_window)
        self._play_btn          = None
        self._btn_prev          = None
        self._btn_next          = None
        self._btn_first         = None
        self._btn_last          = None
        self._counter_lbl       = None
        self._ctrl_counter_lbl  = None
        self._pause_lbl         = None
        self._progress_canvas   = None
        self._now_playing_lbl   = None
        self._mute_btn          = None
        self._vol_canvas        = None
        self._dur_var           = None
        self._trans_var         = None
        self._trans_display_var = None
        self._kb_var            = None
        self._dur_spin          = None
        self._trans_om          = None
        self._kb_chk            = None
        self._title_lbl         = None
        self._fs_btn            = None
        self._mode_lbl          = None
        self._fullscreen        = False
        self._pre_fs_geo        = "1280x820"   # saved geometry before borderless FS
        self._slideshow_mode    = False
        self._bar               = None  # single overlay bar (place-based)
        self._chrome_visible    = True
        self._hide_job          = None
        self._poll_job          = None
        self._last_mouse        = (-1, -1)
        self._last_move_t       = time.monotonic()
        self._hotkeys           = dict(DEFAULT_HOTKEYS)
        self._registered_cbids  = []
        self._fit_cache         = {}  # (path, cw, ch) -> rendered PIL
        self._ui_frames         = {}
        # Titlebar overlay (borderless fullscreen, same as embedded_player)
        self._titlebar          = None
        self._titlebar_job      = None
        self._titlebar_anim     = None
        self._tb_zone           = None
        self._tb_h              = 32
        self._tb_shown          = False
        self._tb_y              = -32
        # Music bar widget refs (inline controls)
        self._music_btn_frame   = None
        self._btn_prev_song     = None
        self._btn_next_song     = None
        self._btn_shuffle       = None
        self._btn_add_music     = None
        get_resource_manager().register_cleanup_callback(self.cleanup)

    def _ctrl(self):
        """Always return embedded-player dark control colours."""
        return {
            "bg": _CTRL_BG,
            "bg2": _CTRL_BG2,
            "surface": _BTN,
            "txt": _TXT,
            "txt_med": _TXT_MED,
            "txt_dim": _TXT_DIM,
            "accent": _ACCENT,
            "accent_hvr": _ACCENT_HVR,
            "btn": _BTN,
            "btn_hvr": _BTN_HVR,
            "btn_act": _BTN_ACT,
            "track": _TRACK,
            "border": _BORDER,
            "canvas": "#000000",
            "play_fg": _PLAY_FG,
            "success": _SUCCESS,
        }

    def _fonts(self):
        return {
            "title": tkfont.Font(family="Segoe UI", size=11, weight="bold"),
            "sm": tkfont.Font(family="Segoe UI", size=8),
            "md": tkfont.Font(family="Segoe UI", size=10),
            "ico": tkfont.Font(family="Segoe UI", size=13),
            "acc": tkfont.Font(family="Segoe UI", size=8, weight="bold"),
            "xs": tkfont.Font(family="Segoe UI", size=7),
        }

    def _sep(self, parent, pady=4, padx=5):
        c = self._ctrl()
        tk.Frame(parent, width=1, bg=c["border"]).pack(
            side=tk.LEFT, fill=tk.Y, pady=pady, padx=padx)

    def _make_btn(self, parent, text, cmd, *, font=None, fg=None, accent=False, padx=8, pady=5):
        c = self._ctrl()
        F = self._fonts()
        if accent:
            b = tk.Button(
                parent, text=text, command=cmd, font=font or F["ico"],
                bg=c["accent"], fg=c["play_fg"], bd=0, padx=padx, pady=pady,
                relief=tk.FLAT, cursor="hand2",
                activebackground=c["accent_hvr"], activeforeground=c["play_fg"],
            )
            b.bind("<Enter>", lambda e, w=b: w.configure(bg=c["accent_hvr"]))
            b.bind("<Leave>", lambda e, w=b: w.configure(bg=c["accent"]))
        else:
            b = tk.Button(
                parent, text=text, command=cmd, font=font or F["ico"],
                bg=c["btn"], fg=fg or c["txt_med"], bd=0, padx=padx, pady=pady,
                relief=tk.FLAT, cursor="hand2",
                activebackground=c["btn_act"], activeforeground=c["txt"],
            )
            b.bind("<Enter>", lambda e, w=b: w.configure(bg=c["btn_hvr"]))
            b.bind("<Leave>", lambda e, w=b: w.configure(bg=c["btn"]))
        b._accent = accent
        b._btn_fg = fg
        b.bind("<Enter>", lambda e: self._cancel_chrome_hide(), add="+")
        b.bind("<Leave>", lambda e: self._schedule_chrome_hide(), add="+")
        return b

    def _restyle_btn(self, btn, *, accent=False, fg=None):
        if not btn or not btn.winfo_exists():
            return
        c = self._ctrl()
        if accent:
            btn.configure(
                bg=c["accent"], fg=c["play_fg"],
                activebackground=c["accent_hvr"], activeforeground=c["play_fg"],
            )
        else:
            btn.configure(
                bg=c["btn"], fg=fg or c["txt_med"],
                activebackground=c["btn_act"], activeforeground=c["txt"],
            )

    def _restyle_transport_btns(self):
        for btn in (self._btn_first, self._btn_prev, self._btn_next, self._btn_last):
            if btn:
                self._restyle_btn(btn, fg=getattr(btn, '_btn_fg', None))
        if self._play_btn:
            self._restyle_btn(self._play_btn, accent=True)

    def _style_option_menu(self, om, width=11):
        c = self._ctrl()
        F = self._fonts()
        om.config(
            font=F["sm"], bg=c["surface"], fg=c["txt"],
            activebackground=c["btn_hvr"], activeforeground=c["txt"],
            relief=tk.FLAT, highlightthickness=1,
            highlightbackground=c["border"], width=width,
        )
        om["menu"].config(
            bg=c["surface"], fg=c["txt"],
            activebackground=c["btn_hvr"], activeforeground=c["txt"],
            relief=tk.FLAT,
        )

    def _style_spinbox(self, spin):
        c = self._ctrl()
        F = self._fonts()
        spin.config(
            font=F["sm"], bg=c["surface"], fg=c["txt"],
            relief=tk.FLAT, bd=0, highlightthickness=1,
            highlightbackground=c["border"],
            buttonbackground=c["surface"],
            insertbackground=c["txt"],
        )

    def _context_menu(self):
        c = self._ctrl()
        return tk.Menu(
            self._win, tearoff=0, bg=c["surface"], fg=c["txt"],
            activebackground=c["btn_hvr"], activeforeground=c["txt"], relief=tk.FLAT,
            font=("Segoe UI", 10),
        )

    def apply_theme(self):
        """Re-apply fixed dark chrome (slideshow is always dark like embedded player)."""
        if not self._win:
            return
        try:
            if not self._win.winfo_exists():
                return
        except tk.TclError:
            return
        c = self._ctrl()
        self._win.configure(bg=c["canvas"])
        if self._canvas and self._canvas.winfo_exists():
            self._canvas.configure(bg=c["canvas"])
        if self._bar and self._bar.winfo_exists():
            self._bar.configure(bg=c["bg"])
        if self._progress_canvas and self._progress_canvas.winfo_exists():
            self._progress_canvas.configure(bg=c["bg"])
        if self._vol_canvas and self._vol_canvas.winfo_exists():
            self._vol_canvas.configure(bg=c["bg"])
        if getattr(self, '_now_playing_lbl', None) and self._now_playing_lbl.winfo_exists():
            self._now_playing_lbl.configure(bg=c["bg"], fg=c["txt_dim"])
        self._update_progress()
        self._draw_vol_slider()
        self._update_play_btn()
        self._update_pause_label()
        self._restyle_transport_btns()
        if hasattr(self.theme_provider, 'apply_title_bar_theme'):
            self.theme_provider.apply_title_bar_theme(self._win)
        self._place_bar()

    def _reset_widget_state(self):
        """Clear canvas/widget refs after window destroy (fixes blank reopen)."""
        self._canvas            = None
        self._photo_img         = None
        self._canvas_img_id     = None
        self._play_btn          = None
        self._btn_prev          = None
        self._btn_next          = None
        self._btn_first         = None
        self._btn_last          = None
        self._counter_lbl       = None
        self._ctrl_counter_lbl  = None
        self._pause_lbl         = None
        self._progress_canvas   = None
        self._now_playing_lbl   = None
        self._mute_btn          = None
        self._vol_canvas        = None
        self._dur_var           = None
        self._trans_var         = None
        self._trans_display_var = None
        self._kb_var            = None
        self._dur_spin          = None
        self._trans_om          = None
        self._kb_chk            = None
        self._title_lbl         = None
        self._fs_btn            = None
        self._mode_lbl          = None
        self._bar               = None
        self._registered_cbids  = []
        self._ui_frames         = {}
        self._chrome_visible    = True
        self._hide_job          = None
        self._poll_job          = None
        # Titlebar
        self._titlebar          = None
        self._titlebar_job      = None
        self._titlebar_anim     = None
        self._tb_zone           = None
        self._tb_shown          = False
        # Music bar buttons
        self._music_btn_frame   = None
        self._btn_prev_song     = None
        self._btn_next_song     = None
        self._btn_shuffle       = None
        self._btn_add_music     = None
        # Edit bar
        self._edit_bar          = None
        self._edit_btn          = None
        self._undo_btn          = None
        self._redo_btn          = None

    def apply_settings(self, settings):
        """Sync slideshow defaults from app settings."""
        if not settings:
            return
        self.duration = getattr(settings, 'slideshow_duration', self.duration)
        self.transition = getattr(settings, 'slideshow_transition', self.transition)
        self.ken_burns = getattr(settings, 'slideshow_ken_burns', self.ken_burns)
        if self._dur_var:
            try:
                self._dur_var.set(self.duration)
            except Exception:
                pass
        if self._trans_display_var and self.transition in self.TRANSITION_LABELS:
            self._trans_display_var.set(self.TRANSITION_LABELS[self.transition])
        if self._kb_var:
            self._kb_var.set(self.ken_burns)

    def cleanup(self):
        self.close()

    def show(self, photos, start_index=0, slideshow_mode=False):
        if not photos:
            return
        self.photos  = list(photos)
        self.index   = max(0, min(start_index, len(photos) - 1))
        self._closing = False
        self._fit_cache.clear()
        self._slideshow_mode = slideshow_mode
        self.playing = slideshow_mode

        if self._win and self._win.winfo_exists():
            self._win.lift()
            self._apply_slideshow_mode_ui()
            self.apply_theme()
            self._show_chrome()
            self._start_mouse_poll()
            self._load_current()
            if self.playing:
                self._schedule_next()
            else:
                self._cancel_timers()
            self._update_play_btn()
            return

        self._build_window()
        self._apply_slideshow_mode_ui()
        self._load_current()
        if self.playing:
            self._schedule_next()
        self._update_play_btn()

    def close(self):
        self._closing = True
        self._cancel_chrome_hide()
        self._stop_mouse_poll()
        self._cancel_timers()
        self._stop_audio()
        # Tear down borderless state before destroying the window
        if self._fullscreen:
            self._destroy_titlebar()
            try:
                if self._win and self._win.winfo_exists():
                    self._win.overrideredirect(False)
            except Exception:
                pass
            self._fullscreen = False
        if self._win and self._win.winfo_exists():
            try:
                self._win.destroy()
            except Exception:
                pass
        self._win = None
        self._reset_widget_state()
        self._fit_cache.clear()


    def set_hotkeys(self, hotkeys):
        """Live-reload key bindings from settings (same actions as embedded player)."""
        self._hotkeys = dict(hotkeys) if hotkeys else dict(DEFAULT_HOTKEYS)
        if self._win and self._win.winfo_exists():
            self._rebind_keys(self._win)

    # ── Window construction ───────────────────────────────────────────────────

    def _build_window(self):
        self._reset_widget_state()
        self._canvas_img_id = None
        c = self._ctrl()
        win = tk.Toplevel(self.root)
        win.title("Photo Viewer")
        win.configure(bg=c["canvas"])
        win.geometry("1280x820")
        win.protocol("WM_DELETE_WINDOW", self.close)
        self._win = win

        try:
            from icon_helper import apply_icon
            apply_icon(win)
        except Exception:
            pass

        # Canvas fills the ENTIRE window — never resizes when bar shows/hides
        self._build_canvas(win)
        # Single overlay bar placed on top of the canvas (embedded-player style)
        self._build_overlay_bar(win)
        # Edit bar (top overlay, hidden by default)
        self._build_edit_bar(win)
        self._bind_keys(win)
        self.apply_theme()
        self._update_play_btn()
        self._update_counter()
        self._setup_chrome_autohide()
        self._show_chrome()
        self._start_mouse_poll()

    # ── Bar placement (overlay, like embedded video player) ──────────────────

    def _place_bar(self):
        """Position the overlay bar at the bottom of the canvas via place()."""
        if not self._bar or not self._win:
            return
        try:
            if self._bar.winfo_exists() and self._chrome_visible:
                self._bar.place(relx=0.0, rely=1.0, anchor="sw", relwidth=1.0)
                self._bar.lift()
        except Exception:
            pass

    # ── Chrome auto-hide (embedded-player style) ──────────────────────────────

    def _chrome_widgets(self):
        return [w for w in (self._bar,) if w]

    def _pointer_over_chrome(self):
        try:
            mx = self._win.winfo_pointerx()
            my = self._win.winfo_pointery()
            for w in self._chrome_widgets():
                if not w.winfo_ismapped():
                    continue
                x, y = w.winfo_rootx(), w.winfo_rooty()
                ww, wh = w.winfo_width(), w.winfo_height()
                if ww > 0 and wh > 0 and x <= mx <= x + ww and y <= my <= y + wh:
                    return True
        except Exception:
            pass
        return False

    def _show_chrome(self):
        self._cancel_chrome_hide()
        if self._chrome_visible:
            return
        self._chrome_visible = True
        try:
            self._place_bar()
            if self._win and self._win.winfo_exists():
                self._win.configure(cursor="")
            if self._canvas and self._canvas.winfo_exists():
                self._canvas.configure(cursor="")
        except Exception:
            pass

    def _hide_chrome(self):
        self._hide_job = None
        if not self._chrome_visible:
            return
        self._chrome_visible = False
        try:
            if self._bar and self._bar.winfo_exists():
                self._bar.place_forget()
            if self._win and self._win.winfo_exists():
                self._win.configure(cursor="none")
            if self._canvas and self._canvas.winfo_exists():
                self._canvas.configure(cursor="none")
        except Exception:
            pass

    def _schedule_chrome_hide(self, delay_ms=2000):
        if self._hide_job or not self._win:
            return
        try:
            self._hide_job = self._win.after(delay_ms, self._hide_chrome)
        except Exception:
            pass

    def _cancel_chrome_hide(self):
        if self._hide_job and self._win:
            try:
                self._win.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None

    def _on_mouse_activity(self, event=None):
        self._last_move_t = time.monotonic()
        if event is not None:
            try:
                self._last_mouse = (event.x_root, event.y_root)
            except Exception:
                pass
        self._show_chrome()

    def _bind_chrome_hover(self, widget):
        if widget is None:
            return
        widget.bind("<Enter>", lambda e: self._cancel_chrome_hide(), add="+")
        widget.bind("<Leave>", lambda e: self._schedule_chrome_hide(), add="+")

    def _setup_chrome_autohide(self):
        if not self._win:
            return
        self._win.bind("<Motion>", self._on_mouse_activity, add="+")
        if self._canvas:
            self._canvas.bind("<Motion>", self._on_mouse_activity, add="+")
        for w in self._chrome_widgets():
            self._bind_chrome_hover(w)
            try:
                for child in w.winfo_children():
                    self._bind_chrome_hover(child)
            except Exception:
                pass

    def _start_mouse_poll(self):
        self._stop_mouse_poll()
        self._last_move_t = time.monotonic()
        self._do_mouse_poll()

    def _stop_mouse_poll(self):
        if self._poll_job and self._win:
            try:
                self._win.after_cancel(self._poll_job)
            except Exception:
                pass
        self._poll_job = None

    def _do_mouse_poll(self):
        if self._closing or not self._win:
            return
        try:
            if not self._win.winfo_exists():
                return
            mx = self._win.winfo_pointerx()
            my = self._win.winfo_pointery()
            wx = self._win.winfo_rootx()
            wy = self._win.winfo_rooty()
            ww = self._win.winfo_width()
            wh = self._win.winfo_height()
            inside = (wx <= mx <= wx + ww) and (wy <= my <= wy + wh)
            if inside:
                if (mx, my) != self._last_mouse:
                    self._last_mouse = (mx, my)
                    self._last_move_t = time.monotonic()
                    self._show_chrome()
                else:
                    idle = time.monotonic() - self._last_move_t
                    if (idle >= self.INACTIVITY_S and self._chrome_visible
                            and not self._hide_job and not self._pointer_over_chrome()):
                        self._schedule_chrome_hide(100)
            elif self._chrome_visible and not self._hide_job:
                self._schedule_chrome_hide(300)
        except Exception:
            pass
        try:
            self._poll_job = self._win.after(120, self._do_mouse_poll)
        except Exception:
            self._poll_job = None

    def _apply_slideshow_mode_ui(self):
        if self._win and self._win.winfo_exists():
            self._win.title("Photo Slideshow" if self._slideshow_mode else "Photo Viewer")
        self._update_mode_label()

    def _enter_slideshow_mode(self):
        if self._slideshow_mode:
            return
        self._slideshow_mode = True
        self._apply_slideshow_mode_ui()

    # ── Single overlay control bar (embedded-player style) ────────────────────

    def _build_overlay_bar(self, win):
        """Build the single floating control bar placed over the canvas.

        Layout (left → right):
          [⏮] [⏪] [▶ Play] [⏩] [⏭]  ──progress──  [1/42]  [🔊] [vol] [♪ now-playing]  [⚙] [⛶] [✕]
        The bar is placed at the bottom via place() so the canvas never resizes.
        """
        c = self._ctrl()
        F = self._fonts()

        bar = tk.Frame(win, bg=c["bg"])
        self._bar = bar
        # Don't pack/grid the bar — it lives as a place() overlay

        # Top border line
        tk.Frame(bar, bg=c["border"], height=1).pack(fill=tk.X, side=tk.TOP)

        # ── Progress row ───────────────────────────────────────────────────
        prog_row = tk.Frame(bar, bg=c["bg"])
        prog_row.pack(fill=tk.X, padx=12, pady=(5, 2))

        self._progress_canvas = tk.Canvas(
            prog_row, height=18, bg=c["bg"],
            highlightthickness=0, cursor="hand2",
        )
        self._progress_canvas.pack(fill=tk.X, expand=True)
        self._progress_canvas.bind("<Button-1>", self._on_progress_click)
        self._progress_canvas.bind("<B1-Motion>", self._on_progress_click)
        self._progress_canvas.bind("<Configure>", lambda e: self._update_progress())

        # ── Buttons row ────────────────────────────────────────────────────
        btn_row = tk.Frame(bar, bg=c["bg"])
        btn_row.pack(fill=tk.X, padx=8, pady=(2, 6))

        # Left zone: transport
        zone_l = tk.Frame(btn_row, bg=c["bg"])
        zone_l.pack(side=tk.LEFT)

        self._btn_first = self._make_btn(
            zone_l, "⏮", self._go_first, padx=6, pady=4, fg=c["txt_dim"],
        )
        self._btn_first.pack(side=tk.LEFT, padx=(0, 1))

        self._btn_prev = self._make_btn(zone_l, "⏪", self._prev, padx=6, pady=4)
        self._btn_prev.pack(side=tk.LEFT, padx=1)

        self._play_btn = self._make_btn(
            zone_l, "▶  Play", self._toggle_play, accent=True,
            font=F["acc"], padx=14, pady=5,
        )
        self._play_btn.pack(side=tk.LEFT, padx=5)

        self._btn_next = self._make_btn(zone_l, "⏩", self._next, padx=6, pady=4)
        self._btn_next.pack(side=tk.LEFT, padx=1)

        self._btn_last = self._make_btn(
            zone_l, "⏭", self._go_last, padx=6, pady=4, fg=c["txt_dim"],
        )
        self._btn_last.pack(side=tk.LEFT, padx=(1, 0))

        # Counter badge
        self._sep(btn_row, pady=6)
        self._ctrl_counter_lbl = tk.Label(
            btn_row, text="", font=F["acc"],
            bg=c["bg"], fg=c["txt_med"],
        )
        self._ctrl_counter_lbl.pack(side=tk.LEFT, padx=(4, 0))

        # Status badge (Playing / Paused / Viewer)
        self._sep(btn_row, pady=6)
        self._pause_lbl = tk.Label(
            btn_row, text="Viewer", font=F["acc"],
            bg=c["btn"], fg=c["txt_med"],
            padx=6, pady=2,
            highlightbackground=c["border"], highlightthickness=1,
        )
        self._pause_lbl.pack(side=tk.LEFT, padx=(4, 0))

        # Right zone: audio + settings + window
        zone_r = tk.Frame(btn_row, bg=c["bg"])
        zone_r.pack(side=tk.RIGHT)

        # Audio: mute + volume slider
        self._mute_btn = tk.Label(
            zone_r, text="🔊", font=F["md"], bg=c["bg"], fg=c["txt_med"],
            cursor="hand2", padx=4,
        )
        self._mute_btn.pack(side=tk.LEFT)
        self._mute_btn.bind("<Button-1>", lambda e: self._toggle_mute())
        self._mute_btn.bind("<Enter>", lambda e: self._mute_btn.config(fg=c["txt"]))
        self._mute_btn.bind("<Leave>", lambda e: self._mute_btn.config(fg=c["txt_med"]))

        self._vol_canvas = tk.Canvas(
            zone_r, bg=c["bg"], width=68, height=14,
            highlightthickness=0, cursor="hand2",
        )
        self._vol_canvas.pack(side=tk.LEFT, padx=(2, 6))
        self._vol_canvas.bind("<Button-1>", self._on_vol_click)
        self._vol_canvas.bind("<B1-Motion>", self._on_vol_click)
        self._vol_canvas.bind("<Configure>", lambda e: self._draw_vol_slider())

        # ── Inline music controls (hidden until songs are added) ───────────
        self._music_btn_frame = tk.Frame(zone_r, bg=c["bg"])
        self._music_btn_frame.pack(side=tk.LEFT)

        self._btn_prev_song = self._make_btn(
            self._music_btn_frame, "⏮", self._prev_song, padx=5, pady=3,
            fg=c["txt_med"],
        )
        self._btn_next_song = self._make_btn(
            self._music_btn_frame, "⏭", self._next_song, padx=5, pady=3,
            fg=c["txt_med"],
        )
        self._btn_shuffle = self._make_btn(
            self._music_btn_frame, "🔀", self._shuffle_songs, padx=5, pady=3,
            fg=c["txt_med"],
        )
        # Highlight shuffle button on hover
        def _on_shuffle_enter(e):
            self._btn_shuffle.config(fg=c["accent"])
            self._cancel_chrome_hide()
        def _on_shuffle_leave(e):
            self._btn_shuffle.config(fg=c["txt_med"])
            self._schedule_chrome_hide()
        self._btn_shuffle.bind("<Enter>", _on_shuffle_enter, add="+")
        self._btn_shuffle.bind("<Leave>", _on_shuffle_leave, add="+")

        # ♪+ Add music button — always visible
        self._btn_add_music = self._make_btn(
            zone_r, "♪+", lambda: self._show_add_music_menu(self._btn_add_music),
            padx=6, pady=3, fg=c["accent"],
        )
        self._btn_add_music.pack(side=tk.LEFT, padx=(2, 0))

        self._sep(zone_r, pady=6)

        # Now-playing label (truncated)
        self._now_playing_lbl = tk.Label(
            zone_r, text="", font=F["sm"],
            bg=c["bg"], fg=c["txt_dim"], anchor="w",
        )
        self._now_playing_lbl.pack(side=tk.LEFT, padx=(0, 4))

        self._sep(zone_r, pady=6)

        # ⋮ Settings button — opens dropdown with slideshow options only
        settings_btn = self._make_btn(
            zone_r, "⋮", self._show_settings_menu, padx=7, pady=4,
        )
        settings_btn.pack(side=tk.LEFT, padx=(0, 2))
        self._settings_btn = settings_btn

        self._sep(zone_r, pady=6)

        # ✏ Edit toggle
        self._edit_btn = self._make_btn(
            zone_r, "✏ Edit", self._toggle_edit_mode, padx=7, pady=4,
        )
        self._edit_btn.pack(side=tk.LEFT, padx=(0, 2))

        self._sep(zone_r, pady=6)

        # Fullscreen + Close
        self._fs_btn = self._make_btn(
            zone_r, "⛶", self._toggle_fullscreen, padx=7, pady=4,
        )
        self._fs_btn.pack(side=tk.LEFT, padx=(0, 2))

        close_btn = self._make_btn(zone_r, "✕", self.close, padx=7, pady=4, fg=c["txt_dim"])
        close_btn.pack(side=tk.LEFT)

        # Bind hover so bar stays visible while mouse is over it
        self._bind_chrome_hover(bar)
        for child in bar.winfo_children():
            self._bind_chrome_hover(child)
            for grandchild in child.winfo_children():
                self._bind_chrome_hover(grandchild)

        # ── Initialise vars for settings (slideshow opts + audio) ──────────
        self._dur_var = tk.DoubleVar(value=self.duration)
        self._trans_var = tk.StringVar(value=self.transition)
        self._trans_label_to_key = {self.TRANSITION_LABELS[t]: t for t in self.TRANSITIONS}
        self._trans_display_var = tk.StringVar(value=self.TRANSITION_LABELS[self.transition])
        self._kb_var = tk.BooleanVar(value=self.ken_burns)

        # Hide music transport buttons until songs loaded
        self._refresh_music_bar()

    def _refresh_music_bar(self):
        """Show or hide the song-transport buttons based on whether songs are loaded."""
        if not self._music_btn_frame:
            return
        try:
            if not self._music_btn_frame.winfo_exists():
                return
        except Exception:
            return
        c = self._ctrl()
        if self._songs:
            # Pack buttons if not already visible
            for btn in (self._btn_prev_song, self._btn_next_song, self._btn_shuffle):
                if btn and btn.winfo_exists() and not btn.winfo_ismapped():
                    btn.pack(side=tk.LEFT, padx=1)
            # Update the now-playing label color to active
            if self._now_playing_lbl and self._now_playing_lbl.winfo_exists():
                self._now_playing_lbl.config(fg=c["txt_med"])
        else:
            # Unpack buttons when no songs
            for btn in (self._btn_prev_song, self._btn_next_song, self._btn_shuffle):
                if btn and btn.winfo_exists() and btn.winfo_ismapped():
                    btn.pack_forget()
            if self._now_playing_lbl and self._now_playing_lbl.winfo_exists():
                self._now_playing_lbl.config(fg=c["txt_dim"])

    # ── Main canvas (fills entire window, never resizes) ──────────────────────

    def _build_canvas(self, win):
        c = self._ctrl()
        self._canvas = tk.Canvas(win, bg=c["canvas"], highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas.bind("<Double-Button-1>", lambda e: self._toggle_fullscreen())
        self._canvas.bind("<Button-3>", lambda e: self._show_context(e))
        # Drag to pan when zoomed
        self._canvas.bind("<Button-1>", self._on_canvas_press, add="+")
        self._canvas.bind("<B1-Motion>", self._on_canvas_drag, add="+")
        self._canvas.bind("<ButtonRelease-1>", self._on_canvas_release, add="+")
        # Scroll to zoom
        self._canvas.bind("<MouseWheel>", self._on_mouse_wheel, add="+")
        self._canvas.bind("<Button-4>", lambda e: self._zoom_in(e.x, e.y), add="+")
        self._canvas.bind("<Button-5>", lambda e: self._zoom_out(e.x, e.y), add="+")
        # Reposition overlay bar when window is resized
        self._canvas.bind("<Configure>", lambda e: (
            self._on_canvas_resize(e),
            self._place_bar(),
        ), add="+")

    # ── Settings dropdown (less-important controls) ───────────────────────────

    def _show_settings_menu(self):
        """Popup menu with slideshow settings only (audio controls are in the main bar)."""
        c = self._ctrl()
        menu = self._context_menu()

        # ── Slideshow settings sub-section ─────────────────────────────────
        menu.add_command(
            label=f"⏱  Duration: {self.duration:.1f} s",
            command=self._prompt_duration,
        )

        # Transition sub-menu
        trans_menu = tk.Menu(
            menu, tearoff=0, bg=c["surface"], fg=c["txt"],
            activebackground=c["btn_hvr"], activeforeground=c["txt"], relief=tk.FLAT,
            font=("Segoe UI", 10),
        )
        for t in self.TRANSITIONS:
            label = self.TRANSITION_LABELS[t]
            check = "✔  " if t == self.transition else "     "
            trans_menu.add_command(
                label=check + label,
                command=lambda _t=t: self._set_transition(_t),
            )
        menu.add_cascade(label="✦  Transition", menu=trans_menu)

        kb_label = "☑  Ken Burns  (on)" if self.ken_burns else "☐  Ken Burns  (off)"
        menu.add_command(label=kb_label, command=self._toggle_ken_burns)

        try:
            btn = self._settings_btn
            x = btn.winfo_rootx()
            y = btn.winfo_rooty()
            menu.tk_popup(x, y)
        except Exception:
            pass
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def _prompt_duration(self):
        """Custom dark-themed dialog for entering slide duration."""
        if not self._win or not self._win.winfo_exists():
            return

        c = self._ctrl()
        F = self._fonts()

        dlg = tk.Toplevel(self._win)
        dlg.withdraw()
        dlg.title("Slide Duration")
        dlg.configure(bg=c["bg2"])
        dlg.resizable(False, False)
        dlg.transient(self._win)
        dlg.grab_set()

        try:
            from icon_helper import apply_icon
            apply_icon(dlg)
        except Exception:
            pass

        # Size and center relative to the slideshow window
        dw, dh = 320, 160
        dlg.update_idletasks()
        pw = self._win.winfo_width()
        ph = self._win.winfo_height()
        px = self._win.winfo_rootx()
        py = self._win.winfo_rooty()
        dlg.geometry(f"{dw}x{dh}+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")
        dlg.deiconify()

        # Accent top border (matches embedded player dialogs)
        tk.Frame(dlg, height=2, bg=c["accent"]).pack(fill=tk.X)

        # Header
        hdr = tk.Frame(dlg, bg=c["bg2"])
        hdr.pack(fill=tk.X, padx=18, pady=(12, 6))
        tk.Label(
            hdr, text="⏱  Slide Duration",
            font=("Segoe UI", 10, "bold"), bg=c["bg2"], fg=c["txt"],
        ).pack(side=tk.LEFT)
        tk.Label(
            hdr, text="seconds per photo",
            font=("Segoe UI", 8), bg=c["bg2"], fg=c["txt_dim"],
        ).pack(side=tk.RIGHT)

        # Entry
        var = tk.StringVar(value=str(self.duration))
        entry = tk.Entry(
            dlg, textvariable=var,
            font=("Segoe UI", 11), bg=c["surface"], fg=c["txt"],
            insertbackground=c["txt"], relief=tk.FLAT,
            highlightthickness=1, highlightbackground=c["border"],
            justify="center",
        )
        entry.pack(fill=tk.X, padx=18, ipady=5)
        entry.select_range(0, tk.END)
        entry.focus_set()

        # Hint label
        tk.Label(
            dlg, text="Range: 0.5 – 120  ·  Press Enter to confirm",
            font=("Segoe UI", 7), bg=c["bg2"], fg=c["txt_dim"],
        ).pack(pady=(3, 0))

        # Buttons row
        btn_row = tk.Frame(dlg, bg=c["bg2"])
        btn_row.pack(pady=(8, 12))

        def _apply(e=None):
            try:
                val = float(var.get().replace(",", "."))
                val = max(0.5, min(120.0, val))
                self.duration = val
                if self._dur_var:
                    self._dur_var.set(val)
            except ValueError:
                pass
            dlg.destroy()

        def _cancel(e=None):
            dlg.destroy()

        tk.Button(
            btn_row, text="Set Duration", command=_apply,
            bg=c["accent"], fg=c["play_fg"],
            relief=tk.FLAT, font=("Segoe UI", 9, "bold"),
            padx=16, pady=5, cursor="hand2",
            activebackground=c["accent_hvr"], activeforeground=c["play_fg"],
        ).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(
            btn_row, text="Cancel", command=_cancel,
            bg=c["btn"], fg=c["txt_med"],
            relief=tk.FLAT, font=("Segoe UI", 9),
            padx=12, pady=5, cursor="hand2",
            activebackground=c["btn_hvr"], activeforeground=c["txt"],
        ).pack(side=tk.LEFT)

        entry.bind("<Return>", _apply)
        dlg.bind("<Escape>", _cancel)
        dlg.wait_window()

    def _set_transition(self, transition_key):
        self.transition = transition_key
        if self._trans_display_var:
            self._trans_display_var.set(self.TRANSITION_LABELS[transition_key])

    def _toggle_ken_burns(self):
        self.ken_burns = not self.ken_burns
        if self._kb_var:
            self._kb_var.set(self.ken_burns)
        self._on_kb_changed()

    def _update_mode_label(self):
        self._update_pause_label()

    # ── Keyboard bindings ─────────────────────────────────────────────────────

    # Slideshow actions mapped to the same settings hotkey ids as EmbeddedPlayer
    _ACTION_MAP = {
        "toggle_pause":      ("_toggle_play",        ()),
        "next_video":        ("_next",               ()),
        "prev_video":        ("_prev",               ()),
        "fast_forward":      ("_next",               ()),
        "rewind":            ("_prev",               ()),
        "toggle_fullscreen": ("_toggle_fullscreen",  ()),
        "toggle_mute":       ("_toggle_mute",        ()),
        "stop_video":        ("_stop_or_close",      ()),
        "ab_set_a":          ("_prev_song",          ()),
        "ab_set_b":          ("_next_song",          ()),
        "zoom_in":           ("_zoom_in",            ()),
        "zoom_out":          ("_zoom_out",           ()),
        "zoom_reset":        ("_zoom_reset",         ()),
        "rotate_right":      ("_temp_rotate_right",  ()),
    }

    def _stop_or_close(self):
        if self._fullscreen:
            self._exit_fullscreen()
        else:
            self.close()

    def _rebind_keys(self, win):
        for seq, cbid in getattr(self, '_registered_cbids', []):
            try:
                win.unbind(seq, cbid)
            except Exception:
                pass
        self._registered_cbids = []
        hk = self._hotkeys

        def _to_tk_seq(combo):
            if not combo:
                return None
            parts = combo.lower().split('+')
            key = parts[-1]
            mods = parts[:-1]
            _key_map = {
                'space': 'space', 'esc': 'Escape', 'escape': 'Escape',
                'enter': 'Return', 'return': 'Return',
                'left': 'Left', 'right': 'Right', 'up': 'Up', 'down': 'Down',
                'page_up': 'Prior', 'page_down': 'Next',
                '=': 'equal', '-': 'minus', '+': 'plus',
                '[': 'bracketleft', ']': 'bracketright',
                '\\': 'backslash',
                **{f'f{i}': f'F{i}' for i in range(1, 13)},
            }
            tk_key = _key_map.get(key, key)
            mod_map = {'ctrl': 'Control', 'shift': 'Shift', 'alt': 'Alt'}
            tk_mods = [mod_map.get(m, m.capitalize()) for m in mods]
            inner = '-'.join(tk_mods + [tk_key]) if tk_mods else tk_key
            return f'<{inner}>'

        def _make_cb(method):
            def _cb(e, _m=method):
                try:
                    _m()
                except Exception:
                    pass
            return _cb

        for action_id, (method_name, _extra) in self._ACTION_MAP.items():
            combo = hk.get(action_id) or DEFAULT_HOTKEYS.get(action_id)
            if not combo:
                continue
            seq = _to_tk_seq(combo)
            if not seq:
                continue
            method = getattr(self, method_name, None)
            if method is None:
                continue
            try:
                cbid = win.bind(seq, _make_cb(method), add=True)
                self._registered_cbids.append((seq, cbid))
                if len(seq) == 3 and seq[1].isalpha() and seq[1].islower():
                    upper_seq = f'<{seq[1].upper()}>'
                    cbid2 = win.bind(upper_seq, _make_cb(method), add=True)
                    self._registered_cbids.append((upper_seq, cbid2))
            except Exception:
                pass

    def _bind_keys(self, win):
        self._rebind_keys(win)

    # ── Image loading & PIL ───────────────────────────────────────────────────

    def _load_pil(self, path):
        cached = self._preload_cache.get(path)
        if cached:
            return cached
        try:
            img = Image.open(path).convert("RGB")
            # Cap to 4K for memory
            img.thumbnail((3840, 2160), Image.Resampling.LANCZOS)
            self._preload_cache[path] = img
            # Evict oldest if cache too large
            if len(self._preload_cache) > 12:
                oldest = next(iter(self._preload_cache))
                del self._preload_cache[oldest]
            return img
        except Exception as e:
            self.logger(f"Slideshow: cannot load {path}: {e}")
            return None

    def _preload_adjacent(self):
        if not self.photos:
            return
        idxs = [
            (self.index + 1) % len(self.photos),
            (self.index + 2) % len(self.photos),
            (self.index - 1) % len(self.photos),
        ]
        def _load():
            for i in idxs:
                p = self.photos[i]
                if p not in self._preload_cache:
                    self._load_pil(p)
        threading.Thread(target=_load, daemon=True).start()

    def _canvas_size(self):
        try:
            w = self._canvas.winfo_width()
            h = self._canvas.winfo_height()
            return (w if w > 10 else 1280), (h if h > 10 else 700)
        except Exception:
            return 1280, 700

    def _fit_image(self, pil_img, cw, ch, scale=1.0, offset_x=0.0, offset_y=0.0):
        """Letterbox-fit image into (cw, ch), applying optional centered scale for Ken Burns."""
        cache_key = (id(pil_img), cw, ch, round(scale, 4), round(offset_x, 4), round(offset_y, 4))
        cached = self._fit_cache.get(cache_key)
        if cached is not None:
            return cached
        iw, ih = pil_img.size
        base_scale = min(cw / iw, ch / ih)
        s  = base_scale * scale
        nw = max(1, int(round(iw * s)))
        nh = max(1, int(round(ih * s)))
        resized = pil_img.resize((nw, nh), Image.Resampling.LANCZOS)
        cx = (cw - nw) / 2 + offset_x * max(0, nw - cw)
        cy = (ch - nh) / 2 + offset_y * max(0, nh - ch)
        canvas_img = Image.new("RGB", (cw, ch), (0, 0, 0))
        canvas_img.paste(resized, (round(cx), round(cy)))
        if len(self._fit_cache) > 24:
            self._fit_cache.clear()
        self._fit_cache[cache_key] = canvas_img
        return canvas_img

    def _show_pil_on_canvas(self, pil_img):
        if not self._canvas or not self._canvas.winfo_exists():
            return
        photo = ImageTk.PhotoImage(pil_img)
        self._photo_img = photo  # keep reference
        if self._canvas_img_id:
            try:
                self._canvas.itemconfig(self._canvas_img_id, image=photo)
            except tk.TclError:
                self._canvas_img_id = None
        if not self._canvas_img_id:
            cw, ch = self._canvas_size()
            self._canvas_img_id = self._canvas.create_image(
                cw // 2, ch // 2, image=photo, anchor="center")

    def _load_current(self):
        self._cancel_timers()
        if not self.photos:
            return
        path = self.photos[self.index]
        self._current_pil = self._load_pil(path)
        if not self._current_pil:
            return
        self._zoom_factor = 1.0
        self._zoom_offset_x = 0.0
        self._zoom_offset_y = 0.0
        self._temp_rotation = 0
        display_pil = self._get_display_pil()
        cw, ch = self._canvas_size()
        rendered = self._fit_image(display_pil, cw, ch,
                                   scale=self._zoom_factor,
                                   offset_x=self._zoom_offset_x,
                                   offset_y=self._zoom_offset_y)
        self._show_pil_on_canvas(rendered)
        self._update_counter()
        self._update_progress()
        self._preload_adjacent()
        if (self.playing and self.ken_burns
                and self._kb_var and self._kb_var.get() and self._current_pil):
            self._start_ken_burns()

    # ── Ken Burns ─────────────────────────────────────────────────────────────

    def _start_ken_burns(self):
        self._cancel_kb()
        if not self._current_pil:
            return
        # Smooth center zoom only — no pan (pan caused shaky movement).
        self._kb_params = (1.0, 1.10)
        self._kb_start  = time.time()
        self._kb_tick()

    def _kb_tick(self):
        if self._closing or not self.playing or not self._current_pil or not self._canvas.winfo_exists():
            return
        elapsed = time.time() - self._kb_start
        total   = max(0.1, self.duration)
        t       = min(elapsed / total, 1.0)
        # Smooth ease-in-out
        t_ease  = t * t * (3 - 2 * t)
        start_scale, end_scale = self._kb_params
        scale   = start_scale + (end_scale - start_scale) * t_ease
        cw, ch = self._canvas_size()
        rendered = self._fit_image(self._current_pil, cw, ch, scale)
        self._show_pil_on_canvas(rendered)
        self._update_progress(t)
        if t < 1.0 and not self._closing:
            self._kb_after = self._canvas.after(33, self._kb_tick)  # ~30 fps

    def _cancel_kb(self):
        if self._kb_after and self._canvas:
            try:
                if self._canvas.winfo_exists():
                    self._canvas.after_cancel(self._kb_after)
            except Exception:
                pass
            self._kb_after = None

    # ── Transitions ───────────────────────────────────────────────────────────

    def _transition_to(self, new_index):
        if not self.photos:
            return
        self.index  = new_index % len(self.photos)
        if not self.playing:
            self._load_current()
            return
        next_path   = self.photos[self.index]
        next_pil    = self._load_pil(next_path)
        if not next_pil:
            self._load_current()
            return

        cw, ch = self._canvas_size()
        tr = self.transition

        if tr == "none" or not self._current_pil:
            self._current_pil = next_pil
            self._load_current()
            if self.playing:
                self._schedule_next()
            return

        cur_img  = self._fit_image(self._current_pil, cw, ch)
        next_img = self._fit_image(next_pil, cw, ch)
        steps    = max(1, int(self.transition_duration * 30))
        step_ms  = max(1, int(self.transition_duration * 1000 / steps))

        def _do_step(i):
            if self._closing or not self._canvas.winfo_exists():
                return
            t      = i / steps
            t_ease = t * t * (3 - 2 * t)

            if tr == "fade":
                blended = Image.blend(cur_img, next_img, t_ease)

            elif tr == "slide_left":
                offset  = int(cw * t_ease)
                blended = Image.new("RGB", (cw, ch))
                blended.paste(cur_img.crop((offset, 0, cw, ch)), (0, 0))
                blended.paste(next_img.crop((0, 0, cw - offset, ch)), (cw - offset, 0))

            elif tr == "slide_right":
                offset  = int(cw * t_ease)
                blended = Image.new("RGB", (cw, ch))
                blended.paste(cur_img.crop((0, 0, cw - offset, ch)), (offset, 0))
                blended.paste(next_img.crop((cw - offset, 0, cw, ch)), (0, 0))

            elif tr == "zoom_in":
                scale   = 1.0 + 0.18 * t_ease
                iw2, ih2 = max(1, int(cw * scale)), max(1, int(ch * scale))
                zoomed  = cur_img.resize((iw2, ih2), Image.Resampling.LANCZOS)
                x0, y0  = (iw2 - cw) // 2, (ih2 - ch) // 2
                cropped = zoomed.crop((x0, y0, x0 + cw, y0 + ch))
                blended = Image.blend(cropped, next_img, t_ease)

            elif tr == "zoom_out":
                scale   = max(0.01, 1.0 - 0.12 * t_ease)
                iw2, ih2 = max(1, int(cw * scale)), max(1, int(ch * scale))
                zoomed  = cur_img.resize((iw2, ih2), Image.Resampling.LANCZOS)
                canvas  = Image.new("RGB", (cw, ch))
                canvas.paste(zoomed, ((cw - iw2) // 2, (ch - ih2) // 2))
                blended = Image.blend(canvas, next_img, t_ease)

            else:
                blended = next_img

            self._show_pil_on_canvas(blended)

            if i < steps:
                self._transition_after = self._canvas.after(
                    step_ms, lambda: _do_step(i + 1))
            else:
                # Transition complete
                self._current_pil = next_pil
                self._update_counter()
                self._update_progress()
                self._preload_adjacent()
                if self.playing and self.ken_burns and self._kb_var and self._kb_var.get():
                    self._start_ken_burns()
                if self.playing:
                    self._schedule_next()

        self._cancel_timers()
        _do_step(0)

    # ── Playback scheduling ───────────────────────────────────────────────────

    def _schedule_next(self):
        if not self._canvas or not self._canvas.winfo_exists():
            return
        if self._after_id:
            try:
                self._canvas.after_cancel(self._after_id)
            except Exception:
                pass
        ms = max(100, int(self.duration * 1000))
        self._after_id = self._canvas.after(ms, self._auto_advance)

    def _auto_advance(self):
        if not self.playing or self._closing:
            return
        self._transition_to((self.index + 1) % len(self.photos))

    def _cancel_timers(self):
        self._cancel_kb()
        canvas = self._canvas
        for attr in ('_after_id', '_transition_after'):
            aid = getattr(self, attr, None)
            if aid and canvas:
                try:
                    if canvas.winfo_exists():
                        canvas.after_cancel(aid)
                except Exception:
                    pass
                setattr(self, attr, None)
            elif aid:
                setattr(self, attr, None)

    # ── Playback controls ─────────────────────────────────────────────────────

    def _toggle_play(self):
        if not self.playing:
            self._enter_slideshow_mode()
        self.playing = not self.playing
        self._update_play_btn()
        if self.playing:
            self._schedule_next()
            if (self.ken_burns and self._kb_var and self._kb_var.get() and self._current_pil):
                self._start_ken_burns()
        else:
            self._cancel_timers()
            self._load_current()

    def _prev(self):
        self._cancel_timers()
        self._transition_to((self.index - 1) % max(1, len(self.photos)))
        if self.playing:
            self._schedule_next()

    def _next(self):
        self._cancel_timers()
        self._transition_to((self.index + 1) % max(1, len(self.photos)))
        if self.playing:
            self._schedule_next()

    def _go_first(self):
        self._cancel_timers()
        self._transition_to(0)
        if self.playing:
            self._schedule_next()

    def _go_last(self):
        self._cancel_timers()
        self._transition_to(len(self.photos) - 1)
        if self.playing:
            self._schedule_next()

    # ── UI update helpers ─────────────────────────────────────────────────────

    def _update_play_btn(self):
        if not self._play_btn or not self._play_btn.winfo_exists():
            return
        self._play_btn.config(text="⏸  Pause" if self.playing else "▶  Play")
        self._restyle_btn(self._play_btn, accent=True)
        self._update_pause_label()

    def _update_pause_label(self):
        if not getattr(self, '_pause_lbl', None) or not self._pause_lbl.winfo_exists():
            return
        c = self._ctrl()
        if self.playing:
            self._pause_lbl.config(text="Playing", fg=c["success"])
        elif self._slideshow_mode:
            self._pause_lbl.config(text="Paused", fg=c["txt_med"])
        else:
            self._pause_lbl.config(text="Viewer", fg=c["txt_med"])

    def _update_counter(self):
        if not self.photos:
            return
        text = f"{self.index + 1} / {len(self.photos)}"
        if self._counter_lbl and self._counter_lbl.winfo_exists():
            self._counter_lbl.config(text=text)
        if getattr(self, '_ctrl_counter_lbl', None) and self._ctrl_counter_lbl.winfo_exists():
            self._ctrl_counter_lbl.config(text=text)

    def _update_progress(self, within_fraction=0.0):
        if not self._progress_canvas or not self._progress_canvas.winfo_exists():
            return
        c = self._ctrl()
        self._progress_canvas.delete("all")
        w = max(1, self._progress_canvas.winfo_width())
        h = max(1, self._progress_canvas.winfo_height())
        cy = h // 2
        rail = 3
        n = max(1, len(self.photos) - 1)
        slide_frac = self.index / n

        self._progress_canvas.create_rectangle(
            0, cy - rail, w, cy + rail, fill=c["track"], outline="")
        filled_x = int(w * slide_frac)
        if filled_x > 0:
            self._progress_canvas.create_rectangle(
                0, cy - rail, filled_x, cy + rail, fill=c["accent"], outline="")
        if within_fraction > 0:
            per_slide = w / max(1, len(self.photos))
            dot_x = max(rail + 2, min(w - rail - 2,
                                      int(filled_x + per_slide * within_fraction)))
            r = 5
            self._progress_canvas.create_oval(
                dot_x - r, cy - r, dot_x + r, cy + r, fill="#FFFFFF", outline="")
        elif filled_x > 0:
            r = 5
            dot_x = max(r, min(w - r, filled_x))
            self._progress_canvas.create_oval(
                dot_x - r, cy - r, dot_x + r, cy + r, fill="#FFFFFF", outline="")

    def _on_progress_click(self, event):
        w = max(1, self._progress_canvas.winfo_width())
        frac = max(0.0, min(1.0, event.x / w))
        idx  = int(round(frac * (len(self.photos) - 1)))
        self._cancel_timers()
        self._transition_to(idx)
        if self.playing:
            self._schedule_next()

    def _on_canvas_resize(self, event):
        if self._current_pil:
            display_pil = self._get_display_pil()
            rendered = self._fit_image(display_pil, event.width, event.height,
                                       scale=self._zoom_factor,
                                       offset_x=self._zoom_offset_x,
                                       offset_y=self._zoom_offset_y)
            self._show_pil_on_canvas(rendered)
            # Reposition image to new center
            if self._canvas_img_id:
                self._canvas.coords(self._canvas_img_id,
                                    event.width // 2, event.height // 2)

    def _on_duration_changed(self):
        try:
            self.duration = max(0.5, float(self._dur_var.get()))
        except (ValueError, tk.TclError):
            pass

    def _on_transition_changed(self, label):
        self.transition = self._trans_label_to_key.get(label, "fade")

    def _on_kb_changed(self):
        self.ken_burns = self._kb_var.get()
        if self.ken_burns and self._current_pil and self.playing:
            self._start_ken_burns()
        elif not self.ken_burns:
            self._cancel_kb()
            if not self.playing:
                self._load_current()

    def _toggle_fullscreen(self):
        """Toggle borderless fullscreen (overrideredirect, like embedded player)."""
        self._fullscreen = not self._fullscreen
        if self._fullscreen:
            self._pre_fs_geo = self._win.geometry()
            self._win.overrideredirect(True)
            self._win.update_idletasks()
            wx = self._win.winfo_x()
            wy = self._win.winfo_y()
            sw = self._win.winfo_screenwidth()
            sh = self._win.winfo_screenheight()
            fx, fy = 0, 0
            try:
                from screeninfo import get_monitors
                for m in get_monitors():
                    if m.x <= wx < m.x + m.width and m.y <= wy < m.y + m.height:
                        sw, sh = m.width, m.height
                        fx, fy = m.x, m.y
                        break
            except Exception:
                pass
            self._win.geometry(f"{sw}x{sh}+{fx}+{fy}")
            self._win.lift()
            self._win.focus_force()
            self._build_titlebar_overlay()
            self._schedule_chrome_hide(800)
        else:
            self._exit_fullscreen()

    def _exit_fullscreen(self):
        """Return from borderless fullscreen to windowed mode."""
        self._fullscreen = False
        self._destroy_titlebar()
        self._win.overrideredirect(False)
        self._win.geometry(self._pre_fs_geo)
        self._win.lift()
        self._win.focus_force()

    # ── Titlebar overlay (borderless fullscreen) ──────────────────────────

    def _build_titlebar_overlay(self):
        """Build the hover-reveal top titlebar for borderless fullscreen."""
        TB_H = 32
        self._tb_h = TB_H
        self._tb_shown = False
        self._tb_y = -TB_H
        c = self._ctrl()

        self._titlebar = tk.Frame(self._win, bg=c["bg2"],
                                  highlightthickness=0, height=TB_H)
        self._titlebar.place(x=0, y=-TB_H,
                             width=self._win.winfo_width(), height=TB_H)
        self._titlebar.lift()

        # Close button
        btn_close = tk.Button(
            self._titlebar, text="✕", command=self.close,
            bg=c["bg2"], fg=c["txt_med"], bd=0, padx=12, pady=0,
            relief=tk.FLAT, cursor="hand2",
            activebackground="#FF8A8A",
            activeforeground="white", font=("Segoe UI", 10),
        )
        btn_close.pack(side=tk.RIGHT)
        btn_close.bind("<Enter>", lambda e: btn_close.config(bg="#FF8A8A", fg="white"))
        btn_close.bind("<Leave>", lambda e: btn_close.config(bg=c["bg2"], fg=c["txt_med"]))

        # Restore/exit-fullscreen button
        btn_restore = tk.Button(
            self._titlebar, text="🗖", command=self._exit_fullscreen,
            bg=c["bg2"], fg=c["txt_med"], bd=0, padx=10, pady=0,
            relief=tk.FLAT, cursor="hand2",
            activebackground=c["btn_hvr"], activeforeground=c["txt"],
            font=("Segoe UI", 10),
        )
        btn_restore.pack(side=tk.RIGHT)
        btn_restore.bind("<Enter>", lambda e: btn_restore.config(bg=c["btn_hvr"]))
        btn_restore.bind("<Leave>", lambda e: btn_restore.config(bg=c["bg2"]))

        # Minimize button
        btn_min = tk.Button(
            self._titlebar, text="—", command=self._fs_minimize,
            bg=c["bg2"], fg=c["txt_med"], bd=0, padx=10, pady=0,
            relief=tk.FLAT, cursor="hand2",
            activebackground=c["btn_hvr"], activeforeground=c["txt"],
            font=("Segoe UI", 10),
        )
        btn_min.pack(side=tk.RIGHT)
        btn_min.bind("<Enter>", lambda e: btn_min.config(bg=c["btn_hvr"]))
        btn_min.bind("<Leave>", lambda e: btn_min.config(bg=c["bg2"]))

        tk.Frame(self._titlebar, width=1, bg=c["border"]).pack(
            side=tk.RIGHT, fill=tk.Y, pady=6)

        tk.Label(
            self._titlebar, text="Photo Slideshow",
            bg=c["bg2"], fg=c["txt_med"],
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=14)

        # Invisible hot-zone at the very top of the screen
        self._tb_zone = tk.Frame(self._win, bg="black", height=8,
                                 highlightthickness=0)
        self._tb_zone.place(x=0, y=0, width=self._win.winfo_width(), height=8)
        self._tb_zone.lift()
        self._tb_zone.bind("<Configure>", lambda e: self._tb_zone.lift())
        self._win.bind("<Configure>", lambda e: self._reposition_tb_zone(), add=True)
        self._tb_zone.bind("<Enter>", lambda e: self._titlebar_slide_in())

        self._titlebar.bind("<Leave>", lambda e: self._titlebar_schedule_hide())
        self._titlebar.bind("<Enter>", lambda e: self._titlebar_cancel_hide())
        for child in self._titlebar.winfo_children():
            child.bind("<Enter>", lambda e: self._titlebar_cancel_hide(), add="+")
            child.bind("<Leave>", lambda e: self._titlebar_schedule_hide(), add="+")

    def _destroy_titlebar(self):
        if self._titlebar_anim:
            try:
                self._win.after_cancel(self._titlebar_anim)
            except Exception:
                pass
            self._titlebar_anim = None
        if self._titlebar_job:
            try:
                self._win.after_cancel(self._titlebar_job)
            except Exception:
                pass
            self._titlebar_job = None
        if self._titlebar:
            try:
                self._titlebar.destroy()
            except Exception:
                pass
            self._titlebar = None
        if self._tb_zone:
            try:
                self._tb_zone.destroy()
            except Exception:
                pass
            self._tb_zone = None

    def _reposition_tb_zone(self):
        if not self._fullscreen or not self._tb_zone:
            return
        try:
            self._tb_zone.place(x=0, y=0, width=self._win.winfo_width(), height=8)
            self._tb_zone.lift()
            if self._titlebar:
                self._titlebar.place(
                    x=0, y=self._tb_y,
                    width=self._win.winfo_width(), height=self._tb_h)
                self._titlebar.lift()
        except Exception:
            pass

    def _titlebar_slide_in(self):
        self._titlebar_cancel_hide()
        if self._tb_shown:
            return
        self._tb_shown = True
        self._tb_y = -self._tb_h
        self._titlebar_animate_to(0)

    def _titlebar_animate_to(self, target_y, step=3):
        if not self._titlebar:
            return
        if self._titlebar_anim:
            try:
                self._win.after_cancel(self._titlebar_anim)
            except Exception:
                pass

        def _tick():
            if not self._titlebar:
                return
            y = self._tb_y
            if y < target_y:
                y = min(y + step, target_y)
            elif y > target_y:
                y = max(y - step, target_y)
            self._tb_y = y
            try:
                self._titlebar.place(
                    x=0, y=y,
                    width=self._win.winfo_width(),
                    height=self._tb_h)
                if self._tb_zone:
                    self._tb_zone.lift()
                self._titlebar.lift()
            except Exception:
                return
            if y != target_y:
                self._titlebar_anim = self._win.after(8, _tick)
            else:
                self._titlebar_anim = None
                if target_y < 0:
                    self._tb_shown = False

        _tick()

    def _titlebar_schedule_hide(self, delay=1800):
        self._titlebar_cancel_hide()
        if self._titlebar:
            self._titlebar_job = self._win.after(
                delay, lambda: self._titlebar_animate_to(-self._tb_h))

    def _titlebar_cancel_hide(self):
        if self._titlebar_job:
            try:
                self._win.after_cancel(self._titlebar_job)
            except Exception:
                pass
            self._titlebar_job = None

    def _fs_minimize(self):
        """Minimize from fullscreen: exit borderless, then iconify."""
        self._fullscreen = False
        self._destroy_titlebar()
        self._win.overrideredirect(False)
        self._win.geometry(self._pre_fs_geo)
        self._win.update_idletasks()
        self._win.iconify()

    def _show_context(self, event):
        menu = self._context_menu()
        menu.add_command(label="▶  Play Slideshow", command=self._toggle_play)
        menu.add_command(label="⏪  Previous", command=self._prev)
        menu.add_command(label="⏩  Next", command=self._next)
        menu.add_separator()
        menu.add_command(label="🔍  Zoom In (Ctrl + =)", command=self._zoom_in)
        menu.add_command(label="🔍  Zoom Out (Ctrl + -)", command=self._zoom_out)
        menu.add_command(label="🔍  Reset Zoom (Ctrl + 0)", command=self._zoom_reset)
        menu.add_separator()
        menu.add_command(label="⟳  Rotate Clockwise (R) [Temp]", command=self._temp_rotate_right)
        menu.add_separator()
        menu.add_command(label="⛶  Toggle Fullscreen", command=self._toggle_fullscreen)
        menu.add_separator()
        menu.add_command(
            label="📁  Open File Location",
            command=lambda: self._open_location(self.photos[self.index]),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _open_location(self, path):
        try:
            import subprocess, sys
            norm = os.path.normpath(path)
            if sys.platform == "win32":
                subprocess.Popen(f'explorer /select,"{norm}"')
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", norm])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(norm)])
        except Exception as e:
            self.logger(f"Slideshow: cannot open location: {e}")

    # ── Photo Editing ─────────────────────────────────────────────────────────

    def _default_transform(self):
        return {
            "rotation": 0, "flip_h": False, "flip_v": False,
            "crop_box": None, "brightness": 1.0, "contrast": 1.0, "sharpness": 1.0,
            "tilt": 0.0, "resize": None,
        }

    def _current_path(self):
        if not self.photos:
            return None
        return self.photos[self.index]

    def _get_transform(self):
        path = self._current_path()
        if path not in self._edit_transforms:
            self._edit_transforms[path] = self._default_transform()
        return self._edit_transforms[path]

    def _get_edited_pil(self):
        if not self._current_pil:
            return self._current_pil
        t = self._get_transform()
        img = self._current_pil.copy()
        if t["crop_box"]:
            try:
                img = img.crop(t["crop_box"])
            except Exception:
                pass
        if t["resize"]:
            try:
                img = img.resize(t["resize"], Image.Resampling.LANCZOS)
            except Exception:
                pass
        if t["rotation"]:
            img = img.rotate(-t["rotation"], expand=True, resample=Image.Resampling.BICUBIC)
        if t["tilt"]:
            img = img.rotate(-t["tilt"], expand=False, resample=Image.Resampling.BICUBIC)
        if t["flip_h"]:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        if t["flip_v"]:
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
        if t["brightness"] != 1.0:
            img = ImageEnhance.Brightness(img).enhance(t["brightness"])
        if t["contrast"] != 1.0:
            img = ImageEnhance.Contrast(img).enhance(t["contrast"])
        if t["sharpness"] != 1.0:
            img = ImageEnhance.Sharpness(img).enhance(t["sharpness"])
        return img

    def _get_display_pil(self):
        if not self._current_pil:
            return None
        cache_key = (id(self._current_pil), self._edit_mode, getattr(self, '_temp_rotation', 0))
        if hasattr(self, '_display_pil_cache_key') and self._display_pil_cache_key == cache_key:
            return self._display_pil_cache
        img = self._get_edited_pil() if self._edit_mode else self._current_pil
        if hasattr(self, '_temp_rotation') and self._temp_rotation:
            img = img.rotate(-self._temp_rotation, expand=True, resample=Image.Resampling.BICUBIC)
        self._display_pil_cache_key = cache_key
        self._display_pil_cache = img
        return img

    def _redraw_current(self):
        if not self._current_pil:
            return
        display_pil = self._get_display_pil()
        cw, ch = self._canvas_size()
        rendered = self._fit_image(display_pil, cw, ch,
                                   scale=self._zoom_factor,
                                   offset_x=self._zoom_offset_x,
                                   offset_y=self._zoom_offset_y)
        self._show_pil_on_canvas(rendered)

    def _get_mouse_canvas_pos(self):
        try:
            mx = self._canvas.winfo_pointerx() - self._canvas.winfo_rootx()
            my = self._canvas.winfo_pointery() - self._canvas.winfo_rooty()
            cw, ch = self._canvas_size()
            if 0 <= mx <= cw and 0 <= my <= ch:
                return mx, my
            return cw / 2, ch / 2
        except Exception:
            cw, ch = self._canvas_size()
            return cw / 2, ch / 2

    def _zoom_to_factor(self, new_factor, mx, my):
        if not self._current_pil:
            return
        display_pil = self._get_display_pil()
        if not display_pil:
            return
        cw, ch = self._canvas_size()
        iw, ih = display_pil.size
        base_scale = min(cw / iw, ch / ih)
        
        s_old = base_scale * self._zoom_factor
        s_new = base_scale * new_factor
        
        max_dx_old = max(0, iw * s_old - cw)
        max_dy_old = max(0, ih * s_old - ch)
        
        max_dx_new = max(0, iw * s_new - cw)
        max_dy_new = max(0, ih * s_new - ch)
        
        if max_dx_new > 0:
            offset_x_val = (mx - cw / 2 - (s_new / s_old) * (mx - cw / 2 - self._zoom_offset_x * max_dx_old)) / max_dx_new
            self._zoom_offset_x = max(-0.5, min(0.5, offset_x_val))
        else:
            self._zoom_offset_x = 0.0
            
        if max_dy_new > 0:
            offset_y_val = (my - ch / 2 - (s_new / s_old) * (my - ch / 2 - self._zoom_offset_y * max_dy_old)) / max_dy_new
            self._zoom_offset_y = max(-0.5, min(0.5, offset_y_val))
        else:
            self._zoom_offset_y = 0.0
            
        self._zoom_factor = new_factor
        self._redraw_current()

    def _zoom_in(self, mx=None, my=None):
        if not self._current_pil:
            return
        if mx is None or my is None:
            mx, my = self._get_mouse_canvas_pos()
        new_factor = min(10.0, self._zoom_factor + 0.1)
        self._zoom_to_factor(new_factor, mx, my)

    def _zoom_out(self, mx=None, my=None):
        if not self._current_pil:
            return
        if mx is None or my is None:
            mx, my = self._get_mouse_canvas_pos()
        new_factor = max(0.1, self._zoom_factor - 0.1)
        self._zoom_to_factor(new_factor, mx, my)

    def _zoom_reset(self):
        if not self._current_pil:
            return
        self._zoom_factor = 1.0
        self._zoom_offset_x = 0.0
        self._zoom_offset_y = 0.0
        self._redraw_current()

    def _temp_rotate_right(self):
        if not self._current_pil:
            return
        self._temp_rotation = (self._temp_rotation + 90) % 360
        self._redraw_current()

    def _on_canvas_press(self, event):
        if self._crop_active:
            self._on_crop_press(event)
            return
        self._drag_start_x = event.x
        self._drag_start_y = event.y
        self._drag_start_offset_x = self._zoom_offset_x
        self._drag_start_offset_y = self._zoom_offset_y

    def _on_canvas_drag(self, event):
        if self._crop_active:
            self._on_crop_drag(event)
            return
        if self._zoom_factor <= 1.0:
            return
        dx = event.x - self._drag_start_x
        dy = event.y - self._drag_start_y
        cw, ch = self._canvas_size()
        display_pil = self._get_display_pil()
        if not display_pil:
            return
        iw, ih = display_pil.size
        base_scale = min(cw / iw, ch / ih)
        s = base_scale * self._zoom_factor
        nw = max(1, int(round(iw * s)))
        nh = max(1, int(round(ih * s)))
        
        max_dx = max(0, nw - cw)
        max_dy = max(0, nh - ch)
        
        if max_dx > 0:
            self._zoom_offset_x = max(-0.5, min(0.5, self._drag_start_offset_x + dx / max_dx))
        if max_dy > 0:
            self._zoom_offset_y = max(-0.5, min(0.5, self._drag_start_offset_y + dy / max_dy))
            
        self._redraw_current()

    def _on_canvas_release(self, event):
        if self._crop_active:
            self._on_crop_release(event)
            return

    def _on_mouse_wheel(self, event):
        if event.delta > 0:
            self._zoom_in(event.x, event.y)
        elif event.delta < 0:
            self._zoom_out(event.x, event.y)

    def _push_edit_history(self):
        path = self._current_path()
        if not path:
            return
        import copy
        hist = self._edit_history.setdefault(path, [])
        hist.append(copy.deepcopy(self._get_transform()))
        if len(hist) > 20:
            hist.pop(0)
        self._edit_redo_stack[path] = []
        self._update_undo_redo_btns()

    def _undo_edit(self):
        path = self._current_path()
        if not path:
            return
        hist = self._edit_history.get(path, [])
        if not hist:
            return
        import copy
        redo = self._edit_redo_stack.setdefault(path, [])
        redo.append(copy.deepcopy(self._get_transform()))
        self._edit_transforms[path] = hist.pop()
        self._refresh_edit_display()
        self._update_undo_redo_btns()

    def _redo_edit(self):
        path = self._current_path()
        if not path:
            return
        redo = self._edit_redo_stack.get(path, [])
        if not redo:
            return
        import copy
        hist = self._edit_history.setdefault(path, [])
        hist.append(copy.deepcopy(self._get_transform()))
        self._edit_transforms[path] = redo.pop()
        self._refresh_edit_display()
        self._update_undo_redo_btns()

    def _update_undo_redo_btns(self):
        path = self._current_path()
        c = self._ctrl()
        if self._undo_btn and self._undo_btn.winfo_exists():
            has_undo = bool(self._edit_history.get(path))
            self._undo_btn.config(fg=c["txt"] if has_undo else c["txt_dim"])
        if self._redo_btn and self._redo_btn.winfo_exists():
            has_redo = bool(self._edit_redo_stack.get(path))
            self._redo_btn.config(fg=c["txt"] if has_redo else c["txt_dim"])

    def _refresh_edit_display(self):
        if not self._current_pil:
            return
        display = self._get_edited_pil()
        cw, ch = self._canvas_size()
        self._fit_cache.clear()
        rendered = self._fit_image(display, cw, ch)
        self._show_pil_on_canvas(rendered)

    def _apply_rotation(self, deg):
        self._push_edit_history()
        t = self._get_transform()
        t["rotation"] = (t["rotation"] + deg) % 360
        self._refresh_edit_display()

    def _apply_flip(self, axis):
        self._push_edit_history()
        t = self._get_transform()
        if axis == "h":
            t["flip_h"] = not t["flip_h"]
        else:
            t["flip_v"] = not t["flip_v"]
        self._refresh_edit_display()

    def _start_crop(self):
        if not self._canvas:
            return
        self._crop_active = True
        self._canvas.config(cursor="crosshair")

    def _stop_crop(self):
        self._crop_active = False
        if self._canvas and self._canvas.winfo_exists():
            self._canvas.config(cursor="")
        if self._crop_rect_id and self._canvas:
            try:
                self._canvas.delete(self._crop_rect_id)
            except Exception:
                pass
            self._crop_rect_id = None
        self._crop_start = None

    def _on_crop_press(self, event):
        self._crop_start = (event.x, event.y)
        if self._crop_rect_id:
            self._canvas.delete(self._crop_rect_id)
            self._crop_rect_id = None

    def _on_crop_drag(self, event):
        if not self._crop_start:
            return
        x0, y0 = self._crop_start
        if self._crop_rect_id:
            self._canvas.delete(self._crop_rect_id)
        self._crop_rect_id = self._canvas.create_rectangle(
            x0, y0, event.x, event.y,
            outline="#FFD700", width=2, dash=(4, 4),
        )

    def _on_crop_release(self, event):
        if not self._crop_start:
            return
        x0, y0 = self._crop_start
        x1, y1 = event.x, event.y
        self._stop_crop()
        if abs(x1 - x0) < 10 or abs(y1 - y0) < 10:
            return
        lx, rx = min(x0, x1), max(x0, x1)
        ty, by = min(y0, y1), max(y0, y1)
        cw, ch = self._canvas_size()
        pil = self._get_edited_pil()
        if not pil:
            return
        iw, ih = pil.size
        scale = min(cw / iw, ch / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        ox, oy = (cw - nw) // 2, (ch - nh) // 2
        px0 = max(0, int((lx - ox) / scale))
        py0 = max(0, int((ty - oy) / scale))
        px1 = min(iw, int((rx - ox) / scale))
        py1 = min(ih, int((by - oy) / scale))
        if px1 > px0 and py1 > py0:
            self._apply_crop((px0, py0, px1, py1))

    def _apply_crop(self, box):
        self._push_edit_history()
        t = self._get_transform()
        cur = t["crop_box"]
        if cur:
            ox, oy = cur[0], cur[1]
            box = (ox + box[0], oy + box[1], ox + box[2], oy + box[3])
        t["crop_box"] = box
        self._fit_cache.clear()
        self._refresh_edit_display()

    def _show_resize_dialog(self):
        if not self._win:
            return
        pil = self._get_edited_pil()
        if not pil:
            return
        orig_w, orig_h = pil.size
        c = self._ctrl()
        dlg = tk.Toplevel(self._win)
        dlg.withdraw()
        dlg.title("Resize Image")
        dlg.configure(bg=c["bg2"])
        dlg.resizable(False, False)
        dlg.transient(self._win)
        dlg.grab_set()
        dw, dh = 320, 220
        dlg.update_idletasks()
        px, py = self._win.winfo_rootx(), self._win.winfo_rooty()
        pw, ph = self._win.winfo_width(), self._win.winfo_height()
        dlg.geometry(f"{dw}x{dh}+{px+(pw-dw)//2}+{py+(ph-dh)//2}")
        dlg.deiconify()
        tk.Frame(dlg, height=2, bg=c["accent"]).pack(fill=tk.X)
        tk.Label(dlg, text=f"⤡  Resize  (current: {orig_w}×{orig_h})",
                 font=("Segoe UI", 10, "bold"), bg=c["bg2"], fg=c["txt"]).pack(pady=(12, 4))
        row = tk.Frame(dlg, bg=c["bg2"])
        row.pack()
        w_var = tk.StringVar(value=str(orig_w))
        h_var = tk.StringVar(value=str(orig_h))
        tk.Label(row, text="W:", bg=c["bg2"], fg=c["txt_med"], font=("Segoe UI", 9)).grid(row=0, column=0, padx=4)
        tk.Entry(row, textvariable=w_var, width=7, bg=c["surface"], fg=c["txt"],
                 insertbackground=c["txt"], relief=tk.FLAT, font=("Segoe UI", 10),
                 highlightthickness=1, highlightbackground=c["border"]).grid(row=0, column=1, padx=4)
        tk.Label(row, text="H:", bg=c["bg2"], fg=c["txt_med"], font=("Segoe UI", 9)).grid(row=0, column=2, padx=4)
        tk.Entry(row, textvariable=h_var, width=7, bg=c["surface"], fg=c["txt"],
                 insertbackground=c["txt"], relief=tk.FLAT, font=("Segoe UI", 10),
                 highlightthickness=1, highlightbackground=c["border"]).grid(row=0, column=3, padx=4)
        pct_var = tk.StringVar(value="100")
        tk.Label(dlg, text="— or by % —", bg=c["bg2"], fg=c["txt_dim"], font=("Segoe UI", 8)).pack(pady=(8, 2))
        tk.Entry(dlg, textvariable=pct_var, width=6, bg=c["surface"], fg=c["txt"],
                 insertbackground=c["txt"], relief=tk.FLAT, font=("Segoe UI", 10),
                 highlightthickness=1, highlightbackground=c["border"], justify="center").pack()
        btn_row = tk.Frame(dlg, bg=c["bg2"])
        btn_row.pack(pady=12)

        def _apply(e=None):
            try:
                pct = float(pct_var.get())
                if pct != 100:
                    nw = max(1, int(orig_w * pct / 100))
                    nh = max(1, int(orig_h * pct / 100))
                else:
                    nw = max(1, int(w_var.get()))
                    nh = max(1, int(h_var.get()))
                self._apply_resize(nw, nh)
            except Exception:
                pass
            dlg.destroy()

        tk.Button(btn_row, text="Resize", command=_apply, bg=c["accent"], fg=c["play_fg"],
                  relief=tk.FLAT, font=("Segoe UI", 9, "bold"), padx=14, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(btn_row, text="Cancel", command=dlg.destroy, bg=c["btn"], fg=c["txt_med"],
                  relief=tk.FLAT, font=("Segoe UI", 9), padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT)
        dlg.bind("<Return>", _apply)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.wait_window()

    def _apply_resize(self, w, h):
        self._push_edit_history()
        self._get_transform()["resize"] = (w, h)
        self._fit_cache.clear()
        self._refresh_edit_display()

    def _show_tilt_dialog(self):
        if not self._win:
            return
        c = self._ctrl()
        dlg = tk.Toplevel(self._win)
        dlg.withdraw()
        dlg.title("Tilt")
        dlg.configure(bg=c["bg2"])
        dlg.resizable(False, False)
        dlg.transient(self._win)
        dlg.grab_set()
        dw, dh = 300, 160
        dlg.update_idletasks()
        px, py = self._win.winfo_rootx(), self._win.winfo_rooty()
        pw, ph = self._win.winfo_width(), self._win.winfo_height()
        dlg.geometry(f"{dw}x{dh}+{px+(pw-dw)//2}+{py+(ph-dh)//2}")
        dlg.deiconify()
        tk.Frame(dlg, height=2, bg=c["accent"]).pack(fill=tk.X)
        tk.Label(dlg, text="◪  Tilt (−45° to +45°)",
                 font=("Segoe UI", 10, "bold"), bg=c["bg2"], fg=c["txt"]).pack(pady=(12, 6))
        cur_tilt = self._get_transform().get("tilt", 0.0)
        angle_var = tk.DoubleVar(value=cur_tilt)
        val_lbl = tk.Label(dlg, text=f"{cur_tilt:.1f}°", bg=c["bg2"], fg=c["accent"],
                           font=("Segoe UI", 10, "bold"))
        val_lbl.pack()
        def _update_label(v):
            val_lbl.config(text=f"{float(v):.1f}°")
        sl = tk.Scale(dlg, variable=angle_var, from_=-45, to=45, resolution=0.5,
                      orient=tk.HORIZONTAL, length=260, bg=c["bg2"], fg=c["txt"],
                      troughcolor=c["track"], highlightthickness=0, showvalue=False,
                      command=_update_label)
        sl.pack(padx=16)
        btn_row = tk.Frame(dlg, bg=c["bg2"])
        btn_row.pack(pady=10)

        def _apply(e=None):
            self._apply_tilt(angle_var.get())
            dlg.destroy()

        tk.Button(btn_row, text="Apply", command=_apply, bg=c["accent"], fg=c["play_fg"],
                  relief=tk.FLAT, font=("Segoe UI", 9, "bold"), padx=14, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(btn_row, text="Cancel", command=dlg.destroy, bg=c["btn"], fg=c["txt_med"],
                  relief=tk.FLAT, font=("Segoe UI", 9), padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT)
        dlg.bind("<Return>", _apply)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.wait_window()

    def _apply_tilt(self, angle):
        self._push_edit_history()
        self._get_transform()["tilt"] = angle
        self._fit_cache.clear()
        self._refresh_edit_display()

    def _show_free_rotation_dialog(self):
        if not self._win:
            return
        c = self._ctrl()
        dlg = tk.Toplevel(self._win)
        dlg.withdraw()
        dlg.title("Free Rotation")
        dlg.configure(bg=c["bg2"])
        dlg.resizable(False, False)
        dlg.transient(self._win)
        dlg.grab_set()
        dw, dh = 300, 160
        dlg.update_idletasks()
        px, py = self._win.winfo_rootx(), self._win.winfo_rooty()
        pw, ph = self._win.winfo_width(), self._win.winfo_height()
        dlg.geometry(f"{dw}x{dh}+{px+(pw-dw)//2}+{py+(ph-dh)//2}")
        dlg.deiconify()
        tk.Frame(dlg, height=2, bg=c["accent"]).pack(fill=tk.X)
        tk.Label(dlg, text="↺  Free Rotation (degrees)",
                 font=("Segoe UI", 10, "bold"), bg=c["bg2"], fg=c["txt"]).pack(pady=(12, 6))
        angle_var = tk.StringVar(value="0")
        tk.Entry(dlg, textvariable=angle_var, width=8, bg=c["surface"], fg=c["txt"],
                 insertbackground=c["txt"], relief=tk.FLAT, font=("Segoe UI", 12),
                 highlightthickness=1, highlightbackground=c["border"], justify="center").pack(ipady=4)
        tk.Label(dlg, text="Positive = CW, Negative = CCW",
                 bg=c["bg2"], fg=c["txt_dim"], font=("Segoe UI", 7)).pack(pady=(2, 0))
        btn_row = tk.Frame(dlg, bg=c["bg2"])
        btn_row.pack(pady=10)

        def _apply(e=None):
            try:
                deg = float(angle_var.get())
                self._apply_rotation(deg)
            except Exception:
                pass
            dlg.destroy()

        tk.Button(btn_row, text="Rotate", command=_apply, bg=c["accent"], fg=c["play_fg"],
                  relief=tk.FLAT, font=("Segoe UI", 9, "bold"), padx=14, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(btn_row, text="Cancel", command=dlg.destroy, bg=c["btn"], fg=c["txt_med"],
                  relief=tk.FLAT, font=("Segoe UI", 9), padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT)
        dlg.bind("<Return>", _apply)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.wait_window()

    def _show_adjust_dialog(self, adjust_type):
        if not self._win:
            return
        c = self._ctrl()
        labels = {"brightness": ("☀  Brightness", "brightness"),
                  "contrast":   ("◑  Contrast",   "contrast"),
                  "sharpness":  ("⬡  Sharpness",  "sharpness")}
        title_txt, key = labels[adjust_type]
        cur_val = self._get_transform().get(key, 1.0)
        dlg = tk.Toplevel(self._win)
        dlg.withdraw()
        dlg.title(title_txt.split()[-1])
        dlg.configure(bg=c["bg2"])
        dlg.resizable(False, False)
        dlg.transient(self._win)
        dlg.grab_set()
        dw, dh = 300, 160
        dlg.update_idletasks()
        px, py = self._win.winfo_rootx(), self._win.winfo_rooty()
        pw, ph = self._win.winfo_width(), self._win.winfo_height()
        dlg.geometry(f"{dw}x{dh}+{px+(pw-dw)//2}+{py+(ph-dh)//2}")
        dlg.deiconify()
        tk.Frame(dlg, height=2, bg=c["accent"]).pack(fill=tk.X)
        tk.Label(dlg, text=title_txt, font=("Segoe UI", 10, "bold"),
                 bg=c["bg2"], fg=c["txt"]).pack(pady=(12, 6))
        val_var = tk.DoubleVar(value=cur_val)
        val_lbl = tk.Label(dlg, text=f"{cur_val:.2f}×", bg=c["bg2"], fg=c["accent"],
                           font=("Segoe UI", 10, "bold"))
        val_lbl.pack()
        def _update_label(v):
            val_lbl.config(text=f"{float(v):.2f}×")
        sl = tk.Scale(dlg, variable=val_var, from_=0.0, to=3.0, resolution=0.05,
                      orient=tk.HORIZONTAL, length=260, bg=c["bg2"], fg=c["txt"],
                      troughcolor=c["track"], highlightthickness=0, showvalue=False,
                      command=_update_label)
        sl.pack(padx=16)
        btn_row = tk.Frame(dlg, bg=c["bg2"])
        btn_row.pack(pady=10)

        def _apply(e=None):
            self._push_edit_history()
            self._get_transform()[key] = val_var.get()
            self._fit_cache.clear()
            self._refresh_edit_display()
            dlg.destroy()

        tk.Button(btn_row, text="Apply", command=_apply, bg=c["accent"], fg=c["play_fg"],
                  relief=tk.FLAT, font=("Segoe UI", 9, "bold"), padx=14, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(btn_row, text="Cancel", command=dlg.destroy, bg=c["btn"], fg=c["txt_med"],
                  relief=tk.FLAT, font=("Segoe UI", 9), padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT)
        dlg.bind("<Return>", _apply)
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.wait_window()

    def _save_edit(self, overwrite=True):
        path = self._current_path()
        if not path:
            return
        edited = self._get_edited_pil()
        if not edited:
            return
        if overwrite:
            from tkinter import messagebox
            if not messagebox.askyesno(
                "Overwrite?", f"Overwrite original file?\n{os.path.basename(path)}",
                parent=self._win
            ):
                return
            save_path = path
        else:
            ext = os.path.splitext(path)[1].lower() or ".jpg"
            fmt_map = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG",
                       ".bmp": "BMP", ".tiff": "TIFF", ".tif": "TIFF"}
            filetypes = [("Image files", "*.jpg *.jpeg *.png *.bmp *.tiff"), ("All", "*.*")]
            save_path = filedialog.asksaveasfilename(
                title="Save As", defaultextension=ext, filetypes=filetypes,
                initialfile=os.path.basename(path), parent=self._win,
            )
            if not save_path:
                return
        try:
            ext = os.path.splitext(save_path)[1].lower()
            fmt = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG",
                   ".bmp": "BMP", ".tiff": "TIFF", ".tif": "TIFF"}.get(ext, "JPEG")
            save_img = edited
            if fmt == "JPEG" and save_img.mode != "RGB":
                save_img = save_img.convert("RGB")
            save_img.save(save_path, fmt, quality=95)
            if overwrite and save_path == path:
                if path in self._preload_cache:
                    del self._preload_cache[path]
                self._current_pil = self._load_pil(path)
            self.logger(f"Slideshow: saved edit → {save_path}")
        except Exception as e:
            self.logger(f"Slideshow: save failed: {e}")

    def _reset_edits(self):
        path = self._current_path()
        if not path:
            return
        self._edit_transforms.pop(path, None)
        self._edit_history.pop(path, None)
        self._edit_redo_stack.pop(path, None)
        if path in self._preload_cache:
            del self._preload_cache[path]
        self._fit_cache.clear()
        self._current_pil = self._load_pil(path)
        self._refresh_edit_display()
        self._update_undo_redo_btns()

    def _toggle_edit_mode(self):
        if self._edit_mode:
            self._close_editor()
        else:
            self._open_editor()

    def _open_editor(self):
        self._edit_mode = True
        if self._edit_bar and self._edit_bar.winfo_exists():
            self._edit_bar.place(relx=0.0, rely=0.0, anchor="nw", relwidth=1.0)
            self._edit_bar.lift()
        if self._edit_btn and self._edit_btn.winfo_exists():
            c = self._ctrl()
            self._edit_btn.config(bg=c["accent"], fg=c["play_fg"])
        self._update_undo_redo_btns()
        self._refresh_edit_display()

    def _close_editor(self):
        self._stop_crop()
        self._edit_mode = False
        if self._edit_bar and self._edit_bar.winfo_exists():
            self._edit_bar.place_forget()
        if self._edit_btn and self._edit_btn.winfo_exists():
            c = self._ctrl()
            self._edit_btn.config(bg=c["btn"], fg=c["txt_med"])
        self._load_current()

    def _build_edit_bar(self, win):
        c = self._ctrl()
        F = self._fonts()
        bar = tk.Frame(win, bg=c["bg"], bd=0)
        self._edit_bar = bar

        tk.Frame(bar, bg=c["border"], height=1).pack(fill=tk.X, side=tk.BOTTOM)

        inner = tk.Frame(bar, bg=c["bg"])
        inner.pack(fill=tk.X, padx=8, pady=4)

        def _eb(parent, text, cmd, fg=None, accent=False):
            b = self._make_btn(parent, text, cmd, font=F["sm"], fg=fg, accent=accent, padx=6, pady=3)
            b.pack(side=tk.LEFT, padx=2)
            return b

        def _sep():
            tk.Frame(inner, width=1, bg=c["border"]).pack(side=tk.LEFT, fill=tk.Y, pady=4, padx=3)

        tk.Label(inner, text="ROTATE", bg=c["bg"], fg=c["txt_dim"],
                 font=F["xs"]).pack(side=tk.LEFT, padx=(4, 2))
        _eb(inner, "↺ 90°", lambda: self._apply_rotation(-90))
        _eb(inner, "↻ 90°", lambda: self._apply_rotation(90))
        _eb(inner, "↺ Free", self._show_free_rotation_dialog)

        _sep()
        tk.Label(inner, text="FLIP", bg=c["bg"], fg=c["txt_dim"],
                 font=F["xs"]).pack(side=tk.LEFT, padx=(4, 2))
        _eb(inner, "↔ H-Flip", lambda: self._apply_flip("h"))
        _eb(inner, "↕ V-Flip", lambda: self._apply_flip("v"))

        _sep()
        tk.Label(inner, text="CROP", bg=c["bg"], fg=c["txt_dim"],
                 font=F["xs"]).pack(side=tk.LEFT, padx=(4, 2))
        _eb(inner, "⌂ Crop", self._start_crop)

        _sep()
        tk.Label(inner, text="RESIZE", bg=c["bg"], fg=c["txt_dim"],
                 font=F["xs"]).pack(side=tk.LEFT, padx=(4, 2))
        _eb(inner, "⤡ Resize", self._show_resize_dialog)

        _sep()
        tk.Label(inner, text="TILT", bg=c["bg"], fg=c["txt_dim"],
                 font=F["xs"]).pack(side=tk.LEFT, padx=(4, 2))
        _eb(inner, "◪ Tilt", self._show_tilt_dialog)

        _sep()
        tk.Label(inner, text="ADJUST", bg=c["bg"], fg=c["txt_dim"],
                 font=F["xs"]).pack(side=tk.LEFT, padx=(4, 2))
        _eb(inner, "☀ Brightness", lambda: self._show_adjust_dialog("brightness"))
        _eb(inner, "◑ Contrast",   lambda: self._show_adjust_dialog("contrast"))
        _eb(inner, "⬡ Sharpness",  lambda: self._show_adjust_dialog("sharpness"))

        _sep()
        self._undo_btn = _eb(inner, "↩ Undo", self._undo_edit, fg=c["txt_dim"])
        self._redo_btn = _eb(inner, "↪ Redo", self._redo_edit, fg=c["txt_dim"])

        _sep()
        _eb(inner, "💾 Save",    self._save_edit, accent=True)
        _eb(inner, "📋 Save As", lambda: self._save_edit(overwrite=False))

        _sep()
        _eb(inner, "✕ Reset All", self._reset_edits, fg=c["txt_dim"])

        self._bind_chrome_hover(bar)
        for child in bar.winfo_children():
            self._bind_chrome_hover(child)

    # ── Audio ─────────────────────────────────────────────────────────────────

    def _show_add_music_menu(self, anchor):
        menu = self._context_menu()
        menu.add_command(label="♪  Add individual songs…", command=self._pick_songs)
        menu.add_command(label="📁  Add folder of songs…", command=self._pick_song_folder)
        if self._songs:
            menu.add_separator()
            menu.add_command(label="🔀  Shuffle playlist", command=self._shuffle_songs)
            menu.add_command(label="✕  Clear all music", command=self._clear_music)
        try:
            x = anchor.winfo_rootx()
            y = anchor.winfo_rooty() + anchor.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _pick_songs(self):
        paths = filedialog.askopenfilenames(
            title="Select songs",
            filetypes=[
                ("Audio files",
                 "*.mp3 *.wav *.ogg *.flac *.m4a *.aac *.wma"),
                ("All files", "*.*"),
            ],
            parent=self._win,
        )
        if paths:
            self._add_songs(list(paths))

    def _pick_song_folder(self):
        folder = filedialog.askdirectory(
            title="Select folder of songs",
            parent=self._win,
        )
        if not folder:
            return
        found = []
        for ext in AUDIO_EXTENSIONS:
            found.extend(glob.glob(os.path.join(folder, f"*{ext}")))
            found.extend(glob.glob(os.path.join(folder, f"*{ext.upper()}")))
        found = sorted(set(found))
        if found:
            random.shuffle(found)
            self._add_songs(found)
            self.logger(f"Slideshow: added {len(found)} songs from folder")
        else:
            self.logger("Slideshow: no audio files found in that folder")

    def _add_songs(self, paths):
        new_songs = [p for p in paths if is_audio(p) and p not in self._songs]
        if not new_songs:
            return
        was_empty = not self._songs
        self._songs.extend(new_songs)
        if was_empty:
            self._pygame = _init_pygame()
            if self._pygame:
                self._song_index = 0
                self._play_current_song()
            else:
                self.logger("Slideshow: install pygame for audio support (pip install pygame)")
        else:
            self._update_now_playing_label()
        self._refresh_music_bar()

    def _shuffle_songs(self):
        if not self._songs:
            return
        current = self._songs[self._song_index % len(self._songs)] if self._songs else None
        random.shuffle(self._songs)
        if current and current in self._songs:
            self._song_index = self._songs.index(current)
        else:
            self._song_index = 0
        self._update_now_playing_label()
        self.logger(f"Slideshow: playlist shuffled ({len(self._songs)} songs)")

    def _clear_music(self):
        self._stop_audio()
        self._songs      = []
        self._song_index = 0
        self._update_now_playing_label()
        self._refresh_music_bar()

    def _play_current_song(self):
        if not self._songs or not self._pygame:
            return
        try:
            path = self._songs[self._song_index % len(self._songs)]
            self._pygame.mixer.music.load(path)
            vol = 0.0 if self._audio_muted else self._audio_volume
            self._pygame.mixer.music.set_volume(vol)
            self._pygame.mixer.music.play()
            self._update_now_playing_label()
            self._start_audio_monitor()
        except Exception as e:
            self.logger(f"Slideshow audio error: {e}")
            # Try next song instead of stopping
            self._song_index = (self._song_index + 1) % max(1, len(self._songs))
            self._win.after(500, self._play_current_song)

    def _start_audio_monitor(self):
        """Poll pygame every 800 ms; when a song ends, advance to next."""
        if self._audio_monitor_id:
            try:
                self._win.after_cancel(self._audio_monitor_id)
            except Exception:
                pass

        def _check():
            if self._closing or not self._songs or not self._pygame:
                return
            try:
                if not self._pygame.mixer.music.get_busy():
                    self._next_song()
                    return
            except Exception:
                return
            if self._win and self._win.winfo_exists():
                self._audio_monitor_id = self._win.after(800, _check)

        if self._win and self._win.winfo_exists():
            self._audio_monitor_id = self._win.after(800, _check)

    def _next_song(self):
        if not self._songs:
            return
        self._song_index = (self._song_index + 1) % len(self._songs)
        self._play_current_song()

    def _prev_song(self):
        if not self._songs:
            return
        self._song_index = (self._song_index - 1) % len(self._songs)
        self._play_current_song()

    def _toggle_mute(self):
        self._audio_muted = not self._audio_muted
        if self._mute_btn and self._mute_btn.winfo_exists():
            self._mute_btn.config(text="🔇" if self._audio_muted else "🔊")
        if self._pygame:
            try:
                vol = 0.0 if self._audio_muted else self._audio_volume
                self._pygame.mixer.music.set_volume(vol)
            except Exception:
                pass

    def _stop_audio(self):
        if self._audio_monitor_id:
            try:
                if self._win and self._win.winfo_exists():
                    self._win.after_cancel(self._audio_monitor_id)
            except Exception:
                pass
            self._audio_monitor_id = None
        if self._pygame:
            try:
                self._pygame.mixer.music.stop()
            except Exception:
                pass

    def _draw_vol_slider(self):
        if not self._vol_canvas or not self._vol_canvas.winfo_exists():
            return
        c = self._ctrl()
        self._vol_canvas.delete("all")
        w = max(1, self._vol_canvas.winfo_width())
        h = max(1, self._vol_canvas.winfo_height())
        cy = h // 2
        filled = int(w * self._audio_volume)
        self._vol_canvas.create_rectangle(0, cy - 2, w, cy + 2, fill=c["track"], outline="")
        if filled > 0:
            self._vol_canvas.create_rectangle(
                0, cy - 2, filled, cy + 2, fill=c["accent"], outline="")
        self._vol_canvas.create_oval(
            filled - 4, cy - 4, filled + 4, cy + 4, fill="#FFFFFF", outline="")

    def _on_vol_click(self, event):
        w = max(1, self._vol_canvas.winfo_width())
        vol = max(0.0, min(1.0, event.x / w))
        self._audio_volume = vol
        self._audio_muted  = False
        if self._mute_btn and self._mute_btn.winfo_exists():
            self._mute_btn.config(text="🔊")
        if self._pygame:
            try:
                self._pygame.mixer.music.set_volume(vol)
            except Exception:
                pass
        self._draw_vol_slider()

    def _update_now_playing_label(self):
        if not self._now_playing_lbl or not self._now_playing_lbl.winfo_exists():
            return
        c = self._ctrl()
        if not self._songs:
            self._now_playing_lbl.config(text="No music added", fg=c["txt_dim"])
            return
        name = os.path.splitext(
            os.path.basename(self._songs[self._song_index % len(self._songs)]))[0]
        if len(name) > 50:
            name = name[:47] + "…"
        pos = self._song_index % len(self._songs) + 1
        self._now_playing_lbl.config(
            text=f"♪  {name}   [{pos} / {len(self._songs)}]",
            fg=c["txt_med"],
        )