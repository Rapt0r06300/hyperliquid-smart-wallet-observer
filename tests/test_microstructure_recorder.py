"""Tests de l'enregistreur carnet L2 + funding.

Ce module est un INSTRUMENT DE MESURE : sa seule faute possible serait de fabriquer une donnee
ou d'en laisser passer une incoherente. Les tests verifient donc surtout ce qu'il REFUSE.

Aucun ordre, aucun reseau : tout est en memoire / fichiers temporaires.
"""
from __future__ import annotations

import json

import pytest

from hl_observer.collection.microstructure_recorder import (
    STREAM_FUNDING,
    STREAM_L2,
    enabled,
    record_funding,
    record_funding_snapshot,
    record_l2,
    summarize_funding,
    summarize_l2,
)
from hl_observer.collection.research_recorder import read_stream


def _book(bids, asks):
    return {"levels": [[{"px": str(p), "sz": str(s)} for p, s in bids],
                       [{"px": str(p), "sz": str(s)} for p, s in asks]]}


# ---------------------------------------------------------------- carnet L2

def test_l2_computes_spread_depth_and_microprice():
    row = summarize_l2("BTC", _book([(100.0, 2.0), (99.0, 5.0)], [(101.0, 1.0), (102.0, 4.0)]), now_ms=1_000)
    assert row is not None
    assert row["bid"] == 100.0 and row["ask"] == 101.0
    assert row["mid"] == pytest.approx(100.5)
    assert row["spread_bps"] == pytest.approx((1.0 / 100.5) * 10_000, rel=1e-6)
    # profondeur en $ sur 5 niveaux : 100*2 + 99*5 = 695 ; 101*1 + 102*4 = 509
    assert row["bid_depth_usd"] == pytest.approx(695.0)
    assert row["ask_depth_usd"] == pytest.approx(509.0)
    # desequilibre positif = plus d'acheteurs -> le prix a tendance a monter
    assert row["imbalance"] > 0
    # micro-prix pondere par la profondeur du cote OPPOSE : (100*1 + 101*2)/3
    assert row["micro_price"] == pytest.approx((100.0 * 1.0 + 101.0 * 2.0) / 3.0)


def test_l2_refuses_crossed_or_empty_book():
    """Un carnet croise (ask <= bid) est une donnee CORROMPUE : on la jette, on ne la 'repare' pas."""
    assert summarize_l2("BTC", _book([(101.0, 1.0)], [(100.0, 1.0)])) is None   # croise
    assert summarize_l2("BTC", _book([], [(100.0, 1.0)])) is None               # pas de bid
    assert summarize_l2("BTC", _book([(100.0, 1.0)], [])) is None               # pas d'ask
    assert summarize_l2("BTC", {"levels": []}) is None
    assert summarize_l2("BTC", {}) is None
    assert summarize_l2("BTC", None) is None  # type: ignore[arg-type]


def test_l2_ignores_zero_and_garbage_levels():
    book = {"levels": [
        [{"px": "0", "sz": "5"}, {"px": "abc", "sz": "1"}, {"px": "100", "sz": "2"}],
        [{"px": "101", "sz": "0"}, {"px": "102", "sz": "3"}],
    ]}
    row = summarize_l2("ETH", book)
    assert row is not None
    assert row["bid"] == 100.0     # les niveaux a prix nul / illisibles sont ecartes
    assert row["ask"] == 102.0


# ---------------------------------------------------------------- funding

def test_funding_converts_rate_to_bps_and_apr():
    ctx = {"funding": "0.0001", "markPx": "100.5", "oraclePx": "100.0", "openInterest": "1000"}
    row = summarize_funding("HYPE", ctx)
    assert row is not None
    assert row["funding_hourly"] == pytest.approx(0.0001)
    assert row["funding_bps_hourly"] == pytest.approx(1.0)          # 0.0001 = 1 bps / heure
    assert row["funding_apr_pct"] == pytest.approx(0.0001 * 24 * 365 * 100)
    assert row["basis_bps"] == pytest.approx(50.0)                  # (100.5-100)/100 * 10000


def test_funding_refuses_missing_or_unreadable_rate():
    """Funding absent = INSUFFICIENT_DATA. On n'ecrit pas 0.0 : ce serait une donnee inventee."""
    assert summarize_funding("HYPE", {"markPx": "100"}) is None       # champ absent
    assert summarize_funding("HYPE", {"funding": "n/a"}) is None      # illisible
    assert summarize_funding("HYPE", {"funding": None}) is None
    assert summarize_funding("HYPE", None) is None  # type: ignore[arg-type]


