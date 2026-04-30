from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from xml.etree.ElementTree import Element

import gpxpy
from gpxpy.gpx import GPXException

from mwgc.errors import GpxParseError
from mwgc.models import TrackPoint

EARTH_RADIUS_M = 6_371_000.0


def parse_gpx(path: Path | str) -> tuple[list[TrackPoint], datetime]:
    path = Path(path)
    try:
        with path.open("r", encoding="utf-8") as f:
            gpx = gpxpy.parse(f)
    except GPXException as e:
        raise GpxParseError(f"failed to parse GPX: {e}") from e

    raw = [pt for trk in gpx.tracks for seg in trk.segments for pt in seg.points]
    if not raw:
        raise GpxParseError(f"no trackpoints in {path}")

    points: list[TrackPoint] = []
    cumulative = 0.0
    for i, pt in enumerate(raw):
        if pt.time is None:
            raise GpxParseError(f"trackpoint {i} has no timestamp")
        time = _to_utc(pt.time)
        ext = _extract_extensions(pt.extensions)
        if i > 0:
            cumulative += _segment_distance(raw[i - 1], pt)
        points.append(
            TrackPoint(
                time=time,
                lat=pt.latitude,
                lon=pt.longitude,
                altitude_m=pt.elevation,
                heart_rate=ext["heart_rate"],
                cadence=ext["cadence"],
                power_w=ext["power_w"],
                speed_mps=pt.speed,
                distance_m=cumulative,
            )
        )

    return points, points[0].time


def _to_utc(t: datetime) -> datetime:
    if t.tzinfo is None:
        return t.replace(tzinfo=UTC)
    return t.astimezone(UTC)


def _extract_extensions(extensions: list[Element]) -> dict[str, int | None]:
    result: dict[str, int | None] = {"heart_rate": None, "cadence": None, "power_w": None}
    for ext in extensions:
        for elem in ext.iter():
            tag = _local_name(elem.tag).lower()
            text = (elem.text or "").strip()
            if not text:
                continue
            try:
                if tag == "hr":
                    result["heart_rate"] = int(text)
                elif tag == "cad":
                    result["cadence"] = int(text)
                elif tag in {"power", "powerinwatts"}:
                    result["power_w"] = int(text)
            except ValueError:
                continue
    return result


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _segment_distance(prev, curr) -> float:
    if (
        prev.latitude is not None
        and prev.longitude is not None
        and curr.latitude is not None
        and curr.longitude is not None
    ):
        return _haversine_m(prev.latitude, prev.longitude, curr.latitude, curr.longitude)
    if curr.speed is not None and prev.time is not None and curr.time is not None:
        dt = (curr.time - prev.time).total_seconds()
        if dt > 0:
            return curr.speed * dt
    return 0.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
