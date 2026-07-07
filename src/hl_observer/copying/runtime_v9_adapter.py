from __future__ import annotations

from dataclasses import asdict, dataclass
from time import time
from typing import Any

from hl_observer.config.settings import Settings
from hl_observer.copying.simulation_pipeline import run_paper_simulation_decision
from hl_observer.features.market import build_market_feature_vector
from hl_observer.hyperliquid.schemas import SignalCandidate
from hl_observer.paper.paper_executor import PaperExecutor


@dataclass(frozen=True, slots=True)
class RuntimeV9DecisionSummary:
    """Serializable V9 view attached to the existing local simulation event."""

    decision: str
    accepted: bool
    reasons: tuple[str, ...]
    evidence_hash: str
    signal_id: str
    signal_type: str
    side: str
    coin: str
    feature_hash: str | None
    market_quality_mode: str
    market_quality_reasons: tuple[str, ...]
    edge_remaining_bps: float
    spread_bps: float | None
    liquidity_score: float | None
    paper_order_id: str | None
    paper_notional_usdc: float | None
    paper_fill_price: float | None
    paper_rejected_reason: str | None

    def to_event_fields(self) -> dict[str, Any]:
        row = asdict(self)
        row["reasons"] = list(self.reasons)
        row["market_quality_reasons"] = list(self.market_quality_reasons)
        return {
            "v9_pipeline": row,
            "v9_decision": self.decision,
            "v9_accepted": self.accepted,
            "v9_evidence_hash": self.evidence_hash,
            "v9_reasons": list(self.reasons),
        }


def attach_v9_runtime_diagnostics(
    event: dict[str, Any],
    *,
    current_ms: int | None = None,
    all_mids: dict[str, Any] | None = None,
    l2_book: dict[str, Any] | None = None,
    candles: list[Any] | None = None,
    run_id: str = "ui-simulation",
    settings: Settings | None = None,
    executor: PaperExecutor | None = None,
) -> dict[str, Any]:
    """Attach V9 risk/evidence diagnostics without changing the paper event.

    Missing market data is represented as a V9 no-trade/data-gap decision. The
    adapter never fabricates an orderbook, liquidity, wallet score, or PnL.
    """

    try:
        signal = build_signal_candidate_from_event(event, current_ms=current_ms)
        market = build_market_feature_vector_from_event(
            event,
            current_ms=current_ms,
            all_mids=all_mids,
            l2_book=l2_book,
            candles=candles,
        )
        notional = _float_or_none(event.get("copied_notional_usdt")) or 0.0
        decision = run_paper_simulation_decision(
            signal=signal,
            market=market,
            settings=settings,
            executor=executor,
            run_id=run_id,
            notional_usdc=notional,
            source_refs=_source_refs(market, l2_book, candles),
        )
        reasons = decision.reasons
        market_reasons = decision.market.quality_reasons if decision.market else ("MARKET_FEATURES_MISSING",)
        if (
            (decision.market is None or decision.market.quality_mode == "NO_TRADE")
            and not any("data gap" in reason.lower() for reason in reasons)
        ):
            reasons = tuple(reasons) + ("data gap: market features incomplete",)
        summary = RuntimeV9DecisionSummary(
            decision=getattr(decision.risk_decision.decision, "value", str(decision.risk_decision.decision)),
            accepted=decision.accepted,
            reasons=tuple(dict.fromkeys(reasons)),
            evidence_hash=decision.evidence.evidence_hash,
            signal_id=decision.signal.id,
            signal_type=decision.signal.signal_type,
            side=decision.signal.side,
            coin=decision.signal.coin,
            feature_hash=decision.market.feature_hash if decision.market else None,
            market_quality_mode=decision.market.quality_mode if decision.market else "NO_TRADE",
            market_quality_reasons=market_reasons,
            edge_remaining_bps=decision.signal.edge_remaining_bps,
            spread_bps=decision.market.spread_bps if decision.market else decision.signal.estimated_spread_bps,
            liquidity_score=decision.market.liquidity_score if decision.market else None,
            paper_order_id=decision.paper_order.order_id if decision.paper_order else None,
            paper_notional_usdc=decision.paper_order.notional_usdc if decision.paper_order else None,
            paper_fill_price=decision.paper_order.simulated_fill_price if decision.paper_order else None,
            paper_rejected_reason=decision.paper_order.rejected_reason if decision.paper_order else None,
        )
        event.update(summary.to_event_fields())
    except Exception as exc:  # keep the UI simulation alive; expose the failure.
        event.update(
            {
                "v9_decision": "ADAPTER_ERROR",
                "v9_accepted": False,
                "v9_reasons": [f"V9_ADAPTER_ERROR: {type(exc).__name__}"],
                "v9_error": str(exc),
            }
        )
    return event


