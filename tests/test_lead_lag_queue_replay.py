from __future__ import annotations

import pytest

from hl_observer.backtesting import lead_lag_queue_replay as replay_module
from hl_observer.backtesting.lead_lag_queue_replay import (
    detect_rolling_shocks,
    replay_lead_lag_queue_maker,
)


def _book(
    ts_ms: int,
    *,
    bid: float,
    ask: float,
    ready: bool = True,
) -> dict[str, object]:
    return {
        "coin": "ETH",
        "ts_ms": ts_ms,
        "exchange_ts_ms": ts_ms - 5,
        "bid": bid,
        "ask": ask,
        "bid_size": 1.0,
        "ask_size": 1.0,
        "bid_top_usd": bid * 10.0,
        "ask_top_usd": ask * 10.0,
        "data_gate_ready": ready,
        "real_execution": False,
    }


def _trade(
    ts_ms: int,
    *,
    side: str,
    price: float,
    size: float,
    ready: bool = True,
) -> dict[str, object]:
    return {
        "coin": "ETH",
        "ts_ms": ts_ms,
        "exchange_ts_ms": ts_ms - 5,
        "side": side,
        "px": price,
        "sz": size,
        "data_gate_ready": ready,
        "real_execution": False,
    }


def _positive_scenario(*, count: int = 1, ready: bool = True):
    lead_trades: list[tuple[int, float, int]] = []
    books: list[dict[str, object]] = []
    trades: list[dict[str, object]] = []
    for index in range(count):
        base_ms = 10_000 * index + 1_000
        trigger_ms = base_ms + 1_000
        lead_trades.extend(
            [
                (base_ms * 1_000_000, 100.0, 1),
                (trigger_ms * 1_000_000, 100.25, 1),
            ]
        )
        entry_ms = trigger_ms + 100
        books.extend(
            [
                _book(entry_ms, bid=2_000.0, ask=2_001.0, ready=ready),
                # This book is before fill + hold and must never be used to exit.
                _book(entry_ms + 1_000, bid=2_100.0, ask=2_101.0, ready=ready),
                _book(entry_ms + 5_200, bid=2_010.0, ask=2_011.0, ready=ready),
            ]
        )
        trades.extend(
            [
                _trade(entry_ms + 20, side="B", price=2_000.0, size=5.0, ready=ready),
                _trade(entry_ms + 30, side="A", price=2_001.0, size=5.0, ready=ready),
                _trade(entry_ms + 40, side="A", price=2_000.0, size=1.0, ready=ready),
                _trade(entry_ms + 200, side="A", price=2_000.0, size=0.0125, ready=ready),
            ]
        )
    return (
        {"ETH": {"TRADE": lead_trades}},
        {"ETH": books},
        {"ETH": trades},
    )


def test_detect_rolling_shocks_is_causal_and_predeclared() -> None:
    shocks = detect_rolling_shocks(
        [
            (1_000_000_000, 100.0, 1),
            (1_500_000_000, 100.10, 1),
            (2_000_000_000, 100.25, 1),
        ]
    )

    assert len(shocks) == 1
    assert shocks[0]["trigger_ts_ms"] == 2_000
    assert shocks[0]["direction"] == 1
    assert shocks[0]["lead_shock_bps"] == pytest.approx(25.0)


def test_queue_replay_requires_ahead_plus_complete_own_order() -> None:
    tape, books, trades = _positive_scenario()
    trades["ETH"] = trades["ETH"][:-1]

    report = replay_lead_lag_queue_maker(
        tape,
        books,
        trades,
        latency_evidence={"measured": True, "p95_ms": 100.0},
    )

    assert report["maker_queue_candidates"] == []
    assert report["diagnostics"]["QUEUE_NOT_FULLY_CONSUMED"] == 1


def test_queue_replay_uses_only_correct_aggressor_side_and_exact_price() -> None:
    tape, books, trades = _positive_scenario()

    report = replay_lead_lag_queue_maker(
        tape,
        books,
        trades,
        latency_evidence={"measured": True, "p95_ms": 100.0},
    )

    row = report["maker_queue_candidates"][0]
    assert row["initial_qty_ahead"] == pytest.approx(1.0)
    assert row["paper_order_qty"] == pytest.approx(0.0125)
    assert row["queue_traded_qty"] == pytest.approx(1.0125)
    assert len(row["queue_events"]) == 2
    assert row["full_fill"] is True


