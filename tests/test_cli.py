import subprocess
import sys
from pathlib import Path

import pytest

from mwgc import cli, uploader
from mwgc.errors import AuthError, FitBuildError, UploadError
from mwgc.uploader import UploadOutcome

FIXTURE = Path(__file__).parent / "fixtures" / "sample_mywhoosh.gpx"


# ---------- happy path: --no-upload ----------


def test_smoke_no_upload_writes_fit_and_exits_zero(tmp_path):
    out = tmp_path / "out.fit"
    rc = cli.main(["--input", str(FIXTURE), "--output", str(out), "--no-upload"])
    assert rc == 0
    assert out.exists()
    assert out.stat().st_size > 0


def test_default_output_path_sits_next_to_input(tmp_path):
    src = tmp_path / "ride.gpx"
    src.write_bytes(FIXTURE.read_bytes())
    rc = cli.main(["--input", str(src), "--no-upload"])
    assert rc == 0
    assert (tmp_path / "ride.fit").exists()


def test_summary_line_on_success(tmp_path, capsys):
    out = tmp_path / "out.fit"
    cli.main(["--input", str(FIXTURE), "--output", str(out), "--no-upload"])
    captured = capsys.readouterr()
    last_line = captured.out.strip().splitlines()[-1]
    assert "written" in last_line.lower()
    assert "skipped" in last_line.lower()
    assert "8 points" in last_line


def test_progress_lines_go_to_stdout(tmp_path, capsys):
    out = tmp_path / "out.fit"
    cli.main(["--input", str(FIXTURE), "--output", str(out), "--no-upload"])
    captured = capsys.readouterr()
    progress_lines = [ln for ln in captured.out.splitlines() if ln.startswith("[")]
    assert progress_lines, "expected at least one progress line on stdout"
    # No errors on stderr for a successful run.
    assert captured.err == ""


# ---------- input errors ----------


