from __future__ import annotations

import os
import threading
import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

from managers.ai_search_bridge import AIServerBridge, AIPreprocessorBridge
from managers.ai_indexing_dialog import IndexingDialog
from managers.ai_index_status import IndexStatus, IndexStatusChecker

try:
    from tkinter import ttk
except ImportError:
    pass

try:
    from PIL import Image, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

import keyboard_navigation

_THUMB_W = 120
_THUMB_H = 68


class AISearchManager:
    def __init__(self, root: tk.Misc, app, logger: Callable = None):
        self._root = root
        self._app = app
        self._log = logger or (lambda m: None)
        self._bridge: Optional[AIServerBridge] = None
        self._preprocessor = AIPreprocessorBridge(
            get_bridge_fn=lambda: self._bridge,
            root=self._root,
            logger=self._log,
        )
        self._directory_filter: list = []
        self._active_ui: Optional[AISearchUI] = None
        self._connect_attempted = False
        self._index_status: Optional[IndexStatus] = None
        self._persisted_state: Optional[dict] = None

    def cleanup(self):
        if self._bridge:
            self._bridge.disconnect()
            self._bridge = None

    def _get_server_url(self) -> str:
        try:
            return (self._app.settings_manager.settings.ai_server_url or "").strip()
        except Exception:
            return ""

    def _get_index_dir(self) -> str:
        try:
            return self._app.settings_manager.settings.ai_index_path
        except Exception:
            return str(Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
                       / "Recursive Video Player" / "index_data")

    def _ensure_bridge(self):
        url = self._get_server_url()

        if not url:
            if self._active_ui:
                self._active_ui.set_status(
                    "error",
                    "⚠  No AI server URL configured — add one in Settings → AI & Preprocessing",
                    show_settings=True
                )
            return

        index_dir = self._get_index_dir()
        checker = IndexStatusChecker(index_dir)
        self._index_status = checker.check_files()

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

        if self._connect_attempted and self._bridge and self._bridge.is_alive():
            if not self._index_status.files_present and self._active_ui:
                self._active_ui.set_status(
                    "warn",
                    "⚠  No index found — click Index to build one",
                    show_settings=False
                )
                self._active_ui.set_device_badge("", "")
            return

        if self._connect_attempted and self._bridge and not self._bridge.is_ready():
            return

        if self._bridge:
            self._bridge.disconnect()

        self._bridge = AIServerBridge(
            base_url=url,
            root=self._root,
            logger=self._log,
            on_ready_callback=self._on_bridge_ready,
        )
        self._connect_attempted = True

        if self._active_ui:
            self._active_ui.set_status("loading", "⏳  Connecting to AI server…")

        def _connect_bg():
            ok = self._bridge.connect()
            if not ok:
                self._root.after(0, self._on_bridge_error)

        threading.Thread(target=_connect_bg, daemon=True).start()

    def _on_bridge_ready(self, msg: dict):
        status = msg.get("status")

        if status == "error":
            self._root.after(0, self._on_bridge_error)
            return

        if self._index_status is None:
            return

        if status == "no_index":
            self._index_status.bridge_ready = False
            if self._active_ui:
                self._active_ui.set_status(
                    "warn",
                    "⚠  No index found — click Index to build one",
                    show_settings=False
                )
                self._active_ui.set_device_badge("", "")
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
        self._connect_attempted = False
        if self._active_ui:
            self._active_ui.set_status(
                "error",
                "✗  Could not reach AI server — check the URL in Settings → AI & Preprocessing",
                retry_callback=self._retry_bridge,
                show_settings=True
            )

    def _retry_bridge(self):
        self._connect_attempted = False
        if self._bridge:
            self._bridge.disconnect()
            self._bridge = None
        self._ensure_bridge()

    def notify_url_changed(self):
        self._connect_attempted = False
        if self._bridge:
            self._bridge.disconnect()
            self._bridge = None
        if self._active_ui:
            self._ensure_bridge()

    def _save_state(self, query: str, results: list, counts: dict, scores: dict, search_mode: str = "ai"):
        self._persisted_state = {
            "query": query,
            "results": results,
            "counts": counts,
            "scores": scores,
            "search_mode": search_mode
        }

    def _clear_state(self):
        self._persisted_state = None

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
        if self._persisted_state:
            ui.restore_state(self._persisted_state)
        return ui

    def apply_search(self, query: str):
        if self._active_ui:
            self._active_ui.apply_local_filter(query)

    def set_directory_filter(self, dirs: list):
        self._directory_filter = list(dirs) if dirs else []
        if self._active_ui:
            self._active_ui.set_directory_filter(self._directory_filter)

    def do_query(self, query: str, directory_filter: str, top_k: int, callback: Callable, search_mode: str = "ai"):
        if not self._bridge or not self._bridge.is_ready():
            self._ensure_bridge()
            callback({"error": "bridge not ready", "results": [], "counts": {}, "scores": {}})
            return
        if search_mode == "normal":
            self._bridge.query(query, directory_filter=directory_filter, top_k=top_k, callback=callback)
        else:
            self._bridge.ai_query(query, directory_filter=directory_filter, top_k=top_k, callback=callback)

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
            self._preprocessor.start_preprocessing(videos_dir, settings, progress_cb, done_cb)
        except Exception as e:
            done_cb(success=False, error=str(e))

    def cancel_preprocessing(self):
        self._preprocessor.cancel()

    def cleanup(self):
        self._active_ui = None
        if self._bridge:
            self._bridge.disconnect()
            self._bridge = None
        self._connect_attempted = False


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

        self._selected_paths: set = set()
        self._all_results: list = []
        self._last_anchor_path: Optional[str] = None
        self._card_frames: dict = {}
        self._photo_cache: dict = {}
        self._sel_count_lbl: Optional[tk.Label] = None
        self._result_count_lbl: Optional[tk.Label] = None
        self._search_mode = "ai"
        self._thumb_semaphore = threading.Semaphore(4)
        self._focus_path: Optional[str] = None
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
        dark = getattr(a, "dark_mode", False)
        self.accent_dim = "#172344" if dark else "#dbeafe"

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

        options_row = tk.Frame(top, bg=self.surface)
        options_row.pack(fill=tk.X, padx=16, pady=(0, 8))

        mode_lbl = tk.Label(
            options_row, text="Search Type:",
            bg=self.surface, fg=self.text, font=self.fs
        )
        mode_lbl.pack(side=tk.LEFT, padx=(0, 8))

        selector_frame = tk.Frame(
            options_row, bg=self.surface,
            highlightbackground=self.border, highlightthickness=1
        )
        selector_frame.pack(side=tk.LEFT)

        self._normal_mode_btn = tk.Label(
            selector_frame, text="Normal Search",
            bg=self.surface, fg=self.muted, font=self.fs,
            padx=12, pady=4, cursor="hand2"
        )
        self._normal_mode_btn.pack(side=tk.LEFT)

        self._advanced_mode_btn = tk.Label(
            selector_frame, text="Advanced Search",
            bg=self.surface, fg=self.muted, font=self.fs,
            padx=12, pady=4, cursor="hand2"
        )
        self._advanced_mode_btn.pack(side=tk.LEFT)

        self._normal_mode_btn.bind("<Button-1>", lambda _e: self._set_search_mode("normal"))
        self._normal_mode_btn.bind("<Enter>", lambda _e: self._on_mode_hover(self._normal_mode_btn, "normal", True))
        self._normal_mode_btn.bind("<Leave>", lambda _e: self._on_mode_hover(self._normal_mode_btn, "normal", False))

        self._advanced_mode_btn.bind("<Button-1>", lambda _e: self._set_search_mode("ai"))
        self._advanced_mode_btn.bind("<Enter>", lambda _e: self._on_mode_hover(self._advanced_mode_btn, "ai", True))
        self._advanced_mode_btn.bind("<Leave>", lambda _e: self._on_mode_hover(self._advanced_mode_btn, "ai", False))

        self._set_search_mode(self._search_mode)

        status_row = tk.Frame(top, bg=self.surface)
        status_row.pack(fill=tk.X, padx=16, pady=(0, 10))

        self._status_lbl = tk.Label(status_row, text="⏳  Initializing…",
                                    bg=self.surface, fg=self.muted, font=self.fs)
        self._status_lbl.pack(side=tk.LEFT)

        self._status_actions = tk.Frame(status_row, bg=self.surface)
        self._status_actions.pack(side=tk.LEFT, padx=(8, 0))

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
                                        command=self._canvas.yview,
                                        style="ExclusionTree.Vertical.TScrollbar")
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 1), pady=1)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._results_frame = tk.Frame(self._canvas, bg=self.bg)
        self._results_win = self._canvas.create_window(
            (0, 0), window=self._results_frame, anchor="nw"
        )
        self._results_frame.bind("<Configure>", self._on_results_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        # Fix mousewheel scrolling
        self._setup_mousewheel_scrolling()

        self._canvas.bind("<Button-1>", lambda _e: self._clear_selection())
        self._results_frame.bind("<Button-1>", lambda _e: self._clear_selection())
        self._frame.bind("<Control-a>", lambda _e: self._select_all())
        self._frame.bind("<Escape>", lambda _e: self._clear_selection())
        self._setup_ai_search_keyboard_nav()
        self._setup_focus_ring()

        self._show_empty_state()

    def _setup_mousewheel_scrolling(self):
        """Set up global mousewheel bindings that only scroll the results canvas when the mouse is hovering over the AI Search UI."""
        def _on_global_mousewheel(event):
            try:
                if not self._canvas.winfo_exists():
                    return
                # Walk up master tree to see if event.widget is inside self._frame
                w = event.widget
                while w:
                    # Try to compare both string paths and widget objects to be robust
                    w_str = str(w)
                    frame_str = str(self._frame)
                    if w == self._frame or w_str == frame_str:
                        if event.num == 4:
                            delta = -1
                        elif event.num == 5:
                            delta = 1
                        else:
                            delta = -1 * (event.delta // abs(event.delta)) if event.delta != 0 else 0
                        self._canvas.yview_scroll(delta, "units")
                        return "break"
                    w = w.master
            except Exception:
                pass

        self._canvas.bind_all("<MouseWheel>", _on_global_mousewheel)
        self._canvas.bind_all("<Button-4>", _on_global_mousewheel)
        self._canvas.bind_all("<Button-5>", _on_global_mousewheel)

        def _unbind_all_scroll(e):
            if e.widget == self._frame:
                try:
                    self._canvas.unbind_all("<MouseWheel>")
                    self._canvas.unbind_all("<Button-4>")
                    self._canvas.unbind_all("<Button-5>")
                except Exception:
                    pass

        self._frame.bind("<Destroy>", _unbind_all_scroll)

    def _on_results_configure(self, e):
        self._canvas.configure(scrollregion=(0, 0, e.width, e.height))

    def _on_canvas_configure(self, e):
        self._canvas.itemconfig(self._results_win, width=e.width)

    def set_status(self, state: str, text: str, retry_callback: Callable = None, show_settings: bool = False):
        icons = {
            "ready": ("✓", "#34c98a"),
            "loading": ("⏳", self.muted),
            "warn": ("⚠", "#f5a623"),
            "error": ("✗", self.accent2),
            "indexing": ("⚙", self.accent),
        }
        icon, color = icons.get(state, ("●", self.muted))
        try:
            self._status_lbl.config(text=text, fg=color if state != "loading" else self.muted)
            for child in self._status_actions.winfo_children():
                child.destroy()
            if retry_callback:
                retry_btn = tk.Label(
                    self._status_actions, text="Retry", bg=self.surface,
                    fg=self.accent, font=self.fs, cursor="hand2"
                )
                retry_btn.pack(side=tk.LEFT, padx=(0, 6))
                retry_btn.bind("<Button-1>", lambda _e: retry_callback())
                retry_btn.bind("<Enter>", lambda _e: retry_btn.config(fg=self.accent2))
                retry_btn.bind("<Leave>", lambda _e: retry_btn.config(fg=self.accent))
            if show_settings:
                settings_btn = tk.Label(
                    self._status_actions, text="Settings", bg=self.surface,
                    fg=self.accent, font=self.fs, cursor="hand2"
                )
                settings_btn.pack(side=tk.LEFT)
                settings_btn.bind("<Button-1>", lambda _e: self._open_ai_settings())
                settings_btn.bind("<Enter>", lambda _e: settings_btn.config(fg=self.accent2))
                settings_btn.bind("<Leave>", lambda _e: settings_btn.config(fg=self.accent))
            self._device_badge.pack_forget()
            self._stale_lbl.pack_forget()
        except Exception:
            pass

    def _open_ai_settings(self):
        try:
            if hasattr(self._app, "settings_manager") and self._app.settings_manager:
                self._app.settings_manager.show_settings(tab_index=1)
        except Exception as e:
            self._manager._log(f"Failed to open settings: {e}")

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

    def _set_search_mode(self, mode: str, rerun_on_change: bool = False):
        old_mode = getattr(self, "_search_mode", None)
        self._search_mode = mode
        if mode == "normal":
            self._normal_mode_btn.config(bg=self.accent, fg="#ffffff", font=("Segoe UI", 9, "bold"))
            self._advanced_mode_btn.config(bg=self.surface, fg=self.muted, font=("Segoe UI", 9))
        else:
            self._normal_mode_btn.config(bg=self.surface, fg=self.muted, font=("Segoe UI", 9))
            self._advanced_mode_btn.config(bg=self.accent, fg="#ffffff", font=("Segoe UI", 9, "bold"))

        if rerun_on_change and old_mode and old_mode != mode:
            query = self._search_var.get().strip()
            if query:
                self._on_search_click()

    def _on_mode_hover(self, btn, mode, entered):
        if self._search_mode != mode:
            if entered:
                btn.config(bg=self.hover, fg=self.text)
            else:
                btn.config(bg=self.surface, fg=self.muted)

    def run_search(self, query: str):
        self._search_var.set(query)
        self._on_search_click()

    def apply_local_filter(self, query: str):
        """Filter the currently displayed AI result cards locally by filename.
        This does NOT modify the AI search bar or re-run the AI query."""
        q = query.strip().lower()
        if not self._all_results or not self._card_frames:
            return
        visible_count = 0
        for video_path, card in list(self._card_frames.items()):
            try:
                if not card.winfo_exists():
                    continue
                name = os.path.splitext(os.path.basename(video_path))[0].lower()
                dir_path = os.path.dirname(video_path).lower()
                matches = not q or q in name or q in dir_path
                if matches:
                    card.pack(fill=tk.X, padx=16, pady=3)
                    visible_count += 1
                else:
                    card.pack_forget()
            except Exception:
                pass
        # Update the header count label to reflect visible results
        try:
            if hasattr(self, '_result_count_lbl') and self._result_count_lbl and \
                    self._result_count_lbl.winfo_exists():
                if q:
                    total = len(self._all_results)
                    self._result_count_lbl.config(
                        text=f"{visible_count} of {total} result{'s' if total != 1 else ''}"
                             f" for  \"{self._last_query}\"  ·  filtered by \"{query.strip()}\""
                    )
                else:
                    total = len(self._all_results)
                    self._result_count_lbl.config(
                        text=f"{total} result{'s' if total != 1 else ''} for  \"{self._last_query}\""
                    )
        except Exception:
            pass

    def apply_search(self, query: str):
        self.apply_local_filter(query)

    def restore_state(self, state: dict):
        self._search_var.set(state["query"])
        self._last_query = state["query"]
        mode = state.get("search_mode", "ai")
        self._set_search_mode(mode)
        self._render_results(state["results"], state["counts"], state["scores"])

    def _clear_search(self):
        self._search_var.set("")
        self.search_entry.focus_set()
        self._manager._clear_state()
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
            search_mode=self._search_mode,
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
        self._manager._save_state(self._last_query, results, counts, scores, self._search_mode)
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
        self._selected_paths.clear()
        self._all_results.clear()
        self._card_frames.clear()
        self._sel_count_lbl = None
        self._result_count_lbl = None
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

        self._all_results = list(results)
        max_score = max(scores.values()) if scores else 1.0

        header = tk.Frame(self._results_frame, bg=self.bg)
        header.pack(fill=tk.X, padx=16, pady=(12, 6))
        self._result_widgets.append(header)

        self._result_count_lbl = tk.Label(
            header,
            text=f"{len(results)} result{'s' if len(results) != 1 else ''} for  \"{self._last_query}\"",
            font=("Segoe UI", 10, "bold"), bg=self.bg, fg=self.text)
        self._result_count_lbl.pack(side=tk.LEFT)
        if self._directory_filter:
            dir_lbl = os.path.basename(self._directory_filter) or self._directory_filter
            tk.Label(header, text=f"in {dir_lbl}",
                     font=self.fs, bg=self.bg, fg=self.muted).pack(side=tk.LEFT, padx=(6, 0))

        self._sel_count_lbl = tk.Label(
            header, text="", font=self.fs, bg=self.bg, fg=self.accent
        )
        self._sel_count_lbl.pack(side=tk.RIGHT, padx=(0, 8))

        self._scores = dict(scores)
        self._counts = dict(counts)
        self._max_score = max_score
        for i, video_path in enumerate(results):
            row_bg = self.surface if i % 2 == 0 else self.alt_row
            card = self._make_result_card(video_path, counts, scores, row_bg, max_score)
            card.pack(fill=tk.X, padx=16, pady=3)
            card._video_path = video_path
            self._result_widgets.append(card)

        self._canvas.yview_moveto(0)

    def _make_result_card(self, video_path: str, counts: dict, scores: dict,
                          bg: str, max_score: float = 15.0) -> tk.Frame:
        score = scores.get(video_path, 0.0)
        count = counts.get(video_path, 1)
        name_no_ext = os.path.splitext(os.path.basename(video_path))[0]
        is_sel = video_path in self._selected_paths

        card_bg = self.accent_dim if is_sel else bg
        border_col = self.accent if is_sel else self.border
        border_w = 2 if is_sel else 1

        card = tk.Frame(
            self._results_frame, bg=card_bg,
            highlightbackground=border_col, highlightthickness=border_w,
        )
        card._orig_bg = bg
        self._card_frames[video_path] = card

        left = tk.Frame(card, bg=card_bg)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 0), pady=10)

        thumb_container = tk.Frame(left, bg="#0b0c0f", width=_THUMB_W, height=_THUMB_H)
        thumb_container.pack()
        thumb_container.pack_propagate(False)
        thumb_container._is_thumb = True

        thumb_lbl = tk.Label(thumb_container, text="🎬",
                             font=("Segoe UI Emoji", 14),
                             bg="#0b0c0f", fg="#2e323c")
        thumb_lbl.pack(fill=tk.BOTH, expand=True)

        threading.Thread(
            target=self._fetch_thumbnail_bg,
            args=(video_path, os.path.normpath(video_path), thumb_lbl),
            daemon=True,
        ).start()

        score_bar_bg = tk.Frame(left, bg=self.border, height=3)
        score_bar_bg.pack(fill=tk.X, pady=(3, 0))
        rel_w = min(score / max(max_score, 0.01), 1.0)
        bar_fill = tk.Frame(score_bar_bg, bg=self._score_color(score, max_score), height=3)
        bar_fill.place(relx=0, rely=0, relwidth=rel_w, relheight=1.0)

        right = tk.Frame(card, bg=card_bg)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=12, pady=10)

        name_lbl = tk.Label(right, text=name_no_ext,
                            font=("Segoe UI", 10, "bold"),
                            bg=card_bg, fg=self.accent if is_sel else self.text,
                            anchor="w", justify=tk.LEFT)
        name_lbl.pack(fill=tk.X)

        meta_lbl = tk.Label(
            right,
            text=f"Score: {score:.2f}  ·  {count} matching frame{'s' if count != 1 else ''}",
            font=self.fs, bg=card_bg, fg=self.muted, anchor="w",
        )
        meta_lbl.pack(fill=tk.X, pady=(2, 0))

        dir_lbl = tk.Label(
            right,
            text=os.path.dirname(video_path),
            font=self.fs, bg=card_bg, fg=self.muted, anchor="w",
        )
        dir_lbl.pack(fill=tk.X)

        btn_row = tk.Frame(right, bg=card_bg)
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
                            bg=card_bg, fg=self.muted,
                            padx=8, pady=4, cursor="hand2",
                            highlightbackground=self.border, highlightthickness=1)
        open_btn.pack(side=tk.LEFT, padx=(0, 6))
        open_btn.bind("<Button-1>", lambda _e: self._locate_video(video_path))
        open_btn.bind("<Enter>", lambda _e: open_btn.config(fg=self.accent, highlightbackground=self.accent))
        open_btn.bind("<Leave>", lambda _e: open_btn.config(fg=self.muted, highlightbackground=self.border))

        card._name_lbl = name_lbl
        card._content_widgets = [left, right, name_lbl, meta_lbl, dir_lbl, btn_row,
                                  open_btn, score_bar_bg]

        def _enter(_e, vp=video_path):
            if vp not in self._selected_paths:
                card.config(highlightbackground=self.accent, highlightthickness=1)

        def _leave(_e, vp=video_path):
            if vp not in self._selected_paths:
                card.config(highlightbackground=self.border, highlightthickness=1)
            self._hide_thumbnail_tooltip()

        all_hover = [card, thumb_container, thumb_lbl, left, right, name_lbl,
                     meta_lbl, dir_lbl, btn_row, open_btn, score_bar_bg]
        for w in all_hover:
            w.bind("<Enter>", _enter)
            w.bind("<Leave>", _leave)

        select_targets = [card, thumb_container, thumb_lbl, left, right,
                          name_lbl, meta_lbl, dir_lbl, btn_row]
        for w in select_targets:
            w.bind("<Button-1>", lambda _e, vp=video_path: self._on_card_click(_e, vp))
            w.bind("<Button-3>", lambda _e, vp=video_path: self._on_card_right_click(_e, vp))
            w.bind("<Double-Button-1>", lambda _e, vp=video_path: self._play_video(vp))

        return card

    def _on_card_click(self, event, vp: str):
        self._claim_workspace_keyboard_focus(self._canvas)
        self._hide_thumbnail_tooltip()
        ctrl = bool(event.state & 0x4)
        shift = bool(event.state & 0x1)

        if shift and self._last_anchor_path and self._last_anchor_path in self._all_results:
            ai = self._all_results.index(self._last_anchor_path)
            bi = self._all_results.index(vp) if vp in self._all_results else 0
            start, end = min(ai, bi), max(ai, bi)
            self._selected_paths = set(self._all_results[start:end + 1])
            for path in self._all_results[start:end + 1]:
                self._update_card_selection(path)
        elif ctrl:
            if vp in self._selected_paths:
                self._selected_paths.discard(vp)
            else:
                self._selected_paths.add(vp)
            self._update_card_selection(vp)
        else:
            old = set(self._selected_paths)
            self._selected_paths = {vp}
            for op in old:
                if op != vp:
                    self._update_card_selection(op)
            self._update_card_selection(vp)
            self._last_anchor_path = vp

        self._update_selection_label()

    def _on_card_right_click(self, event, vp: str):
        if vp not in self._selected_paths:
            vpm = getattr(self._app, 'video_preview_manager', None)
            if vpm and hasattr(vpm, '_thumbnails'):
                vp_norm = os.path.normpath(vp)
                th = vpm._thumbnails.get(vp_norm)
                if th and hasattr(th, 'is_valid') and th.is_valid() and th.thumbnail_data:
                    if hasattr(vpm, 'tooltip'):
                        try:
                            vpm.tooltip.show_preview(vp, th.thumbnail_data,
                                                     event.x_root, event.y_root)
                        except Exception:
                            pass
                        return
                if hasattr(vpm, '_generate_thumbnail_async') and hasattr(vpm, '_lock'):
                    try:
                        with vpm._lock:
                            already = vp_norm in getattr(vpm, '_generation_queue', set())
                        if not already:
                            vpm._generate_thumbnail_async(vp_norm, event.x_root, event.y_root)
                    except Exception:
                        pass
            return
        self._show_context_menu(event, vp)

    def _update_card_selection(self, vp: str):
        card = self._card_frames.get(vp)
        if not card:
            return
        try:
            if not card.winfo_exists():
                return
        except Exception:
            return
        is_sel = vp in self._selected_paths
        bg = self.accent_dim if is_sel else card._orig_bg
        name_fg = self.accent if is_sel else self.text
        border_col = self.accent if is_sel else self.border
        border_w = 2 if is_sel else 1

        card.config(bg=bg, highlightbackground=border_col, highlightthickness=border_w)
        for w in getattr(card, '_content_widgets', []):
            try:
                w.config(bg=bg)
            except Exception:
                pass
        name_lbl = getattr(card, '_name_lbl', None)
        if name_lbl:
            try:
                name_lbl.config(fg=name_fg)
            except Exception:
                pass

    def _update_selection_label(self):
        if not self._sel_count_lbl:
            return
        try:
            if not self._sel_count_lbl.winfo_exists():
                return
            n = len(self._selected_paths)
            self._sel_count_lbl.config(
                text=f"{n} selected" if n > 0 else ""
            )
        except Exception:
            pass

    def _get_selected_videos(self) -> list:
        return [vp for vp in self._all_results if vp in self._selected_paths]

    def _select_all(self):
        for vp in self._all_results:
            self._selected_paths.add(vp)
            self._update_card_selection(vp)
        self._update_selection_label()

    def _clear_selection(self):
        old = set(self._selected_paths)
        self._selected_paths.clear()
        self._last_anchor_path = None
        for vp in old:
            self._update_card_selection(vp)
        self._update_selection_label()

    def _hide_thumbnail_tooltip(self):
        try:
            vpm = getattr(self._app, 'video_preview_manager', None)
            if vpm and hasattr(vpm, 'tooltip') and vpm.tooltip:
                if hasattr(vpm.tooltip, 'hide'):
                    vpm.tooltip.hide()
                elif hasattr(vpm.tooltip, 'hide_preview'):
                    vpm.tooltip.hide_preview()
        except Exception:
            pass

    def _make_context_menu(self):
        tp = getattr(self._app, 'theme_provider', None)
        if tp is None and hasattr(self._app, 'create_manager_context_menu'):
            tp = self._app
        if tp and hasattr(tp, 'create_manager_context_menu'):
            return tp.create_manager_context_menu(self._root)
        dark = getattr(self._app, 'dark_mode', False)
        bg = getattr(self._app, 'surface_color', '#1A1E26' if dark else '#FFFFFF')
        fg = getattr(self._app, 'text_color', '#E2E8F0' if dark else '#1E2A3A')
        hover = getattr(self._app, 'hover_color', '#252C38' if dark else '#EDF2F7')
        return tk.Menu(
            self._root, tearoff=0,
            bg=bg, fg=fg,
            activebackground=hover, activeforeground=fg,
            relief='flat', bd=1, font=('Segoe UI', 10),
        )

    def _show_context_menu(self, event, vp: str):
        if not self._selected_paths:
            return
        menu = self._make_context_menu()
        n = len(self._selected_paths)
        single = vp if n == 1 else None
        gvm = getattr(self._app, 'grid_view_manager', None)

        menu.add_command(
            label=f"▶  Play Selected  ({n})" if n > 1 else "▶  Play",
            command=self._play_selected,
        )

        menu.add_separator()
        menu.add_command(label="Select All", command=self._select_all)
        menu.add_command(label="Clear Selection", command=self._clear_selection)

        menu.add_separator()
        menu.add_command(label="Open in Gallery", command=self._open_in_gallery)

        menu.add_separator()
        menu.add_command(label="Add to Playlist", command=self._ctx_add_to_playlist)
        if gvm and gvm.is_favourite_callback:
            sel = list(self._selected_paths)
            all_fav = all(gvm.is_favourite_callback(v) for v in sel)
            if all_fav and gvm.remove_from_favourites_callback:
                menu.add_command(label="Remove from Favourites",
                                 command=self._ctx_remove_from_favourites)
            elif gvm.add_to_favourites_callback:
                menu.add_command(label="Add to Favourites",
                                 command=self._ctx_add_to_favourites)
        menu.add_command(label="Add to Queue", command=self._ctx_add_to_queue)

        if gvm:
            win1_slots = [s for s in (1, 2, 3)
                          if getattr(gvm, f'play_in_dual_player{s}_callback', None)]
            has_win2 = any(getattr(gvm, f'play_in_dual_player_win2_{s}_callback', None)
                           for s in (1, 2, 3))
            if win1_slots or has_win2:
                menu.add_separator()
            for slot in win1_slots:
                menu.add_command(
                    label=f"▶ Win 1 › Player {slot}",
                    command=lambda s=slot: self._ctx_dual_player(1, s),
                )
            if has_win2:
                menu.add_separator()
                for slot in (1, 2, 3):
                    if getattr(gvm, f'play_in_dual_player_win2_{slot}_callback', None):
                        menu.add_command(
                            label=f"▶ Win 2 › Player {slot}",
                            command=lambda s=slot: self._ctx_dual_player(2, s),
                        )

        if single and os.path.isfile(single):
            menu.add_separator()
            menu.add_command(label="Open File Location",
                             command=lambda: self._locate_video(single))
            menu.add_command(label="Properties",
                             command=lambda: self._ctx_properties(single))
            if hasattr(self._app, 'locate_in_directory_panel'):
                menu.add_command(label="Show in Panel",
                                 command=lambda: self._locate_video(single))

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _play_selected(self):
        videos = self._get_selected_videos()
        if videos:
            try:
                self._app._play_grid_videos(videos)
            except Exception as e:
                self._manager._log(f"AI Search play error: {e}")

    def _ctx_add_to_playlist(self):
        videos = self._get_selected_videos()
        if not videos:
            return
        gvm = getattr(self._app, 'grid_view_manager', None)
        if gvm and gvm.add_to_playlist_callback:
            gvm.add_to_playlist_callback(videos)
            return
        try:
            self._app.playlist_manager.add_videos_to_playlist_dialog(videos)
        except Exception:
            pass

    def _ctx_add_to_queue(self):
        videos = self._get_selected_videos()
        if videos:
            try:
                self._app.queue_manager.add_to_queue(videos, added_from="ai_search")
            except Exception as e:
                self._manager._log(f"AI Search queue error: {e}")

    def _ctx_add_to_favourites(self):
        videos = self._get_selected_videos()
        if not videos:
            return
        gvm = getattr(self._app, 'grid_view_manager', None)
        if gvm and gvm.add_to_favourites_callback:
            gvm.add_to_favourites_callback(videos)

    def _ctx_remove_from_favourites(self):
        videos = self._get_selected_videos()
        if not videos:
            return
        gvm = getattr(self._app, 'grid_view_manager', None)
        if gvm and gvm.remove_from_favourites_callback:
            gvm.remove_from_favourites_callback(videos)

    def _ctx_dual_player(self, win: int, slot: int):
        videos = self._get_selected_videos()
        if not videos:
            return
        gvm = getattr(self._app, 'grid_view_manager', None)
        if not gvm:
            return
        attr = (f"play_in_dual_player{slot}_callback" if win == 1
                else f"play_in_dual_player_win2_{slot}_callback")
        cb = getattr(gvm, attr, None)
        if cb:
            cb(videos)

    def _ctx_properties(self, fp: str):
        gvm = getattr(self._app, 'grid_view_manager', None)
        if gvm and gvm.show_properties_callback:
            gvm.show_properties_callback(fp)
            return
        try:
            from datetime import datetime as _dt
            si = os.stat(fp)
            info = (f"File: {os.path.basename(fp)}\n\n"
                    f"Path: {fp}\n\n"
                    f"Size: {si.st_size / (1024 * 1024):.2f} MB ({si.st_size:,} bytes)\n\n"
                    f"Modified: {_dt.fromtimestamp(si.st_mtime):%Y-%m-%d %H:%M:%S}\n\n")
            import tkinter.messagebox as _mb
            _mb.showinfo("Properties", info)
        except Exception:
            pass

    def _open_in_gallery(self):
        paths = self._get_selected_videos() or list(self._all_results)
        if not paths:
            return
        try:
            vpm = getattr(self._app, 'video_preview_manager', None)
            self._app.grid_view_manager.show_grid_view(paths, video_preview_manager=vpm)
        except Exception as e:
            self._manager._log(f"Open in gallery error: {e}")

    def _fetch_thumbnail_bg(self, vp: str, vp_norm: str, label: tk.Label):
        with self._thumb_semaphore:
            try:
                cached = self._photo_cache.get(vp_norm)
                if cached:
                    self._root.after(0, lambda lbl=label, p=cached: self._set_thumb_label(lbl, p))
                    return

                vpm = getattr(self._app, 'video_preview_manager', None)

                if vpm and hasattr(vpm, 'lru_cache'):
                    photo = vpm.lru_cache.get(vp_norm)
                    if photo:
                        self._photo_cache[vp_norm] = photo
                        self._root.after(0, lambda lbl=label, p=photo: self._set_thumb_label(lbl, p))
                        return

                pil_img = None

                if vpm and hasattr(vpm, '_thumbnails') and _PIL_OK:
                    th = vpm._thumbnails.get(vp_norm)
                    if th and hasattr(th, 'blob_path') and th.blob_path:
                        try:
                            if th.blob_path.exists():
                                pil_img = Image.open(str(th.blob_path)).convert("RGB")
                        except Exception:
                            pass

                if pil_img is None and _PIL_OK:
                    try:
                        import cv2
                        cap = cv2.VideoCapture(vp)
                        ret, frame = cap.read()
                        cap.release()
                        if ret and frame is not None:
                            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                            pil_img = Image.fromarray(frame_rgb)
                    except Exception:
                        pass

                if pil_img is None:
                    return

                sw, sh = pil_img.size
                scale = min(_THUMB_W / sw, _THUMB_H / sh)
                nw, nh = int(sw * scale), int(sh * scale)
                pil_img = pil_img.resize((nw, nh), Image.Resampling.LANCZOS)
                canvas = Image.new("RGB", (_THUMB_W, _THUMB_H), (11, 12, 17))
                canvas.paste(pil_img, ((_THUMB_W - nw) // 2, (_THUMB_H - nh) // 2))

                self._root.after(0, lambda img=canvas, lbl=label, p=vp_norm:
                self._apply_thumbnail(img, lbl, p))
            except Exception:
                pass

    def _apply_thumbnail(self, pil_img, label: tk.Label, vp_norm: str):
        if not _PIL_OK:
            return
        try:
            if not label.winfo_exists():
                return
            photo = ImageTk.PhotoImage(pil_img)
            self._photo_cache[vp_norm] = photo
            label.configure(image=photo, text="")
            label.image = photo
        except Exception:
            pass

    def _set_thumb_label(self, label: tk.Label, photo):
        try:
            if label.winfo_exists():
                label.configure(image=photo, text="")
                label.image = photo
        except Exception:
            pass

    def _score_color(self, score: float, max_score: float = 15.0) -> str:
        ratio = score / max(max_score, 0.01)
        if ratio >= 0.75:
            return "#34c98a"
        if ratio >= 0.50:
            return "#5E81F4"
        if ratio >= 0.25:
            return "#f5a623"
        return "#aaaaaa"

    def _claim_workspace_keyboard_focus(self, widget=None):
        keyboard_navigation.claim_workspace_focus(self._app, widget)

    def _setup_focus_ring(self):
        self.focus_ring = keyboard_navigation.FocusRing(
            container=self._frame,
            on_escape=self.focus_primary,
            accent_color=self.accent,
            border_color=self.border,
        )
        self.focus_ring.register(self.search_entry, 'search', activate=self._on_search_click)
        self.focus_ring.register(self._search_btn, 'search_btn', activate=self._on_search_click)
        self.focus_ring.register(self._index_btn, 'index_btn', activate=self._on_index_click)
        self.focus_ring.register(
            self._normal_mode_btn, 'mode_normal',
            activate=lambda: self._set_search_mode("normal"),
            right=lambda: self._set_search_mode("ai"),
        )
        self.focus_ring.register(
            self._advanced_mode_btn, 'mode_ai',
            activate=lambda: self._set_search_mode("ai"),
            left=lambda: self._set_search_mode("normal"),
        )
        self.focus_ring.register(self._canvas, 'results', activate=self._play_selected)
        self._canvas._no_focus_border = True
        self.search_entry.bind("<Escape>", lambda _e: self.focus_primary(), add="+")

    def cycle_focus_ring(self, reverse=False):
        if not keyboard_navigation.is_workspace_zone(self._app):
            return False
        return self.focus_ring.handle_ctrl_tab(reverse=reverse)

    def focus_primary(self):
        if self._canvas.winfo_exists():
            self._claim_workspace_keyboard_focus(self._canvas)

    def get_primary_widget(self):
        return self._canvas

    def open_context_menu_for_focused(self):
        vp = self._focus_path
        if not vp and self._selected_paths:
            vp = next(iter(self._selected_paths))
        if not vp or vp not in self._card_frames:
            return
        card = self._card_frames[vp]
        x = card.winfo_rootx() + card.winfo_width() // 2
        y = card.winfo_rooty() + card.winfo_height() // 2
        event = type('Event', (), {'x_root': x, 'y_root': y})()
        self._show_context_menu(event, vp)

    def show_preview_for_focused(self):
        vp = self._focus_path
        if not vp and self._selected_paths:
            if len(self._selected_paths) != 1:
                return
            vp = next(iter(self._selected_paths))
        if not vp or vp not in self._card_frames:
            return
        if not self.video_preview_manager:
            return
        card = self._card_frames[vp]
        x, y = keyboard_navigation.preview_coords_for_widget(card)
        self.video_preview_manager._show_video_preview(vp, x, y)

    def _setup_ai_search_keyboard_nav(self):
        keyboard_navigation.bind_keyboard_zone(
            self._frame, "workspace", self._app._set_keyboard_focus_zone)
        self._canvas.configure(takefocus=1)
        keyboard_navigation.bind_focus_target(self._canvas, self._canvas)
        for seq in ("<Up>", "<Down>", "<Return>", "<KP_Enter>"):
            self._canvas.bind(seq, self._on_ai_search_keyboard, add="+")
            self._frame.bind(seq, self._on_ai_search_keyboard, add="+")

    def handle_keyboard_nav(self, event):
        if not keyboard_navigation.is_workspace_zone(self._app):
            return False
        focused = self._frame.focus_get()
        if hasattr(self, 'focus_ring') and self.focus_ring.is_in_ring(focused):
            if focused is not self._canvas:
                return False
        if not self._all_results:
            return False
        return self._on_ai_search_keyboard(event) == "break"

    def _on_ai_search_keyboard(self, event):
        if not keyboard_navigation.is_workspace_zone(self._app):
            return
        keysym = event.keysym
        shift_held = bool(event.state & 0x1)

        if keysym in ("Return", "KP_Enter"):
            selected = self._get_selected_videos()
            if selected:
                self._play_video(selected[0])
            elif self._all_results:
                self._play_video(self._all_results[0])
            return "break"

        if keysym not in ("Up", "Down") or not self._all_results:
            return

        # Determine current focus index
        # Use self._focus_path if valid, else fallback to first selected, else first result
        current = self._focus_path
        if current is None or current not in self._all_results:
            if self._selected_paths:
                # pick the most recently added? We'll just take the first selected.
                current = next(iter(self._selected_paths))
            else:
                current = self._all_results[0]
        try:
            idx = self._all_results.index(current)
        except ValueError:
            idx = 0

        # Move one step
        if keysym == "Up":
            idx = max(0, idx - 1)
        else:
            idx = min(len(self._all_results) - 1, idx + 1)

        new_vp = self._all_results[idx]
        self._focus_path = new_vp  # always update focus

        if shift_held:
            # If no anchor exists, set it to the item we were on before moving
            if self._last_anchor_path is None or self._last_anchor_path not in self._all_results:
                self._last_anchor_path = current
            anchor = self._last_anchor_path
            try:
                a_idx = self._all_results.index(anchor)
                b_idx = idx
                start, end = min(a_idx, b_idx), max(a_idx, b_idx)
                self._selected_paths = set(self._all_results[start:end + 1])
                for path in self._all_results[start:end + 1]:
                    self._update_card_selection(path)
            except ValueError:
                return "break"
            # Do NOT update anchor here – keep it fixed
        else:
            # Without Shift, replace selection and update anchor
            old = set(self._selected_paths)
            self._selected_paths = {new_vp}
            for path in old:
                if path != new_vp:
                    self._update_card_selection(path)
            self._update_card_selection(new_vp)
            self._last_anchor_path = new_vp  # anchor follows the single selection

        self._update_selection_label()

        card = self._card_frames.get(new_vp)
        if card:
            keyboard_navigation.scroll_widget_into_view(self._canvas, card)
        return "break"

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
        self._indexing_dialog = IndexingDialog(self._root, self._app, self._manager)
        self._indexing_dialog.show()