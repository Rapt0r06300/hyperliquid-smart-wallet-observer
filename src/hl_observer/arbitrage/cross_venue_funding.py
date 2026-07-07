"""ARB-DATA — Différentiel de funding cross-venue (le VRAI modèle du funding-arb).

On ne gagne pas le funding absolu d'une venue: on gagne l'ÉCART entre deux venues
(long là où on encaisse, short là où on paie le moins), net des coûts des deux
jambes. Distillé de gajesh (HL vs Lighter) + Hummingbot. Pur, read-only, aucune
donnée inventée: venue manquante / rate absent ⇒ pas d'opportunité.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CrossVenueFundingEdge:
    coin: str
    long_venue: str
    short_venue: str
    net_edge_bps_per_hour: float
    gross_diff_bps_per_hour: float
    cost_bps: float
    reason: str
    paper_only: bool = True
    real_execution: bool = False


def compute_cross_venue_funding_edge(
    coin: str,
    venue_rates_bps_per_hour: dict[str, float],
    *,
    round_trip_cost_bps: float = 4.0,
    min_net_edge_bps_per_hour: float = 1.0,
) -> CrossVenueFundingEdge | None:
    """Meilleur écart de funding entre deux venues, net des coûts (2 jambes)."""

    clean = {}
    for venue, rate in (venue_rates_bps_per_hour or {}).items():
        try:
            clean[str(venue)] = float(rate)
        except (TypeError, ValueError):
            continue
    if len(clean) < 2:
        return None
    # On encaisse le funding sur la jambe SHORT quand le rate est positif (les longs
    # paient les shorts). L'écart exploitable = rate_short_venue - rate_long_venue.
    hi_venue = max(clean, key=lambda v: clean[v])   # rate le + haut → on y short (encaisse)
    lo_venue = min(clean, key=lambda v: clean[v])   # rate le + bas → on y long (paie le moins)
    if hi_venue == lo_venue:
        return None
    gross = clean[hi_venue] - clean[lo_venue]        # bps/heure, toujours >= 0
    net = gross - float(round_trip_cost_bps)
    if net < float(min_net_edge_bps_per_hour):
        return CrossVenueFundingEdge(
            coin=str(coin).upper(), long_venue=lo_venue, short_venue=hi_venue,
            net_edge_bps_per_hour=round(net, 4), gross_diff_bps_per_hour=round(gross, 4),
            cost_bps=float(round_trip_cost_bps), reason="NET_EDGE_TOO_SMALL_AFTER_COSTS",
        )
    return CrossVenueFundingEdge(
        coin=str(coin).upper(), long_venue=lo_venue, short_venue=hi_venue,
        net_edge_bps_per_hour=round(net, 4), gross_diff_bps_per_hour=round(gross, 4),
        cost_bps=float(round_trip_cost_bps), reason="CROSS_VENUE_FUNDING_EDGE",
    )


def rank_cross_venue_edges(
    rates_by_coin: dict[str, dict[str, float]],
    *,
    round_trip_cost_bps: float = 4.0,
    min_net_edge_bps_per_hour: float = 1.0,
    top: int = 10,
) -> tuple[CrossVenueFundingEdge, ...]:
    edges = []
    for coin, venue_rates in (rates_by_coin or {}).items():
        e = compute_cross_venue_funding_edge(
            coin, venue_rates,
            round_trip_cost_bps=round_trip_cost_bps,
            min_net_edge_bps_per_hour=min_net_edge_bps_per_hour,
        )
        if e is not None and e.reason == "CROSS_VENUE_FUNDING_EDGE":
            edges.append(e)
    edges.sort(key=lambda x: -x.net_edge_bps_per_hour)
    return tuple(edges[:top])


__all__ = ["CrossVenueFundingEdge", "compute_cross_venue_funding_edge", "rank_cross_venue_edges"]
