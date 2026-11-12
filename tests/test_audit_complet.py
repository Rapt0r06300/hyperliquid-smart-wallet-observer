"""L'audit complet compose données + mesure + économie et déduit les chantiers priorisés."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("audit_complet", RACINE / "tools" / "audit_complet.py")
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(RACINE))
    sys.path.insert(0, str(RACINE / "src"))
    spec.loader.exec_module(m)
    return m


A = _mod()


def test_synthese_signale_mesure_donnees_gachees_et_chantiers():
    data_audit = [
        {"famille": "explorer_tx", "etat": "CERTIFIÉ · NON UTILISÉ PAR LE LABO", "shards_coffre": 3},
        {"famille": "leader_orders", "etat": "JAMAIS COLLECTÉ", "shards_coffre": 0},
        {"famille": "book_l2", "etat": "FRAIS · UTILISÉ", "shards_coffre": 10},
    ]
    sonde = {"executable": False, "signaux_train": 98138,
             "coins_a_collecter": [{"coin": "HYPE"}, {"coin": "BTC"}]}
    plan = {"hypotheses": [{"status": "REJECTED", "usd_par_jour": None},
                           {"status": "MORE_DATA", "usd_par_jour": -2.09}]}
    texte = "\n".join(A.synthese(data_audit, sonde, plan))
    assert "PRIORITÉ ABSOLUE" in texte and "HYPE" in texte           # mesurabilité
    assert "DONNÉES GÂCHÉES" in texte and "explorer_tx" in texte     # gâché
    assert "JAMAIS COLLECTÉS" in texte and "leader_orders" in texte  # non collecté
    assert "RECHERCHE NÉGATIVE" in texte and "LATENCE" in texte and "MAKER" in texte   # chantiers


def test_synthese_dit_quand_mesurable():
    sonde = {"executable": True, "signaux_executables": 1200}
    texte = "\n".join(A.synthese([], sonde, {}))
    assert "MESURABLE" in texte and "1 200" in texte


def test_main_tourne_sans_rien(tmp_path, capsys):
    (tmp_path / "runtime").mkdir()
    assert A.main(["--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "AUDIT COMPLET" in out and "QUOI AMÉLIORER" in out
