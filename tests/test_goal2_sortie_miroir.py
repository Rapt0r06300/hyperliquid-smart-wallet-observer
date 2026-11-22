"""L12 : appariement ouverture -> première clôture du même côté, et signes, sur réponse connue."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import goal2_sortie_miroir as M  # noqa: E402

P = M.PAS


def _fill(ts, d, px=100.0, sz=20.0, vault="v", coin="X"):
    return {"vault": vault, "coin": coin, "ts_ms": ts, "dir": d, "px": px, "sz": sz}


def test_chaque_ouverture_sort_a_la_premiere_cloture_du_meme_cote() -> None:
    f = pd.DataFrame([_fill(0, "Open Long"), _fill(10 * P, "Close Short"), _fill(20 * P, "Close Long"),
                      _fill(30 * P, "Close Long"), _fill(5 * P, "Open Short"), _fill(40 * P, "Close Short"),
                      _fill(1, "Open Long", sz=1.0)])                    # trop petit : ignoré
    ev = M.apparier_sorties(f).sort_values("entree_ms")
    assert list(zip(ev["sens"], ev["entree_ms"], ev["sortie_ms"])) == [(1, 0, 20 * P), (-1, 5 * P, 10 * P)]


def test_rendement_dans_le_sens_et_jumeau_de_meme_duree() -> None:
    n = 2000
    t = np.arange(n, dtype=np.int64) * P
    o = 100.0 * np.ones(n)
    o[400:] = 110.0                                                    # +10 % au pas 400
    b = pd.DataFrame({"coin": "X", "t_ms": t, "o": o})
    ev = pd.DataFrame([{"vault": "v", "coin": "X", "sens": 1, "entree_ms": 390 * P, "sortie_ms": 420 * P}])
    df = M.mesurer(ev, b, debut=0, fin=n * P)
    assert len(df) == 1 and abs(df["rendement"].iloc[0] - 1000.0) < 1e-6   # il a tenu la marche : +1 000 bps
    assert df["exces"].iloc[0] > 900                                    # un jumeau au hasard ne la tient presque jamais
    ev_court = pd.DataFrame([{"vault": "v", "coin": "X", "sens": -1, "entree_ms": 390 * P, "sortie_ms": 420 * P}])
    assert M.mesurer(ev_court, b, debut=0, fin=n * P)["rendement"].iloc[0] < 0   # un short perd la hausse


def test_une_position_sans_sortie_observee_est_forcee_jamais_sautee() -> None:
    """Défaut réel du 22/11 : sauter ces positions (surtout des perdantes gardées) a fabriqué +21 bps."""
    n = 300
    t = np.arange(n, dtype=np.int64) * P
    o = np.linspace(100.0, 80.0, n)                                  # le prix baisse jusqu'à la dernière bougie
    b = pd.DataFrame({"coin": "X", "t_ms": t, "o": o})
    ev = pd.DataFrame([{"vault": "v", "coin": "X", "sens": 1, "entree_ms": 10 * P, "sortie_ms": None}])
    df = M.mesurer(ev, b, debut=0, fin=n * P)
    assert len(df) == 1, "la position perdante sans sortie a ete SAUTEE"
    assert bool(df["sortie_forcee"].iloc[0]) and df["rendement"].iloc[0] < -1000      # comptée, et perdante
