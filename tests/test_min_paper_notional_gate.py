"""Plancher notional paper — activation justifiée par replay A/B (2026-07-07).

Sur les logs frais, les trades < 40 USDT ont un net négatif (frais > brut).
Le gate refuse ces entrées avec un événement ledger NO_TRADE explicable.
"""

from __future__ import annotations

from hl_observer.ui.fusion_persistent_adapter import apply_fusion_paper_orders_to_state
from hl_observer.ui.state import UiState


def _accepted_decision(notional: float) -> dict:
    return {
        "accepted": True,
        "trade": {
            "trade_id": f"papertrade:minnotional-{notional}",
            "source_delta_id": f"fusion-paper-engine:HYPE:LONG:{notional}",
            "fill_price": 70.0,
            "notional_usdt": notional,
            "fees_and_cost_bps": 8.0,
            "coin": "HYPE",
            "side": "LONG",
        },
        "position": {
            "source_delta_id": f"fusion-paper-engine:HYPE:LONG:{notional}",
            "coin": "HYPE",
            "side": "LONG",
            "quantity": notional / 70.0,
            "entry_price": 70.0,
            "notional_usdt": notional,
            "opened_at_ms": 126_000,
            "leader_wallet": "0x" + "2" * 40,
        },
        "evidence_hash": f"pevidence:minnotional-{notional}",
    }


def _fusion_status(notional: float) -> dict:
    return {
        "status": "OK_LIVE_FUSION_RUNTIME",
        "paper_only": True,
        "real_execution": False,
        "runtime": {
            "session": {"session_id": "min-notional-test"},
            "external_profile_executions": [],
            "paper_engine": {"accepted_count": 1, "decisions": [_accepted_decision(notional)]},
            "paper_orders": [],
        },
        "paper_engine": {"accepted_count": 1, "decisions": [_accepted_decision(notional)]},
    }


def test_paper_engine_entry_below_minimum_notional_is_refused(monkeypatch):
    monkeypatch.setenv("HYPERSMART_MIN_PAPER_NOTIONAL_USDT", "40")
    state = UiState()
    report = apply_fusion_paper_orders_to_state(state, _fusion_status(12.0), current_ms=126_000)
    assert report["applied_count"] == 0
    assert "PAPER_NOTIONAL_BELOW_MINIMUM" in report["reasons"]
    assert state.simulation_virtual_positions == {}
    assert any(
        row.get("paper_action_type") == "NO_TRADE"
        and row.get("reason") == "PAPER_NOTIONAL_BELOW_MINIMUM"
        and row.get("coin") == "HYPE"
        for row in state.simulation_ledger_events
    )


def test_paper_engine_entry_at_minimum_notional_is_accepted(monkeypatch):
    monkeypatch.setenv("HYPERSMART_MIN_PAPER_NOTIONAL_USDT", "40")
    state = UiState()
    report = apply_fusion_paper_orders_to_state(state, _fusion_status(40.0), current_ms=126_000)
    assert report["applied_count"] == 1
    assert len(state.simulation_virtual_positions) == 1


def test_gate_disabled_by_default_keeps_small_entries(monkeypatch):
    monkeypatch.delenv("HYPERSMART_MIN_PAPER_NOTIONAL_USDT", raising=False)
    state = UiState()
    report = apply_fusion_paper_orders_to_state(state, _fusion_status(12.0), current_ms=126_000)
    assert report["applied_count"] == 1
