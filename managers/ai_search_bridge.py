from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional


class AISearchBridge:
    def __init__(self, index_dir: str, root=None, logger=None, on_ready_callback=None):
        self._index_dir = index_dir
        self._root = root
        self._log = logger or (lambda msg: None)
        self._on_ready_cb = on_ready_callback
        self._process: Optional[subprocess.Popen] = None
        self._ready = False
        self._lock = threading.Lock()
        self._pending: dict[int, Callable] = {}
        self._query_counter = 0
        self._reader_thread: Optional[threading.Thread] = None

    def _resolve_ai_executable(self) -> list:
        base = Path(sys.executable).parent
        sidecar = base / "ai_search.exe"
        if sidecar.exists():
            return [str(sidecar)]
        script = Path(__file__).parent.parent / "enhanced_model.py"
        if script.exists():
            return [sys.executable, str(script)]
        raise FileNotFoundError("AI search executable not found")

    def start(self) -> bool:
        if self._process and self._process.poll() is None:
            return True
        try:
            cmd = self._resolve_ai_executable() + [
                "--mode", "search",
                "--keep_alive",
                "--out_dir", self._index_dir,
            ]
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self._ready = False
            self._reader_thread = threading.Thread(
                target=self._reader_loop, daemon=True
            )
            self._reader_thread.start()

            stderr_thread = threading.Thread(
                target=self._stderr_loop, daemon=True
            )
            stderr_thread.start()
            return True
        except Exception as e:
            self._log(f"AISearchBridge start error: {e}")
            return False

    def _reader_loop(self):
        try:
            for raw in self._process.stdout:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    self._log(f"[bridge] non-JSON stdout: {raw}")
                    continue

                if msg.get("status") == "ready":
                    self._ready = True
                    self._log(
                        f"[bridge] ready · {msg.get('video_count', '?')} videos · "
                        f"device={msg.get('device', '?')}"
                    )
                    if self._on_ready_cb:
                        _cb, _msg = self._on_ready_cb, msg
                        if self._root:
                            self._root.after(0, _cb, _msg)
                        else:
                            _cb(_msg)
                    continue

                qid = msg.get("_qid")
                cb = None
                with self._lock:
                    if qid is not None:
                        cb = self._pending.pop(qid, None)

                if cb:
                    if self._root:
                        self._root.after(0, cb, msg)
                    else:
                        cb(msg)
        except Exception as e:
            self._log(f"[bridge] reader error: {e}")
            self._ready = False

    def _stderr_loop(self):
        try:
            for line in self._process.stderr:
                line = line.strip()
                if line:
                    self._log(f"[ai_model] {line}")
        except Exception:
            pass

    def query(
        self,
        text: str,
        directory_filter: str = None,
        top_k: int = 20,
        callback: Callable = None,
    ):
        if not self._process or self._process.poll() is not None:
            if callback:
                err = {"error": "bridge not running", "results": [], "counts": {}, "scores": {}}
                if self._root:
                    self._root.after(0, callback, err)
                else:
                    callback(err)
            return

        with self._lock:
            self._query_counter += 1
            qid = self._query_counter
            if callback:
                self._pending[qid] = callback

        payload = {"query": text, "top_k": top_k, "_qid": qid}
        if directory_filter:
            payload["directory"] = directory_filter

        try:
            line = json.dumps(payload) + "\n"
            self._process.stdin.write(line)
            self._process.stdin.flush()
        except Exception as e:
            self._log(f"[bridge] write error: {e}")
            with self._lock:
                self._pending.pop(qid, None)
            if callback:
                err = {"error": str(e), "results": [], "counts": {}, "scores": {}}
                if self._root:
                    self._root.after(0, callback, err)
                else:
                    callback(err)

    def is_ready(self) -> bool:
        return self._ready and bool(self._process) and self._process.poll() is None

    def stop(self):
        self._ready = False
        if self._process:
            try:
                self._process.stdin.write(json.dumps({"quit": True}) + "\n")
                self._process.stdin.flush()
            except Exception:
                pass
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None


class AIPreprocessor:
    def __init__(self, logger=None):
        self._log = logger or (lambda msg: None)
        self._process: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None

    def _resolve_script(self) -> list:
        base = Path(sys.executable).parent
        sidecar = base / "ai_search.exe"
        if sidecar.exists():
            return [str(sidecar)]
        script = Path(__file__).parent.parent / "enhanced_model.py"
        if script.exists():
            return [sys.executable, str(script)]
        raise FileNotFoundError("AI search executable not found")

    def start_preprocessing(
        self,
        videos_dir: str,
        settings,
        progress_cb: Callable,
        done_cb: Callable,
    ):
        if self._process and self._process.poll() is None:
            return

        try:
            cmd = self._resolve_script() + [
                "--mode", "preprocess",
                "--videos_dir", videos_dir,
                "--out_dir", settings.ai_index_path,
                "--workers", str(settings.preprocessing_workers),
                "--max_frames", str(settings.max_frames_per_video),
            ]
            if settings.incremental_preprocessing:
                cmd.append("--incremental")
            else:
                cmd.append("--force_rebuild")

            excluded = getattr(settings, 'excluded_index_dirs', '').strip()
            if excluded:
                cmd += ['--exclude_dirs', excluded]

            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self._thread = threading.Thread(
                target=self._stream_output,
                args=(progress_cb, done_cb),
                daemon=True,
            )
            self._thread.start()
        except Exception as e:
            self._log(f"AIPreprocessor start error: {e}")
            done_cb(success=False, error=str(e))

    def _stream_output(self, progress_cb: Callable, done_cb: Callable):
        try:
            for line in self._process.stdout:
                line = line.strip()
                if line:
                    progress_cb(line)
            return_code = self._process.wait()
            done_cb(success=(return_code == 0), error=None if return_code == 0 else f"exit {return_code}")
        except Exception as e:
            self._log(f"AIPreprocessor stream error: {e}")
            done_cb(success=False, error=str(e))

    def cancel(self):
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
        self._process = None