"""Lead-Lag queue replay with an optional causal already-priced entry veto.

The frozen V3 implementation lives in ``_lead_lag_queue_replay_core`` unchanged.
This facade preserves that implementation byte-for-byte while adding one
opt-in, pre-FIFO veto for research runs.  ``None`` keeps legacy behaviour.
"""
from __future__ import annotations

import bisect
import contextvars
import math
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting import _lead_lag_queue_replay_core as _core

# Preserve the complete historical module surface, including constants and
# private helpers used by existing internal research/tests.
for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

_ORIGINAL_REPLAY_ONE = _core._replay_one
_ALREADY_PRICED_MAX_FRACTION: contextvars.ContextVar[float | None] = (
    contextvars.ContextVar("lead_lag_already_priced_max_fraction", default=None)
)


def _fresh_book_at_or_before(
    books: Sequence[Mapping[str, Any]],
    timestamps: Sequence[int],
    target_ms: int,
    *,
    max_age_ms: int,
) -> Mapping[str, Any] | None:
    """Return only a fresh observation already known by ``target_ms``."""

    index = bisect.bisect_right(timestamps, int(target_ms)) - 1
    if index < 0:
        return None
    row = books[index]
    observed_ms = int(row.get("ts_ms") or 0)
    age_ms = int(target_ms) - observed_ms
    if age_ms < 0 or age_ms > max(0, int(max_age_ms)):
        return None
    return row


def _book_mid(row: Mapping[str, Any]) -> float | None:
    bid = _core._number(row.get("bid"))
    ask = _core._number(row.get("ask"))
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    return 0.5 * (float(bid) + float(ask))


def _causal_already_priced_fraction(
    shock: Mapping[str, Any],
    *,
    books: Sequence[Mapping[str, Any]],
    book_timestamps: Sequence[int],
    entry_book: Mapping[str, Any],
    max_book_delay_ms: int,
) -> float | None:
    """Measure source-shock absorption using no observation after entry.

    Hyperliquid is compared from the freshest book known at/before the source
    shock window start to the causal book available when the delayed order can
    actually be sent.  Missing baseline evidence disables the veto for that
    signal rather than inventing a price.
    """

    source_shock_bps = _core._number(shock.get("lead_shock_bps"))
    window_start_ms = _core._number(shock.get("window_start_ts_ms"))
    if (
        source_shock_bps is None
        or window_start_ms is None
        or abs(source_shock_bps) <= 1e-12
    ):
        return None

    baseline_book = _fresh_book_at_or_before(
        books,
        book_timestamps,
        int(window_start_ms),
        max_age_ms=max_book_delay_ms,
    )
    if baseline_book is None:
        return None
    baseline_mid = _book_mid(baseline_book)
    entry_mid = _book_mid(entry_book)
    if baseline_mid is None or entry_mid is None or baseline_mid <= 0:
        return None

    source_direction = 1.0 if source_shock_bps > 0 else -1.0
    signed_hl_move_bps = (
        ((entry_mid / baseline_mid) - 1.0) * 10_000.0 * source_direction
    )
    return max(0.0, signed_hl_move_bps / abs(float(source_shock_bps)))


