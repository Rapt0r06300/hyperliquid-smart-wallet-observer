"""ALPHA P48 — SIZING robuste (SEULEMENT après OOS+forward prouvés) : fixe vs Kelly fractionnaire plafonné.

Le sizing NE transforme PAS un mauvais edge en bon edge : si l'edge net ≤ 0, la taille est 0. Sinon Kelly
fractionnaire TRÈS plafonné, borné par capacité / DD / ES. Et surtout : `sizing_apres_preuve` REFUSE de
dimensionner tant que l'OOS ET le forward ne sont pas prouvés positifs — on ne parie jamais sur un edge non
survécu. Pur, 0 réseau, 0 ordre réel.
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
                       dd_max_bps: Any = None, es_bps: Any = None, dd_budget_bps: float = 200.0,
                       es_budget_bps: float = 300.0) -> dict[str, Any]:
    """Notional = capital × fraction Kelly plafonnée, borné par capacité, budget de drawdown ET budget d'ES
    (expected shortfall). Chaque borne est nommée ; l'ES tail-loss limite réellement la taille (plus un paramètre mort)."""
    if not isinstance(edge_net_bps, (int, float)) or edge_net_bps <= 0:
        return {"notional_usd": 0.0, "raison": "edge net <= 0 : le sizing ne repare pas un mauvais edge"}
    f = kelly_fraction(edge_net_bps, variance_bps2)
    if not isinstance(f, (int, float)):
        return {"notional_usd": UNMEASURABLE, "raison": "variance inconnue"}
    notional = capital_usd * f
    if isinstance(capacity_usd, (int, float)):
        notional = min(notional, capacity_usd)
    if isinstance(dd_max_bps, (int, float)) and dd_max_bps > 0:
        notional = min(notional, capital_usd * (dd_budget_bps / dd_max_bps))    # borne par budget DD
    if isinstance(es_bps, (int, float)) and es_bps > 0:
        notional = min(notional, capital_usd * (es_budget_bps / es_bps))        # borne par budget ES (tail loss)
    return {"notional_usd": round(max(0.0, notional), 4), "kelly_fraction": f,
            "borne_capacity": capacity_usd, "borne_dd": dd_max_bps, "borne_es": es_bps}


def taille_fixe(capital_usd: float, *, frac_fixe: float = 0.01, capacity_usd: Any = None) -> dict[str, Any]:
    """Sizing FIXE : une fraction constante du capital (alternative au Kelly), bornée par la capacité."""
    notional = float(capital_usd) * max(0.0, float(frac_fixe))
    if isinstance(capacity_usd, (int, float)):
        notional = min(notional, capacity_usd)
    return {"notional_usd": round(max(0.0, notional), 4), "mode": "FIXE", "frac_fixe": frac_fixe,
            "borne_capacity": capacity_usd}


def preuve_suffisante(oos_net_bps: Any, forward_net_bps: Any) -> bool:
    """Sizing autorisé UNIQUEMENT si l'OOS ET le forward sont mesurés ET strictement positifs."""
    return (isinstance(oos_net_bps, (int, float)) and not isinstance(oos_net_bps, bool) and oos_net_bps > 0
            and isinstance(forward_net_bps, (int, float)) and not isinstance(forward_net_bps, bool)
            and forward_net_bps > 0)


def sizing_apres_preuve(*, oos_net_bps: Any, forward_net_bps: Any, edge_net_bps: Any, variance_bps2: Any,
                        capital_usd: float, mode: str = "kelly", frac_fixe: float = 0.01,
                        **bornes: Any) -> dict[str, Any]:
    """Porte de discipline : REFUSE de dimensionner tant que OOS>0 ET forward>0 ne sont pas prouvés (notional 0).
    Sinon dimensionne en mode `kelly` (défaut) ou `fixe`. On ne parie jamais avant la preuve de survie."""
    if not preuve_suffisante(oos_net_bps, forward_net_bps):
        return {"notional_usd": 0.0, "raison": "sizing INTERDIT avant preuve OOS>0 ET forward>0",
                "oos_net_bps": oos_net_bps, "forward_net_bps": forward_net_bps}
    if mode == "fixe":
        r = taille_fixe(capital_usd, frac_fixe=frac_fixe, capacity_usd=bornes.get("capacity_usd"))
    else:
        r = taille_notionnelle(edge_net_bps, variance_bps2, capital_usd=capital_usd, **bornes)
    r["preuve"] = "OOS+FORWARD>0"
    return r


__all__ = ["kelly_fraction", "taille_notionnelle", "taille_fixe", "preuve_suffisante",
           "sizing_apres_preuve", "UNMEASURABLE"]
