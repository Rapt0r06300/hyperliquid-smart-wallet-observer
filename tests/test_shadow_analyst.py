"""IA-5: analyste shadow-only (explication déterministe, aucune autorité)."""

from __future__ import annotations

from hl_observer.ml.shadow_analyst import explain_decision, summarize_session


def test_explains_accepted_trade():
    txt = explain_decision({"action": "OPEN", "coin": "HYPE", "side": "LONG",
                            "edge_remaining_bps": 46, "leader_wallets_count": 4, "signal_age_ms": 1200, "liquidity_score": 0.8})
    assert "HYPE" in txt and "LONG" in txt and "46 bps" in txt and "shadow-only" in txt


def test_explains_refusal_with_human_verdict():
    txt = explain_decision({"paper_action_type": "NO_TRADE", "coin": "MON", "reason": "EDGE_TOO_SMALL"})
    assert "REFUSÉ" in txt and "avantage net insuffisant" in txt
    stale = explain_decision({"paper_action_type": "NO_TRADE", "coin": "LIT", "reason": "SIGNAL_TOO_OLD"})
    assert "trop vieux" in stale


def test_session_summary_is_honest():
    trades = [{"coin": "A", "net_pnl_usdc": 1.0}, {"coin": "B", "net_pnl_usdc": -0.5}]
    s = summarize_session(trades)
    assert "2 trades" in s and "aucune promesse" in s.lower()
    assert summarize_session([]) == "Aucun trade clos à analyser pour l'instant."
