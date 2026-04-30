from __future__ import annotations

import contextlib
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path

from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.messages.device_info_message import DeviceInfoMessage
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.messages.file_creator_message import FileCreatorMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.profile_type import (
    Activity,
    Event,
    EventType,
    FileType,
    Manufacturer,
    Sport,
    SubSport,
)

from mwgc.errors import FitBuildError
from mwgc.models import DeviceProfile, TrackPoint

ProgressCallback = Callable[[str, float], None]


def build_fit(
    points: list[TrackPoint],
    profile: DeviceProfile,
    out_path: Path | str,
    on_progress: ProgressCallback | None = None,
) -> None:
    if not points:
        raise FitBuildError("cannot build FIT from empty trackpoints")

    out_path = Path(out_path)

    def progress(stage: str, fraction: float) -> None:
        if on_progress is not None:
            on_progress(stage, fraction)

    try:
        progress("aggregating", 0.0)
        agg = _aggregate(points)
        t0_ms = _to_ms(points[0])
        tN_ms = _to_ms(points[-1])
        elapsed_s = (points[-1].time - points[0].time).total_seconds()

        builder = FitFileBuilder(auto_define=True)

        progress("framing", 0.1)
        builder.add(_file_id(profile, t0_ms))
        builder.add(_file_creator(profile.software_version))
        builder.add(_device_info(profile, t0_ms))
        builder.add(_event(Event.TIMER, EventType.START, t0_ms))

        progress("records", 0.2)
        n = len(points)
        for i, p in enumerate(points):
            builder.add(_record(p))
            if n > 1 and i % max(1, n // 10) == 0:
                progress("records", 0.2 + 0.6 * (i / n))

        progress("framing", 0.85)
        builder.add(_event(Event.TIMER, EventType.STOP_ALL, tN_ms))
        builder.add(_lap(t0_ms, tN_ms, elapsed_s, agg))
        builder.add(_session(t0_ms, tN_ms, elapsed_s, agg))
        builder.add(_activity(tN_ms, elapsed_s))

        progress("writing", 0.95)
        fit_file = builder.build()
        fit_file.to_file(str(out_path))
        progress("done", 1.0)
    except FitBuildError:
        _cleanup(out_path)
        raise
    except Exception as e:
        _cleanup(out_path)
        raise FitBuildError(f"FIT encoding failed: {e}") from e


def _to_ms(p: TrackPoint) -> int:
    return int(p.time.timestamp() * 1000)


def _aggregate(points: list[TrackPoint]) -> dict[str, int | float | None]:
    hrs = [p.heart_rate for p in points if p.heart_rate is not None]
    powers = [p.power_w for p in points if p.power_w is not None]
    cads = [p.cadence for p in points if p.cadence is not None]

    work_j = sum(
        prev.power_w * (curr.time - prev.time).total_seconds()
        for prev, curr in pairwise(points)
        if prev.power_w is not None
    )
    # Cycling rule of thumb: 1 kJ of mechanical work ~= 1 kcal of energy
    # expended, because the body's ~25% efficiency cancels the 4.184 J/cal
    # conversion factor. Good enough for v1; refine in v1.1.
    calories = round(work_j / 1000.0)

    return {
        "avg_hr": round(sum(hrs) / len(hrs)) if hrs else None,
        "max_hr": max(hrs) if hrs else None,
        "avg_power": round(sum(powers) / len(powers)) if powers else None,
        "max_power": max(powers) if powers else None,
        "avg_cadence": round(sum(cads) / len(cads)) if cads else None,
        "max_cadence": max(cads) if cads else None,
        "total_calories": calories,
        "total_distance": points[-1].distance_m or 0.0,
    }


def _file_id(profile: DeviceProfile, t0_ms: int) -> FileIdMessage:
    m = FileIdMessage()
    m.type = FileType.ACTIVITY
    m.manufacturer = Manufacturer.GARMIN.value
    m.garmin_product = profile.product_id
    m.serial_number = profile.serial_number
    m.time_created = t0_ms
    return m


def _file_creator(software_version: float) -> FileCreatorMessage:
    m = FileCreatorMessage()
    # FIT software_version is a uint16 stored as major*100 + minor
    # (e.g. 19.30 → 1930).  fit-tool does not apply any scale factor,
    # so we convert here to avoid truncation.
    m.software_version = round(software_version * 100)
    return m


def _device_info(profile: DeviceProfile, t0_ms: int) -> DeviceInfoMessage:
    m = DeviceInfoMessage()
    m.timestamp = t0_ms
    m.device_index = 0  # 0 = creator/primary device
    m.manufacturer = Manufacturer.GARMIN.value
    m.garmin_product = profile.product_id
    m.serial_number = profile.serial_number
    # device_info.software_version has a built-in ×100 scale in fit-tool's
    # profile, so pass the human-readable float and fit-tool encodes it correctly.
    m.software_version = profile.software_version
    return m


def _event(event: Event, event_type: EventType, ts_ms: int) -> EventMessage:
    m = EventMessage()
    m.event = event
    m.event_type = event_type
    m.timestamp = ts_ms
    return m


def _record(p: TrackPoint) -> RecordMessage:
    m = RecordMessage()
    m.timestamp = _to_ms(p)
    if p.lat is not None:
        m.position_lat = p.lat
    if p.lon is not None:
        m.position_long = p.lon
    if p.altitude_m is not None:
        m.altitude = p.altitude_m
    if p.heart_rate is not None:
        m.heart_rate = p.heart_rate
    if p.cadence is not None:
        m.cadence = p.cadence
    if p.power_w is not None:
        m.power = p.power_w
    if p.speed_mps is not None:
        m.speed = p.speed_mps
    if p.distance_m is not None:
        m.distance = p.distance_m
    return m


def _lap(t0_ms: int, tN_ms: int, elapsed_s: float, agg: dict) -> LapMessage:
    m = LapMessage()
    m.timestamp = tN_ms
    m.start_time = t0_ms
    m.total_elapsed_time = elapsed_s
    m.total_timer_time = elapsed_s
    m.total_distance = agg["total_distance"]
    m.sport = Sport.CYCLING
    m.sub_sport = SubSport.VIRTUAL_ACTIVITY
    if agg["avg_hr"] is not None:
        m.avg_heart_rate = agg["avg_hr"]
    if agg["max_hr"] is not None:
        m.max_heart_rate = agg["max_hr"]
    if agg["avg_power"] is not None:
        m.avg_power = agg["avg_power"]
    if agg["max_power"] is not None:
        m.max_power = agg["max_power"]
    if agg["avg_cadence"] is not None:
        m.avg_cadence = agg["avg_cadence"]
    if agg["max_cadence"] is not None:
        m.max_cadence = agg["max_cadence"]
    if agg["total_calories"]:
        m.total_calories = agg["total_calories"]
    return m


def _session(t0_ms: int, tN_ms: int, elapsed_s: float, agg: dict) -> SessionMessage:
    m = SessionMessage()
    m.timestamp = tN_ms
    m.start_time = t0_ms
    m.total_elapsed_time = elapsed_s
    m.total_timer_time = elapsed_s
    m.total_distance = agg["total_distance"]
    m.sport = Sport.CYCLING
    m.sub_sport = SubSport.VIRTUAL_ACTIVITY
    m.first_lap_index = 0
    m.num_laps = 1
    if agg["avg_hr"] is not None:
        m.avg_heart_rate = agg["avg_hr"]
    if agg["max_hr"] is not None:
        m.max_heart_rate = agg["max_hr"]
    if agg["avg_power"] is not None:
        m.avg_power = agg["avg_power"]
    if agg["max_power"] is not None:
        m.max_power = agg["max_power"]
    if agg["avg_cadence"] is not None:
        m.avg_cadence = agg["avg_cadence"]
    if agg["max_cadence"] is not None:
        m.max_cadence = agg["max_cadence"]
    if agg["total_calories"]:
        m.total_calories = agg["total_calories"]
    return m


def _activity(tN_ms: int, elapsed_s: float) -> ActivityMessage:
    m = ActivityMessage()
    m.timestamp = tN_ms
    m.total_timer_time = elapsed_s
    m.num_sessions = 1
    m.type = Activity.MANUAL
    m.event = Event.ACTIVITY
    m.event_type = EventType.STOP
    return m


def _cleanup(out_path: Path) -> None:
    with contextlib.suppress(OSError):
        out_path.unlink(missing_ok=True)
