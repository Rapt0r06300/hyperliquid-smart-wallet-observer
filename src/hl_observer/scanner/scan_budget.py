from __future__ import annotations

from dataclasses import dataclass

from hl_observer.scanner.scanner_models import ScanBudget


@dataclass(slots=True)
class RestCostEstimate:
    wallets: int
    estimated_weight: int
    allowed: bool
    reason: str


def estimate_warm_scan_rest_cost(
    *,
    wallets: int,
    fills_expected_per_wallet: int = 200,
    base_calls_per_wallet: int = 5,
    item_bucket_size: int = 20,
) -> int:
    """Conservative /info weight estimate for one warm scan.

    The estimate is intentionally pessimistic and is used for planning only.
    """

    wallets = max(0, int(wallets))
    fills_expected_per_wallet = max(0, int(fills_expected_per_wallet))
    base = wallets * max(1, int(base_calls_per_wallet))
    fill_buckets = wallets * ((fills_expected_per_wallet + max(1, item_bucket_size) - 1) // max(1, item_bucket_size))
    return base + fill_buckets


def evaluate_warm_scan_budget(budget: ScanBudget, *, requested_wallets: int, fills_expected_per_wallet: int = 200) -> RestCostEstimate:
    allowed_wallets = min(max(0, requested_wallets), max(0, budget.max_leaders_per_run))
    estimated = estimate_warm_scan_rest_cost(wallets=allowed_wallets, fills_expected_per_wallet=fills_expected_per_wallet)
    if not budget.network_read_enabled:
        return RestCostEstimate(allowed_wallets, estimated, False, "NETWORK_READ_DISABLED")
    if allowed_wallets <= 0:
        return RestCostEstimate(allowed_wallets, estimated, False, "NO_WALLETS_SELECTED")
    if estimated > max(0, budget.rest_weight_remaining):
        return RestCostEstimate(allowed_wallets, estimated, False, "RATE_LIMIT_GUARD")
    return RestCostEstimate(allowed_wallets, estimated, True, "BUDGET_OK")

