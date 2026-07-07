"""P6: gate d'éligibilité testnet (verrouillé tant que le paper n'a pas prouvé)
+ preuve que l'adaptateur refuse toute URL non-testnet (mainnet impossible)."""

from __future__ import annotations

import pytest

from hl_observer.testnet.adapters import HyperliquidTestnetAdapter
from hl_observer.testnet.readiness_gate import evaluate_testnet_readiness


def test_not_ready_by_default_empty_history():
    r = evaluate_testnet_readiness([], safety_audit_green=False, closed_trades=0)
    assert r["testnet_eligible"] is False
    assert r["verdict"] == "NOT_READY_STAY_PAPER"


def test_not_ready_when_pf_unstable_even_if_mean_ok():
    # 14 jours mais un jour sous 1.0 → refusé (stabilité exigée)
    pfs = [1.3] * 13 + [0.7]
    r = evaluate_testnet_readiness(pfs, safety_audit_green=True, closed_trades=200)
    assert r["testnet_eligible"] is False
    assert any("PF_BELOW_1" in x for x in r["reasons"])


def test_not_ready_when_safety_audit_not_green():
    pfs = [1.2] * 14
    r = evaluate_testnet_readiness(pfs, safety_audit_green=False, closed_trades=200)
    assert r["testnet_eligible"] is False
    assert "SAFETY_AUDIT_NOT_GREEN" in r["reasons"]


def test_not_ready_when_sample_too_small():
    pfs = [1.2] * 14
    r = evaluate_testnet_readiness(pfs, safety_audit_green=True, closed_trades=20)
    assert r["testnet_eligible"] is False
    assert any("INSUFFICIENT_SAMPLE" in x for x in r["reasons"])


def test_ready_only_when_all_gates_pass():
    pfs = [1.2] * 14
    r = evaluate_testnet_readiness(
        pfs, min_days_stable=14, safety_audit_green=True,
        closed_trades=200, observed_max_drawdown_usdc=5.0, max_drawdown_usdc=20.0,
    )
    assert r["testnet_eligible"] is True
    assert r["verdict"] == "READY_FOR_TESTNET_REVIEW"
    assert r["mean_pf"] == 1.2


def test_drawdown_blocks_readiness():
    pfs = [1.5] * 14
    r = evaluate_testnet_readiness(pfs, safety_audit_green=True, closed_trades=200,
                                   observed_max_drawdown_usdc=50.0, max_drawdown_usdc=20.0)
    assert r["testnet_eligible"] is False
    assert "DRAWDOWN_EXCEEDS_LIMIT" in r["reasons"]


def test_adapter_refuses_non_testnet_url_mainnet_impossible():
    # une URL mainnet est rejetée à la connexion — jamais d'ordre hors testnet
    mainnet = HyperliquidTestnetAdapter(base_url="https://api.hyperliquid.xyz")
    with pytest.raises(RuntimeError, match="refused non-testnet URL"):
        mainnet.connect()
    # une URL testnet se connecte, mais l'exécution reste verrouillée (signature requise)
    tnet = HyperliquidTestnetAdapter(base_url="https://api.hyperliquid-testnet.xyz")
    tnet.connect()
    assert tnet.status == "READY_BUT_LOCKED_SIGNATURE_REQUIRED"
