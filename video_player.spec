# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Recursive Video Player
WITHOUT AI features - Much smaller and simpler build
"""

import sys
import os

block_cipher = None

# Minimal hidden imports - no AI/ML libraries
hidden_imports = [
    # Core dependencies
    'tkinter',
    'tkinter.filedialog',
    'tkinter.messagebox',
    'tkinter.ttk',

    # Video processing (needed for thumbnails)
    'cv2',
    'PIL',
    'PIL.Image',
    'PIL._tkinter_finder',

    # Video playback
    'vlc',

    # System
    'screeninfo',
    'keyboard',
    'pynput',
    'win32clipboard',
    'win32con',
    'win32api',

    # Standard library
    'concurrent.futures',
    'multiprocessing',
    'threading',
    'queue',
    'pathlib',
    'base64',
    'json',
    'pickle',
    're',
    'datetime',
    'time',
    'collections',
    'typing',

    # Manager modules
    'managers',
    'managers.playlist_manager',
    'managers.watch_history_manager',
    'managers.resume_playback_manager',
    'managers.settings_manager',
    'managers.video_preview_manager',
]

a = Analysis(
    ['main.py'],
    pathex=[
        os.path.abspath('src'),
        os.path.abspath(os.path.join('src', 'core')),
        os.path.abspath(os.path.join('src', 'utils')),
    ],
    binaries=[],
    datas=[
        # ── icon & splash asset ──────────────────────────────────────────────
        ('assets/icon.ico', '.'),

        # ── source files ─────────────────────────────────────────────────────
        ('src/utils/icon_helper.py', '.'),
        ('src/core/splash.py', '.'),
        ('src/core/key_press.py', '.'),
        ('src/core/theme.py', '.'),
        ('src/utils/utils.py', '.'),
        ('src/core/embedded_player.py', '.'),
        ('src/core/ai_service.py', '.'),
        ('src/core/app.py', '.'),
        # ── managers package ─────────────────────────────────────────────────
        ('src/managers', 'managers'),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Explicitly exclude AI/ML packages
        'torch',
        'transformers',
        'sentence_transformers',
        'faiss',
        'sklearn',
        'nltk',
        'scipy',
        'pandas',
        'matplotlib',
        'IPython',
        'notebook',
        'jupyter',
        'pytest',
        'sphinx',
        'tensorboard',
        'tensorflow',
        # NOTE: cv2 (opencv) is NOT excluded - needed for video thumbnails
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RecursiveVideoPlayer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # ── custom Windows taskbar / .exe icon ───────────────────────────────────
    icon='assets/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='RecursiveVideoPlayer',
)