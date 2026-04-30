from datetime import UTC, datetime
from pathlib import Path

import pytest
from fit_tool.fit_file import FitFile
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.messages.device_info_message import DeviceInfoMessage
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.messages.file_creator_message import FileCreatorMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.profile_type import (
    Event,
    EventType,
    FileType,
    Manufacturer,
    Sport,
    SubSport,
)

from mwgc.devices import FENIX_5_PLUS
from mwgc.errors import FitBuildError
from mwgc.fit_builder import build_fit
from mwgc.gpx_parser import parse_gpx
from mwgc.models import TrackPoint

FIXTURE = Path(__file__).parent / "fixtures" / "sample_mywhoosh.gpx"


@pytest.fixture
def points():
    pts, _ = parse_gpx(FIXTURE)
    return pts


@pytest.fixture
def built_fit(points, tmp_path) -> Path:
    out = tmp_path / "out.fit"
    build_fit(points, FENIX_5_PLUS, out)
    return out


def _messages_of(fit: FitFile, cls):
    return [r.message for r in fit.records if isinstance(r.message, cls)]


def test_writes_a_non_empty_fit_file(built_fit):
    assert built_fit.exists()
    assert built_fit.stat().st_size > 0


def test_file_decodes_cleanly(built_fit):
    decoded = FitFile.from_file(str(built_fit))
    assert len(decoded.records) > 0


def test_file_id_identifies_fenix_5_plus(built_fit):
    decoded = FitFile.from_file(str(built_fit))
    [fid] = _messages_of(decoded, FileIdMessage)
    assert fid.type == FileType.ACTIVITY.value
    assert fid.manufacturer == Manufacturer.GARMIN.value
    assert fid.garmin_product == 3110
    assert fid.serial_number == FENIX_5_PLUS.serial_number


def test_file_creator_software_version(built_fit):
    decoded = FitFile.from_file(str(built_fit))
    [fc] = _messages_of(decoded, FileCreatorMessage)
    assert fc.software_version == FENIX_5_PLUS.software_version


def test_device_info_present(built_fit):
    decoded = FitFile.from_file(str(built_fit))
    [di] = _messages_of(decoded, DeviceInfoMessage)
    assert di.manufacturer == Manufacturer.GARMIN.value
    assert di.garmin_product == 3110
    assert di.software_version == FENIX_5_PLUS.software_version


def test_record_count_matches_input(points, built_fit):
    decoded = FitFile.from_file(str(built_fit))
    records = _messages_of(decoded, RecordMessage)
    assert len(records) == len(points)


def test_first_record_metrics(built_fit):
    decoded = FitFile.from_file(str(built_fit))
    records = _messages_of(decoded, RecordMessage)
    first = records[0]
    assert first.heart_rate == 140
    assert first.cadence == 88
    assert first.power == 180
    assert first.position_lat == pytest.approx(41.5, abs=1e-4)
    assert first.position_long == pytest.approx(-8.4, abs=1e-4)


def test_missing_metrics_remain_absent(built_fit):
    # Trackpoint at index 3 had no PowerExtension; index 4 had no cadence.
    decoded = FitFile.from_file(str(built_fit))
    records = _messages_of(decoded, RecordMessage)
    assert records[3].power is None
    assert records[4].cadence is None


def test_timer_events_bracket_records(built_fit):
    decoded = FitFile.from_file(str(built_fit))
    events = _messages_of(decoded, EventMessage)
    timer_events = [e for e in events if e.event == Event.TIMER.value]
    assert len(timer_events) >= 2
    assert timer_events[0].event_type == EventType.START.value
    assert timer_events[-1].event_type == EventType.STOP_ALL.value


def test_session_is_cycling_virtual_activity(built_fit):
    decoded = FitFile.from_file(str(built_fit))
    [session] = _messages_of(decoded, SessionMessage)
    assert session.sport == Sport.CYCLING.value
    assert session.sub_sport == SubSport.VIRTUAL_ACTIVITY.value


