# Socrates Performance Benchmarks

Socrates is built to run continuously in developer environments without perceptible resource overhead.

## Resource Consumption

All benchmarks were measured on a modern workstation using `psutil` sampling process memory (Resident Set Size) and CPU utilization.

### 1. Idle Footprint (Between Commands)

| Metric | Measured Value | Target SLA |
| :--- | :--- | :--- |
| **Idle CPU Utilization** | **`0.00%`** | `< 0.5%` |
| **Memory Footprint (RSS)** | **`30.35 MB`** | `< 50 MB` |
| **Event Ingestion Latency** | **`< 2.1 ms`** | `< 10 ms` |

The daemon uses `asyncio` loopback socket listeners that sleep until wake signals arrive from shell hooks.

### 2. Multi-Sweep Execution (Periodic Wake Load)

Measured over a continuous 60-second window with accelerated 3-5 second sweeps forcing $\ge 12$ repo and process wake cycles:

| Metric | Measured Value |
| :--- | :--- |
| **Min CPU Utilization** | `0.00%` |
| **Max CPU Spike (Sweep Peak)**| `3.10%` |
| **Average CPU Utilization** | **`0.92%`** |
| **RAM (RSS) Min / Max** | `30.37 MB` / `31.20 MB` |
| **Average RAM (RSS)** | **`31.14 MB`** |

### 3. Rule Execution Latencies

| Rule Engine Path | Latency | Network Access |
| :--- | :--- | :--- |
| **Leaked Secrets Scan** | `< 0.8 ms` | None (Deterministic) |
| **Silent Failure (Regex/Tail)**| `< 1.2 ms` | None (Deterministic) |
| **Stuck Process (In-Flight)** | `< 0.5 ms` | None (Deterministic) |
| **Forgotten Push (Git check)** | `< 8.4 ms` | Local `git rev-list` only |
| **Groq Tiebreak (Fallback)** | `350 - 650 ms` | Outbound TLS to Groq API |
