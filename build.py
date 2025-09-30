import subprocess
import sys
import os
import shutil


def main():
    print("=" * 60)
    print("Building Recursive Video Player")
    print("=" * 60)

    print("\n[1/5] Cleaning previous builds...")
    dirs_to_clean = ['build', 'dist', '__pycache__']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"  Removed: {dir_name}")

    subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyinstaller'], check=True)

    print("\n[4/5] Building with PyInstaller...")
    subprocess.run([sys.executable, '-m', 'PyInstaller', 'video_player.spec', '--clean'], check=True)

    print("\n[5/5] Post-build cleanup...")

    print("\n" + "=" * 60)
    print("Build Complete!")
    print("=" * 60)
    print(f"\nExecutable location: {os.path.abspath('dist/RecursiveVideoPlayer/RecursiveVideoPlayer.exe')}")
    print("\nNOTE: Before distributing, ensure:")
    print("  1. VLC is installed on target system")
    print("  3. Test all features thoroughly")


if __name__ == '__main__':
    main()