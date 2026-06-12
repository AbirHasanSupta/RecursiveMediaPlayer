from __future__ import annotations

import threading
import time
from typing import Callable, Optional

try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _requests = None
    _REQUESTS_OK = False


class AIServerBridge:
    _POLL_INTERVAL = 1.0
    _POLL_TIMEOUT  = 30

    def __init__(
        self,
        base_url: str,
        root=None,
        logger: Callable = None,
        on_ready_callback: Callable = None,
    ):
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._root = root
        self._log = logger or (lambda msg: None)
        self._on_ready_cb = on_ready_callback

        self._lock = threading.Lock()
        self._ready = False
        self._alive = False

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, timeout: float = 5.0):
        if not _REQUESTS_OK:
            raise RuntimeError("'requests' package not installed")
        return _requests.get(f"{self._base_url}{path}", timeout=timeout)

    def _post(self, path: str, payload: dict, timeout: float = 30.0):
        if not _REQUESTS_OK:
            raise RuntimeError("'requests' package not installed")
        return _requests.post(f"{self._base_url}{path}", json=payload, timeout=timeout)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        if not self._base_url:
            self._log("[bridge] no server URL configured")
            return False
        if not _REQUESTS_OK:
            self._log("[bridge] 'requests' not installed")
            return False

        with self._lock:
            self._ready = False
            self._alive = False

        threading.Thread(target=self._poll_until_ready, daemon=True).start()
        return True

    def _poll_until_ready(self):
        deadline = time.monotonic() + self._POLL_TIMEOUT
        while time.monotonic() < deadline:
            try:
                resp = self._get("/status", timeout=3.0)
                data = resp.json()
                status = data.get("status")

                if status == "ready":
                    device = data.get("device", "unknown")
                    video_count = data.get("video_count", 0)
                    self._log(f"[bridge] ready · {video_count} videos · device={device}")
                    with self._lock:
                        self._ready = True
                        self._alive = True
                    self._fire_callback({"status": "ready", "device": device, "video_count": video_count})
                    return

                elif status == "no_index":
                    self._log("[bridge] server running — no index found")
                    with self._lock:
                        self._alive = True
                        self._ready = False
                    self._fire_callback({"status": "no_index"})
                    return

            except Exception:
                pass

            time.sleep(self._POLL_INTERVAL)

        self._log("[bridge] timed out waiting for AI server")
        self._fire_callback({"status": "error", "error": "connection timeout"})

    def _fire_callback(self, msg: dict):
        if self._on_ready_cb:
            if self._root:
                self._root.after(0, self._on_ready_cb, msg)
            else:
                self._on_ready_cb(msg)

    # ------------------------------------------------------------------
    # Search (original semantic + new AI-powered)
    # ------------------------------------------------------------------

    def query(
        self,
        text: str,
        directory_filter: str = None,
        top_k: int = 20,
        callback: Callable = None,
    ):
        """Original semantic search using /search endpoint."""
        if not self.is_ready():
            if callback:
                self._deliver(callback, {"error": "bridge not ready", "results": [], "counts": {}, "scores": {}})
            return

        payload = {"query": text, "top_k": top_k}
        if directory_filter:
            payload["directory"] = directory_filter

        def _worker():
            try:
                resp = self._post("/search", payload, timeout=60.0)
                result = resp.json()
            except Exception as exc:
                result = {"error": str(exc), "results": [], "counts": {}, "scores": {}}
            if callback:
                self._deliver(callback, result)

        threading.Thread(target=_worker, daemon=True).start()

    def ai_query(
        self,
        text: str,
        directory_filter: str = None,
        top_k: int = 10,
        callback: Callable = None,
    ):
        """
        AI-powered natural language query – uses /search/ai.
        Handles metadata filters, sorting, content search, etc.
        """
        if not self.is_ready():
            if callback:
                self._deliver(callback, {"error": "bridge not ready", "results": [], "counts": {}, "scores": {}})
            return

        payload = {"query": text, "top_k": top_k}
        if directory_filter:
            payload["directory"] = directory_filter

        def _worker():
            try:
                resp = self._post("/search/ai", payload, timeout=60.0)
                result = resp.json()
            except Exception as exc:
                result = {"error": str(exc), "results": [], "counts": {}, "scores": {}}
            if callback:
                self._deliver(callback, result)

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Preprocessing
    # ------------------------------------------------------------------

    def start_preprocessing(self, payload: dict, progress_cb: Callable, done_cb: Callable):
        def _worker():
            try:
                resp = self._post("/index/start", payload, timeout=10.0)
                data = resp.json()
                if data.get("status") not in ("started", "already_running"):
                    _done(False, data.get("error") or "server refused /index/start")
                    return
            except Exception as exc:
                _done(False, str(exc))
                return

            consecutive_errors = 0
            while True:
                time.sleep(0.5)
                try:
                    resp = self._get("/index/status", timeout=8.0)
                    data = resp.json()
                    consecutive_errors = 0
                except Exception:
                    consecutive_errors += 1
                    if consecutive_errors > 20:
                        _done(False, "lost connection to AI server during indexing")
                        return
                    continue

                for line in data.get("lines", []):
                    if progress_cb:
                        _line = line
                        if self._root:
                            self._root.after(0, progress_cb, _line)
                        else:
                            progress_cb(_line)

                if data.get("done"):
                    _done(data.get("success", False), data.get("error"))
                    return

        def _done(success: bool, error=None):
            if done_cb:
                if self._root:
                    self._root.after(0, lambda s=success, e=error: done_cb(success=s, error=e))
                else:
                    done_cb(success=success, error=error)

        threading.Thread(target=_worker, daemon=True).start()

    def cancel_preprocessing(self):
        def _worker():
            try:
                self._post("/index/cancel", {}, timeout=10.0)
            except Exception as exc:
                self._log(f"[bridge] cancel_preprocessing error: {exc}")

        threading.Thread(target=_worker, daemon=True).start()

    def reload_searcher(self, index_dir: str = "", on_done: Callable = None):
        def _worker():
            try:
                resp = self._post("/index/reload", {"out_dir": index_dir}, timeout=60.0)
                data = resp.json()
                if data.get("status") == "reloaded":
                    with self._lock:
                        self._ready = True
                        self._alive = True
                if on_done:
                    if self._root:
                        self._root.after(0, on_done, data)
                    else:
                        on_done(data)
            except Exception as exc:
                self._log(f"[bridge] reload_searcher error: {exc}")

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def is_ready(self) -> bool:
        with self._lock:
            return self._ready

    def is_alive(self) -> bool:
        with self._lock:
            return self._alive

    def disconnect(self):
        with self._lock:
            self._ready = False
            self._alive = False
        self._log("[bridge] disconnected from AI server")

    def _deliver(self, callback: Callable, value):
        if self._root:
            self._root.after(0, callback, value)
        else:
            callback(value)


