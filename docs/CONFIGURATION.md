# Socrates Configuration Guide

Socrates uses a hierarchical configuration cascade. Settings defined closer to the working directory override higher-level defaults.

## Configuration Precedence

1. **Project Local Config**: `.socrates.yaml` or `.socrates.yml` in the current working directory or any ancestor folder.
2. **User Global Config**: `~/.socrates/config.yaml`.
3. **Default Config**: Shipped package defaults in `config/default_config.yaml`.

---

## Configuration Keys Reference

### Detection & Sweeps
```yaml
# How often to check known repos for forgotten unpushed commits (seconds)
sweep_interval_seconds: 600

# How often to check in-flight processes against runtime baselines (seconds)
stuck_sweep_interval_seconds: 30

# Minimum historical command executions required before flagging anomalies
min_baseline_samples: 5

# Stddev multiplier for stuck-process thresholds (k-factor)
baseline_k_factor: 2.0

# Inactivity window: if commits occurred within N seconds, suppress reminders
active_commit_window_seconds: 300

# Number of dismissals before indefinitely suppressing an issue fingerprint
dismiss_threshold: 3

# Cooldown between identical interventions (seconds)
intervention_cooldown_seconds: 3600

# Widening factor applied to cooldowns upon dismissal
dismiss_widening_factor: 1.5
```

### Ambient Commentary (Opt-in)
```yaml
# Master toggle for ambient prompt observations
commentary_enabled: false

# Frequency of commentary when enabled (0.0 to 1.0)
commentary_rate: 0.6

# Minimum cooldown between ambient observations per shell session (seconds)
commentary_cooldown_seconds: 15

# Commands excluded from commentary
commentary_skip_commands:
  - "clear"
  - "cls"
  - "pwd"
  - "exit"
```

### Presentation & Sound
```yaml
# ANSI colors enabled in terminal output
color_enabled: true

# Clean factual messages without Socratic philosophical persona
quiet_mode: false

# Non-verbal audio chime on intervention
sound_enabled: false
sound_file_path: ""
sound_volume: 1.0
```
