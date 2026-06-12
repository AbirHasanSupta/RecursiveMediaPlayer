# splash.py (modern version with progress control)

import os
import tkinter as tk
from tkinter import ttk, font as tkfont

try:
    from version import __version__
except ImportError:
    __version__ = "dev"

_BG      = "#0F1217"
_SURFACE = "#1A1E26"
_SURF2   = "#252C38"
_ACCENT  = "#7B9CFF"
_ACCENT2 = "#FF8A8A"
_BORDER  = "#2A303C"
_TXT     = "#E2E8F0"
_MUTED   = "#8A99B5"
_DIM     = "#4A5568"

def _icon_path() -> str:
    base = getattr(__import__('sys'), '_MEIPASS', None)
    if base:
        return os.path.join(base, "icon.ico")
    # Resolve project root from src/core/splash.py (3 levels up)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "assets", "icon.ico")

class SplashController:
    """Allows the caller to update progress and close the splash."""
    def __init__(self, splash, progress_bar, status_label, on_close):
        self._splash = splash
        self._progress = progress_bar
        self._status = status_label
        self._on_close = on_close
        self._closed = False

    def set_progress(self, percent: float, text: str = None):
        """Update progress bar (0‑100) and optional status text."""
        if self._closed:
            return
        try:
            self._progress['value'] = max(0, min(100, percent))
            if text is not None:
                self._status.config(text=text)
            self._splash.update_idletasks()
        except tk.TclError:
            pass

    def close(self):
        """Destroy the splash and call the original on_done callback."""
        if self._closed:
            return
        self._closed = True
        try:
            self._splash.destroy()
        except Exception:
            pass
        if self._on_close:
            self._on_close()

def show_splash(root: tk.Tk, on_done=None) -> SplashController:
    """Create splash screen and return a controller to drive progress."""
    W, H = 560, 260

    splash = tk.Toplevel(root)
    splash.overrideredirect(True)
    splash.configure(bg=_BG, highlightthickness=1, highlightbackground=_BORDER)
    splash.attributes("-topmost", True)

    sw, sh = splash.winfo_screenwidth(), splash.winfo_screenheight()
    splash.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")

    # Main container
    main_frame = tk.Frame(splash, bg=_SURFACE, highlightbackground=_BORDER, highlightthickness=1)
    main_frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

    tk.Frame(main_frame, bg=_ACCENT, height=3).pack(fill=tk.X, side=tk.TOP)

    content = tk.Frame(main_frame, bg=_SURFACE)
    content.pack(fill=tk.BOTH, expand=True, padx=28, pady=22)

    # Top row: brand + icon
    top_row = tk.Frame(content, bg=_SURFACE)
    top_row.pack(fill=tk.X, anchor="n")

    brand_frame = tk.Frame(top_row, bg=_SURFACE)
    brand_frame.pack(side=tk.LEFT, fill=tk.Y)

    tk.Label(brand_frame, text="RECURSIVE",
             font=tkfont.Font(family="Segoe UI", size=8, weight="bold"),
             fg=_ACCENT, bg=_SURFACE).pack(anchor="w")
    tk.Label(brand_frame, text="Video Player",
             font=tkfont.Font(family="Segoe UI", size=20, weight="bold"),
             fg=_TXT, bg=_SURFACE).pack(anchor="w", pady=(6, 0))
    tk.Label(brand_frame, text="Your personal media library · fast, organised, beautiful",
             font=tkfont.Font(family="Segoe UI", size=9),
             fg=_MUTED, bg=_SURFACE).pack(anchor="w", pady=(4, 0))

    icon_frame = tk.Frame(top_row, bg=_SURFACE)
    icon_frame.pack(side=tk.RIGHT, padx=(10, 0))
    try:
        from PIL import Image, ImageTk
        img = Image.open(_icon_path()).resize((44, 44), Image.Resampling.LANCZOS)
        icon_img = ImageTk.PhotoImage(img)
        icon_label = tk.Label(icon_frame, image=icon_img, bg=_SURFACE)
        icon_label.image = icon_img
        icon_label.pack()
    except Exception:
        cv = tk.Canvas(icon_frame, width=44, height=44, bg=_SURFACE, highlightthickness=0)
        cv.pack()
        cv.create_polygon(14, 11, 34, 22, 14, 33, fill=_ACCENT, outline="")

    # Progress bar
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Splash.Horizontal.TProgressbar",
                    troughcolor=_SURF2, background=_ACCENT,
                    bordercolor=_SURF2, lightcolor=_ACCENT, darkcolor=_ACCENT, thickness=6)
    progress = ttk.Progressbar(content, style="Splash.Horizontal.TProgressbar",
                               mode="determinate", length=W-56)
    progress.pack(fill=tk.X, pady=(28, 12))

    # Footer
    footer = tk.Frame(content, bg=_SURFACE)
    footer.pack(fill=tk.X, side=tk.BOTTOM, pady=(12, 0))

    dot_canvas = tk.Canvas(footer, width=10, height=10, bg=_SURFACE, highlightthickness=0)
    dot_canvas.pack(side=tk.LEFT, padx=(0, 8))
    dot = dot_canvas.create_oval(2, 2, 8, 8, fill=_ACCENT, outline="")

    status_label = tk.Label(footer, text="Initializing…",
                            font=tkfont.Font(family="Segoe UI", size=8),
                            fg=_MUTED, bg=_SURFACE)
    status_label.pack(side=tk.LEFT)

    version_label = tk.Label(footer, text=f"{__version__}",
                             font=tkfont.Font(family="Segoe UI", size=8),
                             fg=_DIM, bg=_SURFACE)
    version_label.pack(side=tk.RIGHT)

    # Simple pulsing dot (cosmetic)
    def pulse_dot(phase=0):
        try:
            if splash.winfo_exists():
                color = _ACCENT if (phase // 8) % 2 == 0 else _SURF2
                dot_canvas.itemconfig(dot, fill=color)
                splash.after(250, lambda: pulse_dot(phase+1))
        except tk.TclError:
            pass
    pulse_dot()

    splash.update()
    return SplashController(splash, progress, status_label, on_done)