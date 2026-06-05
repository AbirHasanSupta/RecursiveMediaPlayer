from __future__ import annotations

import re
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from managers.ai_search_manager import AISearchManager

_RE_PROGRESS = re.compile(r'(\d+)\s*/\s*(\d+)')
_RE_FILENAME = re.compile(r'[Pp]rocessing[:\s]+(.+\.(?:mp4|mkv|avi|mov|wmv|flv|webm|m4v|ts|mts|m2ts))',
                          re.IGNORECASE)


class _ModernProgressBar:
    _H = 12

    def __init__(self, parent, track_bg, accent, success="#34c98a"):
        self._track_bg = track_bg
        self._accent = accent
        self._success = success
        self._value = 0.0
        self._maximum = 100.0
        self._mode = "determinate"
        self._anim_id = None
        self._anim_pos = 0.0

        self._canvas = tk.Canvas(
            parent, height=self._H, bg=track_bg,
            highlightthickness=0, bd=0,
        )
        self._canvas.bind("<Configure>", lambda _e: self._redraw())

    def pack(self, **kw):
        self._canvas.pack(**kw)

    def configure(self, **kw):
        kw.pop("length", None)
        changed = False
        if "mode" in kw:
            self._mode = kw.pop("mode")
            changed = True
        if "maximum" in kw:
            self._maximum = float(kw.pop("maximum"))
            changed = True
        if "value" in kw:
            self._value = float(kw.pop("value"))
            changed = True
        if kw:
            self._canvas.configure(**kw)
        if changed:
            self._redraw()

    config = configure

    def start(self, ms=15):
        self._stop_anim()
        self._mode = "indeterminate"
        self._anim_pos = 0.0
        self._tick(ms)

    def stop(self):
        self._stop_anim()

    def _stop_anim(self):
        if self._anim_id is not None:
            try:
                self._canvas.after_cancel(self._anim_id)
            except Exception:
                pass
            self._anim_id = None

    def _tick(self, ms):
        self._anim_pos = (self._anim_pos + 0.025) % 1.0
        self._redraw()
        self._anim_id = self._canvas.after(ms, lambda: self._tick(ms))

    def _redraw(self):
        c = self._canvas
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 4:
            return
        c.delete("all")
        c.create_rectangle(0, 0, w, h, fill=self._track_bg, outline="")
        if self._mode == "indeterminate":
            streak = max(60, int(w * 0.30))
            x0 = int(self._anim_pos * (w + streak)) - streak
            x1 = min(w, x0 + streak)
            x0 = max(0, x0)
            if x1 > x0:
                c.create_rectangle(x0, 2, x1, h - 2, fill=self._accent, outline="")
        else:
            ratio = min(self._value / max(self._maximum, 1.0), 1.0)
            fw = int(w * ratio)
            if fw > 0:
                color = self._success if ratio >= 1.0 else self._accent
                c.create_rectangle(0, 2, fw, h - 2, fill=color, outline="")


