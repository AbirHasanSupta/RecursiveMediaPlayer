import os

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
