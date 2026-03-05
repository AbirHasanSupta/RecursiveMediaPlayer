import os
import cv2

VIDEO_SUFFIXES = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv')


def is_gpu_available():
    """
    Check if GPU acceleration is available for OpenCV (OpenCL) and VLC.
    Returns a dictionary with availability status for different components.
    """
    gpu_status = {
        'opencv_opencl': False,
        'vlc_hw_accel': True,  # Assume True as most modern systems support some form of HW accel in VLC
        'cuda_available': False,
        'gpu_name': None,
        'vram_total': 0,
        'vram_free': 0
    }

    try:
        if cv2.ocl.haveOpenCL():
            cv2.ocl.setUseOpenCL(True)
            gpu_status['opencv_opencl'] = cv2.ocl.useOpenCL()
    except Exception:
        pass

    try:
        import torch
        if torch.cuda.is_available():
            gpu_status['cuda_available'] = True
            gpu_status['gpu_name'] = torch.cuda.get_device_name(0)
            # VRAM info
            t = torch.cuda.get_device_properties(0).total_memory
            r = torch.cuda.memory_reserved(0)
            a = torch.cuda.memory_allocated(0)
            gpu_status['vram_total'] = t / (1024 ** 3)  # GB
            gpu_status['vram_free'] = (t - (r + a)) / (1024 ** 3)  # Approx free GB
    except Exception:
        pass

    return gpu_status


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
