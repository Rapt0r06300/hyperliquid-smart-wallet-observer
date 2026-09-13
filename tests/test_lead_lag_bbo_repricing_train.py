from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting import lead_lag_bbo_repricing_train as module


def _bbo(
    ts_ms: int,
    *,
    bid: float,
    ask: float,
    bid_size: float = 1.0,
    ask_size: float = 1.0,
    source_id: str = "same.jsonl",
) -> dict[str, object]:
    return {
        "ts_ms": ts_ms,
        "bid": bid,
        "ask": ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "source_id": source_id,
    }


def test_detect_bbo_repricing_is_causal_and_ignores_future_rows() -> None:
    rows = [
        _bbo(1_000, bid=99.99, ask=100.01),
        _bbo(1_100, bid=100.01, ask=100.03),
        _bbo(1_200, bid=109.99, ask=110.01),
    ]

    first, diagnostics = module.detect_bbo_repricing_shocks(
        rows[:2], representation="mid", window_ms=100, threshold_bps=1.0
    )
    with_future, _ = module.detect_bbo_repricing_shocks(
        rows, representation="mid", window_ms=100, threshold_bps=1.0
    )

    assert first == [(1_100_000_000, 1.0)]
    assert with_future[0] == first[0]
    assert diagnostics["causal_evaluations"] == 1
    assert diagnostics["signals"] == 1
    assert diagnostics["heldout_loaded"] is False
    assert diagnostics["real_execution"] is False


def test_detect_bbo_repricing_microprice_uses_only_visible_top_sizes() -> None:
    rows = [
        _bbo(1_000, bid=99.0, ask=101.0, bid_size=1.0, ask_size=1.0),
        _bbo(1_100, bid=99.0, ask=101.0, bid_size=3.0, ask_size=1.0),
    ]

    shocks, diagnostics = module.detect_bbo_repricing_shocks(
        rows, representation="microprice", window_ms=100, threshold_bps=40.0
    )

    assert shocks == [(1_100_000_000, 1.0)]
    assert diagnostics["invalid_rows"] == 0


def test_load_bbo_train_tape_keeps_only_frozen_train_and_common_source(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "bbo_tape_1800000002000000000.jsonl"
    rows = [
        {
            "venue": "BIN",
            "coin": "ETH",
            "ts_wall_ms": 1_800_000_001_000,
            "bid": 99.0,
            "ask": 101.0,
            "event_id": "bin-train",
        },
        {
            "venue": "HL",
            "coin": "ETH",
            "ts_wall_ms": 1_800_000_001_001,
            "bid": 99.5,
            "ask": 100.5,
            "bid_sz": 4.0,
            "ask_sz": 2.0,
            "event_id": "hl-train",
        },
        {
            "venue": "BIN",
            "coin": "ETH",
            "ts_wall_ms": 1_800_000_001_050,
            "bid": 99.0,
            "ask": 101.0,
            "event_id": "bin-unchanged",
        },
        {
            "venue": "BIN",
            "coin": "ETH",
            "ts_wall_ms": 1_800_000_001_501,
            "bid": 100.0,
            "ask": 102.0,
            "event_id": "bin-heldout",
        },
    ]
    source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    monkeypatch.setattr(
        module,
        "_source_training_ranges",
        lambda *_args, **_kwargs: (
            [(1_800_000_000_000, 1_800_000_001_200)],
            {"train_end_ms": 1_800_000_001_200, "heldout_start_ms": 1_800_000_001_201},
        ),
    )

    tape, meta = module.load_bbo_train_tape(tmp_path, [source], coins=("ETH",))

    assert len(tape["ETH"]["BIN_BBO"]) == 1
    assert len(tape["ETH"]["HL_BOOK"]) == 1
    assert tape["ETH"]["BIN_SOURCE_IDS"] == tape["ETH"]["HL_BOOK_SOURCE_IDS"]
    assert meta["binance_unchanged_updates_collapsed"] == 1
    assert meta["rows_outside_frozen_train"] == 1
    assert meta["heldout_loaded"] is False
    assert meta["real_execution"] is False


def test_fixed_grid_trial_count_is_predeclared() -> None:
    expected = (
        len(module.CANDIDATE_COINS)
        * len(module.REPRESENTATIONS)
        * len(module.SHOCK_WINDOWS_MS)
        * len(module.SHOCK_THRESHOLDS_BPS)
        * len(module.HORIZONS_MS)
    )

    assert expected == 162
    assert expected == module.NEW_TRIAL_COUNT
    assert module.BONFERRONI_TRIAL_COUNT == 3_096
