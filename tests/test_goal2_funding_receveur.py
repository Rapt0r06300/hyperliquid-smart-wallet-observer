"""H21 : seuil causal (passe seul), sens receveur, et funding manquant = mesure refusée (jamais 0 favorable)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import goal2_funding_receveur as F  # noqa: E402

H = 3_600_000


def _funding(n_h: int, taux: float, extreme_a: int, valeur: float) -> pd.DataFrame:
    r = [taux] * n_h
    r[extreme_a] = valeur
    return pd.DataFrame({"coin": "BTC", "ts_ms": [k * H for k in range(n_h)], "funding": r})


def test_long_quand_le_taux_est_negatif_extreme_recoit_le_funding() -> None:
    fund = _funding(900, 0.00001, 800, -0.0005)          # taux tres negatif juste avant l'entree
    ev = pd.DataFrame({"coin": ["BTC"], "entree_ms": [800 * H + 1], "sens_position": [1]})
    m = F.marquer(ev, fund)
    assert bool(m["extreme"].iloc[0]) and bool(m["receveur"].iloc[0])
    assert m["funding_bps"].iloc[0] == -1e4 * 0.00001 * 24      # les 24 reglements suivants (taux normaux) se paient


def test_funding_manquant_sur_la_tenue_refuse_la_mesure() -> None:
    fund = _funding(810, 0.00001, 800, -0.0005)          # seulement 9 h de taux apres l'entree
    ev = pd.DataFrame({"coin": ["BTC"], "entree_ms": [800 * H + 1], "sens_position": [1]})
    assert np.isnan(F.marquer(ev, fund)["funding_bps"].iloc[0])
