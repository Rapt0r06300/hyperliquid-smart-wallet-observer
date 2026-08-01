"""[LAB α item 14] Découpage IS/OOS/FORWARD par ÉPISODES INDIVISIBLES : aucun épisode (position epoch,
métaordre/TWAP, Lead-Lag, cross-venue) ne traverse deux segments. 0 réseau.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.mega_cablage.replay_driver import (   # noqa: E402
    episodes_indivisibles, separer_par_episodes, separer_temporel)

T = 1_700_000_000_000


def test_un_episode_explicite_reste_entier_dans_un_seul_segment():
    # 3 métaordres explicites de tailles inégales ; aucun ne doit être coupé entre segments.
    evs = []
    for mo, taille in (("MO1", 6), ("MO2", 3), ("MO3", 1)):
        for i in range(taille):
            evs.append({"metaorder_id": mo, "coin": "BTC", "vault": "A", "signe": 1,
                        "ts_ms": T + len(evs) * 1000})
    segs = separer_par_episodes(evs, fractions=(0.6, 0.2, 0.2))
    # chaque metaorder_id est ENTIÈREMENT dans un seul segment.
    for mo in ("MO1", "MO2", "MO3"):
        presence = [lab for lab, lst in segs.items() if any(e["metaorder_id"] == mo for e in lst)]
        assert len(presence) == 1, (mo, presence)
    # rien n'est perdu ni dupliqué.
    assert sum(len(v) for v in segs.values()) == len(evs)


def test_run_contigu_meme_direction_est_un_episode():
    # 5 events même (vault, coin, direction) contigus = 1 épisode ; un flip de direction en ouvre un autre.
    evs = [{"coin": "ETH", "vault": "V", "signe": 1, "ts_ms": T + i * 1000} for i in range(5)]
    evs += [{"coin": "ETH", "vault": "V", "signe": -1, "ts_ms": T + (5 + i) * 1000} for i in range(5)]
    eps = episodes_indivisibles(evs)
    assert len(eps) == 2 and len(eps[0]) == 5 and len(eps[1]) == 5


def test_trou_temporel_coupe_l_episode():
    evs = [{"coin": "BTC", "vault": "V", "signe": 1, "ts_ms": T + i * 1000} for i in range(4)]
    evs += [{"coin": "BTC", "vault": "V", "signe": 1, "ts_ms": T + 10_000_000 + i * 1000} for i in range(4)]
    eps = episodes_indivisibles(evs, gap_ms=3_600_000)
    assert len(eps) == 2                                   # le trou > gap_ms sépare deux épisodes


def test_contre_exemple_le_split_par_compte_couperait_l_episode():
    # un gros épisode de 10 events + un petit de 2 : le split par COMPTE (0.6) couperait le gros à l'event 7.
    gros = [{"metaorder_id": "BIG", "coin": "BTC", "vault": "A", "signe": 1, "ts_ms": T + i * 1000}
            for i in range(10)]
    petit = [{"metaorder_id": "SMALL", "coin": "BTC", "vault": "A", "signe": 1, "ts_ms": T + (10 + i) * 1000}
             for i in range(2)]
    evs = gros + petit
    # le split temporel NAÏF met une frontière au milieu du gros épisode (fuite) ...
    naif = separer_temporel(evs, fractions=(0.6, 0.2, 0.2))
    big_naif = [lab for lab, lst in naif.items() if any(e.get("metaorder_id") == "BIG" for e in lst)]
    assert len(big_naif) >= 2                              # l'épisode BIG est ÉCLATÉ sur plusieurs segments
    # ... alors que le split par ÉPISODES garde BIG entier.
    parep = separer_par_episodes(evs, fractions=(0.6, 0.2, 0.2))
    big_ep = [lab for lab, lst in parep.items() if any(e.get("metaorder_id") == "BIG" for e in lst)]
    assert len(big_ep) == 1
