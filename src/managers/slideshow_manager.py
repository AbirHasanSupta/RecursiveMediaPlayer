import tkinter as tk
from tkinter import filedialog
from PIL import Image, ImageTk
import os
import threading
import time
import random
import glob

from utils import is_photo, is_audio, PHOTO_EXTENSIONS, AUDIO_EXTENSIONS
from managers.settings_manager import DEFAULT_HOTKEYS
from managers.resource_manager import get_resource_manager


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

        # UI widget refs (set in _build_window)
        self._play_btn          = None
        self._counter_lbl       = None
        self._progress_canvas   = None
        self._now_playing_lbl   = None
        self._mute_btn          = None
        self._vol_canvas        = None
        self._dur_var           = None
        self._trans_var         = None
        self._kb_var            = None
        self._fullscreen        = False
        self._slideshow_mode    = False
        self._slideshow_opts_frame = None
        self._hotkeys           = dict(DEFAULT_HOTKEYS)
        self._registered_cbids  = []
        self._fit_cache         = {}  # (path, cw, ch) -> rendered PIL
        get_resource_manager().register_cleanup_callback(self.cleanup)

    def _reset_widget_state(self):
        """Clear canvas/widget refs after window destroy (fixes blank reopen)."""
        self._canvas            = None
        self._photo_img         = None
        self._canvas_img_id     = None
        self._play_btn          = None
        self._counter_lbl       = None
        self._progress_canvas   = None
        self._now_playing_lbl   = None
        self._mute_btn          = None
        self._vol_canvas        = None
        self._dur_var           = None
        self._trans_var         = None
        self._trans_display_var = None
        self._kb_var            = None
        self._registered_cbids  = []

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
        self._cancel_timers()
        self._stop_audio()
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
        win = tk.Toplevel(self.root)
        win.title("Photo Viewer")
        win.configure(bg="#000000")
        win.geometry("1280x820")
        win.protocol("WM_DELETE_WINDOW", self.close)
        self._win = win

        try:
            from icon_helper import apply_icon
            apply_icon(win)
        except Exception:
            pass

        self._build_top_bar(win)
        self._build_audio_bar(win)
        self._build_canvas(win)
        self._build_control_bar(win)
        self._bind_keys(win)

    def _apply_slideshow_mode_ui(self):
        """Viewer mode: static image only. Slideshow mode: show timing/transition controls."""
        if self._slideshow_opts_frame:
            if self._slideshow_mode:
                if not self._slideshow_opts_frame.winfo_ismapped():
                    self._slideshow_opts_frame.pack(side=tk.LEFT, fill=tk.Y)
            else:
                self._slideshow_opts_frame.pack_forget()
        if self._win and self._win.winfo_exists():
            self._win.title("Photo Slideshow" if self._slideshow_mode else "Photo Viewer")

    def _enter_slideshow_mode(self):
        if self._slideshow_mode:
            return
        self._slideshow_mode = True
        self._apply_slideshow_mode_ui()

    # ── Top bar ───────────────────────────────────────────────────────────────

    def _build_top_bar(self, win):
        top = tk.Frame(win, bg="#111111", height=44)
        top.pack(fill=tk.X)
        top.pack_propagate(False)

        tk.Label(top, text="🖼  Photo Viewer",
                 font=("Segoe UI", 11, "bold"),
                 bg="#111111", fg="#ffffff").pack(side=tk.LEFT, padx=16, pady=10)

        self._slideshow_opts_frame = tk.Frame(top, bg="#111111")
        opts = self._slideshow_opts_frame

        # Duration spinbox
        tk.Label(opts, text="Duration:",
                 font=("Segoe UI", 9),
                 bg="#111111", fg="#aaaaaa").pack(side=tk.LEFT, padx=(20, 4), pady=10)
        self._dur_var = tk.DoubleVar(value=self.duration)
        dur_spin = tk.Spinbox(
            opts, from_=0.5, to=60.0, increment=0.5,
            textvariable=self._dur_var, width=5,
            font=("Segoe UI", 9),
            bg="#1e1e1e", fg="#ffffff",
            relief=tk.FLAT, bd=0,
            highlightthickness=1, highlightbackground="#333333",
            buttonbackground="#1e1e1e",
            insertbackground="#ffffff",
            command=self._on_duration_changed,
        )
        dur_spin.pack(side=tk.LEFT, pady=10)
        dur_spin.bind("<FocusOut>", lambda e: self._on_duration_changed())
        tk.Label(opts, text="s",
                 font=("Segoe UI", 9),
                 bg="#111111", fg="#aaaaaa").pack(side=tk.LEFT, pady=10)

        # Transition picker
        tk.Label(opts, text="Transition:",
                 font=("Segoe UI", 9),
                 bg="#111111", fg="#aaaaaa").pack(side=tk.LEFT, padx=(20, 4), pady=10)
        self._trans_var = tk.StringVar(value=self.transition)
        trans_labels = [self.TRANSITION_LABELS[t] for t in self.TRANSITIONS]
        self._trans_label_to_key = {self.TRANSITION_LABELS[t]: t for t in self.TRANSITIONS}
        self._trans_display_var = tk.StringVar(value=self.TRANSITION_LABELS[self.transition])
        trans_om = tk.OptionMenu(
            opts, self._trans_display_var,
            *trans_labels,
            command=self._on_transition_changed,
        )
        trans_om.config(
            font=("Segoe UI", 9), bg="#1e1e1e", fg="#ffffff",
            relief=tk.FLAT, highlightthickness=1, highlightbackground="#333333",
            activebackground="#2a2a2a", width=11,
        )
        trans_om["menu"].config(
            bg="#1e1e1e", fg="#ffffff",
            activebackground="#333333", activeforeground="#ffffff",
            relief=tk.FLAT,
        )
        trans_om.pack(side=tk.LEFT, pady=10)

        # Ken Burns toggle
        self._kb_var = tk.BooleanVar(value=self.ken_burns)
        kb_chk = tk.Checkbutton(
            opts, text="Ken Burns", variable=self._kb_var,
            font=("Segoe UI", 9),
            bg="#111111", fg="#aaaaaa",
            selectcolor="#333333",
            activebackground="#111111",
            activeforeground="#ffffff",
            command=self._on_kb_changed,
        )
        kb_chk.pack(side=tk.LEFT, padx=(20, 0), pady=10)

        # Fullscreen button
        fs_btn = tk.Label(top, text="⛶",
                          font=("Segoe UI", 14),
                          bg="#111111", fg="#aaaaaa",
                          cursor="hand2", padx=12)
        fs_btn.pack(side=tk.RIGHT, pady=10)
        fs_btn.bind("<Button-1>", lambda e: self._toggle_fullscreen())
        fs_btn.bind("<Enter>",    lambda e: fs_btn.config(fg="#ffffff"))
        fs_btn.bind("<Leave>",    lambda e: fs_btn.config(fg="#aaaaaa"))

        # Counter
        self._counter_lbl = tk.Label(top, text="",
                                      font=("Segoe UI", 9),
                                      bg="#111111", fg="#666666")
        self._counter_lbl.pack(side=tk.RIGHT, padx=12, pady=10)

    # ── Audio bar ─────────────────────────────────────────────────────────────

    def _build_audio_bar(self, win):
        audio_bar = tk.Frame(win, bg="#0d0d0d", height=40)
        audio_bar.pack(fill=tk.X)
        audio_bar.pack_propagate(False)

        # Add music button
        add_btn = tk.Label(audio_bar, text="♪ Add Music",
                           font=("Segoe UI", 9, "bold"),
                           bg="#0d0d0d", fg="#5E81F4",
                           cursor="hand2", padx=12, pady=10)
        add_btn.pack(side=tk.LEFT)
        add_btn.bind("<Button-1>", lambda e: self._show_add_music_menu(add_btn))
        add_btn.bind("<Enter>",    lambda e: add_btn.config(fg="#7c9ff5"))
        add_btn.bind("<Leave>",    lambda e: add_btn.config(fg="#5E81F4"))

        tk.Frame(audio_bar, bg="#222222", width=1).pack(
            side=tk.LEFT, fill=tk.Y, pady=6)

        def _ab_btn(text, cmd):
            lbl = tk.Label(audio_bar, text=text,
                           font=("Segoe UI", 12),
                           bg="#0d0d0d", fg="#777777",
                           cursor="hand2", padx=8, pady=8)
            lbl.bind("<Button-1>", lambda e: cmd())
            lbl.bind("<Enter>",    lambda e: lbl.config(fg="#ffffff"))
            lbl.bind("<Leave>",    lambda e: lbl.config(fg="#777777"))
            return lbl

        _ab_btn("⏮", self._prev_song).pack(side=tk.LEFT)
        _ab_btn("⏭", self._next_song).pack(side=tk.LEFT)

        tk.Frame(audio_bar, bg="#222222", width=1).pack(
            side=tk.LEFT, fill=tk.Y, pady=6)

        # Mute button
        self._mute_btn = tk.Label(audio_bar, text="🔊",
                                   font=("Segoe UI", 11),
                                   bg="#0d0d0d", fg="#777777",
                                   cursor="hand2", padx=8, pady=8)
        self._mute_btn.pack(side=tk.LEFT)
        self._mute_btn.bind("<Button-1>", lambda e: self._toggle_mute())
        self._mute_btn.bind("<Enter>",    lambda e: self._mute_btn.config(fg="#ffffff"))
        self._mute_btn.bind("<Leave>",    lambda e: self._mute_btn.config(fg="#777777"))

        # Volume label
        tk.Label(audio_bar, text="Vol",
                 font=("Segoe UI", 8),
                 bg="#0d0d0d", fg="#444444").pack(side=tk.LEFT, padx=(4, 2))

        # Volume slider
        self._vol_canvas = tk.Canvas(audio_bar, bg="#0d0d0d",
                                      width=90, height=14,
                                      highlightthickness=0, cursor="hand2")
        self._vol_canvas.pack(side=tk.LEFT, pady=13)
        self._vol_canvas.bind("<Button-1>",  self._on_vol_click)
        self._vol_canvas.bind("<B1-Motion>", self._on_vol_click)
        self._vol_canvas.bind("<Configure>", lambda e: self._draw_vol_slider())

        tk.Frame(audio_bar, bg="#222222", width=1).pack(
            side=tk.LEFT, fill=tk.Y, pady=6, padx=6)

        # Now playing label
        self._now_playing_lbl = tk.Label(audio_bar, text="No music added",
                                          font=("Segoe UI", 9, "italic"),
                                          bg="#0d0d0d", fg="#444444",
                                          anchor="w")
        self._now_playing_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)

        # Shuffle button
        shuf_btn = tk.Label(audio_bar, text="🔀",
                            font=("Segoe UI", 10),
                            bg="#0d0d0d", fg="#444444",
                            cursor="hand2", padx=8)
        shuf_btn.pack(side=tk.RIGHT)
        shuf_btn.bind("<Button-1>", lambda e: self._shuffle_songs())
        shuf_btn.bind("<Enter>",    lambda e: shuf_btn.config(fg="#5E81F4"))
        shuf_btn.bind("<Leave>",    lambda e: shuf_btn.config(fg="#444444"))

        # Clear music button
        clear_btn = tk.Label(audio_bar, text="✕",
                              font=("Segoe UI", 10),
                              bg="#0d0d0d", fg="#444444",
                              cursor="hand2", padx=10)
        clear_btn.pack(side=tk.RIGHT)
        clear_btn.bind("<Button-1>", lambda e: self._clear_music())
        clear_btn.bind("<Enter>",    lambda e: clear_btn.config(fg="#e05555"))
        clear_btn.bind("<Leave>",    lambda e: clear_btn.config(fg="#444444"))

    # ── Main canvas ───────────────────────────────────────────────────────────

    def _build_canvas(self, win):
        self._canvas = tk.Canvas(win, bg="#000000", highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas.bind("<Configure>",    lambda e: self._on_canvas_resize(e))
        self._canvas.bind("<Button-1>",     lambda e: self._toggle_play())
        self._canvas.bind("<Button-3>",     lambda e: self._show_context(e))
        self._canvas.bind("<Double-Button-1>", lambda e: self._toggle_fullscreen())

    # ── Bottom control bar ────────────────────────────────────────────────────

    def _build_control_bar(self, win):
        ctrl = tk.Frame(win, bg="#111111", height=50)
        ctrl.pack(fill=tk.X)
        ctrl.pack_propagate(False)

        def _ctrl_btn(text, cmd, fg="#cccccc", size=13):
            lbl = tk.Label(ctrl, text=text,
                           font=("Segoe UI", size),
                           bg="#111111", fg=fg,
                           cursor="hand2", padx=12, pady=12)
            lbl.bind("<Button-1>", lambda e: cmd())
            lbl.bind("<Enter>",    lambda e: lbl.config(fg="#5E81F4"))
            lbl.bind("<Leave>",    lambda e: lbl.config(fg=fg))
            return lbl

        _ctrl_btn("⏮", self._go_first).pack(side=tk.LEFT)
        _ctrl_btn("⏪", self._prev).pack(side=tk.LEFT)

        self._play_btn = tk.Label(ctrl, text="⏵",
                                   font=("Segoe UI", 18),
                                   bg="#111111", fg="#3ecf6e",
                                   cursor="hand2", padx=12, pady=10)
        self._play_btn.pack(side=tk.LEFT)
        self._play_btn.bind("<Button-1>", lambda e: self._toggle_play())
        self._play_btn.bind("<Enter>",    lambda e: self._play_btn.config(fg="#5E81F4"))
        self._play_btn.bind("<Leave>",    lambda e: self._play_btn.config(
            fg="#3ecf6e" if self.playing else "#cccccc"))

        _ctrl_btn("⏩", self._next).pack(side=tk.LEFT)
        _ctrl_btn("⏭", self._go_last).pack(side=tk.LEFT)

        # Progress bar
        self._progress_canvas = tk.Canvas(ctrl, bg="#1a1a1a",
                                           height=6, highlightthickness=0,
                                           cursor="hand2")
        self._progress_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True,
                                    padx=16, pady=22)
        self._progress_canvas.bind("<Button-1>",  self._on_progress_click)
        self._progress_canvas.bind("<B1-Motion>", self._on_progress_click)
        self._progress_canvas.bind("<Configure>", lambda e: self._update_progress())

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
        cw, ch = self._canvas_size()
        rendered = self._fit_image(self._current_pil, cw, ch)
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
        self._play_btn.config(text="⏸" if self.playing else "⏵",
                               fg="#3ecf6e" if self.playing else "#cccccc")

    def _update_counter(self):
        if not self._counter_lbl or not self._counter_lbl.winfo_exists():
            return
        self._counter_lbl.config(
            text=f"{self.index + 1} / {len(self.photos)}")

    def _update_progress(self, within_fraction=0.0):
        if not self._progress_canvas or not self._progress_canvas.winfo_exists():
            return
        self._progress_canvas.delete("all")
        w = max(1, self._progress_canvas.winfo_width())
        n = max(1, len(self.photos) - 1)
        slide_frac = self.index / n

        # Track
        self._progress_canvas.create_rectangle(
            0, 1, w, 5, fill="#2a2a2a", outline="")
        # Filled portion
        filled_x = int(w * slide_frac)
        if filled_x > 0:
            self._progress_canvas.create_rectangle(
                0, 1, filled_x, 5, fill="#5E81F4", outline="")
        # Within-slide dot
        if within_fraction > 0:
            per_slide = w / max(1, len(self.photos))
            dot_x = max(5, min(w - 5,
                               int(filled_x + per_slide * within_fraction)))
            self._progress_canvas.create_oval(
                dot_x - 4, -1, dot_x + 4, 7, fill="#ffffff", outline="")

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
            rendered = self._fit_image(self._current_pil, event.width, event.height)
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
        self._fullscreen = not self._fullscreen
        self._win.attributes("-fullscreen", self._fullscreen)

    def _exit_fullscreen(self):
        self._fullscreen = False
        self._win.attributes("-fullscreen", False)

    def _show_context(self, event):
        menu = tk.Menu(self._win, tearoff=0,
                       bg="#1e1e1e", fg="#ffffff",
                       activebackground="#333333",
                       activeforeground="#ffffff",
                       relief=tk.FLAT)
        menu.add_command(label="⏵  Play Slideshow",  command=self._toggle_play)
        menu.add_command(label="⏪  Previous",        command=self._prev)
        menu.add_command(label="⏩  Next",            command=self._next)
        menu.add_separator()
        menu.add_command(label="⛶  Toggle Fullscreen", command=self._toggle_fullscreen)
        menu.add_separator()
        menu.add_command(label="📁  Open File Location",
                         command=lambda: self._open_location(self.photos[self.index]))
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

    # ── Audio ─────────────────────────────────────────────────────────────────

    def _show_add_music_menu(self, anchor):
        menu = tk.Menu(self._win, tearoff=0,
                       bg="#1e1e1e", fg="#ffffff",
                       activebackground="#333333",
                       activeforeground="#ffffff",
                       relief=tk.FLAT)
        menu.add_command(label="♪  Add individual songs…",
                         command=self._pick_songs)
        menu.add_command(label="📁  Add folder of songs…",
                         command=self._pick_song_folder)
        if self._songs:
            menu.add_separator()
            menu.add_command(label="🔀  Shuffle playlist",
                             command=self._shuffle_songs)
            menu.add_command(label="✕  Clear all music",
                             command=self._clear_music)
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
        self._vol_canvas.delete("all")
        w = max(1, self._vol_canvas.winfo_width())
        h = max(1, self._vol_canvas.winfo_height())
        cy      = h // 2
        filled  = int(w * self._audio_volume)
        # Track
        self._vol_canvas.create_rectangle(0, cy - 2, w, cy + 2,
                                           fill="#333333", outline="")
        # Fill
        if filled > 0:
            self._vol_canvas.create_rectangle(0, cy - 2, filled, cy + 2,
                                               fill="#5E81F4", outline="")
        # Thumb
        self._vol_canvas.create_oval(filled - 5, cy - 5,
                                      filled + 5, cy + 5,
                                      fill="#ffffff", outline="")

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
        if not self._songs:
            self._now_playing_lbl.config(text="No music added", fg="#444444")
            return
        name = os.path.splitext(
            os.path.basename(self._songs[self._song_index % len(self._songs)]))[0]
        if len(name) > 50:
            name = name[:47] + "…"
        pos = self._song_index % len(self._songs) + 1
        self._now_playing_lbl.config(
            text=f"♪  {name}   [{pos} / {len(self._songs)}]",
            fg="#aaaaaa",
        )