"""
socrates/presentation/terminal.py — Terminal visual identity and styling.

Requirements:
  - Messages prefixed with `Socrates:` in distinct ANSI bright cyan (`\033[1;96m`),
    message body in normal readable weight.
  - Compact: 1–3 lines, no walls of text.
  - Graceful fallback to plain unstyled text when NO_COLOR env var is set,
    or when color is disabled via config or output is not a TTY.
  - Clean styling legible on dark and light backgrounds.
"""
from __future__ import annotations

import os
import sys
from typing import Optional, TextIO

# ANSI codes
CYAN_BOLD = "\033[1;96m"
RESET = "\033[0m"


def should_use_color(color_enabled: bool = True, stream: Optional[TextIO] = None) -> bool:
    """
    Determine whether ANSI colors should be emitted.
    Honors NO_COLOR specification (https://no-color.org/) and stream TTY status.
    """
    if not color_enabled:
        return False
    # NO_COLOR: if set to any value, disable color
    if "NO_COLOR" in os.environ and os.environ["NO_COLOR"].strip() != "":
        return False
    # If a stream is given and is not a tty, disable color
    if stream is not None and hasattr(stream, "isatty") and not stream.isatty():
        return False
    return True


def format_terminal_message(message: str, color_enabled: bool = True) -> str:
    """
    Format an intervention message with the 'Socrates:' prefix.
    If the message already starts with 'Socrates:', style the prefix cleanly.
    """
    message = message.strip()
    prefix_text = "Socrates:"

    if message.startswith("Socrates:"):
        body = message[len("Socrates:"):].lstrip()
    else:
        body = message

    use_color = should_use_color(color_enabled)
    if use_color:
        return f"{CYAN_BOLD}{prefix_text}{RESET} {body}"
    return f"{prefix_text} {body}"


def print_intervention(
    message: str,
    color_enabled: bool = True,
    file: Optional[TextIO] = None,
) -> None:
    """
    Print an intervention message to the terminal.
    Never called mid-command — only at prompt or standalone.
    """
    stream = file or sys.stdout
    use_color = should_use_color(color_enabled, stream=stream)
    formatted = format_terminal_message(message, color_enabled=use_color)
    try:
        print(formatted, file=stream)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        safe_text = formatted.encode(encoding, errors="replace").decode(encoding)
        print(safe_text, file=stream)