def test_queue_replay_uses_the_fresh_book_known_at_order_decision_time() -> None:
    tape, books, trades = _positive_scenario()
    books["ETH"][0]["ts_ms"] = 2_050
    books["ETH"][0]["exchange_ts_ms"] = 2_045

    report = replay_lead_lag_queue_maker(
        tape,
        books,
        trades,
        latency_evidence={"measured": True, "p95_ms": 100.0},
    )

    row = report["maker_queue_candidates"][0]
    assert row["entry_book_ts_ms"] == 2_050
    assert row["entry_ts_ms"] == 2_100
    assert row["entry_decision_policy"] == "LATEST_KNOWN_FRESH_BOOK_AT_DECISION"


def test_queue_replay_accounts_exact_fees_and_causal_exit() -> None:
    tape, books, trades = _positive_scenario()

    report = replay_lead_lag_queue_maker(
        tape,
        books,
        trades,
        latency_evidence={"measured": True, "p95_ms": 100.0},
    )

    row = report["maker_queue_candidates"][0]
    assert row["entry_price"] == pytest.approx(2_000.0)
    assert row["exit_price"] == pytest.approx(2_010.0)
    assert row["exit_ts_ms"] == 7_300
    assert row["gross_pnl_usd"] == pytest.approx(0.13125)
    assert row["spread_cost_usd"] == pytest.approx(0.00625)
    assert row["fees_usd"] == pytest.approx(0.01505625)
    assert row["net_pnl_usd"] == pytest.approx(0.10994375)
    assert row["economic_reconciliation_ok"] is True
    assert row["LIQUIDATABLE_NET"] is True


@pytest.mark.parametrize(
    ("latency_evidence", "ready"),
    [
        ({"measured": False, "p95_ms": 100.0}, True),
        ({"measured": True, "p95_ms": 100.0}, False),
    ],
)
def test_queue_replay_fails_closed_without_latency_or_quality(
    latency_evidence: dict[str, object], ready: bool
) -> None:
    tape, books, trades = _positive_scenario(ready=ready)

    report = replay_lead_lag_queue_maker(
        tape,
        books,
        trades,
        latency_evidence=latency_evidence,
    )

    row = report["maker_queue_candidates"][0]
    assert row["closed_position"] is True
    assert row["LIQUIDATABLE_NET"] is False


def test_segments_are_frozen_on_shocks_before_fill_outcome() -> None:
    tape, books, trades = _positive_scenario(count=5)

    report = replay_lead_lag_queue_maker(
        tape,
        books,
        trades,
        latency_evidence={"measured": True, "p95_ms": 100.0},
    )

    rows = report["maker_queue_candidates"]
    assert [row["walk_forward_segment"] for row in rows] == [
        "train",
        "train",
        "train",
        "validation",
        "oos",
    ]
    assert report["segment_summaries"]["train"]["sample_count"] == 3
    assert report["segment_summaries"]["validation"]["sample_count"] == 1
    assert report["segment_summaries"]["oos"]["sample_count"] == 1
    assert report["forward_status"] == "NOT_STARTED_POST_FREEZE"
    assert report["real_execution"] is False


def test_explicit_time_segments_do_not_move_when_future_shocks_are_appended() -> None:
    initial_tape, initial_books, initial_trades = _positive_scenario(count=5)
    grown_tape, grown_books, grown_trades = _positive_scenario(count=7)
    bounds = {
        "train": (0, 15_000),
        "validation": (None, None),
        "oos": (40_000, 49_999),
        "forward": (None, None),
    }

    initial = replay_lead_lag_queue_maker(
        initial_tape,
        initial_books,
        initial_trades,
        latency_evidence={"measured": True, "p95_ms": 100.0},
        segment_bounds=bounds,
    )
    grown = replay_lead_lag_queue_maker(
        grown_tape,
        grown_books,
        grown_trades,
        latency_evidence={"measured": True, "p95_ms": 100.0},
        segment_bounds=bounds,
    )

    initial_segments = {
        row["trade_id"]: row["walk_forward_segment"]
        for row in initial["maker_queue_candidates"]
    }
    grown_segments = {
        row["trade_id"]: row["walk_forward_segment"]
        for row in grown["maker_queue_candidates"]
        if row["trade_id"] in initial_segments
    }
    assert initial_segments == grown_segments


