import winreg
import sys
import os


def register_context_menu():
    try:
        exe_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist", "RecursiveVideoPlayer", "RecursiveVideoPlayer.exe")

        if not os.path.exists(exe_path):
            print(f"Error: Executable not found at {exe_path}")
            print("Please build the app with PyInstaller first.")
            return

        command = f'"{exe_path}" "%V"'

        key_path = r"Directory\shell\RecursiveVideoPlayer"

        key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path)
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Open with Recursive Video Player")
        winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, f'"{exe_path}",0')
        winreg.CloseKey(key)

        command_key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, key_path + r"\command")
        winreg.SetValue(command_key, "", winreg.REG_SZ, command)
        winreg.CloseKey(command_key)

        print("Context menu registered successfully!")
        print(f"Executable: {exe_path}")

    except PermissionError:
        print("Error: This script requires administrator privileges.")
        print("Please run as administrator.")
    except Exception as e:
        print(f"Error registering context menu: {e}")


def unregister_context_menu():
    try:
        key_path = r"Directory\shell\RecursiveVideoPlayer"
        winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, key_path + r"\command")
        winreg.DeleteKey(winreg.HKEY_CLASSES_ROOT, key_path)
        print("Context menu unregistered successfully!")
    except FileNotFoundError:
        print("Context menu entry not found.")
    except PermissionError:
        print("Error: This script requires administrator privileges.")
        print("Please run as administrator.")
    except Exception as e:
        print(f"Error unregistering context menu: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "unregister":
        unregister_context_menu()
    else:
        register_context_menu()