def _replay_one_with_already_priced(
    shock: Mapping[str, Any],
    *,
    direction: int,
    books: Sequence[Mapping[str, Any]],
    book_timestamps: Sequence[int],
    public_trades: Sequence[Mapping[str, Any]],
    trade_timestamps: Sequence[int],
    latency_ms: float,
    latency_measured: bool,
    maker_lifetime_ms: int,
    hold_ms: int,
    notional_usd: float,
    max_book_delay_ms: int,
    placebo: bool,
) -> tuple[dict[str, Any] | None, str]:
    threshold = _ALREADY_PRICED_MAX_FRACTION.get()
    if threshold is not None:
        target_ms = int(shock["trigger_ts_ms"]) + float(latency_ms)
        entry_decision = _core._entry_book_for_decision(
            books,
            book_timestamps,
            target_ms,
            max_age_or_delay_ms=max_book_delay_ms,
        )
        if entry_decision is None:
            return None, "MISSING_CAUSAL_ENTRY_BOOK"
        entry_book, _, _ = entry_decision
        absorbed_fraction = _causal_already_priced_fraction(
            shock,
            books=books,
            book_timestamps=book_timestamps,
            entry_book=entry_book,
            max_book_delay_ms=max_book_delay_ms,
        )
        if absorbed_fraction is not None and absorbed_fraction >= threshold:
            return None, "ALREADY_PRICED"

    return _ORIGINAL_REPLAY_ONE(
        shock,
        direction=direction,
        books=books,
        book_timestamps=book_timestamps,
        public_trades=public_trades,
        trade_timestamps=trade_timestamps,
        latency_ms=latency_ms,
        latency_measured=latency_measured,
        maker_lifetime_ms=maker_lifetime_ms,
        hold_ms=hold_ms,
        notional_usd=notional_usd,
        max_book_delay_ms=max_book_delay_ms,
        placebo=placebo,
    )


# The frozen core assigns and evaluates walk-forward segments before invoking
# this function, so vetoed candidates cannot reshuffle train/validation/OOS.
_core._replay_one = _replay_one_with_already_priced


def replay_lead_lag_queue_maker(
    tape: Mapping[str, Mapping[str, list]],
    l2_history: Mapping[str, Sequence[Mapping[str, Any]]],
    public_trade_history: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    latency_evidence: Mapping[str, Any],
    coin: str = _core.REQUIRED_COIN,
    shock_window_ms: int = _core.SHOCK_WINDOW_MS,
    shock_threshold_bps: float = _core.SHOCK_THRESHOLD_BPS,
    shock_cooldown_ms: int = _core.SHOCK_COOLDOWN_MS,
    maker_lifetime_ms: int = _core.MAKER_LIFETIME_MS,
    hold_ms: int = _core.HOLD_MS,
    notional_usd: float = _core.NOTIONAL_USD,
    max_book_delay_ms: int = _core.MAX_BOOK_DELAY_MS,
    segment_bounds: Mapping[str, tuple[int | None, int | None]] | None = None,
    precomputed_shocks: Sequence[Mapping[str, Any]] | None = None,
    already_priced_max_fraction: float | None = None,
) -> dict[str, Any]:
    """Replay V3 with an optional causal pre-FIFO ``ALREADY_PRICED`` veto."""

    threshold: float | None = None
    if already_priced_max_fraction is not None:
        parsed = _core._number(already_priced_max_fraction)
        if parsed is None or parsed <= 0:
            raise ValueError("INVALID_ALREADY_PRICED_MAX_FRACTION")
        threshold = float(parsed)

    token = _ALREADY_PRICED_MAX_FRACTION.set(threshold)
    try:
        report = _core.replay_lead_lag_queue_maker(
            tape,
            l2_history,
            public_trade_history,
            latency_evidence=latency_evidence,
            coin=coin,
            shock_window_ms=shock_window_ms,
            shock_threshold_bps=shock_threshold_bps,
            shock_cooldown_ms=shock_cooldown_ms,
            maker_lifetime_ms=maker_lifetime_ms,
            hold_ms=hold_ms,
            notional_usd=notional_usd,
            max_book_delay_ms=max_book_delay_ms,
            segment_bounds=segment_bounds,
            precomputed_shocks=precomputed_shocks,
        )
    finally:
        _ALREADY_PRICED_MAX_FRACTION.reset(token)

    result = dict(report)
    parameters = dict(result.get("parameters") or {})
    parameters["already_priced_max_fraction"] = threshold
    result["parameters"] = parameters
    return result


# Keep the original explicit public surface while replacing only the replay
# entry point above.  Frozen evaluation remains byte-for-byte legacy unless a
# caller explicitly opts into this facade parameter.
__all__ = list(_core.__all__)
