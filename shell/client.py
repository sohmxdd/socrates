#!/usr/bin/env python3
"""
shell/client.py — Thin Unix socket client for shell hooks.

Reads a JSON payload from stdin, sends it as a single newline-terminated
line to the Socrates daemon socket, then exits immediately.

Design constraints:
  - Pure stdlib only (no imports from socrates package — must work before install)
  - Exits silently on any error (daemon not running = no-op, not an error)
  - Never blocks the calling shell for more than a fraction of a second
  - Must be fast to import (no heavy deps)

Usage (from shell hook):
    echo '{"type":"preexec","command":"git status",...}' | python3 /path/to/shell/client.py
"""
import json
import os
import socket
import sys


def main() -> None:
    # Determine socket path: honour SOCRATES_HOME env var, fall back to ~/.socrates/
    socrates_home = os.environ.get(
        "SOCRATES_HOME",
        os.path.join(os.path.expanduser("~"), ".socrates"),
    )
    socket_path = os.path.join(socrates_home, "daemon.sock")

    # Read payload from stdin.
    try:
        payload = sys.stdin.buffer.read()
        if not payload:
            return
        # Validate it's parseable JSON (fast sanity check before socket attempt).
        json.loads(payload)
    except (json.JSONDecodeError, OSError):
        return  # Malformed payload — silently drop.

    # Ensure payload ends with exactly one newline (the daemon's readline delimiter).
    payload = payload.rstrip(b"\n") + b"\n"

    # Connect and send — fire-and-forget.
    try:
        if hasattr(socket, "AF_UNIX") and os.path.exists(socket_path):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.5)  # Never block the shell for more than 500ms
            sock.connect(socket_path)
            sock.sendall(payload)
            sock.close()
        else:
            port_path = os.path.join(socrates_home, "daemon.port")
            if os.path.exists(port_path):
                with open(port_path, "r", encoding="utf-8") as f:
                    port = int(f.read().strip())
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                sock.connect(("127.0.0.1", port))
                sock.sendall(payload)
                sock.close()
    except (OSError, socket.timeout, ValueError):
        # Daemon not running, socket/port missing, or send failed — all silent.
        pass


if __name__ == "__main__":
    main()
