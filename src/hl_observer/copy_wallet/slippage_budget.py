from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.copy_wallet.wallet_tier import WalletTier


@dataclass(frozen=True, slots=True)
class SlippageBudgetDecision:
    accepted: bool
    requested_budget_bps: float
    tier_budget_bps: float
    total_degradation_bps: float
    reason_codes: tuple[str, ...] = field(default_factory=tuple)


def evaluate_slippage_budget(
    *,
    requested_budget_bps: float,
    tier: WalletTier,
    spread_bps: float,
    estimated_slippage_bps: float,
    latency_penalty_bps: float = 0.0,
    max_total_degradation_bps: float = 40.0,
) -> SlippageBudgetDecision:
    """Paper-only custom slippage budget gate for wallet mirroring.

    The pattern is intentionally simple and hot-path friendly: every candidate
    carries a budget, the wallet tier may tighten it, and observed spread plus
    slippage plus latency must fit inside both that budget and the global cap.
    """

    requested = max(0.0, float(requested_budget_bps or 0.0))
    tier_budget = max(0.0, float(tier.slippage_budget_bps or 0.0))
    effective_budget = min(requested if requested > 0 else tier_budget, tier_budget if tier_budget > 0 else requested)
    total = (
        max(0.0, float(spread_bps or 0.0))
        + max(0.0, float(estimated_slippage_bps or 0.0))
        + max(0.0, float(latency_penalty_bps or 0.0))
    )
    reasons: list[str] = []
    if effective_budget <= 0:
        reasons.append("SLIPPAGE_BUDGET_MISSING")
    if total > effective_budget:
        reasons.append("SLIPPAGE_BUDGET_EXCEEDED")
    if total > max(0.0, float(max_total_degradation_bps or 0.0)):
        reasons.append("COPY_DEGRADATION_TOO_HIGH")
    return SlippageBudgetDecision(
        accepted=not reasons,
        requested_budget_bps=round(requested, 8),
        tier_budget_bps=round(tier_budget, 8),
        total_degradation_bps=round(total, 8),
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


__all__ = ["SlippageBudgetDecision", "evaluate_slippage_budget"]
