"""H22 : un ordre passif n'est rempli que si le volume agresseur dépasse la file devant lui -- toucher ne suffit pas."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import goal2_maker_tardis as M  # noqa: E402

S = 1000


def _carnet():
    t = np.arange(0, 4000 * S, 500, dtype=np.int64)
    return {"t": t, "bid": np.full(len(t), 100.0), "bid_sz": np.full(len(t), 5.0),
            "ask": np.full(len(t), 100.1), "ask_sz": np.full(len(t), 5.0)}


def _trades(volumes_vendeurs):
    t = np.array([65 * S + k for k in range(len(volumes_vendeurs))], dtype=np.int64)
    return {"t": t, "cote": np.full(len(t), -1, np.int8), "px": np.full(len(t), 100.0), "amt": np.array(volumes_vendeurs, float)}


def test_toucher_le_prix_ne_suffit_pas() -> None:
    assert M.simuler(1, 0, _carnet(), _trades([1.0, 2.0]))["etat"] == "NON_REMPLI"      # 3 < file de 5


def test_le_volume_qui_depasse_la_file_remplit() -> None:
    r = M.simuler(1, 0, _carnet(), _trades([3.0, 3.0]))
    assert r["etat"] == "REMPLI" and r["net"] < r["brut"]                                # frais déduits


def test_un_trade_hors_fenetre_ne_compte_pas() -> None:
    tr = _trades([50.0]); tr["t"] = np.array([200 * S], dtype=np.int64)                  # après la fenêtre de 60 s
    assert M.simuler(1, 0, _carnet(), tr)["etat"] == "NON_REMPLI"
