# socrates.zsh — Socrates shell hook for Zsh
#
# Source this file in your ~/.zshrc:
#   source /path/to/socrates/shell/socrates.zsh
#
# What this does:
#   preexec  — fires before a command runs; captures command text + cwd + timestamp;
#              classifies the command (SAFE vs UNSAFE); sets up stderr capture for SAFE commands
#   precmd   — fires after the command finishes (prompt is about to redraw); captures
#              exit code + end timestamp + stderr tail; delivers any pending messages
#
# Output capture design (SAFE commands only):
#   We use exec FD redirection at the shell level — NOT a subshell — so shell-affecting
#   commands (cd, export, source, venv activate, etc.) are completely unaffected.
#   Stderr is redirected to a temp file for the duration of a SAFE command, then restored.
#   stdout is never captured (silent-failure artifact checks use filesystem inspection).
#
# Classifying commands:
#   UNSAFE = builtins that mutate shell state, interactive/TTY commands, venv activation,
#            background jobs (&), sudo shells. These get exit-code-only tracking.
#   SAFE   = everything else (git, make, cargo, pytest, npm, pip, curl, gcc, etc.)

# ── Configuration ──────────────────────────────────────────────────────────────

# Path to this directory (resolved at source time).
_SOCRATES_SHELL_DIR="${${(%):-%x}:h}"
_SOCRATES_CLIENT="${_SOCRATES_SHELL_DIR}/client.py"
_SOCRATES_HOME="${SOCRATES_HOME:-${HOME}/.socrates}"
_SOCRATES_PENDING_DIR="${_SOCRATES_HOME}/pending"

# ── Command classification ─────────────────────────────────────────────────────

# Commands whose first word marks the entire command as UNSAFE.
# These run in the current shell environment and must not have FD redirection.
typeset -a _SOCRATES_UNSAFE_COMMANDS
_SOCRATES_UNSAFE_COMMANDS=(
    # Shell builtins that mutate state
    cd pushd popd
    export set unset setenv
    source '.'
    exec eval
    alias unalias hash
    umask ulimit ulimit
    read readarray mapfile
    # Shell job control
    fg bg wait disown
    # Interactive / TTY-requiring programs
    vim vi nvim nano emacs ed
    less more most
    man info
    top htop btm bpytop glances
    ssh sftp ftp telnet nc ncat
    mysql psql sqlite3 mongosh redis-cli
    python python3 ipython bpython
    node nodejs irb iex ghci lua
    julia octave R
    # Pagers / multiplexers
    tmux screen
    # sudo shells
    'sudo -s' 'sudo -i' 'su'
)

_socrates_is_unsafe() {
    local cmd="$1"
    # Strip leading path components (e.g. /usr/bin/vim → vim)
    local base="${cmd##*/}"
    # Check against unsafe list
    local unsafe
    for unsafe in "${_SOCRATES_UNSAFE_COMMANDS[@]}"; do
        [[ "$base" == "$unsafe" || "$cmd" == "$unsafe" ]] && return 0
    done
    # Background jobs (trailing & or &| or &!)
    [[ "$cmd" =~ '[[:space:]]&[[:space:]]*$' || "$cmd" =~ '&[|!]' ]] && return 0
    # Virtualenv / conda activation
    [[ "$cmd" == *activate* || "$cmd" == *"conda activate"* || "$cmd" == *"deactivate"* ]] && return 0
    # Interactive flags: sudo -s, sudo -i, su -
    [[ "$cmd" =~ '^sudo[[:space:]]+-[siS]' || "$cmd" =~ '^su[[:space:]]' ]] && return 0
    return 1
}

# ── Session ID ─────────────────────────────────────────────────────────────────

# Generate a session UUID once per shell session.
if [[ -z "$_SOCRATES_SESSION_ID" ]]; then
    if command -v uuidgen &>/dev/null; then
        _SOCRATES_SESSION_ID="$(uuidgen)"
    else
        _SOCRATES_SESSION_ID="$(date +%s%N)-$$"
    fi
fi

# ── State variables (set in preexec, consumed in precmd) ──────────────────────

_SOCRATES_CMD=""
_SOCRATES_CMD_START_TS=""
_SOCRATES_CAPTURE_CLASS="UNSAFE"
_SOCRATES_STDERR_TMP=""
_SOCRATES_SAVED_STDERR_FD=-1

# ── preexec hook ──────────────────────────────────────────────────────────────

_socrates_preexec() {
    local cmd="$1"
    local cwd="$(pwd)"
    local start_ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    _SOCRATES_CMD="$cmd"
    _SOCRATES_CMD_START_TS="$start_ts"

    # Classify the command.
    if _socrates_is_unsafe "${cmd%% *}"; then
        _SOCRATES_CAPTURE_CLASS="UNSAFE"
    else
        _SOCRATES_CAPTURE_CLASS="SAFE"
    fi

    # Set up stderr capture for SAFE commands only.
    if [[ "$_SOCRATES_CAPTURE_CLASS" == "SAFE" ]]; then
        _SOCRATES_STDERR_TMP="$(mktemp /tmp/socrates_stderr_XXXXXX 2>/dev/null)"
        if [[ -n "$_SOCRATES_STDERR_TMP" ]]; then
            # Save the current stderr fd and redirect stderr to the tmp file.
            # The command itself runs normally — no subshell.
            exec {_SOCRATES_SAVED_STDERR_FD}>&2
            exec 2>"$_SOCRATES_STDERR_TMP"
        else
            _SOCRATES_CAPTURE_CLASS="UNSAFE"  # fallback if mktemp fails
        fi
    fi

    # Send preexec event to daemon (background — never blocks the shell).
    local payload
    payload="$(python3 -c "
import json,sys
print(json.dumps({
    'type': 'preexec',
    'session_id': '$_SOCRATES_SESSION_ID',
    'command': sys.argv[1],
    'cwd': '$cwd',
    'start_ts': '$start_ts',
    'capture_class': '$_SOCRATES_CAPTURE_CLASS',
}))
" -- "$cmd" 2>/dev/null)"
    [[ -n "$payload" ]] && echo "$payload" | python3 "$_SOCRATES_CLIENT" &>/dev/null &
}

