#!/usr/bin/env python3
"""
sync_to_pixel.py  —  Push fresh photos/videos from Phone A to your Pixel.

* Remembers the last successful cutoff date in backup_state.json
* Transfers only items newer than that date
* Drops them in /sdcard/Download on the Pixel
* Broadcasts MEDIA_SCANNER so they’re indexed instantly
* Verifies size, then deletes originals from Phone A

First run:
  python3 sync_to_pixel.py --source SERIAL_A --dest SERIAL_B --cutoff YYYY-MM-DD
Subsequent runs:
  python3 sync_to_pixel.py --source SERIAL_A --dest SERIAL_B
"""

import argparse, subprocess, shlex, os, time, json
from datetime import datetime, timezone

# ────────────────────────────────────────────────────────────────────────────
CAMERA_DIRS = [
    "/sdcard/DCIM/Camera",
    "/sdcard/DCIM/Snapchat",
    "/sdcard/Pictures/Backdrops",
    "/sdcard/Pictures/ChatGPT",
    "/sdcard/Pictures/EssentialSpace",
    "/sdcard/Pictures/PhotosEditor",
    "/sdcard/Pictures/Reddit",
    "/sdcard/Pictures/Screenshots",
    # WhatsApp (scoped storage)
    "/sdcard/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images",
    "/sdcard/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Video",
]
EXTS      = (".jpg", ".jpeg", ".png", ".heic",
             ".mp4", ".mov", ".mkv", ".webm")
DEST_DIR  = "/sdcard/Download"                      # Pixel destination
STATE_FILE = os.path.expanduser("~/pixel_sync/backup_state.json")
# ────────────────────────────────────────────────────────────────────────────

def adb(dev: str, cmd: str) -> str:
    """Run an adb sub-command and return stdout."""
    return subprocess.check_output(["adb", "-s", dev] + shlex.split(cmd)
                                  ).decode().strip()

# ─── state-file helpers ─────────────────────────────────────────────────────
def load_last_cutoff(default_iso: str) -> str:
    if not os.path.exists(STATE_FILE):
        return default_iso
    try:
        with open(STATE_FILE) as f:
            return json.load(f)["last_cutoff"].split("T")[0]
    except Exception:
        return default_iso

def save_new_cutoff_now() -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump({"last_cutoff":
                   datetime.now(timezone.utc).isoformat(timespec="seconds")}, f)

# ─── scan for new files ─────────────────────────────────────────────────────
def list_files(device: str, cutoff_ts: int):
    results = []
    for folder in CAMERA_DIRS:
        print(f"Scanning {folder} …", flush=True)
        q = shlex.quote(folder)
        find_cmd = (
            f'shell "if [ -d {q} ]; then '
            f'find {q} -type f \\( -iname \'*.jpg\' -o -iname \'*.jpeg\' '
            f'-o -iname \'*.png\' -o -iname \'*.heic\' -o -iname \'*.mp4\' '
            f'-o -iname \'*.mov\' -o -iname \'*.mkv\' -o -iname \'*.webm\' \\) '
            f'-exec stat -c \\"%Y %n\\" {{}} +; fi"')
        try:
            out = adb(device, find_cmd)
        except subprocess.CalledProcessError:
            continue
        for line in out.splitlines():
            try:
                ts_str, path = line.split(" ", 1)
                mtime = int(ts_str)
            except ValueError:
                continue
            if mtime >= cutoff_ts and "/.trashed-" not in path:
                results.append((path, mtime))
    return results

# ─── main transfer routine ──────────────────────────────────────────────────
def transfer(src: str, dst: str, items, dry=False):
    for path, mtime_epoch in items:
        fname      = os.path.basename(path)
        local_tmp  = f"/tmp/{fname}"
        dest_file  = f"{DEST_DIR.rstrip('/')}/{fname}"

        print(f"▶ {fname}", end=" ")
        if dry:
            print("[dry-run]"); continue

        # pull → push
        subprocess.check_call(["adb", "-s", src, "pull", path, local_tmp])
        subprocess.check_call(["adb", "-s", dst, "push", "-p", local_tmp, DEST_DIR])

        # Preserve original modified time on destination before media scan
        try:
            adb(dst, f'shell "touch -m -d @{mtime_epoch} {shlex.quote(dest_file)}"')
        except Exception:
            try:
                ts_fmt = time.strftime("%Y%m%d%H%M.%S", time.localtime(mtime_epoch))
                adb(dst, f'shell "touch -m -t {ts_fmt} {shlex.quote(dest_file)}"')
            except Exception:
                pass

        # Trigger media scan after timestamp is set so Photos indexes correctly
        adb(dst, f'shell "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE '
                 f'-d file://{shlex.quote(dest_file)}"')

        # size verification
        size_src  = int(adb(src, f'shell "stat -c %s {shlex.quote(path)}"'))
        size_dest = int(adb(dst, f'shell "stat -c %s {shlex.quote(dest_file)}"'))

        if size_src == size_dest:
            adb(src, f'shell "rm {shlex.quote(path)}"')
            print("✓ transferred & deleted")
        else:
            print("✗ size mismatch, NOT deleted")

        os.remove(local_tmp)

# ─── CLI ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="ADB serial of Phone A")
    ap.add_argument("--dest", required=True,   help="ADB serial of Pixel")
    ap.add_argument("--cutoff", help="YYYY-MM-DD (optional)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cutoff_iso = args.cutoff or load_last_cutoff("2000-01-01")
    cutoff_ts  = int(time.mktime(datetime.strptime(cutoff_iso, "%Y-%m-%d").timetuple()))
    print(f"Using cutoff date: {cutoff_iso}")

    files = list_files(args.source, cutoff_ts)
    if not files:
        print("Nothing to transfer."); exit(0)

    print(f"{len(files)} file(s) meet the cutoff; starting transfer…")
    transfer(args.source, args.dest, files, args.dry_run)

    if not args.dry_run:
        save_new_cutoff_now()
        print("Backup complete ✔  State file updated.")