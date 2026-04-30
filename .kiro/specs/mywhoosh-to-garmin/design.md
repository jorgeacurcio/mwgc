# Design Document

## Overview

Three-stage pipeline with a thin CLI wrapper:

```
+----------+    +-------------+    +-------------+    +-----------+
|  GPX     | -> |  Parser     | -> | FIT Builder | -> | Uploader  |
|  file    |    | (gpxpy +    |    | (Garmin FIT |    | (garth)   |
|          |    |  ext xml)   |    |  SDK)       |    |           |
+----------+    +-------------+    +-------------+    +-----------+
                       \                 /                  |
                        +--- core.convert() ---+            |
                                                            v
                                                     Garmin Connect
```

The CLI imports `core`. A future GUI imports the same `core`. No logic
lives in `cli.py` other than argument parsing and progress printing.

## Language and dependencies

- **Python 3.11+** — best ecosystem for FIT writing and Garmin Connect.
- **`gpxpy`** — GPX parsing; we read raw extension XML for power/cadence/HR.
- **Garmin FIT SDK for Python** (`garmin-fit-sdk`) — official, supports
  encode and decode. Alternative: `fit-tool` (community, simpler API) —
  pick at task 4 after a spike.
- **`garth`** — Garmin Connect auth + upload; handles MFA and token cache.
- **`pytest`** — tests.
- Packaging via `pyproject.toml` with a `mwgc` console-script entry point.

## Module layout

```
src/mwgc/
  __init__.py
  models.py        # TrackPoint, DeviceProfile, ConversionResult
  gpx_parser.py    # parse_gpx(path) -> list[TrackPoint], start_time
  fit_builder.py   # build_fit(points, profile, out_path) -> None
  devices.py       # FENIX_5_PLUS profile constants
  uploader.py      # upload(fit_path) -> UploadOutcome
  core.py          # convert(...), upload(...), end-to-end run(...)
  cli.py           # argparse + progress printing
tests/
  fixtures/sample_mywhoosh.gpx
  test_gpx_parser.py
  test_fit_builder.py
  test_core.py
  test_uploader.py  # garth mocked
pyproject.toml
README.md
```

## Data models (`models.py`)

```python
@dataclass(frozen=True)
class TrackPoint:
    time: datetime          # tz-aware UTC
    lat: float | None
    lon: float | None
    altitude_m: float | None
    heart_rate: int | None
    cadence: int | None
    power_w: int | None
    speed_mps: float | None
    distance_m: float | None  # cumulative; filled by parser

@dataclass(frozen=True)
class DeviceProfile:
    manufacturer: str        # "garmin"
    product: str             # "fenix5_plus"
    product_id: int          # 3111
    serial_number: int       # placeholder, configurable
    software_version: float  # e.g. 16.0

@dataclass
class ConversionResult:
    fit_path: Path
    point_count: int
    duration_s: float
    distance_m: float
```

## GPX parsing

MyWhoosh exports use these extension namespaces inside each `<trkpt>`:

- `gpxtpx:TrackPointExtension` containing `gpxtpx:hr`, `gpxtpx:cad`,
  optionally `gpxtpx:atemp`.
- `power` (sometimes namespaced as `pwr:PowerInWatts` or under the Garmin
  power extension) — value in watts.

`gpxpy` exposes `<extensions>` as raw `xml.etree.ElementTree.Element`
nodes. The parser walks them with a small, namespace-aware lookup so we
don't depend on prefix string matches.

Cumulative distance is computed at parse time using the haversine formula
between consecutive points. If lat/lon is missing for both endpoints of a
segment, fall back to `speed * dt`.

## FIT builder

Minimum message set for a Garmin Connect-clean cycling activity:

| Order | Message       | Notes                                            |
|------:|---------------|--------------------------------------------------|
|   1   | `file_id`     | type=activity, manufacturer, product, time_created, serial_number |
|   2   | `file_creator`| software_version                                 |
|   3   | `device_info` | device_index=creator, manufacturer, product, software_version, serial_number |
|   4   | `event`       | event=timer, event_type=start, timestamp=t0     |
|   5   | `record` × N  | one per trackpoint                               |
|   6   | `event`       | event=timer, event_type=stop_all, timestamp=tN  |
|   7   | `lap`         | start_time=t0, totals, sport=cycling, sub_sport=virtual_activity |
|   8   | `session`     | start_time=t0, totals, sport, sub_sport          |
|   9   | `activity`    | timestamp=tN, total_timer_time, num_sessions=1, type=manual, event=activity, event_type=stop |

