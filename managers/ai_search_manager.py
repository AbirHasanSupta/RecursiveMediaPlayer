from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from typing import Callable, Optional

from managers.ai_search_bridge import AISearchBridge, AIPreprocessor
from managers.ai_indexing_dialog import IndexingDialog
from managers.ai_index_status import IndexStatus, IndexStatusChecker

try:
    from tkinter import ttk
except ImportError:
    pass


class AISearchManager:
    def __init__(self, root: tk.Misc, app, logger: Callable = None):
        self._root = root
        self._app = app
        self._log = logger or (lambda m: None)
        self._bridge: Optional[AISearchBridge] = None
        self._preprocessor = AIPreprocessor(logger=self._log)
        self._directory_filter: list = []
        self._active_ui: Optional[AISearchUI] = None
        self._bridge_start_attempted = False
        self._index_status: Optional[IndexStatus] = None

    def _get_index_dir(self) -> str:
        try:
            return self._app.settings_manager.settings.ai_index_path
        except Exception:
            return str(Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
                       / "Recursive Media Player" / "index_data")

    def _ensure_bridge(self):
        index_dir = self._get_index_dir()
        checker = IndexStatusChecker(index_dir)
        self._index_status = checker.check_files()

        if not self._index_status.files_present:
            if self._active_ui:
                self._active_ui.set_status("warn", "⚠  No index found — click Index to build one")
                self._active_ui.set_device_badge("", "")
            return

        if self._bridge and self._bridge.is_ready():
            if self._active_ui:
                label, color = self._index_status.format_device()
                self._active_ui.set_status("ready", self._index_status.ready_status_text())
                self._active_ui.set_device_badge(label, color)
                if self._index_status.is_stale:
                    self._active_ui.set_stale_warning(
                        self._index_status.new_video_count,
                        self._index_status.missing_video_count,
                    )
            return

        if self._bridge_start_attempted and self._bridge and self._bridge._process and \
                self._bridge._process.poll() is None:
            return

        self._bridge = AISearchBridge(
            index_dir, root=self._root, logger=self._log,
            on_ready_callback=self._on_bridge_ready,
        )
        self._bridge_start_attempted = True

        if self._active_ui:
            self._active_ui.set_status("loading", "⏳  Loading AI models…")
            self._active_ui.set_device_badge("", "")

        def _start_bg():
            ok = self._bridge.start()
            if not ok:
                self._root.after(0, self._on_bridge_error)
                return
            self._root.after(200, self._poll_bridge_ready)

        threading.Thread(target=_start_bg, daemon=True).start()

    def _poll_bridge_ready(self, attempts: int = 0):
        if not self._active_ui:
            return
        if self._bridge and self._bridge.is_ready():
            return
        if attempts > 120:
            self._on_bridge_error()
            return
        if self._bridge and self._bridge._process and self._bridge._process.poll() is not None:
            self._on_bridge_error()
            return
        self._root.after(500, lambda: self._poll_bridge_ready(attempts + 1))

    def _on_bridge_ready(self, msg: dict):
        if self._index_status is None:
            return
        device_str = msg.get("device", "")
        self._index_status.device = device_str
        self._index_status.bridge_ready = True
        vc = msg.get("video_count")
        if vc is not None:
            self._index_status.video_count = int(vc)

        if self._active_ui:
            label, color = self._index_status.format_device()
            self._active_ui.set_status("ready", self._index_status.ready_status_text())
            self._active_ui.set_device_badge(label, color)

        status_ref = self._index_status
        watched = list(getattr(self._app, "selected_dirs", []) or [])
        index_dir = self._get_index_dir()

        def _check():
            IndexStatusChecker(index_dir).check_staleness(status_ref, watched or None)
            if status_ref.is_stale and self._active_ui:
                self._root.after(
                    0,
                    lambda: self._active_ui.set_stale_warning(
                        status_ref.new_video_count, status_ref.missing_video_count
                    ) if self._active_ui else None,
                )

        threading.Thread(target=_check, daemon=True).start()

    def _on_bridge_error(self):
        self._bridge_start_attempted = False
        if self._active_ui:
            self._active_ui.set_status(
                "error", "✗  AI process error — click Retry to restart",
                retry_callback=self._retry_bridge
            )

    def _retry_bridge(self):
        self._bridge_start_attempted = False
        if self._bridge:
            self._bridge.stop()
            self._bridge = None
        self._ensure_bridge()

    def show_embedded(self, frame: tk.Frame, close_callback: Callable = None) -> "AISearchUI":
        ui = AISearchUI(
            frame=frame,
            root=self._root,
            app=self._app,
            manager=self,
            close_callback=close_callback,
        )
        self._active_ui = ui
        self._ensure_bridge()
        return ui

    def apply_search(self, query: str):
        if self._active_ui:
            self._active_ui.run_search(query)

    def set_directory_filter(self, dirs: list):
        self._directory_filter = list(dirs) if dirs else []
        if self._active_ui:
            self._active_ui.set_directory_filter(self._directory_filter)

    def do_query(self, query: str, directory_filter: str, top_k: int, callback: Callable):
        if not self._bridge or not self._bridge.is_ready():
            self._ensure_bridge()
            callback({"error": "bridge not ready", "results": [], "counts": {}, "scores": {}})
            return
        self._bridge.query(query, directory_filter=directory_filter, top_k=top_k, callback=callback)

    def start_preprocessing(self, progress_cb: Callable, done_cb: Callable):
        try:
            settings = self._app.settings_manager.settings
            videos_dir = None
            dirs = getattr(self._app, "selected_dirs", [])
            if dirs:
                videos_dir = dirs[0]
            if not videos_dir:
                done_cb(success=False, error="No directory selected")
                return
            self._preprocessor.start_preprocessing(
                videos_dir, settings, progress_cb, done_cb
            )
        except Exception as e:
            done_cb(success=False, error=str(e))

    def cancel_preprocessing(self):
        self._preprocessor.cancel()

    def cleanup(self):
        self._active_ui = None
        if self._bridge:
            self._bridge.stop()
            self._bridge = None
        self._bridge_start_attempted = False


