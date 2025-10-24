"""
Central Resource Manager for Recursive Video Player
Handles cleanup of all resources, threads, and processes
"""
import os
import sys
import threading
import weakref
import atexit
import gc
import time
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from typing import List, Set, Dict, Any, Optional
import logging


class ResourceManager:
    """Centralized resource management and cleanup"""

    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return

        self._initialized = True
        self.logger = self._setup_logger()

        # Track all resources
        self._threads: Set[threading.Thread] = set()
        self._executors: List[Any] = []
        self._cleanup_callbacks: List[callable] = []
        self._temp_files: Set[str] = set()
        self._vlc_instances: List[weakref.ref] = []
        self._file_handles: List[Any] = []

        # Shutdown coordination
        self._shutdown = False
        self._shutdown_event = threading.Event()
        self._shutdown_lock = threading.RLock()

        # Register cleanup on exit
        atexit.register(self.cleanup_all)

        self.logger.info("ResourceManager initialized")

    def _setup_logger(self):
        """Setup logging for resource management"""
        logger = logging.getLogger('ResourceManager')
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def register_thread(self, thread: threading.Thread):
        """Register a thread for cleanup"""
        with self._lock:
            if not self._shutdown:
                self._threads.add(thread)
                self.logger.debug(f"Registered thread: {thread.name}")

    def unregister_thread(self, thread: threading.Thread):
        """Unregister a thread"""
        with self._lock:
            self._threads.discard(thread)
            self.logger.debug(f"Unregistered thread: {thread.name}")

    def register_executor(self, executor):
        """Register an executor for cleanup"""
        with self._lock:
            if not self._shutdown:
                self._executors.append(executor)
                self.logger.debug(f"Registered executor: {type(executor).__name__}")

    def register_cleanup_callback(self, callback: callable):
        """Register a cleanup callback"""
        with self._lock:
            if not self._shutdown:
                self._cleanup_callbacks.append(callback)

    def register_temp_file(self, filepath: str):
        """Register a temporary file for cleanup"""
        with self._lock:
            if not self._shutdown:
                self._temp_files.add(filepath)

    def unregister_temp_file(self, filepath: str):
        """Unregister a temporary file"""
        with self._lock:
            self._temp_files.discard(filepath)

    def register_vlc_instance(self, instance):
        """Register a VLC instance for cleanup"""
        with self._lock:
            if not self._shutdown:
                self._vlc_instances.append(weakref.ref(instance))

    def register_file_handle(self, handle):
        """Register a file handle for cleanup"""
        with self._lock:
            if not self._shutdown:
                self._file_handles.append(handle)

    def is_shutting_down(self) -> bool:
        """Check if shutdown is in progress"""
        return self._shutdown_event.is_set()

    def cleanup_threads(self, timeout_per_thread: float = 2.0):
        """Cleanup all registered threads with graceful shutdown"""
        with self._lock:
            threads = list(self._threads)

        if not threads:
            return

        self.logger.info(f"Cleaning up {len(threads)} threads...")

        # Signal shutdown to all threads
        self._shutdown_event.set()

        # Give threads time to finish gracefully
        time.sleep(0.5)

        # Join each thread individually with timeout
        for thread in threads:
            try:
                if thread.is_alive():
                    thread.join(timeout=timeout_per_thread)
                    if thread.is_alive():
                        self.logger.warning(
                            f"Thread {thread.name} did not stop after {timeout_per_thread}s timeout"
                        )
            except Exception as e:
                self.logger.error(f"Error cleaning up thread {thread.name}: {e}")

        with self._lock:
            self._threads.clear()

    def cleanup_executors(self):
        """Cleanup all registered executors gracefully"""
        if not self._executors:
            return

        self.logger.info(f"Cleaning up {len(self._executors)} executors...")

        for executor in self._executors:
            try:
                # First try graceful shutdown
                executor.shutdown(wait=False, cancel_futures=False)

                # Wait a bit for tasks to complete
                time.sleep(0.5)

            except Exception as e:
                self.logger.error(f"Error shutting down executor: {e}")
                try:
                    # Force shutdown as fallback
                    executor.shutdown(wait=False, cancel_futures=True)
                except:
                    pass

        self._executors.clear()

    def cleanup_temp_files(self):
        """Cleanup all temporary files"""
        import os

        if not self._temp_files:
            return

        self.logger.info(f"Cleaning up {len(self._temp_files)} temp files...")

        for filepath in list(self._temp_files):
            try:
                if os.path.exists(filepath):
                    os.unlink(filepath)
            except Exception as e:
                self.logger.error(f"Error deleting temp file {filepath}: {e}")

        self._temp_files.clear()

    def cleanup_vlc_instances(self):
        """Cleanup all VLC instances"""
        if not self._vlc_instances:
            return

        self.logger.info("Cleaning up VLC instances...")

        # Wait a moment for VLC to finish any pending operations
        time.sleep(0.3)

        for ref in self._vlc_instances:
            try:
                instance = ref()
                if instance:
                    try:
                        # Stop playback first
                        if hasattr(instance, 'stop'):
                            instance.stop()
                        time.sleep(0.1)
                    except:
                        pass

                    # Then release
                    try:
                        instance.release()
                    except:
                        pass
            except Exception as e:
                self.logger.error(f"Error releasing VLC instance: {e}")

        self._vlc_instances.clear()

    def cleanup_file_handles(self):
        """Cleanup all file handles"""
        if not self._file_handles:
            return

        self.logger.info(f"Cleaning up {len(self._file_handles)} file handles...")

        for handle in self._file_handles:
            try:
                if hasattr(handle, 'close') and not getattr(handle, 'closed', False):
                    handle.close()
            except Exception as e:
                self.logger.error(f"Error closing file handle: {e}")

        self._file_handles.clear()

    def run_cleanup_callbacks(self):
        """Run all registered cleanup callbacks"""
        if not self._cleanup_callbacks:
            return

        self.logger.info(f"Running {len(self._cleanup_callbacks)} cleanup callbacks...")

        for callback in self._cleanup_callbacks:
            try:
                callback()
            except Exception as e:
                self.logger.error(f"Error in cleanup callback: {e}")

        self._cleanup_callbacks.clear()

    def force_garbage_collection(self):
        """Force garbage collection (single pass)"""
        self.logger.debug("Running garbage collection...")
        collected = gc.collect()
        self.logger.debug(f"Collected {collected} objects")

    def cleanup_all(self):
        with self._shutdown_lock:
            if self._shutdown:
                return
            self._shutdown = True

        self.logger.info("Starting complete resource cleanup...")

        try:
            self.run_cleanup_callbacks()
            self.cleanup_vlc_instances()

            self.cleanup_threads(timeout_per_thread=1.0)

            self.cleanup_executors()
            self.cleanup_file_handles()
            self.cleanup_temp_files()
            self.force_garbage_collection()

            time.sleep(0.1)
            self.force_garbage_collection()

        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")

        self.logger.info("Resource cleanup complete")

        try:
            sys.exit(0)
        except:
            os._exit(0)

    def is_shutdown(self) -> bool:
        """Check if shutdown is in progress"""
        with self._shutdown_lock:
            return self._shutdown


