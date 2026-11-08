"""Tests du suivi adaptatif des leaders (curés + actifs découverts)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import fusionner_leaders_actifs as F  # noqa: E402


def test_construire_suivis_cures_puis_actifs():
    cures = ["0xcure000001", "0xcure000002"]
    actifs = ["0xactif00001", "0xcure000001", "0xactif00002"]  # 1 doublon avec curé
    out = F.construire_suivis(cures, actifs, cap=10)
    assert out[:2] == ["0xcure000001", "0xcure000002"]        # curés en tête
    assert "0xactif00001" in out and "0xactif00002" in out    # actifs ajoutés
    assert len(out) == len(set(out)) == 4                      # dédup


def test_cap_respecte():
    cures = [f"0xcure{i:06d}" for i in range(5)]
    actifs = [f"0xactif{i:05d}" for i in range(50)]
    out = F.construire_suivis(cures, actifs, cap=10)
    assert len(out) == 10 and out[:5] == cures                # curés gardés, cap respecté


def test_fusion_bout_en_bout(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir(parents=True)
    (cfg / "copy_vault_leaders.json").write_text(
        json.dumps({"vaults": ["0xcure000001", "0xcure000002"]}), encoding="utf-8")
    (cfg / "leaders_actifs_classement.json").write_text(json.dumps(
        {"actifs": [{"vault": "0xactif00001", "score": 9}, {"vault": "0xactif00002", "score": 5}]}),
        encoding="utf-8")
    rap = F.fusionner(tmp_path, cap=120)
    assert rap["statut"] == "OK" and rap["cures"] == 2 and rap["actifs_ajoutes"] == 2
    suivis = json.loads((cfg / "copy_vault_leaders.json").read_text(encoding="utf-8"))["vaults"]
    assert set(suivis) == {"0xcure000001", "0xcure000002", "0xactif00001", "0xactif00002"}
    # base curée figée + sauvegarde créées
    assert (cfg / "copy_vault_leaders_cures.json").exists()
    assert (cfg / "copy_vault_leaders.json.avant-fusion.bak").exists()


def test_sans_classement_garde_cures(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir(parents=True)
    (cfg / "copy_vault_leaders.json").write_text(json.dumps({"vaults": ["0xcure000001"]}), encoding="utf-8")
    rap = F.fusionner(tmp_path)
    assert rap["statut"] == "pas_de_classement" and rap["total"] == 1  # rien perdu
