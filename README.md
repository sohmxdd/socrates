# Socrates

<p align="center">
  <img src="https://raw.githubusercontent.com/sohmxdd/socrates/main/assets/banner.png" alt="Socrates Banner" width="600" onerror="this.style.display='none'"/>
</p>

<p align="center">
  <strong>Watches everything. Says almost nothing. When he finally speaks — listen.</strong>
</p>

<p align="center">
  <a href="#benchmarks"><img src="https://img.shields.io/badge/CPU_Idle-0.00%25-brightgreen.svg" alt="Idle CPU"/></a>
  <a href="#benchmarks"><img src="https://img.shields.io/badge/RAM_RSS-~31_MB-blue.svg" alt="Memory Usage"/></a>
  <a href="#test-suite"><img src="https://img.shields.io/badge/Tests-240%20passed-success.svg" alt="Tests"/></a>
  <a href="#privacy--security"><img src="https://img.shields.io/badge/Privacy-100%25_Offline_Secrets-blueviolet.svg" alt="Privacy"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License"/></a>
  <img src="https://img.shields.io/badge/Python-3.10+-informational.svg" alt="Python Version"/>
  <img src="https://img.shields.io/badge/Platforms-macOS%20|%20Linux%20|%20Windows-lightgrey.svg" alt="Platforms"/>
</p>

---

**Socrates** is a deterministic, low-overhead terminal observer for developers. It quietly monitors your shell sessions and speaks up only when something is genuinely wrong: a forgotten `git push`, an accidentally pasted API key, a build that silently failed with exit code 0, or a process stuck long past its historical runtime baseline.

No walls of text. No annoying nag loops. No subshell wrappers that break `cd` or `export`.

---

## Visual Identity at the Prompt

Socrates provides clear visual demarcation right at your command prompt:

* <span style="color:#00ffff; font-weight:bold;">Socrates:</span> (**Bright Cyan**) — Critical high-confidence interventions (unpushed commits, detected secret leaks, silent process failures).
* <span style="color:#e5a50a; font-weight:bold;">Socrates observes:</span> (**Dark Yellow / Amber**) — Opt-in ambient philosophical commentary ("Socrates vs. Skeleton" mode) deconstructing everyday terminal commands.

---

## The Four Core Failure Modes

| Detection Mode | Condition | Timing | Privacy |
| :--- | :--- | :--- | :--- |
| **1. Forgotten Push** | Local commits ahead of upstream (`@{u}..HEAD`) | Periodic sweep (10m) after 5m inactivity | 100% Offline (Local Git) |
| **2. Leaked Secrets** | AWS, GitHub, Stripe, OpenAI keys or high-entropy tokens | Instant (before shell execution) | 100% Offline (Zero Network) |
| **3. Silent Failure** | Exit code 0, but missing declared artifact or fatal stderr | Immediately upon command exit | Local heuristics + scrubbed tiebreak |
| **4. Stuck Process** | Runtime exceeds historical baseline ($> 3\times \text{mean}$) | In-flight sweep (every 30s) | Local Welford statistical model |

---

## Architecture Flow

