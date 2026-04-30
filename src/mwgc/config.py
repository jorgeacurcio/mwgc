from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from mwgc.errors import ConfigError

DEFAULT_CONFIG_PATH: Path = Path.home() / ".mwgc" / "config.toml"


@dataclass(frozen=True)
class Config:
    garmin_email: str
    garmin_password: str


def load_config(path: Path | None = None) -> Config:
    path = path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise ConfigError(
            f"config file not found: {path}. "
            f'create it with a [garmin] table containing email and password keys.'
        )
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML in {path}: {e}") from e

    garmin = data.get("garmin")
    if not isinstance(garmin, dict):
        raise ConfigError(f"{path} is missing a [garmin] table")

    email = garmin.get("email")
    password = garmin.get("password")
    if not isinstance(email, str) or not email:
        raise ConfigError(f"{path} is missing garmin.email")
    if not isinstance(password, str) or not password:
        raise ConfigError(f"{path} is missing garmin.password")

    return Config(garmin_email=email, garmin_password=password)


def save_config(config: Config, path: Path | None = None) -> None:
    path = path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "[garmin]\n"
        f"email = {_quote_toml_string(config.garmin_email)}\n"
        f"password = {_quote_toml_string(config.garmin_password)}\n"
    )
    path.write_text(body, encoding="utf-8")
    if os.name == "posix":
        os.chmod(path, 0o600)


def _quote_toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
