"""Unit tests for AdbDevice — covers every method and every branch."""

import subprocess
from unittest.mock import call, patch

import pytest

from adb_device import AdbDevice


SERIAL = "PIXEL_SERIAL"


@pytest.fixture
def device():
  return AdbDevice(SERIAL)


# ── __init__ ──────────────────────────────────────────────────────────────────

class TestInit:
  def test_serial_stored(self, device):
    assert device.serial == SERIAL


# ── run ───────────────────────────────────────────────────────────────────────

class TestRun:
  def test_returns_stripped_stdout(self, device):
    with patch("subprocess.check_output", return_value=b"  hello world  ") as mock_out:
      result = device.run("shell ls")
      assert result == "hello world"
      mock_out.assert_called_once_with(["adb", "-s", SERIAL, "shell", "ls"])

  def test_multi_token_command_split_correctly(self, device):
    with patch("subprocess.check_output", return_value=b"ok") as mock_out:
      device.run('shell "stat -c %s /sdcard/file.jpg"')
      args = mock_out.call_args[0][0]
      assert args[0] == "adb"
      assert args[1] == "-s"
      assert args[2] == SERIAL


# ── pull ──────────────────────────────────────────────────────────────────────

class TestPull:
  def test_calls_adb_pull(self, device):
    with patch("subprocess.check_call") as mock_call:
      device.pull("/remote/file.jpg", "/local/file.jpg")
      mock_call.assert_called_once_with(
        ["adb", "-s", SERIAL, "pull", "/remote/file.jpg", "/local/file.jpg"]
      )


# ── push ──────────────────────────────────────────────────────────────────────

class TestPush:
  def test_calls_adb_push_with_progress_flag(self, device):
    with patch("subprocess.check_call") as mock_call:
      device.push("/local/file.jpg", "/sdcard/Download")
      mock_call.assert_called_once_with(
        ["adb", "-s", SERIAL, "push", "-p", "/local/file.jpg", "/sdcard/Download"]
      )


# ── file_size ────────────────────────────────────────────────────────────────

class TestFileSize:
  def test_returns_int(self, device):
    with patch.object(device, "run", return_value="98765"):
      assert device.file_size("/sdcard/file.jpg") == 98765

  def test_stat_command_contains_path(self, device):
    with patch.object(device, "run", return_value="1") as mock_run:
      device.file_size("/sdcard/video.mp4")
      assert "/sdcard/video.mp4" in mock_run.call_args[0][0]


# ── delete ────────────────────────────────────────────────────────────────────

class TestDelete:
  def test_runs_rm_on_device(self, device):
    with patch.object(device, "run") as mock_run:
      device.delete("/sdcard/old.jpg")
      mock_run.assert_called_once()
      assert "rm" in mock_run.call_args[0][0]
      assert "/sdcard/old.jpg" in mock_run.call_args[0][0]


# ── set_mtime ────────────────────────────────────────────────────────────────

class TestSetMtime:
  def test_epoch_form_used_on_first_attempt(self, device):
    """Happy path: the @epoch touch form succeeds immediately."""
    with patch.object(device, "run") as mock_run:
      device.set_mtime("/sdcard/file.jpg", 1_700_000_000)
      mock_run.assert_called_once()
      assert "@1700000000" in mock_run.call_args[0][0]

  def test_falls_back_to_timestamp_format(self, device):
    """When the @epoch form fails, the YYYYMMDDHHmm.SS form is tried."""
    with patch.object(device, "run") as mock_run:
      mock_run.side_effect = [Exception("unsupported"), None]
      device.set_mtime("/sdcard/file.jpg", 1_700_000_000)
      assert mock_run.call_count == 2
      # Second call uses the -t format (no '@')
      second_cmd = mock_run.call_args_list[1][0][0]
      assert "@" not in second_cmd
      assert "touch -m -t" in second_cmd

  def test_silently_passes_when_both_forms_fail(self, device):
    """If both touch forms fail the method swallows the exception."""
    with patch.object(device, "run", side_effect=Exception("unsupported")):
      # Must not raise
      device.set_mtime("/sdcard/file.jpg", 1_700_000_000)

  def test_path_is_shell_quoted(self, device):
    """Paths with spaces are properly quoted in the shell command."""
    with patch.object(device, "run") as mock_run:
      device.set_mtime("/sdcard/My Files/photo.jpg", 0)
    cmd = mock_run.call_args[0][0]
    # shlex.quote wraps the whole path in single-quotes
    assert "'/sdcard/My Files/photo.jpg'" in cmd


# ── trigger_media_scan ────────────────────────────────────────────────────────

class TestTriggerMediaScan:
  def test_broadcasts_media_scanner_intent(self, device):
    with patch.object(device, "run") as mock_run:
      device.trigger_media_scan("/sdcard/Download/photo.jpg")
      mock_run.assert_called_once()
      cmd = mock_run.call_args[0][0]
      assert "MEDIA_SCANNER_SCAN_FILE" in cmd
      assert "photo.jpg" in cmd

  def test_file_uri_scheme_present(self, device):
    with patch.object(device, "run") as mock_run:
      device.trigger_media_scan("/sdcard/Download/video.mp4")
      assert "file://" in mock_run.call_args[0][0]
