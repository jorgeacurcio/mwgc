from pathlib import Path

import pytest
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectInvalidFileFormatError,
    HTTPError,
)

from mwgc import uploader
from mwgc.errors import AuthError, UploadError
from mwgc.uploader import UploadOutcome, _perform_upload


class FakeClient:
    """Minimal stand-in for the python-garminconnect Garmin client."""

    def __init__(self, response=None, raises=None):
        self.response = response
        self.raises = raises
        self.calls: list[str] = []

    def upload_activity(self, path: str):
        self.calls.append(path)
        if self.raises is not None:
            raise self.raises
        return self.response


class FakeHTTPResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


# ---------- happy path ----------


def test_uploaded_returns_uploaded_outcome():
    client = FakeClient(
        response={"detailedImportResult": {"successes": [{"internalId": 1}], "failures": []}}
    )
    outcome = _perform_upload(client, Path("ride.fit"))
    assert outcome == UploadOutcome.UPLOADED
    assert client.calls == ["ride.fit"]


def test_unstructured_success_response_still_uploaded():
    # Garmin Connect responses vary; anything without the duplicate marker is UPLOADED.
    client = FakeClient(response={"uploadId": 12345})
    assert _perform_upload(client, Path("ride.fit")) == UploadOutcome.UPLOADED


# ---------- duplicate path ----------


def test_duplicate_in_response_failures_returns_duplicate():
    client = FakeClient(
        response={
            "detailedImportResult": {
                "successes": [],
                "failures": [
                    {"messages": [{"content": "Duplicate Activity"}]}
                ],
            }
        }
    )
    assert _perform_upload(client, Path("ride.fit")) == UploadOutcome.DUPLICATE


def test_duplicate_via_http_409_returns_duplicate():
    err = HTTPError(
        "409 Conflict",
        response=FakeHTTPResponse(409, '{"message": "Duplicate Activity"}'),
    )
    client = FakeClient(raises=err)
    assert _perform_upload(client, Path("ride.fit")) == UploadOutcome.DUPLICATE


def test_http_409_without_duplicate_marker_is_upload_error():
    err = HTTPError("409 Conflict", response=FakeHTTPResponse(409, "Some other conflict"))
    client = FakeClient(raises=err)
    with pytest.raises(UploadError):
        _perform_upload(client, Path("ride.fit"))


# ---------- error mapping ----------


def test_auth_error_is_remapped():
    client = FakeClient(raises=GarminConnectAuthenticationError("invalid creds"))
    with pytest.raises(AuthError, match="invalid creds"):
        _perform_upload(client, Path("ride.fit"))


def test_connection_error_becomes_upload_error():
    client = FakeClient(raises=GarminConnectConnectionError("network down"))
    with pytest.raises(UploadError, match="connection"):
        _perform_upload(client, Path("ride.fit"))


def test_invalid_file_format_becomes_upload_error():
    client = FakeClient(raises=GarminConnectInvalidFileFormatError("bad ext"))
    with pytest.raises(UploadError, match="invalid upload input"):
        _perform_upload(client, Path("ride.fit"))


def test_file_not_found_becomes_upload_error():
    client = FakeClient(raises=FileNotFoundError("missing"))
    with pytest.raises(UploadError, match="invalid upload input"):
        _perform_upload(client, Path("ride.fit"))


def test_other_http_error_becomes_upload_error():
    err = HTTPError("500 Server Error", response=FakeHTTPResponse(500, "boom"))
    client = FakeClient(raises=err)
    with pytest.raises(UploadError, match="upload failed"):
        _perform_upload(client, Path("ride.fit"))


def test_unexpected_exception_becomes_upload_error():
    client = FakeClient(raises=RuntimeError("???"))
    with pytest.raises(UploadError, match="upload failed"):
        _perform_upload(client, Path("ride.fit"))


# ---------- progress callback ----------


