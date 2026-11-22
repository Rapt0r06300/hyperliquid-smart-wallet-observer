"""La règle bloquante qui refuse un gel silencieux de la collecte CopyVault.

MESURE DU 21/11/2026 — pourquoi cette règle existe. Le coffre SAFE n'a plus reçu une
release copy-vault depuis le **18/10**, et rien n'a crié pendant 45 jours. La cause tenait
en une ligne du reçu canonique :

    copy-vault-e8-broad-2026110702-v8   STUCK   OWNER_RUN_COMPLETED_WITH_ACTIVE_LEASE
    collected_lane_count: 0   qualified_shard_count: 0   publication_complete: False

Cette seule campagne portait **3 052 leaders** — toute la couverture de l'époque. Le reçu
disait honnêtement `MORE_DATA`, mais « pas assez de données » est indiscernable d'un gel
total si personne ne regarde POURQUOI. D'où cette règle : elle distingue le manque de
données (acceptable, mesuré) de la PANNE (un run propriétaire mort que personne ne
reprend, ou zéro lane collectée alors qu'une lane est planifiée).

Elle ne desserre rien : sans reçu lisible elle REFUSE, parce qu'un plan qu'on ne sait pas
lire n'est pas un plan sain.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _audit():
    spec = importlib.util.spec_from_file_location(
        "audit_report_collecte", RACINE / "tools" / "audit_report.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_report_collecte"] = module
    spec.loader.exec_module(module)
    return module


def _ecrire_recu(racine: Path, plan: dict, *, epoque: int = 8) -> Path:
    (racine / "catalog").mkdir(parents=True, exist_ok=True)
    chemin = racine / "catalog" / "COPY_VAULT_COVERAGE_RECEIPT.json"
    chemin.write_text(json.dumps({
        "schema": "alina.copy_vault_coverage_receipt.v2",
        "phase_epoch": epoque,
        "status": "MORE_DATA",
        "authoritative_plan": plan,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return chemin


def _plan_sain() -> dict:
    return {
        "scheduled_lane_count": 4,
        "collected_lane_count": 4,
        "qualified_shard_count": 912,
        "campaigns": [
            {"campaign_id": "copy-vault-e8-broad-x-v8", "status": "COMPLETE",
             "status_reason": "", "collected": True, "published": True},
        ],
    }


def test_un_plan_qui_collecte_passe(tmp_path, monkeypatch):
    module = _audit()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    _ecrire_recu(tmp_path, _plan_sain())
    verdict = module.c_copy_vault_collecte_non_gelee()
    assert verdict.ok, verdict.errors
    assert verdict.blocking is True
    assert "4/4" in verdict.summary


def test_un_run_proprietaire_mort_fait_rougir(tmp_path, monkeypatch):
    """Le cas REEL du 21/11 : une campagne STUCK que personne ne reprend."""
    module = _audit()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    plan = _plan_sain()
    plan["campaigns"] = [{
        "campaign_id": "copy-vault-e8-broad-2026110702-v8",
        "status": "STUCK",
        "status_reason": "OWNER_RUN_COMPLETED_WITH_ACTIVE_LEASE",
        "collected": False, "published": False,
    }]
    _ecrire_recu(tmp_path, plan)
    verdict = module.c_copy_vault_collecte_non_gelee()
    assert not verdict.ok
    assert any("OWNER_RUN" in e for e in verdict.errors)
    # Le remede est NOMME : un rouge sans remede fait perdre du temps.
    assert any("_reconcile_retry_current_epoch" in e for e in verdict.errors)


def test_zero_lane_collectee_malgre_une_lane_planifiee_fait_rougir(tmp_path, monkeypatch):
    module = _audit()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    plan = _plan_sain()
    plan.update({"scheduled_lane_count": 1, "collected_lane_count": 0,
                 "qualified_shard_count": 0})
    _ecrire_recu(tmp_path, plan)
    verdict = module.c_copy_vault_collecte_non_gelee()
    assert not verdict.ok
    assert any("AUCUNE collectee" in e for e in verdict.errors)


def test_un_recu_absent_est_un_REFUS_et_non_un_vert(tmp_path, monkeypatch):
    """Fail-closed : ne pas savoir lire le plan n'est pas la preuve qu'il va bien."""
    module = _audit()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    verdict = module.c_copy_vault_collecte_non_gelee()
    assert not verdict.ok
    assert verdict.blocking is True
    assert "introuvable" in verdict.summary
    # Le refus dit QUOI FAIRE : un rouge sans remede fait perdre du temps.
    assert any("build_copy_vault_coverage_receipt" in e for e in verdict.errors)


def test_un_recu_illisible_ou_sans_plan_est_un_REFUS(tmp_path, monkeypatch):
    module = _audit()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "catalog").mkdir(parents=True, exist_ok=True)
    (tmp_path / "catalog" / "COPY_VAULT_COVERAGE_RECEIPT.json").write_text(
        "{ pas du json", encoding="utf-8")
    assert not module.c_copy_vault_collecte_non_gelee().ok

    (tmp_path / "catalog" / "COPY_VAULT_COVERAGE_RECEIPT.json").write_text(
        json.dumps({"phase_epoch": 8}), encoding="utf-8")
    verdict = module.c_copy_vault_collecte_non_gelee()
    assert not verdict.ok
    assert any("plan autoritaire" in e.lower() or "authoritative_plan" in e
               for e in verdict.errors)


def test_la_regle_est_branchee_dans_le_plan_bloquant():
    """Une règle non enregistrée ne surveille rien."""
    source = (RACINE / "tools" / "audit_report.py").read_text(encoding="utf-8")
    assert "c_copy_vault_collecte_non_gelee," in source
