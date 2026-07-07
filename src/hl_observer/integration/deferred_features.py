"""A7 — Différés: matérialisation paper triangulaire + sonde HIP-4 read-only.

1) Arbitrage triangulaire → candidats paper (gated, jamais d'ordre direct; repassent
   par le PaperEngine). Réutilise le détecteur existant.
2) HIP-4 (marchés binaires HL): sonde READ-ONLY qui parse la forme outcomeMeta et
   calcule un signal de cohérence YES+NO≈1. Aucune exécution (priorité basse, données
   live requises pour l'observation réelle). Pur, testé.
"""

from __future__ import annotations

import os

from hl_observer.arbitrage.triangular_graph import build_triangular_cycles
from hl_observer.arbitrage.triangular_opportunity_detector import detect_triangular_opportunities


def _on(flag: str) -> bool:
    return str(os.getenv(flag, "0")).strip().lower() in {"1", "true", "yes", "on"}


def triangular_paper_candidates(edges: list, *, min_net_edge_bps: float = 20.0, max_candidates: int = 3) -> dict:
    """Opportunités triangulaires acceptées → candidats PAPER (flag gated)."""
    if not _on("HYPERSMART_TRIANGULAR_PAPER"):
        return {"candidates": [], "reason": "TRIANGULAR_PAPER_OFF"}
    cycles = build_triangular_cycles(edges)
    opps = detect_triangular_opportunities(cycles, min_net_edge_bps=min_net_edge_bps)
    candidates = [
        {
            "type": "TRIANGULAR_ARB", "path": list(o.cycle.path),
            "net_edge_bps": o.net_edge_bps, "cost_bps": o.cost_bps,
            "paper_only": True, "real_execution": False,
        }
        for o in opps if o.accepted
    ][:max_candidates]
    return {"candidates": candidates, "count": len(candidates), "reason": "OK"}


def parse_hip4_outcome(outcome_meta: dict) -> dict:
    """Parse un marché binaire HIP-4 (READ-ONLY). Forme inattendue → INVALID."""
    if not isinstance(outcome_meta, dict):
        return {"valid": False, "reason": "INVALID_SHAPE"}
    yes = outcome_meta.get("yes_price")
    no = outcome_meta.get("no_price")
    try:
        yes_f, no_f = float(yes), float(no)
    except (TypeError, ValueError):
        return {"valid": False, "reason": "MISSING_PRICES"}
    if not (0 <= yes_f <= 1 and 0 <= no_f <= 1):
        return {"valid": False, "reason": "PRICES_OUT_OF_RANGE"}
    total = yes_f + no_f
    # YES + NO devrait ≈ 1; l'écart = incohérence exploitable (observation seulement)
    return {
        "valid": True,
        "market": str(outcome_meta.get("name") or "?"),
        "yes_price": yes_f, "no_price": no_f,
        "sum": round(total, 6),
        "coherence_gap": round(abs(total - 1.0), 6),
        "read_only": True, "execution": "forbidden",
    }


def hip4_observation_signal(markets: list[dict], *, min_gap: float = 0.02) -> dict:
    """Signale les marchés HIP-4 dont YES+NO s'écarte de 1 (read-only, jamais d'ordre)."""
    parsed = [parse_hip4_outcome(m) for m in (markets or [])]
    valid = [p for p in parsed if p.get("valid")]
    flagged = [p for p in valid if p["coherence_gap"] >= min_gap]
    return {"observed": len(valid), "incoherent": len(flagged),
            "flagged": flagged, "read_only": True, "note": "observation HIP-4 seulement; aucune execution"}


__all__ = ["triangular_paper_candidates", "parse_hip4_outcome", "hip4_observation_signal"]
