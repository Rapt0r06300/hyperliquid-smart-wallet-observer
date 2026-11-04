from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from hl_observer.wallets.scan_queue import scan_wallet_queue
from hl_observer.wallets.leaderboard_validation import (
    is_full_wallet_address,
    is_truncated_wallet_display,
)


@dataclass(frozen=True)
class WalletScanPlan:
    """Deterministic, bounded plan for a large Copy-Vault wallet scan.

    This planner only admits fresh, fully identified wallet state.  It never
    invents a fill or marks a stale wallet as scanned; stale and unknown state
    are explicit ``NO_TRADE`` outcomes that remain observable to the caller.
    """

    selected_wallets: tuple[str, ...]
    no_trade: tuple[dict[str, object], ...]
    skipped_invalid: int
    skipped_duplicate: int
    eligible_count: int
    batch_count: int
    batch_size: int
    latency_budget_ms: int
    starvation: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "selected_wallets": list(self.selected_wallets),
            "no_trade": [dict(item) for item in self.no_trade],
            "skipped_invalid": self.skipped_invalid,
            "skipped_duplicate": self.skipped_duplicate,
            "eligible_count": self.eligible_count,
            "batch_count": self.batch_count,
            "batch_size": self.batch_size,
            "latency_budget_ms": self.latency_budget_ms,
            "starvation": self.starvation,
            "paper_only": True,
            "real_execution": False,
        }


def plan_wallet_scans(
    candidates: Sequence[Mapping[str, object]],
    *,
    now_ms: int,
    max_wallets: int = 1000,
    batch_size: int = 100,
    stale_after_ms: int = 60_000,
    latency_budget_ms: int = 2_000,
) -> WalletScanPlan:
    """Plan up to ``max_wallets`` without stale-state starvation.

    ``last_state_ms`` is mandatory for an eligible candidate.  Missing or too
    old state is deliberately ``NO_TRADE``.  Ranking is deterministic and the
    returned batch count exposes whether the requested capacity was actually
    reached, so a caller cannot mistake an under-filled scan for full coverage.
    """

    if now_ms < 0 or max_wallets <= 0 or batch_size <= 0 or stale_after_ms <= 0:
        raise ValueError("scan planning bounds must be positive")
    if latency_budget_ms < 0:
        raise ValueError("latency_budget_ms must be non-negative")

    seen: set[str] = set()
    eligible: list[tuple[float, str]] = []
    no_trade: list[dict[str, object]] = []
    skipped_invalid = 0
    skipped_duplicate = 0
    for candidate in candidates:
        address = str(candidate.get("wallet_address") or "").lower()
        if is_truncated_wallet_display(address) or not is_full_wallet_address(address):
            skipped_invalid += 1
            continue
        if address in seen:
            skipped_duplicate += 1
            continue
        seen.add(address)
        last_state_ms = candidate.get("last_state_ms")
        if not isinstance(last_state_ms, int) or isinstance(last_state_ms, bool):
            no_trade.append({"wallet_address": address, "reason": "STATE_UNKNOWN"})
            continue
        age_ms = now_ms - last_state_ms
        if age_ms < 0 or age_ms > stale_after_ms:
            no_trade.append({
                "wallet_address": address,
                "reason": "STALE_STATE" if age_ms >= 0 else "STATE_FROM_FUTURE",
                "age_ms": age_ms,
            })
            continue
        score = candidate.get("priority_score", 0.0)
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)):
            no_trade.append({"wallet_address": address, "reason": "SCORE_UNKNOWN"})
            continue
        eligible.append((float(score), address))

    eligible.sort(key=lambda item: (-item[0], item[1]))
    selected = tuple(address for _, address in eligible[:max_wallets])
    batch_count = math.ceil(len(selected) / batch_size) if selected else 0
    return WalletScanPlan(
        selected_wallets=selected,
        no_trade=tuple(no_trade),
        skipped_invalid=skipped_invalid,
        skipped_duplicate=skipped_duplicate,
        eligible_count=len(eligible),
        batch_count=batch_count,
        batch_size=batch_size,
        latency_budget_ms=latency_budget_ms,
        starvation=len(eligible) > len(selected),
    )

__all__ = ["WalletScanPlan", "plan_wallet_scans", "scan_wallet_queue"]
