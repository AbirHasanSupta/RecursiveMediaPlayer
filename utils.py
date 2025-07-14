import os
import fnmatch


VIDEO_EXTENSIONS = ['*.mp4', '*.mkv', '*.avi', '*.mov', '*.wmv', '*.flv']


def is_video(file_name):
    return any(fnmatch.fnmatch(file_name.lower(), ext) for ext in VIDEO_EXTENSIONS)


def gather_videos_with_directories(directory):
    videos = []
    video_to_dir = {}
    directories = []

    for root, dirs, files in os.walk(directory):
        if any(is_video(file) for file in files):
            directories.append(root)

    directories.sort()

    for dir_path in directories:
        dir_videos = []
        for file in os.listdir(dir_path):
            full_path = os.path.join(dir_path, file)
            if os.path.isfile(full_path) and is_video(file):
                dir_videos.append(full_path)

        dir_videos.sort()

        for video in dir_videos:
            videos.append(video)
            video_to_dir[video] = dir_path

    return videos, video_to_dir, directories


def gather_videos(directory):
    videos, _, _ = gather_videos_with_directories(directory)
    return videos

