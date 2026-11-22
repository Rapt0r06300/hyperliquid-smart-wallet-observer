"""Tableau en direct (22/11/2026) : servi par l'UI du moteur, lu dans les fichiers, jamais inventé."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ui import tableau_direct as T  # noqa: E402


def test_la_page_et_les_donnees_sont_servies() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(T.create_tableau_direct_router())
    c = TestClient(app)
    page = c.get("/direct")
    assert page.status_code == 200 and "HyperSmart en direct" in page.text and "/direct/etat" in page.text
    etat = c.get("/direct/etat").json()
    assert etat["paper"] is True and etat["real_execution"] is False
    assert {"comptes", "signaux", "fantomes", "apprentissage", "collecteurs", "ameliorations", "recherche", "resume"} <= set(etat)


def test_sans_aucune_donnee_rien_n_est_invente(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(T, "_CACHE", {"t": 0.0, "etat": None})
    e = T.etat_direct(tmp_path)
    assert e["signaux"]["derniers"] == [] and e["signaux"]["ouvertures_vues"] == 0
    assert e["fantomes"]["trades"] == 0 and e["apprentissage"] == {"demarre": False}
    assert all(f["etat"] == "inconnu" and f["age_s"] is None for f in e["collecteurs"]["flux"])
    frais = next(a for a in e["ameliorations"] if a["titre"].startswith("Frais"))
    assert frais["actif"] is False and frais["preuve"].startswith("aucune donnée")   # pas de coche sans preuve


def test_une_amelioration_n_est_cochee_que_si_on_la_voit_dans_les_donnees(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(T, "_CACHE", {"t": 0.0, "etat": None})
    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True)
    (d / "vault_fills_live.jsonl").write_text(
        json.dumps({"coin": "BTC", "fee": "0.1"}) + "\n" + json.dumps({"coin": "BTC"}) + "\n", encoding="utf-8")
    frais = next(a for a in T.ameliorations(tmp_path) if a["titre"].startswith("Frais"))
    assert frais["actif"] is False and "50 %" in frais["preuve"]                    # un fill sans frais : pas coché
    (d / "vault_fills_live.jsonl").write_text(json.dumps({"coin": "BTC", "fee": "0.1"}) + "\n", encoding="utf-8")
    assert next(a for a in T.ameliorations(tmp_path) if a["titre"].startswith("Frais"))["actif"] is True
