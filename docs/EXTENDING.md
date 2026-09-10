# Extending Socrates

You can extend Socrates with new rule engines, custom prompt formatters, and external notification targets.

## Authoring a Custom Rule

Every Socrates rule is an isolated module that evaluates an event and returns a `RuleResult`.

```python
from socrates.rules.base import Confidence, RuleResult, RuleType, EventData

def check_custom_rule(event: EventData) -> RuleResult:
    # 1. Inspect event facts
    command = event.command
    exit_code = event.exit_code

    # 2. Evaluate condition
    if "dangerous_operation" in command and exit_code == 0:
        return RuleResult(
            rule_type=RuleType.SILENT_FAILURE,
            confidence=Confidence.HIGH_CONFIDENCE,
            facts={
                "command": command,
                "reason": "Dangerous operation completed without confirmation",
            },
            fingerprint_key=f"custom:{command}",
        )

    # 3. Default: return NONE to stay silent
    return RuleResult(RuleType.SILENT_FAILURE, Confidence.NONE)
```

## Adding a Custom Secret Pattern

To register a custom internal API token pattern, add your regex to `socrates/rules/leaked_secrets.py`:

```python
SECRET_PATTERNS.append((
    "Internal Corporate Token",
    re.compile(r"corp_[0-9a-zA-Z]{32}"),
))
```
Any matches will automatically be redacted before reaching tiebreaking models and flagged offline.
