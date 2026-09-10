"""
tests/test_daemon/test_daemon_health.py — Tests for daemon get_health_status method.
"""
from pathlib import Path
from socrates.config import SocratesConfig
from socrates.daemon.server import SocratesDaemon
from socrates.daemon.db import init_db


def test_daemon_health_status(tmp_path: Path) -> None:
    cfg = SocratesConfig()
    home = tmp_path / "home"
    home.mkdir()
    init_db(cfg.db_path(home))

    daemon = SocratesDaemon(config=cfg, home=home)
    health = daemon.get_health_status()

    assert health["db_exists"] is True
    assert health["db_size_bytes"] > 0
    assert "pid" in health
    assert "platform" in health
    assert health["home"] == str(home)
