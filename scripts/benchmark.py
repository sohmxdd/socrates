"""
scripts/benchmark.py — Automated performance and resource benchmarking tool for Socrates.

Measures idle CPU, wake spikes during periodic sweeps, and memory utilization (RSS).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
import time
from typing import NamedTuple

try:
    import psutil
except ImportError:
    print("psutil required for benchmark: pip install psutil")
    sys.exit(1)

from socrates.config import SocratesConfig, get_socrates_home
from socrates.daemon.server import SocratesDaemon


class BenchmarkResult(NamedTuple):
    duration_seconds: float
    samples_count: int
    min_cpu: float
    max_cpu: float
    avg_cpu: float
    min_ram_mb: float
    max_ram_mb: float
    avg_ram_mb: float


def run_benchmark(duration: int = 15, sweep_interval: int = 3) -> BenchmarkResult:
    """Run an automated benchmark of the Socrates daemon process."""
    config = SocratesConfig(
        sweep_interval_seconds=sweep_interval,
        stuck_sweep_interval_seconds=max(2, sweep_interval - 1),
        commentary_enabled=False,
    )
    home = get_socrates_home()
    daemon = SocratesDaemon(config=config, home=home)
    loop = asyncio.new_event_loop()

    def run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(daemon.start())
        loop.run_forever()

    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()

    time.sleep(0.8)
    process = psutil.Process(os.getpid())
    process.cpu_percent(interval=None)

    cpu_samples: list[float] = []
    ram_samples: list[float] = []

    start = time.time()
    while time.time() - start < duration:
        time.sleep(1.0)
        cpu = process.cpu_percent(interval=None)
        mem = process.memory_info().rss / (1024 * 1024)
        cpu_samples.append(cpu)
        ram_samples.append(mem)

    loop.call_soon_threadsafe(loop.stop)

    return BenchmarkResult(
        duration_seconds=time.time() - start,
        samples_count=len(cpu_samples),
        min_cpu=min(cpu_samples) if cpu_samples else 0.0,
        max_cpu=max(cpu_samples) if cpu_samples else 0.0,
        avg_cpu=sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0.0,
        min_ram_mb=min(ram_samples) if ram_samples else 0.0,
        max_ram_mb=max(ram_samples) if ram_samples else 0.0,
        avg_ram_mb=sum(ram_samples) / len(ram_samples) if ram_samples else 0.0,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Socrates performance benchmark")
    parser.add_argument("--duration", type=int, default=10, help="Test duration in seconds")
    parser.add_argument("--sweep-interval", type=int, default=3, help="Sweep interval in seconds")
    args = parser.parse_args()

    print(f"Running Socrates benchmark for {args.duration}s...")
    res = run_benchmark(duration=args.duration, sweep_interval=args.sweep_interval)
    print("\n--- BENCHMARK RESULTS ---")
    print(f"Duration:   {res.duration_seconds:.1f}s ({res.samples_count} samples)")
    print(f"CPU Avg:    {res.avg_cpu:.2f}% (Min: {res.min_cpu:.2f}%, Max: {res.max_cpu:.2f}%)")
    print(f"RAM Avg:    {res.avg_ram_mb:.2f} MB (Min: {res.min_ram_mb:.2f} MB, Max: {res.max_ram_mb:.2f} MB)")
