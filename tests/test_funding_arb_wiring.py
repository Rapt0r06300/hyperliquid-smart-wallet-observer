"""Câblage funding-arb paper: fusion_runtime -> adapter -> ledger (brique 2)."""

from __future__ import annotations

from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote  # noqa: F401  # ordre d'import (cycle)
from hl_observer.funding.funding_arb_paper import reset_funding_arb_store
from hl_observer.realtime.multi_source_price_stream import PriceEvent
from hl_observer.strategies.fusion_runtime import FusionRuntimeInput, run_fusion_strategy_runtime
from hl_observer.ui.fusion_persistent_adapter import apply_fusion_paper_orders_to_state
from hl_observer.ui.state import UiState


STABLE_HIGH = [0.00049, 0.00051, 0.0005, 0.00052, 0.00048, 0.0005, 0.00051, 0.00049, 0.0005, 0.00052, 0.00048, 0.0005]


def _input(now_ms: int) -> FusionRuntimeInput:
    return FusionRuntimeInput(
        session_id="funding-arb-test",
        leader_votes=(),
        price_events=(PriceEvent("hl", "HYPE", 70.0, 70.05, now_ms),),
        funding_rows=({"coin": "HYPE", "rates": STABLE_HIGH},),
        triangular_edges=(),
        latencies_ms=(100,),
        peak_equity=1000.0,
        current_equity=1000.0,
    )


def test_runtime_disabled_by_default(monkeypatch):
    monkeypatch.delenv("HYPERSMART_FUNDING_ARB_PAPER", raising=False)
    reset_funding_arb_store()
    result = run_fusion_strategy_runtime(_input(1_000_000))
    assert result.funding_arb == {}


def test_runtime_opens_then_accrues_across_ticks(monkeypatch):
    monkeypatch.setenv("HYPERSMART_FUNDING_ARB_PAPER", "1")
    reset_funding_arb_store()
    first = run_fusion_strategy_runtime(_input(0))
    assert first.funding_arb["enabled"] is True
    assert first.funding_arb["open_pairs"] == 1
    assert any(e["action"] == "OPEN" for e in first.funding_arb["events"])
    second = run_fusion_strategy_runtime(_input(2 * 3_600_000))
    accruals = [e for e in second.funding_arb["events"] if e["action"] == "ACCRUAL"]
    assert len(accruals) == 1
    assert abs(accruals[0]["amount_usdc"] - 25.0 * (5.0 / 10_000.0) * 2) < 0.002
    assert all(e["real_execution"] is False for e in second.funding_arb["events"])
    reset_funding_arb_store()


def _fusion_status_with_funding_events() -> dict:
    return {
        "status": "OK_LIVE_FUSION_RUNTIME",
        "paper_only": True,
        "real_execution": False,
        "runtime": {
            "session": {"session_id": "fa"},
            "external_profile_executions": [],
            "paper_orders": [],
            "paper_engine": {"decisions": []},
            "funding_arb": {
                "enabled": True,
                "events": [
                    {"action": "OPEN", "coin": "HYPE", "pair_id": "fundingarb:HYPE:0", "reason": "FUNDING_EDGE_SHORT_RECEIVES", "amount_usdc": 0.0075},
                    {"action": "ACCRUAL", "coin": "HYPE", "pair_id": "fundingarb:HYPE:0", "reason": "FUNDING_ACCRUED_2H", "amount_usdc": 0.025},
                    {
                        "action": "CLOSE",
                        "coin": "HYPE",
                        "pair_id": "fundingarb:HYPE:0",
                        "reason": "FUNDING_EDGE_COLLAPSED",
                        "amount_usdc": 0.0075,
                        "price_pnl_usdc": 0.0,
                        "price_pnl_unknown": False,
                        "net_pnl_usdc": 0.01,
                    },
                ],
            },
        },
        "paper_engine": {"decisions": []},
    }


def test_adapter_credits_funding_events_to_ledger_without_double_count():
    state = UiState()
    report = apply_fusion_paper_orders_to_state(state, _fusion_status_with_funding_events(), current_ms=5_000)
    assert report["funding_arb_events_recorded"] == 3
    # OPEN -0.0075, ACCRUAL +0.025, CLOSE -0.0075 => net +0.01
    assert abs(state.simulation_realized_pnl_usdc - 0.01) < 1e-9
    funding_events = [e for e in state.simulation_ledger_events if str(e.get("paper_action_type", "")).startswith("FUNDING_ARB_")]
    assert len(funding_events) == 3
    assert all(e["execution"] == "forbidden" and e["real_execution"] is False for e in funding_events)
    # Rejouer le même tick: dédupliqué, PnL inchangé
    report2 = apply_fusion_paper_orders_to_state(
        state,
        _fusion_status_with_funding_events(),
        current_ms=999_999,
    )
    assert report2["funding_arb_events_recorded"] == 0
    assert abs(state.simulation_realized_pnl_usdc - 0.01) < 1e-9


# ---------------------------------------------------------------------------------------------
# VERROU CARRY (2026-07-11) -- POURQUOI CES TESTS FORCENT UN FLAG.
#
# Ces tests verifient la MECANIQUE du moteur funding (accrual, caps, sortie, PnL). Pour cela, il
# faut qu'une position s'ouvre. Or depuis la mesure du 2026-07-11, le moteur REFUSE par defaut
# d'ouvrir une jambe NUE :
#
#     232 marches, 9 512 releves : funding median 0,125 bps/h contre ~35 bps/h de mouvement de
#     prix. Pour 1 bps de funding encaisse, une jambe nue subit ~281 bps de mouvement de prix.
#
# On active donc explicitement `HYPERSMART_FUNDING_ALLOW_UNHEDGED_LEG=1` : c'est un mode A/B
# ASSUME, PAS le comportement de production. Le defaut, lui, reste le REFUS -- et c'est
# `tests/test_funding_carry_economics.py` qui garde cette regle.
# ---------------------------------------------------------------------------------------------
import pytest as _pytest


@_pytest.fixture(autouse=True)
def _autoriser_jambe_nue_pour_tester_la_mecanique(monkeypatch):
    """Mode A/B : on ouvre la vanne pour pouvoir tester l'interieur du moteur."""
    monkeypatch.setenv("HYPERSMART_FUNDING_ALLOW_UNHEDGED_LEG", "1")
