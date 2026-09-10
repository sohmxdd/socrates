# Socrates Video Demonstration Walkthrough

This document outlines the recommended step-by-step recording script for recording a short product demo or video showcase of Socrates.

## Setup Before Recording

1. Open your terminal window (suggested dimensions: 120 columns x 35 rows).
2. Set terminal font to a clean monospace font (e.g. JetBrains Mono, Fira Code) at 15pt+.
3. Start the daemon in the background:
   ```bash
   socrates start
   ```

---

## Scenario Progression

### Scene 1: The Ambient Observer & Ragebait Mode (Amber)
1. Initialize local commentary in your project:
   ```bash
   socrates init --commentary --rate 1.0
   ```
2. Run mundane commands:
   ```bash
   git status
   git diff
   ```
3. Highlight Socrates appearing at the prompt with amber text (`Socrates observes:`).

### Scene 2: Accidental Secret Leak (Cyan Intervention)
1. Attempt to enter an API key or AWS credential:
   ```bash
   export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
   ```
2. Socrates immediately intervenes with cyan text (`Socrates:`), warning you before or right as the secret hits your shell history.
3. Emphasize that this check was 100% offline and zero tokens were transmitted.

### Scene 3: Silent Failure Detection
1. Run a build command that returns exit code 0 but failed to produce the binary:
   ```bash
   python scripts/demo.py
   # Select Option 3
   ```
2. Socrates observes the exit code 0 and flags the missing build artifact.

### Scene 4: Forgotten Git Push Across Sessions
1. Create a local commit on a feature branch without pushing.
2. Close the terminal window completely.
3. Open a new terminal window.
4. On the very first prompt, Socrates greets you with a reminder that unpushed commits remain stranded on your laptop.
