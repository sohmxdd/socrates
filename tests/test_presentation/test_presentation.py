"""tests/test_presentation/test_presentation.py — Tests for terminal formatting, sound playback, and OS notifications."""
import io
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from socrates.presentation.notify import send_os_notification
from socrates.presentation.sound import find_sound_player, play_sound
from socrates.presentation.terminal import (
    CYAN_BOLD,
    RESET,
    format_terminal_message,
    print_intervention,
    should_use_color,
)


class TestTerminalStyling:
    def test_should_use_color_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert should_use_color(color_enabled=True) is True
            assert should_use_color(color_enabled=False) is False

    def test_should_use_color_honors_no_color_env(self) -> None:
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            assert should_use_color(color_enabled=True) is False

        with patch.dict(os.environ, {"NO_COLOR": ""}):
            # Empty NO_COLOR means color is permitted per spec
            assert should_use_color(color_enabled=True) is True

    def test_format_terminal_message_colored(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            msg = format_terminal_message("You have 3 unpushed commits.", color_enabled=True)
            assert CYAN_BOLD in msg
            assert RESET in msg
            assert "Socrates:" in msg
            assert "You have 3 unpushed commits." in msg

    def test_format_terminal_message_plain(self) -> None:
        msg = format_terminal_message("You have 3 unpushed commits.", color_enabled=False)
        assert CYAN_BOLD not in msg
        assert msg == "Socrates: You have 3 unpushed commits."

    def test_format_preserves_existing_prefix(self) -> None:
        msg = format_terminal_message("Socrates: Is a secret truly a secret?", color_enabled=False)
        assert msg == "Socrates: Is a secret truly a secret?"

    def test_print_intervention_writes_to_stream(self) -> None:
        buf = io.StringIO()
        print_intervention("Alert message", color_enabled=False, file=buf)
        assert buf.getvalue().strip() == "Socrates: Alert message"


class TestSoundPlayback:
    def test_empty_or_nonexistent_file_returns_false(self) -> None:
        assert play_sound("") is False
        assert play_sound("/nonexistent/audio.wav") is False

    def test_sound_player_probe_and_cache(self) -> None:
        with patch("socrates.presentation.sound._CACHED_PLAYER", None), \
             patch("shutil.which", return_value="/usr/bin/afplay"):
            player = find_sound_player()
            assert player in ["afplay", "paplay", "aplay", "ffplay", "powershell"]

    def test_play_sound_spawns_subprocess(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"RIFF dummy sound data")
            sound_path = f.name

        try:
            with patch("socrates.presentation.sound.find_sound_player", return_value="afplay"), \
                 patch("subprocess.Popen") as mock_popen:
                res = play_sound(sound_path, volume=0.8)
                assert res is True
                mock_popen.assert_called_once()
                args, kwargs = mock_popen.call_args
                assert "afplay" in args[0]
                assert sound_path in args[0]
        finally:
            Path(sound_path).unlink(missing_ok=True)


class TestNotifications:
    def test_empty_notification_returns_false(self) -> None:
        assert send_os_notification("", "") is False

    @patch("sys.platform", "darwin")
    @patch("shutil.which")
    @patch("subprocess.Popen")
    def test_darwin_notification_terminal_notifier(self, mock_popen, mock_which) -> None:
        mock_which.return_value = "/usr/local/bin/terminal-notifier"
        res = send_os_notification("Socrates", "Process stuck")
        assert res is True
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "terminal-notifier"
        assert cmd[2] == "Socrates"

    @patch("sys.platform", "darwin")
    @patch("shutil.which", return_value=None)
    @patch("subprocess.Popen")
    def test_darwin_notification_osascript_fallback(self, mock_popen, mock_which) -> None:
        res = send_os_notification("Socrates", "Process stuck")
        assert res is True
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "osascript"
        assert 'display notification "Process stuck" with title "Socrates"' in cmd[2]

    @patch("sys.platform", "linux")
    @patch("shutil.which", return_value="/usr/bin/notify-send")
    @patch("subprocess.Popen")
    def test_linux_notification_notify_send(self, mock_popen, mock_which) -> None:
        res = send_os_notification("Socrates", "Process stuck")
        assert res is True
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd == ["notify-send", "Socrates", "Process stuck"]
