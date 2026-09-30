from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from hl_observer.hyperliquid.schemas import SignalCandidate, SignalDecision
from hl_observer.loops.models import stable_hash
from hl_observer.mainnet_readonly_observer.observer import MainnetObservation
from hl_observer.testnet.models import unix_ms


@dataclass(frozen=True, slots=True)
class CandidateFactorySkip:
    wallet: str
    reason: str
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CandidateFactoryReport:
    source: str
    generated_at_ms: int
    observed_at_ms: int
    candidates: list[SignalCandidate]
    skipped: list[CandidateFactorySkip]
    methodology: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "generated_at_ms": self.generated_at_ms,
            "observed_at_ms": self.observed_at_ms,
            "candidate_count": len(self.candidates),
            "candidates": [candidate.model_dump(mode="json") for candidate in self.candidates],
            "skipped": [item.to_dict() for item in self.skipped],
            "methodology": self.methodology,
        }


def build_signal_candidates_from_observation(
    observation: MainnetObservation,
    *,
    max_candidates: int = 25,
    default_wallet_score: float = 75.0,
    default_signal_score: float = 72.0,
    min_depth_usdc: float = 5_000.0,
) -> CandidateFactoryReport:
    """Build measurable SignalCandidate objects from read-only Hyperliquid fills.

    The factory never invents fills or positions. It only transforms wallet fills
    already present in the observation into local decision candidates, with a
    conservative cost estimate for the risk gates.
    """

    now = unix_ms()
    candidates: list[SignalCandidate] = []
    skipped: list[CandidateFactorySkip] = []

    for wallet, fills in observation.wallet_fills.items():
        for fill in fills:
            raw = dict(fill)
            if len(candidates) >= max_candidates:
                skipped.append(CandidateFactorySkip(wallet=wallet, reason="max_candidates_reached", raw=raw))
                continue

            parsed = _parse_fill(wallet, raw, observation, now)
            if isinstance(parsed, CandidateFactorySkip):
                skipped.append(parsed)
                continue

            direction, signal_type, side, coin, price, timestamp_ms = parsed
            spread_bps, depth_usdc = _book_metrics(observation.l2_books.get(coin, {}))
            current_mid = _float_or_none(observation.all_mids.get(coin))
            observed_price = current_mid or price
            signal_age_ms = max(0, now - timestamp_ms)
            fee_bps = 4.0
            slippage_bps = _estimate_slippage_bps(depth_usdc=depth_usdc, min_depth_usdc=min_depth_usdc)
            latency_bps = min(30.0, signal_age_ms / 1_000.0 * 2.0)
            base_edge_bps = 58.0 if signal_type in {"open", "add"} else 32.0
            if depth_usdc < min_depth_usdc:
                base_edge_bps -= 20.0
            edge_remaining_bps = round(base_edge_bps - fee_bps - spread_bps - slippage_bps - latency_bps, 8)
            candidate_id = "ro-" + stable_hash(
                {
                    "wallet": wallet,
                    "coin": coin,
                    "dir": direction,
                    "px": price,
                    "time": timestamp_ms,
                    "hash": raw.get("hash"),
                    "tid": raw.get("tid"),
                    "oid": raw.get("oid"),
                }
            )
            candidates.append(
                SignalCandidate(
                    id=candidate_id,
                    source_wallet=wallet,
                    coin=coin,
                    side=side,
                    signal_type=signal_type,
                    observed_price=observed_price,
                    timestamp_ms=timestamp_ms,
                    signal_age_ms=signal_age_ms,
                    wallet_score=default_wallet_score,
                    signal_score=default_signal_score,
                    edge_remaining_bps=edge_remaining_bps,
                    estimated_fee_bps=fee_bps,
                    estimated_spread_bps=round(spread_bps, 8),
                    estimated_slippage_bps=round(slippage_bps, 8),
                    estimated_latency_decay_bps=round(latency_bps, 8),
                    orderbook_depth_usdc=round(depth_usdc, 8),
                    decision=SignalDecision.TESTNET_CANDIDATE,
                )
            )

    return CandidateFactoryReport(
        source=observation.source,
        generated_at_ms=now,
        observed_at_ms=observation.observed_at_ms,
        candidates=candidates,
        skipped=skipped,
        methodology=(
            "read_only_user_fills_to_signal_candidates; no fake fills; costs include "
            "fee/spread/slippage/latency; edge is a conservative local estimate for gating"
        ),
    )


