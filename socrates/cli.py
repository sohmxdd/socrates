"""
socrates/cli.py — Command-line interface for Socrates.

Commands:
  start             Start the Socrates daemon (background by default, or --foreground)
  stop              Stop the running daemon
  status            Show daemon health, database statistics, and repository state
  logs              View recent daemon logs or recorded events
  reset-feedback    Clear suppression state, active snoozes, and dismiss history
  snooze [BRANCH]   Snooze interventions on a branch (default: current branch, 24 hours)
  install-daemon    Install and enable the background daemon service (launchd / systemd)
  uninstall-daemon  Disable and uninstall the background daemon service
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import click

from socrates.config import SocratesConfig, get_socrates_home, load_config
from socrates.presentation.terminal import format_terminal_message


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with given PID is currently alive."""
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            SYNCHRONIZE = 0x00100000
            process = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if process:
                kernel32.CloseHandle(process)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError):
        return False


def _get_running_pid(config: SocratesConfig, home: Path) -> Optional[int]:
    """Return PID if daemon is running, None otherwise."""
    pid_file = config.pid_path(home)
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        if _is_pid_alive(pid):
            return pid
        # Stale PID file
        pid_file.unlink(missing_ok=True)
        return None
    except (ValueError, OSError):
        pid_file.unlink(missing_ok=True)
        return None


@click.group()
@click.version_option(version="0.1.0", prog_name="socrates")
def main() -> None:
    """Socrates: passive terminal watcher that speaks only when something is wrong."""
    pass


# ── start ──────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--foreground", "-f", is_flag=True, help="Run in foreground (interactive).")
def start(foreground: bool) -> None:
    """Start the Socrates daemon."""
    home = get_socrates_home()
    config = load_config()

    running_pid = _get_running_pid(config, home)
    if running_pid is not None:
        click.echo(f"Socrates daemon is already running (PID {running_pid}).")
        return

    if foreground:
        from socrates.daemon.server import run_daemon
        click.echo(format_terminal_message("Starting daemon in foreground...", color_enabled=config.color_enabled))
        run_daemon(config=config, home=home)
    else:
        # Spawn detached background process
        cmd = [sys.executable, "-m", "socrates.cli", "start", "--foreground"]
        kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        else:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

        proc = subprocess.Popen(cmd, **kwargs)
        # Give it a moment to initialize
        time.sleep(0.5)

        pid = _get_running_pid(config, home) or proc.pid
        click.echo(format_terminal_message(f"Daemon started in background (PID {pid}).", color_enabled=config.color_enabled))


# ── stop ───────────────────────────────────────────────────────────────────────

@main.command()
def stop() -> None:
    """Stop the running Socrates daemon."""
    home = get_socrates_home()
    config = load_config()

    pid = _get_running_pid(config, home)
    if pid is None:
        click.echo("Socrates daemon is not running.")
        return

    try:
        if sys.platform == "win32":
            # On Windows terminate process via taskkill
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        pass

    # Clean up PID, socket, and port files
    config.pid_path(home).unlink(missing_ok=True)
    config.socket_path(home).unlink(missing_ok=True)
    (home / "daemon.port").unlink(missing_ok=True)
    click.echo("Socrates daemon stopped.")


