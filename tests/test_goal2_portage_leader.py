"""L11 : signes du funding et causalité, sur des données dont la réponse est connue."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import goal2_commun as G  # noqa: E402
import goal2_portage_leader as L  # noqa: E402

H = G.HEURE_MS


def _donnees(taux: float, n: int = 400):
    t = np.arange(n, dtype=np.int64) * H
    bougies = pd.DataFrame({"coin": "X", "t_ms": t, "o": 100.0, "c": 100.0})
    funding = pd.DataFrame({"coin": "X", "ts_ms": t + 1, "funding": taux})       # publié juste après l'heure
    return bougies, funding


def _ev(sens: int, heure: int):
    return pd.DataFrame([{"vault": "v", "coin": "X", "dernier_ms": heure * H - 120_000, "sens_position": sens}])


def test_un_short_encaisse_quand_les_longs_paient() -> None:
    b, f = _donnees(0.0001)                                   # +1 bps par heure : les longs paient
    s = L.series_par_coin(b, f)
    df = L.mesurer(_ev(-1, 200), s, h=72, latence_ms=120_000, debut=0, fin=400 * H)
    assert len(df) == 1 and abs(df["funding"].iloc[0] - 72.0) < 1e-6 and df["prix"].iloc[0] == 0.0
    assert abs(df["exces"].iloc[0]) < 1e-9                    # un jumeau du même coin porte pareil : 0 d'excès


def test_un_long_n_est_pas_copie_quand_le_funding_connu_ne_le_paie_pas() -> None:
    b, f = _donnees(0.0001)
    assert L.mesurer(_ev(+1, 200), L.series_par_coin(b, f), h=72, latence_ms=120_000, debut=0, fin=400 * H).empty


def test_la_decision_ne_lit_pas_le_funding_publie_apres_l_entree() -> None:
    b, f = _donnees(-0.0001)
    f.loc[f["ts_ms"] >= 200 * H, "funding"] = 0.0005          # le régime change APRÈS l'entrée
    df = L.mesurer(_ev(+1, 200), L.series_par_coin(b, f), h=72, latence_ms=120_000, debut=0, fin=400 * H)
    assert len(df) == 1                                       # décidé sur le taux d'avant (négatif : long payé)
    assert df["funding"].iloc[0] < 0                          # et il PAIE ensuite : le résultat le dit


def test_une_fenetre_de_funding_trouee_est_refusee() -> None:
    b, f = _donnees(0.0001)
    f = f[(f["ts_ms"] < 210 * H) | (f["ts_ms"] > 240 * H)]   # 30 heures manquantes sur 72
    assert L.mesurer(_ev(-1, 200), L.series_par_coin(b, f), h=72, latence_ms=120_000, debut=0, fin=400 * H).empty