def build_signal_candidates_from_position_deltas(
    position_deltas: list[Any],
    *,
    all_mids: dict[str, Any] | None = None,
    l2_books: dict[str, Any] | None = None,
    source: str = "position_deltas",
    observed_at_ms: int | None = None,
    max_candidates: int = 25,
    default_wallet_score: float = 72.0,
    default_signal_score: float = 70.0,
    min_depth_usdc: float = 5_000.0,
) -> CandidateFactoryReport:
    """Build SignalCandidate objects from reconstructed position deltas.

    This is the snapshot/delta path: no order is created here. Unknown, flip or
    under-specified deltas are skipped so they cannot become paper/testnet
    intents by accident.
    """

    now = unix_ms()
    mids = all_mids or {}
    books = l2_books or {}
    candidates: list[SignalCandidate] = []
    skipped: list[CandidateFactorySkip] = []

    for delta in position_deltas:
        raw = _raw_delta(delta)
        wallet = str(_delta_value(delta, "wallet_address", "source_wallet", "wallet") or "").strip()
        if not wallet:
            wallet = "UNKNOWN_WALLET"
        if len(candidates) >= max_candidates:
            skipped.append(CandidateFactorySkip(wallet=wallet, reason="max_candidates_reached", raw=raw))
            continue
        parsed = _parse_position_delta(delta, mids, now)
        if isinstance(parsed, CandidateFactorySkip):
            skipped.append(parsed)
            continue
        signal_type, side, coin, price, timestamp_ms, action = parsed
        spread_bps, depth_usdc = _book_metrics(books.get(coin, {}))
        signal_age_ms = max(0, now - timestamp_ms)
        fee_bps = 4.0
        slippage_bps = _estimate_slippage_bps(depth_usdc=depth_usdc, min_depth_usdc=min_depth_usdc)
        latency_bps = min(30.0, signal_age_ms / 1_000.0 * 2.0)
        base_edge_bps = 54.0 if signal_type in {"open", "add"} else 30.0
        if action.startswith("CLOSE") or signal_type == "close":
            base_edge_bps = 28.0
        if depth_usdc < min_depth_usdc:
            base_edge_bps -= 20.0
        edge_remaining_bps = round(base_edge_bps - fee_bps - spread_bps - slippage_bps - latency_bps, 8)
        candidate_id = "pd-" + stable_hash(
            {
                "wallet": wallet,
                "coin": coin,
                "action": action,
                "price": price,
                "time": timestamp_ms,
                "previous_size": _delta_value(delta, "previous_size", "old_size", "old_signed_size"),
                "new_size": _delta_value(delta, "new_size", "current_size", "new_signed_size"),
                "delta_hash": _delta_value(delta, "delta_hash", "event_hash"),
            }
        )
        candidates.append(
            SignalCandidate(
                id=candidate_id,
                source_wallet=wallet,
                coin=coin,
                side=side,
                signal_type=signal_type,
                observed_price=price,
                timestamp_ms=timestamp_ms,
                signal_age_ms=signal_age_ms,
                wallet_score=default_wallet_score,
                signal_score=default_signal_score,
                edge_remaining_bps=edge_remaining_bps,
                estimated_fee_bps=fee_bps,
                estimated_spread_bps=round(spread_bps, 8),
                estimated_slippage_bps=round(slippage_bps, 8),
                estimated_latency_decay_bps=round(latency_bps, 8),
                orderbook_depth_usdc=round(depth_usdc, 8),
                decision=SignalDecision.TESTNET_CANDIDATE,
            )
        )

    return CandidateFactoryReport(
        source=source,
        generated_at_ms=now,
        observed_at_ms=observed_at_ms or now,
        candidates=candidates,
        skipped=skipped,
        methodology=(
            "read_only_position_deltas_to_signal_candidates; unknown/flips skipped; "
            "costs include fee/spread/slippage/latency; no fake positions"
        ),
    )


