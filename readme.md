Recursive Media Player (Tkinter/PyQt6 + VLC)

A desktop app to recursively scan directories for videos and play them with VLC.

Requirements
- Python 3.9+
- VLC installed (Desktop VLC) so python-vlc can find libvlc
- Windows (tested); keyboard hotkeys rely on the `keyboard` library

Install
1) Create/activate a virtual environment (optional).
2) Install dependencies:
   pip install -r requirements.txt

Run
python app.py

Usage
- Click "Add Directory" to select one or more base folders.
- Adjust "Max Depth" to limit recursion depth.
- Toggle:
  - "Show Videos in Subdirectory List" to show videos under each subdirectory entry.
  - "Show Excluded Only" to filter the list (informational).
- Click "Play Videos" to start playback. Videos are grouped by subdirectory.

Keyboard Shortcuts (only when the app window is focused)
- esc: Stop and exit
- space: Play/Pause
- a / d: Previous/Next video
- left / right: Seek backward/forward
- w / s: Volume up/down
- f: Toggle fullscreen
- t: Take snapshot of current frame (saved next to current video)
- 1 / 2: Move playback window to Monitor 1 / Monitor 2
- q / e: Previous/Next directory (when multiple directories are scanned)

Notes
- The app uses python-vlc and spawns a VLC media player window positioned on the selected monitor.
- Screenshots are written next to the current video file with a timestamped name.

Packaging (PyInstaller)
You can build a Windows executable using the provided app.spec or this example command:
pyinstaller --onefile --noconsole \
  --add-binary "C:\\Program Files\\VideoLAN\\VLC\\libvlc.dll;." \
  --add-binary "C:\\Program Files\\VideoLAN\\VLC\\plugins;plugins" app.py

If PyQt6 plugins are missing at runtime, you may need to collect them, e.g.:
pyinstaller --onefile --noconsole --collect-submodules PyQt6 \
  --add-binary "C:\\Program Files\\VideoLAN\\VLC\\libvlc.dll;." \
  --add-binary "C:\\Program Files\\VideoLAN\\VLC\\plugins;plugins" app.py

Troubleshooting
- If hotkeys do nothing, ensure the app window is focused (foreground only).
- If VLC fails to load, ensure VLC is installed and libvlc.dll is on PATH or bundled via PyInstaller.


UI Enhancements
- Colorful modern theme with blue accents, hover/pressed states, and improved scrollbars.
- Fusion style with HiDPI scaling for crisp visuals on high‑resolution displays.
- Better spacing and margins, section titles for hierarchy, and alternating row colors for lists.
- Responsive layout using splitter stretch factors and sensible size behavior.
