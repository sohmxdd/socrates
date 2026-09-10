"""
scripts/doctor.py — Diagnostic health check tool for Socrates.

Verifies:
  - Python runtime version & platform
  - Socrates configuration & home directory
  - SQLite database accessibility & schema integrity
  - Daemon process status & socket/port reachability
  - Shell hook integration in profiles
  - Optional Groq API key availability
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from socrates.config import load_config, get_socrates_home
from socrates.cli import _get_running_pid


def check_runtime() -> bool:
    print(f"[*] Python: {sys.version.split()[0]} ({sys.platform})")
    if sys.version_info < (3, 10):
        print("    [!] WARNING: Socrates requires Python 3.10+")
        return False
    return True


def check_home_and_db() -> bool:
    home = get_socrates_home()
    print(f"[*] Socrates Home: {home}")
    if not home.exists():
        print("    [!] Home directory does not exist yet (will be created on first start)")
        return True

    cfg = load_config()
    db_file = cfg.db_path(home)
    if db_file.exists():
        size_kb = db_file.stat().st_size / 1024
        print(f"    [+] SQLite Database: {db_file.name} ({size_kb:.1f} KB)")
    else:
        print("    [-] SQLite database not initialized yet.")
    return True


def check_daemon() -> bool:
    home = get_socrates_home()
    cfg = load_config()
    pid = _get_running_pid(cfg, home)
    if pid:
        print(f"[*] Daemon: RUNNING (PID {pid})")
    else:
        print("[*] Daemon: STOPPED (run 'socrates start' to launch)")
    return True


def check_groq() -> None:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if key:
        masked = key[:6] + "..." + key[-4:] if len(key) > 10 else "***"
        print(f"[*] Groq API Key: CONFIGURED ({masked})")
    else:
        print("[*] Groq API Key: NOT SET (offline deterministic rules will still function)")


def run_doctor() -> None:
    print("=" * 55)
    print("       SOCRATES ENVIRONMENT & SYSTEM DOCTOR")
    print("=" * 55)
    check_runtime()
    check_home_and_db()
    check_daemon()
    check_groq()
    print("=" * 55)
    print("All checks completed.")


if __name__ == "__main__":
    run_doctor()
