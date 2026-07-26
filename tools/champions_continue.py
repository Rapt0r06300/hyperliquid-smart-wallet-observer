"""CHAMPION / CHALLENGERS + DÉRIVE (LABO-CONTINU-FINAL FINAL-11/12, Flo 26/07). Statuts clairs, gel immuable,
amélioration = NOUVEAU candidate_id + version + lien parent + A/B. Mesure la dérive (edge récent vs
historique, régime, fill rate, coûts, vol/liquidité, dormant/réveillé). Registre append-only. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import json
from pathlib import Path

STATUTS = ("EXPLORATOIRE", "SURVIVANT_FAST_SCREEN", "EXACT_POSITIF", "PROMETTEUR", "VALIDATION_POSITIVE",
           "HOLDOUT_POSITIF", "FORWARD_POSITIF", "CHAMPION", "SHADOW", "DATA_MISSING", "KILL")


def statut_depuis_metriques(m: dict) -> str:
    """Attribue un statut d'après les preuves accumulées (jamais 'validé' sur du discovery seul)."""
    n = m.get("n") or 0
    if n < 30 or m.get("net_median_bps") is None:
        return "DATA_MISSING"
    if m.get("forward_net_bps") is not None and m["forward_net_bps"] > 0 and m.get("dsr", 0) and m["dsr"] >= 0.95:
        return "CHAMPION"
    if m.get("forward_net_bps") is not None and m["forward_net_bps"] > 0:
        return "FORWARD_POSITIF"
    if (m.get("holdout_net_bps") or 0) > 0:
        return "HOLDOUT_POSITIF"
    if (m.get("validation_net_bps") or 0) > 0:
        return "VALIDATION_POSITIVE"
    if (m.get("exact_net_bps") or 0) > 0:
        return "EXACT_POSITIF"
    if (m.get("net_median_bps") or 0) > 0:
        return "PROMETTEUR"
    return "KILL"


def enregistrer_candidat(rundir: Path, cand: dict, *, parent_id: str | None = None) -> dict:
    """Append au registre des candidats. Une amélioration porte un `parent_id` (lien A/B) et une version+1 ;
    JAMAIS de modification en place d'un candidat figé."""
    rundir = Path(rundir)
    p = rundir / "results" / "champions.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    ligne = {**cand, "parent_id": parent_id, "statut": cand.get("statut") or statut_depuis_metriques(cand)}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    return ligne


def charger(rundir: Path) -> list[dict]:
    p = Path(rundir) / "results" / "champions.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]


def mesurer_derive(recent: dict, historique: dict) -> dict:
    """Dérive entre une fenêtre RÉCENTE et l'HISTORIQUE d'un candidat : edge, régime, fill, coûts, vol."""
    def d(k):
        a, b = recent.get(k), historique.get(k)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return round(a - b, 4)
        return None
    edge_delta = d("net_median_bps")
    return {"edge_recent_bps": recent.get("net_median_bps"), "edge_historique_bps": historique.get("net_median_bps"),
            "edge_delta_bps": edge_delta, "fill_delta": d("fill_rate"), "cout_delta_bps": d("cout_bps"),
            "vol_delta": d("volatilite"),
            "etat": ("DEGRADE" if (edge_delta is not None and edge_delta < -2.0) else
                     "REVEILLE" if (edge_delta is not None and edge_delta > 2.0) else "STABLE"),
            "dormant": bool((recent.get("n") or 0) == 0 and (historique.get("n") or 0) > 0)}


__all__ = ["STATUTS", "statut_depuis_metriques", "enregistrer_candidat", "charger", "mesurer_derive"]