# ── status ─────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--metrics", "-m", is_flag=True, help="Show raw daemon metrics table instead of commentary.")
def status(metrics: bool) -> None:
    """Show Socrates daemon status with dynamic ragebait (or --metrics for raw table)."""
    home = get_socrates_home()
    config = load_config()
    db_path = config.db_path(home)

    pid = _get_running_pid(config, home)
    is_running = pid is not None
    status_str = f"RUNNING (PID {pid})" if is_running else "STOPPED"

    # Database statistics
    total_events = 0
    total_suppressions = 0
    active_in_flight = 0
    repos: list[dict[str, Any]] = []
    if db_path.exists():
        try:
            from socrates.daemon import db
            repos = db.get_all_known_repos(db_path)
            in_flight = db.get_all_in_flight(db_path)
            active_in_flight = len(in_flight)

            with db.get_conn(db_path) as conn:
                cur = conn.execute("SELECT COUNT(*) FROM events")
                total_events = cur.fetchone()[0]
                cur = conn.execute("SELECT COUNT(*) FROM suppression_state")
                total_suppressions = cur.fetchone()[0]
        except Exception:
            pass

    # Git repository context
    repo_path = None
    branch = None
    unpushed_count = 0
    try:
        from socrates.daemon.git_watcher import get_repo_root, get_current_branch, count_unpushed_commits
        repo_root = get_repo_root(Path.cwd())
        if repo_root:
            repo_path = str(repo_root)
            branch = get_current_branch(repo_root)
            unpushed_count = count_unpushed_commits(repo_root, branch) if branch else 0
    except Exception:
        pass

    if metrics:
        click.echo("=" * 48)
        click.echo("  Socrates — Terminal Observer Status")
        click.echo("=" * 48)
        click.echo(f"  Daemon status:        {status_str}")
        click.echo(f"  Socrates home:        {home}")
        port_path = home / "daemon.port"
        if port_path.exists():
            click.echo(f"  TCP loopback port:    {port_path.read_text(encoding='utf-8').strip()}")
        else:
            click.echo(f"  Socket path:          {config.socket_path(home)}")
        click.echo(f"  Database path:        {db_path}")

        if db_path.exists():
            size_kb = db_path.stat().st_size / 1024
            click.echo(f"  Database size:        {size_kb:.1f} KB")
            click.echo(f"  Total logged events:  {total_events}")
            click.echo(f"  Active in-flight:     {active_in_flight}")
            click.echo(f"  Tracked repositories: {len(repos)}")
            click.echo(f"  Suppression rules:    {total_suppressions}")

            if repos:
                click.echo("\n  Tracked Repositories:")
                for r in repos[:5]:
                    swept = r["last_swept_ts"] or "never"
                    click.echo(f"    - {r['repo_path']} (last swept: {swept})")
        else:
            click.echo("  Database:             Not yet initialized")
        click.echo("=" * 48)
        return

    # Default: Extreme dynamic ragebait from Socrates
    from socrates.llm.commentary_writer import generate_status_ragebait

    roast = generate_status_ragebait(
        status_str=status_str,
        total_events=total_events,
        tracked_repos=len(repos),
        active_in_flight=active_in_flight,
        repo_path=repo_path,
        branch=branch,
        unpushed_count=unpushed_count,
        config=config,
    )
    click.echo(format_terminal_message(roast, color_enabled=config.color_enabled))



# ── logs ───────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--tail", "-n", default=20, help="Number of lines to show (default: 20).")
def logs(tail: int) -> None:
    """View recent daemon logs."""
    home = get_socrates_home()
    config = load_config()
    log_file = config.log_path(home)

    if not log_file.exists():
        click.echo("No daemon log file found.")
        return

    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        recent = lines[-tail:] if len(lines) > tail else lines
        for line in recent:
            click.echo(line)
    except Exception as e:
        click.echo(f"Error reading log file: {e}")


# ── reset-feedback ─────────────────────────────────────────────────────────────

@main.command(name="reset-feedback")
def reset_feedback() -> None:
    """Clear all suppression state, snoozes, and dismiss feedback."""
    home = get_socrates_home()
    config = load_config()
    db_path = config.db_path(home)

    if db_path.exists():
        from socrates.daemon.db import clear_suppression_state
        clear_suppression_state(db_path)

    # Clean pending messages directory
    pending_dir = config.pending_dir(home)
    if pending_dir.exists():
        for pfile in pending_dir.glob("*.json"):
            pfile.unlink(missing_ok=True)

    click.echo(format_terminal_message("Suppression state reset. All snoozes and dismiss history cleared.", color_enabled=config.color_enabled))


