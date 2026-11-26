"""``assembler_fills`` sans les copies inutiles (25/11/2026) : tableau IDENTIQUE à la version d'origine.

Pic mémoire mesuré de l'étude des ouvertures : 18 Go, dont deux copies complètes des fills (22 M + 3,5 M lignes) qui ne
servaient qu'à poser la colonne ``post``. Ce test confronte la nouvelle fonction à la copie mot pour mot de l'ancienne,
sur des données tirées au hasard (doublons entre sources, délais courts et longs, cas vides).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import copy_vault_event_study as E  # noqa: E402


def _ancienne(observes, reconstruits, *, assumed_lag_ms):
    """Copie FIGÉE de la version d'origine (avant le 25/11/2026)."""
    observes = observes.copy()
    observes["post"] = (observes["obs"] - observes["time"]) <= E.MAX_DELAI_OBSERVATION_DIRECTE_MS
    reconstruits = reconstruits.copy()
    reconstruits["post"] = False
    reunis = pd.concat([observes, reconstruits], ignore_index=True)
    if not len(reunis):
        return reunis
    reunis = reunis.sort_values("post", ascending=False, kind="stable").drop_duplicates(list(E._IDENTITE_FILL),
                                                                                       keep="first")
    suppose = ~reunis["post"].to_numpy(dtype=bool)
    reunis.loc[suppose, "obs"] = reunis.loc[suppose, "time"] + int(assumed_lag_ms)
    return reunis.sort_values(["vault", "coin", "time", "tid"], kind="stable").reset_index(drop=True)


def _fills(rng, n, decalage=0):
    t = rng.integers(1_790_000_000_000, 1_790_000_900_000, n)
    return pd.DataFrame({
        "vault": rng.choice(["0xa", "0xb", "0xc"], n), "coin": rng.choice(["BTC", "ETH"], n), "time": t,
        "obs": t + rng.choice([1_000, 60_000, 400_000, 3_600_000], n), "px": rng.uniform(1, 2, n).round(3),
        "sz": rng.uniform(1, 3, n).round(2), "signe": rng.choice([-1, 1], n), "dir": "Open Long",
        "start_pos": 0.0, "closed_pnl": np.nan, "crossed": rng.choice([0.0, 1.0], n), "fee": 0.01,
        "tid": np.arange(n) + decalage, "oid": np.arange(n) + decalage, "snap": False,
        "notional": 1.0, "after": 1.0, "is_open": True,
    })


@pytest.mark.parametrize("graine", range(12))
def test_le_tableau_reuni_est_identique_a_la_version_d_origine(graine):
    rng = np.random.default_rng(graine)
    observes = _fills(rng, int(rng.integers(0, 400)))
    reconstruits = _fills(rng, int(rng.integers(0, 300)), decalage=150)          # chevauche : doublons entre sources
    if len(observes) and len(reconstruits):
        k = min(len(observes), len(reconstruits), 40)
        reconstruits.iloc[:k, :] = observes.iloc[:k, :].to_numpy()                # même fill des deux côtés
    attendu = _ancienne(observes, reconstruits, assumed_lag_ms=120_000)
    obtenu = E.assembler_fills(observes, reconstruits, assumed_lag_ms=120_000)
    pd.testing.assert_frame_equal(obtenu, attendu, check_exact=True)
    assert list(obtenu.columns) == list(attendu.columns)


def test_les_entrees_ne_sont_pas_modifiees():
    rng = np.random.default_rng(1)
    observes, reconstruits = _fills(rng, 50), _fills(rng, 30, decalage=10)
    avant_o, avant_r = observes.copy(), reconstruits.copy()
    E.assembler_fills(observes, reconstruits, assumed_lag_ms=1)
    pd.testing.assert_frame_equal(observes, avant_o)
    pd.testing.assert_frame_equal(reconstruits, avant_r)
