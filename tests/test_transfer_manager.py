"""Unit tests for TransferManager — covers every method and every branch."""

import os
import tempfile
import threading
from unittest.mock import MagicMock, call, patch

import pytest

from transfer_manager import DEFAULT_DEST_DIR, DEFAULT_MAX_WORKERS, TransferManager


@pytest.fixture
def source():
  return MagicMock()


@pytest.fixture
def dest():
  return MagicMock()


@pytest.fixture
def manager(source, dest):
  return TransferManager(source, dest)


# ── __init__ ──────────────────────────────────────────────────────────────────

class TestInit:
  def test_default_dest_dir(self, manager):
    assert manager.dest_dir == DEFAULT_DEST_DIR

  def test_default_max_workers(self, manager):
    assert manager.max_workers == DEFAULT_MAX_WORKERS

  def test_custom_dest_dir(self, source, dest):
    m = TransferManager(source, dest, dest_dir="/sdcard/Custom")
    assert m.dest_dir == "/sdcard/Custom"

  def test_custom_max_workers(self, source, dest):
    m = TransferManager(source, dest, max_workers=2)
    assert m.max_workers == 2

  def test_source_and_dest_stored(self, source, dest):
    m = TransferManager(source, dest)
    assert m.source is source
    assert m.dest is dest

  def test_internal_lock_is_a_lock(self, manager):
    assert isinstance(manager._lock, type(threading.Lock()))


# ── transfer_all ──────────────────────────────────────────────────────────────

class TestTransferAll:
  def test_calls_transfer_one_for_each_file(self, manager):
    files = [("/path/a.jpg", 100), ("/path/b.mp4", 200), ("/path/c.png", 300)]
    with patch.object(manager, "_transfer_one") as mock_t:
      manager.transfer_all(files)
    assert mock_t.call_count == 3

  def test_passes_dry_run_true_to_transfer_one(self, manager):
    files = [("/path/a.jpg", 100)]
    with patch.object(manager, "_transfer_one") as mock_t:
      manager.transfer_all(files, dry_run=True)
    # Fourth positional arg is dry_run
    assert mock_t.call_args[0][3] is True

  def test_passes_dry_run_false_by_default(self, manager):
    files = [("/path/a.jpg", 100)]
    with patch.object(manager, "_transfer_one") as mock_t:
      manager.transfer_all(files)
    assert mock_t.call_args[0][3] is False

  def test_handles_exception_without_raising(self, manager):
    """An exception inside a worker must not propagate out of transfer_all."""
    files = [("/path/bad.jpg", 100)]
    with patch.object(manager, "_transfer_one", side_effect=RuntimeError("adb crash")):
      with patch("transfer_manager.tqdm.write"):
        manager.transfer_all(files)  # should not raise

  def test_exception_writes_error_message(self, manager):
    files = [("/path/bad.jpg", 100)]
    with patch.object(manager, "_transfer_one", side_effect=RuntimeError("adb crash")):
      with patch("transfer_manager.tqdm.write") as mock_write:
        manager.transfer_all(files)
    written = mock_write.call_args[0][0]
    assert "bad.jpg" in written
    assert "adb crash" in written

  def test_all_files_processed_even_after_one_fails(self, manager):
    files = [("/path/bad.jpg", 1), ("/path/good.jpg", 2)]
    call_count = 0

    def side_effect(remote_path, mtime, tmp_dir, dry_run):
      nonlocal call_count
      call_count += 1
      if "bad" in remote_path:
        raise RuntimeError("oops")

    with patch.object(manager, "_transfer_one", side_effect=side_effect):
      with patch("transfer_manager.tqdm.write"):
        manager.transfer_all(files)
    assert call_count == 2

  def test_empty_file_list_completes_without_error(self, manager):
    manager.transfer_all([])  # should not raise


# ── _transfer_one ─────────────────────────────────────────────────────────────

