"""
socrates/daemon/server.py — The Socrates daemon: Unix socket server and event dispatcher.

This is the long-running background process that:
  1. Listens on a Unix domain socket for events from shell hooks
  2. Stores events in SQLite
  3. Runs the rule engine on each completed event
  4. Periodically sweeps known repos and in-flight processes (via sweep.py)
  5. Routes results through the intervention gate
  6. Delivers messages via pending files (shell pickup) or OS notifications

The daemon's lifetime is completely decoupled from any terminal session.
It is started once (at login via launchd/systemd, or manually) and runs
until explicitly stopped. Many terminal tabs share the same daemon instance.

Architecture note: this module contains only the server/event-loop skeleton.
Rule engine, gate, sweep, and presentation modules are imported as needed.
This keeps the daemon's startup fast and the dependencies clearly separated.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

from socrates.config import SocratesConfig, get_socrates_home, load_config

logger = logging.getLogger(__name__)


# ── Event types sent by shell hooks ───────────────────────────────────────────

PREEXEC_EVENT = "preexec"
POSTCMD_EVENT = "postcmd"


# ── Daemon class ───────────────────────────────────────────────────────────────

class SocratesDaemon:
    """
    The core daemon. Owns the Unix socket server and the asyncio event loop.
    """

    def __init__(self, config: SocratesConfig, home: Path):
        self.config = config
        self.home = home
        self.db_path = config.db_path(home)
        self.socket_path = config.socket_path(home)
        self._server: asyncio.Server | None = None
        self._sweep_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        from socrates.gate.commentary_gate import CommentaryGate
        self.commentary_gate = CommentaryGate(self.config, self.home)
        self._session_cwds: dict[str, str] = {}

    # ── Startup / shutdown ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialise DB, start socket server, and launch periodic sweeps."""
        from socrates.daemon.db import init_db
        init_db(self.db_path)

        # Remove stale socket file if the daemon crashed without cleaning up.
        if self.socket_path.exists():
            self.socket_path.unlink()

        if hasattr(asyncio, "start_unix_server") and sys.platform != "win32":
            self._server = await asyncio.start_unix_server(
                self._handle_connection,
                path=str(self.socket_path),
            )
            logger.info("Socrates daemon listening on %s", self.socket_path)
            try:
                os.chmod(str(self.socket_path), 0o600)
            except OSError:
                pass
        else:
            # Windows fallback: loopback TCP server on 127.0.0.1
            self._server = await asyncio.start_server(
                self._handle_connection,
                host="127.0.0.1",
                port=0,
            )
            sockets = self._server.sockets or []
            port = sockets[0].getsockname()[1] if sockets else 0
            port_path = self.home / "daemon.port"
            port_path.write_text(str(port), encoding="utf-8")
            logger.info("Socrates daemon listening on 127.0.0.1:%d", port)

        # Start the periodic sweep task.
        self._sweep_task = asyncio.create_task(self._run_sweeps(), name="socrates-sweep")

        # Write PID file
        pid_path = self.config.pid_path(self.home)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")

        # Register clean-shutdown signal handlers (POSIX only)
        if sys.platform != "win32":
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                try:
                    loop.add_signal_handler(sig, self._request_shutdown)
                except (NotImplementedError, RuntimeError):
                    pass

        logger.info("Socrates daemon started (PID %d)", os.getpid())

    async def run_until_shutdown(self) -> None:
        """Block until a shutdown signal is received."""
        async with self._server:
            await self._shutdown_event.wait()
        logger.info("Socrates daemon shutting down.")

    def _request_shutdown(self) -> None:
        logger.info("Shutdown signal received.")
        self._shutdown_event.set()
        if self._sweep_task:
            self._sweep_task.cancel()
        pid_path = self.config.pid_path(self.home)
        pid_path.unlink(missing_ok=True)
        port_path = self.home / "daemon.port"
        port_path.unlink(missing_ok=True)

    async def stop(self) -> None:
        """Graceful stop: close socket, clean up socket and PID files."""
        self._request_shutdown()
        if self.socket_path.exists():
            self.socket_path.unlink(missing_ok=True)
        pid_path = self.config.pid_path(self.home)
        pid_path.unlink(missing_ok=True)
        port_path = self.home / "daemon.port"
        port_path.unlink(missing_ok=True)

    def get_health_status(self) -> dict[str, Any]:
        """Return diagnostic health status of the daemon and database."""
        db_exists = self.db_path.exists()
        db_size_bytes = self.db_path.stat().st_size if db_exists else 0
        return {
            "status": "healthy" if self._server is not None else "initializing",
            "pid": os.getpid(),
            "db_exists": db_exists,
            "db_size_bytes": db_size_bytes,
            "home": str(self.home),
            "platform": sys.platform,
        }

    # ── Connection handler ─────────────────────────────────────────────────────

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """
        Handle one incoming connection from a shell hook.
        Reads a single newline-delimited JSON event, dispatches it, closes.
        Fire-and-forget from the shell side — this never writes a response.
        """
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=2.0)
            if not raw:
                return
            try:
                event = json.loads(raw.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                logger.debug("Received malformed JSON event: %r", raw[:200])
                return
            await self._dispatch_event(event)
        except asyncio.TimeoutError:
            logger.debug("Connection timed out before data was received.")
        except Exception:
            logger.exception("Error handling connection.")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    # ── Event dispatch ─────────────────────────────────────────────────────────

    async def _dispatch_event(self, event: dict[str, Any]) -> None:
        """
        Route an incoming event to the appropriate handler.
        All DB I/O and rule evaluation runs in a thread pool executor to avoid
        blocking the event loop (sqlite3 is synchronous).
        """
        event_type = event.get("type")
        if event_type == PREEXEC_EVENT:
            await asyncio.get_running_loop().run_in_executor(
                None, self._handle_preexec, event
            )
        elif event_type == POSTCMD_EVENT:
            await asyncio.get_running_loop().run_in_executor(
                None, self._handle_postcmd, event
            )
        else:
            logger.debug("Unknown event type: %r", event_type)

    def _handle_preexec(self, event: dict[str, Any]) -> None:
        """
        Handle a preexec event:
          - Store partial event row (no exit_code yet)
          - Insert in_flight row
          - Update known_repos if in a git repo
          - Run leaked_secrets rule immediately (pre-execution check)
        """
        from socrates.daemon import db

        session_id = event.get("session_id", "unknown")
        command = event.get("command", "")
        cwd = event.get("cwd", "")
        start_ts = event.get("start_ts", db.utcnow())
        capture_class = event.get("capture_class", "UNSAFE")
        repo_path = self._find_repo_root(cwd)

        command_sig = db.make_command_sig(command)

        # Store the partial event row.
        db.insert_preexec_event(
            self.db_path,
            session_id=session_id,
            command=command,
            command_sig=command_sig,
            cwd=cwd,
            repo_path=repo_path,
            capture_class=capture_class,
            start_ts=start_ts,
        )

        # Track as in-flight for stuck-process detection.
        db.insert_in_flight(
            self.db_path,
            session_id=session_id,
            command=command,
            command_sig=command_sig,
            cwd=cwd,
            repo_path=repo_path,
            capture_class=capture_class,
            start_ts=start_ts,
        )

        # Track the repo for the periodic sweep.
        if repo_path:
            db.upsert_known_repo(self.db_path, repo_path)

        # Run leaked-secrets rule on the preexec command text.
        # This is the only rule that runs at preexec time.
        # It NEVER escalates to Groq — enforced here and in the rule itself.
        self._run_leaked_secrets_check(command, session_id, repo_path, start_ts)

    def _handle_postcmd(self, event: dict[str, Any]) -> None:
        """
        Handle a postcmd event:
          - Complete the event row with exit code + stderr tail
          - Remove from in_flight
          - Update baseline
          - Run silent_failure rule
          - Run stuck_process rule (retrospective edge-case path)
        """
        from socrates.daemon import db

        session_id = event.get("session_id", "unknown")
        command = event.get("command", "")
        command_sig = db.make_command_sig(command)
        cwd = event.get("cwd", "")
        start_ts = event.get("start_ts", "")
        end_ts = event.get("end_ts", db.utcnow())
        exit_code = event.get("exit_code", -1)
        stderr_tail = event.get("stderr_tail")
        capture_class = event.get("capture_class", "UNSAFE")
        repo_path = self._find_repo_root(cwd)

        # Complete the event row.
        db.update_postcmd_event(
            self.db_path,
            session_id=session_id,
            command_sig=command_sig,
            start_ts=start_ts,
            end_ts=end_ts,
            exit_code=exit_code,
            stderr_tail=stderr_tail,
        )

        # Clear from in_flight.
        db.delete_in_flight(
            self.db_path,
            session_id=session_id,
            command_sig=command_sig,
            start_ts=start_ts,
        )

        # Update baseline duration (only for SAFE commands with real timing).
        if start_ts and end_ts and capture_class == "SAFE":
            try:
                from datetime import datetime, timezone
                s = datetime.fromisoformat(start_ts)
                e = datetime.fromisoformat(end_ts)
                duration = (e - s).total_seconds()
                if duration > 0:
                    project_dir = repo_path or cwd
                    db.upsert_baseline(
                        self.db_path,
                        project_dir=project_dir,
                        command_sig=command_sig,
                        duration_secs=duration,
                    )
            except Exception:
                logger.debug("Could not compute duration for baseline.", exc_info=True)

        # Prune old events periodically (every ~100 postcmd events, cheap enough).
        self._maybe_prune_events()

        # Run post-execution rules.
        self._run_post_rules(
            session_id=session_id,
            command=command,
            command_sig=command_sig,
            cwd=cwd,
            repo_path=repo_path,
            exit_code=exit_code,
            stderr_tail=stderr_tail,
            start_ts=start_ts,
            end_ts=end_ts,
            capture_class=capture_class,
        )

        # Ambient commentary reaction
        self._run_commentary(
            session_id=session_id,
            command=command,
            command_sig=command_sig,
            cwd=cwd,
            repo_path=repo_path,
            exit_code=exit_code,
            stderr_tail=stderr_tail,
            start_ts=start_ts,
            end_ts=end_ts,
        )

    # ── Commentary engine ──────────────────────────────────────────────────────

    def _run_commentary(
        self,
        *,
        session_id: str,
        command: str,
        command_sig: str,
        cwd: str,
        repo_path: str | None,
        exit_code: int,
        stderr_tail: str | None,
        start_ts: str,
        end_ts: str,
    ) -> None:
        """
        Evaluate and dispatch ambient commentary for this completed command.
        """
        try:
            from socrates.config import load_config_for_cwd
            from socrates.rules.base import CommentaryContext
            from socrates.llm.commentary_writer import generate_commentary

            effective_config = load_config_for_cwd(cwd)
            if not self.commentary_gate.should_comment(session_id, command, effective_config):
                return

            duration = 0.0
            try:
                from datetime import datetime
                s = datetime.fromisoformat(start_ts)
                e = datetime.fromisoformat(end_ts)
                duration = max(0.0, (e - s).total_seconds())
            except Exception:
                pass

            from socrates.daemon import db
            limit = getattr(effective_config, "commentary_context_window", 5)
            recent_rows = db.get_recent_commands(self.db_path, session_id, limit=limit)
            recent_cmds = [r["command"] for r in recent_rows if r["command"] != command]

            retry_count = 0
            for r in reversed(recent_rows):
                if r["command_sig"] == command_sig and r["exit_code"] != 0:
                    retry_count += 1
                else:
                    break

            prev_cwd = self._session_cwds.get(session_id)
            is_arrival = bool(prev_cwd and prev_cwd != cwd)
            self._session_cwds[session_id] = cwd

            ctx = CommentaryContext(
                session_id=session_id,
                command=command,
                exit_code=exit_code,
                duration_seconds=duration,
                cwd=cwd,
                repo_path=repo_path,
                stderr_tail=stderr_tail,
                recent_commands=tuple(recent_cmds),
                retry_count=retry_count,
                prev_cwd=prev_cwd,
                is_arrival=is_arrival,
            )

            comment = generate_commentary(ctx, config=effective_config)
            if comment and comment.strip():
                self.commentary_gate.write_pending(
                    comment,
                    session_id=session_id,
                    command=command,
                    repo_path=repo_path,
                    effective_config=effective_config,
                )

                self.commentary_gate.record_comment(session_id)
        except Exception:
            logger.debug("Error in commentary processing", exc_info=True)

    # ── Rule evaluation ────────────────────────────────────────────────────────

    def _run_leaked_secrets_check(
        self,
        command: str,
        session_id: str,
        repo_path: str | None,
        start_ts: str,
    ) -> None:
        """
        Run the leaked-secrets rule on command text.
        NEVER escalates to Groq. NEVER sends command text to network.
        Delivers immediately (not via pending file) since this is a pre-exec alert.
        """
        try:
            from socrates.rules.leaked_secrets import check_leaked_secrets
            from socrates.rules.base import Confidence
            result = check_leaked_secrets(command)
            if result.confidence == Confidence.NONE:
                return
            # Route through gate and deliver.
            self._route_result(result, repo_path=repo_path, session_id=session_id)
        except Exception:
            logger.debug("Error in leaked_secrets rule.", exc_info=True)

    def _run_post_rules(
        self,
        *,
        session_id: str,
        command: str,
        command_sig: str,
        cwd: str,
        repo_path: str | None,
        exit_code: int,
        stderr_tail: str | None,
        start_ts: str,
        end_ts: str,
        capture_class: str,
    ) -> None:
        """Run silent_failure and stuck_process rules on a completed event."""
        try:
            from socrates.rules.base import EventData, Confidence
            from socrates.rules.silent_failure import check_silent_failure
            from socrates.rules.stuck_process import check_postcmd as check_stuck_postcmd
            from socrates.daemon.db import get_baseline

            event_data = EventData(
                session_id=session_id,
                command=command,
                command_sig=command_sig,
                cwd=cwd,
                repo_path=repo_path,
                capture_class=capture_class,
                start_ts=start_ts,
                end_ts=end_ts,
                exit_code=exit_code,
                stderr_tail=stderr_tail,
            )

            # Leaked secrets check (defense-in-depth in case preexec was bypassed)
            self._run_leaked_secrets_check(command, session_id, repo_path, start_ts)

            # Silent failure rule.
            sf_result = check_silent_failure(event_data)
            if sf_result.confidence != Confidence.NONE:
                self._route_result(sf_result, repo_path=repo_path, session_id=session_id)


            # Stuck-process rule (postcmd retrospective path — catches edge cases
            # where the process exits before the sweep fires).
            project_dir = repo_path or cwd
            baseline = get_baseline(
                self.db_path,
                project_dir=project_dir,
                command_sig=command_sig,
            )
            # Note: baseline update already happened above; we pass the pre-update
            # baseline here. This is intentional: we don't want to compare against
            # a baseline that includes the current run.
            sp_result = check_stuck_postcmd(event_data, baseline)
            if sp_result.confidence != Confidence.NONE:
                self._route_result(sp_result, repo_path=repo_path, session_id=session_id)

        except Exception:
            logger.debug("Error in post-execution rules.", exc_info=True)

    def _route_result(
        self,
        result: Any,
        *,
        repo_path: str | None,
        session_id: str,
    ) -> None:
        """
        Send a rule result through the confidence gate → Groq tiebreaker (if needed)
        → intervention gate → delivery.

        This is the single choke point for all results. Leaked-secrets results
        are explicitly excluded from the Groq path here.
        """
        try:
            from socrates.rules.base import Confidence, RuleType
            from socrates.gate.intervention_gate import InterventionGate

            gate = InterventionGate(self.db_path, self.config, self.home)

            # LOW_CONFIDENCE → Groq tiebreaker, unless it's leaked_secrets (never network).
            if result.confidence == Confidence.LOW_CONFIDENCE and result.rule_type != RuleType.LEAKED_SECRETS:
                result = self._groq_tiebreak(result)
                if result is None or result.confidence == Confidence.NONE:
                    return

            if result.confidence == Confidence.NONE:
                return

            # Pass through the intervention gate.
            if gate.should_fire(result):
                gate.record_fire(result)
                self._deliver(result, repo_path=repo_path)

        except Exception:
            logger.debug("Error routing result.", exc_info=True)

    def _groq_tiebreak(self, result: Any) -> Any:
        """
        Call Groq for LOW_CONFIDENCE results. Degrades gracefully to NONE on any failure.
        Leaked-secrets results must never reach this function (enforced in caller).
        """
        try:
            from socrates.llm.groq_client import GroqClient
            client = GroqClient(self.config)
            return client.tiebreak(result)
        except Exception:
            logger.debug("Groq tiebreaker failed, treating as NONE.", exc_info=True)
            return None

    def _deliver(self, result: Any, *, repo_path: str | None) -> None:
        """Write the result to a pending file for shell pickup (and optional sound cue)."""
        try:
            from socrates.gate.intervention_gate import InterventionGate
            gate = InterventionGate(self.db_path, self.config, self.home)
            gate.write_pending(result, repo_path=repo_path)
            if getattr(self.config, "sound_enabled", False):
                try:
                    from socrates.presentation.sound import play_sound
                    play_sound(self.config.sound_file_path, self.config.sound_volume)
                except Exception:
                    pass
        except Exception:
            logger.debug("Error delivering result.", exc_info=True)

    # ── Periodic sweep ─────────────────────────────────────────────────────────

    async def _run_sweeps(self) -> None:
        """
        Run two interleaved periodic sweeps on their own clocks:
          - Repo sweep: check known repos for unpushed commits (default: 10 min)
          - In-flight sweep: check running processes vs baselines (default: 30s)

        Both are completely independent of any terminal session.
        """
        from socrates.daemon.sweep import run_repo_sweep, run_in_flight_sweep

        repo_interval = self.config.sweep_interval_seconds
        stuck_interval = self.config.stuck_sweep_interval_seconds

        repo_countdown = repo_interval
        stuck_countdown = stuck_interval

        while not self._shutdown_event.is_set():
            sleep_time = min(repo_countdown, stuck_countdown, 5)
            try:
                await asyncio.sleep(sleep_time)
            except asyncio.CancelledError:
                break

            repo_countdown -= sleep_time
            stuck_countdown -= sleep_time

            if repo_countdown <= 0:
                try:
                    await asyncio.get_running_loop().run_in_executor(
                        None, run_repo_sweep, self.db_path, self.config, self.home
                    )
                except Exception:
                    logger.debug("Repo sweep error.", exc_info=True)
                repo_countdown = repo_interval

            if stuck_countdown <= 0:
                try:
                    await asyncio.get_running_loop().run_in_executor(
                        None, run_in_flight_sweep, self.db_path, self.config, self.home
                    )
                except Exception:
                    logger.debug("In-flight sweep error.", exc_info=True)
                stuck_countdown = stuck_interval

    # ── Utilities ──────────────────────────────────────────────────────────────

    def _find_repo_root(self, cwd: str) -> str | None:
        """
        Walk up the directory tree from cwd to find a .git directory.
        Returns the repo root path as a string, or None.
        """
        path = Path(cwd)
        for parent in [path] + list(path.parents):
            if (parent / ".git").exists():
                return str(parent)
        return None

    def _maybe_prune_events(self) -> None:
        """Prune the events table occasionally to cap DB size."""
        from socrates.daemon.db import prune_events
        import random
        if random.randint(0, 99) < 2:  # ~2% chance per postcmd
            try:
                prune_events(self.db_path, self.config.max_events)
            except Exception:
                logger.debug("Error pruning events.", exc_info=True)


# ── Entry point ────────────────────────────────────────────────────────────────

def configure_logging(config: SocratesConfig, home: Path) -> None:
    """Configure logging to a file in the Socrates home directory."""
    log_path = config.log_path(home)
    handlers: list[logging.Handler] = [
        logging.FileHandler(str(log_path), encoding="utf-8"),
    ]
    if sys.stdout is not None:
        try:
            handlers.append(logging.StreamHandler(sys.stdout))
        except Exception:
            pass

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def run_daemon(*, config: SocratesConfig | None = None, home: Path | None = None) -> None:
    """
    Main entry point for starting the daemon.
    Called by `socrates start` CLI command.
    """
    if home is None:
        home = get_socrates_home()
    if config is None:
        config = load_config()

    configure_logging(config, home)
    daemon = SocratesDaemon(config=config, home=home)

    async def _main() -> None:
        await daemon.start()
        await daemon.run_until_shutdown()

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
