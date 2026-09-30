from __future__ import annotations

from collections.abc import Iterable

from hl_observer.scanner.scanner_models import (
    MissedOpportunity,
    MissedOpportunityReason,
    ScanBudget,
    ScanSelection,
    WalletPriorityScore,
)
from hl_observer.utils.time import now_ms


def select_wallets_for_warm_scan(
    candidates: Iterable[WalletPriorityScore],
    budget: ScanBudget,
    *,
    component: str = "warm_scan_priority_queue",
) -> ScanSelection:
    """Deduplicate and select wallets without exceeding local read-only budget."""

    current_ms = now_ms()
    if not budget.network_read_enabled:
        return ScanSelection(
            selected_wallets=[],
            skipped=[
                MissedOpportunity(
                    reason=MissedOpportunityReason.NETWORK_READ_DISABLED.value,
                    wallet_address=None,
                    coin=None,
                    action_type=None,
                    observed_at_ms=None,
                    detected_at_ms=current_ms,
                    component=component,
                    message="Network read is disabled, so no warm /info scan was started.",
                    next_action="Rerun with explicit --network-read only when read-only collection is intended.",
                    severity="INFO",
                )
            ],
            stopped_reason="NETWORK_READ_DISABLED",
        )

    unique: dict[str, WalletPriorityScore] = {}
    skipped: list[MissedOpportunity] = []
    for item in candidates:
        wallet = item.wallet_address.lower()
        if item.status == "REJECTED":
            skipped.append(
                MissedOpportunity(
                    reason="|".join(item.reasons) or MissedOpportunityReason.INVALID_WALLET_ADDRESS.value,
                    wallet_address=item.wallet_address,
                    coin=None,
                    action_type=None,
                    observed_at_ms=None,
                    detected_at_ms=current_ms,
                    component=component,
                    message=f"Wallet refused before scan: {', '.join(item.reasons) or 'invalid candidate'}.",
                    next_action="Import a full 0x + 40 hex address with enough history.",
                    severity="WARN",
                    details={"priority_score": item.priority_score, "source": item.source},
                )
            )
            continue
        existing = unique.get(wallet)
        if existing is None or item.priority_score > existing.priority_score:
            unique[wallet] = item

    ordered = sorted(unique.values(), key=lambda row: row.priority_score, reverse=True)
    max_leaders = max(0, min(int(budget.max_leaders_per_run), len(ordered)))
    selected = ordered[:max_leaders]
    for item in ordered[max_leaders:]:
        skipped.append(
            MissedOpportunity(
                reason=MissedOpportunityReason.WALLET_SKIPPED_BY_BUDGET.value,
                wallet_address=item.wallet_address,
                coin=None,
                action_type=None,
                observed_at_ms=None,
                detected_at_ms=current_ms,
                component=component,
                message="Wallet was valid but skipped because the per-run leader budget was exhausted.",
                next_action="Wait for the next rotation or improve wallet priority with fresher activity.",
                severity="INFO",
                details={"priority_score": item.priority_score, "max_leaders_per_run": budget.max_leaders_per_run},
            )
        )
    stopped_reason = "MAX_LEADERS_PER_RUN" if len(ordered) > max_leaders else "BUDGET_OK"
    if budget.rest_weight_remaining <= 0:
        selected = []
        skipped.append(
            MissedOpportunity(
                reason=MissedOpportunityReason.RATE_LIMIT_GUARD.value,
                wallet_address=None,
                coin=None,
                action_type=None,
                observed_at_ms=None,
                detected_at_ms=current_ms,
                component=component,
                message="REST weight budget is exhausted.",
                next_action="Back off and resume after the rate-limit window.",
                severity="WARN",
            )
        )
        stopped_reason = "RATE_LIMIT_GUARD"
    return ScanSelection(selected_wallets=selected, skipped=skipped, stopped_reason=stopped_reason)

