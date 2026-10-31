from __future__ import annotations

import json

from hl_observer.backtesting.copy_vault_generalization import (
    derive_heldout_vault_generalization,
)


def _trade(vault: str, ts: int, net: float, suffix: str) -> dict:
    return {
        "vault": vault,
        "signal_ts_ms": ts,
        "net_pnl_usd": net,
        "notional_usd": 100.0,
        "trade_id": suffix * 64,
        "liquidatable_net": True,
    }


def _strict_trade(*, net: float, suffix: str, gross: float = 2.0) -> dict:
    return {
        **_trade("B", 300, net, suffix),
        "coin": "BTC",
        "direction": 1,
        "gross_pnl_usd": gross,
        "fees_usd": 1.0,
        "spread_cost_usd": 0.0,
        "slippage_cost_usd": 0.0,
        "latency_cost_usd": 0.0,
        "entry_capacity_usd": 100.0,
        "exit_capacity_usd": 100.0,
        "causal_books_eligible": True,
        "causal_forward_eligible": True,
        "paper_read_only": True,
        "real_execution": False,
        "reference_lag_ms": 0,
        "entry_target_lag_ms": 0,
        "exit_target_lag_ms": 0,
        "observed_latency_ms": 0,
    }


def test_generalisation_exclut_tout_vault_deja_vu_avant_oos() -> None:
    trades = [
        _trade("A", 100, 1.0, "a"),
        _trade("A", 300, 3.0, "b"),
        _trade("B", 300, 2.0, "c"),
    ]
    proof = derive_heldout_vault_generalization(trades, oos_start_ms=200)
    assert proof is not None
    assert proof["sample_count"] == 1
    assert proof["vaults_held_out"] == ["B"]
    assert proof["net_pnl_usd"] == 2.0
    assert proof["net_bps"] == 200.0


def test_generalisation_ne_fabrique_pas_de_preuve_sans_vault_inedit() -> None:
    trades = [_trade("A", 100, 1.0, "a"), _trade("A", 300, 2.0, "b")]
    proof = derive_heldout_vault_generalization(trades, oos_start_ms=200)
    assert proof is not None
    assert proof["sample_count"] == 0
    assert proof["net_bps"] is None
    assert proof["heldout_vault_count"] == 0
    assert proof["net_pnl_usd"] is None
    assert proof["notional_usd"] is None
    assert proof["max_drawdown_usd"] is None


def test_generalisation_preserves_native_case_sensitive_coin_identity() -> None:
    lower = _strict_trade(net=1.0, suffix="a")
    upper = _strict_trade(net=1.0, suffix="b")
    lower["coin"] = "kPEPE"
    upper["coin"] = "KPEPE"
    lower["vault"] = "B"
    lower["direction"] = 1
    upper["vault"] = "C"
    upper["direction"] = -1

    proof = derive_heldout_vault_generalization([lower, upper], oos_start_ms=200)

    assert proof is not None
    assert proof["sample_count"] == 2
    assert proof["vault_conflict_pairs"] == 0


def test_generalisation_agrege_economie_nette_par_vault_et_ids() -> None:
    trades = [
        _trade("B", 300, 1.0, "a"),
        _trade("B", 400, -0.25, "b"),
        _trade("C", 500, 0.5, "c"),
    ]
    proof = derive_heldout_vault_generalization(trades, oos_start_ms=200)
    assert proof is not None
    assert proof["sample_count"] == 3
    assert proof["heldout_vault_count"] == 2
    assert proof["heldout_profit_vault_count"] == 2
    assert proof["min_heldout_vault_net_pnl_usd"] == 0.5
    assert proof["trade_ids_count"] == 3
    assert len(proof["trade_ids_sha256"]) == 64


def test_generalisation_conserve_les_petites_valeurs_economiques_non_nulles() -> None:
    proof = derive_heldout_vault_generalization(
        [_trade("B", 300, 1e-12, "a")], oos_start_ms=200
    )

    assert proof is not None
    assert proof["heldout_profit_vault_count"] == 1
    assert proof["per_vault"][0]["net_pnl_usd"] == 1e-12
    assert proof["net_pnl_usd"] == 1e-12
    assert proof["net_bps"] == 1e-10


def test_generalisation_refuse_frontiere_oos_absente() -> None:
    assert derive_heldout_vault_generalization([], oos_start_ms=None) is None


def test_generalisation_rejette_ecart_pnl_superieur_a_la_tolerance_canonique() -> None:
    proof = derive_heldout_vault_generalization(
        [_strict_trade(net=1.0000001, suffix="d")], oos_start_ms=200
    )

    assert proof is not None
    assert proof["sample_count"] == 0
    assert proof["economic_claim_eligible"] is False
    assert proof["rejection_reasons"]["ECONOMIC_RECONCILIATION_FAILED"] == 1


def test_generalisation_ne_cumule_pas_les_tolerances_par_trade() -> None:
    proof = derive_heldout_vault_generalization(
        [
            _strict_trade(net=1.000000007, suffix="e"),
            _strict_trade(net=1.000000007, suffix="f"),
        ],
        oos_start_ms=200,
    )

    assert proof is not None
    assert proof["economic_claim_eligible"] is True
    assert proof["net_pnl_usd"] == 2.0
    json.dumps(proof, sort_keys=True, allow_nan=False)