```
┌─────────────────────────────────────────────────────────────┐
│                      User Shell Process                     │
│  (Zsh: preexec/precmd | Bash: preexec | PowerShell: prompt) │
└──────────────────────────────┬──────────────────────────────┘
                               │ Non-blocking local socket / TCP
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                   Socrates Background Daemon                │
│ ┌──────────────────────┐        ┌─────────────────────────┐ │
│ │  Event Ingestion     │        │  Periodic Sweeps        │ │
│ │  - preexec (in-flight)│       │  - Repo sweep (10m)     │ │
│ │  - postcmd (exit tail│        │  - In-flight sweep (30s)│ │
│ └──────────┬───────────┘        └────────────┬────────────┘ │
│            ▼                                 ▼              │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │               Deterministic Rule Engine                 │ │
│ │  1. Forgotten Git Push (git rev-list @{u}..HEAD)        │ │
│ │  2. Leaked Secrets (Regex + Shannon Entropy) [Offline]  │ │
│ │  3. Silent Failure (Exit 0 + Stderr Error / Artifact)   │ │
│ │  4. Stuck Process (Runtime vs Welford baseline)         │ │
│ └──────────────────────────┬──────────────────────────────┘ │
│                            ▼                                │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │            Confidence Gate & Groq Tiebreaker            │ │
│ │  - HIGH_CONFIDENCE: Fast-path to Intervention Gate      │ │
│ │  - LOW_CONFIDENCE: Scrubbed Groq tiebreak (gpt-oss-20b) │ │
│ └──────────────────────────┬──────────────────────────────┘ │
│                            ▼                                │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │          Intervention Gate (Suppression & Snooze)       │ │
│ │  - SHA-256 fingerprint deduplication                    │ │
│ │  - Cooldown & Dismissal sensitivity widening            │ │
│ │  - Active-commit guard (< 5 min activity skips push)    │ │
│ └──────────────────────────┬──────────────────────────────┘ │
│                            ▼                                │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │                  Delivery & Presentation                │ │
│ │  - Cross-terminal pending delivery (~/.socrates/pending)│ │
│ │  - Desktop notification banner & sound cue (optional)   │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/sohmxdd/socrates.git
cd socrates

# Install package in editable mode
pip install -e .
```

### 2. Set Up Shell Integration

Add Socrates to your shell profile:

#### **Zsh** (`~/.zshrc`)
```bash
echo 'source /path/to/socrates/shell/socrates.zsh' >> ~/.zshrc
```

#### **Bash** (`~/.bashrc`)
```bash
echo 'source /path/to/socrates/shell/socrates.bash' >> ~/.bashrc
```

#### **PowerShell** (`$PROFILE`)
```powershell
. C:\path\to\socrates\shell\socrates.ps1
```

### 3. Start the Daemon

```bash
# Start background observer
socrates start

# (Recommended) Register auto-start service across system reboots
socrates install-daemon
```

---

## Ambient Commentary Mode ("Ragebait Socrates")

Beyond critical safety interventions, Socrates can optionally provide ambient philosophical commentary on your everyday terminal workflow. When enabled, Socrates observes your mundane commands and delivers dry, surgical, existential cross-examinations.

### Quick Setup

```bash
# Enable commentary locally in your current project
socrates init --commentary

# Enable globally with custom frequency
socrates commentary on --rate 0.8
```

---

## CLI Reference

```bash
socrates start              # Launch background daemon (or --foreground for debugging)
socrates stop               # Terminate running daemon
socrates status             # Show daemon health, database metrics, and tracked repos
socrates status --metrics   # Display raw numeric metrics and SQLite storage footprint
socrates logs               # View recent daemon activity logs
socrates snooze [BRANCH]    # Temporarily mute reminders on a branch (default: 24h)
socrates reset-feedback     # Clear all suppression states and dismiss counters
socrates install-daemon     # Install launchd plist (macOS) or systemd service (Linux)
socrates uninstall-daemon   # Remove background auto-start service
socrates version            # Display Socrates version and platform environment
```

---

## Benchmarks & Performance

Measured continuously with Python `psutil` across multi-sweep cycles:

| Metric | Measured Value | Standard / SLA |
| :--- | :--- | :--- |
| **Idle CPU** | **`0.00%`** | `< 0.5%` |
| **Sweep Peak CPU** | **`3.10%`** | Transient spike |
| **Average CPU** | **`0.92%`** | Negligible background load |
| **Memory Footprint (RSS)** | **`31.14 MB`** | `< 50 MB` |
| **Rule Latency (Offline)** | **`< 2 ms`** | Sub-millisecond |

---

## Documentation Deep Dives

* [Architecture Specification](docs/ARCHITECTURE.md)
* [Performance Benchmarks](docs/BENCHMARKS.md)
* [Configuration Guide](docs/CONFIGURATION.md)
* [Shell Hooks & Safety](docs/SHELL_HOOKS.md)
* [Detection Rules Deep Dive](docs/RULES.md)
* [Security & Privacy Guarantee](docs/SECURITY.md)
* [Troubleshooting Guide](docs/TROUBLESHOOTING.md)
* [Contributing Guidelines](docs/CONTRIBUTING.md)
* [Changelog](docs/CHANGELOG.md)

---

## License

MIT License. Designed and built with extreme care for developer flow.
