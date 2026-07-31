"""ALPHA P48 — SIZING robuste (SEULEMENT après OOS+forward prouvés) : fixe vs Kelly fractionnaire plafonné.

Le sizing NE transforme PAS un mauvais edge en bon edge : si l'edge net ≤ 0, la taille est 0. Sinon Kelly
fractionnaire TRÈS plafonné, borné par capacité / DD / ES. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def kelly_fraction(edge_bps: Any, variance_bps2: Any, *, fraction: float = 0.25, cap: float = 0.02) -> Any:
    """Fraction de Kelly = edge/variance, multipliée par `fraction` (prudence) et plafonnée à `cap`. 0 si edge<=0."""
    if not isinstance(edge_bps, (int, float)) or not isinstance(variance_bps2, (int, float)) or variance_bps2 <= 0:
        return UNMEASURABLE
    if edge_bps <= 0:
        return 0.0
    return round(min(cap, max(0.0, (edge_bps / variance_bps2) * fraction)), 6)


def taille_notionnelle(edge_net_bps: Any, variance_bps2: Any, *, capital_usd: float, capacity_usd: Any = None,
                       dd_max_bps: Any = None, es_bps: Any = None, dd_budget_bps: float = 200.0) -> dict[str, Any]:
    """Notional = capital × fraction Kelly plafonnée, borné par capacité et budget de drawdown."""
    if not isinstance(edge_net_bps, (int, float)) or edge_net_bps <= 0:
        return {"notional_usd": 0.0, "raison": "edge net <= 0 : le sizing ne repare pas un mauvais edge"}
    f = kelly_fraction(edge_net_bps, variance_bps2)
    if not isinstance(f, (int, float)):
        return {"notional_usd": UNMEASURABLE, "raison": "variance inconnue"}
    notional = capital_usd * f
    if isinstance(capacity_usd, (int, float)):
        notional = min(notional, capacity_usd)
    if isinstance(dd_max_bps, (int, float)) and dd_max_bps > 0:
        notional = min(notional, capital_usd * (dd_budget_bps / dd_max_bps))   # borne par budget DD
    return {"notional_usd": round(max(0.0, notional), 4), "kelly_fraction": f,
            "borne_capacity": capacity_usd, "borne_dd": dd_max_bps}


__all__ = ["kelly_fraction", "taille_notionnelle", "UNMEASURABLE"]
