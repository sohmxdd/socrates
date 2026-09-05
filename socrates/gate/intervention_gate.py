"""
socrates/gate/intervention_gate.py — The intervention gate.

This is the single choke point between "a rule fired" and "the user sees a message."
Its job is to suppress duplicate, snoozed, dismissed, or otherwise unwanted interventions.

Suppression logic (checked in order, short-circuit on first match):
  1. Empty fingerprint — rule produced no real result, skip.
  2. Snoozed — user said "snooze for N hours"; don't fire until snooze expires.
  3. Dismissed too many times — user hit "don't show again" dismiss_threshold times.
  4. Already fired recently — same fingerprint fired within the cooldown window
     (widened if previous dismissals occurred in the same repo scope).

write_pending(result, repo_path):
  Writes a formatted JSON message to the pending directory for shell pickup.
  The pending file is keyed by repo_path hash so the shell hook can find it
  on the next precmd for the correct repo.

check_and_escalate_pending():
  Checks for stale pending files older than notification_escalation_hours and
  escalates them to OS notifications.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Any

from socrates.gate.fingerprint import make_fingerprint
from socrates.rules.base import RuleResult

logger = logging.getLogger(__name__)


class InterventionGate:
    def __init__(self, db_path: Path, config: Any, home: Path):
        self.db_path = db_path
        self.config = config
        self.home = home

    # ── Public interface ───────────────────────────────────────────────────────

    def should_fire(self, result: RuleResult) -> bool:
        """
        Return True if this result should be delivered to the user.
        Returns False if the result should be suppressed.
        """
        from socrates.daemon import db

        fp_key = result.fingerprint_key
        if not fp_key:
            return False

        fingerprint = make_fingerprint(fp_key)
        row_raw = db.get_suppression(self.db_path, fingerprint)
        if row_raw is None:
            # Never seen before — let it through.
            return True
        row = dict(row_raw)

        # Check snooze.
        if row.get("snoozed_until"):
            snooze_ts = _parse_ts(row["snoozed_until"])
            if snooze_ts and snooze_ts > datetime.now(timezone.utc):
                logger.debug("Fingerprint %s is snoozed until %s", fingerprint, snooze_ts)
                return False

        # Check dismiss threshold.
        dismiss_count = row.get("dismiss_count", 0)
        dismiss_threshold = getattr(self.config, "dismiss_threshold", 3)
        if dismiss_count >= dismiss_threshold:
            logger.debug("Fingerprint %s dismissed %d times", fingerprint, dismiss_count)
            return False

        # Check cooldown window (same result fired too recently).
        last_fired = _parse_ts(row.get("last_fired_ts", ""))
        if last_fired:
            base_cooldown = getattr(self.config, "intervention_cooldown_seconds", 3600)
            repo_path = result.facts.get("repo_path")
            cooldown_seconds = base_cooldown

            # Dismiss-driven sensitivity widening for repo scope:
            if repo_path:
                try:
                    repo_rows = db.get_suppression_by_repo(self.db_path, repo_path)
                    rule_val = getattr(result.rule_type, "value", str(result.rule_type))
                    total_dismisses = sum(
                        r["dismiss_count"] for r in repo_rows if r["rule_type"] == rule_val
                    )
                    if total_dismisses > 0:
                        widening_factor = getattr(self.config, "dismiss_widening_factor", 1.5)
                        cooldown_seconds = int(base_cooldown * (widening_factor ** min(total_dismisses, 5)))
                except Exception:
                    pass

            cooldown = timedelta(seconds=cooldown_seconds)
            if datetime.now(timezone.utc) - last_fired < cooldown:
                logger.debug("Fingerprint %s in cooldown (%ds)", fingerprint, cooldown_seconds)
                return False

        return True

    def record_fire(self, result: RuleResult) -> None:
        """
        Record that this result fired. Called immediately after delivery.
        Updates last_fired_ts or inserts a new row.
        """
        from socrates.daemon import db

        fp_key = result.fingerprint_key
        if not fp_key:
            return

        fingerprint = make_fingerprint(fp_key)
        repo_path = result.facts.get("repo_path")
        branch = result.facts.get("branch")
        rule_val = getattr(result.rule_type, "value", str(result.rule_type))

        db.upsert_suppression_fired(
            self.db_path,
            fingerprint=fingerprint,
            rule_type=rule_val,
            repo_path=repo_path,
            branch=branch,
        )

    def write_pending(self, result: RuleResult, *, repo_path: Optional[str] = None) -> Optional[Path]:
        """
        Write a formatted message to the pending directory for shell pickup.
        The file is keyed by the repo_path hash so the shell hook finds it.
        For results not associated with a repo, we use the fingerprint_key hash.
        """
        pending_dir = self.config.pending_dir(self.home)
        pending_dir.mkdir(parents=True, exist_ok=True)

        if repo_path:
            key = hashlib.sha256(repo_path.encode()).hexdigest()[:16]
        else:
            key = hashlib.sha256(result.fingerprint_key.encode()).hexdigest()[:16]

        pending_file = pending_dir / f"{key}.json"

        try:
            quiet = getattr(self.config, "quiet_mode", False)
            formatted = _format_message(result, quiet_mode=quiet)
            rule_val = getattr(result.rule_type, "value", str(result.rule_type))
            payload = {
                "fingerprint": make_fingerprint(result.fingerprint_key),
                "rule_type": rule_val,
                "formatted_message": formatted,
                "facts": _sanitize_facts(result.facts),
                "written_at": datetime.now(timezone.utc).isoformat(),
            }
            pending_file.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.debug("Wrote pending message to %s", pending_file)
            return pending_file
        except Exception:
            logger.debug("Error writing pending file.", exc_info=True)
            return None

    def check_and_escalate_pending(self) -> list[Path]:
        """
        Check for pending messages older than notification_escalation_hours.
        Escalates them to OS notifications and removes the pending file.
        """
        pending_dir = self.config.pending_dir(self.home)
        if not pending_dir.exists():
            return []

        escalation_hours = getattr(self.config, "notification_escalation_hours", 2.0)
        escalation_threshold = timedelta(hours=escalation_hours)
        now = datetime.now(timezone.utc)
        escalated: list[Path] = []

        for pfile in pending_dir.glob("*.json"):
            try:
                data = json.loads(pfile.read_text(encoding="utf-8"))
                written_at_str = data.get("written_at")
                if written_at_str:
                    written_at = _parse_ts(written_at_str)
                    if written_at and (now - written_at) >= escalation_threshold:
                        msg = data.get("formatted_message", "Socrates intervention pending.")
                        if getattr(self.config, "os_notifications_enabled", True):
                            _deliver_notification("Socrates", msg)
                        pfile.unlink(missing_ok=True)
                        escalated.append(pfile)
            except Exception:
                logger.debug("Error checking escalation for %s", pfile, exc_info=True)

        return escalated

    # ── Snooze / dismiss (called by CLI) ──────────────────────────────────────

    def snooze(self, fingerprint: str, hours: float) -> None:
        """Snooze a result by fingerprint for N hours."""
        from socrates.daemon import db
        snooze_until = (
            datetime.now(timezone.utc) + timedelta(hours=hours)
        ).isoformat()
        db.set_snooze(self.db_path, fingerprint=fingerprint, snoozed_until=snooze_until)

    def snooze_branch(self, repo_path: str, branch: str, hours: float) -> None:
        """Snooze all interventions on a specific branch for N hours."""
        from socrates.daemon import db
        snooze_until = (
            datetime.now(timezone.utc) + timedelta(hours=hours)
        ).isoformat()
        rows = db.get_suppression_by_repo(self.db_path, repo_path)
        for r in rows:
            if r["branch"] == branch:
                db.set_snooze(self.db_path, fingerprint=r["fingerprint"], snoozed_until=snooze_until)

    def dismiss(self, fingerprint: str) -> int:
        """Increment dismiss count. Returns new count."""
        from socrates.daemon import db
        return db.increment_dismiss(self.db_path, fingerprint)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _format_message(result: RuleResult, quiet_mode: bool = False) -> str:
    """Safely format a message, using personality if available, otherwise plain fallback."""
    try:
        from socrates.personality.messages import generate_message
        return generate_message(result.rule_type, result.facts, quiet=quiet_mode)
    except Exception:
        rule_name = getattr(result.rule_type, "value", str(result.rule_type))
        return f"Socrates: {rule_name.replace('_', ' ').capitalize()} detected."


def _deliver_notification(title: str, message: str) -> None:
    """Deliver an OS notification safely without raising on missing presentation module."""
    try:
        from socrates.presentation.notify import send_os_notification
        send_os_notification(title=title, body=message)
    except Exception:
        logger.debug("OS notification delivery skipped or not available.", exc_info=True)


def _parse_ts(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string, returning None on failure."""
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        return None


def _sanitize_facts(facts: dict) -> dict:
    """
    Remove any sensitive fields from facts before writing to disk.
    This is a defence-in-depth measure: rules should never include secret
    values in facts, but we double-check here.
    """
    SENSITIVE_KEYS = {"stderr_tail", "stderr_excerpt"}
    return {k: v for k, v in facts.items() if k not in SENSITIVE_KEYS}
