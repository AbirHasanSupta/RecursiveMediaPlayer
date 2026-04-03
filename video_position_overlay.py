import os
import ctypes
import ctypes.wintypes
import threading
import tkinter as tk
from tkinter.font import Font


def _fmt_time(ms: int) -> str:
    s = max(0, int(ms / 1000))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


# ── Win32 helpers ─────────────────────────────────────────────────────────────

def _get_vlc_hwnd():
    """Return the HWND of the running VLC window, or None."""
    user32 = ctypes.windll.user32
    found = []

    def _cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if "vlc" in buf.value.lower():
                    found.append(hwnd)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                     ctypes.POINTER(ctypes.c_int),
                                     ctypes.POINTER(ctypes.c_int))
    user32.EnumWindows(WNDENUMPROC(_cb), ctypes.pointer(ctypes.c_int(0)))
    return found[0] if found else None


def _window_rect(hwnd):
    """Return (x, y, w, h) for the given HWND, or None."""
    try:
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    except Exception:
        return None


def _cursor_pos():
    """Return (x, y) absolute mouse position."""
    pt = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


# ── Overlay ───────────────────────────────────────────────────────────────────

OVERLAY_H   = 120   # height of the floating panel in pixels
OVERLAY_W   = 680   # fixed width
PANEL_BG    = "#1c1c1c"
ACCENT      = "#E50914"
TEXT_DIM    = "#888888"
TEXT_BRIGHT = "#dddddd"
BTN_BG      = "#2e2e2e"
BTN_HOVER   = "#555555"


