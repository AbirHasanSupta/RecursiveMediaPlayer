"""
Launcher script that handles switching between Tkinter and Qt versions
without terminating the main process.
"""
import subprocess
import sys
import os
from config_util import load_config, save_config


def main():
    while True:
        config = load_config()
        last_mode = config.get("last_mode", "tk")

        if last_mode == "qt":
            qt_app_py = os.path.join(os.path.dirname(__file__), "qt_app.py")
            try:
                result = subprocess.run([sys.executable, qt_app_py],
                                        capture_output=False,
                                        check=False)

                new_config = load_config()
                if new_config.get("last_mode") == "tk" and new_config.get("switch_requested", False):
                    new_config["switch_requested"] = False
                    save_config(new_config)
                    continue
                else:
                    break

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error running Qt app: {e}")
                break
        else:
            tk_app_py = os.path.join(os.path.dirname(__file__), "app.py")
            try:
                result = subprocess.run([sys.executable, tk_app_py],
                                        capture_output=False,
                                        check=False)

                new_config = load_config()
                if new_config.get("last_mode") == "qt" and new_config.get("switch_requested", False):
                    new_config["switch_requested"] = False
                    save_config(new_config)
                    continue
                else:
                    break

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error running Tkinter app: {e}")
                break


if __name__ == "__main__":
    main()