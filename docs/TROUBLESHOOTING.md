# Socrates Troubleshooting Guide

### 1. Daemon Status Shows "STOPPED"
* **Diagnosis**: Run `socrates status --metrics`.
* **Remedy**:
  ```bash
  socrates start
  ```
  If it fails to start, inspect logs at `~/.socrates/daemon.log`. On Unix systems, verify permissions on `~/.socrates/daemon.sock`. On Windows, check that `~/.socrates/daemon.port` is readable.

### 2. Commands Run But Socrates Never Speaks
* **Reason A**: Socrates is working as designed! Socrates stays silent unless a rule fires with high confidence.
* **Reason B**: Shell hook is not sourced in your current session:
  ```bash
  # In PowerShell:
  . .\shell\socrates.ps1
  # In Zsh:
  source shell/socrates.zsh
  # In Bash:
  source shell/socrates.bash
  ```
* **Verify hook connectivity**:
  ```bash
  # Check if events are arriving:
  socrates status --metrics
  # Verify logged events count increments after running a command.
  ```

### 3. Forgotten Push Alert Fails to Appear Immediately
* **Explanation**: By design, Socrates enforces an active-committing window (default: 300 seconds). If you made a commit 30 seconds ago, Socrates assumes you are still actively working and suppresses the notification. Wait 5 minutes, or run `python scripts/demo.py` to test with simulated time.

### 4. Ambient Commentary ("Socrates observes:") Not Displaying
* Ambient commentary is **disabled by default**.
* Enable it locally in your project:
  ```bash
  socrates init --commentary
  # Or globally:
  socrates commentary on --rate 0.8
  ```
