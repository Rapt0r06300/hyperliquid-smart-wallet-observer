"""Local paper execution model with explicit fill and cost truth.

The strict path consumes a causal :class:`ExecutionTruth` and never invents
liquidity. Taker fills walk the observed book. Maker fills require queue
depletion or traded-through evidence. This module is pure simulation: it has
no network client, signer, key handling, or venue execution endpoint.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from hl_observer.paper_trading.execution_truth import ExecutionTruth, normalize_execution_side


@dataclass(frozen=True, slots=True)
class ExecModelConfig:
    # Hyperliquid base-tier defaults. Runtime fee provenance is audited
    # separately; callers may replace these only with a measured fee tier.
    taker_fee_bps: float = 4.5
    maker_fee_bps: float = 1.5
    maker_rebate_bps: float = 0.0
    half_spread_bps: float = 1.0
    impact_coef_bps: float = 10.0
    latency_cost_bps_per_sec: float = 0.20
    max_latency_cost_bps: float = 15.0
    # P1B: "CAUSAL" => la latence vient du carnet causal (non refoldee comme taxe scalaire ; celui-ci
    # n'est plus qu'un STRESS). "SCALAR_STRESS" (defaut) preserve l'ancien comportement.
    latency_mode: str = "SCALAR_STRESS"
    unknown_depth_impact_bps: float = 25.0


@dataclass(frozen=True, slots=True)
class ExecResult:
    fill_price: float | None
    slippage_bps: float | None
    fee_bps: float | None
    latency_bps: float
    net_cost_bps: float | None
    queue_ratio: float | None
    is_maker: bool
    # Compatibility alias used by older diagnostics. It is always the filled,
    # never the requested, notional.
    notional_usdc: float
    requested_notional_usdc: float = 0.0
    filled_notional_usdc: float = 0.0
    missed_notional_usdc: float = 0.0
    fill_ratio: float = 0.0
    partial: bool = False
    missed: bool = False
    reason: str = "FILLED"
    cost_status: str = "MEASURED"
    adverse_selection_bps: float | None = None
    execution_snapshot_id: str | None = None
    filled_quantity: float = 0.0
    level_fills: tuple[BookLevelFill, ...] = ()


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: float
    size: float


@dataclass(frozen=True, slots=True)
class BookLevelFill:
    """Exact quantity consumed at one executable price level."""

    price: float
    available_quantity: float
    filled_quantity: float
    filled_notional_usdc: float


@dataclass(frozen=True, slots=True)
class DepthExecutionResult:
    requested_notional_usdc: float
    filled_notional_usdc: float
    missed_notional_usdc: float
    average_fill_price: float | None
    fill_ratio: float
    partial: bool
    missed: bool
    slippage_bps: float
    levels_consumed: int
    reason: str
    filled_quantity: float = 0.0
    level_fills: tuple[BookLevelFill, ...] = ()


def estimate_slippage_bps(
    notional_usdc: float,
    top_depth_usdc: float | None,
    *,
    config: ExecModelConfig | None = None,
) -> float:
    """Return an explicitly approximate scalar-depth execution cost."""

    cfg = config or ExecModelConfig()
    requested = _finite_positive(notional_usdc, "notional_usdc")
    half_spread = _finite_non_negative(cfg.half_spread_bps, "half_spread_bps")
    if top_depth_usdc is None:
        result = half_spread + _finite_non_negative(
            cfg.unknown_depth_impact_bps,
            "unknown_depth_impact_bps",
        )
    else:
        depth = _finite_positive(top_depth_usdc, "top_depth_usdc")
        impact = _finite_non_negative(cfg.impact_coef_bps, "impact_coef_bps")
        result = half_spread + impact * requested / depth
    if not math.isfinite(result):
        raise ValueError("NUMERIC_OVERFLOW_SLIPPAGE")
    return result


def simulate_execution(
    *,
    side: str,
    notional_usdc: float,
    mid_price: float,
    top_depth_usdc: float | None = None,
    is_maker: bool = False,
    latency_sec: float = 0.0,
    queue_ahead_usdc: float = 0.0,
    queue_depletion_usdc: float | None = None,
    traded_through_usdc: float | None = None,
    adverse_selection_bps: float | None = None,
    execution_truth: ExecutionTruth | None = None,
    decision_ts_ms: int | None = None,
    max_book_age_ms: int = 5_000,
    strict_book: bool = False,
    min_fill_ratio: float = 0.0,
    config: ExecModelConfig | None = None,
) -> ExecResult:
    """Simulate one paper execution from measurable evidence.

    ``strict_book=True`` is the live paper contract. It requires a fresh
    observed L2 snapshot. A maker additionally requires observed queue
    progress. The compatibility path without a book is labelled
    ``APPROXIMATE`` and must not be promoted into strict PnL.
    """

    cfg = config or ExecModelConfig()
    requested = _finite_positive(notional_usdc, "notional_usdc")
    reference_mid = _finite_positive(mid_price, "mid_price")
    normalized_side = normalize_execution_side(side)
    latency = _finite_non_negative(latency_sec, "latency_sec")
    queue_ahead = _finite_non_negative(queue_ahead_usdc, "queue_ahead_usdc")
    latency_bps = min(
        _finite_non_negative(cfg.max_latency_cost_bps, "max_latency_cost_bps"),
        latency * _finite_non_negative(
            cfg.latency_cost_bps_per_sec,
            "latency_cost_bps_per_sec",
        ),
    )
    if getattr(cfg, "latency_mode", "SCALAR_STRESS") == "CAUSAL" and execution_truth is not None:
        # P1B: en mode CAUSAL la latence est DÉJÀ dans le carnet causal d'exécution — ne pas la refold
        # comme taxe scalaire (double compte). Le coût de latence autoritaire est mesuré par latency_truth.
        latency_bps = 0.0

    if execution_truth is not None:
        if decision_ts_ms is None:
            raise ValueError("decision_ts_ms is required with execution_truth")
        timestamp_refusal = execution_truth.timestamp_refusal_reason(
            decision_ts_ms=decision_ts_ms,
            max_age_ms=max_book_age_ms,
        )
        if timestamp_refusal is not None:
            return _no_fill_result(
                requested=requested,
                is_maker=is_maker,
                reason=timestamp_refusal,
                snapshot_id=execution_truth.snapshot_id,
                cost_status="UNMEASURABLE",
            )
        try:
            reference_mid = execution_truth.mid_price
            _ = execution_truth.spread_bps
            execution_truth.visible_notional("BUY")
            execution_truth.visible_notional("SELL")
        except (TypeError, ValueError, OverflowError):
            return _no_fill_result(
                requested=requested,
                is_maker=is_maker,
                reason="NUMERIC_OVERFLOW",
                snapshot_id=execution_truth.snapshot_id,
                cost_status="UNMEASURABLE",
            )
    elif strict_book:
        return _no_fill_result(
            requested=requested,
            is_maker=is_maker,
            reason="NO_LIVE_EXECUTABLE_BOOK",
            cost_status="UNMEASURABLE",
        )

    if is_maker:
        return _simulate_maker(
            side=normalized_side,
            requested=requested,
            reference_mid=reference_mid,
            latency_bps=latency_bps,
            queue_ahead=queue_ahead,
            queue_depletion_usdc=queue_depletion_usdc,
            traded_through_usdc=traded_through_usdc,
            adverse_selection_bps=adverse_selection_bps,
            top_depth_usdc=top_depth_usdc,
            execution_truth=execution_truth,
            cfg=cfg,
        )

    if execution_truth is not None:
        depth_result = simulate_depth_execution(
            side=normalized_side,
            notional_usdc=requested,
            mid_price=reference_mid,
            asks=execution_truth.asks,
            bids=execution_truth.bids,
            min_fill_ratio=min_fill_ratio,
        )
        if depth_result.average_fill_price is None or depth_result.filled_notional_usdc <= 0:
            return _no_fill_result(
                requested=requested,
                is_maker=False,
                reason=depth_result.reason,
                snapshot_id=execution_truth.snapshot_id,
                cost_status="MEASURED",
            )
        fee_bps = _finite_non_negative(cfg.taker_fee_bps, "taker_fee_bps")
        total_cost_bps = fee_bps + latency_bps
        all_in_fill = _apply_price(depth_result.average_fill_price, normalized_side, total_cost_bps)
        net_cost = _directional_cost_bps(all_in_fill, reference_mid, normalized_side)
        if (
            not all(
                math.isfinite(value)
                for value in (
                    total_cost_bps,
                    all_in_fill,
                    net_cost,
                    depth_result.slippage_bps,
                    depth_result.filled_notional_usdc,
                    depth_result.fill_ratio,
                    depth_result.filled_quantity,
                )
            )
            or all_in_fill <= 0.0
        ):
            return _numeric_overflow_result(
                requested,
                is_maker=False,
                snapshot_id=execution_truth.snapshot_id,
            )
        rounded_fill = round(all_in_fill, 10)
        if rounded_fill <= 0.0:
            return _numeric_overflow_result(
                requested,
                is_maker=False,
                snapshot_id=execution_truth.snapshot_id,
            )
        return ExecResult(
            fill_price=rounded_fill,
            slippage_bps=depth_result.slippage_bps,
            fee_bps=fee_bps,
            latency_bps=latency_bps,
            net_cost_bps=round(net_cost, 8),
            queue_ratio=None,
            is_maker=False,
            notional_usdc=depth_result.filled_notional_usdc,
            requested_notional_usdc=round(requested, 8),
            filled_notional_usdc=depth_result.filled_notional_usdc,
            missed_notional_usdc=depth_result.missed_notional_usdc,
            fill_ratio=depth_result.fill_ratio,
            partial=depth_result.partial,
            missed=depth_result.missed,
            reason=depth_result.reason,
            cost_status="MEASURED",
            adverse_selection_bps=None,
            execution_snapshot_id=execution_truth.snapshot_id,
            filled_quantity=depth_result.filled_quantity,
            level_fills=depth_result.level_fills,
        )

    # Legacy/replay approximation. It is intentionally marked and is rejected
    # by the strict PaperEngine.
    try:
        slippage_bps = estimate_slippage_bps(requested, top_depth_usdc, config=cfg)
    except ValueError as exc:
        if "NUMERIC_OVERFLOW_SLIPPAGE" in str(exc):
            return _numeric_overflow_result(requested, is_maker=False)
        raise
    fee_bps = _finite_non_negative(cfg.taker_fee_bps, "taker_fee_bps")
    net_cost_bps = slippage_bps + fee_bps + latency_bps
    fill_price = _apply_price(reference_mid, normalized_side, net_cost_bps)
    filled_quantity = requested / fill_price
    if (
        not all(
            math.isfinite(value)
            for value in (
                slippage_bps,
                fee_bps,
                latency_bps,
                net_cost_bps,
                fill_price,
                filled_quantity,
            )
        )
        or fill_price <= 0.0
    ):
        return _numeric_overflow_result(requested, is_maker=False)
    rounded_fill = round(fill_price, 10)
    if rounded_fill <= 0.0:
        return _numeric_overflow_result(requested, is_maker=False)
    return ExecResult(
        fill_price=rounded_fill,
        slippage_bps=slippage_bps,
        fee_bps=fee_bps,
        latency_bps=latency_bps,
        net_cost_bps=net_cost_bps,
        queue_ratio=None,
        is_maker=False,
        notional_usdc=round(requested, 8),
        requested_notional_usdc=round(requested, 8),
        filled_notional_usdc=round(requested, 8),
        missed_notional_usdc=0.0,
        fill_ratio=1.0,
        reason="FILLED_APPROXIMATE",
        cost_status="APPROXIMATE",
        filled_quantity=round(filled_quantity, 12),
    )


def _simulate_maker(
    *,
    side: str,
    requested: float,
    reference_mid: float,
    latency_bps: float,
    queue_ahead: float,
    queue_depletion_usdc: float | None,
    traded_through_usdc: float | None,
    adverse_selection_bps: float | None,
    top_depth_usdc: float | None,
    execution_truth: ExecutionTruth | None,
    cfg: ExecModelConfig,
) -> ExecResult:
    depth = _maker_visible_depth(execution_truth, side)
    if depth is None and top_depth_usdc is not None:
        depth = _finite_positive(top_depth_usdc, "top_depth_usdc")
    queue_ratio = None if depth is None else queue_ahead / depth
    if queue_ratio is not None and not math.isfinite(queue_ratio):
        return _numeric_overflow_result(
            requested,
            is_maker=True,
            snapshot_id=execution_truth.snapshot_id if execution_truth else None,
        )

    depletion = _optional_non_negative(queue_depletion_usdc, "queue_depletion_usdc")
    traded = _optional_non_negative(traded_through_usdc, "traded_through_usdc")
    if depletion is None and traded is None:
        return _no_fill_result(
            requested=requested,
            is_maker=True,
            reason="NO_FILL_NO_QUEUE_EVIDENCE",
            queue_ratio=queue_ratio,
            snapshot_id=execution_truth.snapshot_id if execution_truth else None,
            cost_status="UNMEASURABLE",
        )
    observed_reach = max(depletion or 0.0, traded or 0.0)
    filled = min(requested, max(0.0, observed_reach - queue_ahead))
    if filled <= 0:
        return _no_fill_result(
            requested=requested,
            is_maker=True,
            reason="NO_FILL_QUEUE_NOT_DEPLETED",
            queue_ratio=queue_ratio,
            snapshot_id=execution_truth.snapshot_id if execution_truth else None,
            cost_status="MEASURED",
        )

    adverse = adverse_selection_bps
    if adverse is None:
        adverse = _env_adverse_selection_bps()
    adverse = _optional_non_negative(adverse, "adverse_selection_bps")
    fee_bps = _finite_non_negative(cfg.maker_fee_bps, "maker_fee_bps") - _finite_non_negative(
        cfg.maker_rebate_bps,
        "maker_rebate_bps",
    )
    base_fill = _maker_base_price(execution_truth, side, reference_mid)
    base_slippage = _directional_cost_bps(base_fill, reference_mid, side)
    if not math.isfinite(base_slippage) or base_fill <= 0.0:
        return _numeric_overflow_result(
            requested,
            is_maker=True,
            snapshot_id=execution_truth.snapshot_id if execution_truth else None,
        )
    partial = filled < requested - 1e-9
    if adverse is None:
        rounded_fill = round(base_fill, 10)
        filled_quantity = filled / base_fill
        if rounded_fill <= 0.0 or not math.isfinite(filled_quantity):
            return _numeric_overflow_result(
                requested,
                is_maker=True,
                snapshot_id=execution_truth.snapshot_id if execution_truth else None,
            )
        return ExecResult(
            fill_price=rounded_fill,
            slippage_bps=round(base_slippage, 8),
            fee_bps=fee_bps,
            latency_bps=latency_bps,
            net_cost_bps=None,
            queue_ratio=queue_ratio,
            is_maker=True,
            notional_usdc=round(filled, 8),
            requested_notional_usdc=round(requested, 8),
            filled_notional_usdc=round(filled, 8),
            missed_notional_usdc=round(requested - filled, 8),
            fill_ratio=round(filled / requested, 8),
            partial=partial,
            missed=partial,
            reason="UNMEASURABLE_ADVERSE_SELECTION",
            cost_status="UNMEASURABLE",
            adverse_selection_bps=None,
            execution_snapshot_id=execution_truth.snapshot_id if execution_truth else None,
            filled_quantity=round(filled_quantity, 12),
        )

    total_cost_bps = fee_bps + latency_bps + adverse
    all_in_fill = _apply_price(base_fill, side, total_cost_bps)
    net_cost = _directional_cost_bps(all_in_fill, reference_mid, side)
    if (
        not all(
            math.isfinite(value)
            for value in (total_cost_bps, all_in_fill, net_cost, filled, requested)
        )
        or all_in_fill <= 0.0
    ):
        return _numeric_overflow_result(
            requested,
            is_maker=True,
            snapshot_id=execution_truth.snapshot_id if execution_truth else None,
        )
    rounded_fill = round(all_in_fill, 10)
    filled_quantity = filled / all_in_fill
    if rounded_fill <= 0.0 or not math.isfinite(filled_quantity):
        return _numeric_overflow_result(
            requested,
            is_maker=True,
            snapshot_id=execution_truth.snapshot_id if execution_truth else None,
        )
    return ExecResult(
        fill_price=rounded_fill,
        slippage_bps=round(base_slippage, 8),
        fee_bps=fee_bps,
        latency_bps=latency_bps,
        net_cost_bps=round(net_cost, 8),
        queue_ratio=queue_ratio,
        is_maker=True,
        notional_usdc=round(filled, 8),
        requested_notional_usdc=round(requested, 8),
        filled_notional_usdc=round(filled, 8),
        missed_notional_usdc=round(requested - filled, 8),
        fill_ratio=round(filled / requested, 8),
        partial=partial,
        missed=partial,
        reason="PARTIAL_FILL" if partial else "FILLED",
        cost_status="MEASURED" if execution_truth else "APPROXIMATE",
        adverse_selection_bps=adverse,
        execution_snapshot_id=execution_truth.snapshot_id if execution_truth else None,
        filled_quantity=round(filled_quantity, 12),
    )


def round_trip_cost_bps(*, entry: ExecResult, exit_: ExecResult) -> float | None:
    """Return measured round-trip cost, or None when either leg is unknown."""

    if entry.net_cost_bps is None or exit_.net_cost_bps is None:
        return None
    return entry.net_cost_bps + exit_.net_cost_bps


def simulate_depth_execution(
    *,
    side: str,
    notional_usdc: float,
    mid_price: float,
    asks: list[tuple[float, float]] | tuple[tuple[float, float], ...] = (),
    bids: list[tuple[float, float]] | tuple[tuple[float, float], ...] = (),
    min_fill_ratio: float = 0.85,
) -> DepthExecutionResult:
    """Walk explicit book levels and return exact partial/missed quantities."""

    try:
        requested = _finite_positive(notional_usdc, "notional_usdc")
        mid = _finite_positive(mid_price, "mid_price")
        normalized_side = normalize_execution_side(side)
        minimum = min(1.0, _finite_non_negative(min_fill_ratio, "min_fill_ratio"))
    except (TypeError, ValueError, OverflowError):
        return _invalid_depth_result()

    raw_levels = asks if normalized_side == "BUY" else bids
    levels = _clean_levels(raw_levels, reverse=normalized_side == "SELL")
    remaining = requested
    filled_notional = 0.0
    filled_qty = 0.0
    level_fills: list[BookLevelFill] = []
    for level in levels:
        available_notional = level.price * level.size
        if not math.isfinite(available_notional) or available_notional <= 0.0:
            return _numeric_overflow_depth_result(requested)
        take_notional = min(remaining, available_notional)
        if take_notional <= 0:
            continue
        take_quantity = take_notional / level.price
        filled_notional += take_notional
        filled_qty += take_quantity
        remaining -= take_notional
        if not all(
            math.isfinite(value)
            for value in (take_notional, take_quantity, filled_notional, filled_qty, remaining)
        ):
            return _numeric_overflow_depth_result(requested)
        level_fills.append(
            BookLevelFill(
                price=round(level.price, 12),
                available_quantity=round(level.size, 12),
                filled_quantity=round(take_quantity, 12),
                filled_notional_usdc=round(take_notional, 8),
            )
        )
        if remaining <= 1e-9:
            break

    if filled_notional <= 0 or filled_qty <= 0:
        return DepthExecutionResult(
            requested_notional_usdc=round(requested, 8),
            filled_notional_usdc=0.0,
            missed_notional_usdc=round(requested, 8),
            average_fill_price=None,
            fill_ratio=0.0,
            partial=False,
            missed=True,
            slippage_bps=0.0,
            levels_consumed=0,
            reason="NO_DEPTH",
            filled_quantity=0.0,
        )

    average = filled_notional / filled_qty
    fill_ratio = min(1.0, filled_notional / requested)
    partial = fill_ratio < 0.999999
    missed = fill_ratio < minimum
    if normalized_side == "BUY":
        slippage = max(0.0, (average / mid - 1.0) * 10_000.0)
    else:
        slippage = max(0.0, (1.0 - average / mid) * 10_000.0)
    if not all(math.isfinite(value) for value in (average, fill_ratio, slippage)):
        return _numeric_overflow_depth_result(requested)
    return DepthExecutionResult(
        requested_notional_usdc=round(requested, 8),
        filled_notional_usdc=round(filled_notional, 8),
        missed_notional_usdc=round(max(0.0, requested - filled_notional), 8),
        average_fill_price=round(average, 10),
        fill_ratio=round(fill_ratio, 8),
        partial=partial,
        missed=missed,
        slippage_bps=round(slippage, 8),
        levels_consumed=len(level_fills),
        reason="MISSED_FILL" if missed else "PARTIAL_FILL" if partial else "FILLED",
        filled_quantity=round(filled_qty, 12),
        level_fills=tuple(level_fills),
    )


def book_notional_for_quantity(
    execution_truth: ExecutionTruth | None,
    *,
    side: str,
    quantity: float,
    fallback_price: float,
) -> float:
    """Return the quote notional required to consume an exact book quantity.

    When visible depth is insufficient, only the actually visible quote
    notional is returned. Callers must compare the resulting filled quantity
    with the requested quantity and retain the unfilled position remainder.
    """

    requested_quantity = _finite_positive(quantity, "quantity")
    reference_price = _finite_positive(fallback_price, "fallback_price")
    if execution_truth is None:
        result = requested_quantity * reference_price
        if not math.isfinite(result) or result <= 0.0:
            raise ValueError("NUMERIC_OVERFLOW_BOOK_NOTIONAL")
        return result

    remaining = requested_quantity
    quote_notional = 0.0
    for price, available_quantity in execution_truth.levels_for_side(side):
        take_quantity = min(remaining, available_quantity)
        level_notional = take_quantity * price
        if not math.isfinite(level_notional) or level_notional <= 0.0:
            raise ValueError("NUMERIC_OVERFLOW_BOOK_NOTIONAL")
        quote_notional += level_notional
        if not math.isfinite(quote_notional):
            raise ValueError("NUMERIC_OVERFLOW_BOOK_NOTIONAL")
        remaining -= take_quantity
        if remaining <= 1e-12:
            break
    return quote_notional


def _clean_levels(
    raw_levels: list[tuple[float, float]] | tuple[tuple[float, float], ...],
    *,
    reverse: bool,
) -> list[BookLevel]:
    levels: list[BookLevel] = []
    for item in raw_levels:
        if isinstance(item, dict):
            price = item.get("px", item.get("price"))
            size = item.get("sz", item.get("size"))
        else:
            try:
                price, size = item
            except (TypeError, ValueError):
                continue
        try:
            parsed_price = float(price)
            parsed_size = float(size)
        except (TypeError, ValueError, OverflowError):
            continue
        if (
            math.isfinite(parsed_price)
            and math.isfinite(parsed_size)
            and parsed_price > 0
            and parsed_size > 0
        ):
            levels.append(BookLevel(price=parsed_price, size=parsed_size))
    return sorted(levels, key=lambda level: level.price, reverse=reverse)


def _invalid_depth_result() -> DepthExecutionResult:
    return DepthExecutionResult(
        requested_notional_usdc=0.0,
        filled_notional_usdc=0.0,
        missed_notional_usdc=0.0,
        average_fill_price=None,
        fill_ratio=0.0,
        partial=False,
        missed=True,
        slippage_bps=0.0,
        levels_consumed=0,
        reason="INVALID_REQUEST",
        filled_quantity=0.0,
    )


def _numeric_overflow_depth_result(requested: float) -> DepthExecutionResult:
    return DepthExecutionResult(
        requested_notional_usdc=requested,
        filled_notional_usdc=0.0,
        missed_notional_usdc=requested,
        average_fill_price=None,
        fill_ratio=0.0,
        partial=False,
        missed=True,
        slippage_bps=0.0,
        levels_consumed=0,
        reason="NUMERIC_OVERFLOW",
        filled_quantity=0.0,
    )


def _numeric_overflow_result(
    requested: float,
    *,
    is_maker: bool,
    snapshot_id: str | None = None,
) -> ExecResult:
    return _no_fill_result(
        requested=requested,
        is_maker=is_maker,
        reason="NUMERIC_OVERFLOW",
        cost_status="UNMEASURABLE",
        snapshot_id=snapshot_id,
    )


def _apply_price(reference_price: float, side: str, signed_bps: float) -> float:
    adjustment = signed_bps / 10_000.0
    if normalize_execution_side(side) == "BUY":
        return reference_price * (1.0 + adjustment)
    return reference_price * (1.0 - adjustment)


def _maker_visible_depth(truth: ExecutionTruth | None, side: str) -> float | None:
    if truth is None:
        return None
    levels = truth.bids if side == "BUY" else truth.asks
    price, size = levels[0]
    return price * size


def _maker_base_price(truth: ExecutionTruth | None, side: str, fallback_mid: float) -> float:
    if truth is None:
        return fallback_mid
    return truth.best_bid if side == "BUY" else truth.best_ask


def _directional_cost_bps(fill_price: float, reference_price: float, side: str) -> float:
    if side == "BUY":
        return (fill_price / reference_price - 1.0) * 10_000.0
    return (1.0 - fill_price / reference_price) * 10_000.0


def _finite_positive(value: object, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return parsed


def _finite_non_negative(value: object, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return parsed


def _optional_non_negative(value: object | None, name: str) -> float | None:
    if value is None:
        return None
    return _finite_non_negative(value, name)


def _env_adverse_selection_bps() -> float | None:
    import os

    raw = os.environ.get("HYPERSMART_MAKER_ADVERSE_SELECTION_BPS")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        parsed = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _no_fill_result(
    *,
    requested: float,
    is_maker: bool,
    reason: str,
    cost_status: str,
    queue_ratio: float | None = None,
    snapshot_id: str | None = None,
) -> ExecResult:
    return ExecResult(
        fill_price=None,
        slippage_bps=None,
        fee_bps=None,
        latency_bps=0.0,
        net_cost_bps=None,
        queue_ratio=queue_ratio,
        is_maker=is_maker,
        notional_usdc=0.0,
        requested_notional_usdc=round(requested, 8),
        filled_notional_usdc=0.0,
        missed_notional_usdc=round(requested, 8),
        fill_ratio=0.0,
        partial=False,
        missed=True,
        reason=reason,
        cost_status=cost_status,
        execution_snapshot_id=snapshot_id,
        filled_quantity=0.0,
    )


__all__ = [
    "BookLevel",
    "BookLevelFill",
    "DepthExecutionResult",
    "ExecModelConfig",
    "ExecResult",
    "book_notional_for_quantity",
    "estimate_slippage_bps",
    "round_trip_cost_bps",
    "simulate_depth_execution",
    "simulate_execution",
]
