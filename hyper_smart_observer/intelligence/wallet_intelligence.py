from __future__ import annotations

from dataclasses import dataclass, field

from hyper_smart_observer.intelligence.anti_luck_filters import one_big_win_risk, pnl_concentration_ratio


@dataclass(slots=True)
class WalletIntelligenceReport:
    wallet_address: str
    trades: int
    total_pnl: float
    winrate: float
    pnl_concentration: float
    one_big_win: bool
    quality_score: float
    copyability_score: float
    status: str
    risk_flags: list[str] = field(default_factory=list)


def analyze_wallet_pnls(wallet_address: str, pnls: list[float], *, min_trades: int = 10) -> WalletIntelligenceReport:
    trades = len(pnls)
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    total = sum(pnls)
    winrate = len(wins) / trades if trades else 0.0
    concentration = pnl_concentration_ratio(pnls)
    big_win = one_big_win_risk(pnls)
    flags: list[str] = []
    if trades < min_trades:
        flags.append("INSUFFICIENT_TRADES")
    if big_win:
        flags.append("ONE_BIG_WIN_RISK")
    if concentration > 0.55:
        flags.append("PNL_CONCENTRATION_TOO_HIGH")
    if total <= 0:
        flags.append("NON_POSITIVE_PNL")
    loss_penalty = min(30.0, abs(sum(losses)) / max(1.0, abs(total) + sum(wins)) * 30.0)
    quality = max(0.0, min(100.0, winrate * 50.0 + max(-20.0, total / 100.0) - concentration * 25.0 - loss_penalty))
    copyability = max(0.0, quality - (20.0 if big_win else 0.0) - (15.0 if trades < min_trades else 0.0))
    status = "WATCH_ONLY" if flags else "CANDIDATE"
    return WalletIntelligenceReport(
        wallet_address=wallet_address.lower(),
        trades=trades,
        total_pnl=round(total, 8),
        winrate=round(winrate, 6),
        pnl_concentration=round(concentration, 6),
        one_big_win=big_win,
        quality_score=round(quality, 6),
        copyability_score=round(copyability, 6),
        status=status,
        risk_flags=flags,
    )
