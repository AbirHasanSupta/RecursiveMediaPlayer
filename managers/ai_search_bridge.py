from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _requests = None  # type: ignore
    _REQUESTS_OK = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_free_port(start: int = 8000, attempts: int = 10) -> int:
    """Return the first free TCP port starting from *start*."""
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start  # fall back; polling will catch the error


# ---------------------------------------------------------------------------
# AIServerBridge
# ---------------------------------------------------------------------------

class AIServerBridge:
    """
    Manages the ``enhanced_model.py --mode server`` sidecar process and
    communicates with it exclusively via HTTP (FastAPI on localhost).

    Handles:
      - Search  →  POST /search
      - Preprocessing  →  POST /index/start  +  GET /index/status  +  POST /index/cancel
      - Reload  →  POST /index/reload   (after new index is built)

    Public API surface is intentionally identical to the old AISearchBridge so
    that AISearchManager needs only a one-line import change.
    """

    _POLL_INTERVAL = 1.0   # seconds between /status polls while waiting for readiness
    _POLL_TIMEOUT  = 300   # max seconds to wait for server to become ready

    def __init__(
        self,
        index_dir: str,
        root=None,
        logger: Callable = None,
        on_ready_callback: Callable = None,
    ):
        self._index_dir = index_dir
        self._root = root
        self._log = logger or (lambda msg: None)
        self._on_ready_cb = on_ready_callback

        self._process: Optional[subprocess.Popen] = None
        self._port: int = 0
        self._base_url: str = ""

        self._lock = threading.Lock()
        self._ready = False   # index is loaded → search works
        self._alive = False   # server process is up → preprocessing works

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _resolve_ai_executable(self) -> list:
        base = Path(sys.executable).parent
        sidecar = base / "ai_search.exe"
        if sidecar.exists():
            return [str(sidecar)]
        script = Path(__file__).parent.parent / "enhanced_model.py"
        if script.exists():
            return [sys.executable, str(script)]
        raise FileNotFoundError("AI search executable not found")

    def _get(self, path: str, timeout: float = 5.0):
        if not _REQUESTS_OK:
            raise RuntimeError("'requests' package not installed")
        return _requests.get(f"{self._base_url}{path}", timeout=timeout)

    def _post(self, path: str, payload: dict, timeout: float = 30.0):
        if not _REQUESTS_OK:
            raise RuntimeError("'requests' package not installed")
        return _requests.post(
            f"{self._base_url}{path}", json=payload, timeout=timeout
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Spawn the server subprocess and begin background readiness polling."""
        if self._process and self._process.poll() is None:
            return True

        if not _REQUESTS_OK:
            self._log("[bridge] 'requests' not installed — cannot use HTTP bridge")
            return False

        try:
            self._port = _find_free_port(8000)
            self._base_url = f"http://127.0.0.1:{self._port}"

            cmd = self._resolve_ai_executable() + [
                "--mode", "server",
                "--host", "127.0.0.1",
                "--port", str(self._port),
                "--out_dir", self._index_dir,
            ]

            self._log(f"[bridge] starting AI server on port {self._port}…")
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with self._lock:
                self._ready = False
                self._alive = False

            threading.Thread(target=self._poll_until_ready, daemon=True).start()
            return True

        except Exception as exc:
            self._log(f"[bridge] start error: {exc}")
            return False

    def _poll_until_ready(self):
        """Background thread: poll GET /status until ready, no_index, or timeout."""
        deadline = time.monotonic() + self._POLL_TIMEOUT

        while time.monotonic() < deadline:
            # Detect subprocess crash
            if self._process and self._process.poll() is not None:
                self._log("[bridge] AI server process exited unexpectedly")
                return

            try:
                resp = self._get("/status", timeout=3.0)
                data = resp.json()
                status = data.get("status")

                if status == "ready":
                    device      = data.get("device", "unknown")
                    video_count = data.get("video_count", 0)
                    self._log(
                        f"[bridge] ready · {video_count} videos · device={device}"
                    )
                    with self._lock:
                        self._ready = True
                        self._alive = True
                    self._fire_callback(
                        {"status": "ready", "device": device,
                         "video_count": video_count}
                    )
                    return

                elif status == "no_index":
                    # Server is up but no index loaded yet — preprocessing is possible
                    self._log("[bridge] server running — no index found")
                    with self._lock:
                        self._alive = True
                        self._ready = False
                    self._fire_callback({"status": "no_index"})
                    return

            except Exception:
                pass  # server not yet listening — keep polling

            time.sleep(self._POLL_INTERVAL)

        self._log("[bridge] timed out waiting for AI server")

    def _fire_callback(self, msg: dict):
        if self._on_ready_cb:
            if self._root:
                self._root.after(0, self._on_ready_cb, msg)
            else:
                self._on_ready_cb(msg)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def query(
        self,
        text: str,
        directory_filter: str = None,
        top_k: int = 20,
        callback: Callable = None,
    ):
        """Fire-and-forget HTTP search; result delivered to *callback*."""
        if not self.is_ready():
            if callback:
                err = {
                    "error": "bridge not ready",
                    "results": [], "counts": {}, "scores": {},
                }
                self._deliver(callback, err)
            return

        payload: dict = {"query": text, "top_k": top_k}
        if directory_filter:
            payload["directory"] = directory_filter

        def _worker():
            try:
                resp   = self._post("/search", payload, timeout=60.0)
                result = resp.json()
            except Exception as exc:
                result = {
                    "error": str(exc),
                    "results": [], "counts": {}, "scores": {},
                }
            if callback:
                self._deliver(callback, result)

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Preprocessing  (all via /index/* HTTP endpoints)
    # ------------------------------------------------------------------

    def start_preprocessing(
        self,
        payload: dict,
        progress_cb: Callable,
        done_cb: Callable,
    ):
        """
        POST /index/start with *payload*, then poll GET /index/status until done.
        Progress lines are delivered to *progress_cb*; *done_cb(success, error)*
        is called when finished.
        """
        def _worker():
            # 1. Kick off preprocessing on the server
            try:
                resp = self._post("/index/start", payload, timeout=10.0)
                data = resp.json()
                if data.get("status") not in ("started", "already_running"):
                    _done(False, data.get("error") or "server refused /index/start")
                    return
            except Exception as exc:
                _done(False, str(exc))
                return

            # 2. Poll for progress until done
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
                    self._root.after(
                        0, lambda s=success, e=error: done_cb(success=s, error=e)
                    )
                else:
                    done_cb(success=success, error=error)

        threading.Thread(target=_worker, daemon=True).start()

    def cancel_preprocessing(self):
        """POST /index/cancel to terminate the server-side subprocess."""
        def _worker():
            try:
                self._post("/index/cancel", {}, timeout=10.0)
            except Exception as exc:
                self._log(f"[bridge] cancel_preprocessing error: {exc}")

        threading.Thread(target=_worker, daemon=True).start()

    def reload_searcher(self, on_done: Callable = None):
        """
        POST /index/reload — tell the server to load the newly built index
        into memory without restarting the process.
        """
        def _worker():
            try:
                resp = self._post(
                    "/index/reload",
                    {"out_dir": self._index_dir},
                    timeout=60.0,
                )
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
    # Status / teardown
    # ------------------------------------------------------------------

    def is_ready(self) -> bool:
        """True when the index is loaded and search is available."""
        with self._lock:
            return (
                self._ready
                and bool(self._process)
                and self._process.poll() is None
            )

    def is_alive(self) -> bool:
        """True when the server process is running (even with no index loaded)."""
        with self._lock:
            return (
                self._alive
                and bool(self._process)
                and self._process.poll() is None
            )

    def stop(self):
        with self._lock:
            self._ready = False
            self._alive = False
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        self._log("[bridge] AI server stopped")

    def _deliver(self, callback: Callable, value):
        if self._root:
            self._root.after(0, callback, value)
        else:
            callback(value)


# ---------------------------------------------------------------------------
# AIPreprocessorBridge
# ---------------------------------------------------------------------------

class AIPreprocessorBridge:
    """
    HTTP-backed drop-in replacement for the old AIPreprocessor subprocess class.

    AIIndexingDialog calls::

        manager._preprocessor.start_preprocessing(
            videos_dir=..., settings=..., progress_cb=..., done_cb=...
        )
        manager._preprocessor.cancel()

    This class presents exactly that interface but routes everything through
    AIServerBridge HTTP calls, so the dialog itself needs zero changes.
    """

    def __init__(
        self,
        get_bridge_fn: Callable,
        root=None,
        logger: Callable = None,
    ):
        self._get_bridge = get_bridge_fn  # callable → AIServerBridge | None
        self._root = root
        self._log = logger or (lambda m: None)

    def start_preprocessing(
        self,
        videos_dir: str,
        settings,
        progress_cb: Callable,
        done_cb: Callable,
    ):
        bridge = self._get_bridge()
        if bridge is None or not bridge.is_alive():
            msg = (
                "AI server is not running yet — "
                "please wait for it to start, then try again"
            )
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
        bridge.start_preprocessing(payload, progress_cb, done_cb)

    def cancel(self):
        bridge = self._get_bridge()
        if bridge:
            bridge.cancel_preprocessing()