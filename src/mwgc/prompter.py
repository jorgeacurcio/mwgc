from __future__ import annotations

import getpass
from typing import Protocol


class Prompter(Protocol):
    """Source of Garmin Connect credentials and MFA codes for the uploader."""

    def email(self) -> str: ...
    def password(self) -> str: ...
    def mfa(self) -> str: ...


class StdinPrompter:
    """Default Prompter; reads credentials from stdin (used by the CLI)."""

    def email(self) -> str:
        return input("Garmin Connect email: ").strip()

    def password(self) -> str:
        return getpass.getpass("Garmin Connect password: ")

    def mfa(self) -> str:
        return input("Garmin Connect MFA code: ").strip()
