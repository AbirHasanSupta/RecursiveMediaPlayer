import base64
import threading
import tkinter as tk
from tkinter import ttk
from tkinter.font import Font


class ThemePreferencesMixin:
    def save_preferences(self):
        if self._save_timer is not None:
            try:
                self.root.after_cancel(self._save_timer)
            except Exception:
                pass
        self._save_timer = self.root.after(300, self._do_save_preferences)

    def _do_save_preferences(self):
        self._save_timer = None

        encoded_excluded_subdirs = {}
        for root_dir, subdirs in getattr(self, 'excluded_subdirs', {}).items():
            encoded_root = base64.b64encode(root_dir.encode()).decode()
            encoded_subdirs = [base64.b64encode(s.encode()).decode() for s in subdirs]
            encoded_excluded_subdirs[encoded_root] = encoded_subdirs

        encoded_excluded_videos = {}
        for root_dir, videos in getattr(self, 'excluded_videos', {}).items():
            encoded_root = base64.b64encode(root_dir.encode()).decode()
            encoded_videos = [base64.b64encode(v.encode()).decode() for v in videos]
            encoded_excluded_videos[encoded_root] = encoded_videos

        prefs = {
            'dark_mode': self.dark_mode,
            'show_videos': self.show_videos,
            'expand_all': False,
            'selected_dirs': [
                d for d in getattr(self, 'selected_dirs', [])
                if isinstance(d, str)
                   and not d.startswith('gdrive://')
                   and not d.startswith('http://')
                   and not d.startswith('https://')
            ],
            'save_directories': True,
            'start_from_last_played': getattr(self, 'start_from_last_played', False),
            'smart_resume_enabled': getattr(self, 'smart_resume_enabled', False),
            'last_played_video_index': getattr(self, 'last_played_video_index', 0),
            'last_played_video_path': getattr(self, 'last_played_video_path', ''),
            'excluded_subdirs': encoded_excluded_subdirs,
            'excluded_videos': encoded_excluded_videos,
            'volume': getattr(self, 'volume', 50),
            'is_muted': getattr(self, 'is_muted', False),
            'loop_mode': getattr(self, 'loop_mode', 'loop_on'),
            'show_console': getattr(self, 'show_console', False),
        }
        threading.Thread(target=self.config.save, args=(prefs,), daemon=True).start()

