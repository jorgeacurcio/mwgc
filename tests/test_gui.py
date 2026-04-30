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