def test_funding_zero_is_a_real_value_and_is_kept():
    """Un funding REELLEMENT nul est une information : il doit etre conserve, pas confondu avec 'absent'."""
    row = summarize_funding("BTC", {"funding": "0", "markPx": "100", "oraclePx": "100"})
    assert row is not None and row["funding_hourly"] == 0.0


# ---------------------------------------------------------------- ecriture disque

def test_records_are_written_and_reread(tmp_path):
    base = str(tmp_path)
    assert record_l2(base, "BTC", _book([(100.0, 1.0)], [(101.0, 1.0)])) is True
    assert record_funding(base, "BTC", {"funding": "0.0002", "markPx": "1", "oraclePx": "1"}) is True
    l2 = read_stream(base, STREAM_L2)
    fd = read_stream(base, STREAM_FUNDING)
    assert len(l2) == 1 and l2[0]["coin"] == "BTC" and l2[0]["spread_bps"] > 0
    assert len(fd) == 1 and fd[0]["funding_bps_hourly"] == pytest.approx(2.0)


def test_bad_data_writes_nothing(tmp_path):
    base = str(tmp_path)
    assert record_l2(base, "BTC", _book([(101.0, 1.0)], [(100.0, 1.0)])) is False   # croise
    assert record_funding(base, "BTC", {"markPx": "1"}) is False                    # pas de funding
    assert read_stream(base, STREAM_L2) == []
    assert read_stream(base, STREAM_FUNDING) == []


def test_snapshot_records_every_market_in_one_call(tmp_path):
    base = str(tmp_path)
    payload = [
        {"universe": [{"name": "BTC"}, {"name": "ETH"}, {"name": "BROKEN"}]},
        [
            {"funding": "0.0001", "markPx": "60000", "oraclePx": "60000"},
            {"funding": "-0.00005", "markPx": "3000", "oraclePx": "3000"},
            {"markPx": "1"},                       # funding manquant -> ignore
        ],
    ]
    written = record_funding_snapshot(base, payload)
    assert written == 2                            # BROKEN n'est PAS ecrit
    rows = {r["coin"]: r for r in read_stream(base, STREAM_FUNDING)}
    assert set(rows) == {"BTC", "ETH"}
    assert rows["ETH"]["funding_bps_hourly"] == pytest.approx(-0.5)   # funding negatif = les shorts paient


def test_snapshot_survives_a_malformed_payload(tmp_path):
    base = str(tmp_path)
    for bad in (None, [], [{}], "nope", [{"universe": "x"}, []]):
        assert record_funding_snapshot(base, bad) == 0
    assert read_stream(base, STREAM_FUNDING) == []


# ---------------------------------------------------------------- securite / defaut

def test_recording_is_off_by_default(monkeypatch):
    monkeypatch.delenv("HYPERSMART_RECORD_MICROSTRUCTURE", raising=False)
    assert enabled() is False
    monkeypatch.setenv("HYPERSMART_RECORD_MICROSTRUCTURE", "1")
    assert enabled() is True


def test_module_places_no_order():
    """Garde-fou no-real-trade : ce module OBSERVE et ECRIT. Aucun appel d'ACTION.

    NB : on cherche des APPELS reels, pas des sous-chaines. Chercher "sign" attraperait "signal"
    et "design" -- exactement le genre de detecteur criard qui finit par etre ignore.
    """
    import re
    from pathlib import Path

    src = Path("src/hl_observer/collection/microstructure_recorder.py").read_text(encoding="utf-8")
    interdits = [
        r"\bplace_order\b",
        r"\bcancel_order\b",
        r"\bprivate_key\b",
        r"\bmnemonic\b",
        r"\bsign_typed_data\b",
        r"\.sign\s*\(",
        r"[\"']/exchange[\"']",
        r"\brequests\.(post|put)\b",
        r"\bhttpx\.(post|put)\b",
    ]
    for motif in interdits:
        assert not re.search(motif, src), f"appel interdit dans un module d'observation : {motif}"

    # et il n'emet AUCUN appel reseau : il recoit les payloads deja recuperes en lecture seule
    assert "import requests" not in src and "import httpx" not in src
