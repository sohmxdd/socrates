"""
socrates/daemon/db.py — SQLite schema definition and query helpers.

All database I/O goes through this module. The schema is intentionally kept
flat and simple: no ORMs, no migrations framework — just plain sqlite3 with
WAL mode for concurrent read access from the shell hook's pending-file check.

Tables
------
events          : one row per completed command (preexec + postcmd pair)
in_flight       : one row per command currently running (preexec, no postcmd yet)
baselines       : running statistics per (project_dir, command_sig)
known_repos     : repos the daemon has seen activity in; swept periodically
suppression_state : fingerprint-based dedup, snooze, and dismiss tracking

All timestamps are stored as ISO-8601 strings (UTC) for human readability
when inspecting the DB directly. The DB file lives at ~/.socrates/history.db
(configurable via SocratesConfig.db_name).
"""
from __future__ import annotations

import hashlib
import logging
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

logger = logging.getLogger(__name__)

# ── Schema ─────────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT    NOT NULL,          -- random UUID per shell session
    command       TEXT    NOT NULL,          -- raw command string
    command_sig   TEXT    NOT NULL,          -- normalised command signature (argv[0] + first arg)
    cwd           TEXT    NOT NULL,          -- working directory at execution time
    repo_path     TEXT,                      -- git repo root if inside one, else NULL
    capture_class TEXT    NOT NULL DEFAULT 'UNSAFE',  -- 'SAFE' | 'UNSAFE'
    start_ts      TEXT    NOT NULL,          -- ISO-8601 UTC
    end_ts        TEXT,                      -- ISO-8601 UTC (NULL until postcmd fires)
    exit_code     INTEGER,                   -- NULL until postcmd fires
    stderr_tail   TEXT,                      -- last N bytes of stderr (SAFE commands only)
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_session  ON events (session_id);
CREATE INDEX IF NOT EXISTS idx_events_repo     ON events (repo_path);
CREATE INDEX IF NOT EXISTS idx_events_created  ON events (created_at);

-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS in_flight (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT    NOT NULL,
    command       TEXT    NOT NULL,
    command_sig   TEXT    NOT NULL,
    cwd           TEXT    NOT NULL,
    repo_path     TEXT,
    capture_class TEXT    NOT NULL DEFAULT 'UNSAFE',
    start_ts      TEXT    NOT NULL,          -- ISO-8601 UTC
    -- used to deduplicate stuck-process alerts for the same invocation:
    stuck_fired   INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(session_id, command_sig, start_ts)
);

CREATE INDEX IF NOT EXISTS idx_in_flight_repo ON in_flight (repo_path);

-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS baselines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_dir TEXT    NOT NULL,            -- git repo root (or cwd if not a repo)
    command_sig TEXT    NOT NULL,
    count       INTEGER NOT NULL DEFAULT 0,
    mean_secs   REAL    NOT NULL DEFAULT 0.0,
    variance_secs REAL  NOT NULL DEFAULT 0.0, -- Welford running variance (M2)
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_dir, command_sig)
);

