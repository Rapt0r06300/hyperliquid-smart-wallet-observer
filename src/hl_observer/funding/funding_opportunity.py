"""Enrichit les signaux funding avec un edge net -> candidats pour le board unifié.

FundingSignal n'a pas d'edge (coin/decision/z_score seulement). Ici on joint chaque
signal à son taux (bps/heure) et on calcule l'edge net via funding_edge, produisant
un FundingOpportunity (coin, side encaisseur, net_edge_bps, apr) qui entre dans le
tableau unifié sur la MÊME échelle que copy/arbitrage.

Unité EXPLICITE: le taux est attendu en bps/heure (le caller convertit depuis le
cache). Honnête: un signal sans taux connu, ou dont l'edge net ne couvre pas les
coûts, est ignoré (jamais scoré à l'aveugle). Pur, paper-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hl_observer.funding.funding_edge import funding_opportunity_edge


@dataclass(frozen=True, slots=True)
class FundingOpportunity:
    coin: str
    side: str
    net_edge_bps: float
    apr_pct: float


def _g(obj: Any, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def enrich_funding_with_edge(
    signals: Any,
    rate_bps_per_hour_by_coin: dict[str, float] | None,
    *,
    holding_hours: float = 8.0,
    round_trip_cost_bps: float = 6.0,
    min_apr_pct: float | None = None,
    spike_only: bool = True,
) -> list[FundingOpportunity]:
    """Joint signaux funding + taux -> opportunités avec edge net. Ignore ce qui
    n'a pas de taux connu ou dont l'edge net ≤ 0 (honnête)."""
    rates = {str(k).upper(): float(v) for k, v in (rate_bps_per_hour_by_coin or {}).items()}
    out: list[FundingOpportunity] = []
    for s in signals or ():
        coin = str(_g(s, "coin", "") or "").upper()
        if not coin:
            continue
        if spike_only and str(_g(s, "decision", "") or "").upper() != "FUNDING_SPIKE":
            continue
        rate = rates.get(coin)
        if rate is None:
            continue                      # pas de taux -> ignoré (jamais inventé)
        e = funding_opportunity_edge(
            rate_bps_per_hour=rate, holding_hours=holding_hours,
            round_trip_cost_bps=round_trip_cost_bps, min_apr_pct=min_apr_pct,
        )
        if not e["tradeable"]:
            continue
        out.append(FundingOpportunity(coin, e["side"], e["net_edge_bps"], e["apr_pct"]))
    return out


# Conversion cache -> bps/heure. HL stocke le funding en FRACTION/heure (ex.
# 0.0000125/h) ; ×10000 -> bps/heure (0.125 bps/h). Le dernier taux connu par coin.
_RATE_FRACTION_TO_BPS = 10_000.0


def latest_funding_rate_bps_per_hour(coin: str):
    """Dernier taux de funding connu (bps/heure) depuis le cache, ou None."""
    try:
        from hl_observer.funding.funding_runtime_cache import recent_rates
        rates = recent_rates(str(coin))
    except Exception:
        return None
    if not rates:
        return None
    return float(rates[-1]) * _RATE_FRACTION_TO_BPS


def funding_rates_bps_for_coins(coins) -> dict:
    """{coin: bps/heure} pour les coins ayant un taux récent (sinon absent)."""
    out = {}
    for c in coins or ():
        r = latest_funding_rate_bps_per_hour(c)
        if r is not None:
            out[str(c).upper()] = r
    return out


__all__ = ["FundingOpportunity", "enrich_funding_with_edge", "latest_funding_rate_bps_per_hour", "funding_rates_bps_for_coins"]
