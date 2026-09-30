"""Smart-money filter with exact V9 thresholds (S5 — MrFadiAi A2).

A wallet is "smart money" only if it clears ALL of:
  * win-rate         >= 60%   (0.60)
  * total PnL        >= $500
  * profit-factor    >= 1.5
  * consistency      >= 70%   (0.70)
  * one-big-win share <= 30%  (0.30)   (no single trade carries the record)

Rates/shares are fractions in [0, 1]. Deny-by-default: any missing or failing
metric excludes the wallet.

SAFETY: scoring is read-only analysis of public data.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SmartMoneyThresholds:
    min_win_rate: float = 0.60
    min_total_pnl_usdc: float = 500.0
    min_profit_factor: float = 1.5
    min_consistency: float = 0.70
    max_one_big_win_share: float = 0.30


@dataclass(frozen=True, slots=True)
class WalletStats:
    win_rate: float | None
    total_pnl_usdc: float | None
    profit_factor: float | None
    consistency: float | None
    one_big_win_share: float | None


@dataclass(frozen=True, slots=True)
class SmartMoneyResult:
    is_smart_money: bool
    failures: tuple[str, ...] = field(default_factory=tuple)


def is_smart_money(
    stats: WalletStats,
    thresholds: SmartMoneyThresholds | None = None,
) -> SmartMoneyResult:
    t = thresholds or SmartMoneyThresholds()
    failures: list[str] = []

    if stats.win_rate is None or stats.win_rate < t.min_win_rate:
        failures.append("WIN_RATE")
    if stats.total_pnl_usdc is None or stats.total_pnl_usdc < t.min_total_pnl_usdc:
        failures.append("TOTAL_PNL")
    if stats.profit_factor is None or stats.profit_factor < t.min_profit_factor:
        failures.append("PROFIT_FACTOR")
    if stats.consistency is None or stats.consistency < t.min_consistency:
        failures.append("CONSISTENCY")
    if stats.one_big_win_share is None or stats.one_big_win_share > t.max_one_big_win_share:
        failures.append("ONE_BIG_WIN")

    return SmartMoneyResult(is_smart_money=not failures, failures=tuple(failures))
