from __future__ import annotations

import json
from pathlib import Path

from hl_observer.loops.candidate_factory import CandidateFactoryReport
from hl_observer.loops.input_diagnostics import build_loop_input_diagnostics, write_loop_input_diagnostics
from hl_observer.mainnet_readonly_observer.observer import MainnetObservation
from hl_observer.testnet.models import unix_ms


def _empty_report(source: str = "test") -> CandidateFactoryReport:
    now = unix_ms()
    return CandidateFactoryReport(
        source=source,
        generated_at_ms=now,
        observed_at_ms=now,
        candidates=[],
        skipped=[],
        methodology="test",
    )


def test_loop_input_diagnostics_explains_no_recent_position_deltas() -> None:
    observation = MainnetObservation(
        source="hyperliquid_mainnet_readonly",
        all_mids={"BTC": 60_000.0},
        l2_books={"BTC": {"levels": []}},
    )

    diagnostics = build_loop_input_diagnostics(
        observation=observation,
        fill_report=_empty_report("fills"),
        delta_report=_empty_report("position_deltas"),
        requested_wallets=[],
        requested_coins=["BTC"],
        recent_delta_window_seconds=300,
    )

    assert diagnostics["status"] == "NO_RECENT_POSITION_DELTAS"
    assert diagnostics["all_mids_count"] == 1
    assert diagnostics["candidate_count"] == 0
    assert diagnostics["recent_delta_window_seconds"] == 300
    assert diagnostics["next_actions"]


def test_loop_input_diagnostics_are_written_to_runtime_and_logs_to_send(tmp_path: Path) -> None:
    diagnostics = {"status": "READY_CANDIDATES", "candidate_count": 2}

    runtime_path, logs_path = write_loop_input_diagnostics(diagnostics, project_root=tmp_path)

    assert runtime_path == tmp_path / "runtime" / "learning" / "latest_loop_input_diagnostics.json"
    assert logs_path == tmp_path / "logs" / "logs à envoyer" / "latest_loop_input_diagnostics.json"
    assert json.loads(runtime_path.read_text(encoding="utf-8"))["candidate_count"] == 2
    assert json.loads(logs_path.read_text(encoding="utf-8"))["status"] == "READY_CANDIDATES"
