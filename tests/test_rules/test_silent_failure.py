"""tests/test_rules/test_silent_failure.py"""
import pytest

from socrates.rules.base import Confidence, CaptureClass, RuleType
from socrates.rules.silent_failure import (
    check_silent_failure,
    _classify_stderr,
    _infer_output_artifact,
)
from socrates.rules.base import EventData


def _make_event(
    command: str = "make build",
    command_sig: str = "make build",
    cwd: str = "/project",
    exit_code: int = 0,
    stderr_tail: str | None = None,
    capture_class: str = "SAFE",
    repo_path: str | None = "/project",
) -> EventData:
    return EventData(
        session_id="test-session",
        command=command,
        command_sig=command_sig,
        cwd=cwd,
        capture_class=capture_class,
        start_ts="2026-01-01T00:00:00+00:00",
        end_ts="2026-01-01T00:00:05+00:00",
        exit_code=exit_code,
        repo_path=repo_path,
        stderr_tail=stderr_tail,
    )


class TestClassifyStderr:
    def test_empty_stderr_returns_none(self) -> None:
        assert _classify_stderr("") == Confidence.NONE

    def test_blank_lines_only_returns_none(self) -> None:
        assert _classify_stderr("\n\n  \n") == Confidence.NONE

    def test_high_confidence_error_keyword(self) -> None:
        assert _classify_stderr("ERROR: could not connect") == Confidence.HIGH_CONFIDENCE

    def test_traceback_is_high_confidence(self) -> None:
        stderr = "Traceback (most recent call last):\n  File 'app.py', line 10, in main\nValueError: bad input"
        assert _classify_stderr(stderr) == Confidence.HIGH_CONFIDENCE

    def test_pytest_failed_is_high_confidence(self) -> None:
        assert _classify_stderr("FAILED tests/test_foo.py::test_bar [100%]") == Confidence.HIGH_CONFIDENCE

    def test_rust_compiler_error(self) -> None:
        assert _classify_stderr("error[E0308]: mismatched types") == Confidence.HIGH_CONFIDENCE

    def test_warning_is_low_confidence(self) -> None:
        assert _classify_stderr("WARNING: deprecated usage") == Confidence.LOW_CONFIDENCE

    def test_npm_warn_is_ignored(self) -> None:
        """npm warnings are extremely noisy and should be filtered out."""
        result = _classify_stderr("npm warn deprecated package@1.0.0")
        assert result == Confidence.NONE

    def test_deprecation_warning_in_site_packages_ignored(self) -> None:
        result = _classify_stderr("DeprecationWarning: blah blah site-packages/something.py")
        assert result == Confidence.NONE

    def test_build_failed_keyword(self) -> None:
        assert _classify_stderr("Build FAILED with 3 errors") == Confidence.HIGH_CONFIDENCE

    def test_permission_denied(self) -> None:
        assert _classify_stderr("Permission denied: /etc/shadow") == Confidence.HIGH_CONFIDENCE


class TestInferOutputArtifact:
    def test_gcc_minus_o(self) -> None:
        artifact = _infer_output_artifact("gcc -o myprogram main.c", "/project")
        assert artifact is not None
        assert "myprogram" in artifact

    def test_clang_minus_o(self) -> None:
        artifact = _infer_output_artifact("clang++ -o server server.cpp -lpthread", "/src")
        assert artifact is not None
        assert "server" in artifact

    def test_cp_destination(self) -> None:
        artifact = _infer_output_artifact("cp config.template config.local", "/")
        assert artifact is not None
        assert "config.local" in artifact

    def test_mv_destination(self) -> None:
        artifact = _infer_output_artifact("mv build/app /usr/local/bin/app", "/")
        assert artifact is not None
        assert "app" in artifact

    def test_go_build_minus_o(self) -> None:
        artifact = _infer_output_artifact("go build -o myserver ./cmd/server", "/project")
        assert artifact is not None
        assert "myserver" in artifact

    def test_git_status_no_artifact(self) -> None:
        assert _infer_output_artifact("git status", "/repo") is None

    def test_pytest_no_artifact(self) -> None:
        assert _infer_output_artifact("pytest tests/", "/repo") is None


class TestCheckSilentFailure:
    def test_nonzero_exit_code_returns_none(self) -> None:
        """Nonzero exit code is an explicit failure, not a silent one."""
        event = _make_event(exit_code=1, stderr_tail="ERROR: build failed")
        result = check_silent_failure(event)
        assert result.confidence == Confidence.NONE

    def test_clean_exit_0_no_stderr_returns_none(self) -> None:
        event = _make_event(exit_code=0, stderr_tail="")
        result = check_silent_failure(event)
        assert result.confidence == Confidence.NONE

    def test_exit_0_with_error_in_stderr_high_confidence(self) -> None:
        event = _make_event(
            exit_code=0,
            stderr_tail="ERROR: undefined symbol 'main'",
            capture_class="SAFE",
        )
        result = check_silent_failure(event)
        assert result.confidence == Confidence.HIGH_CONFIDENCE
        assert result.rule_type == RuleType.SILENT_FAILURE

    def test_exit_0_with_warning_in_stderr_low_confidence(self) -> None:
        event = _make_event(
            exit_code=0,
            stderr_tail="WARNING: deprecated flag --old-flag",
            capture_class="SAFE",
        )
        result = check_silent_failure(event)
        assert result.confidence == Confidence.LOW_CONFIDENCE

    def test_unsafe_capture_class_no_stderr_check(self) -> None:
        """UNSAFE commands have no stderr; rule should not fire on empty facts."""
        event = _make_event(
            command="vim myfile.txt",
            command_sig="vim",
            exit_code=0,
            stderr_tail=None,
            capture_class="UNSAFE",
        )
        result = check_silent_failure(event)
        assert result.confidence == Confidence.NONE

    def test_missing_artifact_high_confidence(self) -> None:
        """If gcc -o output doesn't exist, that's HIGH_CONFIDENCE."""
        import tempfile
        with tempfile.TemporaryDirectory(prefix="socrates_sf_") as tmpdir:
            event = _make_event(
                command=f"gcc -o {tmpdir}/myprogram main.c",
                command_sig="gcc",
                cwd=tmpdir,
                exit_code=0,
                stderr_tail=None,
                capture_class="SAFE",
            )
            result = check_silent_failure(event)
            assert result.confidence == Confidence.HIGH_CONFIDENCE
            assert "myprogram" in result.facts.get("symptom", "")

    def test_facts_contain_command(self) -> None:
        event = _make_event(
            exit_code=0,
            stderr_tail="FAILED tests/test_foo.py",
        )
        result = check_silent_failure(event)
        if result.confidence != Confidence.NONE:
            assert "command" in result.facts

    def test_fingerprint_key_is_non_empty(self) -> None:
        event = _make_event(
            exit_code=0,
            stderr_tail="ERROR: build failed",
        )
        result = check_silent_failure(event)
        if result.confidence != Confidence.NONE:
            assert len(result.fingerprint_key) > 0