class AIPreprocessorBridge:
    def __init__(self, get_bridge_fn: Callable, root=None, logger: Callable = None):
        self._get_bridge = get_bridge_fn
        self._root = root
        self._log = logger or (lambda m: None)

    def start_preprocessing(self, videos_dir: str, settings, progress_cb: Callable, done_cb: Callable):
        bridge = self._get_bridge()
        if bridge is None or not bridge.is_alive():
            msg = "AI server is not connected — provide a valid URL in Settings and try again"
            self._log(f"[preprocessor] {msg}")
            if self._root:
                self._root.after(0, lambda: done_cb(success=False, error=msg))
            else:
                done_cb(success=False, error=msg)
            return

        payload = {
            "videos_dir": videos_dir,
            "out_dir":    settings.ai_index_path,
            "workers":    settings.preprocessing_workers,
            "max_frames": settings.max_frames_per_video,
            "incremental":   settings.incremental_preprocessing,
            "force_rebuild": not settings.incremental_preprocessing,
            "exclude_dirs":  getattr(settings, "excluded_index_dirs", "raw"),
        }
        self._log(f"[bridge] start_preprocessing payload: {payload}")
        bridge.start_preprocessing(payload, progress_cb, done_cb)

    def cancel(self):
        bridge = self._get_bridge()
        if bridge:
            bridge.cancel_preprocessing()