def test_missing_input_file_exits_2(tmp_path, capsys):
    rc = cli.main(["--input", str(tmp_path / "nope.gpx"), "--no-upload"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "not found" in captured.err.lower()


def test_malformed_gpx_exits_2(tmp_path, capsys):
    bad = tmp_path / "bad.gpx"
    bad.write_text("not gpx at all")
    rc = cli.main(["--input", str(bad), "--no-upload"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "parse" in captured.err.lower()


def test_argparse_missing_required_input_exits_nonzero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code != 0


# ---------- upload outcomes ----------


def test_uploaded_outcome_in_summary(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(
        uploader,
        "upload",
        lambda path, on_progress=None, prompter=None: UploadOutcome.UPLOADED,
    )
    out = tmp_path / "out.fit"
    rc = cli.main(["--input", str(FIXTURE), "--output", str(out)])
    assert rc == 0
    captured = capsys.readouterr()
    last_line = captured.out.strip().splitlines()[-1]
    assert "uploaded to garmin connect" in last_line.lower()


def test_duplicate_outcome_exits_zero_and_is_reported(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(
        uploader,
        "upload",
        lambda path, on_progress=None, prompter=None: UploadOutcome.DUPLICATE,
    )
    out = tmp_path / "out.fit"
    rc = cli.main(["--input", str(FIXTURE), "--output", str(out)])
    assert rc == 0
    captured = capsys.readouterr()
    last_line = captured.out.strip().splitlines()[-1]
    assert "duplicate" in last_line.lower()


# ---------- upload error mapping ----------


def test_auth_error_exits_5(tmp_path, capsys, monkeypatch):
    def fail_auth(path, on_progress=None, prompter=None):
        raise AuthError("token expired")

    monkeypatch.setattr(uploader, "upload", fail_auth)
    out = tmp_path / "out.fit"
    rc = cli.main(["--input", str(FIXTURE), "--output", str(out)])
    assert rc == 5
    captured = capsys.readouterr()
    assert "auth" in captured.err.lower()


def test_upload_error_exits_4_and_keeps_fit(tmp_path, capsys, monkeypatch):
    def fail_upload(path, on_progress=None, prompter=None):
        raise UploadError("network down")

    monkeypatch.setattr(uploader, "upload", fail_upload)
    out = tmp_path / "out.fit"
    rc = cli.main(["--input", str(FIXTURE), "--output", str(out)])
    assert rc == 4
    captured = capsys.readouterr()
    assert "upload" in captured.err.lower()
    # FIT must remain on disk so the user can retry (R4.6).
    assert out.exists()


def test_fit_build_error_exits_3(tmp_path, capsys, monkeypatch):
    from mwgc import core

    def fail_build(*args, **kwargs):
        raise FitBuildError("synthetic")

    monkeypatch.setattr(core, "convert", fail_build)
    out = tmp_path / "out.fit"
    rc = cli.main(["--input", str(FIXTURE), "--output", str(out), "--no-upload"])
    assert rc == 3
    captured = capsys.readouterr()
    assert "fit build" in captured.err.lower()


# ---------- module invocation ----------


def test_python_dash_m_module_invocation(tmp_path):
    out = tmp_path / "out.fit"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mwgc",
            "--input",
            str(FIXTURE),
            "--output",
            str(out),
            "--no-upload",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert out.exists()
    assert "written" in result.stdout.lower()


# ---------- --latest ----------


def test_latest_picks_most_recent_gpx(tmp_path, capsys):
    """--latest should select the newest .gpx by mtime and convert it."""
    import time

    older = tmp_path / "old.gpx"
    newer = tmp_path / "new.gpx"
    import shutil

    shutil.copy(FIXTURE, older)
    time.sleep(0.05)
    shutil.copy(FIXTURE, newer)

    out = tmp_path / "out.fit"
    rc = cli.main(["--latest", str(tmp_path), "--output", str(out), "--no-upload"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "new.gpx" in captured.out
    assert out.exists()


def test_latest_no_gpx_in_dir_exits_2(tmp_path, capsys):
    rc = cli.main(["--latest", str(tmp_path), "--no-upload"])
    assert rc == 2
    assert "no gpx" in capsys.readouterr().err.lower()


def test_latest_dir_does_not_exist_exits_2(tmp_path, capsys):
    missing = tmp_path / "nonexistent"
    rc = cli.main(["--latest", str(missing), "--no-upload"])
    assert rc == 2


def test_input_and_latest_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--input", "ride.gpx", "--latest", "."])
    assert exc_info.value.code != 0


# ---------- upload history ----------


def test_latest_skips_when_already_in_history(tmp_path, capsys, monkeypatch):
    import shutil
    from mwgc import history

    hist_path = tmp_path / "history.json"
    shutil.copy(FIXTURE, tmp_path / "ride.gpx")

    # Monkeypatch history to use a tmp file and fake was_uploaded → True.
    monkeypatch.setattr(history, "DEFAULT_HISTORY_PATH", hist_path)

    # Pre-record the fixture's start time.
    from mwgc.gpx_parser import parse_gpx
    _, start_time = parse_gpx(FIXTURE)
    history.record_upload(start_time, path=hist_path)

    # Patch _default_token_dir so uploader doesn't touch real ~/.garminconnect.
    monkeypatch.setattr("mwgc.history.DEFAULT_HISTORY_PATH", hist_path)

    rc = cli.main(["--latest", str(tmp_path)])
    assert rc == cli.EXIT_SKIPPED
    assert "already uploaded" in capsys.readouterr().out.lower()


def test_latest_records_history_after_upload(tmp_path, capsys, monkeypatch):
    import shutil
    from mwgc import history

    hist_path = tmp_path / "history.json"
    shutil.copy(FIXTURE, tmp_path / "ride.gpx")

    monkeypatch.setattr("mwgc.history.DEFAULT_HISTORY_PATH", hist_path)

    # Stub out the upload so we don't hit Garmin.
    def fake_run(gpx_path, fit_path=None, do_upload=True, on_progress=None, prompter=None):
        from mwgc.models import ConversionResult
        fit = fit_path or Path(gpx_path).with_suffix(".fit")
        fit.touch()
        return ConversionResult(fit_path=fit, point_count=1, duration_s=1.0, distance_m=1.0), UploadOutcome.UPLOADED

    monkeypatch.setattr("mwgc.cli.core.run", fake_run)

    rc = cli.main(["--latest", str(tmp_path)])
    assert rc == 0

    from mwgc.gpx_parser import parse_gpx
    _, start_time = parse_gpx(FIXTURE)
    assert history.was_uploaded(start_time, path=hist_path)
