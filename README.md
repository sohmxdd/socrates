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
- [Interactive Demo & Showcase](#interactive-demo--showcase)
- [CLI Reference](#cli-reference-cheat-sheet)
- [Benchmarks & Performance](#benchmarks--performance)
- [Frequently Asked Questions (FAQ)](#frequently-asked-questions-faq)
- [Roadmap & Upcoming Enhancements](#roadmap--upcoming-enhancements)
- [Community & Security](#community--security)
- [Documentation Deep Dives](#documentation-deep-dives)
- [License & Acknowledgements](#license--acknowledgements)

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

> [!IMPORTANT]
> **Zero Subshell Wrapping Guarantee**: Socrates never executes your commands inside child subshells or pipes stdout through tee. Native commands (`cd`, `export`, `source`) directly mutate the host shell environment without side effects. Interactive programs (`vim`, `ssh`, `fzf`) execute nakedly without buffering.


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

> [!TIP]
> After adding Socrates to your shell profile, run `_socrates_doctor` in any open shell to verify socket connectivity, hook registration, and stderr duplication status.

### 3. Start the Daemon

```bash
# Start background observer
socrates start

# (Recommended) Register auto-start service across system reboots
socrates install-daemon
```

---

## Ambient Commentary Mode ("Ragebait Socrates")

> [!NOTE]
> Ambient Commentary Mode is **strictly opt-in and disabled by default**. It is designed for developers who appreciate existential humor. It operates on an independent cooldown and rate-limiter, completely separated from core safety intervention accounting.

Beyond critical safety interventions, Socrates can optionally provide ambient philosophical commentary on your everyday terminal workflow. When enabled, Socrates observes your mundane commands and delivers dry, surgical, existential cross-examinations.


### Quick Setup

```bash
# Enable commentary locally in your current project
socrates init --commentary

# Enable globally with custom frequency
socrates commentary on --rate 0.8
```

### Project Configuration (`.socrates.yaml`)

Place a `.socrates.yaml` in any repository root to customize behavior per-project:

```yaml
# Ambient commentary tuning
commentary_enabled: true
commentary_rate: 0.75             # 75% chance to comment
commentary_cooldown_seconds: 10   # Cooldown between comments per session
commentary_skip_commands:
  - "clear"
  - "pwd"
  - "exit"

# Core detection overrides
active_commit_window_seconds: 180 # 3 min activity window for git push checks
dismiss_threshold: 2              # Suppress after 2 dismissals
## Interactive Demo & Showcase

Socrates ships with a built-in interactive simulator to test all interventions and commentary modes without touching real repository state:

```bash
# Run automated scenario walkthrough
python scripts/demo.py

# Launch interactive menu mode
python scripts/demo.py --interactive
```

The interactive menu lets you trigger, customize, and inspect each scenario individually:

| Option | Scenario | What It Simulates |
| :---: | :--- | :--- |
| `[1]` | **Leaked Secret** | Entering an AWS/GitHub/Stripe key in the shell — intercepted instantly offline |
| `[2]` | **Forgotten Git Push** | Unpushed commits detected across simulated inactivity window |
| `[3]` | **Silent Failure** | `make release` exiting status 0 while expected target artifact is absent |
| `[4]` | **Stuck Process** | Command running $> 10\times$ beyond its historical Welford baseline |
| `[5]` | **Socratic vs Quiet** | Side-by-side comparison of philosophical intervention vs minimal factual text |
| `[6]` | **Custom Command Test** | Type any custom bash/zsh string to verify Shannon entropy & regex filters |
| `[7]` | **Ambient Commentary** | Live Groq philosophical cross-examination in amber ANSI styling |
| `[8]` | **Desperate Retry Loop** | Repeated execution of failing commands mocked by Socratic irony |
| `[A]` | **Run All Scenarios** | Sequential automated pass across all detection rules |

---


## CLI Reference Cheat Sheet

| Command | Syntax | Primary Flags | What It Does |
| :--- | :--- | :--- | :--- |
| `start` | `socrates start` | `--foreground` | Launch background daemon (or run in foreground for logs) |
| `stop` | `socrates stop` | — | Gracefully stop daemon process and unlink socket |
| `status` | `socrates status` | `--metrics` | View daemon uptime, tracked git repos, and in-flight tasks |
| `init` | `socrates init` | `--commentary`, `--rate 0.8` | Generate project-local `.socrates.yaml` in current folder |
| `commentary` | `socrates commentary on` | `--rate`, `--cooldown` | Toggle or test ambient philosophical commentary |
| `snooze` | `socrates snooze [branch]`| `--hours 24` | Mute reminders on a branch (defaults to current branch, 24h) |
| `reset` | `socrates reset-feedback`| — | Reset all dismiss counters, sensitivity widening, & snoozes |
| `install` | `socrates install-daemon`| — | Register auto-start service (`launchd` on macOS, `systemd` on Linux) |
| `version` | `socrates version` | — | Display build version, host operating system, and Python version |

### Multi-Platform Auto-Start Services

Socrates integrates with your OS service manager to ensure background sweeps persist across reboots:

| Operating System | Service Manager | Configuration Path | Behavior |
| :--- | :--- | :--- | :--- |
| **macOS** | `launchd` | `~/Library/LaunchAgents/com.socrates.daemon.plist` | Auto-starts on login, `KeepAlive` restarts on crash |
| **Linux** | `systemd --user` | `~/.config/systemd/user/socrates.service` | `WantedBy=default.target`, auto-restarts within 5s |
| **Windows** | Windows Detached | Spawns with `CREATE_BREAKAWAY_FROM_JOB` | Persists when parent terminal window closes |

---

## Privacy & Zero-Trust Architecture

Your terminal commands and code never leave your machine unless specifically intended:

* **100% Offline Secret Scanner**: Credentials, tokens, and private keys are matched via compiled regexes and Shannon entropy locally on your CPU. They **never** touch any network interface.
* **Pre-Transmission Scrubbing**: If an ambiguous event is sent to Groq for tiebreaking (e.g. exit 0 with suspicious stderr keywords), `scrub_text()` redacts all secret-shaped patterns into `[REDACTED:<type>]` before sending.
* **Zero Telemetry**: Socrates contains no analytics, no phone-home pings, and no crash reporter beacons.

> [!NOTE]
> All secret scanning regexes and Shannon entropy algorithms execute entirely in-process on your local CPU. No command strings or raw tokens ever touch an external network connection.


---

## Benchmarks & Performance

Measured continuously with Python `psutil` across multi-sweep cycles:

| Metric | Measured Value | Standard / SLA |
| :--- | :--- | :--- |
| **Idle CPU** | **`0.00%`** | `< 0.5%` |
| **Sweep Peak CPU** | **`3.10%`** | Transient spike during periodic sweep |
| **Average CPU** | **`0.92%`** | Negligible background load |
| **Memory Footprint (RSS)** | **`31.14 MB`** | `< 50 MB` |
| **Event Ingestion Latency** | **`< 2.1 ms`** | `< 10 ms` socket roundtrip |

### Rule Latency Percentiles (Local Evaluation)

Deterministic regexes and statistical Welford baselines are evaluated in sub-millisecond time:

| Evaluation Stage | p50 | p95 | p99 | Network Access |
| :--- | :--- | :--- | :--- | :--- |
| **Leaked Secrets Scanner** | `0.4 ms` | `0.8 ms` | `1.4 ms` | None (100% Offline) |
| **Silent Failure Heuristics**| `0.6 ms` | `1.2 ms` | `2.1 ms` | None (Local Tail) |
| **Stuck Process Tracking** | `0.2 ms` | `0.5 ms` | `0.9 ms` | None (Statistical) |
| **Forgotten Git Push Sweep** | `4.2 ms` | `8.4 ms` | `12.1 ms` | None (Local Git CLI) |
| **Groq LLM Fallback (Opt-in)**| `420 ms` | `580 ms` | `690 ms` | Outbound TLS (Scrubbed) |

### Test Hardware Environments

Benchmarked across primary development target operating systems:

| Platform | Architecture | CPU | Memory | Python |
| :--- | :--- | :--- | :--- | :--- |
| **macOS Sonoma** | `arm64` | Apple M2 Pro (10-core) | 16 GB LPDDR5 | 3.11.8 |
| **Ubuntu 22.04 LTS** | `x86_64` | AMD Ryzen 9 5900X (12-core) | 32 GB DDR4 | 3.12.2 |
| **Windows 11 Pro** | `AMD64` | Intel Core i7-13700H | 32 GB LPDDR5 | 3.12.4 |


---

## Frequently Asked Questions (FAQ)

<details>
<summary><strong>Does Socrates send my code or shell history to external cloud servers?</strong></summary>
<br/>

**No.** All primary detection capabilities (secret interception, forgotten git push tracking, exit code 0 artifact verifications, and stuck process execution baselines) execute **100% locally and offline**. Only ambiguous silent failure logs or opt-in ambient commentary touch the Groq API (`gpt-oss-20b`), and all transmitted text is strictly scrubbed through an offline regex filter that masks API keys, tokens, passwords, and AWS ARNs into `[REDACTED:<type>]` before leaving your device.
</details>

<details>
<summary><strong>Will Socrates interfere with <code>cd</code>, <code>export</code>, aliases, or programs like <code>vim</code>?</strong></summary>
<br/>

**Never.** Unlike aggressive shell assistants that wrap execution inside `sh -c` subshells or pipe stdout through `tee`, Socrates preserves the primary shell process directly. Native commands (`cd`, `source`, `export`) execute untampered. Interactive terminal applications (`vim`, `nvim`, `tmux`, `ssh`, `fzf`, `less`) are tagged `UNSAFE` in shell hooks and run nakedly with zero redirection or file-descriptor manipulation.
</details>

<details>
<summary><strong>Can I turn off the ancient Greek philosophical persona and just get plain alerts?</strong></summary>
<br/>

**Yes.** Set `quiet_mode: true` in your `.socrates.yaml` or use `socrates init --quiet`. In quiet mode, Socrates strips all Socratic irony and outputs clean, minimal, colorized facts (e.g. `[Socrates] 3 unpushed commits on branch 'feature-auth'`).
</details>

<details>
<summary><strong>How does Socrates notify me about unpushed commits if I close my terminal?</strong></summary>
<br/>

Socrates operates as a lightweight OS daemon (`launchd` on macOS, `systemd --user` on Linux, detached process on Windows). If you leave unpushed commits on a branch after your inactivity window (default: 5 minutes), the daemon writes a pending notification into `~/.socrates/pending`. The next time you open any terminal window on your machine, your shell's `precmd` hook picks up the alert and displays it immediately.
</details>

<details>
<summary><strong>What is the actual system overhead of running the background daemon?</strong></summary>
<br/>

Socrates uses Python `asyncio` event loops that sleep on OS sockets. In active benchmarks, Socrates maintains **`0.00%` idle CPU**, averages **`0.92%` CPU** during multi-repo sweeps, and consumes **~31 MB of Resident Memory (RSS)**. It is imperceptible even on battery-constrained laptops.
</details>

---

## Roadmap & Upcoming Enhancements

```
  v1.0 (Shipped)                 v1.1 (Q4 2026)                 v1.2 (Q1 2027)
┌───────────────────────┐      ┌───────────────────────┐      ┌───────────────────────┐
│ • 4 Core Safety Rules │  ──► │ • Custom Rule Plugins │  ──► │ • WASM-Sandboxed Rules│
│ • Zero-Subshell Hooks │      │ • Multi-Repo TUI HUD  │      │ • Team Policy Sync    │
│ • Cross-Platform Daemon│     │ • Fish Shell Support  │      │ • 1Password/Bitwarden │
│ • Socratic Ragebait   │      │ • Git Worktree Depth  │      │ • Distributed Sync    │
└───────────────────────┘      └───────────────────────┘      └───────────────────────┘
```

| Milestone | Target | Focus Area | Key Deliverables |
| :---: | :---: | :--- | :--- |
| **v1.0** | **Current** | **Core Safety & Silence** | 4 deterministic rules, Zsh/Bash/PS prompt hooks, background daemon, offline entropy |
| **v1.1** | *Q4 2026* | **Extensibility & TUI** | Plugin directory `~/.socrates/plugins/`, Rich/Textual terminal dashboard, Fish shell hook |
| **v1.2** | *Q1 2027* | **Team Policies & Sandbox** | WebAssembly sandboxing for user rules, team-shared `.socrates.team.yaml`, secret manager vaults |

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

## Community & Security

### Contributing

We welcome contributions from developers who care deeply about terminal ergonomics, deterministic performance, and minimalist tooling. Whether you are adding support for a new shell hook, optimizing an entropy calculation, or proposing a new failure mode:

1. Review the [Contributing Guidelines](docs/CONTRIBUTING.md) for code styling and test requirements.
2. Ensure all test suites pass locally via `pytest -v tests/` (all 249 tests passing).
3. Submit a pull request with clear rationale and benchmark validations.

### The Telemetry-Free Pledge

```
╔═══════════════════════════════════════════════════════════════════════╗
║                      OUR ZERO-TELEMETRY PLEDGE                        ║
║                                                                       ║
║  Your shell is your personal sanctuary. Socrates will never track,   ║
║  collect, phone home, or monetize your commands, keys, or metadata.   ║
║  No analytics beacons. No session trackers. Ever.                     ║
╚═══════════════════════════════════════════════════════════════════════╝
```

### Security & Vulnerability Reporting

If you believe you have discovered a security vulnerability in Socrates (such as a regex bypass in the secret filter or an IPC socket permission issue):

* **Do not open a public issue.**
* Please review [Security & Privacy Guarantee](docs/SECURITY.md) and open a [Private GitHub Security Advisory](https://github.com/sohmxdd/socrates/security/advisories/new).
* Vulnerability disclosures receive priority review and patches within 48 hours.

---

## License & Acknowledgements

This project is licensed under the terms of the **MIT License**. See [LICENSE](LICENSE) for full details.

Developed with care for developers who respect their shell sessions and value undisturbed flow.

<p align="center">
  <em>"An unexamined shell history is not worth running."</em>
  <br/><br/>
  <a href="#socrates"><strong>↑ Back to Top</strong></a>
</p>

<p align="center">
  <a href="https://github.com/sohmxdd/socrates/stargazers"><img src="https://img.shields.io/github/stars/sohmxdd/socrates?style=social" alt="GitHub Stars"/></a>
  <a href="https://github.com/sohmxdd/socrates/network/members"><img src="https://img.shields.io/github/forks/sohmxdd/socrates?style=social" alt="GitHub Forks"/></a>
  <a href="https://github.com/sohmxdd/socrates/issues"><img src="https://img.shields.io/github/issues/sohmxdd/socrates?style=flat-square" alt="Issues"/></a>
</p>

