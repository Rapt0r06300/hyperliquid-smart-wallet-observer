"""ALPHA P47 — EFFICIENCE du capital : net_edge_per_margin_hour = net PnL / marge moyenne / temps en marché.

Un edge net positif mais qui immobilise beaucoup de marge longtemps vaut moins qu'un edge plus petit mais
rapide et léger. On compare les alphas à ce ratio, pas au PnL brut. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def net_edge_per_margin_hour(net_pnl_usd: Any, marge_moyenne_usd: Any, temps_en_marche_h: Any) -> Any:
    """PnL net par dollar de marge et par heure en marché. UNMEASURABLE si un facteur manque/<=0."""
    if not all(isinstance(x, (int, float)) for x in (net_pnl_usd, marge_moyenne_usd, temps_en_marche_h)):
        return UNMEASURABLE
    if marge_moyenne_usd <= 0 or temps_en_marche_h <= 0:
        return UNMEASURABLE
    return round(net_pnl_usd / (marge_moyenne_usd * temps_en_marche_h), 6)


def comparer(alphas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ajoute `capital_per_h` à chaque alpha et trie décroissant (mesurables d'abord)."""
    out = []
    for a in alphas:
        v = net_edge_per_margin_hour(a.get("net_pnl_usd"), a.get("marge_moyenne_usd"), a.get("temps_en_marche_h"))
        out.append({**a, "capital_per_h": v})

    def cle(a: dict[str, Any]) -> float:
        return -a["capital_per_h"] if isinstance(a["capital_per_h"], (int, float)) else 1e18
    return sorted(out, key=cle)


__all__ = ["net_edge_per_margin_hour", "comparer", "UNMEASURABLE"]