class AISearchUI:
    def __init__(self, frame: tk.Frame, root: tk.Misc, app, manager: AISearchManager,
                 close_callback: Callable = None):
        self._frame = frame
        self._root = root
        self._app = app
        self._manager = manager
        self._close_callback = close_callback
        self._directory_filter: Optional[str] = None
        self._last_query = ""
        self._result_widgets: list = []
        self._preprocessing = False
        self._debounce_id = None

        self._pull_theme()
        self._build()

    def _pull_theme(self):
        a = self._app
        self.bg = getattr(a, "bg_color", "#F7F9FC")
        self.surface = getattr(a, "surface_color", "#FFFFFF")
        self.accent = getattr(a, "accent_color", "#5E81F4")
        self.accent2 = getattr(a, "accent_secondary", "#FF6B6B")
        self.text = getattr(a, "text_color", "#1E2A3A")
        self.muted = getattr(a, "text_muted", "#5B6C8F")
        self.border = getattr(a, "border_color", "#E2E8F0")
        self.hover = getattr(a, "hover_color", "#EDF2F7")
        self.alt_row = getattr(a, "alt_row_color", "#F7F9FC")
        self.fn = getattr(a, "normal_font", ("Segoe UI", 10))
        self.fs = getattr(a, "small_font", ("Segoe UI", 9))

    def _build(self):
        self._frame.configure(bg=self.bg)

        top = tk.Frame(self._frame, bg=self.surface,
                       highlightbackground=self.border, highlightthickness=1)
        top.pack(fill=tk.X, padx=0, pady=0)

        search_row = tk.Frame(top, bg=self.surface)
        search_row.pack(fill=tk.X, padx=16, pady=(12, 8))

        search_wrap = tk.Frame(search_row, bg=self.surface,
                               highlightbackground=self.border, highlightthickness=1)
        search_wrap.pack(side=tk.LEFT, fill=tk.X, expand=True)

        icon_lbl = tk.Label(search_wrap, text="🔍", bg=self.surface, fg=self.muted,
                            font=("Segoe UI Emoji", 11), padx=6)
        icon_lbl.pack(side=tk.LEFT)

        self._search_var = tk.StringVar()
        self.search_entry = tk.Entry(
            search_wrap,
            textvariable=self._search_var,
            bg=self.surface, fg=self.text,
            relief="flat", bd=0,
            font=self.fn,
            insertbackground=self.accent,
        )
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, padx=(0, 8))
        self.search_entry.insert(0, "")
        self.search_entry.bind("<Return>", lambda _e: self._on_search_click())
        self.search_entry.bind("<FocusIn>", lambda _e: search_wrap.config(
            highlightbackground=self.accent))
        self.search_entry.bind("<FocusOut>", lambda _e: search_wrap.config(
            highlightbackground=self.border))

        clear_btn = tk.Label(search_wrap, text="✕", bg=self.surface, fg=self.muted,
                             font=("Segoe UI", 10), padx=6, cursor="hand2")
        clear_btn.pack(side=tk.RIGHT)
        clear_btn.bind("<Button-1>", lambda _e: self._clear_search())

        self._search_btn = tk.Label(
            search_row, text="Search",
            bg=self.accent, fg="#ffffff",
            font=("Segoe UI", 10, "bold"),
            padx=14, pady=6, cursor="hand2",
        )
        self._search_btn.pack(side=tk.LEFT, padx=(8, 6))
        self._search_btn.bind("<Button-1>", lambda _e: self._on_search_click())
        self._search_btn.bind("<Enter>", lambda _e: self._search_btn.config(bg=self.accent2))
        self._search_btn.bind("<Leave>", lambda _e: self._search_btn.config(bg=self.accent))

        self._index_btn = tk.Label(
            search_row, text="⚙  Index",
            bg=self.surface, fg=self.muted,
            font=("Segoe UI", 10),
            padx=10, pady=6, cursor="hand2",
            highlightbackground=self.border, highlightthickness=1,
        )
        self._index_btn.pack(side=tk.LEFT, padx=(0, 0))
        self._index_btn.bind("<Button-1>", lambda _e: self._on_index_click())
        self._index_btn.bind("<Enter>", lambda _e: self._index_btn.config(
            fg=self.accent, highlightbackground=self.accent))
        self._index_btn.bind("<Leave>", lambda _e: self._index_btn.config(
            fg=self.muted, highlightbackground=self.border))

        status_row = tk.Frame(top, bg=self.surface)
        status_row.pack(fill=tk.X, padx=16, pady=(0, 10))

        self._status_icon = tk.Label(status_row, text="⏳", bg=self.surface,
                                     fg=self.muted, font=("Segoe UI Emoji", 9))
        self._status_icon.pack(side=tk.LEFT)

        self._status_lbl = tk.Label(status_row, text="Initializing…",
                                    bg=self.surface, fg=self.muted, font=self.fs)
        self._status_lbl.pack(side=tk.LEFT, padx=(4, 0))

        self._retry_lbl = tk.Label(status_row, text="Retry", bg=self.surface,
                                   fg=self.accent, font=self.fs, cursor="hand2")

        self._device_badge = tk.Label(
            status_row, text="", bg="#34c98a", fg="#ffffff",
            font=("Segoe UI", 7, "bold"), padx=5, pady=1,
        )

        self._stale_lbl = tk.Label(
            status_row, text="", bg=self.surface,
            fg="#f5a623", font=self.fs, cursor="hand2",
        )
        self._stale_lbl.bind("<Button-1>", lambda _e: self._on_index_click())

        divider = tk.Frame(self._frame, bg=self.border, height=1)
        divider.pack(fill=tk.X)

        self._results_outer = tk.Frame(self._frame, bg=self.bg)
        self._results_outer.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(self._results_outer, bg=self.bg,
                                 highlightthickness=0, bd=0)
        self._scrollbar = ttk.Scrollbar(self._results_outer, orient="vertical",
                                        command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._results_frame = tk.Frame(self._canvas, bg=self.bg)
        self._results_win = self._canvas.create_window(
            (0, 0), window=self._results_frame, anchor="nw"
        )
        self._results_frame.bind("<Configure>", self._on_results_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        self._show_empty_state()

    def _on_results_configure(self, _e):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, e):
        self._canvas.itemconfig(self._results_win, width=e.width)

    def _on_mousewheel(self, e):
        try:
            self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        except Exception:
            pass

    def set_status(self, state: str, text: str, retry_callback: Callable = None):
        icons = {
            "ready": ("✓", "#34c98a"),
            "loading": ("⏳", self.muted),
            "warn": ("⚠", "#f5a623"),
            "error": ("✗", self.accent2),
            "indexing": ("⚙", self.accent),
        }
        icon, color = icons.get(state, ("●", self.muted))
        try:
            self._status_icon.config(text=icon, fg=color)
            self._status_lbl.config(text=text, fg=color if state != "loading" else self.muted)
            self._retry_lbl.pack_forget()
            if state != "ready":
                self._device_badge.pack_forget()
                self._stale_lbl.pack_forget()
            if retry_callback:
                self._retry_lbl.config(command=retry_callback)
                self._retry_lbl.bind("<Button-1>", lambda _e: retry_callback())
                self._retry_lbl.pack(side=tk.LEFT, padx=(8, 0))
        except Exception:
            pass

    def set_device_badge(self, label: str, hex_color: str):
        try:
            if label:
                self._device_badge.config(text=f" {label} ", bg=hex_color)
                self._device_badge.pack(side=tk.LEFT, padx=(8, 0))
            else:
                self._device_badge.pack_forget()
        except Exception:
            pass

    def set_stale_warning(self, new_count: int, missing_count: int):
        try:
            if new_count or missing_count:
                parts = []
                if new_count:
                    parts.append(f"{new_count:,} new")
                if missing_count:
                    parts.append(f"{missing_count:,} removed")
                self._stale_lbl.config(
                    text="  ⚠ " + ", ".join(parts) + " — click Index to update"
                )
                self._stale_lbl.pack(side=tk.LEFT, padx=(4, 0))
            else:
                self._stale_lbl.pack_forget()
        except Exception:
            pass

    def set_directory_filter(self, dirs: list):
        self._directory_filter = dirs[0] if dirs else None

    def run_search(self, query: str):
        self._search_var.set(query)
        self._on_search_click()

    def apply_search(self, query: str):
        self.run_search(query)

    def _clear_search(self):
        self._search_var.set("")
        self.search_entry.focus_set()
        self._show_empty_state()

    def _on_search_click(self):
        query = self._search_var.get().strip()
        if not query:
            return
        self._last_query = query
        self._show_loading_state(query)
        self._manager.do_query(
            query,
            directory_filter=self._directory_filter,
            top_k=20,
            callback=self._on_results,
        )

    def _on_results(self, msg: dict):
        if msg.get("error"):
            err = msg["error"]
            if "bridge not ready" in err:
                self.set_status("loading", "⏳  AI still loading — please wait and try again")
            else:
                self.set_status("error", f"✗  Search error: {err}")
            self._show_error_state(err)
            return
        results = msg.get("results", [])
        counts = msg.get("counts", {})
        scores = msg.get("scores", {})
        self._render_results(results, counts, scores)

    def _show_empty_state(self):
        self._clear_results()
        pad = tk.Frame(self._results_frame, bg=self.bg)
        pad.pack(fill=tk.BOTH, expand=True, pady=60)
        tk.Label(pad, text="🔍", font=("Segoe UI Emoji", 32),
                 bg=self.bg, fg=self.border).pack()
        tk.Label(pad, text="Describe what you're looking for",
                 font=("Segoe UI", 13, "bold"), bg=self.bg, fg=self.text).pack(pady=(8, 4))
        tk.Label(pad,
                 text="e.g.  \"woman in red dress dancing\"  ·  \"sunset on the beach\"  ·  \"cat playing with toy\"",
                 font=("Segoe UI", 9), bg=self.bg, fg=self.muted).pack()

    def _show_loading_state(self, query: str):
        self._clear_results()
        pad = tk.Frame(self._results_frame, bg=self.bg)
        pad.pack(fill=tk.BOTH, expand=True, pady=60)
        tk.Label(pad, text="⏳", font=("Segoe UI Emoji", 28),
                 bg=self.bg, fg=self.muted).pack()
        tk.Label(pad, text=f"Searching for  \"{query}\"…",
                 font=("Segoe UI", 11), bg=self.bg, fg=self.muted).pack(pady=(8, 0))

    def _show_error_state(self, error: str):
        self._clear_results()
        pad = tk.Frame(self._results_frame, bg=self.bg)
        pad.pack(fill=tk.BOTH, expand=True, pady=60)
        tk.Label(pad, text="✗", font=("Segoe UI", 28, "bold"),
                 bg=self.bg, fg=self.accent2).pack()
        tk.Label(pad, text=error, font=("Segoe UI", 10),
                 bg=self.bg, fg=self.muted, wraplength=480).pack(pady=(8, 0))

    def _show_no_results_state(self, query: str):
        self._clear_results()
        pad = tk.Frame(self._results_frame, bg=self.bg)
        pad.pack(fill=tk.BOTH, expand=True, pady=60)
        tk.Label(pad, text="🎬", font=("Segoe UI Emoji", 28),
                 bg=self.bg, fg=self.border).pack()
        tk.Label(pad, text=f"No results for  \"{query}\"",
                 font=("Segoe UI", 12, "bold"), bg=self.bg, fg=self.text).pack(pady=(8, 4))
        tk.Label(pad, text="Try different keywords or broader descriptions",
                 font=("Segoe UI", 9), bg=self.bg, fg=self.muted).pack()

    def _clear_results(self):
        for w in self._result_widgets:
            try:
                w.destroy()
            except Exception:
                pass
        self._result_widgets.clear()
        for child in self._results_frame.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass

    def _render_results(self, results: list, counts: dict, scores: dict):
        self._clear_results()
        if not results:
            self._show_no_results_state(self._last_query)
            return

        header = tk.Frame(self._results_frame, bg=self.bg)
        header.pack(fill=tk.X, padx=16, pady=(12, 6))
        self._result_widgets.append(header)
        tk.Label(header,
                 text=f"{len(results)} result{'s' if len(results) != 1 else ''} for  \"{self._last_query}\"",
                 font=("Segoe UI", 10, "bold"), bg=self.bg, fg=self.text).pack(side=tk.LEFT)
        if self._directory_filter:
            dir_lbl = os.path.basename(self._directory_filter) or self._directory_filter
            tk.Label(header, text=f"in {dir_lbl}",
                     font=self.fs, bg=self.bg, fg=self.muted).pack(side=tk.LEFT, padx=(6, 0))

        for i, video_path in enumerate(results):
            row_bg = self.surface if i % 2 == 0 else self.alt_row
            card = self._make_result_card(video_path, counts, scores, row_bg)
            card.pack(fill=tk.X, padx=16, pady=3)
            self._result_widgets.append(card)

        self._canvas.yview_moveto(0)

    def _make_result_card(self, video_path: str, counts: dict, scores: dict, bg: str) -> tk.Frame:
        score = scores.get(video_path, 0.0)
        count = counts.get(video_path, 1)
        filename = os.path.basename(video_path)
        name_no_ext = os.path.splitext(filename)[0]

        card = tk.Frame(
            self._results_frame, bg=bg,
            highlightbackground=self.border, highlightthickness=1,
        )

        def _enter(_e):
            card.config(bg=self.hover, highlightbackground=self.accent)
            for w in _all_card_widgets:
                try:
                    w.config(bg=self.hover)
                except Exception:
                    pass

        def _leave(_e):
            card.config(bg=bg, highlightbackground=self.border)
            for w in _all_card_widgets:
                try:
                    w.config(bg=bg)
                except Exception:
                    pass

        card.bind("<Enter>", _enter)
        card.bind("<Leave>", _leave)
        card.bind("<Double-Button-1>", lambda _e: self._play_video(video_path))

        left = tk.Frame(card, bg=bg, width=72)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 0), pady=10)
        left.pack_propagate(False)

        thumb_lbl = tk.Label(left, text="🎬", font=("Segoe UI Emoji", 22),
                             bg=bg, fg=self.muted, width=4, height=2)
        thumb_lbl.pack(expand=True)

        score_bar_bg = tk.Frame(left, bg=self.border, height=4)
        score_bar_bg.pack(fill=tk.X, pady=(4, 0))
        bar_fill = tk.Frame(score_bar_bg, bg=self._score_color(score), height=4)
        bar_fill.place(relx=0, rely=0, relwidth=min(score, 1.0), relheight=1.0)

        right = tk.Frame(card, bg=bg)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=10)

        name_lbl = tk.Label(right, text=name_no_ext,
                            font=("Segoe UI", 10, "bold"),
                            bg=bg, fg=self.text,
                            anchor="w", justify=tk.LEFT)
        name_lbl.pack(fill=tk.X)

        meta_lbl = tk.Label(
            right,
            text=f"Score: {score:.2f}  ·  {count} matching frame{'s' if count != 1 else ''}",
            font=self.fs, bg=bg, fg=self.muted, anchor="w",
        )
        meta_lbl.pack(fill=tk.X, pady=(2, 0))

        dir_lbl = tk.Label(
            right,
            text=os.path.dirname(video_path),
            font=self.fs, bg=bg, fg=self.muted, anchor="w",
        )
        dir_lbl.pack(fill=tk.X)

        btn_row = tk.Frame(right, bg=bg)
        btn_row.pack(fill=tk.X, pady=(6, 0))

        play_btn = tk.Label(btn_row, text="▶  Play",
                            font=("Segoe UI", 9, "bold"),
                            bg=self.accent, fg="#ffffff",
                            padx=10, pady=4, cursor="hand2")
        play_btn.pack(side=tk.LEFT, padx=(0, 6))
        play_btn.bind("<Button-1>", lambda _e: self._play_video(video_path))
        play_btn.bind("<Enter>", lambda _e: play_btn.config(bg=self.accent2))
        play_btn.bind("<Leave>", lambda _e: play_btn.config(bg=self.accent))

        open_btn = tk.Label(btn_row, text="📂  Locate",
                            font=("Segoe UI", 9),
                            bg=bg, fg=self.muted,
                            padx=8, pady=4, cursor="hand2",
                            highlightbackground=self.border, highlightthickness=1)
        open_btn.pack(side=tk.LEFT, padx=(0, 6))
        open_btn.bind("<Button-1>", lambda _e: self._locate_video(video_path))
        open_btn.bind("<Enter>", lambda _e: open_btn.config(
            fg=self.accent, highlightbackground=self.accent))
        open_btn.bind("<Leave>", lambda _e: open_btn.config(
            fg=self.muted, highlightbackground=self.border))

        queue_btn = tk.Label(btn_row, text="+ Queue",
                             font=("Segoe UI", 9),
                             bg=bg, fg=self.muted,
                             padx=8, pady=4, cursor="hand2",
                             highlightbackground=self.border, highlightthickness=1)
        queue_btn.pack(side=tk.LEFT)
        queue_btn.bind("<Button-1>", lambda _e: self._add_to_queue(video_path))
        queue_btn.bind("<Enter>", lambda _e: queue_btn.config(
            fg=self.accent, highlightbackground=self.accent))
        queue_btn.bind("<Leave>", lambda _e: queue_btn.config(
            fg=self.muted, highlightbackground=self.border))

        _all_card_widgets = [left, thumb_lbl, score_bar_bg, right,
                              name_lbl, meta_lbl, dir_lbl, btn_row, open_btn, queue_btn]
        for w in _all_card_widgets:
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)

        return card

    def _score_color(self, score: float) -> str:
        if score >= 0.75:
            return "#34c98a"
        if score >= 0.50:
            return "#5E81F4"
        if score >= 0.30:
            return "#f5a623"
        return "#aaaaaa"

    def _play_video(self, video_path: str):
        try:
            self._app._play_grid_videos([video_path])
        except Exception as e:
            self._manager._log(f"AI Search play error: {e}")

    def _locate_video(self, video_path: str):
        try:
            if hasattr(self._app, "locate_in_directory_panel"):
                self._app.locate_in_directory_panel(video_path)
        except Exception:
            pass

    def _add_to_queue(self, video_path: str):
        try:
            self._app.queue_manager.add_to_queue([video_path], added_from="ai_search")
        except Exception as e:
            self._manager._log(f"AI Search queue error: {e}")

    def _on_index_click(self):
        IndexingDialog(self._root, self._app, self._manager).show()