# ── snooze ─────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("branch", required=False)
@click.option("--hours", "-h", default=24.0, help="Hours to snooze (default: 24).")
def snooze(branch: Optional[str], hours: float) -> None:
    """Snooze interventions on a git branch (default: current branch, 24h)."""
    home = get_socrates_home()
    config = load_config()
    db_path = config.db_path(home)

    # Auto-detect branch if not provided
    if not branch:
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res.returncode == 0 and res.stdout.strip():
                branch = res.stdout.strip()
        except Exception:
            pass

    target_branch = branch or "all"

    # Find current repo if possible
    repo_path = ""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if res.returncode == 0 and res.stdout.strip():
            repo_path = res.stdout.strip()
    except Exception:
        pass

    if db_path.exists() and repo_path:
        from socrates.gate.intervention_gate import InterventionGate
        gate = InterventionGate(db_path, config, home)
        gate.snooze_branch(repo_path, target_branch, hours)

    click.echo(format_terminal_message(f"Snoozed branch '{target_branch}' for {hours:g} hours.", color_enabled=config.color_enabled))


# ── install-daemon ─────────────────────────────────────────────────────────────

@main.command(name="install-daemon")
def install_daemon() -> None:
    """Install and enable background daemon service (launchd on macOS / systemd on Linux)."""
    home = get_socrates_home()
    socrates_bin = shutil.which("socrates") or f"{sys.executable} -m socrates.cli"

    if sys.platform == "darwin":
        plist_dir = Path.home() / "Library" / "LaunchAgents"
        plist_dir.mkdir(parents=True, exist_ok=True)
        plist_path = plist_dir / "com.socrates.daemon.plist"

        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.socrates.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>-m</string>
        <string>socrates.cli</string>
        <string>start</string>
        <string>--foreground</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{home / "daemon.log"}</string>
    <key>StandardErrorPath</key>
    <string>{home / "daemon.log"}</string>
</dict>
</plist>
"""
        plist_path.write_text(plist_content, encoding="utf-8")
        try:
            subprocess.run(["launchctl", "load", str(plist_path)], check=True)
            click.echo(f"Installed and loaded launchd agent at {plist_path}")
        except Exception as e:
            click.echo(f"Created {plist_path}. Run 'launchctl load {plist_path}' to activate.")

    elif sys.platform.startswith("linux"):
        systemd_dir = Path.home() / ".config" / "systemd" / "user"
        systemd_dir.mkdir(parents=True, exist_ok=True)
        service_path = systemd_dir / "socrates.service"

        service_content = f"""[Unit]
Description=Socrates Terminal Observer Daemon
After=default.target

[Service]
ExecStart={sys.executable} -m socrates.cli start --foreground
Restart=always
RestartSec=5
StandardOutput=append:{home / "daemon.log"}
StandardError=append:{home / "daemon.log"}

