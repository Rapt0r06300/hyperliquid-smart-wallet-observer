"""Distillation HFT: microprice + markout/toxicité (anti adverse-selection)."""

from __future__ import annotations

from hl_observer.signals.microprice_toxicity import (
    ToxicityTracker, entry_price_refusal, markout_bps, microprice,
    toxicity_adjusted_min_edge_bps,
)


def test_microprice_leans_toward_thin_side():
    mid = (100.0 + 100.2) / 2
    # beaucoup de bids, peu d'asks -> pression acheteuse -> microprice > mid (vers l'ask)
    mp = microprice(100.0, 100.2, bid_size=900, ask_size=100)
    assert mp > mid
    # équilibré -> ~ mid
    assert abs(microprice(100.0, 100.2, 500, 500) - mid) < 1e-6


def test_markout_sign_is_trade_relative():
    assert markout_bps("LONG", 100.0, 100.5) == 50.0     # LONG, prix monte = favorable
    assert markout_bps("LONG", 100.0, 99.5) == -50.0     # LONG, prix baisse = adverse
    assert markout_bps("SHORT", 100.0, 99.5) == 50.0     # SHORT, prix baisse = favorable


def test_toxicity_ewma_accumulates_adverse():
    t = ToxicityTracker(alpha=0.5)
    t.record_markout("MON", -20)     # adverse 20
    t.record_markout("MON", -20)     # encore adverse
    assert t.toxicity("MON") > 0
    # un marché non toxique reste à 0
    t.record_markout("BTC", 30)      # favorable -> pas de toxicité
    assert t.toxicity("BTC") == 0.0


def test_toxicity_raises_required_edge():
    base = toxicity_adjusted_min_edge_bps(28.0)
    tox = toxicity_adjusted_min_edge_bps(28.0, volatility_bps=10, toxicity_bps=15, c_vol=0.5, c_tox=1.0)
    assert base == 28.0
    assert tox == 28.0 + 5 + 15   # + c_vol*vol + c_tox*tox


def test_entry_refused_when_microprice_already_adverse():
    # LONG voulu à 100, mais microprice déjà tombé à 99.9 (défavorable au long) au-delà du seuil
    r = entry_price_refusal(side="LONG", intended_price=100.0, micro_price=99.9, max_micro_gap_bps=5.0)
    assert r == "MICROPRICE_ALREADY_ADVERSE"
    # microprice favorable/proche -> OK
    assert entry_price_refusal(side="LONG", intended_price=100.0, micro_price=100.02, max_micro_gap_bps=5.0) == ""
