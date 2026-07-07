"""Quote reconciliation REST vs WS (V12 capability C/G -> SOURCE_CONFLICT).

Complements reconcile_positions (which reconciles positions): this compares scalar
quotes (e.g. allMids from REST vs WS) per market and, if any deviation exceeds the
tolerance, returns the canonical NO_TRADE code SOURCE_CONFLICT. Deny-by-default
friendly. Pure: no I/O, no order, no fabricated values.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.signals.no_trade_taxonomy import resolve


@dataclass(frozen=True, slots=True)
class QuoteReconResult:
    agree: bool
    reason_code: str | None
    max_dev_bps: float
    compared: int
    missing: tuple[str, ...] = field(default_factory=tuple)
    worst_market: str | None = None


def _f(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def reconcile_quotes(
    rest: dict[str, object],
    ws: dict[str, object],
    *,
    max_dev_bps: float = 5.0,
    block_on_missing: bool = False,
) -> QuoteReconResult:
    rest_keys = set(rest)
    ws_keys = set(ws)
    common = rest_keys & ws_keys
    missing = tuple(sorted((rest_keys | ws_keys) - common))

    max_dev = 0.0
    worst: str | None = None
    for key in sorted(common):
        r = _f(rest[key])
        w = _f(ws[key])
        if r is None or w is None:
            continue
        mid = (r + w) / 2.0
        if mid == 0:
            continue
        dev_bps = abs(r - w) / abs(mid) * 10_000.0
        if dev_bps > max_dev:
            max_dev = dev_bps
            worst = key

    conflict = max_dev > max_dev_bps or (block_on_missing and bool(missing))
    return QuoteReconResult(
        agree=not conflict,
        reason_code=resolve("SOURCE_CONFLICT").value if conflict else None,
        max_dev_bps=round(max_dev, 4),
        compared=len(common),
        missing=missing,
        worst_market=worst,
    )


__all__ = ["QuoteReconResult", "reconcile_quotes"]
