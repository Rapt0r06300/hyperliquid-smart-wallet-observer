from __future__ import annotations

import subprocess
import sys

from hyper_smart_observer.scale.scale_benchmark import run_scale_benchmark


def test_scale_benchmark_14000_wallets_is_local() -> None:
    result = run_scale_benchmark(wallets=14_000, events=50_000)

    assert result.wallets_requested == 14_000
    assert result.events_requested == 50_000
    assert result.wallets_aggregated == 14_000
    assert result.events_processed == 50_000
    assert result.network_used is False


def test_scale_benchmark_cli_is_available() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "hyper_smart_observer.app.main",
            "scale-benchmark",
            "--wallets",
            "14000",
            "--events",
            "50000",
        ],
        cwd="C:\\Users\\flo\\Desktop\\Projet invest",
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "wallets_requested=14000" in completed.stdout
    assert "network_used=false" in completed.stdout
    assert "scope=synthetic_local_scale" in completed.stdout
