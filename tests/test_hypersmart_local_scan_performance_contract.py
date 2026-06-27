from __future__ import annotations

import subprocess
import sys

from hyper_smart_observer.local_index.index_benchmark import run_local_scan_benchmark


def test_local_scan_benchmark_contract_has_no_network() -> None:
    result = run_local_scan_benchmark(2_000)

    assert result.wallets_requested == 2_000
    assert result.wallets_scanned == 2_000
    assert result.network_used is False
    assert result.target_wallets_per_second == 2_000
    assert result.wallets_per_second > 0


def test_local_scan_cli_command() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "hyper_smart_observer.app.main", "benchmark-local-scan", "--wallets", "2000"],
        cwd="C:\\Users\\flo\\Desktop\\Projet invest",
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "wallets_scanned=2000" in completed.stdout
    assert "network_used=false" in completed.stdout
    assert "scope=local_index_only" in completed.stdout