def _parse_fill(
    wallet: str,
    fill: dict[str, Any],
    observation: MainnetObservation,
    now_ms: int,
) -> tuple[str, str, str, str, float, int] | CandidateFactorySkip:
    coin = str(fill.get("coin") or fill.get("asset") or "").upper().strip()
    if not coin:
        return CandidateFactorySkip(wallet=wallet, reason="missing_coin", raw=fill)
    direction = str(fill.get("dir") or fill.get("direction") or "").strip()
    signal_type, side = _map_fill_direction(direction, fill)
    if signal_type is None or side is None:
        return CandidateFactorySkip(wallet=wallet, reason="unsupported_fill_direction", raw=fill)
    price = _float_or_none(fill.get("px") or fill.get("price") or fill.get("markPx"))
    if price is None or price <= 0:
        price = _float_or_none(observation.all_mids.get(coin))
    if price is None or price <= 0:
        return CandidateFactorySkip(wallet=wallet, reason="missing_price", raw=fill)
    timestamp_ms = _timestamp_ms(fill, now_ms)
    return direction, signal_type, side, coin, price, timestamp_ms


def _parse_position_delta(
    delta: Any,
    all_mids: dict[str, Any],
    now_ms: int,
) -> tuple[str, str, str, float, int, str] | CandidateFactorySkip:
    raw = _raw_delta(delta)
    wallet = str(_delta_value(delta, "wallet_address", "source_wallet", "wallet") or "UNKNOWN_WALLET")
    coin = str(_delta_value(delta, "coin", "asset") or "").upper().strip()
    if not coin:
        return CandidateFactorySkip(wallet=wallet, reason="missing_coin", raw=raw)
    action = str(_delta_value(delta, "action", "action_type", "delta_type") or "UNKNOWN").upper().strip()
    signal_type, side = _map_delta_action(action, delta)
    if signal_type is None or side is None:
        return CandidateFactorySkip(wallet=wallet, reason="unknown_delta", raw=raw)
    price = _float_or_none(
        _delta_value(delta, "price", "mark_price", "current_price", "reference_price", "entry_price")
    )
    if price is None or price <= 0:
        price = _float_or_none(all_mids.get(coin))
    if price is None or price <= 0:
        return CandidateFactorySkip(wallet=wallet, reason="missing_price", raw=raw)
    timestamp_ms = _delta_timestamp_ms(delta, now_ms)
    return signal_type, side, coin, price, timestamp_ms, action


def _map_delta_action(action: str, delta: Any) -> tuple[str | None, str | None]:
    normalized = action.replace(" ", "_").replace("-", "_").upper()
    if normalized in {"UNKNOWN", "FLIP", "FLIP_LONG_TO_SHORT", "FLIP_SHORT_TO_LONG"}:
        return None, None
    if normalized == "OPEN_LONG":
        return "open", "long"
    if normalized == "OPEN_SHORT":
        return "open", "short"
    if normalized == "CLOSE_LONG":
        return "close", "long"
    if normalized == "CLOSE_SHORT":
        return "close", "short"
    side = _infer_delta_side(delta)
    if normalized in {"ADD", "INCREASE", "POSITION_INCREASE"} and side:
        return "add", side
    if normalized in {"REDUCE", "POSITION_REDUCE", "DECREASE"} and side:
        return "reduce", side
    if normalized in {"CLOSE"} and side:
        return "close", side
    if normalized in {"OPEN"} and side:
        return "open", side
    return None, None


def _infer_delta_side(delta: Any) -> str | None:
    for key in ("side", "new_side", "position_side", "direction"):
        value = str(_delta_value(delta, key) or "").lower()
        if "long" in value:
            return "long"
        if "short" in value:
            return "short"
    for key in ("new_size", "current_size", "signed_size", "new_signed_size"):
        size = _float_or_none(_delta_value(delta, key))
        if size is None:
            continue
        if size > 0:
            return "long"
        if size < 0:
            return "short"
    return None


def _map_fill_direction(direction: str, fill: dict[str, Any]) -> tuple[str | None, str | None]:
    normalized = direction.lower().replace("_", " ").strip()
    start_position = _float_or_none(fill.get("startPosition") or fill.get("start_position"))
    if normalized == "open long":
        return ("add" if start_position and start_position > 0 else "open"), "long"
    if normalized == "open short":
        return ("add" if start_position and start_position < 0 else "open"), "short"
    if normalized == "close long":
        return "close" if _is_full_close(fill) else "reduce", "long"
    if normalized == "close short":
        return "close" if _is_full_close(fill) else "reduce", "short"
    return None, None


