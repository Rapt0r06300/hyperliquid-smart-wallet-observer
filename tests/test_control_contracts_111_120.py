from __future__ import annotations

from hl_observer.copy_vault.authoritative_close_direction import authoritative_close_receipt
from hl_observer.copy_vault.close_only_degradation import close_only_receipt
from hl_observer.copy_vault.close_priority_queue import close_priority_receipt
from hl_observer.copy_vault.liquidation_distance_gate import liquidation_distance_receipt
from hl_observer.copy_vault.multi_vault_intent_netting import netting_attribution_receipt
from hl_observer.copy_vault.orphan_copy_sweeper import orphan_sweep_receipt
from hl_observer.copy_vault.per_coin_serialization import serialization_receipt
from hl_observer.risk.correlated_exposure import Position, correlated_exposure_receipt
from hl_observer.risk.portfolio_drawdown_kill_switch import drawdown_kill_switch_receipt


def test_111_correlated_exposure_is_capped() -> None:
    result = correlated_exposure_receipt(
        [Position("BTC", "LONG", 200.0)],
        Position("ETH", "LONG", 150.0),
        correlation_groups={"BTC": "majors", "ETH": "majors"},
    )
    assert result["status"] == "PROVEN"
    assert result["allowed"] is False


def test_112_netting_keeps_vault_attribution() -> None:
    result = netting_attribution_receipt([
        {"vault_id": "A", "coin": "BTC", "montant_signe": 80.0},
        {"vault_id": "B", "coin": "BTC", "montant_signe": -50.0},
    ])
    assert result["status"] == "PROVEN"
    assert result["net_par_coin"] == {"BTC": 30.0}
    assert result["attribution_by_coin"] == {"BTC": ["A", "B"]}


def test_113_same_coin_serialization_refuses_reentry() -> None:
    result = serialization_receipt(vault="vault-a", coin="BTC")
    assert result["status"] == "PROVEN"
    assert result["reentrant_acquire"]["ok"] is False


def test_114_close_priority_is_stable() -> None:
    result = close_priority_receipt([
        {"id": "open", "action": "OPEN"},
        {"id": "close", "action": "CLOSE"},
        {"id": "reduce", "action": "REDUCE"},
    ])
    assert result["status"] == "PROVEN"
    assert [item["id"] for item in result["order"]] == ["close", "reduce", "open"]


def test_115_incomplete_data_degrades_to_close_only() -> None:
    result = close_only_receipt("OPEN", donnees_completes=False)
    assert result["status"] == "PROVEN"
    assert result["allowed"] is False
    assert result["close_only"] is True


def test_116_close_direction_uses_current_position() -> None:
    result = authoritative_close_receipt(-3.0, 5.0)
    assert result["status"] == "PROVEN"
    assert result["direction"] == "ACHAT"
    assert result["quantite"] == 3.0


def test_117_orphan_copy_is_fail_closed() -> None:
    result = orphan_sweep_receipt(0.0, 2.0)
    assert result["status"] == "PROVEN"
    assert result["orphelin"] is True
    assert result["sens_debouclage"] == "VENTE"


def test_118_liquidation_distance_blocks_close_to_liquidation() -> None:
    result = liquidation_distance_receipt(2.0, seuil_pct=5.0)
    assert result["status"] == "PROVEN"
    assert result["peut_augmenter"] is False
    assert result["peut_reduire"] is True


def test_120_drawdown_kill_switch_is_paper_only() -> None:
    result = drawdown_kill_switch_receipt(peak_equity=100.0, current_equity=90.0, max_drawdown_pct=5.0)
    assert result == {
        "status": "PROVEN",
        "triggered": True,
        "drawdown_pct": 10.0,
        "reason": "PORTFOLIO_DRAWDOWN_KILL_SWITCH",
        "real_execution": False,
    }
