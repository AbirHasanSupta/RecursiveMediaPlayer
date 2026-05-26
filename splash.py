"""
splash.py — Startup splash screen for Recursive Video Player.
Call show_splash() before building the main UI; it destroys itself
after `duration_ms` milliseconds and then calls `on_done()`.
"""

import os
import tkinter as tk
from tkinter import font as tkfont
from pathlib import Path


def _icon_path() -> str:
    base = getattr(__import__('sys'), '_MEIPASS', None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "icon.ico")


def show_splash(root: tk.Tk, on_done, duration_ms: int = 1000):
    SPLASH_W, SPLASH_H = 480, 280
    BG       = "#0d0f12"
    ACCENT   = "#e50914"
    TXT      = "#f0f0f0"
    TXT_DIM  = "#888888"

    splash = tk.Toplevel(root)
    splash.overrideredirect(True)
    splash.configure(bg=BG)
    splash.attributes("-topmost", True)

    sw = splash.winfo_screenwidth()
    sh = splash.winfo_screenheight()
    x  = (sw - SPLASH_W) // 2
    y  = (sh - SPLASH_H) // 2
    splash.geometry(f"{SPLASH_W}x{SPLASH_H}+{x}+{y}")

    ico = _icon_path()

    img_label = None
    try:
        from PIL import Image, ImageTk
        img = Image.open(ico)
        img = img.resize((96, 96), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        img_label = tk.Label(splash, image=photo, bg=BG)
        img_label.image = photo
        img_label.pack(pady=(36, 8))
    except Exception:
        tk.Label(splash, text="▶", font=("Segoe UI", 52),
                 bg=BG, fg=ACCENT).pack(pady=(30, 4))

    tk.Label(splash,
             text="Recursive Video Player",
             font=("Segoe UI", 18, "bold"),
             bg=BG, fg=TXT).pack(pady=(0, 4))

    bar = tk.Frame(splash, bg=ACCENT, height=4)
    bar.pack(side=tk.BOTTOM, fill=tk.X)

    splash.configure(highlightthickness=1, highlightbackground="#333333")

    def _finish():
        try:
            splash.destroy()
        except Exception:
            pass
        on_done()

    splash.after(duration_ms, _finish)
    splash.update()
    status_lbl = tk.Label(splash, text="Loading…", font=("Segoe UI", 10), bg=BG, fg=TXT_DIM)
    status_lbl.pack()
    return status_lbl