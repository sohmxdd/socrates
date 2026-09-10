# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2026-09-10

### Added
- **Core Observer Daemon**: Background `asyncio` process with SQLite persistence (WAL mode).
- **Deterministic Rule Engine**:
  - `forgotten_push`: Unpushed git commit tracker with actively-committing silence guard.
  - `leaked_secrets`: Offline regex and Shannon entropy scanner for credentials.
  - `silent_failure`: Zero-exit detector tracking missing compiler artifacts and fatal stderr keywords.
  - `stuck_process`: Real-time execution monitor using Welford running baseline statistics.
- **Groq LLM Tiebreaker**: Privacy-first fallback for ambiguous events with pre-scrubbing.
- **Intervention Gate**: Issue fingerprinting (`SHA-256`), cooldown suppression, branch snooze, and dismissal sensitivity widening.
- **Shell Hooks**: Native lifecycle integrations for Zsh, Bash, and PowerShell without subshell wrapping.
- **Ambient Commentary Mode**: Opt-in "Socrates vs. Skeleton" philosophical ragebait commentary.
- **CLI Suite**: Full Click CLI (`start`, `stop`, `status`, `logs`, `snooze`, `reset-feedback`, `install-daemon`, `commentary`, `version`).
- **Diagnostics & Benchmarks**: `scripts/doctor.py` and `scripts/benchmark.py` diagnostic harnesses.
