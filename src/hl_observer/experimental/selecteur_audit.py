"""AUDIT POINT-IN-TIME du SÉLECTEUR de vaults (rectif Flo 25/07).

La sélection dynamique (CORE/candidats, scores, rotation) ne doit JAMAIS être réinterprétée avec des scores
FUTURS. À chaque OPEN, on fige donc IMMUABLEMENT l'état du sélecteur À CET INSTANT :
  • `vault_role_at_open`  : CORE / CANDIDAT / HORS_ROSTER au moment de l'ouverture ;
  • `score_at_open` + `facteurs_at_open` : score et facteurs disponibles alors ;
  • `score_model_version` : version du MODÈLE de sélection ;
  • `score_snapshot_ts`   : horodatage du snapshot de scores utilisé ;
  • `roster_hash`         : empreinte de la liste suivie/scorée à cet instant.

Ces champs permettent de VENTILER les stats par paire vault+coin ET par version du sélecteur, SANS reclasser
rétroactivement les anciens trades. C'est une COUCHE SÉPARÉE : elle **n'entre pas** dans le config_hash RAW
(qui ne décrit que la cohorte : notional, seuils, coûts, L2, exécution). Lecture seule ; aucune position.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SELECTEUR_MODEL_VERSION = "sel_v1"          # version du MODÈLE de sélection (bump si la logique vaults_et_roles change)
SCORES_RELPATH = Path("runtime") / "data" / "vaults_scores.json"


def snapshot_selecteur(root, vault: str) -> dict:
    """État IMMUABLE du sélecteur pour `vault` à l'instant présent, à stamper sur l'OPEN. Tolérant : si les
    scores sont absents/illisibles, renvoie des champs `INCONNU`/None (jamais inventé)."""
    p = Path(root) / SCORES_RELPATH
    base = {"vault_role_at_open": "INCONNU", "score_at_open": None, "facteurs_at_open": None,
            "score_model_version": SELECTEUR_MODEL_VERSION, "score_snapshot_ts": None,
            "roster_hash": None, "n_roster": 0, "n_core": 0}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        ts = int(p.stat().st_mtime * 1000)
    except (OSError, ValueError):
        return base
    cl = d.get("classement") or []
    vlc = str(vault).lower()
    entry = next((c for c in cl if str(c.get("vault", "")).lower() == vlc), None)
    retenu = bool(entry and entry.get("retenu"))
    role = "CORE" if retenu else ("CANDIDAT" if entry else "HORS_ROSTER")
    roster = sorted(str(c.get("vault", "")).lower() for c in cl if c.get("vault"))
    roster_hash = "rost-" + hashlib.sha1("|".join(roster).encode("utf-8")).hexdigest()[:12] if roster else None
    return {"vault_role_at_open": role,
            "score_at_open": (entry or {}).get("score"),
            "facteurs_at_open": (entry or {}).get("facteurs"),
            "score_model_version": str(d.get("model_version") or d.get("version") or SELECTEUR_MODEL_VERSION),
            "score_snapshot_ts": int(d.get("ts_ms") or d.get("genere_ts_ms") or ts),
            "roster_hash": roster_hash, "n_roster": len(roster),
            "n_core": sum(1 for c in cl if c.get("retenu"))}


__all__ = ["SELECTEUR_MODEL_VERSION", "snapshot_selecteur", "SCORES_RELPATH"]
