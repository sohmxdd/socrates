"""
tests/test_benchmark.py — Tests for benchmark data structures and runner.
"""
from scripts.benchmark import BenchmarkResult


def test_benchmark_result_fields() -> None:
    res = BenchmarkResult(
        duration_seconds=10.0,
        samples_count=10,
        min_cpu=0.0,
        max_cpu=2.5,
        avg_cpu=0.8,
        min_ram_mb=30.0,
        max_ram_mb=32.0,
        avg_ram_mb=31.0,
    )
    assert res.duration_seconds == 10.0
    assert res.avg_cpu == 0.8
    assert res.avg_ram_mb == 31.0
    assert res.max_cpu >= res.min_cpu
