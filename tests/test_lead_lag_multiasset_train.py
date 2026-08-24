from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting import lead_lag_multiasset_train as module
from hl_observer.backtesting.lead_lag_source_alignment import SourceWindow


def test_multiasset_loader_coupe_le_heldout_avant_de_lire_les_resultats(
    tmp_path: Path, monkeypatch
) -> None:
    start = 1_800_000_000_000
    end = start + 10_000
    dummy_market = tmp_path / "market.jsonl.gz"
    monkeypatch.setattr(
        module,
        "discover_market_tick_windows",
        lambda _root: [SourceWindow(dummy_market, start, end)],
    )
    source = tmp_path / "bbo.jsonl"
    rows = [
        {
            "venue": "BIN_TRADE",
            "coin": "ETH",
            "px": 100.0,
            "side": "BUY",
            "sz": "1",
            "event_id": "train",
            "ts_wall_ms": start + 1_000,
        },
        {
            "venue": "BIN_TRADE",
            "coin": "ETH",
            "px": 101.0,
            "side": "BUY",
            "sz": "1",
            "event_id": "heldout",
            "ts_wall_ms": start + 7_000,
        },
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    tape, meta = module.load_multiasset_train_tape(
        tmp_path,
        [source],
        coins=("ETH",),
    )

    assert len(tape["ETH"]["TRADE"]) == 1
    assert tape["ETH"]["TRADE"][0][1] == 100.0
    assert meta["train_end_ms"] == start + 6_000
    assert meta["heldout_start_ms"] == start + 6_001
    assert meta["rows_outside_frozen_train"] == 1
    assert meta["heldout_loaded"] is False
    assert meta["real_execution"] is False


def test_score_report_expose_le_diagnostic_brut_sans_le_rendre_eligible() -> None:
    diagnostics = {
        "diagnostic_only": True,
        "selection_eligible": False,
        "net_pnl_usd_if_all_executable_taken": 42.0,
    }
    report = {
        "costs_measured": True,
        "segments": {
            label: {"net": 0.0}
            for label in ("IS", "OOS", "FORWARD")
        },
        "ledgers": {
            label: []
            for label in ("IS", "OOS", "FORWARD")
        },
        "placebo_net": 0.0,
        "coverage": {"observable": 6},
        "signals": 6,
        "decision_counts": {"INSUFFICIENT_PRIOR_HISTORY": 6},
        "raw_observation_diagnostics": diagnostics,
    }

    scored = module._score_report(
        report,
        coin="ETH",
        threshold_bps=8.0,
        horizon_ms=1_000,
        trial_count=1,
    )

    assert scored["raw_observation_diagnostics"] == diagnostics
    assert scored["decision_counts"] == {"INSUFFICIENT_PRIOR_HISTORY": 6}
    assert scored["eligible"] is False