def _shift_scenario(delta_ms: int):
    tape, books, trades = _positive_scenario()
    tape["ETH"]["TRADE"] = [
        (timestamp_ns + delta_ms * 1_000_000, price, direction)
        for timestamp_ns, price, direction in tape["ETH"]["TRADE"]
    ]
    for row in [*books["ETH"], *trades["ETH"]]:
        row["ts_ms"] = int(row["ts_ms"]) + delta_ms
        row["exchange_ts_ms"] = int(row["exchange_ts_ms"]) + delta_ms
    return tape, books, trades


def test_frozen_maker_uses_first_two_complete_post_freeze_days() -> None:
    day_ms = 86_400_000
    first = _shift_scenario(11 * day_ms)
    second = _shift_scenario(12 * day_ms)
    tape = {"ETH": {"TRADE": [*first[0]["ETH"]["TRADE"], *second[0]["ETH"]["TRADE"]]}}
    books = {"ETH": [*first[1]["ETH"], *second[1]["ETH"]]}
    trades = {"ETH": [*first[2]["ETH"], *second[2]["ETH"]]}
    frozen = {
        **replay_module.maker_protocol_signature(),
        "selection_cutoff_ms": 10 * day_ms,
        "train_ranges": [[1, 10 * day_ms]],
        "applied_latency_ms": 100.0,
        "latency_evidence_sha256": "a" * 64,
        "training_selection_evidence_sha256": "b" * 64,
        "training_selection_eligible": True,
    }

    report = replay_module.evaluate_frozen_maker(
        tape,
        books,
        trades,
        frozen_parameters=frozen,
        frozen_at_ms=10 * day_ms + 1,
        evaluated_at_ms=13 * day_ms + 1,
    )

    assert report["proof_window"]["complete_days_available"] == 2
    assert report["temporal_evidence"]["oos"]["sample_count"] == 1
    assert report["temporal_evidence"]["oos"]["no_lookahead"] is True
    assert report["temporal_evidence"]["forward"]["sample_count"] == 1
    assert report["temporal_evidence"]["forward"]["post_freeze"] is True
    assert {row["walk_forward_segment"] for row in report["trades"]} == {
        "oos",
        "forward",
    }
    for row in report["trades"]:
        assert row["economic_contract"]["reality_model_version"] == (
            "lead_lag_queue_maker_taker.v1"
        )
        assert set(row["cost_component_receipts"]) == {
            "fees",
            "spread",
            "slippage",
            "latency",
        }


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"execution_model": "legacy-taker"}, "FROZEN_MAKER_PROTOCOL_MISMATCH"),
        ({"selection_cutoff_ms": 11 * 86_400_000}, "INVALID_SELECTION_CUTOFF"),
        ({"latency_evidence_sha256": "short"}, "INVALID_FROZEN_EVIDENCE_HASH"),
        ({"training_selection_eligible": False}, "TRAINING_SELECTION_NOT_ELIGIBLE"),
    ],
)
def test_frozen_maker_fails_closed_on_invalid_freeze(
    override: dict[str, object], message: str
) -> None:
    day_ms = 86_400_000
    frozen = {
        **replay_module.maker_protocol_signature(),
        "selection_cutoff_ms": 10 * day_ms,
        "train_ranges": [[1, 10 * day_ms]],
        "applied_latency_ms": 100.0,
        "latency_evidence_sha256": "a" * 64,
        "training_selection_evidence_sha256": "b" * 64,
        "training_selection_eligible": True,
        **override,
    }

    with pytest.raises(ValueError, match=message):
        replay_module.evaluate_frozen_maker(
            {"ETH": {"TRADE": []}},
            {"ETH": []},
            {"ETH": []},
            frozen_parameters=frozen,
            frozen_at_ms=10 * day_ms + 1,
            evaluated_at_ms=13 * day_ms + 1,
        )