class IndexingDialog:
    def __init__(self, root: tk.Misc, app, manager: "AISearchManager"):
        self._root = root
        self._app = app
        self._manager = manager
        self._win: Optional[tk.Toplevel] = None
        self._running = False
        self._cancelled = False

        self._dir_var: Optional[tk.StringVar] = None
        self._workers_var: Optional[tk.IntVar] = None
        self._frames_var: Optional[tk.IntVar] = None
        self._incremental_var: Optional[tk.BooleanVar] = None
        self._gpu_var: Optional[tk.BooleanVar] = None

        self._progress_bar: Optional[ttk.Progressbar] = None
        self._progress_lbl: Optional[tk.Label] = None
        self._file_lbl: Optional[tk.Label] = None
        self._log_text: Optional[tk.Text] = None
        self._start_btn: Optional[tk.Label] = None
        self._cancel_btn: Optional[tk.Label] = None
        self._close_btn: Optional[tk.Label] = None

    def show(self):
        if self._win and self._win.winfo_exists():
            self._win.lift()
            return

        tp = self._app
        bg = getattr(tp, "bg_color", "#F7F9FC")
        surface = getattr(tp, "surface_color", "#FFFFFF")
        accent = getattr(tp, "accent_color", "#5E81F4")
        accent2 = getattr(tp, "accent_secondary", "#FF6B6B")
        text = getattr(tp, "text_color", "#1E2A3A")
        muted = getattr(tp, "text_muted", "#5B6C8F")
        border = getattr(tp, "border_color", "#E2E8F0")
        fn = getattr(tp, "normal_font", ("Segoe UI", 10))
        fs = getattr(tp, "small_font", ("Segoe UI", 9))

        try:
            settings = self._app.settings_manager.settings
        except Exception:
            from managers.settings_manager import SettingsData
            settings = SettingsData()

        initial_dir = ""
        try:
            dirs = getattr(self._app, "selected_dirs", [])
            if dirs:
                initial_dir = dirs[0]
        except Exception:
            pass

        self._win = tk.Toplevel(self._root)
        self._win.withdraw()
        self._win.title("Index Videos for AI Search")
        self._win.configure(bg=bg)
        self._win.resizable(False, False)
        self._win.transient(self._root)
        self._win.grab_set()
        self._win.protocol("WM_DELETE_WINDOW", self._on_close)

        try:
            from icon_helper import apply_icon
            apply_icon(self._win)
        except Exception:
            pass

        outer = tk.Frame(self._win, bg=bg, padx=24, pady=20)
        outer.pack(fill=tk.BOTH, expand=True)

        tk.Label(outer, text="Index Videos for AI Search",
                 font=("Segoe UI", 13, "bold"), bg=bg, fg=text).pack(anchor="w", pady=(0, 4))
        tk.Label(outer,
                 text="Build or update the semantic search index for a video directory.",
                 font=fs, bg=bg, fg=muted).pack(anchor="w", pady=(0, 16))

        tk.Frame(outer, bg=border, height=1).pack(fill=tk.X, pady=(0, 16))

        def _section_lbl(t):
            tk.Label(outer, text=t, font=("Segoe UI", 9, "bold"),
                     bg=bg, fg=muted).pack(anchor="w", pady=(0, 4))

        _section_lbl("DIRECTORY TO INDEX")
        dir_row = tk.Frame(outer, bg=bg)
        dir_row.pack(fill=tk.X, pady=(0, 14))

        self._dir_var = tk.StringVar(value=initial_dir)
        dir_wrap = tk.Frame(dir_row, bg=surface,
                            highlightbackground=border, highlightthickness=1)
        dir_wrap.pack(side=tk.LEFT, fill=tk.X, expand=True)
        dir_entry = tk.Entry(dir_wrap, textvariable=self._dir_var,
                             bg=surface, fg=text, relief="flat", bd=0,
                             font=fn, insertbackground=accent)
        dir_entry.pack(fill=tk.X, ipady=6, padx=8)

        browse_lbl = tk.Label(dir_row, text="Browse",
                              bg=surface, fg=accent,
                              font=("Segoe UI", 9),
                              padx=12, pady=6, cursor="hand2",
                              highlightbackground=border, highlightthickness=1)
        browse_lbl.pack(side=tk.LEFT, padx=(6, 0))
        browse_lbl.bind("<Button-1>", lambda _e: self._browse_dir())
        browse_lbl.bind("<Enter>", lambda _e: browse_lbl.config(
            bg=accent, fg="#ffffff", highlightbackground=accent))
        browse_lbl.bind("<Leave>", lambda _e: browse_lbl.config(
            bg=surface, fg=accent, highlightbackground=border))

        _section_lbl("PREPROCESSING SETTINGS")
        grid = tk.Frame(outer, bg=bg)
        grid.pack(fill=tk.X, pady=(0, 6))
        grid.columnconfigure(1, weight=1)
        grid.columnconfigure(3, weight=1)

        def _spin_row(parent, row, label, var, from_, to, hint):
            tk.Label(parent, text=label, font=fn, bg=bg, fg=text,
                     anchor="w").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 8))
            spin = tk.Spinbox(parent, from_=from_, to=to, textvariable=var,
                              font=fn, width=6,
                              bg=getattr(tp, "entry_bg", surface),
                              fg=getattr(tp, "entry_fg", text),
                              buttonbackground=bg, relief=tk.FLAT, bd=1)
            spin.grid(row=row, column=1, sticky="w", pady=4, padx=(0, 12))
            tk.Label(parent, text=hint, font=fs, bg=bg, fg=muted).grid(
                row=row, column=2, sticky="w", pady=4)

        self._workers_var = tk.IntVar(value=settings.preprocessing_workers)
        self._frames_var = tk.IntVar(value=settings.max_frames_per_video)
        _spin_row(grid, 0, "Workers:", self._workers_var, 1, 8, "1–8 (recommend 2–4)")
        _spin_row(grid, 1, "Max Frames per Video:", self._frames_var, 10, 200, "10–200 (higher = more accurate)")

        checks = tk.Frame(outer, bg=bg)
        checks.pack(fill=tk.X, pady=(2, 14))
        self._incremental_var = tk.BooleanVar(value=settings.incremental_preprocessing)
        self._gpu_var = tk.BooleanVar(value=settings.enable_gpu_acceleration)
        ttk.Checkbutton(checks, text="Incremental mode  (add new videos only, skip already-indexed)",
                        variable=self._incremental_var,
                        style="Modern.TCheckbutton").pack(anchor="w", pady=1)
        ttk.Checkbutton(checks, text="GPU acceleration  (requires CUDA-capable GPU)",
                        variable=self._gpu_var,
                        style="Modern.TCheckbutton").pack(anchor="w", pady=1)

        tk.Frame(outer, bg=border, height=1).pack(fill=tk.X, pady=(0, 14))

        _section_lbl("PROGRESS")

        prog_card = tk.Frame(outer, bg=surface,
                             highlightbackground=border, highlightthickness=1)
        prog_card.pack(fill=tk.X, pady=(0, 4))
        prog_inner = tk.Frame(prog_card, bg=surface)
        prog_inner.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)

        self._progress_lbl = tk.Label(prog_inner, text="Ready to start",
                                      font=fs, bg=surface, fg=muted, anchor="w")
        self._progress_lbl.pack(fill=tk.X, pady=(0, 8))

        dark = getattr(tp, 'dark_mode', False)
        track_bg = getattr(tp, 'border_color', "#2A303C" if dark else "#E2E8F0")
        self._progress_bar = _ModernProgressBar(prog_inner, track_bg, accent)
        self._progress_bar.pack(fill=tk.X)

        self._file_lbl = tk.Label(prog_inner, text="",
                                  font=fs, bg=surface, fg=muted, anchor="w",
                                  wraplength=460, justify=tk.LEFT)
        self._file_lbl.pack(fill=tk.X, pady=(7, 0))

        log_frame = tk.Frame(outer, bg=surface,
                             highlightbackground=border, highlightthickness=1)
        log_frame.pack(fill=tk.X, pady=(12, 16))
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL,
                                   style="ExclusionTree.Vertical.TScrollbar")
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 1), pady=1)
        self._log_text = tk.Text(
            log_frame, height=10,
            bg=getattr(tp, "console_bg", "#1E2A3A"),
            fg=getattr(tp, "console_fg", "#F7F9FC"),
            font=("Consolas", 8),
            relief=tk.FLAT, bd=0,
            yscrollcommand=log_scroll.set,
            state=tk.DISABLED,
            wrap=tk.WORD,
        )
        self._log_text.pack(fill=tk.X, padx=1, pady=1)
        log_scroll.config(command=self._log_text.yview)

        tk.Frame(outer, bg=border, height=1).pack(fill=tk.X, pady=(0, 14))

        btn_row = tk.Frame(outer, bg=bg)
        btn_row.pack(fill=tk.X)

        self._close_btn = tk.Label(btn_row, text="Close",
                                   bg=surface, fg=muted,
                                   font=("Segoe UI", 10),
                                   padx=16, pady=7, cursor="hand2",
                                   highlightbackground=border, highlightthickness=1)
        self._close_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self._close_btn.bind("<Button-1>", lambda _e: self._on_close())
        self._close_btn.bind("<Enter>", lambda _e: self._close_btn.config(
            highlightbackground=muted))
        self._close_btn.bind("<Leave>", lambda _e: self._close_btn.config(
            highlightbackground=border))

        self._cancel_btn = tk.Label(btn_row, text="Cancel Indexing",
                                    bg=getattr(tp, "accent_secondary", "#FF6B6B"),
                                    fg="#ffffff",
                                    font=("Segoe UI", 10, "bold"),
                                    padx=16, pady=7, cursor="hand2")
        self._cancel_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self._cancel_btn.bind("<Button-1>", lambda _e: self._cancel_indexing())
        self._cancel_btn.pack_forget()

        self._start_btn = tk.Label(btn_row, text="▶  Start Indexing",
                                   bg=accent, fg="#ffffff",
                                   font=("Segoe UI", 10, "bold"),
                                   padx=16, pady=7, cursor="hand2")
        self._start_btn.pack(side=tk.RIGHT)
        self._start_btn.bind("<Button-1>", lambda _e: self._start_indexing())
        self._start_btn.bind("<Enter>", lambda _e: self._start_btn.config(bg=accent2))
        self._start_btn.bind("<Leave>", lambda _e: self._start_btn.config(bg=accent))

        self._win.update_idletasks()
        w, h = 540, self._win.winfo_reqheight() + 10
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self._win.geometry(f"{w}x{h}+{x}+{y}")
        self._win.deiconify()
        self._win.lift()

    def _browse_dir(self):
        current = self._dir_var.get()
        initial = current if os.path.isdir(current) else os.path.expanduser("~")
        chosen = filedialog.askdirectory(
            title="Select Directory to Index",
            initialdir=initial,
            parent=self._win,
        )
        if chosen:
            self._dir_var.set(chosen)

    def _start_indexing(self):
        videos_dir = self._dir_var.get().strip()
        if not videos_dir:
            self._set_progress_text("⚠  Please select a directory first", error=True)
            return
        if not os.path.isdir(videos_dir):
            self._set_progress_text("⚠  Directory does not exist", error=True)
            return
        if self._running:
            return

        self._running = True
        self._cancelled = False

        self._start_btn.pack_forget()
        self._cancel_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self._close_btn.config(state=tk.DISABLED, cursor="")

        self._progress_bar.config(value=0, maximum=100, mode="indeterminate")
        self._progress_bar.start(12)
        self._set_progress_text("⏳  Starting preprocessing…")
        self._log_append(f"Directory: {videos_dir}\n")
        self._log_append(f"Workers: {self._workers_var.get()}  "
                         f"Max frames: {self._frames_var.get()}  "
                         f"Incremental: {self._incremental_var.get()}  "
                         f"GPU: {self._gpu_var.get()}\n")
        self._log_append("─" * 50 + "\n")

        try:
            settings = self._app.settings_manager.settings
        except Exception:
            from managers.settings_manager import SettingsData
            settings = SettingsData()

        settings.preprocessing_workers = self._workers_var.get()
        settings.max_frames_per_video = self._frames_var.get()
        settings.incremental_preprocessing = self._incremental_var.get()
        settings.enable_gpu_acceleration = self._gpu_var.get()

        self._manager._preprocessor.start_preprocessing(
            videos_dir=videos_dir,
            settings=settings,
            progress_cb=self._on_progress,
            done_cb=self._on_done,
        )

    def _cancel_indexing(self):
        if not self._running:
            return
        self._cancelled = True
        self._manager._preprocessor.cancel()
        self._set_progress_text("Cancelling…")

    def _on_progress(self, line: str):
        self._root.after(0, lambda l=line: self._handle_progress_line(l))

    def _handle_progress_line(self, line: str):
        if not self._win or not self._win.winfo_exists():
            return

        self._log_append(line + "\n")

        m = _RE_PROGRESS.search(line)
        if m:
            current = int(m.group(1))
            total = int(m.group(2))
            if total > 0:
                pct = int(100 * current / total)
                try:
                    self._progress_bar.stop()
                    self._progress_bar.config(mode="determinate", maximum=total, value=current)
                except Exception:
                    pass
                self._set_progress_text(
                    f"Indexing…  {current} / {total} videos  ({pct}%)"
                )

        mf = _RE_FILENAME.search(line)
        if mf:
            fname = os.path.basename(mf.group(1).strip())
            try:
                self._file_lbl.config(text=f"Current: {fname}")
            except Exception:
                pass

    def _on_done(self, success: bool, error: str = None):
        self._root.after(0, lambda: self._finish(success, error))

    def _finish(self, success: bool, error: str):
        self._running = False
        if not self._win or not self._win.winfo_exists():
            return

        try:
            self._progress_bar.stop()
        except Exception:
            pass

        self._cancel_btn.pack_forget()
        self._start_btn.pack(side=tk.RIGHT)
        try:
            self._close_btn.config(state=tk.NORMAL, cursor="hand2")
        except Exception:
            pass

        if self._cancelled:
            self._progress_bar.config(mode="determinate", value=0)
            self._set_progress_text("Cancelled")
            self._log_append("─" * 50 + "\nCancelled by user.\n")
            return

        if success:
            self._progress_bar.config(mode="determinate", maximum=100, value=100)
            self._set_progress_text("✓  Indexing complete — reloading AI search…")
            self._log_append("─" * 50 + "\n✓ Indexing completed successfully.\n")
            try:
                self._file_lbl.config(text="")
            except Exception:
                pass
            self._manager._retry_bridge()
            if self._manager._active_ui:
                self._manager._active_ui.set_status(
                    "ready", "✓  Index rebuilt — AI search ready")
        else:
            self._progress_bar.config(mode="determinate", value=0)
            self._set_progress_text(f"✗  Failed: {error or 'unknown error'}", error=True)
            self._log_append(f"─" * 50 + f"\n✗ Failed: {error}\n")

    def _set_progress_text(self, text: str, error: bool = False):
        try:
            tp = self._app
            color = getattr(tp, "accent_secondary", "#FF6B6B") if error \
                else getattr(tp, "text_muted", "#5B6C8F")
            self._progress_lbl.config(text=text, fg=color)
        except Exception:
            pass

    def _log_append(self, text: str):
        try:
            self._log_text.config(state=tk.NORMAL)
            self._log_text.insert(tk.END, text)
            self._log_text.see(tk.END)
            self._log_text.config(state=tk.DISABLED)
        except Exception:
            pass

    def _on_close(self):
        if self._running:
            self._cancel_indexing()
        if self._win and self._win.winfo_exists():
            self._win.destroy()
        self._win = None