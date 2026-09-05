"""
socrates/presentation/notify.py — Desktop OS notifications.

Requirements:
  - macOS: terminal-notifier -> fallback osascript
  - Linux: notify-send
  - Non-blocking, fails silently (debug-log only).
  - Used for stuck-process alerts (while user is tabbed away) and escalation
    of long-pending push notifications.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)


def send_os_notification(title: str, body: str) -> bool:
    """
    Send an OS notification banner.
    Returns True if the notification command was executed, False otherwise.
    Fails silently — never raises.
    """
    if not title and not body:
        return False

    title = title or "Socrates"
    body = body or ""

    cmd: list[str] = []

    if sys.platform == "darwin":
        if shutil.which("terminal-notifier"):
            cmd = ["terminal-notifier", "-title", title, "-message", body]
        else:
            # Escape quotes for AppleScript
            escaped_body = body.replace('"', '\\"')
            escaped_title = title.replace('"', '\\"')
            script = f'display notification "{escaped_body}" with title "{escaped_title}"'
            cmd = ["osascript", "-e", script]

    elif sys.platform.startswith("linux"):
        if shutil.which("notify-send"):
            cmd = ["notify-send", title, body]
        else:
            logger.debug("notify-send not found on Linux.")
            return False

    elif sys.platform == "win32":
        # Best-effort Windows notification fallback using powershell toast or balloon
        ps_script = f"""
        [reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null
        $notify = new-object system.windows.forms.notifyicon
        $notify.icon = [system.drawing.systemicons]::Information
        $notify.visible = $true
        $notify.showballoontip(5000, '{title}', '{body}', [system.windows.forms.tooltipicon]::Info)
        """
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script]

    else:
        logger.debug("Unsupported OS for desktop notifications: %s", sys.platform)
        return False

    try:
        kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform != "win32":
            kwargs["start_new_session"] = True

        subprocess.Popen(cmd, **kwargs)
        logger.debug("Sent OS notification: %s", title)
        return True
    except Exception:
        logger.debug("Failed to dispatch OS notification.", exc_info=True)
        return False
