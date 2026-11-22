"""H14 : classification causale des fermetures de réallocation."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import goal2_sortie_reallocation as R  # noqa: E402

H = 3_600_000


def _f(ts, coin, d, sz=20.0, px=100.0, vault="v"):
    return {"vault": vault, "coin": coin, "ts_ms": ts, "dir": d, "px": px, "sz": sz,
            "crossed": True, "closed_pnl": 0.0, "fee": 0.0}


def test_une_ouverture_sur_un_autre_coin_dans_l_heure_fait_une_reallocation_entree_apres_l_avoir_vue() -> None:
    fills = pd.DataFrame([_f(10 * H, "BTC", "Close Long"), _f(10 * H + 1_800_000, "ETH", "Open Long"),
                          _f(20 * H, "SOL", "Close Short"), _f(20 * H + 600_000, "SOL", "Open Long"),
                          _f(30 * H, "XRP", "Close Long"), _f(32 * H, "ETH", "Open Long")])
    fer = R.classer(fills).set_index("coin")
    assert bool(fer.loc["BTC", "reallocation"]) is True
    assert fer.loc["BTC", "entree_ms"] == 10 * H + 1_800_000 + R.LATENCE_MS      # attend d'avoir VU l'ouverture
    assert bool(fer.loc["SOL", "reallocation"]) is False                          # même coin : pas une réallocation
    assert bool(fer.loc["XRP", "reallocation"]) is False                          # ouverture 2 h après : hors fenêtre
    assert fer.loc["XRP", "entree_ms"] == 30 * H + R.LATENCE_MS


def test_la_validation_refuse_de_se_lire_sans_confirmation() -> None:
    assert R.main(["--segment", "validation", "--sans-registre"]) == 2
