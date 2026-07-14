"""Modèles d'exécution & microstructure — pur, testé. Exécution du backlog :
micro_price (IDEA-18), effective_spread (IDEA-20), almgren_chriss_cost (IDEA-51),
twap_schedule (IDEA-53). Aucun ordre réel, aucune promesse.
"""
from __future__ import annotations


def micro_price(bid: float, ask: float, bid_size: float, ask_size: float) -> float:
    """Mid pondéré par la profondeur (imbalance) : une grosse taille au bid (pression acheteuse)
    tire le micro-prix vers l'ask (le prix va probablement monter)."""
    bs, as_ = float(bid_size), float(ask_size)
    tot = bs + as_
    if tot <= 0:
        return (float(bid) + float(ask)) / 2.0
    return (float(ask) * bs + float(bid) * as_) / tot


def effective_spread(trade_price: float, mid: float, side: str) -> float:
    """Spread effectif = 2 × (prix payé au-delà du mid). Positif = coût subi."""
    d = (float(trade_price) - float(mid)) if str(side).upper() == "BUY" else (float(mid) - float(trade_price))
    return 2.0 * d


def almgren_chriss_cost(quantity: float, *, adv: float, spread_bps: float,
                        impact_coeff: float = 0.1) -> float:
    """Coût d'exécution approx (bps) = demi-spread + impact proportionnel à (quantité / volume moyen)."""
    part = float(quantity) / float(adv) if adv and adv > 0 else 0.0
    return float(spread_bps) / 2.0 + impact_coeff * 10000.0 * part


def twap_schedule(total_qty: float, n_slices: int) -> list:
    """Découpe TWAP : n tranches égales dans le temps."""
    if n_slices <= 0:
        return []
    q = float(total_qty) / n_slices
    return [q] * int(n_slices)
