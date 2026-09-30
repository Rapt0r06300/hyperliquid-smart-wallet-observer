from hl_observer.scoring.leader_quality_gate import (
    LeaderQualityConfig,
    assess_leader_quality,
    select_smart_money,
)
from hl_observer.backtest.ledger_replay_v9 import replay_ledger_v9, ReplayConfig


# ---------- leader quality gate ----------

def test_good_leader_qualifies():
    q = assess_leader_quality("0xGOOD", [30, 25, 40, -10, 35])  # 80% win, mean +24
    assert q.qualified is True and q.net_edge_bps > 0 and "SMART_MONEY" in q.reasons


def test_losing_leader_is_rejected():
    q = assess_leader_quality("0xBAD", [-20, -30, 10, -25, -40, -15, 5, -50])  # winrate faible, mean négatif
    assert q.qualified is False
    assert any("WINRATE" in r or "MEAN_MOVE" in r for r in q.reasons)


def test_too_few_trips_rejected():
    q = assess_leader_quality("0xNEW", [50, 60])  # 2 < 3
    assert q.qualified is False and any("TOO_FEW_TRIPS" in r for r in q.reasons)


def test_one_big_win_flagged():
    cfg = LeaderQualityConfig(min_winrate=0.5)
    q = assess_leader_quality("0xLUCKY", [500, -5, 3, -4], config=cfg)  # un trade porte tout
    assert q.qualified is False and "ONE_BIG_WIN_RISK" in q.reasons


def test_select_smart_money_returns_only_qualified_ranked():
    wallets = {
        "0xA": [30, 25, 40, 35, 20],       # qualifie, edge fort
        "0xB": [15, 18, 14, 20, 13],       # qualifie, edge moindre
        "0xC": [-20, -30, 10, -25, -40],   # rejeté
    }
    sel = select_smart_money(wallets)
    assert [s.wallet for s in sel] == ["0xA", "0xB"]  # 0xC exclu, triés par edge net
    assert all(s.qualified for s in sel)


# ---------- ledger replay V9 ----------

def _row(ts, wallet, coin, side, action, price):
    return {
        "timestamp_ms": ts, "wallet_address": wallet, "coin": coin,
        "leader_side": side, "leader_action": action, "leader_price": price,
        "signal_age_ms": 2000,
    }


def test_replay_pairs_open_close_and_computes_pnl():
    rows = [
        _row(1, "0xA", "BTC", "LONG", "OPEN_LONG", 100.0),
        _row(2, "0xA", "BTC", "LONG", "CLOSE_LONG", 110.0),   # +10% long
        _row(3, "0xB", "SOL", "SHORT", "OPEN_SHORT", 200.0),
        _row(4, "0xB", "SOL", "SHORT", "CLOSE_SHORT", 180.0),  # prix baisse -> short gagne
        _row(5, "0xC", "XYZ:TSLA", "LONG", "OPEN_LONG", 400.0),  # exotique -> skip
    ]
    r = replay_ledger_v9(rows, config=ReplayConfig(notional_usdt=50.0))
    assert r.matched_round_trips == 2
    assert r.skipped_exotic == 1
    assert r.gross_pnl_usdt > 0          # deux gagnants bruts
    assert r.wins_gross == 2
