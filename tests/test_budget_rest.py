"""Amélioration n° 22 : chaque collecteur déclare son poids REST réel, sans jamais bloquer."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.ops import budget_rest as B  # noqa: E402


def test_les_poids_suivent_la_regle_publiee() -> None:
    assert B.poids("l2Book") == 2 and B.poids("allMids") == 2 and B.poids("clearinghouseState") == 2
    assert B.poids("vaultDetails") == 20 and B.poids("userRole") == 60
    assert B.poids("userFillsByTime", 2000) == 20 + 100           # +1 par 20 éléments
    assert B.poids("fundingHistory", 500) == 20 + 25
    assert B.poids("candleSnapshot", 5000) == 20 + 83             # +1 par 60 bougies


def test_une_seule_ecriture_par_minute_avec_le_poids_de_la_derniere_minute(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(B, "_FENETRES", {})
    monkeypatch.setattr(B, "_DERNIERE_ECRITURE", {})
    t = {"v": 0.0}
    for _ in range(10):
        B.compter("l2Book", source="carnet", root=tmp_path, horloge=lambda: t["v"])
        t["v"] += 5.0                                              # 10 appels en 50 s
    lu = json.loads((tmp_path / B.FICHIER).read_text(encoding="utf-8"))
    assert lu["carnet"]["poids_par_passe"] == 2                    # écrit au 1er appel, pas à chaque appel
    t["v"] = 61.0
    B.compter("l2Book", source="carnet", root=tmp_path, horloge=lambda: t["v"])
    lu = json.loads((tmp_path / B.FICHIER).read_text(encoding="utf-8"))
    assert lu["carnet"]["poids_par_passe"] == 2 * 10               # la fenêtre glissante d'une minute
    assert lu["carnet"]["mesure"] == "REELLE_FENETRE_60S"


def test_les_autres_sources_sont_gardees_et_rien_ne_leve(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(B, "_FENETRES", {})
    monkeypatch.setattr(B, "_DERNIERE_ECRITURE", {})
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / B.FICHIER).write_text(json.dumps({"garde_rest_ws": {"poids_par_min_moyen": 135.3, "ts_ms": 1}}),
                                      encoding="utf-8")
    B.compter("userFillsByTime", 40, source="poll", root=tmp_path)
    lu = json.loads((tmp_path / B.FICHIER).read_text(encoding="utf-8"))
    assert set(lu) == {"garde_rest_ws", "poll"} and lu["poll"]["poids_par_passe"] == 22
    (tmp_path / B.FICHIER).write_text("pas du json", encoding="utf-8")
    monkeypatch.setattr(B, "_DERNIERE_ECRITURE", {})
    assert B.compter("l2Book", source="x", root=tmp_path) == 2     # fichier corrompu : pas d'exception


def test_sous_pytest_rien_n_est_ecrit_dans_le_vrai_runtime(monkeypatch) -> None:
    monkeypatch.setattr(B, "_FENETRES", {})
    monkeypatch.setattr(B, "_DERNIERE_ECRITURE", {})
    ecrits = []
    monkeypatch.setattr(B, "publier", lambda *a, **k: ecrits.append(a))
    B.compter("l2Book", source="carnet")                           # sans racine explicite
    assert ecrits == []
