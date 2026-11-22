"""H15 : le score d'un leader n'utilise que des étiquettes connues avant la fin de la fenêtre."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import goal2_informativite_leaders as I  # noqa: E402

H = 3_600_000


def test_une_etiquette_connue_apres_la_fin_n_entre_pas_dans_le_score() -> None:
    lignes = []
    for k in range(12):                                               # 12 événements connus bien avant la fin
        lignes.append({"vault": "a", "dernier_ms": k * H, "notionnel": 2000.0, "aj_4h": 10.0, "connu_4h": k * H + 5 * H})
    lignes.append({"vault": "a", "dernier_ms": 90 * H, "notionnel": 1e9, "aj_4h": -9999.0, "connu_4h": 101 * H})   # connu APRÈS
    sc = I.scores(pd.DataFrame(lignes), 100 * H, 0, 4)
    assert abs(sc["a"] - 10.0) < 1e-9                                 # l'étiquette future n'a rien changé


def test_un_leader_trop_peu_actif_n_est_pas_classe() -> None:
    lignes = [{"vault": "b", "dernier_ms": k * H, "notionnel": 2000.0, "aj_4h": 5.0, "connu_4h": k * H + 5 * H} for k in range(5)]
    assert I.scores(pd.DataFrame(lignes), 100 * H, 0, 4).empty


def test_la_validation_refuse_de_se_lire_sans_confirmation() -> None:
    assert I.main(["--segment", "validation", "--sans-registre"]) == 2
