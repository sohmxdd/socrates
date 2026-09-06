# Socrates

> Watches everything. Says almost nothing. When he finally speaks — listen.

Socrates is a passive terminal-watching agent for developers. It observes shell sessions and speaks up only when something is genuinely wrong: a forgotten `git push`, a leaked API key, a build that silently failed, or a process stuck long past its own historical baseline. It stays silent the rest of the time.

---

## How it works (30-second version)

Socrates is a background daemon that hooks into your shell. Every command you run gets logged locally. A periodic sweep checks all your known repos on its own clock — independent of any terminal window — so it catches a forgotten push even days later in a brand-new terminal. A suppression gate based on issue fingerprints (not timers) means it won't nag you while you're actively committing. Only genuinely ambiguous cases get a quick yes/no from a free cloud model (Groq). Everything else is local, offline, and deterministic.

**Output:** one short styled text message, optionally a non-verbal chime. No voice, no TTS, no chat interface.

---

## Requirements

- Python 3.10+
- macOS, Linux, or Windows
- `zsh`, `bash`, or `powershell`
- A free [Groq API key](https://console.groq.com/) for dynamic LLM interventions and ambient commentary (offline fallbacks included)

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/sohmxdd/socrates.git
cd socrates

# 2. Install package
pip install -e .

# 3. Set your Groq API key (optional — Socrates includes rich offline fallbacks)
#    Add to your shell profile (~/.zshrc, ~/.bashrc, or $PROFILE):
export GROQ_API_KEY="your_api_key_here"

# 4. Source the shell hook:
# For Zsh:
echo 'source /path/to/socrates/shell/socrates.zsh' >> ~/.zshrc

# For Bash:
echo 'source /path/to/socrates/shell/socrates.bash' >> ~/.bashrc

# For PowerShell (Windows / macOS / Linux):
# Add to your $PROFILE:
. C:\path\to\socrates\shell\socrates.ps1

# 5. Start the daemon
socrates start

# 6. (Recommended) Auto-start at login
socrates install-daemon
```

---

## Ambient Commentary Mode ("Ragebait Socrates")

Beyond critical safety interventions, Socrates can optionally provide ambient philosophical commentary on your everyday terminal workflow. When enabled, Socrates observes your commands and delivers dry, surgical, sardonically observant commentary right at your prompt.

### Quick Start in Any Project Directory

Initialize Socrates in any directory to tailor its behavior for that repository:

```bash
# Initialize local .socrates.yaml with ambient commentary enabled (60% trigger chance)
socrates init --commentary

# Or specify a higher/lower commentary rate (e.g. 90% chance)
socrates init --commentary --rate 0.9
```

### Commentary CLI Commands

```bash
socrates commentary on [--rate 0.8]   # Enable commentary (local or global)
socrates commentary off               # Disable commentary
socrates commentary status            # Show current scope, rate, and cooldown
socrates commentary test "pytest"     # Preview Socrates' observation for a command
```

### Visual Distinction at the Prompt

- **Amber (`Socrates observes:`):** Ambient commentary and dry philosophical observations on commands, directory changes, or repeated retries.
- **Cyan (`Socrates:`):** Critical high-priority interventions (forgotten unpushed commits, detected secret leaks, silent process failures).

---

## Daemon Management

```bash
socrates start            # Start daemon in background (or --foreground for debug)
socrates stop             # Stop running daemon
socrates status           # Health, PID, DB stats, tracked repos, and in-flight processes
socrates install-daemon   # Register with launchd (macOS) or systemd user (Linux)
socrates uninstall-daemon # Unregister auto-start daemon service
```

---

## CLI Reference

```bash
socrates logs [--tail N]              # View recent daemon logs
socrates reset-feedback               # Clear suppression state (resets all snoozes and dismiss history)
socrates snooze [BRANCH] [--hours N]  # Mute push reminders for a branch (default: current branch, 24h)
```

---

## Configuration

Socrates looks for `~/.socrates/config.yaml`. All keys are optional — unset keys fall back to defaults.

```yaml
# ~/.socrates/config.yaml

# ── Detection tuning ──────────────────────────────────────────────────────────
sweep_interval_seconds: 600       # How often repo push sweep runs (default: 10 min)
stuck_sweep_interval_seconds: 30  # How often in-flight processes are checked (default: 30s)
active_commit_window_seconds: 300 # Skip push alert if commit was made within 5 min
min_baseline_samples: 5           # Minimum history before stuck-process rule fires
baseline_k_factor: 2.0            # Stddev multiplier for stuck-process threshold
dismiss_threshold: 3              # Dismiss count before permanent rule suppression
intervention_cooldown_seconds: 3600 # Minimum seconds between identical alerts
dismiss_widening_factor: 1.5      # Sensitivity widening for frequently dismissed repos

# ── LLM tiebreaker ────────────────────────────────────────────────────────────
groq_enabled: true
groq_model: "openai/gpt-oss-20b"  # Fast, free-tier cloud model for ambiguous events
groq_timeout_seconds: 8           # Timeout before falling back to silence
groq_min_call_interval_seconds: 2 # Client-side rate-limit throttle

# ── Presentation ──────────────────────────────────────────────────────────────
color_enabled: true               # Set false or use NO_COLOR env var to disable ANSI
quiet_mode: false                 # Factual messages only (no Socratic persona)
sound_enabled: false              # Play audio cue on intervention
sound_file_path: ""               # Path to user-supplied audio file (.wav/.mp3/.aiff)
sound_volume: 1.0

# ── Notifications ─────────────────────────────────────────────────────────────
os_notifications_enabled: true    # Enable desktop notification banners
notification_escalation_hours: 2  # Inactivity hours before pending alert escalates to OS banner
```

---

## Architecture

```
Shell Hook (preexec / precmd)
  │  Captures command text, cwd, exit code, stderr tail [SAFE commands only]
  │  ↓ JSON over local Unix socket (fire-and-forget, non-blocking)
Background Daemon (long-running, independent of terminal lifecycle)
  │  Stores events → SQLite (~/.socrates/history.db)
  │  ↓
Rule Engine (deterministic, sub-millisecond)
  │  forgotten_push · leaked_secrets · silent_failure · stuck_process
  │  → NONE / HIGH_CONFIDENCE / LOW_CONFIDENCE
  │  ↓ [LOW_CONFIDENCE only; leaked_secrets NEVER leaves machine]
Groq LLM Tiebreaker (scrubbed prompt, strict JSON contract, graceful degradation)
  │  ↓
Intervention Gate (fingerprint dedup · snooze · dismiss feedback widening)
  │  ↓
Delivery (pending file pickup at next prompt / OS notification)
  ↓
Socrates speaks: Cyan prefix, dry Socratic question, optional chime.
```

---

## The 4 Detection Scenarios

### 1. Forgotten `git push`
- **Scenario:** Developer commits to a branch and closes the terminal or walks away.
- **Daemon behavior:** Periodic sweep checks `git rev-list @{u}..HEAD`. If older than `active_commit_window_seconds` (not actively committing), writes a pending message keyed to the repo.
- **Message:**
  ```text
  Socrates: You have created 3 commits on 'main', yet they remain trapped upon this machine.
  Tell me — what is the purpose of a commit that nobody can pull? (run 'socrates snooze' to mute this branch for today)
  ```

### 2. Leaked Secrets in Commands
- **Scenario:** Developer pastes an AWS key, GitHub PAT, Stripe secret, or private key into a shell command.
- **Daemon behavior:** Preexec hook scans command with regex + Shannon entropy. **Hard constraint: never touches network or Groq.**
- **Message:**
  ```text
  Socrates: An AWS Access Key ID sits plainly in that command, for any shell history or log to find.
  Tell me — is a secret truly a secret, if you have just shouted it into your terminal?
  ```

### 3. Silent Failures (Exit 0 with Errors)
- **Scenario:** Build tool or script exits 0, but stderr contains compilation errors or expected output artifact was not created.
- **Daemon behavior:** Inspects stderr patterns and filesystem artifacts.
- **Message:**
  ```text
  Socrates: The command claimed success with exit code 0, yet 'dist/bundle.js' does not exist.
  Tell me — which one of you is lying?
  ```

### 4. Stuck Process (Runtime Anomaly)
- **Scenario:** Test suite or script hangs in a loop, running 10x longer than its own historical baseline for that repository.
- **Daemon behavior:** In-flight sweep compares elapsed runtime against SQLite running baseline. Dispatches immediate OS notification banner.
- **Message:**
  ```text
  Socrates: Process 'pytest' normally finishes in 12 seconds. It has now been running for 180 seconds.
  Tell me — at what point does 'running' become 'waiting'?
  ```

---

## Privacy & Security

- **Leaked secrets never leave the machine.** The rule evaluates 100% locally and is explicitly blocked from reaching Groq.
- **Payload scrubbing:** All string fields in ambiguous events are passed through the local secret scanner before Groq prompt construction. Matched secrets are replaced with `[REDACTED:<type>]`.
- **Zero telemetry:** No external analytics, telemetry, or tracking.
- **Key security:** `GROQ_API_KEY` is loaded only from environment variables or `~/.socrates/.env` (which is gitignored).

---

## Resource Footprint (Measured)

Measured on Python 3.14 on idle background daemon:

| Metric | Target | Measured |
|--------|--------|----------|
| Idle CPU | < 0.1% | **< 0.05%** |
| Idle RAM | < 30 MB | **29.2 MB** |
| Event Storage | < 10 MB | **~0.1 MB** (10,000 event pruning) |
| Hook Overhead | < 5 ms | **< 2 ms** (detached socket client) |

---

## Verification & Acceptance Criteria

- [x] **Low interruption rate:** 0–3 genuine interventions/day targeted via fingerprint dedup, snooze, and dismiss widening.
- [x] **Actively committing guard:** Multi-commit sequences produce zero nags mid-session.
- [x] **Closed-terminal delivery:** Pending files keyed by repo hash surface in new terminals opened days later.
- [x] **4 demoable failure modes:** Forgotten push, leaked secrets, silent failure, stuck process.
- [x] **Zero paid tiers:** Fully functional offline; optional Groq free tier for ambiguous tiebreaking with complete graceful degradation.
- [x] **Lightweight:** 29.2 MB RAM, < 0.05% idle CPU.
- [x] **Modular architecture:** Detection engine runs independently with presentation and personality completely disabled.
- [x] **Test suite:** 177 unit and integration tests passing.

---

## License

MIT
