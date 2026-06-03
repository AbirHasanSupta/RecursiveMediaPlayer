import json
import os
import os.path
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import base64
from mixin.theme_core import ThemeCoreMixin
from mixin.theme_directory import ThemeDirectoryMixin
from mixin.theme_managers import ThemeManagerMixin
from mixin.theme_preferences import ThemePreferencesMixin
from mixin.theme_toolbar import ThemeToolbarMixin


def _get_app_dirs():
    APP = "Recursive Media Player"
    if os.name == "nt":
        settings = Path(os.environ.get("APPDATA",  Path.home() / "AppData" / "Roaming")) / APP
        local    = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))  / APP
    elif sys.platform == "darwin":
        settings = Path.home() / "Library" / "Application Support" / APP
        local    = Path.home() / "Library" / "Caches" / APP
    else:
        settings = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP
        local    = Path(os.environ.get("XDG_CACHE_HOME",  Path.home() / ".cache"))  / APP
    return settings, local


class ConfigHandler:

    def __init__(self):
        self._config_path = None

    @property
    def config_path(self):
        if self._config_path is None:
            config_dir, _ = _get_app_dirs()
            config_dir.mkdir(parents=True, exist_ok=True)
            self._config_path = config_dir / "config.json"
        return self._config_path

    def load_preferences(self):
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r') as f:
                    config = json.load(f)

                    encoded_dirs = config.get('selected_dirs', [])
                    decoded_dirs = []
                    for ed in encoded_dirs:
                        try:
                            decoded_dirs.append(base64.b64decode(ed.encode()).decode())
                        except Exception:
                            pass
                    last_played_encoded = config.get('last_played_video_path', '')
                    try:
                        last_played_path = os.path.normpath(base64.b64decode(last_played_encoded.encode()).decode())
                    except Exception:
                        last_played_path = ''

                    encoded_excluded_subdirs = config.get('excluded_subdirs', {})
                    decoded_excluded_subdirs = {}
                    for encoded_root, encoded_subdirs in encoded_excluded_subdirs.items():
                        try:
                            root_dir = base64.b64decode(encoded_root.encode()).decode()
                            subdirs  = []
                            for encoded_subdir in encoded_subdirs:
                                try:
                                    subdirs.append(base64.b64decode(encoded_subdir.encode()).decode())
                                except Exception:
                                    pass
                            if subdirs:
                                decoded_excluded_subdirs[root_dir] = subdirs
                        except Exception:
                            pass

                    encoded_excluded_videos = config.get('excluded_videos', {})
                    decoded_excluded_videos = {}
                    for encoded_root, encoded_videos in encoded_excluded_videos.items():
                        try:
                            root_dir = base64.b64decode(encoded_root.encode()).decode()
                            videos   = []
                            for encoded_video in encoded_videos:
                                try:
                                    videos.append(base64.b64decode(encoded_video.encode()).decode())
                                except Exception:
                                    pass
                            if videos:
                                decoded_excluded_videos[root_dir] = videos
                        except Exception:
                            pass

                    return {
                        'dark_mode':               config.get('dark_mode', True),
                        'show_videos':             config.get('show_videos', True),
                        'expand_all':              False,
                        'selected_dirs':           decoded_dirs,
                        'save_directories':        True,
                        'start_from_last_played':  config.get('start_from_last_played', False),
                        'last_played_video_index': config.get('last_played_video_index', 0),
                        'last_played_video_path':  last_played_path,
                        'excluded_subdirs':        decoded_excluded_subdirs,
                        'excluded_videos':         decoded_excluded_videos,
                        'smart_resume_enabled':    config.get('smart_resume_enabled', False),
                        'volume':                  config.get('volume', 50),
                        'is_muted':                config.get('is_muted', False),
                        'loop_mode':               config.get('loop_mode', 'loop_on'),
                        'show_console':            config.get('show_console', False),
                    }
        except Exception:
            pass
        return {
            'dark_mode': True, 'show_videos': True, 'expand_all': False,
            'selected_dirs': [], 'save_directories': True,
            'start_from_last_played': False, 'last_played_video_index': 0,
            'last_played_video_path': '', 'excluded_subdirs': {}, 'excluded_videos': {},
            'smart_resume_enabled': False, 'volume': 50, 'is_muted': False,
            'loop_mode': 'loop_on', 'show_console': False,
        }

    def save(self, config_dict):
        try:
            encoded_dirs       = [base64.b64encode(d.encode()).decode() for d in config_dict.get('selected_dirs', [])]
            config_dict        = dict(config_dict)
            config_dict['selected_dirs'] = encoded_dirs
            last_played_path   = config_dict.get('last_played_video_path', '')
            config_dict['last_played_video_path'] = base64.b64encode(last_played_path.encode()).decode()
            with open(self.config_path, 'w') as f:
                json.dump(config_dict, f, indent=2)
        except Exception:
            pass


class ThemeSelector(ThemePreferencesMixin, ThemeCoreMixin, ThemeDirectoryMixin, ThemeManagerMixin, ThemeToolbarMixin):
    def __init__(self):
        self.config = ConfigHandler()
        self.toast = None
        self._save_timer = None




















































    # ── Toolbar / pill colour palette ─────────────────────────────────────────
    PILL_ACCENTS_LIGHT = {
        "Home":           ("#4a5568", "#d7dde8", "#1a2035", "#c7cfdd"),
        "Gallery":        ("#2d7ef7", "#1a6de8", "#FFFFFF", "#1557bd"),
        "🎵 Playlist":   ("#5B9BD5", "#1a5fa8", "#FFFFFF", "#144d8a"),
        "⬛ Queue":      ("#2ecc71", "#1a8a4a", "#FFFFFF", "#156e3a"),
        "♥ Favourites": ("#e67e22", "#b35a00", "#FFFFFF", "#8a4400"),
        "🕐 History":   ("#9b59b6", "#6c2f8f", "#FFFFFF", "#521f6e"),
        "🏷 Tags & Ratings": ("#c8a000", "#8a6d0a", "#FFFFFF", "#5a4600"),
    }
    PILL_ACCENTS_DARK = {
        "Home":           ("#A9B7C6", "#343a46", "#FFFFFF", "#2b303a"),
        "Gallery":        ("#5b9cf6", "#2D5A8E", "#FFFFFF", "#1A4070"),
        "🎵 Playlist":   ("#4A9EFF", "#1a5fa8", "#FFFFFF", "#144d8a"),
        "⬛ Queue":      ("#2ecc71", "#1a8a4a", "#FFFFFF", "#156e3a"),
        "♥ Favourites": ("#FF9F43", "#b35a00", "#FFFFFF", "#8a4400"),
        "🕐 History":   ("#C39BD3", "#6c2f8f", "#FFFFFF", "#521f6e"),
        "🏷 Tags & Ratings": ("#f5c518", "#b8920f", "#FFFFFF", "#8a6d0a"),
    }











