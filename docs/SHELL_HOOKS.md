# Socrates Shell Integration & Lifecycle Hooks

Socrates attaches to your active interactive shell sessions to observe command execution without wrapping or altering command semantics.

## Supported Shells

| Shell | Mechanism | Stderr Interception | State Mutation Safe |
| :--- | :--- | :--- | :--- |
| **Zsh** | `preexec` / `precmd` hooks | FD duplication (`exec {_FD}>&2`) | Yes (`cd`, `export` work) |
| **Bash** | `bash-preexec` arrays | FD duplication (`exec {_FD}>&2`) | Yes (`cd`, `export` work) |
| **PowerShell** | `PSReadLine` handler + prompt | Native command history inspection | Yes (`cd`, `$env:VAR` work) |

---

## The Two-Tier Command Classifier

To prevent breaking interactive curses apps, REPLs, or environment changers, Socrates classifies every command before execution:

### 1. `UNSAFE` Classification
Commands that mutate shell state or demand full TTY control:
- **Builtins**: `cd`, `pushd`, `popd`, `export`, `set`, `unset`, `source`, `.`, `exec`, `eval`
- **Interactive Programs**: `vim`, `nvim`, `nano`, `emacs`, `top`, `htop`, `ssh`, `python`, `node`, `psql`
- **Job Control**: `fg`, `bg`, `wait`, trailing `&`
- **Privileged Shells**: `sudo -s`, `sudo -i`, `su`

**Behavior for UNSAFE commands**: Zero file descriptor manipulation. The command executes 100% naked in the host terminal. Only process start/stop timestamps and exit status are recorded.

### 2. `SAFE` Classification
Standard batch commands (`git`, `cargo`, `pytest`, `npm`, `make`, `gcc`, `curl`):
- `preexec`: Redirects file descriptor 2 (stderr) to a temporary buffer via shell FD saving.
- `precmd`: Restores file descriptor 2 immediately, reads up to 8KB of the stderr tail, and unlinks the buffer.
