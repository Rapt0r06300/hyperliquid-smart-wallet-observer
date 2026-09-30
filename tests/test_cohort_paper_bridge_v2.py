from __future__ import annotations

from dataclasses import dataclass

from hl_observer.experimental.cohort_paper_bridge import (
    ECONOMIC_SOURCE,
    apply_entry,
    apply_exit,
    build_engine,
    canonical_execution_truth,
    position_from_projection,
)

NOW_MS = 1_800_000_000_000
WALLET = "0x" + "a" * 40


@dataclass(frozen=True)
class _Cohort:
    nom: str = "TEST_COHORT"
    budget_usd: float = 300.0
    notional_usd: float = 60.0
    max_positions: int = 3


def _book() -> dict[str, object]:
    return {
        "bids": [[99.98, 0.2], [99.95, 100.0]],
        "asks": [[100.02, 0.2], [100.05, 100.0]],
        "received_ts_ms": NOW_MS - 10,
        "exchange_ts_ms": NOW_MS - 20,
        "source": "test:recorded-hyperliquid-l2",
        "data_origin": "RECORDED_REAL",
    }


def _entry(engine, truth, *, edge: float | None = 80.0):
    return apply_entry(
        engine,
        wallet=WALLET,
        coin="HYPE",
        side_sign=1,
        leader_size=2.0,
        observed_at_ms=NOW_MS,
        leader_event_time_ms=NOW_MS - 50,
        evidence_ref="fill:recorded:hype:1",
        edge_remaining_bps=edge,
        wallet_score=95.0,
        signal_score=99.0,
        estimated_slippage_bps=1.0,
        target_notional_usdt=60.0,
        execution_truth=truth,
    )


def _projection(result) -> dict[str, object]:
    assert result.position is not None
    assert result.trade is not None
    position = result.position
    return {
        "coin": position.coin,
        "paire": position.coin,
        "sens": 1,
        "quantity": position.quantity,
        "notional_usd": position.notional_usdt,
        "margin_locked_usd": position.margin_locked_usdt,
        "prix_entree": position.entry_price,
        "ts_ouverture_ms": position.opened_at_ms,
        "meta": {
            "vault": position.leader_wallet,
            "paper_position_id": position.position_id,
            "source_delta_id": position.source_delta_id,
            "economic_source": ECONOMIC_SOURCE,
        },
    }


def test_bridge_requires_real_full_l2() -> None:
    assert canonical_execution_truth(
        "HYPE",
        {
            "hl_bid": 99.98,
            "hl_ask": 100.02,
            "received_ts_ms": NOW_MS - 10,
            "source": "test:top-only",
            "data_origin": "RECORDED_REAL",
        },
        now_ms=NOW_MS,
    ) is None


def test_bridge_execution_is_deterministic_and_walks_multiple_levels() -> None:
    truth = canonical_execution_truth("HYPE", _book(), now_ms=NOW_MS)
    assert truth is not None
    first = _entry(build_engine(_Cohort(), {}, taker_fee_bps=3.5), truth)
    second = _entry(build_engine(_Cohort(), {}, taker_fee_bps=3.5), truth)

    assert first.accepted is True
    assert second.accepted is True
    assert first.trade is not None and second.trade is not None
    assert first.trade.fill_price == second.trade.fill_price
    assert first.trade.fees_and_cost_bps == second.trade.fees_and_cost_bps
    assert first.trade.execution_snapshot_id == truth.snapshot_id
    assert first.trade.fill_price > truth.best_ask
    assert first.ledger_snapshot is not None
    assert first.ledger_snapshot["strict_pnl_allowed"] is True


def test_bridge_refuses_unmeasurable_edge_without_position_or_pnl() -> None:
    truth = canonical_execution_truth("HYPE", _book(), now_ms=NOW_MS)
    assert truth is not None
    result = _entry(build_engine(_Cohort(), {}, taker_fee_bps=3.5), truth, edge=None)

    assert result.accepted is False
    assert "EDGE_UNMEASURABLE" in result.reason_codes
    assert result.position is None
    assert result.realized_pnl_usdt == 0.0


def test_bridge_reduce_is_proportional_and_restore_is_idempotent() -> None:
    truth = canonical_execution_truth("HYPE", _book(), now_ms=NOW_MS)
    assert truth is not None
    engine = build_engine(_Cohort(), {}, taker_fee_bps=3.5)
    opened = _entry(engine, truth)
    payload = _projection(opened)
    original = position_from_projection("HYPE", payload)

    events_before_restore = len(engine.ledger.events)
    engine.restore_position(original)
    assert len(engine.ledger.events) == events_before_restore

    reduced = apply_exit(
        engine,
        position_payload=payload,
        fraction=0.25,
        observed_at_ms=NOW_MS + 100,
        leader_event_time_ms=NOW_MS + 90,
        evidence_ref="fill:recorded:hype:reduce",
        execution_truth=truth,
        reason="LEADER_A_REDUIT",
    )
    assert reduced.accepted is True
    assert reduced.trade is not None
    assert reduced.position is not None
    assert reduced.trade.action == "REDUCE"
    assert reduced.position.quantity == original.quantity * 0.75
    assert reduced.trade.quantity == original.quantity * 0.25
    assert reduced.ledger_snapshot is not None
    assert reduced.ledger_snapshot["strict_pnl_allowed"] is True
