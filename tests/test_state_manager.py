"""Unit tests for StateManager — covers every method and every branch."""

import json
from datetime import datetime, timezone

import pytest

from state_manager import DEFAULT_STATE_FILE, StateManager


# ── __init__ ──────────────────────────────────────────────────────────────────

class TestInit:
  def test_uses_default_state_file(self):
    sm = StateManager()
    assert sm.state_file == DEFAULT_STATE_FILE

  def test_uses_custom_state_file(self, tmp_path):
    custom = str(tmp_path / "my_state.json")
    sm = StateManager(state_file=custom)
    assert sm.state_file == custom


# ── load_cutoff ───────────────────────────────────────────────────────────────

class TestLoadCutoff:
  def test_returns_fallback_when_file_is_missing(self, tmp_path):
    sm = StateManager(str(tmp_path / "nonexistent.json"))
    assert sm.load_cutoff("2023-06-01") == "2023-06-01"

  def test_default_fallback_is_year_2000(self, tmp_path):
    sm = StateManager(str(tmp_path / "nonexistent.json"))
    assert sm.load_cutoff() == "2000-01-01"

  def test_returns_date_portion_from_valid_file(self, tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"last_cutoff": "2024-06-15T10:30:00+00:00"}))
    sm = StateManager(str(state_file))
    assert sm.load_cutoff() == "2024-06-15"

  def test_strips_time_portion_correctly(self, tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"last_cutoff": "2025-12-31T23:59:59+05:30"}))
    sm = StateManager(str(state_file))
    assert sm.load_cutoff() == "2025-12-31"

  def test_returns_fallback_on_invalid_json(self, tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text("{ this is not json }")
    sm = StateManager(str(state_file))
    assert sm.load_cutoff("2021-01-01") == "2021-01-01"

  def test_returns_fallback_when_key_is_missing(self, tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"wrong_key": "2024-01-01"}))
    sm = StateManager(str(state_file))
    assert sm.load_cutoff("2021-01-01") == "2021-01-01"

  def test_returns_fallback_on_empty_file(self, tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text("")
    sm = StateManager(str(state_file))
    assert sm.load_cutoff("2022-01-01") == "2022-01-01"


# ── save_cutoff_now ───────────────────────────────────────────────────────────

class TestSaveCutoffNow:
  def test_creates_file_and_parent_directories(self, tmp_path):
    state_file = tmp_path / "subdir" / "nested" / "state.json"
    sm = StateManager(str(state_file))
    sm.save_cutoff_now()
    assert state_file.exists()

  def test_writes_valid_json(self, tmp_path):
    state_file = tmp_path / "state.json"
    sm = StateManager(str(state_file))
    sm.save_cutoff_now()
    data = json.loads(state_file.read_text())
    assert "last_cutoff" in data

  def test_timestamp_is_close_to_now(self, tmp_path):
    state_file = tmp_path / "state.json"
    sm = StateManager(str(state_file))
    before = datetime.now(timezone.utc)
    sm.save_cutoff_now()
    after = datetime.now(timezone.utc)

    data = json.loads(state_file.read_text())
    saved = datetime.fromisoformat(data["last_cutoff"])
    # save_cutoff_now uses timespec="seconds" so truncate before to seconds
    before_truncated = before.replace(microsecond=0)
    assert before_truncated <= saved <= after

  def test_overwrites_existing_cutoff(self, tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"last_cutoff": "2000-01-01T00:00:00+00:00"}))
    sm = StateManager(str(state_file))
    sm.save_cutoff_now()

    data = json.loads(state_file.read_text())
    assert data["last_cutoff"] != "2000-01-01T00:00:00+00:00"

  def test_file_can_be_reloaded_after_save(self, tmp_path):
    state_file = tmp_path / "state.json"
    sm = StateManager(str(state_file))
    sm.save_cutoff_now()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert sm.load_cutoff() == today
