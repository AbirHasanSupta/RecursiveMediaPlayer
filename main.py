import sys
import os
import multiprocessing

# Add source directories to sys.path to preserve all imports
root_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(root_dir, "src"))
sys.path.insert(0, os.path.join(root_dir, "src", "core"))
sys.path.insert(0, os.path.join(root_dir, "src", "utils"))

if __name__ == "__main__":
    multiprocessing.freeze_support()
    
    from app import select_multiple_folders_and_play, check_vlc, show_vlc_missing_and_exit
    if not check_vlc():
        show_vlc_missing_and_exit()
    select_multiple_folders_and_play()
