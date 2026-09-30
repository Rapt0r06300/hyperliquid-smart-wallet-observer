"""PERF-5 — Budget latence → gate d'âge de signal dynamique.

Le lien vitesse↔PnL: un signal trop vieux est REFUSÉ (SIGNAL_TOO_OLD). Si la
chaîne est rapide (p95 bas), on peut resserrer le gate d'âge sans perdre de
trades frais; si elle ralentit, on l'élargit pour ne pas tout refuser. Pur.

Retourne une RECOMMANDATION (l'activation reste gated par replay A/B, jamais
appliquée en aveugle).
"""

from __future__ import annotations

DEFAULT_FLOOR_MS = 2_000.0
DEFAULT_CEIL_MS = 12_000.0
SAFETY_MULT = 3.0  # marge au-dessus du p95 end-to-end


def recommend_signal_age_gate_ms(
    latency_report: dict,
    *,
    floor_ms: float = DEFAULT_FLOOR_MS,
    ceil_ms: float = DEFAULT_CEIL_MS,
    safety_mult: float = SAFETY_MULT,
) -> dict:
    """Recommande un plafond d'âge signal = p95(end_to_end) × marge, borné."""

    e2e = (latency_report or {}).get("end_to_end", {}) if isinstance(latency_report, dict) else {}
    p95 = e2e.get("p95")
    n = int(e2e.get("n") or 0)
    if not p95 or n < 30:
        return {
            "recommended_max_signal_age_ms": None,
            "reason": "INSUFFICIENT_LATENCY_SAMPLES",
            "n": n,
            "applied": False,
        }
    raw = float(p95) * float(safety_mult)
    rec = max(floor_ms, min(ceil_ms, raw))
    return {
        "recommended_max_signal_age_ms": round(rec, 1),
        "p95_end_to_end_ms": float(p95),
        "safety_mult": float(safety_mult),
        "bounded_by": "floor" if raw < floor_ms else ("ceil" if raw > ceil_ms else "none"),
        "reason": "OK",
        "applied": False,  # activation seulement via replay A/B (règle produit)
        "n": n,
    }


__all__ = ["recommend_signal_age_gate_ms"]
