#!/usr/bin/env python3
"""Scans directories on an ADB device for media files newer than a cutoff timestamp."""

import shlex
import subprocess

from adb_device import AdbDevice


MEDIA_EXTENSIONS = (
  ".jpg", ".jpeg", ".png", ".heic",
  ".mp4", ".mov", ".mkv", ".webm",
)

DEFAULT_CAMERA_DIRS = [
  "/sdcard/DCIM/Camera",
  "/sdcard/DCIM/Snapchat",
  "/sdcard/Pictures/Backdrops",
  "/sdcard/Pictures/ChatGPT",
  "/sdcard/Pictures/EssentialSpace",
  "/sdcard/Pictures/PhotosEditor",
  "/sdcard/Pictures/Reddit",
  "/sdcard/Pictures/Screenshots",
  "/sdcard/Pictures/Telegram",
  "/sdcard/Download",
  # WhatsApp (scoped storage)
  "/sdcard/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Images",
  "/sdcard/Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Video",
]


class FileScanner:
  """Finds media files on a device that are newer than a given Unix timestamp."""

  def __init__(self, device: AdbDevice, folders: list[str] | None = None):
    self.device = device
    self.folders = folders or DEFAULT_CAMERA_DIRS

  def scan(self, cutoff_ts: int) -> list[tuple[str, int]]:
    """
    Return a list of (remote_path, mtime_epoch) tuples for all media files
    with mtime >= cutoff_ts across all configured folders.
    """
    results = []
    for folder in self.folders:
      print(f"  Scanning {folder} …", flush=True)
      results.extend(self._scan_folder(folder, cutoff_ts))
    return results

  # ── internal ─────────────────────────────────────────────────────────────

  def _build_find_command(self, folder: str) -> str:
    """Build a single adb shell find+stat command for all media extensions."""
    quoted = shlex.quote(folder)
    ext_filters = " -o ".join(f"-iname '*{ext}'" for ext in MEDIA_EXTENSIONS)
    return (
      f'shell "if [ -d {quoted} ]; then '
      f'find {quoted} -type f \\( {ext_filters} \\) '
      f'-exec stat -c \\"%Y %n\\" {{}} +; fi"'
    )

  def _scan_folder(self, folder: str, cutoff_ts: int) -> list[tuple[str, int]]:
    """Run find+stat on a single folder and return matching (path, mtime) pairs."""
    try:
      output = self.device.run(self._build_find_command(folder))
    except subprocess.CalledProcessError:
      return []

    results = []
    for line in output.splitlines():
      try:
        ts_str, path = line.split(" ", 1)
        mtime = int(ts_str)
      except ValueError:
        continue
      if mtime >= cutoff_ts and "/.trashed-" not in path:
        results.append((path, mtime))
    return results
