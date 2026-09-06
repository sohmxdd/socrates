# socrates.bash — Socrates shell hook for Bash
#
# Source this file in your ~/.bashrc:
#   source /path/to/socrates/shell/socrates.bash
#
# Requires bash-preexec for preexec/precmd support in Bash:
#   https://github.com/rcaloras/bash-preexec
#   Install: curl https://raw.githubusercontent.com/rcaloras/bash-preexec/master/bash-preexec.sh -o ~/.bash-preexec.sh
#   Then add to ~/.bashrc (BEFORE sourcing this file):
#     [[ -f ~/.bash-preexec.sh ]] && source ~/.bash-preexec.sh
#
# The logic here is identical to socrates.zsh; see that file for full commentary.
# Differences from the zsh version:
#   - Uses bash array syntax
#   - Registers via preexec_functions / precmd_functions (bash-preexec arrays)
#   - ${BASH_SOURCE[0]} for self-path resolution instead of zsh's %x

# ── Configuration ──────────────────────────────────────────────────────────────

_SOCRATES_SHELL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_SOCRATES_CLIENT="${_SOCRATES_SHELL_DIR}/client.py"
_SOCRATES_HOME="${SOCRATES_HOME:-${HOME}/.socrates}"
_SOCRATES_PENDING_DIR="${_SOCRATES_HOME}/pending"

# ── Command classification ─────────────────────────────────────────────────────

_SOCRATES_UNSAFE_CMDS=(
    cd pushd popd
    export set unset
    source
    exec eval
    alias unalias hash
    umask ulimit
    read readarray mapfile
    fg bg wait disown
    vim vi nvim nano emacs ed
    less more most
    man info
    top htop btm
    ssh sftp ftp telnet nc ncat
    mysql psql sqlite3 mongosh redis-cli
    python python3 ipython bpython
    node nodejs irb iex ghci lua julia octave R
    tmux screen
)

_socrates_is_unsafe_bash() {
    local cmd="${1%% *}"   # first word only
    local base="${cmd##*/}"
    local unsafe
    for unsafe in "${_SOCRATES_UNSAFE_CMDS[@]}"; do
        [[ "$base" == "$unsafe" || "$cmd" == "$unsafe" ]] && return 0
    done
    # Background jobs
    [[ "$1" =~ [[:space:]]'&'[[:space:]]*$ || "$1" =~ '&[|!]' ]] && return 0
    # Virtualenv / conda
    [[ "$1" == *activate* || "$1" == *"conda activate"* || "$1" == *deactivate* ]] && return 0
    # sudo shells
    [[ "$1" =~ ^sudo[[:space:]]+-[siS] || "$1" =~ ^su[[:space:]] ]] && return 0
    return 1
}

# ── Session ID ─────────────────────────────────────────────────────────────────

if [[ -z "$_SOCRATES_SESSION_ID" ]]; then
    if command -v uuidgen &>/dev/null; then
        _SOCRATES_SESSION_ID="$(uuidgen)"
    else
        _SOCRATES_SESSION_ID="$(date +%s%N)-$$"
    fi
fi

# ── State variables ────────────────────────────────────────────────────────────

_SOCRATES_CMD=""
_SOCRATES_CMD_START_TS=""
_SOCRATES_CAPTURE_CLASS="UNSAFE"
_SOCRATES_STDERR_TMP=""
_SOCRATES_SAVED_STDERR_FD=-1

# ── preexec hook ───────────────────────────────────────────────────────────────

_socrates_preexec_bash() {
    local cmd="$1"
    local cwd
    cwd="$(pwd)"
    local start_ts
    start_ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    _SOCRATES_CMD="$cmd"
    _SOCRATES_CMD_START_TS="$start_ts"

    if _socrates_is_unsafe_bash "$cmd"; then
        _SOCRATES_CAPTURE_CLASS="UNSAFE"
    else
        _SOCRATES_CAPTURE_CLASS="SAFE"
    fi

    if [[ "$_SOCRATES_CAPTURE_CLASS" == "SAFE" ]]; then
        _SOCRATES_STDERR_TMP="$(mktemp /tmp/socrates_stderr_XXXXXX 2>/dev/null)"
        if [[ -n "$_SOCRATES_STDERR_TMP" ]]; then
            exec {_SOCRATES_SAVED_STDERR_FD}>&2
            exec 2>"$_SOCRATES_STDERR_TMP"
        else
            _SOCRATES_CAPTURE_CLASS="UNSAFE"
        fi
    fi

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

# ── precmd hook ────────────────────────────────────────────────────────────────

_socrates_precmd_bash() {
    local exit_code=$?
    local end_ts
    end_ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    local stderr_tail=""
    if [[ "$_SOCRATES_CAPTURE_CLASS" == "SAFE" && $_SOCRATES_SAVED_STDERR_FD -ge 0 ]]; then
        exec 2>&"$_SOCRATES_SAVED_STDERR_FD"
        exec {_SOCRATES_SAVED_STDERR_FD}>&-
        _SOCRATES_SAVED_STDERR_FD=-1
        if [[ -f "$_SOCRATES_STDERR_TMP" ]]; then
            stderr_tail="$(tail -c 8192 "$_SOCRATES_STDERR_TMP" 2>/dev/null)"
            rm -f "$_SOCRATES_STDERR_TMP"
            _SOCRATES_STDERR_TMP=""
        fi
    fi

    if [[ -n "$_SOCRATES_CMD" ]]; then
        local cmd="$_SOCRATES_CMD"
        local start_ts="$_SOCRATES_CMD_START_TS"
        local capture_class="$_SOCRATES_CAPTURE_CLASS"
        local cwd
        cwd="$(pwd)"
        local session_id="$_SOCRATES_SESSION_ID"

        _SOCRATES_CMD=""
        _SOCRATES_CMD_START_TS=""
        _SOCRATES_CAPTURE_CLASS="UNSAFE"

        local payload
        payload="$(python3 -c "
import json,sys
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

    _socrates_deliver_pending_bash
}

# ── Pending message delivery ───────────────────────────────────────────────────

# ── Local config discovery & delivery ──────────────────────────────────────────

_socrates_find_local_config_bash() {
    local dir="$PWD"
    while [[ "$dir" != "/" && -n "$dir" ]]; do
        if [[ -f "$dir/.socrates.yaml" ]]; then
            export SOCRATES_LOCAL_CONFIG="$dir/.socrates.yaml"
            return 0
        elif [[ -f "$dir/.socrates.yml" ]]; then
            export SOCRATES_LOCAL_CONFIG="$dir/.socrates.yml"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    unset SOCRATES_LOCAL_CONFIG 2>/dev/null || true
}

_socrates_deliver_pending_bash() {
    _socrates_find_local_config_bash
    [[ -d "$_SOCRATES_PENDING_DIR" ]] || return 0

    local repo_root=""
    local dir="$(pwd)"
    while [[ "$dir" != "/" && -n "$dir" ]]; do
        if [[ -d "$dir/.git" ]]; then
            repo_root="$dir"
            break
        fi
        dir="$(dirname "$dir")"
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
        echo ""
        echo -e "$output"
        echo ""
    fi
}

# ── Register hooks (requires bash-preexec) ────────────────────────────────────

preexec_functions+=(_socrates_preexec_bash)
precmd_functions+=(_socrates_precmd_bash)
