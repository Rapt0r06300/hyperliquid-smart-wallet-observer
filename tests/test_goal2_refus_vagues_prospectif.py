"""H18 : une copie est refusée seulement si le leader a ouvert CONTRE une vague, dans son heure ou la suivante."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import goal2_refus_vagues_prospectif as V  # noqa: E402

H = 3_600_000


def test_marquage_contre_vague() -> None:
    vg = pd.DataFrame([{"coin": "BTC", "heure_ms": 10 * H, "sens_absorbeur": 1, "liquide_usd": 2e6}])
    c = [{"coin": "BTC", "sens": 1, "entree_ms": 10 * H + 70_000, "realized_usd": -1.0, "contexte": {"latence_ms": 60_000}},
         {"coin": "BTC", "sens": -1, "entree_ms": 10 * H + 70_000, "realized_usd": 1.0, "contexte": {"latence_ms": 60_000}},
         {"coin": "BTC", "sens": 1, "entree_ms": 13 * H, "realized_usd": 1.0, "contexte": {"latence_ms": 60_000}}]
    assert [x["contre_vague"] for x in V.marquer(c, vg)] == [True, False, False]


def test_peu_de_refus_reste_more_data() -> None:
    c = [{"entree_ms": j * 86_400_000 + 1, "realized_usd": -0.1, "contre_vague": True} for j in range(6)]
    assert V.juger(c)["statut"] == "MORE_DATA"
