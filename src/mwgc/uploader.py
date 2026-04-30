from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectInvalidFileFormatError,
    HTTPError,
)

from mwgc.errors import AuthError, UploadError

ProgressCallback = Callable[[str, float], None]


class UploadOutcome(Enum):
    UPLOADED = "uploaded"
    DUPLICATE = "duplicate"


def upload(
    fit_path: Path,
    on_progress: ProgressCallback | None = None,
) -> UploadOutcome:
    client = _get_client()
    return _perform_upload(client, fit_path, on_progress=on_progress)


def _perform_upload(
    client: Any,
    fit_path: Path,
    on_progress: ProgressCallback | None = None,
) -> UploadOutcome:
    if on_progress is not None:
        on_progress("uploading", 0.0)

    try:
        response = client.upload_activity(str(fit_path))
    except GarminConnectAuthenticationError as e:
        raise AuthError(str(e)) from e
    except HTTPError as e:
        if _is_duplicate_http_error(e):
            if on_progress is not None:
                on_progress("uploaded", 1.0)
            return UploadOutcome.DUPLICATE
        raise UploadError(f"upload failed: {e}") from e
    except (GarminConnectInvalidFileFormatError, FileNotFoundError, ValueError) as e:
        raise UploadError(f"invalid upload input: {e}") from e
    except GarminConnectConnectionError as e:
        raise UploadError(f"connection error: {e}") from e
    except UploadError:
        raise
    except Exception as e:
        raise UploadError(f"upload failed: {e}") from e

    if _is_duplicate_response(response):
        outcome = UploadOutcome.DUPLICATE
    else:
        outcome = UploadOutcome.UPLOADED
    if on_progress is not None:
        on_progress("uploaded", 1.0)
    return outcome


def _is_duplicate_http_error(err: HTTPError) -> bool:
    response = getattr(err, "response", None)
    if response is None:
        return False
    if getattr(response, "status_code", None) != 409:
        return False
    body = getattr(response, "text", "") or ""
    return "duplicate" in body.lower()


def _is_duplicate_response(response: object) -> bool:
    if not isinstance(response, dict):
        return False
    detailed = response.get("detailedImportResult")
    if not isinstance(detailed, dict):
        return False
    failures = detailed.get("failures")
    if not isinstance(failures, list):
        return False
    for failure in failures:
        if not isinstance(failure, dict):
            continue
        for message in failure.get("messages", []) or []:
            if not isinstance(message, dict):
                continue
            content = (message.get("content") or "").lower()
            if "duplicate" in content:
                return True
    return False


def _get_client() -> Any:
    raise NotImplementedError("authenticated client setup is implemented in task 8")