class TestTransferOne:
  """Tests run _transfer_one directly with a real temporary directory."""

  def _run(self, manager, remote_path, mtime, dry_run=False):
    with tempfile.TemporaryDirectory(prefix="test_pixel_sync_") as tmp_dir:
      manager._transfer_one(remote_path, mtime, tmp_dir, dry_run)
      return tmp_dir  # already cleaned up but useful for assertions

  # ── dry-run branch ────────────────────────────────────────────────────────

  def test_dry_run_prints_filename(self, manager):
    with patch("transfer_manager.tqdm.write") as mock_write:
      self._run(manager, "/sdcard/DCIM/Camera/photo.jpg", 1000, dry_run=True)
    assert "dry-run" in mock_write.call_args[0][0]
    assert "photo.jpg" in mock_write.call_args[0][0]

  def test_dry_run_skips_all_device_calls(self, manager, source, dest):
    with patch("transfer_manager.tqdm.write"):
      self._run(manager, "/sdcard/file.jpg", 1000, dry_run=True)
    source.pull.assert_not_called()
    dest.push.assert_not_called()
    source.delete.assert_not_called()

  # ── happy path (sizes match) ──────────────────────────────────────────────

  def test_success_pulls_from_source(self, manager, source, dest):
    source.file_size.return_value = 1024
    dest.file_size.return_value = 1024
    with patch("os.remove"), patch("transfer_manager.tqdm.write"):
      self._run(manager, "/sdcard/DCIM/photo.jpg", 1000)
    source.pull.assert_called_once()
    assert source.pull.call_args[0][0] == "/sdcard/DCIM/photo.jpg"

  def test_success_pushes_to_dest_dir(self, manager, source, dest):
    source.file_size.return_value = 512
    dest.file_size.return_value = 512
    with patch("os.remove"), patch("transfer_manager.tqdm.write"):
      self._run(manager, "/sdcard/DCIM/photo.jpg", 1000)
    dest.push.assert_called_once()
    assert dest.push.call_args[0][1] == DEFAULT_DEST_DIR

  def test_success_sets_mtime_on_dest(self, manager, source, dest):
    source.file_size.return_value = 100
    dest.file_size.return_value = 100
    with patch("os.remove"), patch("transfer_manager.tqdm.write"):
      self._run(manager, "/sdcard/DCIM/photo.jpg", mtime=1_700_000_000)
    dest.set_mtime.assert_called_once_with(
      f"{DEFAULT_DEST_DIR}/photo.jpg", 1_700_000_000
    )

  def test_success_triggers_media_scan(self, manager, source, dest):
    source.file_size.return_value = 100
    dest.file_size.return_value = 100
    with patch("os.remove"), patch("transfer_manager.tqdm.write"):
      self._run(manager, "/sdcard/DCIM/photo.jpg", 1000)
    dest.trigger_media_scan.assert_called_once_with(f"{DEFAULT_DEST_DIR}/photo.jpg")

  def test_success_deletes_original(self, manager, source, dest):
    source.file_size.return_value = 2048
    dest.file_size.return_value = 2048
    with patch("os.remove"), patch("transfer_manager.tqdm.write"):
      self._run(manager, "/sdcard/DCIM/photo.jpg", 1000)
    source.delete.assert_called_once_with("/sdcard/DCIM/photo.jpg")

  def test_success_prints_checkmark(self, manager, source, dest):
    source.file_size.return_value = 100
    dest.file_size.return_value = 100
    with patch("os.remove"), patch("transfer_manager.tqdm.write") as mock_write:
      self._run(manager, "/sdcard/DCIM/photo.jpg", 1000)
    assert "✓" in mock_write.call_args[0][0]

  def test_success_removes_local_temp_file(self, manager, source, dest):
    source.file_size.return_value = 100
    dest.file_size.return_value = 100
    with patch("os.remove") as mock_remove, patch("transfer_manager.tqdm.write"):
      self._run(manager, "/sdcard/DCIM/photo.jpg", 1000)
    mock_remove.assert_called_once()

  # ── size mismatch branch ──────────────────────────────────────────────────

  def test_mismatch_does_not_delete_original(self, manager, source, dest):
    source.file_size.return_value = 2048
    dest.file_size.return_value = 1024  # different!
    with patch("os.remove"), patch("transfer_manager.tqdm.write"):
      self._run(manager, "/sdcard/DCIM/photo.jpg", 1000)
    source.delete.assert_not_called()

  def test_mismatch_prints_error_message(self, manager, source, dest):
    source.file_size.return_value = 2048
    dest.file_size.return_value = 512
    with patch("os.remove"), patch("transfer_manager.tqdm.write") as mock_write:
      self._run(manager, "/sdcard/DCIM/photo.jpg", 1000)
    assert "size mismatch" in mock_write.call_args[0][0]

  def test_mismatch_still_removes_local_temp_file(self, manager, source, dest):
    """Even on failure the local temp file must be cleaned up."""
    source.file_size.return_value = 2048
    dest.file_size.return_value = 512
    with patch("os.remove") as mock_remove, patch("transfer_manager.tqdm.write"):
      self._run(manager, "/sdcard/DCIM/photo.jpg", 1000)
    mock_remove.assert_called_once()

  # ── temp-file uniqueness ──────────────────────────────────────────────────

  def test_local_tmp_prefixed_with_thread_id(self, manager, source, dest):
    """Two files with the same basename from different folders should not collide."""
    source.file_size.return_value = 100
    dest.file_size.return_value = 100
    captured = {}

    def capture_pull(remote_path, local_path):
      captured["local_path"] = local_path

    source.pull.side_effect = capture_pull
    with patch("os.remove"), patch("transfer_manager.tqdm.write"):
      self._run(manager, "/folder1/IMG_0001.jpg", 1000)

    local = captured["local_path"]
    assert "IMG_0001.jpg" in local
    assert str(threading.get_ident()) in local

  # ── dest_dir trailing slash ───────────────────────────────────────────────

  def test_trailing_slash_stripped_from_dest_path(self, source, dest):
    manager = TransferManager(source, dest, dest_dir="/sdcard/Download/")
    source.file_size.return_value = 100
    dest.file_size.return_value = 100
    with patch("os.remove"), patch("transfer_manager.tqdm.write"):
      with tempfile.TemporaryDirectory() as tmp_dir:
        manager._transfer_one("/sdcard/file.jpg", 0, tmp_dir, dry_run=False)
    dest.set_mtime.assert_called_once_with("/sdcard/Download/file.jpg", 0)
