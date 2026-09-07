from __future__ import annotations

from hl_observer.backtesting import lead_lag_multiasset_train as module


def _positive_report() -> dict:
    return {
        "costs_measured": True,
        "segments": {label: {"net": 1.0} for label in ("IS", "OOS", "FORWARD")},
        "placebo_net": -1.0,
        "coverage": {},
        "signals": 30,
        "decision_counts": {},
        "raw_observation_diagnostics": {},
        "raw_direction_flip_diagnostics": {},
    }


def test_diagnostic_8bps_reste_ineligible_sans_nouvelle_predeclaration_train(monkeypatch) -> None:
    monkeypatch.setattr(module, "_rows_from_ledgers", lambda _report: [])
    monkeypatch.setattr(
        module,
        "_independent_train_rows",
        lambda _rows, **_kwargs: (
            [],
            {
                "raw_sample_count": 30,
                "effective_sample_count": 30,
                "overlapping_events_rejected": 0,
                "minimum_separation_ms": 1_000,
                "effective_distinct_days": 3,
            },
        ),
    )
    monkeypatch.setattr(
        module,
        "summarize_train_rows",
        lambda *_args, **_kwargs: {
            "net_pnl_usd": 3.0,
            "profit_factor": 2.0,
            "total_lcb_usd": 1.0,
            "sample_count": 30,
            "distinct_days": 3,
            "top_positive_trade_share": 0.2,
        },
    )

    blocked = module._score_report(
        _positive_report(),
        coin="BTC",
        threshold_bps=8.0,
        horizon_ms=1_000,
        trial_count=1,
        min_train_fills=30,
    )
    assert blocked["threshold_role"] == "DIAGNOSTIC_ONLY"
    assert blocked["economic_threshold_allowed"] is False
    assert blocked["economic_predeclaration_id"] is None
    assert blocked["eligible"] is False

    regular = module._score_report(
        _positive_report(),
        coin="BTC",
        threshold_bps=12.0,
        horizon_ms=1_000,
        trial_count=1,
        min_train_fills=30,
    )
    assert regular["threshold_role"] == "TRAIN_ECONOMIC_PREDECLARED"
    assert regular["economic_threshold_allowed"] is True
    assert regular["eligible"] is True

    redeclared = module._score_report(
        _positive_report(),
        coin="BTC",
        threshold_bps=8.0,
        horizon_ms=1_000,
        trial_count=1,
        min_train_fills=30,
        economic_predeclaration_id="train-only:hypothesis:8bps-v2",
    )
    assert redeclared["threshold_role"] == "TRAIN_ECONOMIC_PREDECLARED"
    assert redeclared["economic_threshold_allowed"] is True
    assert redeclared["economic_predeclaration_id"] == "train-only:hypothesis:8bps-v2"
    assert redeclared["eligible"] is True
