"""tests/test_cli.py — Tests for the Socrates Click CLI."""
import os
import signal
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from socrates.cli import main
from socrates.config import SocratesConfig
from socrates.daemon.db import init_db, upsert_suppression_fired


class TestCliBasics:
    def test_help(self) -> None:
        runner = CliRunner()
        res = runner.invoke(main, ["--help"])
        assert res.exit_code == 0
        assert "Socrates" in res.output
        assert "start" in res.output
        assert "stop" in res.output
        assert "status" in res.output
        assert "snooze" in res.output

    def test_version(self) -> None:
        runner = CliRunner()
        res = runner.invoke(main, ["--version"])
        assert res.exit_code == 0
        assert "0.1.0" in res.output


class TestCliStatus:
    def test_status_stopped(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory(prefix="socrates_cli_") as tmp:
            with patch("socrates.cli.get_socrates_home", return_value=Path(tmp)):
                res = runner.invoke(main, ["status"])
                assert res.exit_code == 0
                assert "STOPPED" in res.output

    def test_status_running(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory(prefix="socrates_cli_") as tmp:
            home = Path(tmp)
            pid_file = home / "daemon.pid"
            pid_file.write_text("99999", encoding="utf-8")

            with patch("socrates.cli.get_socrates_home", return_value=home), \
                 patch("socrates.cli._is_pid_alive", return_value=True):
                res = runner.invoke(main, ["status"])
                assert res.exit_code == 0
                assert "RUNNING (PID 99999)" in res.output


class TestCliStop:
    def test_stop_when_not_running(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory(prefix="socrates_cli_") as tmp:
            with patch("socrates.cli.get_socrates_home", return_value=Path(tmp)):
                res = runner.invoke(main, ["stop"])
                assert res.exit_code == 0
                assert "not running" in res.output

    def test_stop_when_running(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory(prefix="socrates_cli_") as tmp:
            home = Path(tmp)
            pid_file = home / "daemon.pid"
            pid_file.write_text("12345", encoding="utf-8")

            with patch("socrates.cli.get_socrates_home", return_value=home), \
                 patch("socrates.cli._is_pid_alive", return_value=True), \
                 patch("os.kill") as mock_kill, \
                 patch("subprocess.run"):
                res = runner.invoke(main, ["stop"])
                assert res.exit_code == 0
                assert "stopped" in res.output
                assert not pid_file.exists()


class TestCliResetFeedback:
    def test_reset_feedback(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory(prefix="socrates_cli_") as tmp:
            home = Path(tmp)
            db_path = home / "history.db"
            init_db(db_path)
            upsert_suppression_fired(db_path, fingerprint="fp1", rule_type="forgotten_push")

            pending_dir = home / "pending"
            pending_dir.mkdir(parents=True, exist_ok=True)
            (pending_dir / "test.json").write_text("{}", encoding="utf-8")

            with patch("socrates.cli.get_socrates_home", return_value=home):
                res = runner.invoke(main, ["reset-feedback"])
                assert res.exit_code == 0
                assert "reset" in res.output.lower()
                assert len(list(pending_dir.glob("*.json"))) == 0


class TestCliSnooze:
    def test_snooze_explicit_branch(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory(prefix="socrates_cli_") as tmp:
            home = Path(tmp)
            with patch("socrates.cli.get_socrates_home", return_value=home):
                res = runner.invoke(main, ["snooze", "feature-branch", "--hours", "12"])
                assert res.exit_code == 0
                assert "feature-branch" in res.output
                assert "12 hours" in res.output


class TestCliInstallUninstallDaemon:
    @patch("sys.platform", "darwin")
    @patch("subprocess.run")
    def test_install_daemon_darwin(self, mock_run) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory(prefix="socrates_cli_") as tmp:
            fake_home = Path(tmp) / "user_home"
            fake_home.mkdir()
            with patch("pathlib.Path.home", return_value=fake_home):
                res = runner.invoke(main, ["install-daemon"])
                assert res.exit_code == 0
                plist = fake_home / "Library" / "LaunchAgents" / "com.socrates.daemon.plist"
                assert plist.exists()
                assert "com.socrates.daemon" in plist.read_text(encoding="utf-8")

    @patch("sys.platform", "linux")
    @patch("subprocess.run")
    def test_install_daemon_linux(self, mock_run) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory(prefix="socrates_cli_") as tmp:
            fake_home = Path(tmp) / "user_home"
            fake_home.mkdir()
            with patch("pathlib.Path.home", return_value=fake_home):
                res = runner.invoke(main, ["install-daemon"])
                assert res.exit_code == 0
                service = fake_home / ".config" / "systemd" / "user" / "socrates.service"
                assert service.exists()
                assert "ExecStart" in service.read_text(encoding="utf-8")

    @patch("sys.platform", "darwin")
    @patch("subprocess.run")
    def test_uninstall_daemon_darwin(self, mock_run) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory(prefix="socrates_cli_") as tmp:
            fake_home = Path(tmp) / "user_home"
            plist_dir = fake_home / "Library" / "LaunchAgents"
            plist_dir.mkdir(parents=True)
            plist = plist_dir / "com.socrates.daemon.plist"
            plist.write_text("<plist/>", encoding="utf-8")

            with patch("pathlib.Path.home", return_value=fake_home):
                res = runner.invoke(main, ["uninstall-daemon"])
                assert res.exit_code == 0
                assert not plist.exists()

    @patch("sys.platform", "linux")
    @patch("subprocess.run")
    def test_uninstall_daemon_linux(self, mock_run) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory(prefix="socrates_cli_") as tmp:
            fake_home = Path(tmp) / "user_home"
            service_dir = fake_home / ".config" / "systemd" / "user"
            service_dir.mkdir(parents=True)
            service = service_dir / "socrates.service"
            service.write_text("[Unit]", encoding="utf-8")

            with patch("pathlib.Path.home", return_value=fake_home):
                res = runner.invoke(main, ["uninstall-daemon"])
                assert res.exit_code == 0
                assert not service.exists()
