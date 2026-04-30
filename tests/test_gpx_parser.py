from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import pytest

from mwgc.errors import GpxParseError
from mwgc.gpx_parser import parse_gpx

FIXTURE = Path(__file__).parent / "fixtures" / "sample_mywhoosh.gpx"


def test_parses_eight_points():
    points, _ = parse_gpx(FIXTURE)
    assert len(points) == 8


def test_first_point_metrics():
    points, _ = parse_gpx(FIXTURE)
    p = points[0]
    assert p.lat == 41.5
    assert p.lon == -8.4
    assert p.altitude_m == 100.0
    assert p.heart_rate == 140
    assert p.cadence == 88
    assert p.power_w == 180


def test_first_point_time_is_utc():
    points, _ = parse_gpx(FIXTURE)
    assert points[0].time == datetime(2026, 4, 30, 8, 0, 0, tzinfo=UTC)


def test_start_time_equals_first_trackpoint():
    points, start = parse_gpx(FIXTURE)
    assert start == points[0].time


def test_first_point_distance_is_zero():
    points, _ = parse_gpx(FIXTURE)
    assert points[0].distance_m == 0.0


def test_distances_monotonically_increasing():
    points, _ = parse_gpx(FIXTURE)
    distances = [p.distance_m for p in points]
    assert all(b > a for a, b in pairwise(distances))


def test_total_distance_matches_geometry():
    # 7 steps of 0.0001 deg longitude at latitude 41.5 deg ~= 58.3 m by haversine.
    points, _ = parse_gpx(FIXTURE)
    assert points[-1].distance_m == pytest.approx(58.3, abs=0.5)


def test_missing_power_yields_none():
    # The trackpoint at 08:00:03Z has only TrackPointExtension, no PowerExtension.
    points, _ = parse_gpx(FIXTURE)
    assert points[3].power_w is None
    assert points[2].power_w == 195
    assert points[4].power_w == 210


def test_missing_cadence_yields_none():
    # The trackpoint at 08:00:04Z has hr only inside TrackPointExtension.
    points, _ = parse_gpx(FIXTURE)
    assert points[4].cadence is None
    assert points[3].cadence == 90
    assert points[5].cadence == 91


def test_temperature_parsed_from_atemp():
    # Every point in the fixture has atemp=22.0.
    points, _ = parse_gpx(FIXTURE)
    assert all(p.temperature_c == 22.0 for p in points)


def test_missing_atemp_yields_none(tmp_path):
    # A GPX without atemp should give temperature_c=None on every point.
    gpx = tmp_path / "no_temp.gpx"
    gpx.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"'
        ' xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">'
        "<trk><trkseg>"
        '<trkpt lat="0" lon="0"><ele>0</ele><time>2026-01-01T00:00:00Z</time>'
        "<extensions><gpxtpx:TrackPointExtension>"
        "<gpxtpx:hr>140</gpxtpx:hr>"
        "</gpxtpx:TrackPointExtension></extensions>"
        "</trkpt>"
        '<trkpt lat="0.001" lon="0"><ele>0</ele><time>2026-01-01T00:00:01Z</time>'
        "<extensions><gpxtpx:TrackPointExtension>"
        "<gpxtpx:hr>141</gpxtpx:hr>"
        "</gpxtpx:TrackPointExtension></extensions>"
        "</trkpt>"
        "</trkseg></trk></gpx>"
    )
    points, _ = parse_gpx(gpx)
    assert all(p.temperature_c is None for p in points)


def test_raises_on_zero_trackpoints(tmp_path):
    empty = tmp_path / "empty.gpx"
    empty.write_text(
        '<?xml version="1.0"?>'
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"/>'
    )
    with pytest.raises(GpxParseError, match="no trackpoints"):
        parse_gpx(empty)


def test_raises_on_malformed_xml(tmp_path):
    bad = tmp_path / "bad.gpx"
    bad.write_text("not a gpx file at all")
    with pytest.raises(GpxParseError, match="failed to parse"):
        parse_gpx(bad)


def test_raises_on_missing_file(tmp_path):
    missing = tmp_path / "does_not_exist.gpx"
    with pytest.raises(FileNotFoundError):
        parse_gpx(missing)
