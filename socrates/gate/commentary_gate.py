"""
socrates/gate/commentary_gate.py — Lightweight gate for ambient commentary.

Unlike InterventionGate (which uses SQLite suppression tables and permanent dismissals),
CommentaryGate regulates ambient, in-character commentary using an in-memory,
per-session cooldown and probability sampler.

Duties:
  1. Check if commentary is enabled in effective config.
  2. Filter out commands listed in commentary_skip_commands.
  3. Enforce a minimum interval (commentary_cooldown_seconds) between comments in each session.
  4. Apply commentary_rate probability (0.0 - 1.0).
  5. Write session-keyed pending JSON messages for prompt delivery.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CommentaryGate:
    """Manages session-level gating and delivery for ambient commentary."""

    def __init__(self, config: Any, home: Path):
        self.config = config
        self.home = home
        # session_id -> last comment timestamp (seconds since epoch)
        self._last_comment_ts: dict[str, float] = {}

    def should_comment(
        self,
        session_id: str,
        command: str,
        effective_config: Optional[Any] = None,
    ) -> bool:
        """
        Determine if a commentary reaction should be generated for this command.
        """
        cfg = effective_config or self.config

        # 1. Master toggle
        if not getattr(cfg, "commentary_enabled", False):
            return False

        cmd_clean = command.strip()
        if not cmd_clean:
            return False

        # 2. Skip list check
        skip_list = getattr(cfg, "commentary_skip_commands", ["clear", "cls", "pwd", "exit"])
        base_cmd = cmd_clean.split()[0].lower() if cmd_clean.split() else ""
        if cmd_clean.lower() in [s.lower() for s in skip_list] or base_cmd in [s.lower() for s in skip_list]:
            logger.debug("Commentary skipped: command '%s' in skip list", cmd_clean)
            return False

        # 3. Session cooldown check
        cooldown_sec = getattr(cfg, "commentary_cooldown_seconds", 15)
        last_ts = self._last_comment_ts.get(session_id, 0.0)
        now = time.time()
        if now - last_ts < cooldown_sec:
            logger.debug(
                "Commentary skipped: session %s in cooldown (%.1fs < %ds)",
                session_id,
                now - last_ts,
                cooldown_sec,
            )
            return False

        # 4. Rate sampling
        rate = float(getattr(cfg, "commentary_rate", 0.6))
        if rate <= 0.0:
            return False
        if rate < 1.0:
            if random.random() > rate:
                logger.debug("Commentary skipped by rate sample (rate=%.2f)", rate)
                return False

        return True

    def record_comment(self, session_id: str, ts: Optional[float] = None) -> None:
        """Update last commentary timestamp for a session."""
        self._last_comment_ts[session_id] = time.time() if ts is None else ts

    def write_pending(
        self,
        message: str,
        session_id: str,
        repo_path: Optional[str] = None,
        effective_config: Optional[Any] = None,
    ) -> Optional[Path]:
        """
        Write a pending commentary message to ~/.socrates/pending/.
        Keyed to session_id or repo_path so the active shell picks it up immediately.
        """
        cfg = effective_config or self.config
        pending_dir = cfg.pending_dir(self.home)
        pending_dir.mkdir(parents=True, exist_ok=True)

        if repo_path:
            key = hashlib.sha256(repo_path.encode()).hexdigest()[:16]
        else:
            key = hashlib.sha256(session_id.encode()).hexdigest()[:16]

        pending_file = pending_dir / f"commentary_{key}.json"

        payload = {
            "fingerprint": f"commentary_{key}_{int(time.time())}",
            "rule_type": "commentary",
            "is_commentary": True,
            "session_id": session_id,
            "formatted_message": message.strip(),
            "written_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            pending_file.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.debug("Wrote commentary pending file: %s", pending_file)
            return pending_file
        except Exception:
            logger.debug("Error writing commentary pending file", exc_info=True)
            return None
