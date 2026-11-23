"""H22-P : rien d'avant le gel, un fill vu trop tard est un NO-TRADE, et pas de verdict sans 100 signaux sur 5 jours."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import goal2_maker_prospectif as P  # noqa: E402

S = 1000


def _c():
    t = np.arange(0, 4000 * S, 500, dtype=np.int64)
    return {"BTC": {"t": t, "bid": np.full(len(t), 100.0), "bid_sz": np.full(len(t), 5.0),
                    "ask": np.full(len(t), 100.1), "ask_sz": np.full(len(t), 5.0)}}


def _tr():
    return {"BTC": {"t": np.array([65 * S, 66 * S], np.int64), "cote": np.array([-1, -1], np.int8),
                    "px": np.array([100.0, 100.0]), "amt": np.array([3.0, 3.0])}}


def test_les_ouvertures_d_avant_le_gel_sont_ignorees() -> None:
    lignes = [{"dir": "Open Long", "fill_ts_ms": 10, "recu_ms": 20, "coin": "BTC", "vault": "a"},
              {"dir": "Open Long", "fill_ts_ms": 5_000, "recu_ms": 5_100, "coin": "BTC", "vault": "a"},
              {"dir": "Close Long", "fill_ts_ms": 6_000, "recu_ms": 6_100, "coin": "BTC", "vault": "a"}]
    assert [s["t"] for s in P.ouvertures(lignes, 1_000)] == [5_000]


def test_un_fill_vu_trop_tard_est_un_no_trade_et_peu_de_signaux_reste_more_data() -> None:
    sig = [{"coin": "BTC", "vault": "a", "signe": 1, "t": 0, "recu": 61 * S},        # vu après 61 s
           {"coin": "BTC", "vault": "a", "signe": 1, "t": 0, "recu": 5 * S}]
    r = P.evaluer(sig, _c(), _tr())
    assert r["etats"]["TROP_TARD"] == 1 and r["etats"]["REMPLI"] == 1 and r["statut"] == "MORE_DATA"
