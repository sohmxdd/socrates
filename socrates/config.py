"""
socrates/config.py — Configuration loader and typed config dataclass.

Merges config/default_config.yaml (shipped defaults) with the user's
~/.socrates/config.yaml (overrides). Neither file is required to exist.

Usage:
    from socrates.config import load_config, SocratesConfig
    cfg = load_config()
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


# ── Paths ──────────────────────────────────────────────────────────────────────

def get_socrates_home() -> Path:
    """Return the Socrates home directory, creating it if necessary."""
    env_home = os.environ.get("SOCRATES_HOME")
    if env_home:
        home = Path(env_home)
    else:
        home = Path.home() / ".socrates"
    home.mkdir(parents=True, exist_ok=True)
    return home


def _default_config_path() -> Path:
    """Path to the shipped default_config.yaml (next to this package)."""
    return Path(__file__).parent.parent / "config" / "default_config.yaml"


def _user_config_path() -> Path:
    return get_socrates_home() / "config.yaml"


# ── Typed config dataclass ─────────────────────────────────────────────────────

@dataclass
class SocratesConfig:
    # Detection
    sweep_interval_seconds: int = 600
    stuck_sweep_interval_seconds: int = 30
    min_baseline_samples: int = 5
    baseline_k_factor: float = 2.0
    active_commit_window_seconds: int = 300
    dismiss_threshold: int = 3
    intervention_cooldown_seconds: int = 3600
    dismiss_widening_factor: float = 1.5

    @property
    def stuck_k_factor(self) -> float:
        return self.baseline_k_factor

    # LLM tiebreaker
    groq_enabled: bool = True
    groq_model: str = "openai/gpt-oss-20b"
    groq_timeout_seconds: int = 8
    groq_min_call_interval_seconds: float = 2.0
    groq_rate_limit_backoff_seconds: float = 30.0

    # Presentation
    color_enabled: bool = True
    quiet_mode: bool = False
    sound_enabled: bool = False
    sound_file_path: str = ""
    sound_volume: float = 1.0

    # OS Notifications
    os_notifications_enabled: bool = True
    notification_escalation_hours: float = 2.0

    # Daemon internals
    socket_name: str = "daemon.sock"
    db_name: str = "history.db"
    pending_dir_name: str = "pending"
    pid_file_name: str = "daemon.pid"
    log_file_name: str = "daemon.log"
    log_level: str = "INFO"
    max_stderr_tail_bytes: int = 8192
    max_events: int = 10000
    in_flight_orphan_ttl_hours: float = 24.0

    # ── Derived paths (not settable via YAML) ─────────────────────────────────

    def socket_path(self, home: Optional[Path] = None) -> Path:
        h = home or get_socrates_home()
        return h / self.socket_name

    def db_path(self, home: Optional[Path] = None) -> Path:
        h = home or get_socrates_home()
        return h / self.db_name

    def pending_dir(self, home: Optional[Path] = None) -> Path:
        h = home or get_socrates_home()
        p = h / self.pending_dir_name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def pid_path(self, home: Optional[Path] = None) -> Path:
        h = home or get_socrates_home()
        return h / self.pid_file_name

    def log_path(self, home: Optional[Path] = None) -> Path:
        h = home or get_socrates_home()
        return h / self.log_file_name


# ── Loader ─────────────────────────────────────────────────────────────────────

def _load_env(home: Optional[Path] = None) -> None:
    """Load environment variables from ~/.socrates/.env if present."""
    h = home or get_socrates_home()
    env_file = h / ".env"
    if not env_file.is_file():
        return
    try:
        with env_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key:
                        os.environ[key] = val
    except Exception:
        pass


def _load_yaml(path: Path) -> dict:
    """Load a YAML file, returning an empty dict if it doesn't exist."""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def load_config(user_config_path: Optional[Path] = None) -> SocratesConfig:
    """
    Load and merge configuration.

    Priority (highest wins):
        1. User config: ~/.socrates/config.yaml
        2. Shipped defaults: config/default_config.yaml
        3. Dataclass defaults (hardcoded fallback)
    """
    _load_env()
    defaults = _load_yaml(_default_config_path())
    user = _load_yaml(user_config_path or _user_config_path())

    merged = {**defaults, **user}

    # Only pass keys that the dataclass knows about; silently ignore unknown keys.
    known_fields = {f.name for f in SocratesConfig.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    filtered = {k: v for k, v in merged.items() if k in known_fields}

    return SocratesConfig(**filtered)