[Install]
WantedBy=default.target
"""
        service_path.write_text(service_content, encoding="utf-8")
        try:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "--user", "enable", "--now", "socrates"], check=True)
            click.echo(f"Installed and enabled systemd user service at {service_path}")
        except Exception as e:
            click.echo(f"Created {service_path}. Run 'systemctl --user enable --now socrates' to activate.")

    else:
        click.echo(f"install-daemon is supported on macOS (launchd) and Linux (systemd user). Current platform: {sys.platform}")


# ── uninstall-daemon ───────────────────────────────────────────────────────────

@main.command(name="uninstall-daemon")
def uninstall_daemon() -> None:
    """Uninstall and disable background daemon service."""
    if sys.platform == "darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / "com.socrates.daemon.plist"
        if plist_path.exists():
            try:
                subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
            except Exception:
                pass
            plist_path.unlink(missing_ok=True)
            click.echo(f"Uninstalled launchd service from {plist_path}")
        else:
            click.echo("No launchd service file found.")

    elif sys.platform.startswith("linux"):
        service_path = Path.home() / ".config" / "systemd" / "user" / "socrates.service"
        if service_path.exists():
            try:
                subprocess.run(["systemctl", "--user", "disable", "--now", "socrates"], check=False)
            except Exception:
                pass
            service_path.unlink(missing_ok=True)
            click.echo(f"Uninstalled systemd user service from {service_path}")
        else:
            click.echo("No systemd service file found.")

    else:
        click.echo(f"uninstall-daemon is supported on macOS and Linux. Current platform: {sys.platform}")


# ── demo ───────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--interactive", "-i", is_flag=True, help="Launch interactive menu for live video demo.")
def demo(interactive: bool) -> None:
    """Run demonstration showcase of Socrates detection rules and personality."""
    import importlib.util
    demo_script = Path(__file__).resolve().parent.parent / "scripts" / "demo.py"
    if not demo_script.exists():
        click.echo("Demo script not found at scripts/demo.py")
        return

    spec = importlib.util.spec_from_file_location("socrates_demo", str(demo_script))
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if interactive and hasattr(mod, "run_interactive"):
            mod.run_interactive()
        elif hasattr(mod, "run_demo"):
            mod.run_demo()


# ── init ───────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--commentary", is_flag=True, default=False, help="Enable ambient commentary in this project.")
@click.option("--commentary-rate", type=float, default=None, help="Commentary trigger rate (0.0 to 1.0).")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing .socrates.yaml if present.")
def init(commentary: bool, commentary_rate: Optional[float], force: bool) -> None:
    """Initialize a project-local .socrates.yaml configuration."""
    target = Path.cwd() / ".socrates.yaml"
    if target.exists() and not force:
        click.echo(f"Configuration file already exists at {target}. Use --force to overwrite.")
        return

    rate = commentary_rate if commentary_rate is not None else (0.8 if commentary else 0.6)

    content = f"""# Socrates Project Configuration
# Created by `socrates init`

# Ambient commentary mode
commentary_enabled: {str(commentary).lower()}
commentary_rate: {rate}
commentary_cooldown_seconds: 15

# Commands to skip commentary for
commentary_skip_commands:
  - "clear"
  - "cls"
  - "pwd"
  - "exit"
