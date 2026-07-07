"""A2: pipeline copy/leaders (shortlist swing+PF, consensus clusters, exits)."""

from __future__ import annotations

from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote  # noqa: F401  # ordre d'import
from hl_observer.integration.leader_pipeline import (
    build_copy_shortlist, consensus_and_coin_score, decide_position_exit,
)


def _fill(coin, side, action, ts):
    return {"coin": coin, "side": side, "action": action, "ts_ms": ts}


def _swing_fills():
    return [_fill("HYPE", "LONG", "OPEN", 0), _fill("HYPE", "LONG", "CLOSE", 1_800_000),
            _fill("BTC", "LONG", "OPEN", 2_000_000), _fill("BTC", "LONG", "CLOSE", 4_000_000)]


def _scalp_fills():
    return [_fill("SOL", "LONG", "OPEN", 0), _fill("SOL", "LONG", "CLOSE", 30_000),
            _fill("SOL", "LONG", "OPEN", 60_000), _fill("SOL", "LONG", "CLOSE", 90_000)]


def test_shortlist_swing_only(monkeypatch):
    monkeypatch.setenv("HYPERSMART_COPY_SWING_ONLY", "1")
    monkeypatch.delenv("HYPERSMART_COPY_PF_SHORTLIST", raising=False)
    out = build_copy_shortlist(
        candidate_wallets=["0xswing", "0xscalp"],
        fills_by_wallet={"0xswing": _swing_fills(), "0xscalp": _scalp_fills()},
        closed_trades=[],
    )
    assert out["shortlist"] == ["0xswing"]
    assert "0xscalp" in out["rejected"]


def test_shortlist_off_by_default_keeps_all(monkeypatch):
    monkeypatch.delenv("HYPERSMART_COPY_SWING_ONLY", raising=False)
    monkeypatch.delenv("HYPERSMART_COPY_PF_SHORTLIST", raising=False)
    out = build_copy_shortlist(candidate_wallets=["a", "b"], fills_by_wallet={}, closed_trades=[])
    assert set(out["shortlist"]) == {"a", "b"}


def test_pf_gate_filters_losers(monkeypatch):
    monkeypatch.delenv("HYPERSMART_COPY_SWING_ONLY", raising=False)
    monkeypatch.setenv("HYPERSMART_COPY_PF_SHORTLIST", "1")
    trades = [{"wallet": "0xwin", "net_pnl_usdc": v} for v in (3, 2, -1, 2, 1)] + \
             [{"wallet": "0xlose", "net_pnl_usdc": v} for v in (-3, 1, -2, -1, 1)]
    out = build_copy_shortlist(candidate_wallets=["0xwin", "0xlose"], fills_by_wallet={}, closed_trades=trades, min_trades=5)
    assert out["shortlist"] == ["0xwin"]


def test_consensus_uses_clusters_not_wallets():
    votes = [{"wallet": f"0x{i}", "coin": "HYPE", "side": "LONG", "ts_ms": 1000 + i * 50} for i in range(3)]
    res = consensus_and_coin_score(votes=votes, wallet="0x0", coin="HYPE", closed_trades=[])
    assert res["raw_wallets"] == 3 and res["consensus_clusters"] == 1


def test_exit_engine_gated(monkeypatch):
    monkeypatch.delenv("HYPERSMART_EXIT_ENGINE", raising=False)
    off = decide_position_exit(side="LONG", entry_price=100, current_price=101.5, peak_price=101.5, atr_abs=1.0, age_sec=60)
    assert off["action"] == "HOLD" and off["reason"] == "EXIT_ENGINE_OFF"
    monkeypatch.setenv("HYPERSMART_EXIT_ENGINE", "1")
    on = decide_position_exit(side="LONG", entry_price=100, current_price=101.5, peak_price=101.5, atr_abs=1.0, age_sec=60)
    assert on["action"] == "PARTIAL_CLOSE"
