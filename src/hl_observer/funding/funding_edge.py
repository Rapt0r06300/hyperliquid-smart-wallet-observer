"""Estimateur d'edge net pour le funding — met le funding sur l'ÉCHELLE COMMUNE.

Trou trouvé: FundingSignal ne porte que (coin, decision, z_score) — AUCUN edge net.
Le tableau unifié classe par edge net après coûts ; sans edge, le funding ne peut
pas être comparé au copy/arbitrage. Ce module convertit un taux de funding en edge
net attendu (accrual sur la durée de détention − coûts aller-retour), pour que les
opportunités funding entrent dans le board sur la même échelle.

Modèle honnête et conservateur: edge net = |taux/h| × heures_détention − coûts.
Un funding delta-neutre encaisse le taux horaire récurrent ; on retranche les coûts
d'entrée+sortie des deux jambes. Réutilise apr_rotation pour l'APR (affichage).
Pur, déterministe, paper-only.
"""

from __future__ import annotations

from hl_observer.funding.apr_rotation import annualized_yield_pct


def funding_net_edge_bps(
    *, rate_bps_per_hour: float, holding_hours: float = 8.0, round_trip_cost_bps: float = 6.0,
) -> float:
    """Edge net attendu (bps) d'une position funding delta-neutre tenue holding_hours.

    accrual brut = |taux/h| × heures ; net = brut − coûts aller-retour (2 jambes).
    """
    gross = abs(float(rate_bps_per_hour)) * max(0.0, float(holding_hours))
    return round(gross - max(0.0, float(round_trip_cost_bps)), 4)


def funding_receive_side(rate_bps_per_hour: float) -> str:
    """Côté qui ENCAISSE le funding: taux positif → les longs paient → on SHORT."""
    r = float(rate_bps_per_hour)
    return "SHORT" if r > 0 else ("LONG" if r < 0 else "NEUTRAL")


def funding_opportunity_edge(
    *, rate_bps_per_hour: float, holding_hours: float = 8.0,
    round_trip_cost_bps: float = 6.0, min_apr_pct: float | None = None,
) -> dict:
    """Vue complète pour le board: net_edge_bps, côté encaisseur, APR, tradeable.

    tradeable = edge net strictement positif (et |APR| ≥ min_apr_pct si fourni).
    Honnête: un taux qui ne couvre pas les coûts → net ≤ 0 → non tradeable.
    """
    edge = funding_net_edge_bps(
        rate_bps_per_hour=rate_bps_per_hour, holding_hours=holding_hours,
        round_trip_cost_bps=round_trip_cost_bps,
    )
    apr = annualized_yield_pct(rate_bps_per_hour)
    tradeable = edge > 0.0 and (min_apr_pct is None or abs(apr) >= float(min_apr_pct))
    return {
        "net_edge_bps": edge,
        "side": funding_receive_side(rate_bps_per_hour),
        "apr_pct": apr,
        "tradeable": bool(tradeable),
    }


__all__ = ["funding_net_edge_bps", "funding_receive_side", "funding_opportunity_edge"]