def build_signal_candidate_from_event(
    event: dict[str, Any],
    *,
    current_ms: int | None = None,
) -> SignalCandidate:
    now_ms = int(current_ms if current_ms is not None else time() * 1000)
    coin = str(event.get("coin") or "").upper()
    side = _side_from_event(event)
    signal_type = _signal_type_from_event(event)
    observed_at = _int_or_none(event.get("observed_at_ms")) or now_ms
    observed_price = (
        _float_or_none(event.get("leader_price"))
        or _float_or_none(event.get("entry_price"))
        or _float_or_none(event.get("exit_price"))
        or _float_or_none(event.get("leader_reference_price"))
        or _float_or_none(event.get("current_mid"))
    )
    if not coin:
        raise ValueError("coin missing")
    if side not in {"long", "short"}:
        raise ValueError("side missing")
    if signal_type not in {"open", "add", "reduce", "close", "flip"}:
        raise ValueError("signal type missing")
    if observed_price is None or observed_price <= 0:
        raise ValueError("observed price missing")

    signal_age_ms = _int_or_none(event.get("signal_age_ms"))
    if signal_age_ms is None:
        signal_age_ms = max(0, now_ms - observed_at)

    return SignalCandidate(
        id=str(event.get("paper_ref") or event.get("delta_key") or f"{coin}:{observed_at}"),
        source_wallet=str(event.get("wallet_address") or "unknown"),
        coin=coin,
        side=side,
        signal_type=signal_type,
        observed_price=float(observed_price),
        timestamp_ms=int(observed_at),
        signal_age_ms=int(signal_age_ms),
        wallet_score=float(_float_or_none(event.get("leader_score")) or _float_or_none(event.get("wallet_score")) or 0.0),
        signal_score=float(_float_or_none(event.get("opportunity_score")) or _float_or_none(event.get("signal_score")) or 0.0),
        edge_remaining_bps=float(_float_or_none(event.get("edge_remaining_bps")) or 0.0),
        estimated_fee_bps=float(_float_or_none(event.get("fee_bps")) or _float_or_none(event.get("estimated_fee_bps")) or 4.0),
        estimated_spread_bps=float(_float_or_none(event.get("spread_bps")) or _float_or_none(event.get("estimated_spread_bps")) or 0.0),
        estimated_slippage_bps=float(_float_or_none(event.get("slippage_bps")) or _float_or_none(event.get("estimated_slippage_bps")) or 0.0),
        estimated_latency_decay_bps=float(_float_or_none(event.get("estimated_latency_decay_bps")) or 0.0),
        orderbook_depth_usdc=float(_float_or_none(event.get("orderbook_depth_usdc")) or 0.0),
        crowding_score=float(_float_or_none(event.get("crowding_score")) or 0.0),
    )


def build_market_feature_vector_from_event(
    event: dict[str, Any],
    *,
    current_ms: int | None = None,
    all_mids: dict[str, Any] | None = None,
    l2_book: dict[str, Any] | None = None,
    candles: list[Any] | None = None,
):
    coin = str(event.get("coin") or "").upper()
    if not coin:
        return None
    now_ms = int(current_ms if current_ms is not None else time() * 1000)
    mids = dict(all_mids or {})
    explicit_mid = _float_or_none(event.get("current_mid"))
    if explicit_mid is not None and explicit_mid > 0:
        mids[coin] = explicit_mid
    elif coin not in mids:
        maybe_price = _float_or_none(event.get("leader_price")) or _float_or_none(event.get("entry_price")) or _float_or_none(event.get("exit_price"))
        if maybe_price is not None and maybe_price > 0:
            mids[coin] = maybe_price
    return build_market_feature_vector(
        timestamp_ms=now_ms,
        source_ts_ms=_int_or_none(event.get("leader_exchange_ts")) or _int_or_none(event.get("observed_at_ms")),
        coin=coin,
        l2_book=l2_book,
        all_mids=mids,
        candles=candles,
        last_trade_price=event.get("leader_price"),
        is_stale=bool(event.get("stale_signal")),
    )


def _signal_type_from_event(event: dict[str, Any]) -> str:
    action = str(event.get("leader_action") or event.get("paper_action_type") or "").upper()
    if action in {"OPEN_LONG", "OPEN_SHORT", "OPEN"}:
        return "open"
    if action in {"ADD", "INCREASE"}:
        return "add"
    if action == "REDUCE":
        return "reduce"
    if action in {"CLOSE_LONG", "CLOSE_SHORT", "CLOSE"}:
        return "close"
    if "FLIP" in action:
        return "flip"
    return ""


def _side_from_event(event: dict[str, Any]) -> str:
    side = str(event.get("leader_side") or "").upper()
    action = str(event.get("leader_action") or "").upper()
    if side == "LONG" or action.endswith("LONG"):
        return "long"
    if side == "SHORT" or action.endswith("SHORT"):
        return "short"
    return ""


def _source_refs(market: Any, l2_book: dict[str, Any] | None, candles: list[Any] | None) -> tuple[str, ...]:
    refs = ["leader_delta"]
    if market is not None:
        refs.append(str(getattr(market, "mid_endpoint", "market_features")))
    if l2_book is not None:
        refs.append("l2Book")
    if candles:
        refs.append("candles")
    return tuple(dict.fromkeys(refs))


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None
