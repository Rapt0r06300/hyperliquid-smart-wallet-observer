from __future__ import annotations

from hl_observer.backtesting import lead_lag_multiasset_train as train_module
from hl_observer.backtesting.lead_lag_book_confirmation import (
    MECHANISM,
    book_confirmation_trial_count,
    confirm_shocks_with_causal_book,
)


def _book(
    ts_ms: int,
    *,
    bid_size: float,
    ask_size: float,
    source_id: str = "aligned-a.jsonl",
) -> dict:
    return {
        "ts_ms": ts_ms,
        "observable_at_ms": ts_ms,
        "bid": 99.9,
        "ask": 100.1,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "source_id": source_id,
    }


def _trade(ts_ms: int, source_id: str = "aligned-a.jsonl") -> dict:
    return {"observable_at_ms": ts_ms, "price": 100.0, "source_id": source_id}


def test_confirmation_uses_only_same_source_causal_fresh_book() -> None:
    shocks = [
        (1_000_000_000, 1.0),
        (2_000_000_000, -1.0),
        (3_000_000_000, 1.0),
        (4_000_000_000, 1.0),
    ]
    trades = [
        _trade(1_000),
        _trade(2_000),
        _trade(3_000),
        _trade(4_000, "aligned-b.jsonl"),
    ]
    books = [
        _book(990, bid_size=9.0, ask_size=1.0),
        _book(1_990, bid_size=1.0, ask_size=9.0),
        _book(2_990, bid_size=1.0, ask_size=9.0),
        _book(3_990, bid_size=9.0, ask_size=1.0, source_id="other.jsonl"),
    ]

    accepted, diagnostics = confirm_shocks_with_causal_book(
        shocks,
        books,
        trades,
        min_abs_imbalance=0.25,
        max_book_age_ms=100,
    )

    assert accepted == [(1_000_000_000, 1.0), (2_000_000_000, -1.0)]
    assert diagnostics["accepted"] == 2
    assert diagnostics["book_conflict"] == 1
    assert diagnostics["missing_same_source_book"] == 1
    assert diagnostics["selection_scope"] == "TRAIN_ONLY_PRE_FREEZE"
    assert diagnostics["heldout_loaded"] is False


def test_confirmation_never_uses_future_or_stale_book() -> None:
    shocks = [(1_000_000_000, 1.0), (2_000_000_000, 1.0)]
    trades = [_trade(1_000), _trade(2_000)]
    books = [
        _book(1_010, bid_size=9.0, ask_size=1.0),
        _book(1_500, bid_size=9.0, ask_size=1.0),
    ]

    accepted, diagnostics = confirm_shocks_with_causal_book(
        shocks,
        books,
        trades,
        min_abs_imbalance=0.25,
        max_book_age_ms=100,
    )

    assert accepted == []
    assert diagnostics["missing_same_source_book"] == 1
    assert diagnostics["stale_book"] == 1


def test_confirmation_trial_count_is_frozen_before_replay() -> None:
    assert book_confirmation_trial_count(11) == 396
    assert book_confirmation_trial_count(0) == 0


def test_book_confirmation_family_is_wired_and_counted_before_replay(
    tmp_path, monkeypatch
) -> None:
    trigger_ns = 1_800_000_000_000_000_000
    tape = {
        "SOL": {
            "TRADE": [(trigger_ns, 100.0, 1.0)],
            "TRADE_OBS": [
                {
                    "observable_at_ms": 1_800_000_000_000,
                    "price": 100.0,
                    "source_id": "aligned.jsonl",
                }
            ],
            "HL_BOOK": [
                {
                    **_book(
                        1_799_999_999_990,
                        bid_size=9.0,
                        ask_size=1.0,
                        source_id="aligned.jsonl",
                    ),
                    "coin": "SOL",
                    "bid_top_usd": 899.1,
                    "ask_top_usd": 100.1,
                }
            ],
            "TRADE_SOURCE_IDS": ["aligned.jsonl"],
            "HL_BOOK_SOURCE_IDS": ["aligned.jsonl"],
        }
    }
    monkeypatch.setattr(
        train_module,
        "load_multiasset_train_tape",
        lambda *_args, **_kwargs: (tape, {"heldout_loaded": False}),
    )
    monkeypatch.setattr(train_module, "TRAIN_HYPOTHESES", ())
    monkeypatch.setattr(train_module, "CROSS_ASSET_LEADERS", ())
    monkeypatch.setattr(train_module, "CROSS_ASSET_FOLLOWERS", ())
    monkeypatch.setattr(
        train_module,
        "load_runtime_latency_evidence",
        lambda _root: {"measured": True, "p95_ms": 1.0},
    )
    monkeypatch.setattr(
        train_module.lead_lag_shadow,
        "detecter_chocs_fenetre",
        lambda *_args, **_kwargs: [(trigger_ns, 1.0)],
    )
    replayed = []

    def replay(*_args, **kwargs):
        replayed.append(kwargs["precomputed_shocks"])
        return {
            "costs_measured": True,
            "segments": {label: {"net": 0.0} for label in ("IS", "OOS", "FORWARD")},
            "ledgers": {label: [] for label in ("IS", "OOS", "FORWARD")},
            "placebo_net": 0.0,
            "coverage": {},
            "signals": 0,
            "decision_counts": {},
            "raw_observation_diagnostics": {},
            "raw_direction_flip_diagnostics": {},
        }

    monkeypatch.setattr(train_module, "replay_measured_lead_lag", replay)

    report = train_module.explore_lead_lag_multiasset_train(
        tmp_path, [], candidate_coins=("SOL",)
    )

    assert report["fixed_grid"]["trial_count"] == 37
    assert report["fixed_grid"]["book_confirmation_hypothesis"]["trial_count"] == 36
    assert len(report["variants"]) == 36
    assert {row["mechanism"] for row in report["variants"]} == {MECHANISM}
    assert {row["book_imbalance_threshold"] for row in report["variants"]} == {
        0.15,
        0.35,
    }
    assert all(value == {"SOL": [(trigger_ns, 1.0)]} for value in replayed)
