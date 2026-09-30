"""ALPHA P14 — SOURCE UNIQUE de coûts pour la recherche. Fini les hardcodes 9/3 concurrents.

Tout coût passe par ici, qui délègue à l'autorité `config/frais_venues`. On DÉCOMPOSE le coût en
fees / spread / slippage / latency et on trace `cost_incomplet` : si une composante requise manque, le
coût est incomplet et **interdit CANDIDAT/PROMOTE** (jamais de vert sur un coût partiel présenté complet).

Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hl_observer.config.frais_venues import frais_taker_bps

UNMEASURABLE = "UNMEASURABLE"


def fees_roundtrip_taker_bps(venue_entree: object, venue_sortie: object | None = None) -> float:
    """Frais taker aller-retour depuis l'UNIQUE source. Cross-venue = frais des deux venues."""
    e = frais_taker_bps(venue_entree)
    s = frais_taker_bps(venue_sortie if venue_sortie is not None else venue_entree)
    return round(e + s, 6)


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def decomposer_cout(*, fees_bps: Any = UNMEASURABLE, spread_bps: Any = UNMEASURABLE,
                    slippage_bps: Any = UNMEASURABLE, latency_bps: Any = UNMEASURABLE,
                    requis: tuple[str, ...] = ("fees_bps", "spread_bps", "slippage_bps", "latency_bps")) -> dict[str, Any]:
    """Décompose le coût ; total = somme des composantes mesurables ; `cost_incomplet` si un `requis` manque.

    FIX-06 : par DÉFAUT les QUATRE composantes (fees+spread+slippage+latency) sont requises. Une slippage ou
    latency inconnue rend le coût INCOMPLET → interdit CANDIDAT/PROMOTE. Le caller doit fournir explicitement
    chaque composante (même 0.0 quand elle est réellement nulle, ex. latency=0 en exécution causale)."""
    comp = {"fees_bps": _num(fees_bps), "spread_bps": _num(spread_bps),
            "slippage_bps": _num(slippage_bps), "latency_bps": _num(latency_bps)}
    presents = [v for v in comp.values() if v is not None]
    manque_requis = any(comp.get(r) is None for r in requis)
    total = round(sum(presents), 6) if presents else UNMEASURABLE
    return {**{k: (v if v is not None else UNMEASURABLE) for k, v in comp.items()},
            "cost_total_bps": total, "cost_incomplet": bool(manque_requis or not presents)}


def cout_bloque_promote(cost: Mapping[str, Any]) -> bool:
    """True si ce coût interdit CANDIDAT/PROMOTE (incomplet). La discipline passe avant le beau chiffre."""
    return bool(cost.get("cost_incomplet", True))


def cout_executable_taker_bps(venue: object, *, spread_bps: Any = UNMEASURABLE,
                              slippage_bps: Any = UNMEASURABLE, latency_bps: Any = UNMEASURABLE) -> dict[str, Any]:
    """Coût exécutable taker aller-retour : frais (source unique) + spread + slippage + latency décomposés."""
    return decomposer_cout(fees_bps=fees_roundtrip_taker_bps(venue), spread_bps=spread_bps,
                           slippage_bps=slippage_bps, latency_bps=latency_bps)


__all__ = ["fees_roundtrip_taker_bps", "decomposer_cout", "cout_bloque_promote",
           "cout_executable_taker_bps", "UNMEASURABLE"]
