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
