# Socrates Security & Privacy Model

Socrates is designed with a zero-trust model toward external network transmission.

## Security Architecture

```
User Terminal Command
         │
         ▼
[Offline Secret Scanner] ────────── If Secret Detected ──────────► [Local Cyan Alert]
         │ (clean or scrubbed)                                     (Zero Network)
         ▼
[Deterministic Rules]
         │
         ▼ (LOW_CONFIDENCE tiebreak only)
[Scrubbing Layer: scrub_text()]
         │ Replaces all secrets with [REDACTED:<type>]
         ▼
[Groq LLM Tiebreaker]
```

## Privacy Guarantees

1. **Local-First Secret Scanning**:
   - All shell commands are analyzed in-process on your CPU using compiled regular expressions and Shannon entropy calculation.
   - Any command containing credentials triggers an immediate offline alert and **never** makes an outbound network request.

2. **Pre-Transmission Secret Redaction**:
   - For ambiguous events where the deterministic engine requests an LLM tiebreak (e.g. exit 0 with suspicious stderr keywords), the payload is scrubbed by `scrub_text()` before serializing JSON to Groq.
   - Any secret-shaped token in `command`, `stderr_excerpt`, or error context is redacted as `[REDACTED:<type>]`.

3. **No Codebase Scanning or Telemetry**:
   - Socrates does not read repository source code, ASTs, or git diffs beyond commit hashes and commit author timestamps.
   - Socrates contains no telemetry, analytics tracking, or external crash reporting.
