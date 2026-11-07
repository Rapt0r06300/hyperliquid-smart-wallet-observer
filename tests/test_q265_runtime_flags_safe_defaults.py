"""Q-265 — Env vars absentes → défauts sûrs.

Vérifie que runtime_flags renvoie des défauts paper/read-only/fail-closed
quand AUCUNE variable HYPERSMART_ n'est posée.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("HYPERSMART_") or key.startswith("HL_"):
            monkeypatch.delenv(key, raising=False)


def test_security_defaults_paper():
    from hl_observer.config.runtime_flags import load_security

    sec = load_security()
    assert sec.hl_env == "paper"
    assert sec.mainnet_execution is False
    assert sec.testnet_execution is False
    assert sec.paper_only is True


def test_sizing_defaults_conservative():
    from hl_observer.config.runtime_flags import load_sizing

    sz = load_sizing()
    assert sz.capital_usd == 350.0
    assert sz.leverage == 5
    assert sz.max_open_positions == 2
    assert sz.kelly_sizing_enabled is True
    assert sz.kelly_fraction == 0.25
    assert sz.min_paper_notional_usd >= 10.0


def test_signal_defaults_strict():
    from hl_observer.config.runtime_flags import load_signals

    sig = load_signals()
    assert sig.max_signal_age_ms <= 30_000
    assert sig.min_edge_bps > 0
    assert sig.min_liquidity_score > 0
    assert sig.fusion_copy_min_wallets >= 2


def test_protection_defaults_all_enabled():
    from hl_observer.config.runtime_flags import load_protections

    prot = load_protections()
    assert prot.risk_gate_enabled is True
    assert prot.entry_gate_enabled is True
    assert prot.exit_engine_enabled is True
    assert prot.fair_value_veto is True
    assert prot.protections_v26 is True
    assert prot.graded_halt is True


def test_security_assert_paper_passes():
    from hl_observer.config.runtime_flags import load_security

    sec = load_security()
    sec.assert_paper()


def test_security_assert_paper_fails_on_mainnet(monkeypatch):
    monkeypatch.setenv("HL_ENABLE_MAINNET_EXECUTION", "1")
    from hl_observer.config.runtime_flags import load_security

    sec = load_security()
    with pytest.raises(RuntimeError, match="PAPER invariant violated"):
        sec.assert_paper()
