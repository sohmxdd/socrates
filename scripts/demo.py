"""
scripts/demo.py — Interactive / automated demonstration of Socrates.

Demonstrates all 4 failure modes and key architectural features:
  1. Forgotten push (closed terminal -> pending pickup in new terminal)
  2. Leaked secret (local evaluation, zero network transmission)
  3. Silent failure (exit code 0 with missing build artifact)
  4. Stuck process (anomaly vs historical runtime baseline)
  5. Socratic Persona vs Quiet Mode comparison
"""
from __future__ import annotations

import os
import sys
import time

from socrates.presentation.terminal import format_terminal_message, print_intervention
from socrates.personality.messages import generate_message
from socrates.rules.base import Confidence, RuleResult, RuleType
from socrates.rules.leaked_secrets import check_leaked_secrets


def run_demo() -> None:
    print("\n" + "=" * 60)
    print("      SOCRATES — TERMINAL WATCHING AGENT DEMO")
    print("=" * 60 + "\n")

    # Scenario 1: Forgotten push
    print("--- Scenario 1: Forgotten Git Push ---")
    print("Developer has created 3 commits on 'feature-auth' and walked away.")
    print("Daemon sweep triggers on its own clock after inactivity window.")
    facts_push = {"unpushed_count": 3, "branch": "feature-auth"}
    msg_push = generate_message(RuleType.FORGOTTEN_PUSH, facts_push)
    print_intervention(msg_push)
    print()

    # Scenario 2: Leaked secrets
    print("--- Scenario 2: Leaked Secret in Shell Command ---")
    bad_cmd = "export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
    print(f"Developer enters: {bad_cmd}")
    res_sec = check_leaked_secrets(bad_cmd)
    msg_sec = generate_message(res_sec.rule_type, res_sec.facts)
    print_intervention(msg_sec)
    print()

    # Scenario 3: Silent failure
    print("--- Scenario 3: Silent Failure (Exit 0 with Missing Artifact) ---")
    print("Command 'make release' exited with status 0, but 'bin/app' was not created.")
    facts_sf = {"artifact_path": "bin/app", "command": "make release"}
    msg_sf = generate_message(RuleType.SILENT_FAILURE, facts_sf)
    print_intervention(msg_sf)
    print()

    # Scenario 4: Stuck process
    print("--- Scenario 4: Stuck Process (Runtime Anomaly) ---")
    print("Command 'pytest' usually completes in 12 seconds; currently at 180 seconds.")
    facts_stuck = {
        "command_sig": "pytest",
        "elapsed_secs": 180,
        "baseline_mean_secs": 12,
    }
    msg_stuck = generate_message(RuleType.STUCK_PROCESS, facts_stuck)
    print_intervention(msg_stuck)
    print()

    # Comparison: Quiet Mode
    print("--- Quiet Mode Comparison ---")
    print("When quiet_mode: true is configured:")
    print("Push:    " + generate_message(RuleType.FORGOTTEN_PUSH, facts_push, quiet=True))
    print("Secrets: " + generate_message(RuleType.LEAKED_SECRETS, res_sec.facts, quiet=True))
    print("Build:   " + generate_message(RuleType.SILENT_FAILURE, facts_sf, quiet=True))
    print("Stuck:   " + generate_message(RuleType.STUCK_PROCESS, facts_stuck, quiet=True))

    print("\n" + "=" * 60)
    print("Demo complete. Socrates stays silent the rest of the time.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    run_demo()
