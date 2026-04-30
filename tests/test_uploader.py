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


# ---------- public upload pending task 8 ----------


def test_public_upload_raises_until_task_8():
    with pytest.raises(NotImplementedError, match="task 8"):
        uploader.upload(Path("ignored.fit"))
