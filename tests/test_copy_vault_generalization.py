from __future__ import annotations

from decimal import Decimal

from hl_observer.backtesting.copy_vault_generalization import (
    derive_heldout_vault_generalization,
)


def _trade(
    vault: str, ts: int, net: float, suffix: str, *, coin: str = "BTC", direction: int = 1
) -> dict:
    return {
        "vault": vault,
        "signal_ts_ms": ts,
        "net_pnl_usd": net,
        "notional_usd": 100.0,
        "trade_id": suffix * 64,
        "liquidatable_net": True,
        "coin": coin,
        "direction": direction,
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


def test_generalisation_refuse_frontiere_oos_absente() -> None:
    assert derive_heldout_vault_generalization([], oos_start_ms=None) is None


def test_generalisation_ne_confond_pas_les_symboles_native_case_sensitive():
    proof = derive_heldout_vault_generalization(
        [
            _trade("A", 300, 1.0, "a", coin="kPEPE", direction=1),
            _trade("B", 301, 1.0, "b", coin="KPEPE", direction=-1),
        ],
        oos_start_ms=200,
    )

    assert proof is not None
    assert proof["vault_conflict_pairs"] == 0


def _strict_trade(*, net: float, gross: float, suffix: str) -> dict:
    return {
        **_trade("B", 300, net, suffix),
        "gross_pnl_usd": gross,
        "fees_usd": 0.0,
        "spread_cost_usd": 0.0,
        "slippage_cost_usd": 0.0,
        "latency_cost_usd": 0.0,
        "entry_capacity_usd": 200.0,
        "exit_capacity_usd": 200.0,
        "causal_books_eligible": True,
        "causal_forward_eligible": True,
        "paper_read_only": True,
        "real_execution": False,
        "reference_lag_ms": 1.0,
        "entry_target_lag_ms": 1.0,
        "exit_target_lag_ms": 1.0,
        "observed_latency_ms": 1.0,
    }


def test_strict_generalisation_rejects_relative_tolerance_pnl_forgery() -> None:
    forged = _strict_trade(net=999_999_999.0, gross=1_000_000_000.0, suffix="d")

    proof = derive_heldout_vault_generalization([forged], oos_start_ms=200)

    assert proof is not None
    assert proof["sample_count"] == 0
    assert proof["economic_claim_eligible"] is False
    assert proof["rejection_reasons"]["ECONOMIC_RECONCILIATION_FAILED"] == 1


def test_strict_generalisation_never_credits_reconciliation_tolerance() -> None:
    row = _strict_trade(net=1.000000005, gross=1.0, suffix="e")

    proof = derive_heldout_vault_generalization([row], oos_start_ms=200)

    assert proof is not None
    assert proof["economic_claim_eligible"] is True
    assert proof["net_pnl_usd"] <= 1.0
    assert Decimal(proof["net_pnl_usd_exact_decimal"]) == Decimal("1.0")


def test_strict_generalisation_detects_share_just_above_half_without_float_rounding() -> None:
    values = ("0.50000000000000001", "0.49999999999999999")
    trades = []
    for index, net in enumerate(values):
        row = _strict_trade(net=0.5, gross=0.5, suffix=chr(ord("f") + index))
        row["net_pnl_usd"] = net
        row["gross_pnl_usd"] = net
        trades.append(row)

    proof = derive_heldout_vault_generalization(trades, oos_start_ms=200)

    assert proof is not None
    assert proof["economic_claim_eligible"] is True
    assert proof["one_big_win_dependency"] is True
    assert proof["largest_positive_trade_share"] == 0.5
    assert Decimal(proof["largest_positive_trade_share_upper_bound_decimal"]) > Decimal("0.50")
    assert proof["one_big_win_share_threshold_exact_decimal"] == "0.50"