-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS known_repos (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_path        TEXT    NOT NULL UNIQUE,
    last_activity_ts TEXT    NOT NULL,
    last_swept_ts    TEXT,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ──────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS suppression_state (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint     TEXT    NOT NULL UNIQUE,  -- SHA-256 hex of stable issue identity
    rule_type       TEXT    NOT NULL,          -- 'forgotten_push'|'leaked_secrets'|'silent_failure'|'stuck_process'
    repo_path       TEXT,
    branch          TEXT,
    last_fired_ts   TEXT,
    snoozed_until   TEXT,                      -- ISO-8601 UTC or NULL
    dismiss_count   INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_suppression_fp   ON suppression_state (fingerprint);
CREATE INDEX IF NOT EXISTS idx_suppression_repo ON suppression_state (repo_path);
"""


# ── Connection helper ──────────────────────────────────────────────────────────

@contextmanager
def get_conn(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager for a SQLite connection.
    Uses WAL mode (set in SCHEMA_SQL) and row_factory for dict-like access.
    """
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    """Create the schema if it doesn't exist. Safe to call multiple times."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_conn(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
    logger.debug("Database initialised at %s", db_path)


# ── Utility ────────────────────────────────────────────────────────────────────

def utcnow() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def make_command_sig(command: str) -> str:
    """
    Normalise a raw command string into a stable signature for baseline keying.
    Strategy: take argv[0] + first non-flag argument (if any).
    This groups 'pytest tests/foo.py' and 'pytest tests/bar.py' as the same
    baseline key ('pytest tests/'), which is intentional.
    """
    parts = command.strip().split()
    if not parts:
        return "<empty>"
    argv0 = parts[0].lstrip("./")  # strip relative path prefixes
    # Find first non-flag arg
    for part in parts[1:]:
        if not part.startswith("-"):
            # Truncate to avoid unbounded key space on path-heavy commands
            first_arg = part[:40]
            return f"{argv0} {first_arg}"
    return argv0


# ── events table ──────────────────────────────────────────────────────────────

def insert_preexec_event(
    db_path: Path,
    *,
    session_id: str,
    command: str,
    command_sig: str,
    cwd: str,
    repo_path: Optional[str],
    capture_class: str,
    start_ts: str,
) -> int:
    """Insert a new event row when preexec fires. Returns the row id."""
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO events (session_id, command, command_sig, cwd, repo_path,
                                capture_class, start_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, command, command_sig, cwd, repo_path, capture_class, start_ts),
        )
        return cur.lastrowid  # type: ignore[return-value]


def update_postcmd_event(
    db_path: Path,
    *,
    session_id: str,
    command_sig: str,
    start_ts: str,
    end_ts: str,
    exit_code: int,
    stderr_tail: Optional[str],
) -> None:
    """Update the event row when postcmd fires (command has finished)."""
    with get_conn(db_path) as conn:
        conn.execute(
            """
            UPDATE events
            SET end_ts = ?, exit_code = ?, stderr_tail = ?
            WHERE session_id = ? AND command_sig = ? AND start_ts = ?
              AND end_ts IS NULL
            """,
            (end_ts, exit_code, stderr_tail, session_id, command_sig, start_ts),
        )


def get_recent_events(db_path: Path, limit: int = 20) -> list[sqlite3.Row]:
    """Return the most recent completed events."""
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """
            SELECT * FROM events
            WHERE end_ts IS NOT NULL
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()


def prune_events(db_path: Path, max_events: int) -> None:
    """Keep only the most recent max_events rows."""
    with get_conn(db_path) as conn:
        conn.execute(
            """
            DELETE FROM events WHERE id NOT IN (
                SELECT id FROM events ORDER BY created_at DESC LIMIT ?
            )
            """,
            (max_events,),
        )


# ── in_flight table ───────────────────────────────────────────────────────────

def insert_in_flight(
    db_path: Path,
    *,
    session_id: str,
    command: str,
    command_sig: str,
    cwd: str,
    repo_path: Optional[str],
    capture_class: str,
    start_ts: str,
) -> None:
    """Record a command as currently in-flight (preexec, no postcmd yet)."""
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO in_flight
                (session_id, command, command_sig, cwd, repo_path, capture_class, start_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, command, command_sig, cwd, repo_path, capture_class, start_ts),
        )


def delete_in_flight(
    db_path: Path,
    *,
    session_id: str,
    command_sig: str,
    start_ts: str,
) -> None:
    """Remove an in-flight row when postcmd fires."""
    with get_conn(db_path) as conn:
        conn.execute(
            """
            DELETE FROM in_flight
            WHERE session_id = ? AND command_sig = ? AND start_ts = ?
            """,
            (session_id, command_sig, start_ts),
        )


def get_all_in_flight(db_path: Path) -> list[sqlite3.Row]:
    """Return all currently in-flight rows (for the stuck-process sweep)."""
    with get_conn(db_path) as conn:
        cur = conn.execute("SELECT * FROM in_flight ORDER BY start_ts ASC")
        return cur.fetchall()


def mark_in_flight_stuck_fired(
    db_path: Path, *, session_id: str, command_sig: str, start_ts: str
) -> None:
    """Mark that a stuck-process alert was already fired for this invocation."""
    with get_conn(db_path) as conn:
        conn.execute(
            """
            UPDATE in_flight SET stuck_fired = 1
            WHERE session_id = ? AND command_sig = ? AND start_ts = ?
            """,
            (session_id, command_sig, start_ts),
        )


def purge_orphan_in_flight(db_path: Path, ttl_hours: float) -> int:
    """Remove in_flight rows older than ttl_hours (crashed shells). Returns count."""
    cutoff = datetime.now(timezone.utc).timestamp() - ttl_hours * 3600
    cutoff_ts = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM in_flight WHERE start_ts < ?", (cutoff_ts,)
        )
        return cur.rowcount


# ── baselines table ───────────────────────────────────────────────────────────

