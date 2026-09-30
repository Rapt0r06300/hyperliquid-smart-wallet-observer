"""ALPHA P65 — ACCEPTATION économique finale : pas de DONE GLOBAL sans tous les prérequis (ou BLOCKED documenté).

Le DONE global n'est prononçable que si : factory exhaustive, data HF (ou blocage documenté), wallets
scalables, TWAP testé, L4 testé si data, maker calibré, coûts complets, OOS, forward, ADVERSE P95/P99,
capacité, efficience capital. Chaque critère est SATISFAIT, BLOCKED_EXTERNAL (documenté) ou MANQUANT.
DONE global seulement si aucun critère MANQUANT. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CRITERES = ("factory_exhaustive", "data_hf", "wallets_scalables", "twap_teste", "l4_teste",
            "maker_calibre", "couts_complets", "oos", "forward", "adverse_p95_p99",
            "capacity", "capital_efficiency")


def evaluer(etat: Mapping[str, str]) -> dict[str, Any]:
    """etat[critere] ∈ {SATISFAIT, BLOCKED_EXTERNAL, MANQUANT}. DONE global si zéro MANQUANT."""
    resume = {c: str(etat.get(c, "MANQUANT")).upper() for c in CRITERES}
    manquants = [c for c, s in resume.items() if s == "MANQUANT"]
    bloques = [c for c, s in resume.items() if s == "BLOCKED_EXTERNAL"]
    satisfaits = [c for c, s in resume.items() if s == "SATISFAIT"]
    done = not manquants
    return {"par_critere": resume, "satisfaits": satisfaits, "bloques_documentes": bloques,
            "manquants": manquants,
            "verdict_global": ("DONE_GLOBAL" if done else "PAS_DONE"),
            "note": "DONE global seulement si aucun critere MANQUANT (BLOCKED documente est tolere)"}


__all__ = ["CRITERES", "evaluer"]
