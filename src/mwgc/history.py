"""Upload history — tracks which activity start times have been sent to Garmin.

The backing store is a small JSON file at ~/.mwgc/history.json.  The key
used for deduplication is the activity start time (first trackpoint's UTC
timestamp, serialised as an ISO-8601 string).  Start time is stable across
re-exports of the same ride, so it survives the user re-downloading the GPX.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

DEFAULT_HISTORY_PATH = Path.home() / ".mwgc" / "history.json"

_KEY = "uploaded"


def was_uploaded(start_time: datetime, path: Path | None = None) -> bool:
    """Return True if *start_time* has been recorded as uploaded."""
    path = path or DEFAULT_HISTORY_PATH
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return _iso(start_time) in data.get(_KEY, [])


def record_upload(start_time: datetime, path: Path | None = None) -> None:
    """Append *start_time* to the history file (idempotent)."""
    path = path or DEFAULT_HISTORY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {_KEY: []}
    else:
        data = {_KEY: []}

    key = _iso(start_time)
    if key not in data.get(_KEY, []):
        data.setdefault(_KEY, []).append(key)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _iso(dt: datetime) -> str:
    """Canonical ISO-8601 string for a datetime (UTC, no microseconds)."""
    return dt.replace(microsecond=0).isoformat()