def test_progress_callback_is_invoked_on_success():
    client = FakeClient(response={})
    calls: list[tuple[str, float]] = []
    _perform_upload(client, Path("ride.fit"), on_progress=lambda s, f: calls.append((s, f)))
    assert calls[0] == ("uploading", 0.0)
    assert calls[-1] == ("uploaded", 1.0)


def test_progress_callback_is_invoked_on_duplicate_via_http():
    err = HTTPError("409", response=FakeHTTPResponse(409, "Duplicate Activity"))
    client = FakeClient(raises=err)
    calls: list[tuple[str, float]] = []
    _perform_upload(client, Path("ride.fit"), on_progress=lambda s, f: calls.append((s, f)))
    assert calls[0] == ("uploading", 0.0)
    assert calls[-1] == ("uploaded", 1.0)


def test_progress_callback_not_required():
    client = FakeClient(response={})
    # Must not raise when on_progress is None.
    assert _perform_upload(client, Path("ride.fit")) == UploadOutcome.UPLOADED


# ---------- auth flow + retry (task 8) ----------


class FakeGarmin:
    """Fake Garmin client wired to class-level sequences so a single test can
    configure per-instance behavior across multiple constructions."""

    instances: list["FakeGarmin"] = []
    login_raises_sequence: list[BaseException | None] = []
    upload_raises_sequence: list[BaseException | None] = []
    upload_response_sequence: list[dict] = []

    @classmethod
    def reset(cls) -> None:
        cls.instances = []
        cls.login_raises_sequence = []
        cls.upload_raises_sequence = []
        cls.upload_response_sequence = []

    def __init__(self, email=None, password=None, prompt_mfa=None, **kw):
        self.email = email
        self.password = password
        self.prompt_mfa = prompt_mfa
        self.login_calls: list[str | None] = []
        self.upload_calls: list[str] = []
        self.dumped_to: str | None = None
        self._idx = len(FakeGarmin.instances)
        FakeGarmin.instances.append(self)
        self.garth = _FakeGarth(self)

    def login(self, tokenstore=None):
        self.login_calls.append(tokenstore)
        if self._idx < len(FakeGarmin.login_raises_sequence):
            exc = FakeGarmin.login_raises_sequence[self._idx]
            if exc is not None:
                raise exc
        return (None, None)

    def upload_activity(self, path: str):
        self.upload_calls.append(path)
        if self._idx < len(FakeGarmin.upload_raises_sequence):
            exc = FakeGarmin.upload_raises_sequence[self._idx]
            if exc is not None:
                raise exc
        if self._idx < len(FakeGarmin.upload_response_sequence):
            return FakeGarmin.upload_response_sequence[self._idx]
        return {}


class _FakeGarth:
    def __init__(self, parent: FakeGarmin):
        self.parent = parent

    def dump(self, path: str) -> None:
        self.parent.dumped_to = path


@pytest.fixture
def fake_auth(monkeypatch, tmp_path):
    FakeGarmin.reset()
    monkeypatch.setattr(uploader, "Garmin", FakeGarmin)
    monkeypatch.setattr(uploader, "_prompt_email", lambda: "test@example.com")
    monkeypatch.setattr(uploader, "_prompt_password", lambda: "secret-pw")
    monkeypatch.setattr(uploader, "_prompt_mfa", lambda: "123456")
    token_dir = tmp_path / ".garminconnect"
    monkeypatch.setattr(uploader, "_default_token_dir", lambda: token_dir)
    return FakeGarmin, token_dir


def test_get_client_resumes_when_token_dir_exists(fake_auth):
    _, token_dir = fake_auth
    token_dir.mkdir()
    client = uploader._get_client()
    assert len(FakeGarmin.instances) == 1
    assert client is FakeGarmin.instances[0]
    # Resume client built without credentials, login called with the token dir.
    assert client.email is None
    assert client.password is None
    assert client.login_calls == [str(token_dir)]


