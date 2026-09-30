"""
Fills honnêtes — simulation de remplissage depuis le carnet d'ordres réel.

Un backtest/paper qui fill au mid surestime les retours de 30 à 100%.
Ici, chaque fill paper:
- traverse le spread (un BUY paie l'ask, jamais le mid),
- marche le carnet niveau par niveau → prix VWAP réel,
- refuse si la profondeur est insuffisante (max 10% du book),
- ajoute une pénalité de latence configurable,
- est etiquete data_source (REAL_INDEXER / LEGACY_ARTIFICIAL / FIXTURE):
  un fill non reel ne doit JAMAIS etre compte dans un PnL live.

PAPER-ONLY. Aucun ordre réel n'est envoyé — on simule seulement
ce qu'un ordre AURAIT payé.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DATA_SOURCE_REAL = "REAL_INDEXER"
DATA_SOURCE_DEMO = "LEGACY_ARTIFICIAL"
DATA_SOURCE_FIXTURE = "FIXTURE"
DATA_SOURCE_FALLBACK = "FALLBACK_ESTIMATED"

DEFAULT_MAX_PARTICIPATION = 0.10   # max 10% de la profondeur visible
DEFAULT_LATENCY_EXTRA_BPS = 2.0    # pénalité adverse de latence
DEFAULT_BOOK_DEPTH_LEVELS = 20


@dataclass
class BookLevel:
    price: float
    size: float

    @property
    def notional(self) -> float:
        return self.price * self.size


@dataclass
class FillResult:
    ok: bool
    fill_price: float = 0.0          # VWAP payé (latence incluse)
    mid_price: float = 0.0
    slippage_bps: float = 0.0        # vs mid, signé adverse (>0 = on paie plus)
    spread_bps: float = 0.0
    depth_participation: float = 0.0  # part de la profondeur consommée
    levels_consumed: int = 0
    data_source: str = DATA_SOURCE_REAL
    reason: str = ""                  # si refus

    @property
    def refused(self) -> bool:
        return not self.ok


def parse_orderbook(raw: dict) -> tuple[list[BookLevel], list[BookLevel]]:
    """
    Parse la réponse /v4/orderbooks/perpetualMarket/{id}.
    Formats tolérés: [{"price": "..", "size": ".."}] ou [["price","size"]].
    Retourne (bids triés desc, asks triés asc).
    """
    def _parse(side: list) -> list[BookLevel]:
        out: list[BookLevel] = []
        for lvl in side or []:
            try:
                if isinstance(lvl, dict):
                    p, s = float(lvl["price"]), float(lvl["size"])
                else:
                    p, s = float(lvl[0]), float(lvl[1])
                if p > 0 and s > 0:
                    out.append(BookLevel(p, s))
            except (KeyError, IndexError, TypeError, ValueError):
                continue
        return out

    bids = sorted(_parse(raw.get("bids", [])), key=lambda x: -x.price)
    asks = sorted(_parse(raw.get("asks", [])), key=lambda x: x.price)
    return bids, asks


def synthetic_orderbook(
    mid_price: float, spread_bps: float = 6.0, depth_notional: float = 500_000.0,
) -> dict:
    """Carnet synthétique pour le mode DÉMO uniquement. Étiqueté DEMO en aval."""
    half = mid_price * spread_bps / 2 / 10_000
    bids, asks = [], []
    for i in range(10):
        step = half * (1 + i)
        size = (depth_notional / 10) / max(1e-9, mid_price)
        bids.append({"price": str(mid_price - step), "size": str(size)})
        asks.append({"price": str(mid_price + step), "size": str(size)})
    return {"bids": bids, "asks": asks}


def simulate_market_fill(
    orderbook_raw: dict,
    side: str,
    notional_usdc: float,
    *,
    max_participation: float = DEFAULT_MAX_PARTICIPATION,
    latency_extra_bps: float = DEFAULT_LATENCY_EXTRA_BPS,
    depth_levels: int = DEFAULT_BOOK_DEPTH_LEVELS,
    data_source: str = DATA_SOURCE_REAL,
) -> FillResult:
    """
    Simuler un ordre market PAPER de `notional_usdc` côté `side` (BUY/SELL).

    Refus (FillResult.ok=False) si:
    - carnet vide/invalide                    → NO_ORDERBOOK
    - notional > max_participation × profondeur → INSUFFICIENT_DEPTH
    - profondeur insuffisante pour tout remplir  → INSUFFICIENT_DEPTH
    """
    bids, asks = parse_orderbook(orderbook_raw)
    if not bids or not asks:
        return FillResult(ok=False, reason="NO_ORDERBOOK", data_source=data_source)

    best_bid, best_ask = bids[0].price, asks[0].price
    if best_ask <= best_bid:
        return FillResult(ok=False, reason="CROSSED_BOOK", data_source=data_source)

    mid = (best_bid + best_ask) / 2
    spread_bps = (best_ask - best_bid) / mid * 10_000

    is_buy = side.upper() in ("BUY", "LONG")
    levels = (asks if is_buy else bids)[:depth_levels]
    total_depth = sum(lv.notional for lv in levels)

    if notional_usdc <= 0:
        return FillResult(ok=False, reason="ZERO_NOTIONAL", data_source=data_source)
    if total_depth <= 0 or notional_usdc > max_participation * total_depth:
        return FillResult(
            ok=False,
            mid_price=mid,
            spread_bps=spread_bps,
            reason=(
                f"INSUFFICIENT_DEPTH: notional={notional_usdc:.0f} > "
                f"{max_participation:.0%} × depth={total_depth:.0f}"
            ),
            data_source=data_source,
        )

    remaining = notional_usdc
    qty = 0.0
    consumed = 0
    for lv in levels:
        take_notional = min(remaining, lv.notional)
        qty += take_notional / lv.price
        remaining -= take_notional
        consumed += 1
        if remaining <= 1e-9:
            break

    if remaining > 1e-9 or qty <= 0:
        return FillResult(
            ok=False, mid_price=mid, spread_bps=spread_bps,
            reason="INSUFFICIENT_DEPTH: book épuisé", data_source=data_source,
        )

    vwap = notional_usdc / qty
    # Pénalité de latence: toujours adverse
    latency_mult = latency_extra_bps / 10_000
    vwap_with_latency = vwap * (1 + latency_mult) if is_buy else vwap * (1 - latency_mult)

    slippage_bps = (
        (vwap_with_latency - mid) / mid * 10_000 if is_buy
        else (mid - vwap_with_latency) / mid * 10_000
    )

    return FillResult(
        ok=True,
        fill_price=vwap_with_latency,
        mid_price=mid,
        slippage_bps=slippage_bps,
        spread_bps=spread_bps,
        depth_participation=notional_usdc / total_depth,
        levels_consumed=consumed,
        data_source=data_source,
    )
