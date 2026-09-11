# Socrates

<p align="center">
  <img src="https://raw.githubusercontent.com/sohmxdd/socrates/main/assets/banner.png" alt="Socrates Banner" width="600" onerror="this.style.display='none'"/>
</p>

<p align="center">
  <strong>Watches everything. Says almost nothing. When he finally speaks — listen.</strong>
</p>

<p align="center">
  <a href="https://github.com/sohmxdd/socrates/releases"><img src="https://img.shields.io/badge/version-1.0.0-00ffff.svg?style=flat-square" alt="Version 1.0.0"/></a>
  <a href="#benchmarks"><img src="https://img.shields.io/badge/CPU_Idle-0.00%25-brightgreen.svg?style=flat-square" alt="Idle CPU"/></a>
  <a href="#benchmarks"><img src="https://img.shields.io/badge/RAM_RSS-~31_MB-blue.svg?style=flat-square" alt="Memory Usage"/></a>
  <a href="tests"><img src="https://img.shields.io/badge/Tests-249_passed-success.svg?style=flat-square" alt="Tests"/></a>
  <a href="docs/SECURITY.md"><img src="https://img.shields.io/badge/Privacy-100%25_Offline_Secrets-blueviolet.svg?style=flat-square" alt="Privacy"/></a>
  <a href="docs/SECURITY.md"><img src="https://img.shields.io/badge/Telemetry-Zero-black.svg?style=flat-square" alt="Zero Telemetry"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square" alt="License"/></a>
  <img src="https://img.shields.io/badge/Python-3.10%20|%203.11%20|%203.12%20|%203.13%20|%203.14-informational.svg?style=flat-square" alt="Python Version"/>
  <img src="https://img.shields.io/badge/Platforms-macOS%20|%20Linux%20|%20Windows-lightgrey.svg?style=flat-square" alt="Platforms"/>
</p>

---

**Socrates** is a deterministic, low-overhead terminal observer for developers. It quietly monitors your shell sessions and speaks up only when something is genuinely wrong: a forgotten `git push`, an accidentally pasted API key, a build that silently failed with exit code 0, or a process stuck long past its historical runtime baseline.

No walls of text. No annoying nag loops. No subshell wrappers that break `cd` or `export`.

## Why Socrates?

Traditional terminal tools either nag you constantly or do nothing until disaster strikes. Socrates occupies the quiet middle ground:

| Capability | Traditional Linters | Copilot / AI Chats | Shell History | **Socrates** |
| :--- | :--- | :--- | :--- | :--- |
| **Forgotten Git Push** | ❌ None | ❌ None | ❌ None | **✅ 10m sweep + inactivity guard** |
| **Accidental Secret Paste** | ⚠️ Only in committed files | ❌ May exfiltrate in prompts | ❌ Permanently recorded | **✅ Blocked before/at execution** |
| **Exit 0 Build Silent Failures**| ❌ Assumes 0 = success | ❌ Unaware of artifacts | ❌ Unaware | **✅ Verifies declared disk artifacts** |
| **Hung/Stuck Background Tasks** | ❌ None | ❌ None | ❌ None | **✅ Compares vs historical baseline** |
| **Subshell Wrapping Risk** | N/A | N/A | N/A | **✅ 100% Zero Subshell Wrappers** |
| **Interruption Frequency** | 🔴 Constant warnings | 🔴 Interactive chat | ⚪ Passive log | **🟢 0–3 genuine alerts / day** |
<details>
<summary><strong>Table of Contents</strong> (click to expand)</summary>

