"""DATA-1 — contrat des garde-fous qualité données (fat-finger, gap, contradiction).

Prouve: donnée douteuse -> NO_TRADE avec raison précise ; donnée insuffisante ->
jamais "OK" par défaut (honnêteté). Module pur, déterministe.
"""

from __future__ import annotations

from hl_observer.data_quality.guards import (
    cross_source_agreement,
    evaluate_data_quality,
    price_sanity,
    staleness,
)


def test_price_sanity_accepts_normal_and_rejects_fat_finger():
    good = price_sanity("HYPE", 100.0, [99.0, 100.0, 101.0])
    assert good["ok"] and good["verdict"] == "OK"
    fat = price_sanity("HYPE", 130.0, [99.0, 100.0, 101.0], max_dev_pct=10.0)
    assert not fat["ok"] and fat["verdict"] == "PRICE_OUTLIER_FAT_FINGER"


def test_price_sanity_honest_on_missing_data():
    assert price_sanity("HYPE", -1.0, [100.0, 101.0, 102.0])["verdict"] == "PRICE_INVALID"
    # <3 points d'historique -> INSUFFICIENT, jamais "OK"
    assert price_sanity("HYPE", 100.0, [100.0])["verdict"] == "INSUFFICIENT_HISTORY"


def test_staleness_detects_gap_and_clock_skew():
    assert staleness("HYPE", 1_000_000, 1_010_000, max_gap_ms=30_000)["ok"] is True
    assert staleness("HYPE", 1_000_000, 1_100_000, max_gap_ms=30_000)["verdict"] == "DATA_GAP_TOO_OLD"
    assert staleness("HYPE", 1_100_000, 1_000_000)["verdict"] == "CLOCK_SKEW"  # futur = horloge décalée


def test_cross_source_agreement_flags_contradiction():
    ok = cross_source_agreement("HYPE", {"hl": 100.0, "px": 100.5}, max_disagreement_pct=1.5)
    assert ok["ok"] and ok["verdict"] == "OK"
    bad = cross_source_agreement("HYPE", {"hl": 100.0, "px": 105.0}, max_disagreement_pct=1.5)
    assert not bad["ok"] and bad["verdict"] == "SOURCES_CONTRADICT"
    assert cross_source_agreement("HYPE", {})["verdict"] == "NO_SOURCE"       # honnête
    assert cross_source_agreement("HYPE", {"hl": 100.0})["verdict"] == "SINGLE_SOURCE"


def test_evaluate_combined_verdict_is_no_trade_on_any_failure():
    # tout bon -> tradeable
    ok = evaluate_data_quality("HYPE", 100.0, [99.0, 100.0, 101.0], {"hl": 100.0, "px": 100.2}, 1_000_000, 1_005_000)
    assert ok["tradeable"] is True and ok["verdict"] == "OK"
    # un fat-finger -> NO_TRADE avec raison
    bad = evaluate_data_quality("HYPE", 200.0, [99.0, 100.0, 101.0], {"hl": 100.0, "px": 100.2}, 1_000_000, 1_005_000)
    assert bad["tradeable"] is False
    assert bad["verdict"] == "NO_TRADE_DATA_QUALITY"
    assert "PRICE_OUTLIER_FAT_FINGER" in bad["reasons"]
