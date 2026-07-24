"""AUDIT POINT-IN-TIME du sélecteur (rectif Flo 25/07) — figé à l'OPEN, couche SÉPARÉE (hors config_hash).

On teste le snapshot immuable (rôle/score/facteurs/version/ts/roster_hash) et le fait que la couche sélecteur
n'entre PAS dans le config_hash RAW (le sélecteur ne doit jamais reclasser ni modifier la cohorte).
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.experimental import selecteur_audit as SA
from hl_observer.experimental import cohortes as CO


def _scores(tmp_path, classement):
    p = tmp_path / "runtime" / "data" / "vaults_scores.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"model_version": "sel_test", "ts_ms": 12345, "classement": classement}), encoding="utf-8")


def test_snapshot_role_score_roster_immuables(tmp_path):
    _scores(tmp_path, [{"vault": "0xCORE", "retenu": True, "score": 0.91, "facteurs": {"copyabilite": 0.8}},
                       {"vault": "0xCAND", "retenu": False, "score": 0.42, "facteurs": {"copyabilite": 0.5}}])
    s = SA.snapshot_selecteur(tmp_path, "0xcore")                  # casse insensible
    assert s["vault_role_at_open"] == "CORE" and s["score_at_open"] == 0.91 and s["facteurs_at_open"]["copyabilite"] == 0.8
    assert s["score_model_version"] == "sel_test" and s["score_snapshot_ts"] == 12345 and s["n_core"] == 1
    assert SA.snapshot_selecteur(tmp_path, "0xCAND")["vault_role_at_open"] == "CANDIDAT"
    assert SA.snapshot_selecteur(tmp_path, "0xABSENT")["vault_role_at_open"] == "HORS_ROSTER"
    # roster_hash STABLE et déterministe (même liste -> même hash)
    assert s["roster_hash"] == SA.snapshot_selecteur(tmp_path, "0xCAND")["roster_hash"] and s["roster_hash"].startswith("rost-")


def test_scores_absents_ne_crashe_pas(tmp_path):
    s = SA.snapshot_selecteur(tmp_path, "0xX")                     # aucun fichier -> INCONNU, jamais inventé
    assert s["vault_role_at_open"] == "INCONNU" and s["roster_hash"] is None and s["score_model_version"] == SA.SELECTEUR_MODEL_VERSION


def test_selecteur_hors_config_hash(tmp_path):
    # la couche sélecteur NE DOIT PAS entrer dans le config_hash RAW (empreinte de la COHORTE uniquement)
    h = CO.config_hash_courant(CO.RAW_PROBE, tmp_path)
    assert h.startswith("cfg-6d8a2937adce7d0")                    # inchangé, indépendant du sélecteur/scores
