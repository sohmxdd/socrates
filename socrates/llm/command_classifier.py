"""
socrates/llm/command_classifier.py — Fast heuristic classifier for shell commands.

Categorizes commands so Socrates can deploy precisely targeted commentary
(mocking micromanaging git workflows, desperate retries, aimless directory hops, etc.).
Runs locally with zero LLM/network overhead.
"""
from __future__ import annotations

import re
from enum import Enum


class CommandCategory(str, Enum):
    NAVIGATION = "NAVIGATION"
    GIT = "GIT"
    BUILD = "BUILD"
    TEST = "TEST"
    DEBUG = "DEBUG"
    DESPERATE_RETRY = "DESPERATE_RETRY"
    GENERAL = "GENERAL"


_NAV_COMMANDS = {"cd", "ls", "dir", "pwd", "pushd", "popd", "find", "tree"}
_DEBUG_COMMANDS = {"cat", "type", "grep", "rg", "head", "tail", "echo", "less", "more"}
_BUILD_TOKENS = {"build", "compile", "make", "cmake", "cargo", "docker", "pip", "npm", "yarn", "pnpm", "mvn", "gradle", "go build"}
_TEST_TOKENS = {"test", "pytest", "ctest", "jest", "tox", "check", "cargo test", "npm test"}


def classify_command(command: str, retry_count: int = 0) -> CommandCategory:
    """Classify a shell command string into a functional category."""
    if retry_count >= 2:
        return CommandCategory.DESPERATE_RETRY

    raw = command.strip()
    if not raw:
        return CommandCategory.GENERAL

    tokens = raw.split()
    first = tokens[0].lower()
    # Normalize path prefix e.g. /usr/bin/git -> git
    base_cmd = first.replace("\\", "/").split("/")[-1]

    if base_cmd == "git":
        return CommandCategory.GIT

    if base_cmd in _NAV_COMMANDS:
        return CommandCategory.NAVIGATION

    if base_cmd in _DEBUG_COMMANDS:
        return CommandCategory.DEBUG

    raw_lower = raw.lower()
    for t in _TEST_TOKENS:
        if t in raw_lower:
            return CommandCategory.TEST

    for b in _BUILD_TOKENS:
        if b in raw_lower:
            return CommandCategory.BUILD

    return CommandCategory.GENERAL
