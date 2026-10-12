from __future__ import annotations

import concurrent.futures
import importlib.metadata
import json
import os
import re
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectInvalidFileFormatError,
    GarminConnectTooManyRequestsError,
    HTTPError,
)

from mwgc.errors import AuthError, UploadError
from mwgc.prompter import Prompter, StdinPrompter

ProgressCallback = Callable[[str, float], None]

DEFAULT_UPLOAD_TIMEOUT_S = 60.0
UPLOAD_TIMEOUT_ENV_VAR = "MWGC_UPLOAD_TIMEOUT_S"

# Older releases cannot log in since Garmin moved SSO behind Cloudflare TLS
# fingerprinting (March 2026). Keep in sync with pyproject.toml.
MIN_GARMINCONNECT_VERSION = (0, 3, 17)

RATE_LIMITED_MSG = (
    "Garmin rejected the login with HTTP 429 (rate limited / blocked). "
    "This is not a password problem. Do not retry now: repeated attempts "
    "extend the block. Wait a few hours and try once more."
)


class UploadOutcome(Enum):
    UPLOADED = "uploaded"
    DUPLICATE = "duplicate"


def upload(
    fit_path: Path,
    on_progress: ProgressCallback | None = None,
    prompter: Prompter | None = None,
) -> UploadOutcome:
    prompter = prompter or StdinPrompter()
    client = _get_client(prompter)
    try:
        return _perform_upload(client, fit_path, on_progress=on_progress)
    except AuthError:
        # Cached tokens may have expired between resume and upload (R4.4).
        # Force a fresh interactive login and retry exactly once.
        client = _interactive_login(_default_token_dir(), prompter)
        return _perform_upload(client, fit_path, on_progress=on_progress)


def _perform_upload(
    client: Any,
    fit_path: Path,
    on_progress: ProgressCallback | None = None,
) -> UploadOutcome:
    if on_progress is not None:
        on_progress("uploading", 0.0)

    timeout = _get_upload_timeout()

    try:
        response = _upload_with_timeout(client, fit_path, timeout)
    except concurrent.futures.TimeoutError as e:
        raise UploadError(f"upload timed out after {timeout:.0f}s") from e
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
        # Newer garminconnect wraps HTTP 409 "Duplicate Activity" responses
        # as connection errors with the marker in the message string,
        # rather than re-raising an HTTPError.  Treat that as DUPLICATE so
        # cross-PC deduplication works.
        if _is_duplicate_marker_in_message(str(e)):
            if on_progress is not None:
                on_progress("uploaded", 1.0)
            return UploadOutcome.DUPLICATE
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


def _is_duplicate_marker_in_message(text: str) -> bool:
    """Detect Garmin's 'Duplicate Activity' marker in any error message string.

    Used to recover the DUPLICATE outcome when garminconnect surfaces a 409
    response as a GarminConnectConnectionError (its current behaviour) rather
    than an HTTPError.
    """
    return "duplicate" in text.lower()


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


def _get_client(prompter: Prompter | None = None) -> Garmin:
    """Return an authenticated Garmin client, resuming from cached tokens if any."""
    prompter = prompter or StdinPrompter()
    _check_garminconnect_version()
    token_dir = _default_token_dir()
    if not token_dir.exists():
        return _interactive_login(token_dir, prompter)
    client = Garmin()
    try:
        client.login(str(token_dir))
    except (
        FileNotFoundError,
        GarminConnectAuthenticationError,
        OSError,
        json.JSONDecodeError,
    ):
        # Token cache is unusable (missing files, expired auth, old garth-format
        # tokens, unreadable bytes, corrupt JSON) â€” fall through to a fresh
        # interactive login.
        # Other exceptions (e.g. RuntimeError, ValueError) likely indicate a real
        # bug in garminconnect and should propagate so the user sees them.
        return _interactive_login(token_dir, prompter)
    except GarminConnectTooManyRequestsError as e:
        # Falling back to a credential login here would only extend the block.
        raise AuthError(RATE_LIMITED_MSG) from e
    except GarminConnectConnectionError as e:
        raise AuthError(f"could not reach Garmin Connect: {e}") from e
    return client


def _interactive_login(token_dir: Path, prompter: Prompter | None = None) -> Garmin:
    """Prompt for credentials, run a fresh login, persist tokens on success."""
    prompter = prompter or StdinPrompter()
    email = prompter.email()
    password = prompter.password()
    token_dir.mkdir(parents=True, exist_ok=True)
    # garminconnect >= MIN_GARMINCONNECT_VERSION is required: since March 2026 Garmin's SSO sits
    # behind Cloudflare TLS fingerprinting, and older releases (and garth's
    # login) get a 429 on every fresh login. Newer ones impersonate a browser via
    # curl_cffi and try several fallback SSO strategies.
    # retry_attempts=1: a failed login must not turn into repeated attempts,
    # which is what gets an account rate-limited in the first place.
    client = Garmin(
        email=email,
        password=password,
        prompt_mfa=prompter.mfa,
        retry_attempts=1,
    )
    try:
        # Passing token_dir tells garminconnect to persist the OAuth tokens
        # there after a successful login, so subsequent runs can resume without
        # re-entering credentials.
        client.login(str(token_dir))
    except GarminConnectAuthenticationError as e:
        raise AuthError(str(e)) from e
    except GarminConnectTooManyRequestsError as e:
        raise AuthError(RATE_LIMITED_MSG) from e
    except GarminConnectConnectionError as e:
        # garminconnect raises this when every SSO strategy failed for a
        # non-credential reason (WAF challenge, network, server error).
        raise AuthError(f"login failed (not a credential rejection): {e}") from e
    return client


def _check_garminconnect_version() -> None:
    """Fail fast when the installed garminconnect predates the SSO workaround.

    `git pull` updates pyproject.toml but not the virtualenv, so an old
    install would otherwise fail every login with an opaque 429.
    """
    installed = importlib.metadata.version("garminconnect")
    parts = tuple(int(n) for n in re.findall(r"\d+", installed)[:3])
    if parts < MIN_GARMINCONNECT_VERSION:
        required = ".".join(map(str, MIN_GARMINCONNECT_VERSION))
        raise AuthError(
            f"garminconnect {installed} is too old to log in to Garmin Connect "
            f"(need >= {required}). Reinstall the dependencies: "
            "pip install -r requirements.lock && pip install -e . --no-deps"
        )


def _default_token_dir() -> Path:
    return Path.home() / ".garminconnect"


def _get_upload_timeout() -> float:
    """Read MWGC_UPLOAD_TIMEOUT_S env var (default 60s).

    Falls back to the default if the env var is missing, empty, or
    non-numeric â€” we don't want a typo'd env var to break the upload.
    """
    raw = os.environ.get(UPLOAD_TIMEOUT_ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_UPLOAD_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_UPLOAD_TIMEOUT_S
    if value <= 0:
        return DEFAULT_UPLOAD_TIMEOUT_S
    return value


def _upload_with_timeout(client: Any, fit_path: Path, timeout: float) -> Any:
    """Run client.upload_activity in a worker thread with a hard timeout.

    Raises concurrent.futures.TimeoutError if the call doesn't return within
    the timeout window.  The underlying HTTP request will continue running
    in the background until it completes or the process exits â€” we accept
    that trade-off because Python can't cleanly cancel a blocked C-extension
    socket read across platforms.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(client.upload_activity, str(fit_path))
        return future.result(timeout=timeout)