def _is_full_close(fill: dict[str, Any]) -> bool:
    start_position = abs(_float_or_none(fill.get("startPosition") or fill.get("start_position")) or 0.0)
    size = abs(_float_or_none(fill.get("sz") or fill.get("size")) or 0.0)
    return bool(start_position and size and size >= start_position - 1e-12)


def _timestamp_ms(fill: dict[str, Any], default_ms: int) -> int:
    for key in ("time", "timestamp", "ts", "createdAt"):
        value = fill.get(key)
        parsed = _float_or_none(value)
        if parsed is None:
            continue
        if parsed < 10_000_000_000:
            parsed *= 1_000
        return int(parsed)
    return default_ms


def _delta_timestamp_ms(delta: Any, default_ms: int) -> int:
    for key in ("detected_at_ms", "exchange_ts", "timestamp_ms", "observed_at_ms", "created_at_ms", "time"):
        value = _delta_value(delta, key)
        parsed = _float_or_none(value)
        if parsed is None:
            continue
        if parsed < 10_000_000_000:
            parsed *= 1_000
        return int(parsed)
    return default_ms


def _raw_delta(delta: Any) -> dict[str, Any]:
    if isinstance(delta, dict):
        return dict(delta)
    raw: dict[str, Any] = {}
    for key in (
        "id",
        "wallet_address",
        "source_wallet",
        "wallet",
        "coin",
        "action",
        "delta_type",
        "previous_size",
        "current_size",
        "new_size",
        "delta_size",
        "side",
        "new_side",
        "price",
        "detected_at_ms",
        "exchange_ts",
        "delta_hash",
    ):
        if hasattr(delta, key):
            raw[key] = getattr(delta, key)
    extra = getattr(delta, "raw_json", None)
    if isinstance(extra, dict):
        raw.update({k: v for k, v in extra.items() if k not in raw})
    return raw


def _delta_value(delta: Any, *keys: str) -> Any:
    if isinstance(delta, dict):
        for key in keys:
            if key in delta:
                return delta[key]
        raw = delta.get("raw_json")
        if isinstance(raw, dict):
            for key in keys:
                if key in raw:
                    return raw[key]
        return None
    for key in keys:
        if hasattr(delta, key):
            return getattr(delta, key)
    raw = getattr(delta, "raw_json", None)
    if isinstance(raw, dict):
        for key in keys:
            if key in raw:
                return raw[key]
    return None


def _book_metrics(book: dict[str, Any]) -> tuple[float, float]:
    levels = book.get("levels") if isinstance(book, dict) else None
    if not isinstance(levels, list) or len(levels) < 2:
        return 5.0, 0.0
    bids = levels[0] if isinstance(levels[0], list) else []
    asks = levels[1] if isinstance(levels[1], list) else []
    best_bid = _level_price(bids[0]) if bids else None
    best_ask = _level_price(asks[0]) if asks else None
    depth = _levels_depth(bids[:10]) + _levels_depth(asks[:10])
    if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0:
        return 5.0, depth
    mid = (best_bid + best_ask) / 2.0
    if mid <= 0:
        return 5.0, depth
    return max(0.0, (best_ask - best_bid) / mid * 10_000.0), depth


def _levels_depth(levels: list[Any]) -> float:
    total = 0.0
    for level in levels:
        price = _level_price(level)
        size = _level_size(level)
        if price and size:
            total += price * size
    return total


def _level_price(level: Any) -> float | None:
    if isinstance(level, dict):
        return _float_or_none(level.get("px") or level.get("price"))
    if isinstance(level, (list, tuple)) and level:
        return _float_or_none(level[0])
    return None


def _level_size(level: Any) -> float | None:
    if isinstance(level, dict):
        return _float_or_none(level.get("sz") or level.get("size"))
    if isinstance(level, (list, tuple)) and len(level) > 1:
        return _float_or_none(level[1])
    return None


def _estimate_slippage_bps(*, depth_usdc: float, min_depth_usdc: float) -> float:
    if depth_usdc <= 0:
        return 12.0
    if depth_usdc >= min_depth_usdc * 10:
        return 1.5
    if depth_usdc >= min_depth_usdc:
        return 4.0
    return 10.0


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
