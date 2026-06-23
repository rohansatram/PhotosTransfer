#!/usr/bin/env python3
"""Thin wrapper around the adb command-line tool."""

import shlex
import subprocess
import time


class AdbDevice:
  """Represents a single ADB-connected device and exposes common operations."""

  def __init__(self, serial: str):
    self.serial = serial

  # ── low-level ────────────────────────────────────────────────────────────

  def run(self, command: str) -> str:
    """Run an adb sub-command and return stdout as a stripped string."""
    return subprocess.check_output(
      ["adb", "-s", self.serial] + shlex.split(command)
    ).decode().strip()

  def pull(self, remote_path: str, local_path: str) -> None:
    """Pull a single file from the device to a local path."""
    subprocess.check_call(
      ["adb", "-s", self.serial, "pull", remote_path, local_path]
    )

  def push(self, local_path: str, remote_dir: str) -> None:
    """Push a local file into a directory on the device."""
    subprocess.check_call(
      ["adb", "-s", self.serial, "push", "-p", local_path, remote_dir]
    )

  # ── file helpers ─────────────────────────────────────────────────────────

  def file_size(self, remote_path: str) -> int:
    """Return the size in bytes of a file on the device."""
    return int(self.run(f'shell "stat -c %s {shlex.quote(remote_path)}"'))

  def delete(self, remote_path: str) -> None:
    """Delete a file on the device."""
    self.run(f'shell "rm {shlex.quote(remote_path)}"')

  def set_mtime(self, remote_path: str, epoch: int) -> None:
    """
    Set the modified time of a file on the device.
    Tries the @epoch form first, falls back to the YYYYMMDDHHmm.SS form.
    """
    quoted = shlex.quote(remote_path)
    try:
      self.run(f'shell "touch -m -d @{epoch} {quoted}"')
    except Exception:
      try:
        ts_fmt = time.strftime("%Y%m%d%H%M.%S", time.localtime(epoch))
        self.run(f'shell "touch -m -t {ts_fmt} {quoted}"')
      except Exception:
        pass  # non-fatal — indexing will still work

  def trigger_media_scan(self, remote_path: str) -> None:
    """Broadcast a MEDIA_SCANNER intent so Google Photos indexes the file immediately."""
    quoted = shlex.quote(remote_path)
    self.run(
      f'shell "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE '
      f'-d file://{quoted}"'
    )
