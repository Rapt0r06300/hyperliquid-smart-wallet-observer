"""ALPHA P40 — WALLET INFORMATION RATIO : score d'un wallet selon ce qui compte POUR NOUS, jamais son PnL brut.

Combine : temps d'avance (lead time), edge copyable gross, décroissance de l'edge, capacité, tolérance à la
latence, stabilité coin/jour/régime, indépendance d'entité. Un wallet au gros PnL mais non copyable (latence,
capacité, decay) score bas. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def info_ratio(*, lead_time_ms: Any, copyable_gross_bps: Any, edge_decay_ratio: Any = 0.0,
               capacity_usd: Any = None, latency_tol_ms: Any = None, stability: Any = 0.5,
               entity_independent: bool = True, cout_bps: float = 9.0) -> dict[str, Any]:
    """Score ∈ [0,1] (0 = inutile). Requiert lead_time et copyable_gross ; le reste module."""
    if not isinstance(lead_time_ms, (int, float)) or not isinstance(copyable_gross_bps, (int, float)):
        return {"score": UNMEASURABLE, "raison": "lead_time/copyable manquant"}
    net = copyable_gross_bps - cout_bps
    if net <= 0:
        return {"score": 0.0, "net_copyable_bps": round(net, 4), "raison": "net copyable <= 0"}
    # normalisations douces
    s_lead = _clamp01(lead_time_ms / 2000.0)                 # 2s d'avance = plein pot
    s_net = _clamp01(net / 20.0)                             # 20 bps net = plein pot
    s_decay = _clamp01(1.0 - float(edge_decay_ratio))        # decay fort -> pénalité
    s_stab = _clamp01(float(stability))
    s_cap = _clamp01((float(capacity_usd) / 1000.0)) if isinstance(capacity_usd, (int, float)) else 0.5
    s_lat = _clamp01(float(latency_tol_ms) / 1000.0) if isinstance(latency_tol_ms, (int, float)) else 0.5
    penal_entite = 1.0 if entity_independent else 0.4
    score = (0.30 * s_net + 0.20 * s_lead + 0.15 * s_decay + 0.15 * s_stab +
             0.10 * s_cap + 0.10 * s_lat) * penal_entite
    return {"score": round(score, 4), "net_copyable_bps": round(net, 4),
            "composantes": {"net": s_net, "lead": s_lead, "decay": s_decay, "stab": s_stab,
                            "cap": s_cap, "lat": s_lat, "entite": penal_entite}}


def classer(wallets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classe des wallets par info_ratio décroissant (les scores UNMEASURABLE en dernier)."""
    def cle(w: dict[str, Any]) -> float:
        s = w.get("score")
        return -s if isinstance(s, (int, float)) else 1e9
    return sorted(wallets, key=cle)


__all__ = ["info_ratio", "classer", "UNMEASURABLE"]
