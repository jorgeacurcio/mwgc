"""Tests for mwgc.history."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from mwgc import history


@pytest.fixture()
def hist_path(tmp_path):
    return tmp_path / "history.json"


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


class TestWasUploaded:
    def test_returns_false_when_file_missing(self, hist_path):
        assert history.was_uploaded(_dt("2026-04-28T11:52:31"), path=hist_path) is False

    def test_returns_false_when_not_in_list(self, hist_path):
        hist_path.write_text(json.dumps({"uploaded": ["2025-01-01T00:00:00"]}))
        assert history.was_uploaded(_dt("2026-04-28T11:52:31"), path=hist_path) is False

    def test_returns_true_when_present(self, hist_path):
        dt = _dt("2026-04-28T11:52:31")
        hist_path.write_text(json.dumps({"uploaded": [history._iso(dt)]}))
        assert history.was_uploaded(dt, path=hist_path) is True

    def test_tolerates_corrupt_json(self, hist_path):
        hist_path.write_text("not json")
        assert history.was_uploaded(_dt("2026-04-28T11:52:31"), path=hist_path) is False

    def test_microseconds_are_ignored(self, hist_path):
        dt_with = _dt("2026-04-28T11:52:31").replace(microsecond=123456)
        dt_without = _dt("2026-04-28T11:52:31")
        hist_path.write_text(json.dumps({"uploaded": [history._iso(dt_without)]}))
        assert history.was_uploaded(dt_with, path=hist_path) is True


class TestRecordUpload:
    def test_creates_file_and_records(self, hist_path):
        dt = _dt("2026-04-28T11:52:31")
        history.record_upload(dt, path=hist_path)
        assert hist_path.exists()
        data = json.loads(hist_path.read_text())
        assert history._iso(dt) in data["uploaded"]

    def test_creates_parent_directory(self, tmp_path):
        nested = tmp_path / "sub" / "dir" / "history.json"
        history.record_upload(_dt("2026-04-28T11:52:31"), path=nested)
        assert nested.exists()

    def test_idempotent(self, hist_path):
        dt = _dt("2026-04-28T11:52:31")
        history.record_upload(dt, path=hist_path)
        history.record_upload(dt, path=hist_path)
        data = json.loads(hist_path.read_text())
        assert data["uploaded"].count(history._iso(dt)) == 1

    def test_appends_to_existing(self, hist_path):
        dt1 = _dt("2026-04-28T11:52:31")
        dt2 = _dt("2026-04-29T09:00:00")
        history.record_upload(dt1, path=hist_path)
        history.record_upload(dt2, path=hist_path)
        data = json.loads(hist_path.read_text())
        assert len(data["uploaded"]) == 2

    def test_round_trip_with_was_uploaded(self, hist_path):
        dt = _dt("2026-04-28T11:52:31")
        assert not history.was_uploaded(dt, path=hist_path)
        history.record_upload(dt, path=hist_path)
        assert history.was_uploaded(dt, path=hist_path)
