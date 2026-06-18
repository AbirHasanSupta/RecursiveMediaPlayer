import tkinter as tk
from tkinter import ttk
from typing import Optional

from utils import _responsive_geometry

APP_NAV_SHORTCUTS = [
    ("App Navigation", [
        ("h",                   "Go to Home view"),
        ("Tab",                 "Cycle to next view tab"),
        ("Shift+Tab",           "Cycle to previous view tab"),
        ("Ctrl+1 … Ctrl+8",    "Switch directly to view tab by number"),
        ("Ctrl+Tab",            "Cycle UI focus forward"),
        ("Ctrl+Shift+Tab",      "Cycle UI focus backward"),
        ("Ctrl+BackSpace",      "Focus directory panel"),
    ]),
    ("Directory Panel", [
        ("Ctrl+D",              "Toggle directory panel"),
        ("Ctrl+O",              "Add directory"),
        ("Arrow Up / Down",     "Navigate directory tree"),
        ("Arrow Left / Right",  "Collapse / expand tree node"),
        ("Enter",               "Activate selected item"),
    ]),
    ("Search & Filter", [
        ("Ctrl+K",              "Focus global search bar"),
        ("Ctrl+F",              "Open Filter / Sort dialog"),
    ]),
    ("Playback", [
        ("Ctrl+P",              "Play selected video(s)"),
        ("v",                   "Show video preview"),
    ]),
    ("App Controls", [
        ("Ctrl+,",              "Open Settings"),
        ("Ctrl+T",              "Toggle dark / light theme"),
        ("Esc",                 "Close active dialog / cancel"),
        ("F10 / Shift+F10",     "Open context menu for focused item"),
        (".",                   "Open context menu for focused item"),
    ]),
]


class HelpManager:
    def __init__(self, parent, theme_provider):
        self.parent = parent
        self.theme_provider = theme_provider
        self._window: Optional[tk.Toplevel] = None

    def show_help(self):
        if self._window and self._window.winfo_exists():
            self._window.lift()
            return
        self._build_window()

    def _build_window(self):
        tp = self.theme_provider
        win = tk.Toplevel(self.parent)
        win.withdraw()
        self._window = win
        win.title("Keyboard Shortcuts")
        win.geometry(_responsive_geometry(self.parent, 580, 700))
        win.configure(bg=tp.bg_color)
        win.resizable(True, True)
        win.minsize(420, 400)
        win.transient(self.parent)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        win.bind("<Escape>", lambda e: win.destroy())

        try:
            from icon_helper import apply_icon
            apply_icon(win)
        except Exception:
            pass

        title_bar = tk.Frame(win, bg=tp.surface_color)
        title_bar.pack(fill=tk.X)
        tk.Label(
            title_bar,
            text="⌨  Keyboard Shortcuts",
            font=("Segoe UI", 13, "bold"),
            bg=tp.surface_color, fg=tp.text_color,
            padx=20, pady=14,
        ).pack(side=tk.LEFT)
        tk.Frame(win, bg=tp.border_color, height=1).pack(fill=tk.X)

        outer = tk.Frame(win, bg=tp.bg_color)
        outer.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(outer, bg=tp.bg_color, highlightthickness=0, bd=0)
        try:
            sb_style = "ExclusionTree.Vertical.TScrollbar"
            scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview, style=sb_style)
        except Exception:
            scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=tp.bg_color)
        canvas_win = canvas.create_window((0, 0), window=inner, anchor='nw', tags='inner')

        def _on_inner_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(e):
            canvas.itemconfig('inner', width=e.width)

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            try:
                if canvas.winfo_exists():
                    canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except Exception:
                pass

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        win.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        badge_bg = getattr(tp, 'badge_bg', tp.surface_color)
        badge_fg = getattr(tp, 'badge_fg', tp.text_color)
        border_color = getattr(tp, 'border_color', '#E2E8F0')

        content = tk.Frame(inner, bg=tp.bg_color, padx=20, pady=16)
        content.pack(fill=tk.X)

        for group_title, entries in APP_NAV_SHORTCUTS:
            grp_border = tk.Frame(content, bg=border_color, bd=0)
            grp_border.pack(fill=tk.X, pady=(0, 10))

            grp_header = tk.Frame(grp_border, bg=tp.surface_color)
            grp_header.pack(fill=tk.X)
            tk.Label(
                grp_header, text=group_title,
                font=("Segoe UI", 9, "bold"),
                bg=tp.surface_color, fg=tp.text_muted,
                padx=10, pady=5,
            ).pack(side=tk.LEFT)

            tk.Frame(grp_border, bg=border_color, height=1).pack(fill=tk.X)

            grp_body = tk.Frame(grp_border, bg=tp.bg_color, padx=10, pady=8)
            grp_body.pack(fill=tk.X, padx=1, pady=(0, 1))

            for key, description in entries:
                row = tk.Frame(grp_body, bg=tp.bg_color)
                row.pack(fill=tk.X, pady=3)

                key_lbl = tk.Label(
                    row, text=key,
                    font=("Segoe UI", 9),
                    bg=badge_bg, fg=badge_fg,
                    relief=tk.FLAT,
                    padx=6, pady=2,
                    highlightthickness=1,
                    highlightbackground=border_color,
                )
                key_lbl.pack(side=tk.LEFT)

                tk.Label(
                    row, text=description,
                    font=getattr(tp, 'normal_font', ("Segoe UI", 10)),
                    bg=tp.bg_color, fg=tp.text_color,
                    anchor='w',
                ).pack(side=tk.LEFT, padx=(10, 0))

        close_bar = tk.Frame(win, bg=tp.surface_color)
        close_bar.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Frame(win, bg=tp.border_color, height=1).pack(fill=tk.X, side=tk.BOTTOM)

        close_btn = tk.Button(
            close_bar, text="Close",
            font=getattr(tp, 'normal_font', ("Segoe UI", 10)),
            bg=tp.surface_color, fg=tp.text_color,
            relief=tk.FLAT, bd=0,
            padx=18, pady=8,
            cursor="hand2",
            activebackground=getattr(tp, 'hover_color', tp.surface_color),
            activeforeground=tp.text_color,
            command=win.destroy,
        )
        close_btn.pack(side=tk.RIGHT, padx=12, pady=8)

        win.grab_set()
        win.deiconify()

    def apply_theme(self):
        if self._window and self._window.winfo_exists():
            self._window.destroy()
            self._window = None