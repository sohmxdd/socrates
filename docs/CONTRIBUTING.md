# Contributing to Socrates

Thank you for contributing to Socrates.

## Code Standards

1. **Python Compatibility**: Socrates targets Python 3.10 through 3.14+.
2. **Deterministic Rules First**: Every new failure mode should be handled deterministically without network access whenever possible.
3. **Zero Secret Exfiltration**: Never send raw command strings containing credentials to external APIs. Always pass through `scrub_text()` or scan offline.
4. **Shell Hook Isolation**: Never use constructs in shell hooks that wrap user commands in subshells or break interactive curses/TTY applications.

## Conventional Commits

We follow Conventional Commits specification:
- `feat(...)`: New user-facing feature
- `fix(...)`: Bug fix
- `test(...)`: Adding or updating tests
- `docs(...)`: Documentation additions or changes
- `refactor(...)`: Code refactoring without behavior change

## Testing Requirements

Before submitting changes, ensure all tests pass:
```bash
pytest
```
All pull requests must maintain 100% test pass rate across unit and integration suites.
