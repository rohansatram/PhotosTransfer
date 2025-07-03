#!/usr/bin/env python3
"""
Transfer NEW photos/videos from Phone A to Pixel (Phone B) over USB,
then delete them from Phone A if transfer succeeds.

Requirements:
  * Homebrew 'android-platform-tools'
  * Both phones authorised for adb
Usage:
  python sync_to_pixel.py --source SERIAL_A --dest SERIAL_B --cutoff 2025-07-01 --dry-run
Remove --dry-run after you confirm it behaves as expected.
"""
import argparse, subprocess, shlex, os, sys, time
from datetime import datetime
# --- sync_to_pixel.py (only the lines below have changed) --------------------

CAMERA_DIRS = [
    "/sdcard/DCIM/Camera",
    "/sdcard/DCIM/Snapchat",
    "/sdcard/Pictures/Backdrops",
    "/sdcard/Pictures/ChatGPT",
    "/sdcard/Pictures/EssentialSpace",
    "/sdcard/Pictures/PhotosEditor",
    "/sdcard/Pictures/Reddit",
    "/sdcard/Pictures/Screenshots",

    # WhatsApp (scoped storage on Android 11+)
    "/sdcard/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images",
    "/sdcard/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Video",
]

EXTS = (".jpg", ".jpeg", ".png", ".heic", ".mp4", ".mov", ".mkv", ".webm")
DEST_DIR = "/sdcard/Download"

def adb(shell_cmd, device):
    full_cmd = f"adb -s {device} {shell_cmd}"
    return subprocess.check_output(shlex.split(full_cmd)).decode().strip()

def list_files(device, cutoff_ts):
    """
    Return [(path, mtime), …] for all files in CAMERA_DIRS
    that are on or after `cutoff_ts` (epoch seconds).
    Uses a single adb call per folder for speed.
    """
    files_to_copy = []
    for folder in CAMERA_DIRS:
        print(f"Scanning {folder} …", flush=True)
        q = shlex.quote(folder)
        # One shell: find → stat → print "mtime path"
        cmd = (
            f'shell "if [ -d {q} ]; then '
            f'find {q} -type f \\( -iname \'*.jpg\' -o -iname \'*.jpeg\' '
            f'-o -iname \'*.png\' -o -iname \'*.heic\' '
            f'-o -iname \'*.mp4\' -o -iname \'*.mov\' '
            f'-o -iname \'*.mkv\' -o -iname \'*.webm\' \\) '
            f'-exec stat -c \\"%Y %n\\" {{}} +; fi"'
        )
        try:
            output = adb(cmd, device)
        except subprocess.CalledProcessError:
            continue  # folder missing, skip

        for line in output.splitlines():
            try:
                t_str, path = line.split(" ", 1)
                mtime = int(t_str)
            except ValueError:
                continue  # malformed line
            if mtime >= cutoff_ts and "/.trashed-" not in path:
                files_to_copy.append((path, mtime))
    return files_to_copy

def transfer(src, dst, items, dry):
    for path, mtime in items:
        fname = os.path.basename(path)
        local_tmp = f"/tmp/{fname}"
        dest_file = f"{DEST_DIR.rstrip('/')}/{fname}"   # <-- new line

        print(f"▶ {fname}", end=" ")
        if dry:
            print("[dry-run]")
            continue

        # copy from source → Mac
        subprocess.check_call(["adb", "-s", src, "pull", path, local_tmp])

        # copy from Mac → Pixel
        subprocess.check_call(["adb", "-s", dst, "push", local_tmp, DEST_DIR])

        # verify sizes
        size_src  = int(adb(f'shell "stat -c %s {shlex.quote(path)}"', src))
        size_dest = int(adb(f'shell "stat -c %s {shlex.quote(dest_file)}"', dst))

        if size_src == size_dest:
            # delete from source only after successful compare
            subprocess.check_call(["adb", "-s", src, "shell", "rm", shlex.quote(path)])
            print("✓ transferred & deleted")
        else:
            print("✗ size mismatch, NOT deleted")

        # now it’s safe to drop the Mac temp copy
        os.remove(local_tmp)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="ADB serial for Phone A")
    ap.add_argument("--dest",   required=True, help="ADB serial for Pixel")
    ap.add_argument("--cutoff", required=True, help="ISO date YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="Do not copy/delete, just list")
    args = ap.parse_args()

    cutoff_ts = int(time.mktime(datetime.strptime(args.cutoff, "%Y-%m-%d").timetuple()))
    to_copy = list_files(args.source, cutoff_ts)
    if not to_copy:
        print("Nothing to transfer.")
        return
    print(f"{len(to_copy)} file(s) meet the cutoff; starting transfer…")
    transfer(args.source, args.dest, to_copy, args.dry_run)

if __name__ == "__main__":
    main()