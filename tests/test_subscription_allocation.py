"""Tests du Lot 1 — allocation intelligente des slots WS userFills (pur)."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection.subscription_universe import (  # noqa: E402
    QUOTA_USERS, allouer_slots_ws, score_activite_leader,
    selectionner_challengers_ucb, slots_a_liberer,
)

NOW = 1_800_000_000_000


def test_score_actif_superieur_a_inactif():
    actif = {"fills_par_min": 10.0, "dernier_fill_ms": NOW - 1000, "twap_actif": True,
             "notional_ouvert_usd": 50_000}
    inactif = {"fills_par_min": 0.0, "dernier_fill_ms": NOW - 3_600_000}
    assert score_activite_leader(actif, now_ms=NOW) > score_activite_leader(inactif, now_ms=NOW)


def test_snapshot_only_jamais_en_ws():
    st = {"fills_par_min": 999.0, "snapshot_only": True}
    assert score_activite_leader(st, now_ms=NOW) == float("-inf")


def test_recence_decroit_avec_age():
    recent = {"dernier_fill_ms": NOW - 1000}
    vieux = {"dernier_fill_ms": NOW - 600_000}
    assert score_activite_leader(recent, now_ms=NOW) > score_activite_leader(vieux, now_ms=NOW)


def test_ucb_explore_les_jamais_essayes_dabord():
    cands = ["0xA", "0xB", "0xC"]
    stats = {
        "0xA": {"essais": 100, "fills_observes": 5},   # faible reward, bien explore
        "0xB": {"essais": 0},                           # jamais essaye -> infini
        "0xC": {"essais": 100, "fills_observes": 2},
    }
    choisis = selectionner_challengers_ucb(cands, stats, slots=1)
    assert choisis == ["0xB"]


def test_ucb_prefere_meilleur_reward_a_essais_egaux():
    cands = ["0xA", "0xB"]
    stats = {"0xA": {"essais": 50, "fills_observes": 40}, "0xB": {"essais": 50, "fills_observes": 1}}
    assert selectionner_challengers_ucb(cands, stats, slots=1) == ["0xA"]


def test_allocation_core_challengers_poll():
    leaders = [f"0x{i:02d}" for i in range(15)]
    stats = {}
    # 0x00..0x07 tres actifs (CORE), 0x08 snapshot_only (poll), reste inactif
    for i in range(8):
        stats[f"0x{i:02d}"] = {"fills_par_min": 20 - i, "dernier_fill_ms": NOW - 1000}
    stats["0x08"] = {"fills_par_min": 999, "snapshot_only": True}
    alloc = allouer_slots_ws(leaders, stats, now_ms=NOW, user_slots=10, core_slots=8, challenger_slots=2)
    # les 8 plus actifs en CORE
    assert set(alloc["ws_core"]) == {f"0x{i:02d}" for i in range(8)}
    assert len(alloc["ws_challengers"]) == 2
    assert len(alloc["ws"]) == 10 <= QUOTA_USERS
    # snapshot_only jamais en WS, et present dans poll
    assert "0x08" not in alloc["ws"]
    assert "0x08" in alloc["poll"]
    assert "0x08" in alloc["snapshot_only"]
    # partition : ws + poll = tous les leaders uniques
    assert set(alloc["ws"]) | set(alloc["poll"]) == set(leaders)
    assert not (set(alloc["ws"]) & set(alloc["poll"]))


def test_slots_a_liberer():
    leaders = ["0x01", "0x02", "0x03"]
    stats = {"0x01": {"fills_par_min": 5}, "0x02": {"fills_par_min": 3}}
    alloc = allouer_slots_ws(leaders, stats, now_ms=NOW, user_slots=2, core_slots=2, challenger_slots=0)
    # precedemment 0x09 avait un slot WS ; il n'est plus retenu -> a liberer
    a_liberer = slots_a_liberer(["0x01", "0x09"], alloc)
    assert "0x09" in a_liberer and "0x01" not in a_liberer
