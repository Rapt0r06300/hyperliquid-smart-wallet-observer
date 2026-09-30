"""Corpus growth: refus -> échantillons shadow honnêtes (IA ingestion).

Vérifie qu'un refus mesurable devient un sample labellisé par le PnL réel qu'il
aurait fait, qu'un refus non mesurable est ignoré (jamais fabriqué), et que le
"bon refus" (aurait perdu) et le "mauvais refus" (aurait gagné) sont distingués.
"""

from __future__ import annotations

from hl_observer.ml.refused_shadow_extract import (
    SHADOW_CONTEXT,
    rows_outcomes_from_refusals,
    summarize_refusal_corpus,
)


def _refusal(coin, side, price, ts_ms, **feats):
    ev = {
        "status": "REJECT_NO_TRADE",
        "paper_action_type": "NO_TRADE",
        "coin": coin,
        "leader_side": side,
        "leader_price": price,
        "observed_at_ms": ts_ms,
        "reason": "EDGE_TOO_SMALL",
    }
    ev.update(feats)
    return ev


def _marks(coin, base_ts_sec, prices, step_sec=60.0):
    return {coin: [(base_ts_sec + i * step_sec, p) for i, p in enumerate(prices)]}


def test_bad_refusal_would_have_won_is_labeled_positive():
    ts = 1_000_000
    marks = _marks("HYPE", ts / 1000.0, [100.0, 100.5, 101.2, 102.0])
    ev = _refusal("HYPE", "LONG", 100.0, ts, edge_remaining_bps=40, signal_age_ms=1000, liquidity_score=0.8, leader_wallets_count=3)
    rows, outcomes = rows_outcomes_from_refusals([ev], marks, horizon_min=10.0, cost_bps=12.0)
    assert len(rows) == 1 and len(outcomes) == 1
    assert rows[0].context == SHADOW_CONTEXT
    assert outcomes[0].realized_net_pnl_usdc > 0  # le prix est monté: refus = manqué un gain
    assert rows[0].features["net_edge_bps"] == 40.0


def test_good_refusal_would_have_lost_is_labeled_negative():
    ts = 2_000_000
    marks = _marks("MON", ts / 1000.0, [100.0, 99.3, 98.5, 97.0])
    ev = _refusal("MON", "LONG", 100.0, ts, edge_remaining_bps=12, liquidity_score=0.3)
    rows, outcomes = rows_outcomes_from_refusals([ev], marks, horizon_min=10.0)
    assert len(outcomes) == 1
    assert outcomes[0].realized_net_pnl_usdc < 0  # le prix a chuté: refus = bien évité


def test_unmeasurable_refusal_is_skipped_never_fabricated():
    ts = 3_000_000
    # aucun mark postérieur à la décision -> non mesurable
    marks = {"BTC": [(ts / 1000.0 - 600, 50_000.0)]}
    ev = _refusal("BTC", "LONG", 50_000.0, ts)
    rows, outcomes = rows_outcomes_from_refusals([ev], marks)
    assert rows == [] and outcomes == []
    # refus sans prix / sans side -> ignoré aussi
    no_price = _refusal("BTC", "LONG", 0.0, ts)
    no_side = _refusal("BTC", "", 50_000.0, ts)
    r2, o2 = rows_outcomes_from_refusals([no_price, no_side], {"BTC": [(ts/1000.0 + 60, 50_100.0)]})
    assert r2 == []


def test_non_refusal_events_are_ignored():
    ts = 4_000_000
    marks = _marks("HYPE", ts / 1000.0, [100.0, 101.0])
    accepted = {"paper_action_type": "OPEN", "status": "LOCAL_REPLAY", "coin": "HYPE", "leader_side": "LONG", "leader_price": 100.0, "observed_at_ms": ts}
    rows, outcomes = rows_outcomes_from_refusals([accepted], marks)
    assert rows == []


def test_summary_counts_wins_and_losses():
    ts = 5_000_000
    marks = {}
    marks.update(_marks("A", ts / 1000.0, [100.0, 103.0]))
    marks.update(_marks("B", ts / 1000.0, [100.0, 96.0]))
    evs = [
        _refusal("A", "LONG", 100.0, ts, edge_remaining_bps=30, liquidity_score=0.7),
        _refusal("B", "LONG", 100.0, ts, edge_remaining_bps=20, liquidity_score=0.5),
    ]
    rows, outcomes = rows_outcomes_from_refusals(evs, marks, horizon_min=10.0)
    summary = summarize_refusal_corpus(rows, outcomes)
    assert summary["shadow_samples"] == 2
    assert summary["would_have_won"] == 1
    assert summary["would_have_lost"] == 1
