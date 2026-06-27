"""Wallet intelligence V2 for Hyperliquid paper simulation.

This module turns observed, historical wallet outcomes into a copyability score.
It never fabricates performance and never emits a trading recommendation: a
high score is only a research input for the local paper simulator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from math import sqrt


@dataclass(frozen=True, slots=True)
class WalletScoreV2Config:
    min_history_days: float = 7.0
    min_closed_pnl_points: int = 12
    min_consistency: float = 0.60
    max_drawdown_pct: float = 0.35
    max_pnl_concentration: float = 0.30
    min_copyability_score: float = 50.0


@dataclass(frozen=True, slots=True)
class WalletPerformanceSample:
    wallet: str
    coin: str
    closed_pnl_usdc: float
    timestamp_ms: int
    notional_usdc: float | None = None
    fee_usdc: float | None = None
    holding_time_ms: int | None = None


@dataclass(frozen=True, slots=True)
class WalletScoreV2:
    wallet: str
    status: str
    copyability_score: float
    sample_confidence: float
    closed_pnl_points: int
    history_days: float
    total_closed_pnl_usdc: float
    win_rate: float
    profit_factor: float | None
    consistency_score: float
    max_drawdown_usdc: float
    max_drawdown_pct: float
    pnl_concentration: float
    one_big_win_risk: bool
    per_coin_stability: float
    avg_fee_bps: float | None
    reasons: tuple[str, ...] = field(default_factory=tuple)
    score_hash: str = ""

    @property
    def accepted_for_shortlist(self) -> bool:
        return self.status == "SHORTLISTED"


def score_wallet_v2(
    wallet: str,
    samples: list[WalletPerformanceSample],
    *,
    now_ms: int | None = None,
    config: WalletScoreV2Config | None = None,
) -> WalletScoreV2:
    """Score a wallet from observed samples only."""

    cfg = config or WalletScoreV2Config()
    clean = [s for s in samples if s.wallet.lower() == wallet.lower()]
    clean.sort(key=lambda s: s.timestamp_ms)

    if not clean:
        return _empty_score(wallet, "INSUFFICIENT_DATA", ("INSUFFICIENT_CLOSED_PNL",))

    pnl = [float(s.closed_pnl_usdc) for s in clean]
    timestamps = [int(s.timestamp_ms) for s in clean]
    ref_now = int(now_ms if now_ms is not None else max(timestamps))
    history_days = max(0.0, (min(ref_now, max(timestamps)) - min(timestamps)) / 86_400_000.0)
    wins = [x for x in pnl if x > 0]
    losses = [abs(x) for x in pnl if x < 0]
    total_pnl = sum(pnl)
    win_rate = len(wins) / len(pnl) if pnl else 0.0
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    profit_factor = None if gross_loss == 0 else gross_profit / gross_loss
    concentration = max(wins) / gross_profit if gross_profit > 0 else 1.0
    one_big_win = concentration > cfg.max_pnl_concentration
    drawdown_usdc, drawdown_pct = _max_drawdown(pnl)
    consistency = _consistency_score(pnl)
    per_coin_stability = _per_coin_stability(clean)
    sample_confidence = _sample_confidence(len(clean), history_days, cfg)
    avg_fee_bps = _avg_fee_bps(clean)

    reasons: list[str] = []
    if history_days < cfg.min_history_days:
        reasons.append("INSUFFICIENT_HISTORY")
    if len(clean) < cfg.min_closed_pnl_points:
        reasons.append("INSUFFICIENT_CLOSED_PNL")
    if concentration > cfg.max_pnl_concentration:
        reasons.append("PNL_CONCENTRATION_TOO_HIGH")
        reasons.append("ONE_BIG_WIN_RISK")
    if consistency < cfg.min_consistency:
        reasons.append("LOW_CONSISTENCY")
    if drawdown_pct > cfg.max_drawdown_pct:
        reasons.append("MAX_DRAWDOWN_TOO_HIGH")

    score = _copyability_score(
        win_rate=win_rate,
        profit_factor=profit_factor,
        consistency=consistency,
        sample_confidence=sample_confidence,
        pnl_concentration=concentration,
        drawdown_pct=drawdown_pct,
        per_coin_stability=per_coin_stability,
        total_pnl=total_pnl,
    )
    if score < cfg.min_copyability_score:
        reasons.append("COPYABILITY_TOO_LOW")

    status = "SHORTLISTED" if not reasons else "REJECTED"
    if any(r.startswith("INSUFFICIENT") for r in reasons):
        status = "INSUFFICIENT_DATA"

    unique_reasons = tuple(dict.fromkeys(reasons))
    material = "|".join(
        [
            wallet.lower(),
            status,
            str(len(clean)),
            f"{history_days:.6f}",
            f"{total_pnl:.6f}",
            f"{score:.6f}",
            ",".join(unique_reasons),
        ]
    )
    return WalletScoreV2(
        wallet=wallet,
        status=status,
        copyability_score=round(score, 6),
        sample_confidence=round(sample_confidence, 6),
        closed_pnl_points=len(clean),
        history_days=round(history_days, 6),
        total_closed_pnl_usdc=round(total_pnl, 6),
        win_rate=round(win_rate, 6),
        profit_factor=None if profit_factor is None else round(profit_factor, 6),
        consistency_score=round(consistency, 6),
        max_drawdown_usdc=round(drawdown_usdc, 6),
        max_drawdown_pct=round(drawdown_pct, 6),
        pnl_concentration=round(concentration, 6),
        one_big_win_risk=one_big_win,
        per_coin_stability=round(per_coin_stability, 6),
        avg_fee_bps=None if avg_fee_bps is None else round(avg_fee_bps, 6),
        reasons=unique_reasons,
        score_hash="wsv2:" + sha256(material.encode("utf-8")).hexdigest(),
    )


def _empty_score(wallet: str, status: str, reasons: tuple[str, ...]) -> WalletScoreV2:
    material = f"{wallet.lower()}|{status}|{','.join(reasons)}"
    return WalletScoreV2(
        wallet=wallet,
        status=status,
        copyability_score=0.0,
        sample_confidence=0.0,
        closed_pnl_points=0,
        history_days=0.0,
        total_closed_pnl_usdc=0.0,
        win_rate=0.0,
        profit_factor=None,
        consistency_score=0.0,
        max_drawdown_usdc=0.0,
        max_drawdown_pct=0.0,
        pnl_concentration=1.0,
        one_big_win_risk=True,
        per_coin_stability=0.0,
        avg_fee_bps=None,
        reasons=reasons,
        score_hash="wsv2:" + sha256(material.encode("utf-8")).hexdigest(),
    )


def _max_drawdown(pnl: list[float]) -> tuple[float, float]:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for x in pnl:
        equity += x
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    positive_base = max(sum(x for x in pnl if x > 0), 1.0)
    return max_dd, max_dd / positive_base


def _consistency_score(pnl: list[float]) -> float:
    if not pnl:
        return 0.0
    wins = sum(1 for x in pnl if x > 0) / len(pnl)
    if len(pnl) < 2:
        return wins * 0.5
    mean = sum(pnl) / len(pnl)
    variance = sum((x - mean) ** 2 for x in pnl) / (len(pnl) - 1)
    stdev = sqrt(max(0.0, variance))
    stability = 1.0 / (1.0 + (stdev / max(abs(mean), 1.0)))
    return _clamp(0.65 * wins + 0.35 * stability)


def _per_coin_stability(samples: list[WalletPerformanceSample]) -> float:
    by_coin: dict[str, float] = {}
    for s in samples:
        by_coin[s.coin.upper()] = by_coin.get(s.coin.upper(), 0.0) + abs(float(s.closed_pnl_usdc))
    total_abs = sum(by_coin.values())
    if total_abs <= 0:
        return 0.0
    largest_share = max(by_coin.values()) / total_abs
    return _clamp(1.0 - largest_share)


def _sample_confidence(count: int, history_days: float, cfg: WalletScoreV2Config) -> float:
    sample_part = _clamp(count / max(1, cfg.min_closed_pnl_points * 2))
    history_part = _clamp(history_days / max(1.0, cfg.min_history_days * 2))
    return _clamp(0.55 * sample_part + 0.45 * history_part)


def _avg_fee_bps(samples: list[WalletPerformanceSample]) -> float | None:
    values: list[float] = []
    for s in samples:
        if s.fee_usdc is None or not s.notional_usdc or s.notional_usdc <= 0:
            continue
        values.append(abs(float(s.fee_usdc)) / float(s.notional_usdc) * 10_000.0)
    if not values:
        return None
    return sum(values) / len(values)


def _copyability_score(
    *,
    win_rate: float,
    profit_factor: float | None,
    consistency: float,
    sample_confidence: float,
    pnl_concentration: float,
    drawdown_pct: float,
    per_coin_stability: float,
    total_pnl: float,
) -> float:
    pf_component = 0.5 if profit_factor is None else _clamp(profit_factor / 3.0)
    pnl_component = _clamp(total_pnl / 5_000.0)
    concentration_health = _clamp(1.0 - pnl_concentration)
    drawdown_health = _clamp(1.0 - drawdown_pct)
    raw = (
        0.18 * _clamp(win_rate)
        + 0.16 * pf_component
        + 0.18 * _clamp(consistency)
        + 0.16 * _clamp(sample_confidence)
        + 0.12 * concentration_health
        + 0.10 * drawdown_health
        + 0.06 * _clamp(per_coin_stability)
        + 0.04 * pnl_component
    )
    return _clamp(raw) * 100.0


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


__all__ = [
    "WalletPerformanceSample",
    "WalletScoreV2",
    "WalletScoreV2Config",
    "score_wallet_v2",
]
