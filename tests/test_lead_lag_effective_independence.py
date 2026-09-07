from __future__ import annotations

from hl_observer.backtesting import lead_lag_multiasset_train as module


def test_score_report_ne_compte_que_les_episodes_temporels_independants(monkeypatch) -> None:
    base = 1_800_000_000_000
    timestamps = [
        base,
        base + 100,
        base + 200,
        base + 86_400_000,
        base + 86_400_100,
        base + 86_400_200,
        base + 2 * 86_400_000,
        base + 2 * 86_400_100,
    ]
    labels = ("IS", "IS", "IS", "OOS", "OOS", "OOS", "FORWARD", "FORWARD")
    ledgers = {label: [] for label in ("IS", "OOS", "FORWARD")}
    for index, (timestamp_ms, label) in enumerate(zip(timestamps, labels, strict=True)):
        trade_id = f"clustered-{index}"
        ledgers[label].append(
            {"evt": "SIGNAL", "trade_id": trade_id, "ts": timestamp_ms, "coin": "ETH"}
        )
        ledgers[label].append(
            {
                "evt": "PNL",
                "trade_id": trade_id,
                "LIQUIDATABLE_NET": True,
                "pnl_usd": 1.0,
            }
        )

    rows_seen: list[dict] = []

    def fake_summary(rows, **_kwargs):
        rows_seen.extend(rows)
        return {
            "sample_count": len(rows),
            "distinct_days": len({int(row["timestamp_ms"]) // 86_400_000 for row in rows}),
            "net_pnl_usd": float(len(rows)),
            "profit_factor": 2.0,
            "total_lcb_usd": 1.0,
            "top_positive_trade_share": 0.25,
        }

    monkeypatch.setattr(module, "summarize_train_rows", fake_summary)
    report = {
        "costs_measured": True,
        "segments": {label: {"net": 1.0} for label in ("IS", "OOS", "FORWARD")},
        "ledgers": ledgers,
        "placebo_net": -1.0,
        "coverage": {},
        "signals": len(timestamps),
        "decision_counts": {},
        "raw_observation_diagnostics": {},
        "raw_direction_flip_diagnostics": {},
    }

    scored = module._score_report(
        report,
        coin="ETH",
        threshold_bps=12.0,
        horizon_ms=1_000,
        trial_count=1,
        min_train_fills=8,
    )

    assert [row["timestamp_ms"] for row in rows_seen] == [
        base,
        base + 86_400_000,
        base + 2 * 86_400_000,
    ]
    assert scored["independence"] == {
        "raw_sample_count": 8,
        "effective_sample_count": 3,
        "overlapping_events_rejected": 5,
        "minimum_separation_ms": 1_000,
        "effective_distinct_days": 3,
    }
    assert scored["statistics"]["sample_count"] == 3
    assert scored["eligible"] is False
