from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from mwgc import fit_builder, gpx_parser, history, uploader
from mwgc.devices import FENIX_5_PLUS
from mwgc.models import ConversionResult, DeviceProfile
from mwgc.prompter import Prompter
from mwgc.uploader import UploadOutcome

ProgressCallback = Callable[[str, float], None]


def convert(
    gpx_path: Path | str,
    fit_path: Path | str,
    profile: DeviceProfile = FENIX_5_PLUS,
    on_progress: ProgressCallback | None = None,
) -> ConversionResult:
    points, _start = gpx_parser.parse_gpx(gpx_path)
    fit_path = Path(fit_path)
    fit_builder.build_fit(points, profile, fit_path, on_progress=on_progress)
    return ConversionResult(
        fit_path=fit_path,
        point_count=len(points),
        duration_s=(points[-1].time - points[0].time).total_seconds(),
        distance_m=points[-1].distance_m or 0.0,
    )


def upload(
    fit_path: Path | str,
    on_progress: ProgressCallback | None = None,
    prompter: Prompter | None = None,
) -> UploadOutcome:
    return uploader.upload(Path(fit_path), on_progress=on_progress, prompter=prompter)


def run(
    gpx_path: Path | str,
    fit_path: Path | str | None = None,
    do_upload: bool = True,
    on_progress: ProgressCallback | None = None,
    prompter: Prompter | None = None,
) -> tuple[ConversionResult, UploadOutcome | None]:
    gpx_path = Path(gpx_path)
    fit_path = Path(fit_path) if fit_path is not None else gpx_path.with_suffix(".fit")

    convert_progress = _scope(on_progress, "convert", 0.0, 0.7) if do_upload else on_progress
    result = convert(gpx_path, fit_path, on_progress=convert_progress)

    upload_outcome: UploadOutcome | None = None
    if do_upload:
        upload_progress = _scope(on_progress, "upload", 0.7, 1.0)
        upload_outcome = upload(fit_path, on_progress=upload_progress, prompter=prompter)

        # R9.3: any successful upload — including DUPLICATE responses from
        # Garmin (the activity was already there from another machine) —
        # gets recorded in the local history so future runs (CLI --latest
        # or GUI) on this machine can dedupe without round-tripping Garmin.
        if upload_outcome in {UploadOutcome.UPLOADED, UploadOutcome.DUPLICATE}:
            try:
                _, start_time = gpx_parser.parse_gpx(gpx_path)
                history.record_upload(start_time)
            except Exception:  # noqa: BLE001 — history write is best-effort
                pass

    return result, upload_outcome


def _scope(
    parent: ProgressCallback | None,
    prefix: str,
    start: float,
    end: float,
) -> ProgressCallback | None:
    if parent is None:
        return None
    span = end - start

    def scoped(stage: str, fraction: float) -> None:
        parent(f"{prefix}/{stage}", start + span * fraction)

    return scoped
