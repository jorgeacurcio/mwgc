from pathlib import Path

import pytest

from mwgc import core, uploader
from mwgc.errors import GpxParseError
from mwgc.models import ConversionResult
from mwgc.uploader import UploadOutcome

FIXTURE = Path(__file__).parent / "fixtures" / "sample_mywhoosh.gpx"


def test_convert_returns_conversion_result(tmp_path):
    out = tmp_path / "out.fit"
    result = core.convert(FIXTURE, out)
    assert isinstance(result, ConversionResult)
    assert result.fit_path == out
    assert result.point_count == 8
    assert result.duration_s == pytest.approx(7.0, abs=0.001)
    assert result.distance_m == pytest.approx(58.3, abs=0.5)
    assert out.exists()


def test_convert_propagates_gpx_parse_errors(tmp_path):
    bad = tmp_path / "bad.gpx"
    bad.write_text("not gpx at all")
    out = tmp_path / "out.fit"
    with pytest.raises(GpxParseError):
        core.convert(bad, out)


def test_run_without_upload(tmp_path):
    out = tmp_path / "out.fit"
    conv, outcome = core.run(FIXTURE, fit_path=out, do_upload=False)
    assert isinstance(conv, ConversionResult)
    assert outcome is None
    assert out.exists()


def test_run_default_fit_path_sits_next_to_gpx(tmp_path):
    src = tmp_path / "ride.gpx"
    src.write_bytes(FIXTURE.read_bytes())
    conv, _ = core.run(src, do_upload=False)
    assert conv.fit_path == src.with_suffix(".fit")
    assert conv.fit_path.exists()


def test_run_with_upload_threads_outcome(tmp_path, monkeypatch):
    out = tmp_path / "out.fit"
    upload_calls: list[Path] = []

    def fake_upload(path, on_progress=None, prompter=None):
        upload_calls.append(path)
        return UploadOutcome.UPLOADED

    monkeypatch.setattr(uploader, "upload", fake_upload)

    _, outcome = core.run(FIXTURE, fit_path=out, do_upload=True)
    assert outcome == UploadOutcome.UPLOADED
    assert upload_calls == [out]


def test_run_threads_duplicate_outcome(tmp_path, monkeypatch):
    out = tmp_path / "out.fit"
    monkeypatch.setattr(
        uploader,
        "upload",
        lambda path, on_progress=None, prompter=None: UploadOutcome.DUPLICATE,
    )
    _, outcome = core.run(FIXTURE, fit_path=out, do_upload=True)
    assert outcome == UploadOutcome.DUPLICATE


def test_run_progress_stages_are_namespaced(tmp_path, monkeypatch):
    out = tmp_path / "out.fit"

    def fake_upload(path, on_progress=None, prompter=None):
        if on_progress is not None:
            on_progress("uploading", 0.5)
            on_progress("done", 1.0)
        return UploadOutcome.UPLOADED

    monkeypatch.setattr(uploader, "upload", fake_upload)

    calls: list[tuple[str, float]] = []
    core.run(FIXTURE, fit_path=out, do_upload=True, on_progress=lambda s, f: calls.append((s, f)))

    stages = [s for s, _ in calls]
    assert any(s.startswith("convert/") for s in stages)
    assert any(s.startswith("upload/") for s in stages)

    # Convert phase fractions stay in [0, 0.7]; upload phase in [0.7, 1.0].
    convert_fractions = [f for s, f in calls if s.startswith("convert/")]
    upload_fractions = [f for s, f in calls if s.startswith("upload/")]
    assert all(0.0 <= f <= 0.7 + 1e-9 for f in convert_fractions)
    assert all(0.7 - 1e-9 <= f <= 1.0 + 1e-9 for f in upload_fractions)

    # Overall fractions are non-decreasing.
    fractions = [f for _, f in calls]
    assert fractions == sorted(fractions)


def test_run_no_progress_callback_works(tmp_path):
    out = tmp_path / "out.fit"
    conv, _ = core.run(FIXTURE, fit_path=out, do_upload=False, on_progress=None)
    assert conv.point_count == 8


def test_core_does_not_write_to_stdout_or_stderr(tmp_path, capsys):
    out = tmp_path / "out.fit"
    core.run(FIXTURE, fit_path=out, do_upload=False)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


# ---------- history recording (R9.3) ----------


def test_run_records_history_after_uploaded_outcome(tmp_path, monkeypatch):
    """Successful UPLOADED → activity start time written to history.json."""
    from mwgc import history

    hist_path = tmp_path / "history.json"
    monkeypatch.setattr("mwgc.history.DEFAULT_HISTORY_PATH", hist_path)
    monkeypatch.setattr(
        uploader,
        "upload",
        lambda path, on_progress=None, prompter=None: UploadOutcome.UPLOADED,
    )

    out = tmp_path / "out.fit"
    core.run(FIXTURE, fit_path=out, do_upload=True)

    from mwgc.gpx_parser import parse_gpx
    _, start_time = parse_gpx(FIXTURE)
    assert history.was_uploaded(start_time, path=hist_path)


def test_run_records_history_after_duplicate_outcome(tmp_path, monkeypatch):
    """DUPLICATE responses (already on Garmin from another machine) also record.

    This is the cross-PC dedup case: machine B running the same GPX after
    machine A uploaded it gets DUPLICATE from Garmin and writes the local
    history so subsequent --latest runs on B skip without round-tripping.
    """
    from mwgc import history

    hist_path = tmp_path / "history.json"
    monkeypatch.setattr("mwgc.history.DEFAULT_HISTORY_PATH", hist_path)
    monkeypatch.setattr(
        uploader,
        "upload",
        lambda path, on_progress=None, prompter=None: UploadOutcome.DUPLICATE,
    )

    out = tmp_path / "out.fit"
    core.run(FIXTURE, fit_path=out, do_upload=True)

    from mwgc.gpx_parser import parse_gpx
    _, start_time = parse_gpx(FIXTURE)
    assert history.was_uploaded(start_time, path=hist_path)


def test_run_does_not_record_history_when_not_uploading(tmp_path, monkeypatch):
    hist_path = tmp_path / "history.json"
    monkeypatch.setattr("mwgc.history.DEFAULT_HISTORY_PATH", hist_path)

    out = tmp_path / "out.fit"
    core.run(FIXTURE, fit_path=out, do_upload=False)

    assert not hist_path.exists()
