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
    print("      SOCRATES -- TERMINAL WATCHING AGENT DEMO")
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


def run_interactive() -> None:
    """Interactive demo mode for live video recordings and testing."""
    while True:
        print("\n" + "=" * 62)
        print("     SOCRATES -- INTERACTIVE DEMO & VIDEO SHOWCASE")
        print("=" * 62)
        print("  Select a scenario to trigger Socrates:")
        print("    [1] Leaked Secret        (AWS/GitHub/Stripe key entered in shell)")
        print("    [2] Forgotten Git Push   (Unpushed commits on current branch)")
        print("    [3] Silent Failure       (Build exits 0 without creating artifact)")
        print("    [4] Stuck Process        (Task running 10x past historical baseline)")
        print("    [5] Socratic vs Quiet    (Philosophical ragebait vs plain factual)")
        print("    [6] Custom Command Test  (Type any command to check for secrets)")
        print("    [A] Run All Scenarios")
        print("    [Q] Quit")
        print("=" * 62)

        try:
            choice = input("Enter choice (1-6, A, Q): ").strip().upper()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if choice == "Q":
            print("Exiting demo.")
            break
        elif choice == "1":
            print("\nSimulating: export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE")
            time.sleep(0.3)
            res = check_leaked_secrets("export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE")
            msg = generate_message(res.rule_type, res.facts)
            print_intervention(msg)
        elif choice == "2":
            branch = input("Branch name [default: feature-auth]: ").strip() or "feature-auth"
            count_str = input("Unpushed commits [default: 4]: ").strip() or "4"
            count = int(count_str) if count_str.isdigit() else 4
            print(f"\nSimulating: {count} unpushed commits on '{branch}'...")
            time.sleep(0.3)
            msg = generate_message(RuleType.FORGOTTEN_PUSH, {"unpushed_count": count, "branch": branch})
            print_intervention(msg)
        elif choice == "3":
            cmd = input("Command [default: make release]: ").strip() or "make release"
            artifact = input("Missing artifact [default: bin/app]: ").strip() or "bin/app"
            print(f"\nSimulating: '{cmd}' succeeded (exit 0) but '{artifact}' was not found...")
            time.sleep(0.3)
            msg = generate_message(RuleType.SILENT_FAILURE, {"command": cmd, "artifact_path": artifact})
            print_intervention(msg)
        elif choice == "4":
            cmd = input("Command [default: pytest]: ").strip() or "pytest"
            elapsed_str = input("Elapsed seconds [default: 240]: ").strip() or "240"
            baseline_str = input("Baseline seconds [default: 15]: ").strip() or "15"
            elapsed = int(elapsed_str) if elapsed_str.isdigit() else 240
            baseline = int(baseline_str) if baseline_str.isdigit() else 15
            print(f"\nSimulating: '{cmd}' has run for {elapsed}s (normal: {baseline}s)...")
            time.sleep(0.3)
            msg = generate_message(RuleType.STUCK_PROCESS, {"command_sig": cmd, "elapsed_secs": elapsed, "baseline_mean_secs": baseline})
            print_intervention(msg)
        elif choice == "5":
            facts = {"unpushed_count": 3, "branch": "main"}
            print("\n[Quiet Mode (factual)]:")
            print("  " + generate_message(RuleType.FORGOTTEN_PUSH, facts, quiet=True))
            print("\n[Socratic Mode (theatrical contempt)]:")
            print_intervention(generate_message(RuleType.FORGOTTEN_PUSH, facts, quiet=False))
        elif choice == "6":
            user_cmd = input("\nEnter shell command to test: ").strip()
            if user_cmd:
                res = check_leaked_secrets(user_cmd)
                if res.confidence != Confidence.NONE:
                    msg = generate_message(res.rule_type, res.facts)
                    print_intervention(msg)
                else:
                    print("Socrates: ... (Silent. No issues detected in this command.)")
        elif choice == "A":
            run_demo()
        else:
            print("Invalid option. Please choose 1-6, A, or Q.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--interactive", "-i", "interactive"):
        run_interactive()
    else:
        run_demo()
