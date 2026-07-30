"""P3.2 — carnet de profondeur Binance : snapshot + diffs contigus, DESYNC deny-by-default."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import binance_depth_book as D  # noqa: E402


def _book():
    b = D.BinanceDepthBook()
    b.appliquer_snapshot(last_update_id=100, bids=[[10.0, 1.0], [9.0, 2.0]], asks=[[11.0, 1.0], [12.0, 3.0]])
    return b


def test_diff_avant_snapshot_exige_un_snapshot():
    b = D.BinanceDepthBook()
    assert b.appliquer_diff(U=1, u=2).status == D.SNAPSHOT_REQUIS


def test_diff_anterieur_est_ignore():
    b = _book()
    assert b.appliquer_diff(U=90, u=100).status == D.IGNORE_ANTERIEUR
    assert b.last_update_id == 100


def test_premier_diff_doit_encadrer_snapshot_plus_un():
    b = _book()
    r = b.appliquer_diff(U=101, u=105, bids=[[10.0, 5.0]], asks=[[11.0, 0.0]])
    assert r.status == D.APPLIQUE and b.last_update_id == 105
    assert b.bids[10.0] == 5.0 and 11.0 not in b.asks       # qty 0 supprime le niveau


def test_premier_diff_hors_borne_desync():
    b = _book()
    r = b.appliquer_diff(U=103, u=108)                        # 101 pas dans [103,108]
    assert r.status == D.DESYNC_PREMIER and b.desync and not b.exploitable()


def test_gap_de_contiguite_desync():
    b = _book()
    assert b.appliquer_diff(U=101, u=105).status == D.APPLIQUE
    r = b.appliquer_diff(U=107, u=110)                        # attendu U=106
    assert r.status == D.DESYNC_GAP and not b.exploitable()


def test_apres_desync_le_carnet_refuse_jusqu_au_resnapshot():
    b = _book()
    b.appliquer_diff(U=101, u=105)
    b.appliquer_diff(U=107, u=110)                            # DESYNC
    assert b.appliquer_diff(U=111, u=112).status == D.DESYNC  # refuse
    # ré-ancrage par un nouveau snapshot
    b.appliquer_snapshot(last_update_id=200, bids=[[10.0, 1.0]], asks=[[11.0, 1.0]])
    assert b.exploitable() and b.appliquer_diff(U=201, u=202, bids=[[10.0, 4.0]]).status == D.APPLIQUE


def test_suite_contigue_maintient_le_carnet():
    b = _book()
    assert b.appliquer_diff(U=101, u=103, bids=[[9.5, 1.0]]).status == D.APPLIQUE
    assert b.appliquer_diff(U=104, u=106, asks=[[10.5, 2.0]]).status == D.APPLIQUE
    assert b.best_bid() == 10.0 and b.best_ask() == 10.5 and b.mid() == 10.25


def test_futures_utilise_pu_pour_la_contiguite():
    b = D.BinanceDepthBook(futures=True)
    b.appliquer_snapshot(last_update_id=100, bids=[[10.0, 1.0]], asks=[[11.0, 1.0]])
    assert b.appliquer_diff(U=101, u=105, pu=100).status == D.APPLIQUE
    assert b.appliquer_diff(U=106, u=108, pu=105).status == D.APPLIQUE     # pu == u précédent
    r = b.appliquer_diff(U=109, u=110, pu=999)                             # pu incohérent
    assert r.status == D.DESYNC_GAP


def test_carnet_desync_ne_publie_pas_de_prix():
    b = _book()
    b.appliquer_diff(U=103, u=108)                            # DESYNC_PREMIER
    assert b.best_bid() is None and b.best_ask() is None and b.mid() is None
    assert b.snapshot()["exploitable"] is False


def test_snapshot_trie_les_niveaux():
    b = _book()
    snap = b.snapshot(depth=2)
    assert snap["bids"][0][0] == 10.0 and snap["asks"][0][0] == 11.0
    assert snap["best_bid"] == 10.0 and snap["mid"] == 10.5
