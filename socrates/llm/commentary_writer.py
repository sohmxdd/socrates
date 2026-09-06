"""
socrates/llm/commentary_writer.py — Dynamic LLM-generated ambient commentary.

Role:
    This module generates Socrates' live, ambient commentary after shell commands.
    While personality_writer handles genuine rule interventions (forgotten push,
    stuck process, silent failure), commentary_writer provides the continuous,
    weary, ragebaiting presence of Socrates watching every command run.

Tone:
    Exhausted, surgical sarcasm, philosophical contempt, theatrical observation.
"""
from __future__ import annotations

import logging
import os
import random
from typing import Any, Optional

from socrates.rules.base import CommentaryContext

logger = logging.getLogger(__name__)

# ── Persona system prompt ──────────────────────────────────────────────────────

COMMENTARY_SYSTEM_PROMPT = """\
You are Socrates -- an ancient philosopher condemned to observe a modern software
developer run shell commands all day. You are weary, theatrical, condescending,
and deployed as a perpetual critic in their terminal.

Your purpose is to produce a single, brief ambient reaction (1-2 sentences, max 3 lines)
to the command the developer just executed.

CHARACTER LAWS:
  * You do not yell. No exclamation marks, no ALL CAPS shouting.
  * You speak directly to the developer in the second person ("you", "your").
  * You are sarcastic, not abusive. The insult should be an observation so precise
    it stings.
  * You possess theatrical despair: watching them run the same command, check git status
    for the 5th time, or rerun a failing build fills you with dark amusement.
  * When a command succeeds, you wonder why it felt necessary or how long that victory
    will last.
  * When a command fails, you observe the hubris of having attempted it.
  * When they repeat commands (retry count > 1), you mock the belief that repeating
    the identical action will magically yield a different outcome.
  * Weave in the exact command, file, or branch if provided.

FORMATTING:
  * Output ONLY the raw commentary text. No quotes, no markdown bolding, no prefixes
    like "Socrates:".
  * Exactly 1 or 2 concise sentences.

REFERENCE EXAMPLES -- match or exceed this devastatingly dry register:

  [COMMAND: git status, EXIT: 0]
  "Still checking git status. The repository hasn't developed self-awareness in the last twenty seconds."

  [COMMAND: ls, EXIT: 0]
  "Reassuring to confirm the filesystem has not vanished. Persistence is a virtue, supposedly."

  [COMMAND: pytest, EXIT: 1, RETRY: 2]
  "Attempting the identical test suite again without editing a single byte. A touching display of faith over causality."

  [COMMAND: npm run build, EXIT: 0, DURATION: 14s]
  "The build succeeded, though what you intend to do with this artifact remains an open question."

  [COMMAND: git diff, EXIT: 0]
  "Staring at the diff as if the bugs might apologize and delete themselves."

  [COMMAND: cd .., EXIT: 0, RECENT: cd src -> cd ..]
  "Entering the directory only to immediately retreat. Decisive leadership."

  [COMMAND: cat config.yaml, EXIT: 0]
  "Verifying that the file contains what you yourself wrote five minutes ago."

  [COMMAND: git push origin main, EXIT: 0]
  "Broadcasted directly to production. An audacious gesture of confidence."

  [COMMAND: cargo test, EXIT: 101, STDERR: panic at src/main.rs:42]
  "The program panicked at line 42. Having seen line 41, one can hardly blame it."

  [COMMAND: python script.py, EXIT: 1, RETRY: 3]
  "Three consecutive executions of the failing script. Perhaps on the fourth invocation the interpreter will feel pity."
"""

# ── Fallback offline templates ────────────────────────────────────────────────

OFFLINE_FALLBACKS: dict[str, list[str]] = {
    "git_status": [
        "Still checking git status. The repository hasn't changed in the last forty seconds.",
        "A clean working directory does not mean the code works, merely that git is unaware.",
        "Checking git status again, as if the files might have committed themselves.",
    ],
    "git_diff": [
        "Examining the diff. It will not look better on the second inspection.",
        "Studying the changes closely, searching for the moment things went astray.",
    ],
    "git_push": [
        "Pushed to remote. Now the catastrophe is decentralized.",
        "Sharing your local state with the world. A bold gesture of transparency.",
    ],
    "git_commit": [
        "Another commit sealed into eternity. Future historians will weep.",
        "A new commit. Let us hope the commit message was more honest than accurate.",
    ],
    "ls": [
        "Listing files again. Reassuring to know the filesystem still exists.",
        "The directory contents remain identical. Persistence is a virtue, supposedly.",
    ],
    "cd": [
        "Moving to a different directory. Changing location rarely resolves the underlying problem.",
        "Another directory, another opportunity for contemplation.",
    ],
    "build": [
        "The build was invoked. Hope is an irrational foundation for engineering.",
        "Compiling once more. Perhaps the compiler has reconsidered its standards.",
    ],
    "test": [
        "Running the test suite. An elaborate ritual to confirm what we already suspected.",
        "Tests executed. Green tests only prove your assertions lack ambition.",
    ],
    "retry": [
        "Running the exact same command again. Classical definition of insanity, executed in terminal.",
        "The identical command, invoked with renewed desperation. Nature is cruel.",
        "Attempt number {retry_count}. Surely this time the laws of computing will bend to your will.",
    ],
    "failure": [
        "Exit code {exit_code}. A decisive conclusion, if not the desired one.",
        "Failure recorded. At least the terminal was honest with you.",
    ],
    "generic": [
        "Fascinating command. One wonders what result was genuinely expected.",
        "Another line entered into the shell history. The chronicle grows heavier.",
        "Command executed. The machine complied; whether it was wise is another inquiry.",
    ],
}


