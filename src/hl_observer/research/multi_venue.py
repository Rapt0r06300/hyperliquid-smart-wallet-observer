"""ALPHA P18/P54 — MULTI-VENUE leader observer (READ-ONLY) + NBBO synthétique.

Normalise BBO/L2/trades de plusieurs venues (Binance/Bybit/OKX/Coinbase) dans un format commun, READ-ONLY.
Hyperliquid reste la seule venue PAPER d'exécution. Construit un **NBBO exécutable synthétique** (meilleur
bid / meilleur ask entre venues) comme référence de prix/signaux — pas d'exécution multi-venue. Les flux
externes ne sont pas branchés ici (BLOCKED_EXTERNAL) ; la normalisation et le NBBO sont codés/testés.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

BLOCKED = "BLOCKED_EXTERNAL"
UNMEASURABLE = "UNMEASURABLE"


def normaliser_bbo(venue: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    """BBO canonique {venue, coin, bid, ask, bid_sz, ask_sz, ts_ms} depuis un format brut par venue."""
    return {"venue": venue, "coin": raw.get("coin"),
            "bid": raw.get("bid"), "ask": raw.get("ask"),
            "bid_sz": raw.get("bid_sz"), "ask_sz": raw.get("ask_sz"),
            "ts_ms": raw.get("ts_ms")}


def nbbo(bbos: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """NBBO exécutable : meilleur bid (max) et meilleur ask (min) entre venues fraîches. READ-ONLY (référence)."""
    bids = [(b["bid"], b.get("venue")) for b in bbos if isinstance(b.get("bid"), (int, float))]
    asks = [(b["ask"], b.get("venue")) for b in bbos if isinstance(b.get("ask"), (int, float))]
    if not bids or not asks:
        return {"nbbo_bid": UNMEASURABLE, "nbbo_ask": UNMEASURABLE, "spread_bps": UNMEASURABLE}
    best_bid = max(bids); best_ask = min(asks)
    mid = (best_bid[0] + best_ask[0]) / 2.0
    spread_bps = (best_ask[0] - best_bid[0]) / mid * 1e4 if mid > 0 else UNMEASURABLE
    return {"nbbo_bid": best_bid[0], "bid_venue": best_bid[1], "nbbo_ask": best_ask[0], "ask_venue": best_ask[1],
            "mid": round(mid, 8), "spread_bps": (round(spread_bps, 4) if isinstance(spread_bps, float) else spread_bps),
            "croise": bool(best_bid[0] > best_ask[0])}


def flux_externe(venue: str) -> dict[str, Any]:
    return {"statut": BLOCKED, "venue": venue, "manque": "flux read-only %s (cote user)" % venue}


__all__ = ["normaliser_bbo", "nbbo", "flux_externe", "BLOCKED", "UNMEASURABLE"]