def test_session_totals(built_fit):
    decoded = FitFile.from_file(str(built_fit))
    [session] = _messages_of(decoded, SessionMessage)
    # 7 seconds elapsed (08:00:00 -> 08:00:07).
    assert session.total_elapsed_time == pytest.approx(7.0, abs=0.001)
    assert session.total_timer_time == pytest.approx(7.0, abs=0.001)
    # Geometry-based total distance ~58.3 m.
    assert session.total_distance == pytest.approx(58.3, abs=0.5)


def test_session_aggregates(built_fit):
    decoded = FitFile.from_file(str(built_fit))
    [session] = _messages_of(decoded, SessionMessage)
    # HR ramps 140..152, all 8 points.
    assert session.max_heart_rate == 152
    assert 140 <= session.avg_heart_rate <= 152
    # Power ramps 180..225 with one missing.
    assert session.max_power == 225
    assert session.avg_power is not None and session.avg_power >= 180
    # Cadence ramps 88..92 with one missing.
    assert session.max_cadence == 92
    assert session.avg_cadence is not None and session.avg_cadence >= 88


def test_lap_mirrors_session(built_fit):
    decoded = FitFile.from_file(str(built_fit))
    [lap] = _messages_of(decoded, LapMessage)
    [session] = _messages_of(decoded, SessionMessage)
    assert lap.sport == session.sport
    assert lap.sub_sport == session.sub_sport
    assert lap.start_time == session.start_time
    assert lap.total_distance == pytest.approx(session.total_distance, abs=0.001)


def test_activity_message_terminates_file(built_fit):
    decoded = FitFile.from_file(str(built_fit))
    [activity] = _messages_of(decoded, ActivityMessage)
    assert activity.num_sessions == 1
    assert activity.event == Event.ACTIVITY.value
    assert activity.event_type == EventType.STOP.value


def test_progress_callback_is_invoked(points, tmp_path):
    out = tmp_path / "out.fit"
    calls: list[tuple[str, float]] = []
    build_fit(points, FENIX_5_PLUS, out, on_progress=lambda s, f: calls.append((s, f)))
    assert calls, "on_progress was never called"
    assert calls[-1] == ("done", 1.0)
    fractions = [f for _, f in calls]
    assert all(0.0 <= f <= 1.0 for f in fractions)
    assert fractions == sorted(fractions)


def test_empty_points_raises(tmp_path):
    out = tmp_path / "out.fit"
    with pytest.raises(FitBuildError, match="empty"):
        build_fit([], FENIX_5_PLUS, out)
    assert not out.exists()


def test_failure_mid_write_cleans_up_partial_file(points, tmp_path, monkeypatch):
    out = tmp_path / "out.fit"

    # Force a write-time failure: monkeypatch FitFile.to_file to write a few
    # bytes then raise. Verifies the cleanup-on-failure contract.
    from fit_tool.fit_file import FitFile

    def boom(self, path):
        Path(path).write_bytes(b"\x00\x01\x02")
        raise OSError("simulated disk full")

    monkeypatch.setattr(FitFile, "to_file", boom)

    with pytest.raises(FitBuildError, match="FIT encoding failed"):
        build_fit(points, FENIX_5_PLUS, out)
    assert not out.exists()


def test_handles_single_trackpoint(tmp_path):
    pt = TrackPoint(
        time=datetime(2026, 4, 30, 8, 0, 0, tzinfo=UTC),
        lat=41.5, lon=-8.4, altitude_m=100.0,
        heart_rate=140, cadence=88, power_w=180,
        speed_mps=8.3, distance_m=0.0,
    )
    out = tmp_path / "out.fit"
    build_fit([pt], FENIX_5_PLUS, out)
    assert out.exists()
    decoded = FitFile.from_file(str(out))
    records = [r.message for r in decoded.records if isinstance(r.message, RecordMessage)]
    assert len(records) == 1
