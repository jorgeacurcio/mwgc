from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mwgc import core
from mwgc.errors import (
    AuthError,
    FitBuildError,
    GpxParseError,
    MwgcError,
    UploadError,
)
from mwgc.uploader import UploadOutcome

EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_BAD_INPUT = 2
EXIT_BUILD = 3
EXIT_UPLOAD = 4
EXIT_AUTH = 5


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"error: input file not found: {input_path}", file=sys.stderr)
        return EXIT_BAD_INPUT

    output_path = Path(args.output) if args.output else None
    do_upload = not args.no_upload

    printer = _ProgressPrinter()

    try:
        result, outcome = core.run(
            input_path,
            fit_path=output_path,
            do_upload=do_upload,
            on_progress=printer,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_BAD_INPUT
    except GpxParseError as e:
        print(f"error: GPX parse failed: {e}", file=sys.stderr)
        return EXIT_BAD_INPUT
    except FitBuildError as e:
        print(f"error: FIT build failed: {e}", file=sys.stderr)
        return EXIT_BUILD
    except AuthError as e:
        print(f"error: Garmin Connect authentication failed: {e}", file=sys.stderr)
        return EXIT_AUTH
    except UploadError as e:
        print(f"error: upload failed: {e}", file=sys.stderr)
        return EXIT_UPLOAD
    except MwgcError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_GENERIC
    except KeyboardInterrupt:
        print("\ncancelled.", file=sys.stderr)
        return EXIT_GENERIC

    print(_summary(result, outcome))
    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mwgc",
        description="Convert a MyWhoosh GPX export to a Garmin FIT activity "
        "and upload it to Garmin Connect.",
    )
    p.add_argument("--input", required=True, help="Path to the input GPX file.")
    p.add_argument(
        "--output",
        help="Path for the output FIT file (default: input path with .fit extension).",
    )
    p.add_argument(
        "--no-upload",
        action="store_true",
        help="Write the FIT file but skip uploading to Garmin Connect.",
    )
    return p


def _summary(result, outcome: UploadOutcome | None) -> str:
    base = (
        f"{result.fit_path} written "
        f"({result.point_count} points, "
        f"{result.duration_s:.1f}s, "
        f"{result.distance_m:.1f} m)"
    )
    if outcome is None:
        return f"{base}. Upload skipped."
    if outcome == UploadOutcome.UPLOADED:
        return f"{base}. Uploaded to Garmin Connect."
    if outcome == UploadOutcome.DUPLICATE:
        return f"{base}. Already on Garmin Connect (duplicate)."
    return base


class _ProgressPrinter:
    """Print one line per stage transition; dedupe identical (stage, percent) pairs."""

    def __init__(self) -> None:
        self._last: tuple[str, int] | None = None

    def __call__(self, stage: str, fraction: float) -> None:
        pct = int(round(fraction * 100))
        key = (stage, pct)
        if key == self._last:
            return
        self._last = key
        print(f"[{pct:3d}%] {stage}")
