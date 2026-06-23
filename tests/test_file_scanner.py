"""Unit tests for FileScanner — covers every method and every branch."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from file_scanner import DEFAULT_CAMERA_DIRS, MEDIA_EXTENSIONS, FileScanner


@pytest.fixture
def mock_device():
  return MagicMock()


@pytest.fixture
def scanner(mock_device):
  return FileScanner(mock_device, folders=["/sdcard/DCIM/Camera"])


# ── __init__ ──────────────────────────────────────────────────────────────────

class TestInit:
  def test_uses_default_folders_when_none_given(self, mock_device):
    s = FileScanner(mock_device)
    assert s.folders == DEFAULT_CAMERA_DIRS

  def test_uses_custom_folders_when_provided(self, mock_device):
    custom = ["/sdcard/Custom", "/sdcard/Other"]
    s = FileScanner(mock_device, folders=custom)
    assert s.folders == custom

  def test_device_stored(self, mock_device):
    s = FileScanner(mock_device)
    assert s.device is mock_device


# ── scan ──────────────────────────────────────────────────────────────────────

class TestScan:
  def test_aggregates_results_from_all_folders(self, mock_device):
    s = FileScanner(mock_device, folders=["/folder1", "/folder2"])
    with patch.object(s, "_scan_folder") as mock_scan:
      mock_scan.side_effect = [
        [("/folder1/a.jpg", 100)],
        [("/folder2/b.mp4", 200)],
      ]
      results = s.scan(cutoff_ts=50)

    assert results == [("/folder1/a.jpg", 100), ("/folder2/b.mp4", 200)]
    assert mock_scan.call_count == 2

  def test_returns_empty_when_all_folders_empty(self, mock_device):
    s = FileScanner(mock_device, folders=["/a", "/b"])
    with patch.object(s, "_scan_folder", return_value=[]):
      assert s.scan(0) == []

  def test_prints_folder_name_during_scan(self, mock_device, capsys):
    s = FileScanner(mock_device, folders=["/sdcard/DCIM/Camera"])
    with patch.object(s, "_scan_folder", return_value=[]):
      s.scan(0)
    assert "/sdcard/DCIM/Camera" in capsys.readouterr().out

  def test_passes_cutoff_to_scan_folder(self, mock_device):
    s = FileScanner(mock_device, folders=["/folder"])
    with patch.object(s, "_scan_folder", return_value=[]) as mock_scan:
      s.scan(cutoff_ts=9999)
    mock_scan.assert_called_once_with("/folder", 9999)


# ── _build_find_command ───────────────────────────────────────────────────────

class TestBuildFindCommand:
  def test_contains_all_media_extensions(self, scanner):
    cmd = scanner._build_find_command("/sdcard/DCIM")
    for ext in MEDIA_EXTENSIONS:
      assert ext in cmd

  def test_contains_target_folder(self, scanner):
    cmd = scanner._build_find_command("/sdcard/DCIM/Camera")
    assert "/sdcard/DCIM/Camera" in cmd

  def test_uses_find_with_stat(self, scanner):
    cmd = scanner._build_find_command("/sdcard/DCIM")
    assert "find" in cmd
    assert "stat" in cmd

  def test_guards_with_directory_check(self, scanner):
    cmd = scanner._build_find_command("/sdcard/DCIM")
    assert "if [ -d" in cmd


# ── _scan_folder ──────────────────────────────────────────────────────────────

class TestScanFolder:
  def test_returns_files_at_or_above_cutoff(self, scanner, mock_device):
    mock_device.run.return_value = (
      "1000 /sdcard/DCIM/Camera/old.jpg\n"
      "2000 /sdcard/DCIM/Camera/new.jpg"
    )
    results = scanner._scan_folder("/sdcard/DCIM/Camera", cutoff_ts=1500)
    assert results == [("/sdcard/DCIM/Camera/new.jpg", 2000)]

  def test_includes_file_at_exact_cutoff(self, scanner, mock_device):
    mock_device.run.return_value = "1000 /sdcard/DCIM/Camera/exact.jpg"
    results = scanner._scan_folder("/sdcard/DCIM/Camera", cutoff_ts=1000)
    assert len(results) == 1

  def test_excludes_files_below_cutoff(self, scanner, mock_device):
    mock_device.run.return_value = "500 /sdcard/DCIM/Camera/old.jpg"
    results = scanner._scan_folder("/sdcard/DCIM/Camera", cutoff_ts=1000)
    assert results == []

  def test_returns_empty_on_adb_error(self, scanner, mock_device):
    mock_device.run.side_effect = subprocess.CalledProcessError(1, "adb")
    results = scanner._scan_folder("/sdcard/DCIM/Camera", cutoff_ts=0)
    assert results == []

  def test_skips_lines_that_cannot_be_parsed(self, scanner, mock_device):
    mock_device.run.return_value = (
      "not_a_valid_line\n"
      "1000 /sdcard/DCIM/Camera/valid.jpg"
    )
    results = scanner._scan_folder("/sdcard/DCIM/Camera", cutoff_ts=0)
    assert len(results) == 1
    assert results[0][0] == "/sdcard/DCIM/Camera/valid.jpg"

  def test_skips_trashed_files(self, scanner, mock_device):
    mock_device.run.return_value = "1000 /sdcard/.trashed-1234567/photo.jpg"
    results = scanner._scan_folder("/sdcard/DCIM/Camera", cutoff_ts=0)
    assert results == []

  def test_handles_completely_empty_output(self, scanner, mock_device):
    mock_device.run.return_value = ""
    results = scanner._scan_folder("/sdcard/DCIM/Camera", cutoff_ts=0)
    assert results == []

  def test_returns_correct_mtime_with_path(self, scanner, mock_device):
    mock_device.run.return_value = "1700000000 /sdcard/DCIM/Camera/IMG_001.jpg"
    results = scanner._scan_folder("/sdcard/DCIM/Camera", cutoff_ts=0)
    assert results == [("/sdcard/DCIM/Camera/IMG_001.jpg", 1_700_000_000)]

  def test_path_with_spaces_parsed_correctly(self, scanner, mock_device):
    """Filenames containing spaces should not break the split on first space."""
    mock_device.run.return_value = "1000 /sdcard/DCIM/Camera/my photo.jpg"
    results = scanner._scan_folder("/sdcard/DCIM/Camera", cutoff_ts=0)
    assert results == [("/sdcard/DCIM/Camera/my photo.jpg", 1000)]

  def test_multiple_valid_files_all_returned(self, scanner, mock_device):
    mock_device.run.return_value = (
      "1000 /sdcard/a.jpg\n"
      "2000 /sdcard/b.mp4\n"
      "3000 /sdcard/c.png"
    )
    results = scanner._scan_folder("/sdcard/DCIM/Camera", cutoff_ts=0)
    assert len(results) == 3
