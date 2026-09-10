# Socrates Detection Rules Deep Dive

Socrates uses four deterministic, offline rule engines to detect edge-case failure modes without false alarms.

---

## 1. Forgotten Push (`forgotten_push.py`)

* **Condition**: A git repository has local commits ahead of upstream (`git rev-list @{u}..HEAD`).
* **Trigger Mechanism**: Ran on an independent periodic background sweep (default: every 10 minutes) across all known repos.
* **Actively-Committing Guard**: If the most recent commit in the repository was authored within `active_commit_window_seconds` (default: 300s), Socrates suppresses the reminder. The developer is actively working; Socrates only speaks once the developer walks away or pauses.

---

## 2. Leaked Secrets (`leaked_secrets.py`)

* **Condition**: A shell command contains hardcoded API keys, private tokens, or credential strings.
* **Patterns Supported**:
  - AWS Access Key IDs (`AKIA[0-9A-Z]{16}`)
  - GitHub Personal Access Tokens (`ghp_[0-9a-zA-Z]{36}`)
  - Stripe Secret Keys (`sk_live_[0-9a-zA-Z]{24}`)
  - OpenAI Secret Keys (`sk-[0-9a-zA-Z]{32,}`)
  - PEM Private Keys (`-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----`)
  - Generic high-entropy strings ($H(X) \ge 4.5$ bits/char via Shannon entropy)
* **Zero Network Guarantee**: Runs 100% offline. Secret detection logic never calls an LLM or touches the internet.

---

## 3. Silent Failure (`silent_failure.py`)

* **Condition**: A command exits with status `0`, but failed in reality.
* **Heuristics**:
  1. **Stderr Fatal Errors**: Stderr tail contains explicit failure indicators (`fatal:`, `Segmentation fault`, `compilation error`, `panicked at`).
  2. **Missing Build Artifacts**: Compilers or tools (`gcc -o bin/app`, `cp src dst`) that exit 0 but fail to create their declared target file on disk.

---

## 4. Stuck Process (`stuck_process.py`)

* **Condition**: A running process has exceeded its historical runtime baseline by a significant margin.
* **Baseline Calculation**:
  - Maintained per `(project_dir, command_signature)` in SQLite.
  - Calculated using online Welford updates for numerical stability.
  - Requires minimum `min_baseline_samples` (default: 5) to mature.
* **Confidence Thresholds**:
  - `HIGH_CONFIDENCE`: Elapsed time exceeds $3 \times \text{mean}$.
  - `LOW_CONFIDENCE`: Elapsed time exceeds $\text{mean} + k \times \text{stddev}$.
