from __future__ import annotations

import math
import re

from hl_observer.scanner.scanner_models import WalletPriorityInput, WalletPriorityScore

WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def score_wallet_priority(data: WalletPriorityInput) -> WalletPriorityScore:
    """Score a wallet for scarce read-only scan budget.

    This is not a trade score. It only decides which wallets deserve the next
    observation slot.
    """

    wallet = str(data.wallet_address or "").strip()
    if "..." in wallet:
        return WalletPriorityScore(
            wallet_address=wallet,
            source=data.source,
            priority_score=0.0,
            status="REJECTED",
            reasons=["TRUNCATED_WALLET_ADDRESS"],
        )
    if not WALLET_RE.fullmatch(wallet):
        return WalletPriorityScore(
            wallet_address=wallet,
            source=data.source,
            priority_score=0.0,
            status="REJECTED",
            reasons=["INVALID_WALLET_ADDRESS"],
        )

    recency_score = _recency_score(data.last_seen_ms, data.now_ms)
    activity_score = min(25.0, math.log1p(max(0, data.trades_count)) * 6.0)
    notional_score = min(18.0, math.log1p(max(0.0, data.observed_notional_usdt)) / math.log(10) * 3.0)
    quality_score = _clamp(data.wallet_quality_score, 0.0, 100.0) * 0.18
    consistency_score = _clamp(data.consistency_score, 0.0, 100.0) * 0.12
    copyability_score = _clamp(data.copyability_score, 0.0, 100.0) * 0.15
    consensus_score = min(8.0, max(0, data.consensus_hits) * 2.0)
    source_health_score = _clamp(data.source_health_score, 0.0, 1.0) * 8.0

    one_big_win_penalty = _clamp(data.one_big_win_risk, 0.0, 1.0) * 18.0
    drawdown_penalty = min(16.0, max(0.0, data.drawdown_pct) * 0.32)
    inactive_penalty = _clamp(data.inactive_penalty, 0.0, 30.0)

    score = (
        recency_score
        + activity_score
        + notional_score
        + quality_score
        + consistency_score
        + copyability_score
        + consensus_score
        + source_health_score
        - one_big_win_penalty
        - drawdown_penalty
        - inactive_penalty
    )
    reasons: list[str] = []
    if data.one_big_win_risk >= 0.65:
        reasons.append("ONE_BIG_WIN_RISK")
    if data.drawdown_pct >= 35.0:
        reasons.append("MAX_DRAWDOWN_TOO_HIGH")
    if recency_score <= 2.0:
        reasons.append("INACTIVE_WALLET")
    if data.copyability_score and data.copyability_score < 40.0:
        reasons.append("LOW_COPYABILITY")

    final = round(_clamp(score, 0.0, 100.0), 6)
    status = "PRIORITIZED" if final >= 35.0 and not {"ONE_BIG_WIN_RISK", "MAX_DRAWDOWN_TOO_HIGH"} & set(reasons) else "WATCH_ONLY"
    return WalletPriorityScore(
        wallet_address=wallet.lower(),
        source=data.source,
        priority_score=final,
        status=status,
        reasons=reasons,
        components={
            "recency": round(recency_score, 6),
            "activity": round(activity_score, 6),
            "notional": round(notional_score, 6),
            "quality": round(quality_score, 6),
            "consistency": round(consistency_score, 6),
            "copyability": round(copyability_score, 6),
            "consensus": round(consensus_score, 6),
            "source_health": round(source_health_score, 6),
            "one_big_win_penalty": round(one_big_win_penalty, 6),
            "drawdown_penalty": round(drawdown_penalty, 6),
            "inactive_penalty": round(inactive_penalty, 6),
        },
    )


def _recency_score(last_seen_ms: int | None, now_ms: int) -> float:
    if not last_seen_ms or not now_ms:
        return 0.0
    age_ms = max(0, now_ms - last_seen_ms)
    if age_ms <= 10_000:
        return 18.0
    if age_ms <= 60_000:
        return 14.0
    if age_ms <= 5 * 60_000:
        return 9.0
    if age_ms <= 60 * 60_000:
        return 4.0
    return 0.0


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))