def test_get_client_falls_through_when_token_dir_missing(fake_auth):
    _, token_dir = fake_auth
    assert not token_dir.exists()
    client = uploader._get_client()
    # One client only -- the interactive one. With creds set.
    assert len(FakeGarmin.instances) == 1
    assert client.email == "test@example.com"
    assert client.password == "secret-pw"
    assert client.dumped_to == str(token_dir)
    assert token_dir.exists()


def test_get_client_falls_through_when_resume_login_fails(fake_auth):
    _, token_dir = fake_auth
    token_dir.mkdir()
    FakeGarmin.login_raises_sequence = [
        GarminConnectAuthenticationError("token expired"),
        None,
    ]
    client = uploader._get_client()
    # Two clients: resume attempt (failed) + interactive (succeeded).
    assert len(FakeGarmin.instances) == 2
    assert client is FakeGarmin.instances[1]
    assert client.email == "test@example.com"
    assert client.dumped_to == str(token_dir)


def test_interactive_login_persists_tokens(fake_auth):
    _, token_dir = fake_auth
    client = uploader._interactive_login(token_dir)
    assert client.email == "test@example.com"
    assert client.password == "secret-pw"
    assert client.prompt_mfa is uploader._prompt_mfa
    assert client.login_calls == [None]
    assert client.dumped_to == str(token_dir)


def test_interactive_login_raises_auth_error_on_bad_creds(fake_auth):
    _, token_dir = fake_auth
    FakeGarmin.login_raises_sequence = [GarminConnectAuthenticationError("nope")]
    with pytest.raises(AuthError, match="nope"):
        uploader._interactive_login(token_dir)


def test_upload_happy_path_no_retry(fake_auth):
    _, token_dir = fake_auth
    token_dir.mkdir()
    FakeGarmin.upload_response_sequence = [{"detailedImportResult": {"successes": [{}]}}]
    outcome = uploader.upload(Path("ride.fit"))
    assert outcome == UploadOutcome.UPLOADED
    assert len(FakeGarmin.instances) == 1
    assert FakeGarmin.instances[0].upload_calls == ["ride.fit"]


def test_upload_retries_once_after_auth_error(fake_auth):
    """The required retry-once contract from task 8."""
    _, token_dir = fake_auth
    token_dir.mkdir()
    # Resume client succeeds at login but upload raises auth; the retry's
    # interactive client succeeds at both login and upload.
    FakeGarmin.upload_raises_sequence = [
        GarminConnectAuthenticationError("token expired mid-flight"),
        None,
    ]
    outcome = uploader.upload(Path("ride.fit"))
    assert outcome == UploadOutcome.UPLOADED
    # Two clients constructed: resume + retry-interactive.
    assert len(FakeGarmin.instances) == 2
    # Each client did exactly one upload attempt -- no third try.
    assert FakeGarmin.instances[0].upload_calls == ["ride.fit"]
    assert FakeGarmin.instances[1].upload_calls == ["ride.fit"]
    # The retry persisted fresh tokens.
    assert FakeGarmin.instances[1].dumped_to == str(token_dir)


def test_upload_propagates_auth_error_after_retry_also_fails(fake_auth):
    _, token_dir = fake_auth
    token_dir.mkdir()
    FakeGarmin.upload_raises_sequence = [
        GarminConnectAuthenticationError("first"),
        GarminConnectAuthenticationError("second"),
    ]
    with pytest.raises(AuthError, match="second"):
        uploader.upload(Path("ride.fit"))
    # No third attempt.
    assert len(FakeGarmin.instances) == 2
    assert FakeGarmin.instances[0].upload_calls == ["ride.fit"]
    assert FakeGarmin.instances[1].upload_calls == ["ride.fit"]


def test_upload_does_not_retry_on_non_auth_error(fake_auth):
    _, token_dir = fake_auth
    token_dir.mkdir()
    FakeGarmin.upload_raises_sequence = [GarminConnectConnectionError("network down")]
    with pytest.raises(UploadError, match="connection"):
        uploader.upload(Path("ride.fit"))
    # Single client; no retry was attempted.
    assert len(FakeGarmin.instances) == 1
