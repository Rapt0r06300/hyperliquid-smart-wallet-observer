"""
Qualité des leaders — n'agir que sur des wallets PROUVÉS gagnants.

READ-ONLY / PAPER-ONLY. Logique pure, testable. Sert la « sélectivité extrême » :
un consensus ne déclenche un paper trade que si assez de wallets participants ont
un historique prouvé (winrate, profit factor, échantillon suffisant). C'est la
version honnête, côté perps, du « peu d'erreurs » — pas une promesse de 98 %.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass
class LeaderThresholds:
    min_winrate: float = 0.45
    min_profit_factor: float = 1.3
    min_trades: int = 15


def qualifies_as_leader(
    winrate: Optional[float],
    profit_factor: Optional[float],
    trade_count: Optional[int],
    thresholds: Optional[LeaderThresholds] = None,
) -> bool:
    """True si le wallet est un gagnant PROUVÉ (assez de trades + winrate + PF)."""
    t = thresholds or LeaderThresholds()
    if (trade_count or 0) < t.min_trades:
        return False
    if (winrate or 0.0) < t.min_winrate:
        return False
    if (profit_factor or 0.0) < t.min_profit_factor:
        return False
    return True


def has_track_record(wallet: object) -> bool:
    """Le wallet a-t-il des métriques exploitables (≥1 trade mesuré) ?"""
    return (getattr(wallet, "trade_count", 0) or 0) > 0


def count_proven(
    addresses: Iterable[str],
    score_by_addr: dict,
    thresholds: Optional[LeaderThresholds] = None,
) -> int:
    """Compter, parmi `addresses`, les wallets prouvés gagnants (via score_by_addr)."""
    n = 0
    for a in addresses or []:
        w = score_by_addr.get(a)
        if w is None:
            continue
        if qualifies_as_leader(
            getattr(w, "winrate", 0.0),
            getattr(w, "profit_factor", 0.0),
            getattr(w, "trade_count", 0),
            thresholds,
        ):
            n += 1
    return n


def any_track_record(wallets: Iterable[object]) -> bool:
    """Au moins un wallet du lot a-t-il des métriques ? (sinon: ne pas gater)."""
    return any(has_track_record(w) for w in (wallets or []))



@dataclass
class MarketScore:
    """Score par marché pour un wallet donné."""
    market: str = ""
    trade_count: int = 0
    winrate: float = 0.0
    profit_factor: float = 0.0
    expectancy_usdc: float = 0.0
    net_pnl_usdc: float = 0.0
    recent_score: float = 0.0
    confidence: float = 0.0


def score_trades_by_market(
    closed_records: list[object],
    current_ts_ms: int = 0,
    recency_half_life_ms: int = 7 * 24 * 3600 * 1000,  # 7 jours
    confidence_full_trades: int = 20,
) -> dict[str, MarketScore]:
    """
    Calculer un MarketScore par marché à partir des trades fermés.
    
    closed_records: liste de dicts avec au minimum 'market', 'realizedPnl',
    et optionnellement 'closedAt' (ISO timestamp).
    """
    from collections import defaultdict
    import math

    by_market: dict[str, list[dict]] = defaultdict(list)
    def _get(rec: object, key: str, default: object = None) -> object:
        if isinstance(rec, dict):
            return rec.get(key, default)
        return getattr(rec, key, default)

    for rec in closed_records or []:
        m = (
            _get(rec, "market")
            or _get(rec, "ticker")
            or _get(rec, "market_id")
            or ""
        )
        if m:
            by_market[m].append(rec)

    scores: dict[str, MarketScore] = {}
    for market, trades in by_market.items():
        wins = 0
        losses = 0
        gross_win = 0.0
        gross_loss = 0.0
        total_pnl = 0.0
        for t in trades:
            pnl = float(
                _get(t, "realizedPnl", None)
                if _get(t, "realizedPnl", None) is not None
                else _get(t, "pnl_net", 0)
                or 0
            )
            total_pnl += pnl
            if pnl > 0:
                wins += 1
                gross_win += pnl
            elif pnl < 0:
                losses += 1
                gross_loss += abs(pnl)

        n = wins + losses
        wr = wins / n if n > 0 else 0.0
        pf = gross_win / gross_loss if gross_loss > 0 else (2.0 if gross_win > 0 else 0.0)
        exp = total_pnl / n if n > 0 else 0.0
        conf = min(1.0, n / max(1, confidence_full_trades))

        # Recency: poids exponentiel basé sur le trade le plus récent
        recent = 0.5
        if current_ts_ms > 0 and trades:
            latest_ms = 0
            for t in trades:
                ts_obj = _get(t, "closed_at_ms", None)
                if isinstance(ts_obj, (int, float)) and ts_obj > 0:
                    latest_ms = max(latest_ms, int(ts_obj))
                    continue
                ca = _get(t, "closedAt") or _get(t, "updatedAt") or ""
                if ca:
                    try:
                        from datetime import datetime, timezone
                        dt = datetime.fromisoformat(ca.replace("Z", "+00:00"))
                        ts = int(dt.timestamp() * 1000)
                        latest_ms = max(latest_ms, ts)
                    except Exception:
                        pass
            if latest_ms > 0:
                age_ms = max(0, current_ts_ms - latest_ms)
                recent = math.pow(0.5, age_ms / recency_half_life_ms)

        scores[market] = MarketScore(
            market=market,
            trade_count=n,
            winrate=wr,
            profit_factor=pf,
            expectancy_usdc=exp,
            net_pnl_usdc=total_pnl,
            recent_score=recent,
            confidence=conf,
        )

    return scores


__all__ = [
    "LeaderThresholds",
    "MarketScore",
    "qualifies_as_leader",
    "has_track_record",
    "count_proven",
    "any_track_record",
    "score_trades_by_market",
]