def upsert_baseline(
    db_path: Path,
    *,
    project_dir: str,
    command_sig: str,
    duration_secs: float,
) -> None:
    """
    Update the running baseline statistics for a (project_dir, command_sig) pair
    using Welford's online algorithm for numerically stable variance computation.
    """
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT count, mean_secs, variance_secs FROM baselines WHERE project_dir=? AND command_sig=?",
            (project_dir, command_sig),
        ).fetchone()

        if row is None:
            count, mean, m2 = 0, 0.0, 0.0
        else:
            count, mean, m2 = row["count"], row["mean_secs"], row["variance_secs"]

        # Welford online update
        count += 1
        delta = duration_secs - mean
        mean += delta / count
        delta2 = duration_secs - mean
        m2 += delta * delta2

        conn.execute(
            """
            INSERT INTO baselines (project_dir, command_sig, count, mean_secs, variance_secs, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_dir, command_sig) DO UPDATE SET
                count = excluded.count,
                mean_secs = excluded.mean_secs,
                variance_secs = excluded.variance_secs,
                updated_at = excluded.updated_at
            """,
            (project_dir, command_sig, count, mean, m2, utcnow()),
        )


def get_baseline(
    db_path: Path, *, project_dir: str, command_sig: str
) -> Optional[dict]:
    """
    Return baseline stats for a (project_dir, command_sig) pair.
    Returns None if no baseline exists yet.
    Returns dict with keys: count, mean_secs, stddev_secs.
    """
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT count, mean_secs, variance_secs FROM baselines WHERE project_dir=? AND command_sig=?",
            (project_dir, command_sig),
        ).fetchone()

    if row is None:
        return None

    count = row["count"]
    mean = row["mean_secs"]
    # Welford M2 → population variance; use sample variance if count > 1
    m2 = row["variance_secs"]
    if count > 1:
        stddev = math.sqrt(m2 / (count - 1))
    elif count == 1:
        stddev = 0.0
    else:
        return None

    return {"count": count, "mean_secs": mean, "stddev_secs": stddev}


# ── known_repos table ─────────────────────────────────────────────────────────

def upsert_known_repo(db_path: Path, repo_path: str) -> None:
    """Record that we've seen activity in this repo, updating the timestamp."""
    now = utcnow()
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO known_repos (repo_path, last_activity_ts)
            VALUES (?, ?)
            ON CONFLICT(repo_path) DO UPDATE SET last_activity_ts = excluded.last_activity_ts
            """,
            (repo_path, now),
        )


def get_all_known_repos(db_path: Path) -> list[sqlite3.Row]:
    with get_conn(db_path) as conn:
        cur = conn.execute("SELECT * FROM known_repos ORDER BY last_activity_ts DESC")
        return cur.fetchall()


def update_repo_swept_ts(db_path: Path, repo_path: str) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE known_repos SET last_swept_ts = ? WHERE repo_path = ?",
            (utcnow(), repo_path),
        )


# ── suppression_state table ───────────────────────────────────────────────────

def get_suppression(db_path: Path, fingerprint: str) -> Optional[sqlite3.Row]:
    with get_conn(db_path) as conn:
        return conn.execute(
            "SELECT * FROM suppression_state WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()


def upsert_suppression_fired(
    db_path: Path,
    *,
    fingerprint: str,
    rule_type: str,
    repo_path: Optional[str],
    branch: Optional[str],
) -> None:
    """Record that an intervention for this fingerprint was fired."""
    now = utcnow()
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO suppression_state (fingerprint, rule_type, repo_path, branch, last_fired_ts)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(fingerprint) DO UPDATE SET last_fired_ts = excluded.last_fired_ts
            """,
            (fingerprint, rule_type, repo_path, branch, now),
        )


def set_snooze(
    db_path: Path, *, fingerprint: str, snoozed_until: str
) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            """
            UPDATE suppression_state SET snoozed_until = ? WHERE fingerprint = ?
            """,
            (snoozed_until, fingerprint),
        )


def increment_dismiss(db_path: Path, fingerprint: str) -> int:
    """Increment dismiss count and return the new value."""
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE suppression_state SET dismiss_count = dismiss_count + 1 WHERE fingerprint = ?",
            (fingerprint,),
        )
        row = conn.execute(
            "SELECT dismiss_count FROM suppression_state WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
    return row["dismiss_count"] if row else 0


def clear_suppression_state(db_path: Path) -> int:
    """Clear all suppression rows (for 'socrates reset-feedback'). Returns count."""
    with get_conn(db_path) as conn:
        cur = conn.execute("DELETE FROM suppression_state")
        return cur.rowcount


def get_suppression_by_repo(db_path: Path, repo_path: str) -> list[sqlite3.Row]:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM suppression_state WHERE repo_path = ?", (repo_path,)
        )
        return cur.fetchall()
