from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as defused_ET
import gpxpy
from gpxpy.gpx import GPXException

from mwgc.errors import GpxParseError
from mwgc.models import TrackPoint

EARTH_RADIUS_M = 6_371_000.0
# Hard cap on GPX input size. A real ride with 8h of 1Hz samples and full
# extensions runs well under 5 MB, so 50 MB is generous yet keeps a malicious
# file from exhausting RAM regardless of what's inside.
MAX_GPX_SIZE_BYTES = 50 * 1024 * 1024


def parse_gpx(path: Path | str) -> tuple[list[TrackPoint], datetime]:
    path = Path(path)

    # Size guard — primary DoS defense. Bounded input means bounded memory.
    # path.stat() raises FileNotFoundError for a missing file; let it propagate
    # so the CLI can map it to exit code 2 with the existing message.
    size = path.stat().st_size
    if size > MAX_GPX_SIZE_BYTES:
        raise GpxParseError(
            f"GPX file too large: {size} bytes (max {MAX_GPX_SIZE_BYTES})"
        )

    content = path.read_bytes()

    # Defense-in-depth: defusedxml rejects XXE and entity-expansion bombs that
    # would otherwise be passed verbatim through gpxpy → stdlib expat.
    try:
        defused_ET.fromstring(content)
    except defused_ET.EntitiesForbidden as e:
        raise GpxParseError(f"GPX contains forbidden XML entities: {e}") from e
    except defused_ET.ParseError:
        # Malformed XML — let gpxpy produce its more descriptive error below.
        pass

    try:
        gpx = gpxpy.parse(content.decode("utf-8"))
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
                temperature_c=ext["temperature_c"],
            )
        )

    return points, points[0].time


def _to_utc(t: datetime) -> datetime:
    if t.tzinfo is None:
        return t.replace(tzinfo=UTC)
    return t.astimezone(UTC)


def _extract_extensions(extensions: list[Element]) -> dict[str, int | float | None]:
    result: dict[str, int | float | None] = {
        "heart_rate": None,
        "cadence": None,
        "power_w": None,
        "temperature_c": None,
    }
    for ext in extensions:
        for elem in ext.iter():
            tag = _local_name(elem.tag).lower()
            text = (elem.text or "").strip()
            if not text:
                continue
            try:
                if tag == "hr":
                    result["heart_rate"] = int(float(text))
                elif tag == "cad":
                    result["cadence"] = int(float(text))
                elif tag in {"power", "powerinwatts"}:
                    result["power_w"] = int(float(text))
                elif tag == "atemp":
                    result["temperature_c"] = float(text)
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
