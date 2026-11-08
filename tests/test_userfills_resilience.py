"""Tests du Lot 2 — resilience anti-perte userFills (gap-fill + dedup)."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection.userfills_resilience import (  # noqa: E402
    MAX_GAPFILL_LOOKBACK_MS, DedupFills, cle_dedup_fill, fenetre_gapfill,
)

NOW = 1_800_000_000_000


def _fill(**kw):
    base = {"vault": "0xabc", "coin": "ETH", "ts_ms": NOW - 1000, "tid": 1,
            "px": 2000.0, "sz": 1.0, "signe": 1}
    base.update(kw)
    return base


def test_gapfill_recouvre_depuis_high_water():
    f = fenetre_gapfill(NOW - 30_000, NOW, marge_ms=2000)
    assert f is not None
    start, end = f
    assert start == NOW - 30_000 - 2000  # marge de recouvrement
    assert end == NOW


def test_gapfill_borne_le_lookback():
    # high-water tres ancien -> start plancher a now - MAX_LOOKBACK, jamais avant
    f = fenetre_gapfill(NOW - 10 * MAX_GAPFILL_LOOKBACK_MS, NOW)
    assert f is not None
    start, _ = f
    assert start == NOW - MAX_GAPFILL_LOOKBACK_MS


def test_gapfill_sans_high_water():
    f = fenetre_gapfill(None, NOW)
    assert f == (NOW - MAX_GAPFILL_LOOKBACK_MS, NOW)


def test_gapfill_fenetre_vide():
    assert fenetre_gapfill(NOW, NOW, marge_ms=0) is None  # start>=end


def test_identite_stable_ws_poll():
    # meme fill vu en WS et en poll -> meme cle -> dedupliqué
    ws = _fill(source="LIVE_WS")
    poll = _fill(source="LIVE_POLL")
    assert cle_dedup_fill(ws) == cle_dedup_fill(poll)


def test_dedup_filtre_doublons():
    d = DedupFills(capacite=1000)
    a, b = _fill(tid=1), _fill(tid=2)
    nouveaux = d.filtrer_nouveaux([a, b, a, b, a])
    assert len(nouveaux) == 2
    assert d.vu_ou_marquer(a) is True       # deja vu
    assert d.vu_ou_marquer(_fill(tid=3)) is False  # nouveau


def test_dedup_cache_borne():
    d = DedupFills(capacite=3)
    for i in range(10):
        d.vu_ou_marquer(_fill(tid=i))
    assert len(d) <= 3  # borne respectee (LRU)
