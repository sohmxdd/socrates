"""
socrates/presentation/sound.py — Non-blocking audio playback for intervention cues.

Requirements:
  - Non-verbal sound cue only (chime/ding, not a voice clip).
  - Non-blocking playback: fired as a detached background subprocess.
  - Platform detection:
      macOS: afplay
      Linux: paplay -> aplay -> ffplay
    Result is cached after first probe.
  - Fails silently (debug-log only) if player or file is unavailable.
  - Socrates ships NO default sound file — user must configure sound_file_path.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Cached player: None = not probed yet; "" = probed but no player found
_CACHED_PLAYER: Optional[str] = None


def find_sound_player() -> Optional[str]:
    """
    Probe for an available command-line audio player based on platform.
    Caches the result so probing only happens once.
    """
    global _CACHED_PLAYER
    if _CACHED_PLAYER is not None:
        return _CACHED_PLAYER if _CACHED_PLAYER else None

    candidates: list[str] = []
    if sys.platform == "darwin":
        candidates = ["afplay"]
    elif sys.platform.startswith("linux"):
        candidates = ["paplay", "aplay", "ffplay"]
    else:
        # Fallback for Windows or other platforms
        candidates = ["ffplay", "powershell"]

    for player in candidates:
        if shutil.which(player):
            _CACHED_PLAYER = player
            logger.debug("Found audio player: %s", player)
            return player

    _CACHED_PLAYER = ""
    logger.debug("No supported audio player found on system.")
    return None


def play_sound(sound_file_path: str, volume: float = 1.0) -> bool:
    """
    Play an audio file non-blockingly in a detached subprocess.
    Returns True if playback was spawned, False if skipped/failed.
    Fails silently — never raises an exception.
    """
    if not sound_file_path:
        return False

    path = Path(sound_file_path)
    if not path.exists() or not path.is_file():
        logger.debug("Sound file does not exist: %s", sound_file_path)
        return False

    player = find_sound_player()
    if not player:
        return False

    # Clamp volume between 0.0 and 1.0
    vol = max(0.0, min(1.0, volume))

    cmd: list[str] = []
    if player == "afplay":
        # afplay -v <0..1> <path>
        cmd = ["afplay", "-v", str(vol), str(path)]
    elif player == "paplay":
        # paplay --volume=<0..65536> <path>
        pa_vol = int(vol * 65536)
        cmd = ["paplay", f"--volume={pa_vol}", str(path)]
    elif player == "aplay":
        cmd = ["aplay", "-q", str(path)]
    elif player == "ffplay":
        # ffplay -nodisp -autoexit -volume <0..100>
        ff_vol = int(vol * 100)
        cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-volume", str(ff_vol), str(path)]
    else:
        return False

    try:
        # Spawn detached non-blocking subprocess
        kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        else:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

        subprocess.Popen(cmd, **kwargs)
        logger.debug("Spawned audio playback: %s", cmd)
        return True
    except Exception:
        logger.debug("Failed to spawn audio playback process.", exc_info=True)
        return False
