"""H17 : une vague se repère avec le seul passé, et l'entrée attend la fin de la vague."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import goal2_absorption_liquidations as A  # noqa: E402

H = 3_600_000


def _liq(heures_usd: dict[int, float], n: int = 800) -> pd.DataFrame:
    return pd.DataFrame([{"coin": "BTC", "heure_ms": k * H, "long_usd": heures_usd.get(k, 10_000.0), "short_usd": 0.0}
                         for k in range(n)])


def test_une_vague_se_mesure_sur_les_heures_passees() -> None:
    liq = _liq({790: 2_000_000.0})
    vg = A.vagues(liq, 760 * H, 800 * H)
    assert list(vg["heure_ms"]) == [790 * H] and int(vg["sens_absorbeur"].iloc[0]) == 1   # longs liquidés : on achète


def test_sous_le_seuil_absolu_ce_n_est_pas_une_vague() -> None:
    assert A.vagues(_liq({790: 900_000.0}), 760 * H, 800 * H).empty


def test_l_entree_attend_la_fin_de_la_vague() -> None:
    vg = pd.DataFrame([{"coin": "BTC", "heure_ms": 10 * H, "sens_absorbeur": 1, "liquide_usd": 2e6}])
    fills = pd.DataFrame([{"vault": "a", "ts_ms": 10 * H + 60_000, "coin": "BTC", "px": 100.0, "sz": 50.0, "signe": 1,
                           "dir": "Open Long", "start_position": 0.0, "crossed": True, "fee": 0.0, "closed_pnl": 0.0,
                           "tid": 1}])
    ev = A.evenements(fills, vg)
    assert bool(ev["absorbe"].iloc[0]) and int(ev["entree_ms"].iloc[0]) >= 11 * H


def test_le_suiveur_retient_l_ouverture_dans_le_sens_de_la_vague() -> None:
    """H19 : longs liquidés (ventes forcées) -> le SUIVEUR est celui qui VEND, pas celui qui achète."""
    vg = pd.DataFrame([{"coin": "BTC", "heure_ms": 10 * H, "sens_absorbeur": 1, "liquide_usd": 2e6}])
    base = {"vault": "a", "ts_ms": 10 * H + 60_000, "coin": "BTC", "px": 100.0, "sz": 50.0, "start_position": 0.0,
            "crossed": True, "fee": 0.0, "closed_pnl": 0.0}
    achat = pd.DataFrame([{**base, "signe": 1, "dir": "Open Long", "tid": 1}])
    vente = pd.DataFrame([{**base, "signe": -1, "dir": "Open Short", "tid": 2}])
    assert not bool(A.evenements(achat, vg, sens_cible="suiveur")["absorbe"].iloc[0])
    assert bool(A.evenements(vente, vg, sens_cible="suiveur")["absorbe"].iloc[0])
    assert bool(A.evenements(achat, vg, sens_cible="absorbeur")["absorbe"].iloc[0])     # H17 inchangée
