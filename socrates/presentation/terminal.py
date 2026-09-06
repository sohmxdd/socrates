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
AMBER_BOLD = "\033[1;93m"
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


def sanitize_terminal_text(text: str) -> str:
    """
    Replace Unicode punctuation characters that cause encoding failures
    on legacy Windows consoles (cp1252, cp437) with standard ASCII equivalents.
    """
    replacements = {
        "\u2011": "-",   # non-breaking hyphen
        "\u2012": "-",   # figure dash
        "\u2013": "--",  # en dash
        "\u2014": "--",  # em dash
        "\u2018": "'",   # left single quotation mark
        "\u2019": "'",   # right single quotation mark
        "\u201a": ",",   # single low-9 quotation mark
        "\u201c": '"',   # left double quotation mark
        "\u201d": '"',   # right double quotation mark
        "\u2026": "...", # horizontal ellipsis
        "\u00a0": " ",   # non-breaking space
        "\u202f": " ",   # narrow no-break space
    }
    for orig, repl in replacements.items():
        text = text.replace(orig, repl)
    return text


def format_terminal_message(message: str, color_enabled: bool = True) -> str:
    """
    Format an intervention message with the 'Socrates:' prefix.
    If the message already starts with 'Socrates:', style the prefix cleanly.
    """
    message = sanitize_terminal_text(message.strip())
    prefix_text = "Socrates:"

    if message.startswith("Socrates:"):
        body = message[len("Socrates:"):].lstrip()
    else:
        body = message

    use_color = should_use_color(color_enabled)
    if use_color:
        return f"{CYAN_BOLD}{prefix_text}{RESET} {body}"
    return f"{prefix_text} {body}"


def format_commentary_message(message: str, color_enabled: bool = True) -> str:
    """
    Format an ambient commentary message with the 'Socrates observes:' prefix in amber.
    """
    message = sanitize_terminal_text(message.strip())
    prefix_text = "Socrates observes:"

    if message.startswith("Socrates observes:"):
        body = message[len("Socrates observes:"):].lstrip()
    elif message.startswith("Socrates:"):
        body = message[len("Socrates:"):].lstrip()
    else:
        body = message

    use_color = should_use_color(color_enabled)
    if use_color:
        return f"{AMBER_BOLD}{prefix_text}{RESET} {body}"
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


def print_commentary(
    message: str,
    color_enabled: bool = True,
    file: Optional[TextIO] = None,
) -> None:
    """
    Print an ambient commentary message to the terminal.
    """
    stream = file or sys.stdout
    use_color = should_use_color(color_enabled, stream=stream)
    formatted = format_commentary_message(message, color_enabled=use_color)
    try:
        print(formatted, file=stream)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        safe_text = formatted.encode(encoding, errors="replace").decode(encoding)
        print(safe_text, file=stream)

