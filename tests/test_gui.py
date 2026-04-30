import pytest

ctk = pytest.importorskip("customtkinter")

from mwgc.config import Config  # noqa: E402
from mwgc.gui import App, ConfigPrompter, main  # noqa: E402


def test_config_prompter_returns_config_values():
    cfg = Config(garmin_email="a@b.c", garmin_password="pw")
    seen = []

    def mfa_callback() -> str:
        seen.append("called")
        return "999999"

    p = ConfigPrompter(cfg, mfa_callback=mfa_callback)
    assert p.email() == "a@b.c"
    assert p.password() == "pw"
    assert p.mfa() == "999999"
    assert seen == ["called"]


def test_main_is_callable():
    # We don't enter mainloop in tests; just confirm the entry point is wired.
    assert callable(main)


def test_app_constructs_and_destroys_cleanly():
    app = App()
    try:
        # Smoke check: required widgets exist.
        assert app.run_button is not None
        assert app.progress is not None
        assert app.gpx_entry is not None
        assert app.fit_entry is not None
        assert app.log is not None
    finally:
        app.root.destroy()
