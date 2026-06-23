#!/usr/bin/env python3
"""Manages the persistent backup state (last successful sync cutoff date)."""

import json
import os
from datetime import datetime, timezone


DEFAULT_STATE_FILE = os.path.expanduser("~/pixel_sync/backup_state.json")


class StateManager:
  """Reads and writes the last-sync cutoff date to a JSON state file."""

  def __init__(self, state_file: str = DEFAULT_STATE_FILE):
    self.state_file = state_file

  def load_cutoff(self, fallback_iso: str = "2000-01-01") -> str:
    """
    Return the last cutoff date as YYYY-MM-DD.
    Returns fallback_iso if the state file is missing or unreadable.
    """
    if not os.path.exists(self.state_file):
      return fallback_iso
    try:
      with open(self.state_file) as f:
        return json.load(f)["last_cutoff"].split("T")[0]
    except Exception:
      return fallback_iso

  def save_cutoff_now(self) -> None:
    """Save the current UTC timestamp as the new cutoff date."""
    os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
    with open(self.state_file, "w") as f:
      json.dump(
        {"last_cutoff": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        f,
      )
