from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.simulation.ledger_integrity import seal_chain
from hl_observer.simulation.log_metrics import analyze_logs_streaming
from hl_observer.simulation.paper_ledger import PaperLedger
from hl_observer.simulation.pnl_ledger_audit import CONTAMINATED, TRUSTED, audit_paper_ledger


def _complete_lifecycle() -> PaperLedger:
    ledger = PaperLedger(starting_balance_usdc=1_000.0, session_id="paper:audit")
    ledger.open_position(
        coin="HYPE",
        side="LONG",
        notional_usdc=100.0,
        fill_price=10.0,
        timestamp_ms=1,
        fee_bps=5.0,
    )
    ledger.open_position(
        coin="HYPE",
        side="LONG",
        notional_usdc=55.0,
        fill_price=11.0,
        timestamp_ms=2,
        fee_bps=5.0,
    )
    ledger.reduce_or_close(
        coin="HYPE",
        side="LONG",
        quantity=6.0,
        fill_price=12.0,
        timestamp_ms=3,
        fee_bps=5.0,
    )
    ledger.apply_funding(
        coin="HYPE",
        side="LONG",
        amount_usdc=0.2,
        timestamp_ms=4,
    )
    ledger.reduce_or_close(
        coin="HYPE",
        side="LONG",
        quantity=9.0,
        fill_price=9.0,
        timestamp_ms=5,
        fee_bps=5.0,
    )
    return ledger


def test_semantic_audit_reconciles_open_add_reduce_close_costs_and_funding():
    ledger = _complete_lifecycle()

    audit = audit_paper_ledger(
        (event.to_dict() for event in ledger.events),
        snapshot=ledger.snapshot(),
    )

    assert audit.status == TRUSTED
    assert audit.pnl_valid is True
    assert audit.open_positions == {}
    assert audit.realized_pnl_usdc == pytest.approx(-2.0)
    assert audit.fees_paid_usdc == pytest.approx(0.154)
    assert audit.funding_net_usdc == pytest.approx(0.2)
    assert audit.recalculated_net_pnl_usdc == pytest.approx(-1.954)
    assert audit.recalculated_equity_usdc == pytest.approx(998.046)
    assert ledger.snapshot()["strict_pnl_allowed"] is True
    assert ledger.snapshot()["pnl_audit"]["status"] == TRUSTED


def test_empty_new_ledger_has_audited_zero_pnl():
    snapshot = PaperLedger(starting_balance_usdc=1_000.0).snapshot()

    assert snapshot["strict_pnl_allowed"] is True
    assert snapshot["pnl_audit"]["status"] == TRUSTED
    assert snapshot["pnl_audit"]["recalculated_net_pnl_usdc"] == 0.0


def test_position_events_reference_authoritative_fee_and_position_identity():
    ledger = _complete_lifecycle()
    rows = [event.to_dict() for event in ledger.events]
    fee_ids = {row["event_id"] for row in rows if row["event_type"] == "PaperFeeCharged"}
    position_rows = [
        row
        for row in rows
        if row["event_type"]
        in {
            "PaperPositionOpened",
            "PaperPositionIncreased",
            "PaperPositionReduced",
            "PaperPositionClosed",
        }
    ]

    assert position_rows
    assert all(row["refs"]["position_id"] == "HYPE:LONG" for row in position_rows)
    assert all(row["refs"]["fee_accounting"] == "SEPARATE_EVENT" for row in position_rows)
    assert all(row["refs"]["fee_event_id"] in fee_ids for row in position_rows)


def test_identical_fills_in_same_millisecond_keep_unique_event_identity():
    ledger = PaperLedger(starting_balance_usdc=1_000.0, session_id="paper:same-ms")
    for _ in range(2):
        ledger.open_position(
            coin="HYPE",
            side="LONG",
            notional_usdc=100.0,
            fill_price=10.0,
            timestamp_ms=1,
            fee_bps=5.0,
        )

    event_ids = [event.event_id for event in ledger.events]
    assert len(event_ids) == len(set(event_ids))
    assert ledger.verify_event_chain()
    assert ledger.snapshot()["strict_pnl_allowed"] is True


def test_semantic_audit_invalidates_ambiguous_historical_pnl_without_rewriting_it():
    old_rows = seal_chain(
        [
            {
                "event_type": "PaperPositionOpened",
                "timestamp_ms": 1,
                "coin": "BTC",
                "side": "SHORT",
                "quantity": 1.0,
                "price": 100.0,
                "notional_usdc": 100.0,
                "fee_usdc": 0.05,
                "refs": {"position_id": "BTC:SHORT"},
            },
            {
                "event_type": "PaperPositionClosed",
                "timestamp_ms": 2,
                "coin": "BTC",
                "side": "SHORT",
                "quantity": 1.0,
                "price": 90.0,
                "notional_usdc": 90.0,
                "fee_usdc": 0.045,
                "realized_pnl_usdc": 10.0,
                "refs": {"position_id": "BTC:SHORT"},
            },
        ],
        session_id="paper:legacy-ambiguous",
    )

    audit = audit_paper_ledger(old_rows)

    assert audit.status == CONTAMINATED
    assert audit.pnl_valid is False
    assert audit.recalculated_net_pnl_usdc is None
    assert "AMBIGUOUS_FEE_ATTRIBUTION" in {issue.code for issue in audit.issues}


def test_semantic_audit_rejects_orphan_close_and_identity_mismatch():
    rows = seal_chain(
        [
            {
                "event_type": "PaperPositionClosed",
                "timestamp_ms": 1,
                "coin": "ETH",
                "side": "LONG",
                "quantity": 1.0,
                "price": 2_000.0,
                "realized_pnl_usdc": 3.0,
                "refs": {"position_id": "unknown-position"},
            }
        ],
        session_id="paper:orphan",
    )

    audit = audit_paper_ledger(rows)

    assert audit.status == CONTAMINATED
    assert audit.pnl_valid is False
    assert "CLOSE_WITHOUT_OPEN" in {issue.code for issue in audit.issues}


def test_log_metrics_reads_canonical_ledger_without_double_counting_fees(tmp_path: Path):
    ledger = _complete_lifecycle()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "simulation_pnl_ledger_latest.jsonl").write_text(
        "".join(json.dumps(event.to_dict()) + "\n" for event in ledger.events),
        encoding="utf-8",
    )

    report = analyze_logs_streaming(log_dir)

    assert report.gross_pnl_usdc == pytest.approx(-2.0)
    assert report.fees_usdc == pytest.approx(0.154)
    assert report.net_pnl_usdc == pytest.approx(-1.954)
    assert report.accepted == 4
