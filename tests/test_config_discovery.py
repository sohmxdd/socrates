"""
tests/test_config_discovery.py — Unit tests for project-local config discovery.
"""
from pathlib import Path
import pytest
import yaml

from socrates.config import find_local_config, load_config_for_cwd, load_config


def test_find_local_config_in_current_dir(tmp_path: Path):
    cfg_file = tmp_path / ".socrates.yaml"
    cfg_file.write_text("commentary_enabled: true\ncommentary_rate: 0.9\n", encoding="utf-8")

    found = find_local_config(tmp_path)
    assert found == cfg_file


def test_find_local_config_in_parent_dir(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    sub1 = root / "src"
    sub1.mkdir()
    sub2 = sub1 / "nested"
    sub2.mkdir()

    cfg_file = root / ".socrates.yaml"
    cfg_file.write_text("commentary_enabled: true\n", encoding="utf-8")

    assert find_local_config(sub2) == cfg_file
    assert find_local_config(sub1) == cfg_file
    assert find_local_config(root) == cfg_file


def test_find_local_config_yml_extension(tmp_path: Path):
    cfg_file = tmp_path / ".socrates.yml"
    cfg_file.write_text("commentary_enabled: true\n", encoding="utf-8")

    assert find_local_config(tmp_path) == cfg_file


def test_find_local_config_none_found(tmp_path: Path):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    # It might walk all the way up, but in tmp_path none exists
    found = find_local_config(empty_dir)
    # If the system root has no .socrates.yaml, this is None
    # We test with a controlled subpath
    assert found is None or not str(found).startswith(str(tmp_path))


def test_load_config_for_cwd_overrides(tmp_path: Path):
    cfg_file = tmp_path / ".socrates.yaml"
    cfg_file.write_text(
        "commentary_enabled: true\n"
        "commentary_rate: 0.95\n"
        "commentary_cooldown_seconds: 5\n"
        "commentary_skip_commands:\n"
        "  - 'mycmd'\n",
        encoding="utf-8",
    )

    loaded = load_config_for_cwd(tmp_path)
    assert loaded.commentary_enabled is True
    assert loaded.commentary_rate == 0.95
    assert loaded.commentary_cooldown_seconds == 5
    assert "mycmd" in loaded.commentary_skip_commands
