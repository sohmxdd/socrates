# Socrates System Architecture

Socrates is a local-first, low-overhead terminal observer that detects and flags subtle developer failure modes with zero cognitive overhead.

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
│ │  - ZERO network for secrets; full graceful degradation  │ │
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
│ │  - Pending file writes (~/.socrates/pending/*.json)     │ │
│ │  - Next prompt pickup: Cyan `Socrates:`                 │ │
│ │  - Ambient commentary (opt-in): Amber `Socrates obs:`   │ │
│ │  - Desktop notification & non-blocking chime (optional) │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Core Design Principles

1. **Subshell & Tee Elimination**: User commands run naked in the host shell. No subshell wrappers, no pipe-tee hacks. Builtins (`cd`, `export`, `source`) and interactive programs (`vim`, `top`, `ssh`) are untouched.
2. **Zero-Secret Exfiltration**: Leaked secret detection runs 100% offline with Shannon entropy and strict token validation. Any ambiguous event routed to Groq for tiebreaking is scrubbed via deterministic redactors before leaving the machine.
3. **Independent Lifecycle**: The daemon runs independently via `launchd` (macOS), `systemd --user` (Linux), or detached process (Windows). It wakes on independent timers to catch forgotten commits even days later across new terminal windows.
4. **Welford Running Baselines**: Running durations for safe commands are modeled using Welford's algorithm ($M_{k} = M_{k-1} + \frac{x_k - M_{k-1}}{k}$) for numerically stable mean and variance calculation.