- [Visual Identity at the Prompt](#visual-identity-at-the-prompt)
- [The Four Core Failure Modes](#the-four-core-failure-modes)
- [Architecture Flow](#architecture-flow)
- [Quick Start](#quick-start)
  - [1. Installation](#1-installation)
  - [2. Shell Integration](#2-set-up-shell-integration)
  - [3. Daemon Launch](#3-start-the-daemon)
- [Ambient Commentary Mode ("Ragebait Socrates")](#ambient-commentary-mode-ragebait-socrates)
- [CLI Reference](#cli-reference)
- [Benchmarks & Performance](#benchmarks--performance)
- [Documentation Deep Dives](#documentation-deep-dives)
- [License](#license)

</details>

---

## Visual Identity at the Prompt

Socrates provides clear visual demarcation right at your command prompt:

* <span style="color:#00ffff; font-weight:bold;">Socrates:</span> (**Bright Cyan**) — Critical high-confidence interventions (unpushed commits, detected secret leaks, silent process failures).
* <span style="color:#e5a50a; font-weight:bold;">Socrates observes:</span> (**Dark Yellow / Amber**) — Opt-in ambient philosophical commentary ("Socrates vs. Skeleton" mode) deconstructing everyday terminal commands.

```text
┌── terminal ────────────────────────────────────────────────────────────────────────┐
│ $ git commit -m "fix auth token refresh"                                           │
│ [main 8f3d12c] fix auth token refresh                                              │
│                                                                                    │
│ Socrates: Two commits sit on 'main', visible to no one.                            │
│ Tell me — is code truly written if no remote ever receives it?                     │
│                                                                                    │
│ $ git diff                                                                         │
│ Socrates observes: You just pulled a diff, as if the repository has developed       │
│ self-awareness in the last twenty seconds.                                         │
│ $                                                                                  │
└────────────────────────────────────────────────────────────────────────────────────┘
```

### The Two Voices of Socrates

1. **The Interventions (Cyan)**: Reserved for genuine dangers:
   > **Socrates:** *Exit code zero. Stderr reporting a fatal authentication failure. These two facts cannot both be true, and yet here they are, coexisting peacefully in your shell history.*

2. **The Socratic Cross-Examinations (Amber)**: The uninvited ancient philosopher deconstructing everyday developer delusions:
   > **Socrates observes:** *Tell me, developer: do you run `git status` because you believe the working tree evolved since your keystroke fifteen seconds ago, or because contemplating actual logic fills you with dread?*

---

## The Four Core Failure Modes

| Detection Mode | Condition | Timing | Privacy |
| :--- | :--- | :--- | :--- |
| **1. Forgotten Push** | Local commits ahead of upstream (`@{u}..HEAD`) | Periodic sweep (10m) after 5m inactivity | 100% Offline (Local Git) |
| **2. Leaked Secrets** | AWS, GitHub, Stripe, OpenAI keys or high-entropy tokens | Instant (before shell execution) | 100% Offline (Zero Network) |
| **3. Silent Failure** | Exit code 0, but missing declared artifact or fatal stderr | Immediately upon command exit | Local heuristics + scrubbed tiebreak |
| **4. Stuck Process** | Runtime exceeds historical baseline ($> 3\times \text{mean}$) | In-flight sweep (every 30s) | Local Welford statistical model |

---

## Non-Intrusive Prompt Lifecycle

Socrates is engineered with a fundamental constraint: **never break developer muscle memory**.

```
User types command ──► [preexec Hook] ──► Host Shell Runs Command ──► [precmd Hook] ──► Next Prompt
                             │                                             │
               SAFE: Duplicates Stderr FD                     Restores Stderr FD & reads tail
               UNSAFE: Naked execution (no FD change)         Delivers pending messages
```

* **No Subshell / Tee Wrapping**: Commands like `cd ..`, `export FOO=bar`, or activating a virtual environment execute directly inside your primary shell process.
* **Curses & Interactive Isolation**: Full-screen programs (`vim`, `nvim`, `top`, `ssh`, `python`) are tagged `UNSAFE` and run with zero redirection or buffering.
* **Non-Blocking IPC**: Events are dispatched over non-blocking local Unix domain sockets (`~/.socrates/daemon.sock`) or loopback TCP, adding `< 1ms` to your prompt return.

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

Choose your preferred installation method:

```bash
# Option A: Install via pip (recommended for local development)
pip install -e .

# Option B: Isolated installation via pipx (ideal for global CLI usage)
pipx install .

# Option C: Direct clone and install
git clone https://github.com/sohmxdd/socrates.git
cd socrates && pip install .
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
