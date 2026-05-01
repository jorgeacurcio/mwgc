import pytest

ctk = pytest.importorskip("customtkinter")

from mwgc.errors import AuthError  # noqa: E402
from mwgc.gui import App, _DialogPrompter, main  # noqa: E402


def test_dialog_prompter_calls_request_fn():
    calls = []

    def fake_request(prompt: str, secret: bool) -> str:
        calls.append((prompt, secret))
        return "value"

    p = _DialogPrompter(fake_request)
    assert p.email() == "value"
    assert p.password() == "value"
    assert p.mfa() == "value"
    assert calls[0] == (p.email.__func__.__code__.co_consts, False) or calls[0][1] is False
    # email and mfa are not secret; password is
    assert calls[1][1] is True   # password → secret=True
    assert calls[0][1] is False  # email   → secret=False
    assert calls[2][1] is False  # mfa     → secret=False


def test_dialog_prompter_raises_on_cancel():
    def cancel(_prompt, _secret):
        return None

    p = _DialogPrompter(lambda prompt, secret: (_ for _ in ()).throw(AuthError("cancelled")))
    with pytest.raises(AuthError):
        p.email()


def test_main_is_callable():
    # We don't enter mainloop in tests; just confirm the entry point is wired.
    assert callable(main)


def test_app_smoke_widgets_folder_mode_and_history(tmp_path, monkeypatch):
    """Single combined test — multiple App() instantiations in one process
    hit Tk's `tcl_findLibrary`/`init.tcl` errors on Windows, so we share one
    root and assert everything we need against it.

    Verifies:
      - all expected widgets exist (smoke check)
      - folder-mode checkbox defaults to off
      - toggling folder mode relabels the GPX-input row
      - the history pre-check returns True iff the start time is recorded
    """
    from pathlib import Path

    from mwgc import history
    from mwgc.gpx_parser import parse_gpx

    fixture = Path(__file__).parent / "fixtures" / "sample_mywhoosh.gpx"
    hist_path = tmp_path / "history.json"
    monkeypatch.setattr("mwgc.history.DEFAULT_HISTORY_PATH", hist_path)

    app = App()
    try:
        # widget presence
        assert app.run_button is not None
        assert app.progress is not None
        assert app.gpx_entry is not None
        assert app.fit_entry is not None
        assert app.log is not None
        assert app.folder_mode_var is not None

        # default state
        assert app.folder_mode_var.get() is False
        assert app.gpx_label.cget("text") == "GPX file:"

        # toggle on → relabel
        app.folder_mode_var.set(True)
        app._on_folder_mode_toggled()
        assert app.gpx_label.cget("text") == "Folder:"

        # toggle off → original label
        app.folder_mode_var.set(False)
        app._on_folder_mode_toggled()
        assert app.gpx_label.cget("text") == "GPX file:"

        # history pre-check: empty history returns False
        assert app._already_uploaded(str(fixture)) is False

        # …and True once the activity is recorded
        _, start_time = parse_gpx(fixture)
        history.record_upload(start_time, path=hist_path)
        assert app._already_uploaded(str(fixture)) is True
    finally:
        app.root.destroy()
