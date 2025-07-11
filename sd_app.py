import threading
from tkinter import filedialog
import tkinter as tk

from key_press import listen_keys
from utils import gather_videos
from vlc_player_controller import BaseVLCPlayerController


def select_folder_and_play():
    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="Select Folder Containing Videos")
    if not folder:
        print("No folder selected.")
        return

    videos = gather_videos(folder)
    if not videos:
        print("No videos found.")
        return

    controller = BaseVLCPlayerController(videos)

    player_thread = threading.Thread(target=controller.run, daemon=True)
    player_thread.start()

    listen_keys(controller, multi_directory=False)

    print("Exiting player...")

if __name__ == "__main__":
    select_folder_and_play()