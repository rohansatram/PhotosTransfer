#!/usr/bin/env python3
"""Parallel file transfers between two ADB devices with a live progress bar."""

import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from adb_device import AdbDevice


DEFAULT_DEST_DIR = "/sdcard/Download"
DEFAULT_MAX_WORKERS = 4


class TransferManager:
  """
  Transfers files from a source device to a destination device.

  Files are pulled to a temporary local directory in parallel (up to
  max_workers at a time) and then pushed to the destination. A progress
  bar shows how many files are done and the elapsed / estimated time.

  Note: max_workers of 3–5 is the sweet spot for USB — beyond that you
  saturate the bus and transfers slow back down.
  """

  def __init__(
    self,
    source: AdbDevice,
    dest: AdbDevice,
    dest_dir: str = DEFAULT_DEST_DIR,
    max_workers: int = DEFAULT_MAX_WORKERS,
  ):
    self.source = source
    self.dest = dest
    self.dest_dir = dest_dir
    self.max_workers = max_workers
    self._lock = threading.Lock()

  def transfer_all(self, files: list[tuple[str, int]], dry_run: bool = False) -> None:
    """
    Transfer all files in parallel with a live progress bar.

    Each entry in `files` is a (remote_path, mtime_epoch) tuple from
    FileScanner. On dry_run, files are listed but not moved.
    """
    bar_format = (
      "{desc}: {percentage:3.0f}%|{bar}| "
      "{n_fmt}/{total_fmt} files  "
      "[{elapsed} elapsed · ETA {remaining}]"
    )

    with tempfile.TemporaryDirectory(prefix="pixel_sync_") as tmp_dir:
      with tqdm(
        total=len(files),
        desc="Transferring",
        unit="file",
        bar_format=bar_format,
        colour="cyan",
        dynamic_ncols=True,
      ) as progress:

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
          future_to_path = {
            executor.submit(
              self._transfer_one, remote_path, mtime_epoch, tmp_dir, dry_run
            ): remote_path
            for remote_path, mtime_epoch in files
          }

          for future in as_completed(future_to_path):
            remote_path = future_to_path[future]
            filename = os.path.basename(remote_path)
            try:
              future.result()
            except Exception as error:
              tqdm.write(f"  ✗ {filename} — {error}")
            with self._lock:
              progress.update(1)

  # ── internal ─────────────────────────────────────────────────────────────

  def _transfer_one(
    self,
    remote_path: str,
    mtime_epoch: int,
    tmp_dir: str,
    dry_run: bool,
  ) -> None:
    """
    Pull one file from source, push it to dest, verify size, then delete
    the original. Uses a shared temp directory; filenames are kept unique
    by the caller's TemporaryDirectory.
    """
    filename = os.path.basename(remote_path)
    # Use a unique local path so concurrent transfers never collide on the
    # same filename (e.g. two 'IMG_0001.jpg' from different folders).
    local_tmp = os.path.join(tmp_dir, f"{threading.get_ident()}_{filename}")
    dest_path = f"{self.dest_dir.rstrip('/')}/{filename}"

    if dry_run:
      tqdm.write(f"  [dry-run] {filename}")
      return

    # Step 1: pull from source device to local machine
    self.source.pull(remote_path, local_tmp)

    # Step 2: push from local machine to destination device
    self.dest.push(local_tmp, self.dest_dir)

    # Step 3: preserve original modified time before media scan
    self.dest.set_mtime(dest_path, mtime_epoch)

    # Step 4: tell Google Photos to index the new file immediately
    self.dest.trigger_media_scan(dest_path)

    # Step 5: verify transfer integrity by comparing file sizes
    source_size = self.source.file_size(remote_path)
    dest_size = self.dest.file_size(dest_path)

    if source_size == dest_size:
      self.source.delete(remote_path)
      tqdm.write(f"  ✓ {filename}")
    else:
      tqdm.write(f"  ✗ {filename} — size mismatch, NOT deleted")

    os.remove(local_tmp)
