"""V14 #173 — Leaderboard scraping robustness + smart-money thresholds applied live.

Pure validation + filtering layer on top of the existing leaderboard scrapers. It drops
malformed rows (robustness), dedupes by address, and applies exact smart-money thresholds
so only genuine quality leaders survive. read-only / paper-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class LeaderRow:
    address: str
    pnl_usd: float
    roi: float
    winrate: float
    trades: int
    age_days: float = 0.0


@dataclass(frozen=True, slots=True)
class SmartMoneyThresholds:
    min_pnl_usd: float = 50_000.0
    min_roi: float = 0.10
    min_winrate: float = 0.50
    min_trades: int = 20
    max_age_days: float = 30.0


def _valid_addr(addr: str) -> bool:
    a = str(addr or "").strip().lower()
    return a.startswith("0x") and len(a) == 42 and all(c in "0123456789abcdef" for c in a[2:])


def validate_leaderboard_rows(rows: Sequence[LeaderRow]) -> tuple[list[LeaderRow], list[tuple[str, str]]]:
    """Drop rows with invalid address or non-finite/negative-where-impossible numbers."""
    good: list[LeaderRow] = []
    bad: list[tuple[str, str]] = []
    for r in rows:
        if not _valid_addr(r.address):
            bad.append((str(r.address), "BAD_ADDRESS"))
            continue
        try:
            if any(v != v for v in (r.pnl_usd, r.roi, r.winrate)):  # NaN check
                bad.append((r.address, "NAN_FIELD"))
                continue
        except TypeError:
            bad.append((r.address, "NON_NUMERIC"))
            continue
        if int(r.trades) < 0:
            bad.append((r.address, "NEGATIVE_TRADES"))
            continue
        good.append(r)
    return good, bad


def apply_smart_money_filter(
    rows: Sequence[LeaderRow],
    thresholds: SmartMoneyThresholds | None = None,
) -> tuple[list[LeaderRow], list[tuple[str, str]]]:
    """Validate, dedupe by address (keep best PnL), then keep only quality leaders."""
    th = thresholds or SmartMoneyThresholds()
    good, rejected = validate_leaderboard_rows(rows)
    # dedupe by address: keep the highest PnL row
    best: dict[str, LeaderRow] = {}
    for r in good:
        key = r.address.lower()
        if key not in best or r.pnl_usd > best[key].pnl_usd:
            best[key] = r
    kept: list[LeaderRow] = []
    for r in best.values():
        if r.pnl_usd < th.min_pnl_usd:
            rejected.append((r.address, "PNL_BELOW_MIN"))
        elif r.roi < th.min_roi:
            rejected.append((r.address, "ROI_BELOW_MIN"))
        elif r.winrate < th.min_winrate:
            rejected.append((r.address, "WINRATE_BELOW_MIN"))
        elif int(r.trades) < th.min_trades:
            rejected.append((r.address, "TOO_FEW_TRADES"))
        elif th.max_age_days and r.age_days > th.max_age_days:
            rejected.append((r.address, "STALE_LEADER"))
        else:
            kept.append(r)
    kept.sort(key=lambda r: -float(r.pnl_usd))
    return kept, rejected


__all__ = ["LeaderRow", "SmartMoneyThresholds", "validate_leaderboard_rows", "apply_smart_money_filter"]
