from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.models import Position


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    allowed_for_paper: bool
    reason: str
    max_abs_diff: float
    warnings: tuple[str, ...] = field(default_factory=tuple)


def reconcile_positions(
    rest_positions: list[Position],
    ws_positions: list[Position],
    *,
    max_abs_size_diff: float = 1e-9,
) -> ReconciliationResult:
    rest_by_key = {(item.wallet, item.coin): item for item in rest_positions}
    ws_by_key = {(item.wallet, item.coin): item for item in ws_positions}
    keys = set(rest_by_key) | set(ws_by_key)
    warnings: list[str] = []
    max_diff = 0.0
    for key in keys:
        rest = rest_by_key.get(key)
        ws = ws_by_key.get(key)
        if rest is None or ws is None:
            warnings.append(f"MISSING_SOURCE:{key[0]}:{key[1]}")
            continue
        diff = abs(float(rest.signed_size) - float(ws.signed_size))
        max_diff = max(max_diff, diff)
        if diff > max_abs_size_diff:
            return ReconciliationResult(
                allowed_for_paper=False,
                reason="RECONCILIATION_DIVERGENCE_NO_TRADE",
                max_abs_diff=max_diff,
                warnings=tuple(warnings),
            )
    if warnings:
        return ReconciliationResult(
            allowed_for_paper=False,
            reason="RECONCILIATION_SOURCE_MISSING_NO_TRADE",
            max_abs_diff=max_diff,
            warnings=tuple(warnings),
        )
    return ReconciliationResult(
        allowed_for_paper=True,
        reason="RECONCILIATION_OK",
        max_abs_diff=max_diff,
    )