"""
    target.write_text(content, encoding="utf-8")
    click.echo(f"Created project configuration: {target}")
    if commentary:
        click.echo("Ambient commentary enabled at rate: " + str(rate))
    else:
        click.echo("Commentary is disabled. Run `socrates commentary on` or edit .socrates.yaml to enable.")


# ── config ─────────────────────────────────────────────────────────────────────

@main.group()
def config() -> None:
    """Inspect and manage Socrates configuration."""
    pass


@config.command(name="show")
@click.option("--cwd", type=click.Path(exists=True, file_okay=False, dir_okay=True), default=None, help="Working directory to evaluate config for.")
def config_show(cwd: Optional[str]) -> None:
    """Show effective configuration for the current or specified directory."""
    from socrates.config import find_local_config, load_config_for_cwd, _user_config_path

    target_cwd = Path(cwd).resolve() if cwd else Path.cwd().resolve()
    local_cfg = find_local_config(target_cwd)
    user_cfg = _user_config_path()

    click.echo(f"Working Directory: {target_cwd}")
    click.echo(f"Local Config:      {local_cfg if local_cfg else '(none)'}")
    click.echo(f"User Config:       {user_cfg if user_cfg.exists() else '(none)'}")
    click.echo("-" * 50)

    cfg = load_config_for_cwd(target_cwd)
    click.echo(f"commentary_enabled:          {cfg.commentary_enabled}")
    click.echo(f"commentary_rate:             {cfg.commentary_rate}")
    click.echo(f"commentary_cooldown_seconds: {cfg.commentary_cooldown_seconds}")
    click.echo(f"commentary_skip_commands:    {cfg.commentary_skip_commands}")
    click.echo(f"groq_enabled:                {cfg.groq_enabled}")
    click.echo(f"groq_model:                  {cfg.groq_model}")
    click.echo(f"color_enabled:               {cfg.color_enabled}")
    click.echo(f"quiet_mode:                  {cfg.quiet_mode}")


# ── commentary ─────────────────────────────────────────────────────────────────

@main.group()
def commentary() -> None:
    """Manage Socrates ambient commentary mode."""
    pass


@commentary.command(name="on")
@click.option("--rate", type=float, default=None, help="Commentary trigger rate (0.0 to 1.0).")
@click.option("--local", "scope_local", is_flag=True, help="Update .socrates.yaml in current directory.")
@click.option("--global", "scope_global", is_flag=True, help="Update global ~/.socrates/config.yaml.")
def commentary_on(rate: Optional[float], scope_local: bool, scope_global: bool) -> None:
    """Enable ambient commentary."""
    import yaml
    from socrates.config import find_local_config, _user_config_path

    # Determine target file
    target: Path
    if scope_local:
        target = Path.cwd() / ".socrates.yaml"
    elif scope_global:
        target = _user_config_path()
    else:
        # Default to local if local exists, otherwise global
        loc = find_local_config(Path.cwd())
        target = loc if loc else _user_config_path()

    data: dict = {}
    if target.exists():
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}

    data["commentary_enabled"] = True
    if rate is not None:
        data["commentary_rate"] = rate

    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False)

    click.echo(f"Enabled Socrates ambient commentary in {target}")
    if rate is not None:
        click.echo(f"Commentary rate set to {rate}")


@commentary.command(name="off")
@click.option("--local", "scope_local", is_flag=True, help="Update .socrates.yaml in current directory.")
@click.option("--global", "scope_global", is_flag=True, help="Update global ~/.socrates/config.yaml.")
def commentary_off(scope_local: bool, scope_global: bool) -> None:
    """Disable ambient commentary."""
    import yaml
    from socrates.config import find_local_config, _user_config_path

    target: Path
    if scope_local:
        target = Path.cwd() / ".socrates.yaml"
    elif scope_global:
        target = _user_config_path()
    else:
        loc = find_local_config(Path.cwd())
        target = loc if loc else _user_config_path()

    data: dict = {}
    if target.exists():
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}

    data["commentary_enabled"] = False
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False)

    click.echo(f"Disabled Socrates ambient commentary in {target}")


@commentary.command(name="status")
@click.option("--cwd", type=click.Path(exists=True, file_okay=False, dir_okay=True), default=None, help="Working directory.")
def commentary_status(cwd: Optional[str]) -> None:
    """Show current commentary configuration and active scope."""
    from socrates.config import find_local_config, load_config_for_cwd, _user_config_path

    target_cwd = Path(cwd).resolve() if cwd else Path.cwd().resolve()
    cfg = load_config_for_cwd(target_cwd)
    local_cfg = find_local_config(target_cwd)

    status_str = "ENABLED" if cfg.commentary_enabled else "DISABLED"
    click.echo(f"Commentary Status: {status_str}")
    click.echo(f"Active Scope:      {'Local project (' + str(local_cfg) + ')' if local_cfg else 'Global'}")
    click.echo(f"Rate:              {cfg.commentary_rate} ({int(cfg.commentary_rate * 100)}% chance)")
    click.echo(f"Cooldown:          {cfg.commentary_cooldown_seconds}s between comments")
    click.echo(f"Skip Commands:     {', '.join(cfg.commentary_skip_commands)}")


@commentary.command(name="test")
@click.argument("cmd", default="git status")
@click.option("--exit-code", type=int, default=0, help="Simulated exit code.")
@click.option("--retries", type=int, default=0, help="Simulated retry count.")
def commentary_test(cmd: str, exit_code: int, retries: int) -> None:
    """Test what Socrates would observe for a given command without running it."""
    from socrates.config import load_config_for_cwd
    from socrates.rules.base import CommentaryContext
    from socrates.llm.commentary_writer import generate_commentary
    from socrates.presentation.terminal import print_commentary

    cfg = load_config_for_cwd(Path.cwd())
    ctx = CommentaryContext(
        session_id="test-session",
        command=cmd,
        exit_code=exit_code,
        duration_seconds=0.42,
        cwd=str(Path.cwd()),
        recent_commands=("git status", "git diff", cmd),
        retry_count=retries,
    )

    comment = generate_commentary(ctx, config=cfg)
    print_commentary(comment, color_enabled=cfg.color_enabled)


if __name__ == "__main__":
    main()



