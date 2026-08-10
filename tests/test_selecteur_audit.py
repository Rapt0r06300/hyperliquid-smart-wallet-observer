"""AUDIT POINT-IN-TIME du sélecteur — figé à l'OPEN, couche SÉPARÉE (hors config_hash).

Le test verrouille l'invariant utile : modifier les scores/roster du sélecteur ne change jamais
le config_hash RAW de la cohorte. Il ne fige pas un digest historique qui change légitimement
quand la configuration RAW elle-même évolue.
"""
from __future__ import annotations

import json

from hl_observer.experimental import cohortes as CO
from hl_observer.experimental import selecteur_audit as SA


def _scores(tmp_path, classement):
    p = tmp_path / "runtime" / "data" / "vaults_scores.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"model_version": "sel_test", "ts_ms": 12345, "classement": classement}), encoding="utf-8")


def test_snapshot_role_score_roster_immuables(tmp_path):
    _scores(tmp_path, [{"vault": "0xCORE", "retenu": True, "score": 0.91, "facteurs": {"copyabilite": 0.8}},
                       {"vault": "0xCAND", "retenu": False, "score": 0.42, "facteurs": {"copyabilite": 0.5}}])
    s = SA.snapshot_selecteur(tmp_path, "0xcore")
    assert s["vault_role_at_open"] == "CORE" and s["score_at_open"] == 0.91 and s["facteurs_at_open"]["copyabilite"] == 0.8
    assert s["score_model_version"] == "sel_test" and s["score_snapshot_ts"] == 12345 and s["n_core"] == 1
    assert SA.snapshot_selecteur(tmp_path, "0xCAND")["vault_role_at_open"] == "CANDIDAT"
    assert SA.snapshot_selecteur(tmp_path, "0xABSENT")["vault_role_at_open"] == "HORS_ROSTER"
    assert s["roster_hash"] == SA.snapshot_selecteur(tmp_path, "0xCAND")["roster_hash"] and s["roster_hash"].startswith("rost-")


def test_scores_absents_ne_crashe_pas(tmp_path):
    s = SA.snapshot_selecteur(tmp_path, "0xX")
    assert s["vault_role_at_open"] == "INCONNU" and s["roster_hash"] is None and s["score_model_version"] == SA.SELECTEUR_MODEL_VERSION


def test_selecteur_hors_config_hash(tmp_path):
    avant = CO.config_hash_courant(CO.RAW_PROBE, tmp_path)
    assert avant.startswith("cfg-")

    _scores(tmp_path, [{"vault": "0xA", "retenu": True, "score": 0.99, "facteurs": {"copyabilite": 1.0}}])
    milieu = CO.config_hash_courant(CO.RAW_PROBE, tmp_path)

    _scores(tmp_path, [{"vault": "0xB", "retenu": False, "score": 0.01, "facteurs": {"copyabilite": 0.0}}])
    apres = CO.config_hash_courant(CO.RAW_PROBE, tmp_path)

    assert avant == milieu == apres, "le roster/sélecteur ne doit jamais contaminer le config_hash RAW"