class VideoPositionOverlay:
    """
    A hover-triggered floating control panel for the main VLC player.

    Behaviour
    ---------
    * Invisible by default.
    * While the mouse is anywhere inside the VLC window, the panel slides in
      at the bottom of that window (mouse-position polled every 120 ms so it
      works even when VLC owns the HWND).
    * Fades out 500 ms after the cursor leaves the VLC window.
    * Fully interactive — seek bar, play/pause, prev/next, volume, speed.
    """

    def __init__(self, controller, logger=None):
        self.controller   = controller
        self.logger       = logger

        # state
        self._vlc_hwnd        = None
        self._visible         = False
        self._hide_job        = None
        self._poll_job        = None
        self._update_job      = None
        self._is_dragging     = False
        self._is_hovering_bar = False
        # When True the user explicitly toggled the overlay OFF — suppress
        # the mouse-poll auto-show until the user toggles it ON again.
        self._user_hidden     = False

        # tk widgets (created lazily on first show)
        self.overlay_window   = None
        self._seek_canvas     = None
        self._play_btn        = None
        self._vol_label       = None
        self._vol_value       = None
        self._spd_label       = None
        self._title_label     = None
        self._time_label      = None

        # public compat shim (old code checks is_visible)
        self.is_visible = False

    # ── public API (matches old VideoPositionOverlay) ─────────────────────────

    def create_overlay(self):
        """Build the Toplevel window (hidden).  Safe to call multiple times."""
        if self.overlay_window and self.overlay_window.winfo_exists():
            return
        self._build_window()

    def _run_on_main(self, fn):
        """Schedule fn() on the Tk main thread. Safe to call from any thread."""
        try:
            if self.overlay_window and self.overlay_window.winfo_exists():
                self.overlay_window.after(0, fn)
            else:
                # window not built yet — use the controller's root if available
                root = getattr(self.controller, '_tk_root', None)
                if root:
                    root.after(0, fn)
                else:
                    fn()   # last resort: call directly (should rarely happen)
        except Exception:
            pass

    def show(self):
        self._run_on_main(self._show_main)

    def _show_main(self):
        if not self.overlay_window or not self.overlay_window.winfo_exists():
            self._build_window()
        self._do_show()
        self._start_poll()
        self._schedule_update()

    def hide(self):
        self._run_on_main(self._hide_main)

    def _hide_main(self):
        self._do_hide()

    def toggle(self):
        self._run_on_main(self._toggle_main)

    def _toggle_main(self):
        if self._visible:
            # User is explicitly hiding — suppress the poll's auto-show.
            self._user_hidden = True
            self._do_hide()
            self._cancel_poll()        # stop auto-show loop while hidden
            self._cancel_update()
        else:
            # User is explicitly showing — re-enable auto-show.
            self._user_hidden = False
            if not self.overlay_window or not self.overlay_window.winfo_exists():
                self._build_window()
            self._do_show()
            self._start_poll()
            self._schedule_update()

    def cleanup(self):
        self._visible   = False
        self.is_visible = False
        self._cancel_poll()
        self._cancel_update()
        if self._hide_job and self.overlay_window:
            try:
                self.overlay_window.after_cancel(self._hide_job)
            except Exception:
                pass
        self._hide_job = None
        if self.overlay_window:
            try:
                self.overlay_window.destroy()
            except Exception:
                pass
            self.overlay_window = None

    # keep old names working
    def init_overlay(self):
        """Called from controller — may be on a background thread."""
        # Store a tk root reference on the controller so _run_on_main works
        # even before the Toplevel is created.
        try:
            import tkinter as tk
            if not getattr(self.controller, '_tk_root', None):
                self.controller._tk_root = tk._default_root
        except Exception:
            pass
        self._run_on_main(self.create_overlay)

    # ── window construction ───────────────────────────────────────────────────

    def _build_window(self):
        self.overlay_window = tk.Toplevel()
        self.overlay_window.overrideredirect(True)      # no title bar
        self.overlay_window.attributes("-topmost", True)
        self.overlay_window.attributes("-alpha", 0.92)
        self.overlay_window.configure(bg=PANEL_BG)
        self.overlay_window.withdraw()                  # hidden until hover

        root = self.overlay_window

        # ── title row ────────────────────────────────────────────────────────
        title_row = tk.Frame(root, bg=PANEL_BG)
        title_row.pack(fill=tk.X, padx=12, pady=(8, 2))

        self._title_label = tk.Label(
            title_row, text="", anchor="w",
            font=Font(family="Segoe UI", size=9),
            bg=PANEL_BG, fg=TEXT_BRIGHT)
        self._title_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._time_label = tk.Label(
            title_row, text="0:00 / 0:00",
            font=Font(family="Segoe UI", size=8),
            bg=PANEL_BG, fg=TEXT_DIM)
        self._time_label.pack(side=tk.RIGHT)

        # ── seek bar ─────────────────────────────────────────────────────────
        seek_row = tk.Frame(root, bg=PANEL_BG)
        seek_row.pack(fill=tk.X, padx=12, pady=(2, 4))

        self._seek_canvas = tk.Canvas(
            seek_row, height=16, bg=PANEL_BG,
            highlightthickness=0, cursor="hand2")
        self._seek_canvas.pack(fill=tk.X, expand=True)
        self._seek_canvas.bind("<Button-1>",        self._on_seek_click)
        self._seek_canvas.bind("<B1-Motion>",       self._on_seek_drag)
        self._seek_canvas.bind("<ButtonRelease-1>", self._on_seek_release)
        self._seek_canvas.bind("<Enter>",           lambda e: self._set_hover(True))
        self._seek_canvas.bind("<Leave>",           lambda e: self._set_hover(False))
        self._seek_canvas.bind("<Configure>",       lambda e: self._draw_seek())

        # ── control row ───────────────────────────────────────────────────────
        ctrl = tk.Frame(root, bg=PANEL_BG)
        ctrl.pack(fill=tk.X, padx=12, pady=(0, 8))

        btn_kw = dict(
            bg=BTN_BG, fg="white", bd=0, padx=8, pady=3,
            relief=tk.FLAT, cursor="hand2",
            activebackground=BTN_HOVER, activeforeground="white",
            font=Font(family="Segoe UI", size=11))

        tk.Button(ctrl, text="⏮", command=self.previous_video, **btn_kw).pack(side=tk.LEFT, padx=2)
        self._play_btn = tk.Button(ctrl, text="⏸", command=self.toggle_pause, **btn_kw)
        self._play_btn.pack(side=tk.LEFT, padx=2)
        tk.Button(ctrl, text="⏭", command=self.next_video, **btn_kw).pack(side=tk.LEFT, padx=2)

        # volume
        tk.Frame(ctrl, width=16, bg=PANEL_BG).pack(side=tk.LEFT)
        self._vol_label = tk.Label(
            ctrl, text="🔊", cursor="hand2",
            font=Font(family="Segoe UI", size=11),
            bg=PANEL_BG, fg=TEXT_BRIGHT)
        self._vol_label.pack(side=tk.LEFT, padx=(0, 2))
        self._vol_label.bind("<Button-1>",   lambda e: self._vol_click())
        self._vol_label.bind("<MouseWheel>", self._on_vol_scroll)

        self._vol_value = tk.Label(
            ctrl, text="50%", width=4,
            font=Font(family="Segoe UI", size=8),
            bg=PANEL_BG, fg=TEXT_DIM)
        self._vol_value.pack(side=tk.LEFT)

        # speed (right-aligned)
        self._spd_label = tk.Label(
            ctrl, text="1.00×", cursor="hand2",
            font=Font(family="Segoe UI", size=8, weight="bold"),
            bg=PANEL_BG, fg=ACCENT)
        self._spd_label.pack(side=tk.RIGHT, padx=(4, 0))
        self._spd_label.bind("<Button-1>",        lambda e: self.increase_speed())
        self._spd_label.bind("<Button-3>",        lambda e: self.decrease_speed())
        self._spd_label.bind("<Double-Button-1>", lambda e: self.reset_speed())
        self._spd_label.bind("<MouseWheel>",      self._on_spd_scroll)

        tk.Label(ctrl, text="Spd:", font=Font(family="Segoe UI", size=8),
                 bg=PANEL_BG, fg=TEXT_DIM).pack(side=tk.RIGHT)

        # keep overlay shown while mouse is over it
        for w in [root, title_row, seek_row, ctrl,
                  self._title_label, self._time_label,
                  self._seek_canvas, self._play_btn,
                  self._vol_label, self._vol_value, self._spd_label]:
            w.bind("<Enter>", lambda e: self._cancel_hide(), add="+")
            w.bind("<Leave>", lambda e: self._schedule_hide(), add="+")

    # ── show / hide ───────────────────────────────────────────────────────────

    def _do_show(self):
        if not self.overlay_window or not self.overlay_window.winfo_exists():
            return
        self._cancel_hide()
        self._user_hidden = False  # explicit show always clears the suppression flag
        if not self._visible:
            self._visible   = True
            self.is_visible = True
            self._position_panel()
            self.overlay_window.deiconify()
            self.overlay_window.lift()

    def _do_hide(self):
        self._hide_job = None
        self._visible   = False
        self.is_visible = False
        if self.overlay_window and self.overlay_window.winfo_exists():
            self.overlay_window.withdraw()

    def _schedule_hide(self):
        if self._hide_job or not self.overlay_window:
            return
        self._hide_job = self.overlay_window.after(500, self._do_hide)

    def _cancel_hide(self):
        if self._hide_job and self.overlay_window:
            try:
                self.overlay_window.after_cancel(self._hide_job)
            except Exception:
                pass
        self._hide_job = None

    # ── position panel at bottom of VLC window ────────────────────────────────

    def _position_panel(self):
        if not self.overlay_window:
            return
        hwnd = self._get_or_find_hwnd()
        if hwnd:
            r = _window_rect(hwnd)
            if r:
                wx, wy, ww, wh = r
                x = wx + (ww - OVERLAY_W) // 2
                y = wy + wh - OVERLAY_H - 10
                self.overlay_window.geometry(f"{OVERLAY_W}x{OVERLAY_H}+{x}+{y}")
                return
        # fallback: top-left corner
        self.overlay_window.geometry(f"{OVERLAY_W}x{OVERLAY_H}+20+20")

    def _get_or_find_hwnd(self):
        if self._vlc_hwnd:
            try:
                if ctypes.windll.user32.IsWindowVisible(self._vlc_hwnd):
                    return self._vlc_hwnd
            except Exception:
                pass
        self._vlc_hwnd = _get_vlc_hwnd()
        return self._vlc_hwnd

    # ── mouse-position polling (works even when VLC owns HWND) ───────────────

    def _start_poll(self):
        self._cancel_poll()
        self._poll()

    def _cancel_poll(self):
        if self._poll_job and self.overlay_window:
            try:
                self.overlay_window.after_cancel(self._poll_job)
            except Exception:
                pass
        self._poll_job = None

    def _poll(self):
        if not self.overlay_window or not self.overlay_window.winfo_exists():
            return
        try:
            hwnd = self._get_or_find_hwnd()
            if hwnd:
                r = _window_rect(hwnd)
                if r:
                    wx, wy, ww, wh = r
                    mx, my = _cursor_pos()
                    inside_vlc = (wx <= mx <= wx + ww) and (wy <= my <= wy + wh)
                    if inside_vlc:
                        # Only auto-show when the user hasn't explicitly hidden it via toggle.
                        if not self._user_hidden:
                            self._do_show()
                        # keep panel bottom-aligned as VLC window moves/resizes
                        if self._visible:
                            self._position_panel()
                    else:
                        if self._visible and not self._hide_job:
                            self._schedule_hide()
            else:
                # VLC window gone
                if self._visible:
                    self._do_hide()
        except Exception:
            pass
        self._poll_job = self.overlay_window.after(120, self._poll)

    # ── periodic display update ───────────────────────────────────────────────

    def _schedule_update(self):
        self._cancel_update()
        if self.overlay_window and self.overlay_window.winfo_exists():
            self._update_job = self.overlay_window.after(500, self._update_tick)

    def _cancel_update(self):
        if self._update_job and self.overlay_window:
            try:
                self.overlay_window.after_cancel(self._update_job)
            except Exception:
                pass
        self._update_job = None

    def _update_tick(self):
        if not self.overlay_window or not self.overlay_window.winfo_exists():
            return
        if not self._is_player_active():
            self._do_hide()
            return
        if self._visible and not self._is_dragging:
            self.update_display()
        self._update_job = self.overlay_window.after(500, self._update_tick)

    def _is_player_active(self):
        try:
            return (self.controller and
                    getattr(self.controller, 'running', False) and
                    getattr(self.controller, 'player', None) is not None)
        except Exception:
            return False

    # ── seek bar drawing ──────────────────────────────────────────────────────

    def _draw_seek(self):
        if not self._seek_canvas:
            return
        try:
            c = self._seek_canvas
            c.delete("all")
            w = c.winfo_width()
            h = c.winfo_height()
            if w <= 1:
                return
            cy = h // 2
            # track
            c.create_rectangle(0, cy - 2, w, cy + 2, fill="#404040", outline="")
            cur, dur = 0, 1
            if self.controller and self.controller.player:
                cur = max(0, self.controller.player.get_time()   or 0)
                dur = max(1, self.controller.player.get_length() or 1)
            px = int((cur / dur) * w)
            # progress
            c.create_rectangle(0, cy - 2, px, cy + 2, fill=ACCENT, outline="")
            # handle
            r = 6 if self._is_hovering_bar else 4
            c.create_oval(px - r, cy - r, px + r, cy + r, fill="white", outline="")
        except Exception:
            pass

    def _set_hover(self, val: bool):
        self._is_hovering_bar = val
        self._draw_seek()

    def _seek_from_x(self, x: int):
        try:
            w = self._seek_canvas.winfo_width()
            if w <= 1 or not self.controller or not self.controller.player:
                return
            frac = max(0.0, min(1.0, x / w))
            self.controller.player.set_time(
                int(frac * (self.controller.player.get_length() or 0)))
            self._draw_seek()
        except Exception:
            pass

    def _on_seek_click(self, e):
        self._is_dragging = True
        self._seek_from_x(e.x)

    def _on_seek_drag(self, e):
        if self._is_dragging:
            self._seek_from_x(e.x)

    def _on_seek_release(self, e):
        self._is_dragging = False

    # ── display update ────────────────────────────────────────────────────────

    def update_display(self):
        if not self.overlay_window or not self.overlay_window.winfo_exists():
            return
        try:
            c = self.controller
            if not c:
                return

            # title
            if c.index < len(c.videos):
                name = os.path.basename(c.videos[c.index])
                if len(name) > 60:
                    name = name[:57] + "..."
                self._title_label.config(text=name)

            # play/pause icon
            try:
                playing = c.player.is_playing()
                self._play_btn.config(text="⏸" if playing else "▶")
            except Exception:
                pass

            # time
            try:
                cur = c.player.get_time()  or 0
                dur = c.player.get_length() or 0
                self._time_label.config(text=f"{_fmt_time(cur)} / {_fmt_time(dur)}")
            except Exception:
                pass

            # volume icon
            vol    = getattr(c, 'volume', 50)
            muted  = getattr(c, 'is_muted', False)
            if muted or vol == 0:
                icon = "🔇"
            elif vol < 30:
                icon = "🔈"
            elif vol < 70:
                icon = "🔉"
            else:
                icon = "🔊"
            self._vol_label.config(text=icon)
            self._vol_value.config(text=f"{vol}%")

            # speed
            try:
                spd = c.player.get_rate()
                self._spd_label.config(text=f"{spd:.2f}×")
            except Exception:
                pass

            self._draw_seek()

        except Exception as e:
            if self.logger:
                self.logger(f"Overlay update error: {e}")

    # ── controls ──────────────────────────────────────────────────────────────

    def toggle_pause(self):
        if self.controller:
            self.controller.toggle_pause()
            self.update_display()

    def previous_video(self):
        if self.controller:
            try:
                self.controller.previous_video()
            except AttributeError:
                self.controller.prev_video()
            self.update_display()

    def next_video(self):
        if self.controller:
            self.controller.next_video()
            self.update_display()

    def volume_up(self):
        if self.controller:
            self.controller.volume_up()
            self.update_display()

    def volume_down(self):
        if self.controller:
            self.controller.volume_down()
            self.update_display()

    def increase_speed(self):
        if self.controller:
            self.controller.increase_speed()
            self.update_display()

    def decrease_speed(self):
        if self.controller:
            self.controller.decrease_speed()
            self.update_display()

    def reset_speed(self):
        if self.controller:
            self.controller.set_playback_rate(1.0)
            self.update_display()

    def _vol_click(self):
        """Left-click volume icon = toggle mute."""
        if self.controller:
            self.controller.toggle_mute()
            self.update_display()

    def _on_vol_scroll(self, e):
        if e.delta > 0:
            self.volume_up()
        else:
            self.volume_down()

    def _on_spd_scroll(self, e):
        if e.delta > 0:
            self.increase_speed()
        else:
            self.decrease_speed()

    # ── legacy compat stubs (called by vlc_player_controller.py) ─────────────

    def position_window(self):
        self._position_panel()

    def start_updates(self):
        self._schedule_update()

    def stop_updates(self):
        self._cancel_update()

    def start_position_tracking(self):
        self._start_poll()

    def stop_position_tracking(self):
        self._cancel_poll()