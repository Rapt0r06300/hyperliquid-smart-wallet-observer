"""ALPHA P31 — CASCADE early warning : signal précoce de cascade de liquidations. FILTRE de régime jusqu'à preuve.

Combine des proxies : compression/variance du flux taker, autocorrélation du prix (momentum anormal),
amincissement de la profondeur, proxies de liquidation. Sort un score ∈ [0,1] ; au-dessus d'un seuil, on
passe en régime prudence (pas d'application aveugle d'un modèle normal). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _c01(x: float) -> float:
    return max(0.0, min(1.0, x))


def warning_score(*, taker_flow_compression: Any = None, price_autocorr: Any = None,
                  depth_thinning: Any = None, liq_proxy: Any = None, seuil: float = 0.6) -> dict[str, Any]:
    """Score de pré-cascade ∈ [0,1]. UNMEASURABLE si aucune composante. Régime PRUDENCE si score ≥ seuil."""
    parts = []
    if isinstance(taker_flow_compression, (int, float)):
        parts.append(_c01(taker_flow_compression))
    if isinstance(price_autocorr, (int, float)):
        parts.append(_c01(price_autocorr))               # autocorr positive forte = momentum anormal
    if isinstance(depth_thinning, (int, float)):
        parts.append(_c01(depth_thinning))
    if isinstance(liq_proxy, (int, float)):
        parts.append(_c01(liq_proxy))
    if not parts:
        return {"score": UNMEASURABLE, "regime": UNMEASURABLE}
    score = sum(parts) / len(parts)
    return {"score": round(score, 4), "n_composantes": len(parts),
            "regime": ("PRUDENCE_PRE_CASCADE" if score >= seuil else "NORMAL")}


__all__ = ["warning_score", "UNMEASURABLE"]