# Register with zsh hook arrays.
preexec_functions+=(_socrates_preexec)

# ── precmd hook ───────────────────────────────────────────────────────────────

_socrates_precmd() {
    local exit_code=$?  # Capture IMMEDIATELY — must be first line.
    local end_ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    # Restore stderr if we redirected it.
    local stderr_tail=""
    if [[ "$_SOCRATES_CAPTURE_CLASS" == "SAFE" && $_SOCRATES_SAVED_STDERR_FD -ge 0 ]]; then
        exec 2>&${_SOCRATES_SAVED_STDERR_FD}
        exec {_SOCRATES_SAVED_STDERR_FD}>&-
        _SOCRATES_SAVED_STDERR_FD=-1
        # Read the tail of captured stderr (last 8KB).
        if [[ -f "$_SOCRATES_STDERR_TMP" ]]; then
            stderr_tail="$(tail -c 8192 "$_SOCRATES_STDERR_TMP" 2>/dev/null)"
            rm -f "$_SOCRATES_STDERR_TMP"
            _SOCRATES_STDERR_TMP=""
        fi
    fi

    # Only send a postcmd event if we have a paired preexec.
    if [[ -n "$_SOCRATES_CMD" ]]; then
        local cmd="$_SOCRATES_CMD"
        local start_ts="$_SOCRATES_CMD_START_TS"
        local capture_class="$_SOCRATES_CAPTURE_CLASS"
        local cwd="$(pwd)"
        local session_id="$_SOCRATES_SESSION_ID"

        # Reset state.
        _SOCRATES_CMD=""
        _SOCRATES_CMD_START_TS=""
        _SOCRATES_CAPTURE_CLASS="UNSAFE"

        # Send postcmd event to daemon (background — never blocks).
        local payload
        payload="$(python3 -c "
import json,sys
# Truncate stderr_tail to avoid enormous payloads.
tail = sys.argv[1][:8192] if sys.argv[1] else None
print(json.dumps({
    'type': 'postcmd',
    'session_id': '$session_id',
    'command': sys.argv[2],
    'cwd': '$cwd',
    'start_ts': '$start_ts',
    'end_ts': '$end_ts',
    'exit_code': $exit_code,
    'stderr_tail': tail,
    'capture_class': '$capture_class',
}))
" -- "$stderr_tail" "$cmd" 2>/dev/null)"
        [[ -n "$payload" ]] && echo "$payload" | python3 "$_SOCRATES_CLIENT" &>/dev/null &
    fi

    # Check for pending Socrates messages for the current repo.
    _socrates_deliver_pending
}

precmd_functions+=(_socrates_precmd)

# ── Pending message delivery ───────────────────────────────────────────────────

# ── Local config discovery & delivery ──────────────────────────────────────────

_socrates_find_local_config_zsh() {
    local dir="$PWD"
    while [[ "$dir" != "/" && -n "$dir" ]]; do
        if [[ -f "$dir/.socrates.yaml" ]]; then
            export SOCRATES_LOCAL_CONFIG="$dir/.socrates.yaml"
            return 0
        elif [[ -f "$dir/.socrates.yml" ]]; then
            export SOCRATES_LOCAL_CONFIG="$dir/.socrates.yml"
            return 0
        fi
        dir="${dir:h}"
    done
    unset SOCRATES_LOCAL_CONFIG 2>/dev/null || true
}

_socrates_deliver_pending() {
    _socrates_find_local_config_zsh
    [[ -d "$_SOCRATES_PENDING_DIR" ]] || return 0

    local repo_root=""
    local dir="$(pwd)"
    while [[ "$dir" != "/" && -n "$dir" ]]; do
        if [[ -d "$dir/.git" ]]; then
            repo_root="$dir"
            break
        fi
        dir="${dir:h}"
    done

    local repo_hash=""
    if [[ -n "$repo_root" ]]; then
        repo_hash="$(python3 -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:16])" -- "$repo_root" 2>/dev/null)"
    fi

    local output
    output="$(python3 -c "
import os, sys, glob, json
pending_dir = sys.argv[1]
repo_hash = sys.argv[2] if len(sys.argv) > 2 else ''

files = []
if repo_hash:
    rf = os.path.join(pending_dir, f'{repo_hash}.json')
    if os.path.isfile(rf): files.append(rf)

for f in sorted(glob.glob(os.path.join(pending_dir, '*.json'))):
    if f not in files: files.append(f)

for path in files:
    if not os.path.isfile(path): continue
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        os.unlink(path)
        is_commentary = data.get('is_commentary', False) or data.get('rule_type') == 'commentary'
        msg = data.get('formatted_message', '').strip()
        if msg:
            if is_commentary:
                print(f'\\033[1;93mSocrates observes:\\033[0m {msg}')
            else:
                if not msg.startswith('Socrates:'):
                    print(f'\\033[1;96mSocrates:\\033[0m {msg}')
                else:
                    print(msg)
    except Exception:
        pass
" "$_SOCRATES_PENDING_DIR" "$repo_hash" 2>/dev/null)"

    if [[ -n "$output" ]]; then
        print ""
        print -P "$output"
        print ""
    fi
}
