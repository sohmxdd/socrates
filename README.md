# Socrates

> Watches everything. Says almost nothing. When he finally speaks — listen.

Socrates is a passive terminal-watching agent for developers. It observes shell sessions and speaks up only when something is genuinely wrong: a forgotten `git push`, a leaked API key, a build that silently failed, or a process stuck long past its own historical baseline. It stays silent the rest of the time.

---

## How it works (30-second version)

Socrates is a background daemon that hooks into your shell. Every command you run gets logged locally. A periodic sweep checks all your known repos on its own clock — independent of any terminal window — so it catches a forgotten push even days later in a brand-new terminal. A suppression gate based on issue fingerprints (not timers) means it won't nag you while you're actively committing. Only genuinely ambiguous cases get a quick yes/no from a free cloud model (Groq). Everything else is local, offline, and deterministic.

**Output:** one short styled text message, optionally a chime. No voice, no TTS, no chat interface.

---

## Requirements

- Python 3.10+
- macOS or Linux (Windows/WSL: stretch goal, not yet supported)
- `zsh` or `bash` shell
- A free [Groq API key](https://console.groq.com/) for the LLM tiebreaker (optional — system works without it, ambiguous cases are silently dropped)

---

## Installation

```bash
# 1. Clone the repo
git clone https://github.com/sohmxdd/socrates.git
cd socrates

# 2. Install (editable recommended for now)
pip install -e .

# 3. Set your Groq API key (optional — for the LLM tiebreaker on ambiguous cases)
#    Add to your shell profile, NOT to a committed file:
export GROQ_API_KEY="your_key_here"
#    Or create ~/.socrates/.env (never committed — covered by .gitignore):
echo 'GROQ_API_KEY=your_key_here' > ~/.socrates/.env

# 4. Source the shell hook (add to your ~/.zshrc or ~/.bashrc)
# Zsh:
echo 'source /path/to/socrates/shell/socrates.zsh' >> ~/.zshrc
# Bash:
echo 'source /path/to/socrates/shell/socrates.bash' >> ~/.bashrc

# 5. Start the daemon
socrates start

# Optional: auto-start at login (recommended for normal use)
socrates install-daemon
```

---

## Daemon management

```bash
socrates start            # Start the daemon manually
socrates stop             # Stop the daemon
socrates status           # Show daemon status, DB stats, last sweep time
socrates install-daemon   # Register with launchd (macOS) or systemd (Linux) for auto-start
socrates uninstall-daemon # Remove the auto-start registration
```

---

## CLI reference

```bash
socrates logs [--tail N]          # Show last N events (default: 20)
socrates reset-feedback           # Clear suppression state (resets all snoozes and dismiss history)
socrates snooze <branch> [--hours N]  # Mute push reminders for a branch (default: 24h)
```

---

## Configuration

Socrates looks for `~/.socrates/config.yaml`. All keys are optional — unset keys fall back to defaults.

```yaml
# ~/.socrates/config.yaml

# Detection tuning
sweep_interval_seconds: 600       # How often the repo sweep runs (default: 10 min)
stuck_sweep_interval_seconds: 30  # How often in-flight processes are checked (default: 30s)
min_baseline_samples: 5           # Minimum history before stuck-process fires
baseline_k_factor: 2.0            # Stddev multiplier for stuck-process threshold

# LLM tiebreaker
groq_enabled: true
groq_model: "openai/gpt-oss-20b"  # Configurable — swap without code changes

# Presentation
color_enabled: true               # Set false or use NO_COLOR env var to disable ANSI
quiet_mode: false                 # Factual messages only (no personality)
sound_enabled: false
sound_file_path: ""               # Path to a .wav/.mp3/.aiff file; Socrates ships no default
sound_volume: 1.0

# Notifications
os_notifications_enabled: true
notification_escalation_hours: 2  # Hours of inactivity before pending → OS notification
```

---

## Architecture

```
Shell hook (preexec/precmd)
  │  command text, cwd, exit code, stderr tail [SAFE commands only]
  │  ↓ JSON over Unix socket (fire-and-forget, non-blocking)
Daemon (long-running, independent of any terminal)
  │  stores events → SQLite (~/.socrates/history.db)
  │  ↓
Rule Engine (deterministic, synchronous, sub-ms)
  │  forgotten_push · leaked_secrets · silent_failure · stuck_process
  │  → NONE / HIGH_CONFIDENCE / LOW_CONFIDENCE
  │  ↓ [LOW_CONFIDENCE only, never for leaked_secrets]
Groq LLM tiebreaker (optional, graceful-degrade on failure)
  │  scrubbed facts → yes/no + one sentence
  │  ↓
Intervention Gate (fingerprint dedup · snooze · dismiss feedback)
  │  → write pending file OR deliver at next prompt OR OS notification
  ↓
User sees one short message. Maybe hears a chime.
```

**Key property:** the daemon runs independently of any terminal. The periodic sweep checks all known repos on its own schedule. A push reminder persists as a pending file and is delivered at the first prompt of the next shell session opened in that repo — even days later, even in a completely new terminal window.

---

## What Socrates detects (v1)

| Rule | Mechanism | Network? |
|------|-----------|----------|
| Forgotten `git push` | `git rev-list @{u}..HEAD` | Never |
| Leaked secrets in commands | Regex + Shannon entropy | Never |
| Silent failures (exit 0, bad output) | stderr pattern + artifact check | Only if LOW_CONFIDENCE → Groq |
| Stuck process (past its baseline) | Per-command runtime history | Only if LOW_CONFIDENCE → Groq |

---

## Privacy

- **Leaked-secrets rule never touches the network by design.** If a secret is detected, the content stays local — it is never sent to Groq, logged externally, or telemetered anywhere.
- **Before any data reaches Groq**, it is scrubbed through the same secret scanner. Regex/entropy matches are replaced with `[REDACTED:<type>]`.
- **Groq API key** must live in an environment variable or `~/.socrates/.env`. It is never hardcoded, never logged, never committed to the repo.
- No telemetry of any kind.

---

## Resource footprint

Target (measured on idle daemon):

| Metric | Target |
|--------|--------|
| CPU (idle) | < 0.1% |
| RAM | < 30 MB |
| Disk (DB, 30 days) | < 10 MB |

*Actual measurements will be documented here after Phase 7 verification.*

---

## Status

**v0.1 — In active development.** See build phases in the spec. Not yet ready for daily use.

---

## License

MIT