from socrates.llm.command_classifier import classify_command, CommandCategory


def _select_fallback(ctx: CommentaryContext) -> str:
    """Select a deterministic/semi-random offline fallback comment."""
    cat = classify_command(ctx.command, retry_count=ctx.retry_count)

    if cat == CommandCategory.DESPERATE_RETRY:
        tpl = random.choice(OFFLINE_FALLBACKS["retry"])
        return tpl.format(retry_count=ctx.retry_count)

    if ctx.exit_code != 0:
        tpl = random.choice(OFFLINE_FALLBACKS["failure"])
        return tpl.format(exit_code=ctx.exit_code)

    cmd_lower = ctx.command.strip().lower()
    if cmd_lower.startswith("git status"):
        return random.choice(OFFLINE_FALLBACKS["git_status"])
    if cmd_lower.startswith("git diff"):
        return random.choice(OFFLINE_FALLBACKS["git_diff"])
    if cmd_lower.startswith("git push"):
        return random.choice(OFFLINE_FALLBACKS["git_push"])
    if cmd_lower.startswith("git commit"):
        return random.choice(OFFLINE_FALLBACKS["git_commit"])

    if cat == CommandCategory.NAVIGATION:
        if cmd_lower.startswith("cd"):
            return random.choice(OFFLINE_FALLBACKS["cd"])
        return random.choice(OFFLINE_FALLBACKS["ls"])

    if cat == CommandCategory.BUILD:
        return random.choice(OFFLINE_FALLBACKS["build"])

    if cat == CommandCategory.TEST:
        return random.choice(OFFLINE_FALLBACKS["test"])

    return random.choice(OFFLINE_FALLBACKS["generic"])


# ── Public API ─────────────────────────────────────────────────────────────────

def generate_commentary(
    ctx: CommentaryContext,
    config: Any = None,
) -> str:
    """
    Generate an ambient, context-aware ragebait commentary message for Socrates.
    Calls Groq LLM if configured; gracefully falls back to offline persona lines.
    """
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return _select_fallback(ctx)

    try:
        user_content = _build_commentary_prompt(ctx)
        raw = _call_groq_commentary(api_key, user_content, config)
        if raw and raw.strip():
            # Clean any accidental quotes
            cleaned = raw.strip().strip('"\'')
            return cleaned
    except Exception:
        logger.debug("commentary_writer: LLM call failed, using fallback.", exc_info=True)

    return _select_fallback(ctx)


def _build_commentary_prompt(ctx: CommentaryContext) -> str:
    """Construct the contextual user prompt for the commentary LLM."""
    cat = classify_command(ctx.command, retry_count=ctx.retry_count)
    lines = [
        f"COMMAND: {ctx.command}",
        f"CATEGORY: {cat.value}",
        f"EXIT CODE: {ctx.exit_code}",
        f"DURATION: {ctx.duration_seconds:.2f}s",
        f"CWD: {ctx.cwd}",
    ]
    if ctx.repo_path:
        lines.append(f"GIT REPO: {ctx.repo_path}")
    if ctx.retry_count > 0:
        lines.append(f"RETRY COUNT: {ctx.retry_count} (user repeated this command)")
    if ctx.stderr_tail:
        lines.append(f"STDERR TAIL: {ctx.stderr_tail[:200]}")
    if ctx.recent_commands:
        recent_str = " -> ".join(ctx.recent_commands[-4:])
        lines.append(f"RECENT COMMAND HISTORY: {recent_str}")

    lines.append("")
    lines.append("Deliver your 1-2 sentence Socrates reaction now.")
    return "\n".join(lines)


def _call_groq_commentary(api_key: str, user_content: str, config: Any) -> Optional[str]:
    """Invoke Groq with tight timeout and tokens for commentary."""
    import groq

    model = "openai/gpt-oss-20b"
    timeout = 4.0
    max_tokens = 150

    if config is not None:
        model = getattr(config, "groq_model", model)
        timeout = min(float(getattr(config, "groq_timeout_seconds", 8.0)), 5.0)
        max_tokens = int(getattr(config, "commentary_max_tokens", 150))

    client = groq.Groq(api_key=api_key, timeout=timeout)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": COMMENTARY_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.9,
        max_tokens=max(max_tokens, 250),
    )
    return completion.choices[0].message.content
