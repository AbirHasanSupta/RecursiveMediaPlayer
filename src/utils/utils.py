import os
import sys

VIDEO_SUFFIXES = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv')


def is_video(file_name: str) -> bool:
    return file_name.lower().endswith(VIDEO_SUFFIXES)


def gather_videos_with_directories(directory):
    videos = []
    video_to_dir = {}
    directories = []

    try:
        for root, dirs, files in os.walk(directory):
            try:
                if any(is_video(file) for file in files):
                    directories.append(root)
            except (PermissionError, OSError):
                continue

        directories.sort()

        for dir_path in directories:
            dir_videos = []
            try:
                with os.scandir(dir_path) as it:
                    for entry in it:
                        try:
                            if entry.is_file() and is_video(entry.name):
                                dir_videos.append(entry.path)
                        except (PermissionError, OSError):
                            continue
            except (PermissionError, OSError):
                continue

            dir_videos.sort()

            for video in dir_videos:
                videos.append(video)
                video_to_dir[video] = dir_path

        return videos, video_to_dir, directories

    except Exception as e:
        print(f"Error gathering videos: {e}")
        return [], {}, []


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
                w = min(desired_w, int(m.width  * 0.90))
                h = min(desired_h, int(m.height * 0.90))
                x = m.x + (m.width  - w) // 2
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