from mwgc import prompter
from mwgc.prompter import StdinPrompter


def test_stdin_prompter_reads_email_via_input(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": " jorge@example.com  ")
    assert StdinPrompter().email() == "jorge@example.com"


def test_stdin_prompter_reads_password_via_getpass(monkeypatch):
    monkeypatch.setattr(prompter.getpass, "getpass", lambda prompt="": "secret-pw")
    assert StdinPrompter().password() == "secret-pw"


def test_stdin_prompter_reads_mfa_via_input(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "  654321  ")
    assert StdinPrompter().mfa() == "654321"


def test_stdin_prompter_satisfies_prompter_protocol():
    p = StdinPrompter()
    # Structural check: the three required callables exist.
    assert callable(p.email)
    assert callable(p.password)
    assert callable(p.mfa)
