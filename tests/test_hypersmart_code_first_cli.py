from __future__ import annotations

import subprocess
import sys


def run_cli(*args: str):
    return subprocess.run(
        [sys.executable, "-m", "hyper_smart_observer.app.main", *args],
        cwd="C:\\Users\\flo\\Desktop\\Projet invest",
        text=True,
        capture_output=True,
        check=False,
    )


def test_simulate_magic_bot_cli_reports_no_money_no_order() -> None:
    completed = run_cli("simulate-magic-bot", "--capital", "1000", "--scenario", "conservative")

    assert completed.returncode == 0, completed.stderr
    assert "simulate_magic_bot=local_no_money" in completed.stdout
    assert "starting_equity=1000.00" in completed.stdout
    assert "current_equity=1000.000000" in completed.stdout
    assert "fills=0" in completed.stdout
    assert "execution=forbidden" in completed.stdout


def test_scan_local_and_universe_cli() -> None:
    local = run_cli("scan-local", "--limit", "25")
    universe = run_cli("scan-universe", "--source", "imports", "--limit", "25")

    assert local.returncode == 0, local.stderr
    assert "scan_local=research_only_no_network" in local.stdout
    assert "wallets_scanned=25" in local.stdout
    assert universe.returncode == 0, universe.stderr
    assert "scan_universe=local_only" in universe.stdout
    assert "imported=25" in universe.stdout


def test_hot_watch_requires_network_read_duration_and_dry_run() -> None:
    no_network = run_cli("hot-watch", "--duration-seconds", "60", "--dry-run")
    assert no_network.returncode == 2
    assert "NETWORK_READ_DISABLED" in no_network.stdout

    no_duration = run_cli("hot-watch", "--network-read", "--dry-run")
    assert no_duration.returncode == 2
    assert "WEBSOCKET_DURATION_REQUIRED" in no_duration.stdout

    ok = run_cli("hot-watch", "--network-read", "--duration-seconds", "60", "--dry-run")
    assert ok.returncode == 0, ok.stderr
    assert "hot_watch=read_only_dry_run" in ok.stdout
    assert "slots=10" in ok.stdout


def test_consensus_opportunity_and_missed_reports_cli() -> None:
    consensus = run_cli("consensus-report", "--period", "1h")
    opportunity = run_cli("opportunity-report", "--period", "1h")
    missed = run_cli("missed-opportunities", "--period", "24h")

    assert consensus.returncode == 0, consensus.stderr
    assert "consensus_report_period=1h" in consensus.stdout
    assert opportunity.returncode == 0, opportunity.stderr
    assert "opportunity_report_period=1h" in opportunity.stdout
    assert "edge_remaining_bps" in opportunity.stdout
    assert missed.returncode == 0, missed.stderr
    assert "missed_opportunities_period=24h" in missed.stdout
