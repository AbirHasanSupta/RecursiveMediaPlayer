"""
Launcher script that handles switching between Tkinter and Qt versions
without terminating the main process.
Works both in normal Python runs and PyInstaller builds.
"""
import subprocess
import sys
import os
from config_util import load_config, save_config


def get_app_path(filename_no_ext: str):
    """
    Returns the correct path to an app script/exe depending on whether
    we are running from source or from a PyInstaller build.
    """
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
        return os.path.join(base_dir, f"{filename_no_ext}.exe")
    else:
        base_dir = os.path.dirname(__file__)
        return os.path.join(base_dir, f"{filename_no_ext}.py")


def run_app(path):
    """Run either .py or .exe depending on context."""
    if path.endswith(".py"):
        return subprocess.run([sys.executable, path], check=False)
    else:
        return subprocess.run([path], check=False)


def main():
    while True:
        config = load_config()
        last_mode = config.get("last_mode", "tk")

        if last_mode == "qt":
            qt_path = get_app_path("qt_app")
            try:
                run_app(qt_path)

                new_config = load_config()
                if new_config.get("last_mode") == "tk" and new_config.get("switch_requested", False):
                    new_config["switch_requested"] = False
                    save_config(new_config)
                    continue
                else:
                    break
            except Exception as e:
                print(f"Error running Qt app: {e}")
                break

        else:
            tk_path = get_app_path("app")
            try:
                run_app(tk_path)

                new_config = load_config()
                if new_config.get("last_mode") == "qt" and new_config.get("switch_requested", False):
                    new_config["switch_requested"] = False
                    save_config(new_config)
                    continue
                else:
                    break
            except Exception as e:
                print(f"Error running Tkinter app: {e}")
                break


if __name__ == "__main__":
    main()
