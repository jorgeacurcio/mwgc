import os
import stat
import sys

import pytest

from mwgc.config import Config, load_config, save_config
from mwgc.errors import ConfigError


def test_round_trip(tmp_path):
    path = tmp_path / "config.toml"
    save_config(Config(garmin_email="a@b.c", garmin_password="pw"), path)
    loaded = load_config(path)
    assert loaded == Config(garmin_email="a@b.c", garmin_password="pw")


def test_save_creates_parent_dirs(tmp_path):
    path = tmp_path / "deeply" / "nested" / "config.toml"
    save_config(Config(garmin_email="a@b.c", garmin_password="pw"), path)
    assert path.exists()


def test_load_missing_file_raises(tmp_path):
    path = tmp_path / "nope.toml"
    with pytest.raises(ConfigError, match="not found"):
        load_config(path)


def test_load_malformed_toml_raises(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("this is = not [valid] = toml = at = all", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(path)


def test_load_missing_garmin_table_raises(tmp_path):
    path = tmp_path / "no_table.toml"
    path.write_text("[other]\nkey = 'value'\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="missing a \\[garmin\\] table"):
        load_config(path)


def test_load_missing_email_raises(tmp_path):
    path = tmp_path / "no_email.toml"
    path.write_text('[garmin]\npassword = "pw"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="missing garmin.email"):
        load_config(path)


def test_load_missing_password_raises(tmp_path):
    path = tmp_path / "no_pw.toml"
    path.write_text('[garmin]\nemail = "a@b.c"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="missing garmin.password"):
        load_config(path)


def test_save_escapes_quotes_and_backslashes(tmp_path):
    path = tmp_path / "tricky.toml"
    cfg = Config(garmin_email='odd "name"', garmin_password='back\\slash')
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded == cfg


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only chmod check")
def test_save_sets_600_on_posix(tmp_path):
    path = tmp_path / "secret.toml"
    save_config(Config(garmin_email="a@b.c", garmin_password="pw"), path)
    mode = os.stat(path).st_mode & (stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
    assert mode == 0o600
