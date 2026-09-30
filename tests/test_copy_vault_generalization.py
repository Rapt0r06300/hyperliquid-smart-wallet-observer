from __future__ import annotations

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
