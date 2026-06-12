"""
icon_helper.py — shared helper to apply icon.ico to any Tk/Toplevel window.
Import and call apply_icon(window) from anywhere in the project.
"""
import os
import sys


def _ico_path() -> str:
    base = getattr(sys, '_MEIPASS', None)
    if base:
        return os.path.join(base, "icon.ico")
    # Resolve project root from src/utils/icon_helper.py (3 levels up)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "assets", "icon.ico")


def apply_icon(window) -> None:
    """Set icon.ico as the window icon (silently ignores errors)."""
    try:
        ico = _ico_path()
        if os.path.isfile(ico):
            window.iconbitmap(ico)
    except Exception:
        pass