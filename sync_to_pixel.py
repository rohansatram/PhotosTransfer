#!/usr/bin/env python3
"""
sync_to_pixel.py  —  Push fresh photos/videos from Phone A to your Pixel.

* Remembers the last successful cutoff date in backup_state.json
* Transfers only items newer than that date
* Drops them in /sdcard/Download on the Pixel
* Broadcasts MEDIA_SCANNER so they're indexed instantly
* Verifies size, then deletes originals from Phone A

First run:
  python3 sync_to_pixel.py --source SERIAL_A --dest SERIAL_B --cutoff YYYY-MM-DD
Subsequent runs:
  python3 sync_to_pixel.py --source SERIAL_A --dest SERIAL_B
"""

import argparse
import time
from datetime import datetime

from adb_device import AdbDevice
from file_scanner import FileScanner
from state_manager import StateManager
from transfer_manager import TransferManager


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
    description="Sync new photos/videos from Phone A to a Pixel."
  )
  parser.add_argument("--source",  required=True, help="ADB serial of Phone A")
  parser.add_argument("--dest",    required=True, help="ADB serial of Pixel")
  parser.add_argument("--cutoff",  help="Override cutoff date as YYYY-MM-DD")
  parser.add_argument("--dry-run", action="store_true", help="Preview without transferring")
  parser.add_argument(
    "--workers", type=int, default=4,
    help="Number of parallel transfer threads (default: 4, sweet spot: 3-5 over USB)",
  )
  return parser.parse_args()


def main() -> None:
  args = parse_args()

  state   = StateManager()
  source  = AdbDevice(args.source)
  dest    = AdbDevice(args.dest)
  scanner = FileScanner(source)

  cutoff_date = args.cutoff or state.load_cutoff(fallback_iso="2000-01-01")
  cutoff_ts   = int(time.mktime(datetime.strptime(cutoff_date, "%Y-%m-%d").timetuple()))
  print(f"Cutoff date: {cutoff_date}\n")

  print("Scanning for new files…")
  new_files = scanner.scan(cutoff_ts)

  if not new_files:
    print("Nothing to transfer.")
    return

  print(f"\n{len(new_files)} file(s) found — starting transfer…\n")
  manager = TransferManager(source, dest, max_workers=args.workers)
  manager.transfer_all(new_files, dry_run=args.dry_run)

  if not args.dry_run:
    state.save_cutoff_now()
    print("\nBackup complete ✔  State file updated.")


if __name__ == "__main__":
  main()