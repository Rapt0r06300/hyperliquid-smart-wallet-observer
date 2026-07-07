"""SCALE (scanner à étages) + ARB-DATA (différentiel funding cross-venue)."""

from __future__ import annotations

from hl_observer.arbitrage.cross_venue_funding import (
    compute_cross_venue_funding_edge,
    rank_cross_venue_edges,
)
from hl_observer.wallets.tiered_scanner import (
    HOT, WARM, COLD, DISCOVERY,
    apply_promotions, assign_tiers, due_for_refresh, ws_subscription_count,
)


def _scored(n):
    return {f"0x{i:02d}": float(1000 - i) for i in range(n)}


def test_ws_cap_never_exceeded():
    plans = assign_tiers(_scored(400), max_ws=10)
    assert ws_subscription_count(plans) == 10  # jamais > 10 WS (contrainte HL)
    tiers = {p.tier for p in plans}
    assert tiers == {HOT, WARM, COLD, DISCOVERY}


def test_top_scored_go_hot():
    plans = assign_tiers(_scored(50), max_ws=5)
    hot = [p.wallet for p in plans if p.tier == HOT]
    assert hot == ["0x00", "0x01", "0x02", "0x03", "0x04"]  # meilleurs scores


def test_due_for_refresh_respects_cadence_and_excludes_hot():
    plans = assign_tiers(_scored(60), max_ws=10, warm_size=20)
    now = 1_000_000
    last = {p.wallet: now for p in plans}  # tous vus à l'instant
    assert due_for_refresh(plans, last, now) == ()  # rien d'échu
    due = due_for_refresh(plans, last, now + 20_000)  # +20s: WARM (15s) échus, COLD (120s) non
    warm_wallets = {p.wallet for p in plans if p.tier == WARM}
    assert set(due) == warm_wallets
    hot_wallets = {p.wallet for p in plans if p.tier == HOT}
    assert not (set(due) & hot_wallets)  # HOT jamais en REST (il est en WS)


def test_promotion_detected_when_score_rises():
    current = {p.wallet: p.tier for p in assign_tiers(_scored(30), max_ws=5)}
    boosted = _scored(30)
    boosted["0x29"] = 99_999.0  # le dernier devient le meilleur
    moves = apply_promotions(current, boosted, max_ws=5)
    assert moves["0x29"]["to"] == HOT
    assert moves["0x29"]["direction"] == "PROMOTED"


def test_cross_venue_funding_edge_pays_the_spread_not_absolute():
    # HL +5bps/h, Bybit +1bps/h → on short HL (encaisse 5), long Bybit (paie 1), écart 4
    e = compute_cross_venue_funding_edge("HYPE", {"hl": 5.0, "bybit": 1.0}, round_trip_cost_bps=1.0)
    assert e is not None and e.reason == "CROSS_VENUE_FUNDING_EDGE"
    assert e.short_venue == "hl" and e.long_venue == "bybit"
    assert e.gross_diff_bps_per_hour == 4.0
    assert e.net_edge_bps_per_hour == 3.0  # 4 - 1 de coûts
    assert e.real_execution is False


def test_cross_venue_rejects_thin_edge_and_single_venue():
    thin = compute_cross_venue_funding_edge("BTC", {"hl": 2.0, "bybit": 1.8}, round_trip_cost_bps=4.0)
    assert thin.reason == "NET_EDGE_TOO_SMALL_AFTER_COSTS"
    assert compute_cross_venue_funding_edge("BTC", {"hl": 5.0}) is None  # une seule venue


def test_rank_cross_venue_edges_orders_by_net():
    ranked = rank_cross_venue_edges({
        "A": {"hl": 8.0, "bybit": 1.0},
        "B": {"hl": 3.0, "bybit": 2.0},   # écart 1, sous coûts → exclu
        "C": {"hl": 10.0, "okx": 2.0},
    }, round_trip_cost_bps=2.0, min_net_edge_bps_per_hour=1.0)
    coins = [e.coin for e in ranked]
    assert coins == ["C", "A"]  # C (net 6) avant A (net 5), B exclu
