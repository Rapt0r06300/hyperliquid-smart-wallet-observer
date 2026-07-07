"""P3 — Classifieur de comportement leader (ne copier que les SWING).

73% des bots perdent à cause de l'exécution: copier un HFT/scalper/market-maker
est perdant par construction (latence HL 200-500ms). On classe chaque leader
depuis ses fills publics et on ne garde que les SWING (holding > seuil). Pur.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

HFT, SCALPER, MARKET_MAKER, MANIPULATOR, SWING, UNKNOWN = (
    "HFT", "SCALPER", "MARKET_MAKER", "MANIPULATOR", "SWING", "UNKNOWN"
)
COPYABLE = {SWING}


@dataclass(frozen=True, slots=True)
class LeaderBehavior:
    wallet: str
    kind: str
    copyable: bool
    median_hold_sec: float
    trades_per_hour: float
    both_sides_ratio: float
    leverage_changes: int
    reason: str


def _holds_sec(fills: list[dict]) -> list[float]:
    """Durées de détention estimées: temps entre une ouverture et sa clôture par coin."""
    opens: dict[str, float] = {}
    holds: list[float] = []
    for f in sorted(fills, key=lambda x: float(x.get("ts_ms") or 0)):
        coin = str(f.get("coin") or "").upper()
        act = str(f.get("action") or "").upper()
        ts = float(f.get("ts_ms") or 0) / 1000.0
        if any(t in act for t in ("OPEN", "ADD", "INCREASE", "BUY")) and coin not in opens:
            opens[coin] = ts
        elif any(t in act for t in ("CLOSE", "REDUCE", "EXIT", "SELL")) and coin in opens:
            holds.append(max(0.0, ts - opens.pop(coin)))
    return holds


def classify_leader(
    wallet: str,
    fills: list[dict],
    *,
    window_sec: float = 3600.0,
    swing_min_hold_sec: float = 900.0,
    scalp_max_hold_sec: float = 120.0,
    hft_trades_per_hour: float = 120.0,
    mm_both_sides_ratio: float = 0.4,
) -> LeaderBehavior:
    fills = [f for f in (fills or []) if isinstance(f, dict)]
    n = len(fills)
    if n < 3:
        return LeaderBehavior(str(wallet), UNKNOWN, False, 0.0, 0.0, 0.0, 0, "INSUFFICIENT_FILLS")
    span_h = max(window_sec, (max(float(f.get("ts_ms") or 0) for f in fills) - min(float(f.get("ts_ms") or 0) for f in fills)) / 1000.0) / 3600.0
    tph = n / span_h if span_h > 0 else n
    holds = _holds_sec(fills)
    med_hold = median(holds) if holds else 0.0
    longs = sum(1 for f in fills if "LONG" in str(f.get("side") or "").upper() or "BUY" in str(f.get("action") or "").upper())
    shorts = n - longs
    both_sides = min(longs, shorts) / max(1, n)
    lev_changes = sum(1 for f in fills if f.get("leverage_changed") is True)

    if tph >= hft_trades_per_hour:
        kind, reason = HFT, "TOO_MANY_TRADES_PER_HOUR"
    elif both_sides >= mm_both_sides_ratio:
        kind, reason = MARKET_MAKER, "HOLDS_BOTH_SIDES_SIMULTANEOUSLY"
    elif lev_changes >= max(3, n // 3):
        kind, reason = MANIPULATOR, "FREQUENT_LEVERAGE_CHANGES"
    elif holds and med_hold <= scalp_max_hold_sec:
        kind, reason = SCALPER, "HOLD_TOO_SHORT"
    elif holds and med_hold >= swing_min_hold_sec:
        kind, reason = SWING, "SWING_COPYABLE"
    else:
        kind, reason = UNKNOWN, "AMBIGUOUS_HOLD_PROFILE"
    return LeaderBehavior(
        str(wallet), kind, kind in COPYABLE, round(med_hold, 2), round(tph, 3),
        round(both_sides, 3), int(lev_changes), reason,
    )


def filter_copyable_leaders(behaviors: list[LeaderBehavior]) -> tuple[str, ...]:
    return tuple(b.wallet for b in behaviors if b.copyable)


__all__ = ["HFT", "SCALPER", "MARKET_MAKER", "MANIPULATOR", "SWING", "UNKNOWN",
           "COPYABLE", "LeaderBehavior", "classify_leader", "filter_copyable_leaders"]
