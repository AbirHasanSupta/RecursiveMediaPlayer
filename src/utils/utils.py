import os
import sys

VIDEO_SUFFIXES = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv')
PHOTO_EXTENSIONS = (
    '.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp', '.tiff', '.tif', '.heic', '.avif',
)
AUDIO_EXTENSIONS = ('.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac', '.wma')
MEDIA_MODES = ('video', 'photo', 'both')
VALID_MEDIA_MODES = set(MEDIA_MODES)


def is_video(file_name: str) -> bool:
    return file_name.lower().endswith(VIDEO_SUFFIXES)


def is_photo(file_name: str) -> bool:
    return os.path.splitext(file_name)[1].lower() in PHOTO_EXTENSIONS


def is_audio(file_name: str) -> bool:
    return os.path.splitext(file_name)[1].lower() in AUDIO_EXTENSIONS


def normalize_media_mode(mode: str) -> str:
    mode = (mode or 'video').lower()
    return mode if mode in VALID_MEDIA_MODES else 'video'


def is_media(file_name: str, media_mode: str = 'video') -> bool:
    """Return True if file_name matches the active media mode filter."""
    mode = normalize_media_mode(media_mode)
    if mode == 'video':
        return is_video(file_name)
    if mode == 'photo':
        return is_photo(file_name)
    return is_video(file_name) or is_photo(file_name)


def media_type_label(media_mode: str) -> str:
    mode = normalize_media_mode(media_mode)
    return {'video': 'videos', 'photo': 'photos', 'both': 'media'}[mode]


def media_icon_for_path(path: str) -> str:
    return '🖼' if is_photo(path) else '🎬'


def _gather_files_with_directories(directory, file_predicate):
    files = []
    file_to_dir = {}
    directories = []

    try:
        for root, dirs, walk_files in os.walk(directory):
            try:
                if any(file_predicate(file) for file in walk_files):
                    directories.append(root)
            except (PermissionError, OSError):
                continue

        directories.sort()

        for dir_path in directories:
            dir_files = []
            try:
                with os.scandir(dir_path) as it:
                    for entry in it:
                        try:
                            if entry.is_file() and file_predicate(entry.name):
                                dir_files.append(entry.path)
                        except (PermissionError, OSError):
                            continue
            except (PermissionError, OSError):
                continue

            dir_files.sort()

            for file_path in dir_files:
                files.append(file_path)
                file_to_dir[file_path] = dir_path

        return files, file_to_dir, directories

    except Exception as e:
        print(f"Error gathering media: {e}")
        return [], {}, []


def gather_media_with_directories(directory, media_mode: str = 'video'):
    mode = normalize_media_mode(media_mode)
    predicate = lambda name: is_media(name, mode)
    return _gather_files_with_directories(directory, predicate)


def gather_videos_with_directories(directory):
    return gather_media_with_directories(directory, 'video')


def gather_videos(directory):
    videos, _, _ = gather_videos_with_directories(directory)
    return videos


def _responsive_geometry(parent, desired_w, desired_h):
    """Return 'WxH+X+Y' centered on the same monitor as parent, capped at 90% of monitor size."""
    try:
        from screeninfo import get_monitors
        wx = parent.winfo_rootx()
        wy = parent.winfo_rooty()
        for m in get_monitors():
            if m.x <= wx < m.x + m.width and m.y <= wy < m.y + m.height:
                w = min(desired_w, int(m.width * 0.90))
                h = min(desired_h, int(m.height * 0.90))
                x = m.x + (m.width - w) // 2
                y = m.y + (m.height - h) // 2
                return f"{w}x{h}+{x}+{y}"
    except Exception:
        pass
    sw = parent.winfo_screenwidth()
    sh = parent.winfo_screenheight()
    w = min(desired_w, int(sw * 0.90))
    h = min(desired_h, int(sh * 0.90))
    x = (sw - w) // 2
    y = (sh - h) // 2
    return f"{w}x{h}+{x}+{y}"


def check_vlc():
    try:
        import vlc
        inst = vlc.Instance()
        if inst is None:
            raise RuntimeError
        inst.release()
        return True
    except Exception:
        return False


def show_vlc_missing_and_exit():
    import tkinter as tk
    from tkinter import messagebox
    import webbrowser
    root = tk.Tk()
    root.withdraw()
    open_dl = messagebox.askyesno(
        "VLC Not Found",
        "VLC media player (64-bit) is required but was not found.\n\n"
        "Open the VLC download page now?",
    )
    if open_dl:
        webbrowser.open("https://www.videolan.org/vlc/index.html")
    root.destroy()
    sys.exit(1)
