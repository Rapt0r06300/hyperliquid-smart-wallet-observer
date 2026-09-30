"""
Tests du consensus temps réel (firehose → consensus en mémoire, zéro REST).

100% pur, déterministe, sans réseau. READ-ONLY / PAPER-ONLY.
"""

from __future__ import annotations

from hyper_smart_observer.dydx_v4.stream_consensus import (
    StreamFillWindow,
    StreamSignal,
    build_cluster_signal,
    detect_consensus,
    side_to_direction,
)


def test_side_to_direction():
    assert side_to_direction("BUY") == "LONG"
    assert side_to_direction("SELL") == "SHORT"
    assert side_to_direction("buy") == "LONG"


def test_window_add_and_prune():
    w = StreamFillWindow(window_ms=4000)
    w.add("w1", 0, "LONG", 500)
    w.add("w2", 0, "LONG", 1000)
    w.add("w3", 0, "LONG", 5000)
    assert len(w) == 3
    w.prune(now_ms=5000)        # cutoff = 1000 → le ts 500 sort
    assert len(w) == 2


def test_window_ignores_incomplete():
    w = StreamFillWindow()
    w.add("", 0, "LONG", 1)        # pas d'owner
    w.add("w1", None, "LONG", 1)   # pas de clob
    assert len(w) == 0


def test_detect_consensus_threshold():
    items = [
        (1000, "w1", 0, "LONG"),
        (1001, "w2", 0, "LONG"),
        (1002, "w3", 0, "LONG"),
        (1003, "w1", 0, "LONG"),   # doublon → compte une fois
    ]
    sigs = detect_consensus(items, min_wallets=3)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.clob_pair_id == 0 and s.direction == "LONG" and s.wallet_count == 3
    assert s.freshest_ts == 1003
    # Seuil plus haut → aucun consensus
    assert detect_consensus(items, min_wallets=4) == []


def test_detect_consensus_separates_market_and_direction():
    items = [
        (1, "w1", 0, "LONG"), (2, "w2", 0, "LONG"),
        (3, "w3", 1, "SHORT"), (4, "w4", 1, "SHORT"),
    ]
    sigs = detect_consensus(items, min_wallets=2)
    keys = {(s.clob_pair_id, s.direction) for s in sigs}
    assert keys == {(0, "LONG"), (1, "SHORT")}


def test_detect_consensus_with_market_names():
    # Chemin SANS node: la clé est un nom de marché (WS public), pas un ID node.
    items = [
        (1, "w1", "BTC-USD", "LONG"),
        (2, "w2", "BTC-USD", "LONG"),
        (3, "w3", "BTC-USD", "LONG"),
    ]
    sigs = detect_consensus(items, min_wallets=3)
    assert len(sigs) == 1
    assert sigs[0].clob_pair_id == "BTC-USD" and sigs[0].wallet_count == 3


def test_build_cluster_signal_origin_stream():
    sig = StreamSignal(clob_pair_id=0, direction="LONG",
                       wallets=["w1", "w2", "w3"], freshest_ts=5000, oldest_ts=4000)
    c = build_cluster_signal(sig, "BTC-USD", 60000.0, now_ms=5500)
    assert c.market_id == "BTC-USD" and c.side == "LONG"
    assert c.wallet_count == 3 and len(c.participating_wallets) == 3
    assert c.signal_age_ms == 500 and c.is_fresh is True
    assert c.origin == "stream"
    assert c.avg_entry_price == 60000.0
