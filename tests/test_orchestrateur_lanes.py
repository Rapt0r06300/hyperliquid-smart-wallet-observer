"""Tests de l'orchestration d'allocation multi-sources (#44-50)."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import orchestrateur_lanes as O  # noqa: E402


def test_recommander_nb_lanes():
    assert O.recommander_nb_lanes(0) == 1
    assert O.recommander_nb_lanes(25, slots_par_lane=10) == 3
    assert O.recommander_nb_lanes(1000, slots_par_lane=10, max_lanes=8) == 8


def test_orchestrer_repartition():
    # 25 leaders scorés décroissant ; WS cap = 2 lanes × 5 = 10, poll cap = 10, pas de nœud
    classement = [(f"0x{i:02d}", 100.0 - i) for i in range(25)]
    r = O.orchestrer(classement, lanes_ws=2, slots_par_lane=5, poll_capacite=10, node_actif=False)
    assert r["resume"]["ws"] == 10
    assert r["resume"]["poll"] == 10
    assert r["resume"]["non_couverts"] == 5      # 25 - 10 - 10
    assert r["capacite_ws"] == 10
    # les 10 meilleurs sont en WS, répartis en 2 lanes disjointes
    lane0 = O.leaders_par_lane(r, 0)
    lane1 = O.leaders_par_lane(r, 1)
    assert len(lane0) == 5 and len(lane1) == 5
    assert set(lane0) & set(lane1) == set()       # disjoint


def test_noeud_filet():
    classement = [(f"0x{i:02d}", 50.0 - i) for i in range(15)]
    r = O.orchestrer(classement, lanes_ws=1, slots_par_lane=5, poll_capacite=5, node_actif=True)
    assert r["resume"]["ws"] == 5 and r["resume"]["poll"] == 5
    assert r["resume"]["node"] == 5 and r["resume"]["non_couverts"] == 0


def test_seuil_actif_exclut_inactifs_du_ws():
    classement = [("0xa", 10.0), ("0xb", 0.0), ("0xc", 0.0)]
    r = O.orchestrer(classement, lanes_ws=2, slots_par_lane=5, poll_capacite=10, seuil_actif=0.0)
    assert r["assignations"]["0xa"]["source"] == "ws"
    assert r["assignations"]["0xb"]["source"] == "poll"   # score 0 => pas de slot WS
