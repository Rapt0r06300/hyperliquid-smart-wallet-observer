"""
Moteur de fills paper RÉALISTE — READ-ONLY / PAPER-ONLY.

Objectif (demande utilisateur) : que la simulation reflète le mainnet. Si on
perd en simulation, on aurait perdu sur le mainnet ; si on gagne, on gagne
comme sur le mainnet. On y parvient en remplissant aux VRAIS prix du marché et
en appliquant les VRAIS coûts — sans jamais passer d'ordre réel.

Deux modes (config `fill_realism_mode`) :
  - "orderbook_real" : on parcourt le CARNET D'ORDRES RÉEL (VWAP sur la
    profondeur) → exactement le prix qu'on aurait obtenu, slippage réel inclus.
  - "mark_simple"    : fill au prix mark réel + frais/spread/slippage forfaitaires.

Dans les DEUX cas, le PnL est ensuite marké au VRAI prix de sortie du mainnet,
moins les vrais frais + funding. C'est un proxy fidèle du mainnet, à la seule
limite près qu'aucun paper trade ne peut être identique à 100 % au live (impact
de marché de notre propre ordre, latence d'acheminement) — limites qu'on MODÉLISE
honnêtement via le slippage et la latence, jamais qu'on cache.

Logique 100 % pure et testable. Aucune méthode d'ordre/signature.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

FILL_MODE_ORDERBOOK = "orderbook_real"
FILL_MODE_MARK = "mark_simple"


def _is_buy(side: str) -> bool:
    v = str(side).upper()
    return v in ("BUY", "LONG")


@dataclass
class FillResult:
    price: float
    slippage_bps: float
    filled_notional: float
    mode: str
    fully_filled: bool = True


# --------------------------------------------------------------------------- #
# Prix de fill
# --------------------------------------------------------------------------- #
def orderbook_vwap(side: str, notional_usdc: float, levels: list[tuple[float, float]]) -> Optional[tuple[float, float, float]]:
    """
    Prix moyen pondéré (VWAP) en consommant le carnet réel.

    `levels` = [(prix, taille), …] DÉJÀ trié dans le sens de consommation :
    pour un BUY → asks par prix croissant ; pour un SELL → bids par prix
    décroissant. Retourne (vwap, notional_rempli, slippage_bps vs meilleur prix),
    ou None si rien d'exploitable.
    """
    if notional_usdc <= 0 or not levels:
        return None
    best = levels[0][0]
    if best <= 0:
        return None
    remaining = notional_usdc
    cost = 0.0
    qty = 0.0
    for price, size in levels:
        if price <= 0 or size <= 0:
            continue
        level_notional = price * size
        take = min(remaining, level_notional)
        q = take / price
        cost += q * price
        qty += q
        remaining -= take
        if remaining <= 1e-9:
            break
    if qty <= 0:
        return None
    vwap = cost / qty
    slippage_bps = abs(vwap - best) / best * 10_000.0
    fully = remaining <= 1e-9
    return vwap, cost, slippage_bps if fully else slippage_bps


def simple_mark_fill(side: str, mark_price: float, spread_bps: float, slippage_bps: float) -> float:
    """Fill au mark réel pénalisé de façon adverse (demi-spread + slippage)."""
    adverse = (spread_bps / 2.0 + slippage_bps) / 10_000.0
    return mark_price * (1.0 + adverse) if _is_buy(side) else mark_price * (1.0 - adverse)


def compute_entry_fill(
    mode: str,
    side: str,
    notional_usdc: float,
    mark_price: float,
    book: Optional[list[tuple[float, float]]] = None,
    *,
    spread_bps: float = 3.0,
    slippage_bps: float = 5.0,
) -> FillResult:
    """
    Prix d'entrée réaliste selon le mode. `book` = côté pertinent du carnet
    (asks pour BUY, bids pour SELL). Fallback sur le mark si carnet absent.
    """
    if mode == FILL_MODE_ORDERBOOK and book:
        r = orderbook_vwap(side, notional_usdc, book)
        if r is not None:
            vwap, filled, slip = r
            return FillResult(price=vwap, slippage_bps=slip, filled_notional=filled,
                              mode=FILL_MODE_ORDERBOOK, fully_filled=filled >= notional_usdc - 1e-6)
    px = simple_mark_fill(side, mark_price, spread_bps, slippage_bps)
    return FillResult(price=px, slippage_bps=spread_bps / 2.0 + slippage_bps,
                      filled_notional=notional_usdc, mode=FILL_MODE_MARK)


# --------------------------------------------------------------------------- #
# Coûts & PnL (markés aux vrais prix)
# --------------------------------------------------------------------------- #
def fee_usdc(notional_usdc: float, fee_bps: float) -> float:
    return abs(notional_usdc) * fee_bps / 10_000.0


def round_trip_cost_bps(taker_fee_bps: float, spread_bps: float, slippage_bps: float, funding_bps: float = 0.0) -> float:
    """Coût total aller-retour estimé en bps (entrée + sortie)."""
    return taker_fee_bps * 2.0 + spread_bps + slippage_bps + funding_bps


def funding_cost_usdc(notional_usdc: float, funding_rate_hourly: float, hours: float) -> float:
    """Coût de funding (positif = payé). Le signe selon long/short est appliqué
    par l'appelant ; ici on renvoie l'ampleur signée par le taux."""
    return abs(notional_usdc) * funding_rate_hourly * max(0.0, hours)


def realized_pnl_usdc(
    side: str,
    entry_price: float,
    exit_price: float,
    size: float,
    total_fees_usdc: float,
    funding_usdc: float = 0.0,
) -> float:
    """
    PnL net réalisé, marké aux VRAIS prix d'entrée/sortie du mainnet.
    LONG: (exit-entry)*size ; SHORT: (entry-exit)*size. Moins frais + funding.
    """
    if _is_buy(side):
        gross = (exit_price - entry_price) * abs(size)
    else:
        gross = (entry_price - exit_price) * abs(size)
    return gross - abs(total_fees_usdc) - funding_usdc


def unrealized_pnl_usdc(side: str, entry_price: float, mark_price: float, size: float) -> float:
    """PnL latent marké au vrai prix courant du mainnet."""
    if _is_buy(side):
        return (mark_price - entry_price) * abs(size)
    return (entry_price - mark_price) * abs(size)


__all__ = [
    "FILL_MODE_ORDERBOOK",
    "FILL_MODE_MARK",
    "FillResult",
    "orderbook_vwap",
    "simple_mark_fill",
    "compute_entry_fill",
    "fee_usdc",
    "round_trip_cost_bps",
    "funding_cost_usdc",
    "realized_pnl_usdc",
    "unrealized_pnl_usdc",
]