Aggregates are computed in one pass over `TrackPoint` list:
- `avg_heart_rate`, `max_heart_rate`
- `avg_power`, `max_power`, `normalized_power` (optional)
- `avg_cadence`, `max_cadence`
- `total_calories` from a simple TSS-like estimate
  (`work_kj * efficiency_factor`, where `work_kj = sum(power_w * dt) / 1000`)
- `total_distance` from cumulative distance

Timestamps are written as FIT timestamps (seconds since 1989-12-31 UTC).
The FIT SDK handles that conversion if we pass `datetime` objects.

## Device profile

`devices.FENIX_5_PLUS`:
```python
DeviceProfile(
    manufacturer="garmin",
    product="fenix5_plus",
    product_id=3111,
    serial_number=3_141_592_653,  # stable placeholder
    software_version=16.0,
)
```

The serial is a constant so Garmin Connect groups uploads under the same
"device". A user-provided serial via env var (e.g. `MWGC_SERIAL`) is a
v1.1 nice-to-have, not required.

## Uploader

`garth` flow:
1. On import, attempt `garth.resume("~/.garth")`.
2. If resume fails or no tokens exist: prompt for email and password on
   stdin, call `garth.login(email, password)`. `garth` handles the MFA
   prompt internally.
3. `garth.client.upload(fit_path)`.
4. Map response to `UploadOutcome`:
   - `UPLOADED` (HTTP 201/202)
   - `DUPLICATE` (HTTP 409 with detailMessage containing "duplicate")
   - `AUTH_FAILED` → trigger one re-login + retry
   - `FAILED(reason)` → propagate

Token cache lives at `~/.garth` (garth default).

## Core orchestration

```python
def convert(gpx_path, fit_path, profile=FENIX_5_PLUS, on_progress=None):
    points, start = gpx_parser.parse_gpx(gpx_path)
    if not points:
        raise GpxParseError("no trackpoints")
    fit_builder.build_fit(points, profile, fit_path, on_progress=on_progress)
    return ConversionResult(...)

def upload(fit_path, on_progress=None) -> UploadOutcome: ...

def run(gpx_path, fit_path=None, do_upload=True, on_progress=None):
    """End-to-end. CLI calls this."""
```

`on_progress` is `Callable[[str, float], None]` — `(stage, fraction)`.
The CLI binds it to a stdout printer; a future GUI binds it to a progress
bar.

## Error handling

Custom exceptions in `mwgc.errors`:
- `GpxParseError`
- `FitBuildError`
- `UploadError`, with subclasses `AuthError`, `DuplicateActivity`

CLI exit codes:
| Code | Meaning                                  |
|-----:|------------------------------------------|
|  0   | Success (incl. duplicate handled cleanly)|
|  1   | Generic / unexpected                     |
|  2   | Bad input (file missing or malformed)    |
|  3   | FIT build failure                        |
|  4   | Upload failed (non-auth)                 |
|  5   | Auth failed after retry                  |

If `fit_builder` raises mid-write, it deletes the partial file in a
`finally` block.

## Testing strategy

- **Unit:**
  - `test_gpx_parser.py`: known fixture in/out — counts, first/last
    timestamp, HR/cadence/power extraction, missing-field tolerance.
  - `test_fit_builder.py`: build a FIT from a synthetic 60-point list,
    decode it back with the FIT SDK, assert message types and totals.
  - `test_core.py`: `convert` end-to-end with fixture; `run` with
    `do_upload=False`.
- **Integration (gated):** real upload to Garmin Connect — manual only,
  not in CI.
- **Mocked:** `test_uploader.py` uses a fake `garth.client` to assert
  duplicate handling and retry-once-on-auth.

## GUI extension path (informational, not v1)

When the GUI lands, it will import `mwgc.core.run(...)` and pass an
`on_progress` callback bound to its own widget. The only CLI-specific
file is `cli.py`. Upload prompts (email/password/MFA) currently use
`input()` — for the GUI we'll abstract these behind a `Prompter`
protocol in `uploader.py`. Flagged in tasks but not implemented in v1.
