from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class TrackPoint:
    time: datetime
    lat: float | None
    lon: float | None
    altitude_m: float | None
    heart_rate: int | None
    cadence: int | None
    power_w: int | None
    speed_mps: float | None
    distance_m: float | None
    temperature_c: float | None = None


@dataclass(frozen=True)
class DeviceProfile:
    manufacturer: str
    product: str
    product_id: int
    serial_number: int
    software_version: float


@dataclass
class ConversionResult:
    fit_path: Path
    point_count: int
    duration_s: float
    distance_m: float