class ManagedThread(threading.Thread):
    """Thread that auto-registers with ResourceManager and checks shutdown signal"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.daemon = True
        self._resource_manager = ResourceManager()
        self._resource_manager.register_thread(self)

    def should_stop(self) -> bool:
        """Check if thread should stop"""
        return self._resource_manager.is_shutting_down()

    def run(self):
        try:
            super().run()
        finally:
            self._resource_manager.unregister_thread(self)


class ManagedExecutor:
    """Wrapper for executors with auto-registration"""

    def __init__(self, executor_class, *args, **kwargs):
        self.executor = executor_class(*args, **kwargs)
        ResourceManager().register_executor(self.executor)

    def __getattr__(self, name):
        return getattr(self.executor, name)

    def shutdown(self, wait=True, cancel_futures=False):
        self.executor.shutdown(wait=wait, cancel_futures=cancel_futures)


class ThreadSafeDict:
    """Thread-safe dictionary with proper locking"""

    def __init__(self):
        self._dict = {}
        self._lock = threading.RLock()

    def get(self, key, default=None):
        with self._lock:
            return self._dict.get(key, default)

    def set(self, key, value):
        with self._lock:
            self._dict[key] = value

    def delete(self, key):
        with self._lock:
            if key in self._dict:
                del self._dict[key]

    def clear(self):
        with self._lock:
            self._dict.clear()

    def __len__(self):
        with self._lock:
            return len(self._dict)

    def __contains__(self, key):
        with self._lock:
            return key in self._dict

    def keys(self):
        with self._lock:
            return list(self._dict.keys())

    def values(self):
        with self._lock:
            return list(self._dict.values())

    def items(self):
        with self._lock:
            return list(self._dict.items())


class MemoryMonitor:
    """Monitor memory usage and trigger cleanup if needed"""

    def __init__(self, threshold_mb: int = 1000):
        self.threshold_bytes = threshold_mb * 1024 * 1024
        self.logger = logging.getLogger('MemoryMonitor')

    def check_memory(self) -> bool:
        """Check if memory usage exceeds threshold"""
        try:
            import psutil
            process = psutil.Process()
            memory_info = process.memory_info()

            if memory_info.rss > self.threshold_bytes:
                self.logger.warning(
                    f"Memory usage ({memory_info.rss / 1024 / 1024:.1f} MB) "
                    f"exceeds threshold ({self.threshold_bytes / 1024 / 1024:.1f} MB)"
                )
                return True
        except ImportError:
            pass

        return False

    def cleanup_if_needed(self):
        """Trigger cleanup if memory usage is high"""
        if self.check_memory():
            self.logger.info("Triggering garbage collection due to high memory usage")
            gc.collect()


# Singleton instance
_resource_manager = ResourceManager()


def get_resource_manager() -> ResourceManager:
    """Get the global ResourceManager instance"""
    return _resource_manager