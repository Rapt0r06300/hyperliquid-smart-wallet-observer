"""Canonical local resolver for fresh Hyperliquid L2 observations.

The resolver owns no network client.  It reconciles already observed public
market data and an optional explicitly injected on-demand reader.  This keeps
copy-vault decisions causal while avoiding three independent freshness rules.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from hl_observer.paper_trading.execution_truth import (
    MAX_SUPPORTED_EPOCH_MS,
    ExecutionTruth,
    Levels,
)

DYNAMIC_L2_RELPATH = Path("runtime") / "data" / "raw_l2_live.json"
BBO_RELPATH = Path("runtime") / "data" / "bbo_synchro.jsonl"
CARNET_RELPATH = Path("runtime") / "data" / "carnet_venues.jsonl"

DEFAULT_MAX_AGE_MS = 1_000
DEFAULT_FUTURE_SKEW_MS = 2_000
DEFAULT_JSONL_TAIL_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class LiveL2Snapshot:
    """One validated, causal public L2 observation."""

    coin: str
    best_bid: float
    best_ask: float
    depth_usd: float
    source: str
    received_ts_ms: int
    exchange_ts_ms: int | None = None
    bids: Levels = ()
    asks: Levels = ()
    data_origin: str = "REAL"
    exchange_ts_raw: object = None
    exchange_ts_status: str = "MISSING"
    received_ts_raw: object = None
    received_ts_unit: str = "ms_since_unix_epoch"

    def __post_init__(self) -> None:
        if self.exchange_ts_status == "MISSING" and self.exchange_ts_ms is not None:
            raw = self.exchange_ts_ms if self.exchange_ts_raw is None else self.exchange_ts_raw
            parsed, status = _parse_exchange_ts_ms(raw)
            object.__setattr__(self, "exchange_ts_raw", raw)
            object.__setattr__(self, "exchange_ts_ms", parsed)
            object.__setattr__(self, "exchange_ts_status", status)

    def age_ms(self, now_ms: int) -> int:
        if type(now_ms) is not int or not 0 < now_ms <= MAX_SUPPORTED_EPOCH_MS:
            raise ValueError("L2 age reference must be a supported epoch millisecond")
        age = now_ms - self.received_ts_ms
        if age < 0:
            raise ValueError("L2 observation received after reference time")
        return age

    @property
    def has_full_book(self) -> bool:
        return bool(self.bids and self.asks)

    def as_legacy_payload(self, *, now_ms: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "hl_bid": self.best_bid,
            "hl_ask": self.best_ask,
            "depth_usd": self.depth_usd,
            "src": _legacy_source(self.source),
            "source": self.source,
            "age_ms": self.age_ms(now_ms),
            "received_ts_ms": self.received_ts_ms,
            "exchange_ts_ms": self.exchange_ts_ms,
            "exchange_ts_raw": self.exchange_ts_raw,
            "exchange_ts_status": self.exchange_ts_status,
            "received_ts_raw": (
                str(self.received_ts_raw)
                if isinstance(self.received_ts_raw, Decimal)
                else self.received_ts_ms
                if self.received_ts_raw is None
                else self.received_ts_raw
            ),
            "received_ts_unit": self.received_ts_unit,
            "data_origin": self.data_origin,
        }
        if self.has_full_book:
            payload["bids"] = [list(level) for level in self.bids]
            payload["asks"] = [list(level) for level in self.asks]
        return payload

    def execution_truth(self) -> ExecutionTruth | None:
        """Return strict execution truth only when real full levels exist."""

        if not self.has_full_book:
            return None
        return ExecutionTruth.from_levels(
            coin=self.coin,
            bids=self.bids,
            asks=self.asks,
            received_ts_ms=self.received_ts_ms,
            exchange_ts_ms=self.exchange_ts_raw,
            source=self.source,
            data_origin=self.data_origin,
            received_ts_raw=(
                self.received_ts_ms
                if self.received_ts_raw is None
                else self.received_ts_raw
            ),
            received_ts_unit=self.received_ts_unit,
        )


class LiveL2Service:
    """Resolve the freshest valid local L2 observation for one coin."""

    def __init__(
        self,
        root: str | Path = ".",
        *,
        on_demand_reader: Callable[[str], Mapping[str, Any] | None] | None = None,
        max_age_ms: int = DEFAULT_MAX_AGE_MS,
        future_skew_ms: int = DEFAULT_FUTURE_SKEW_MS,
    ) -> None:
        self.root = Path(root)
        self.on_demand_reader = on_demand_reader
        self.max_age_ms = max(0, int(max_age_ms))
        # Kept for call-site compatibility. Local receipt clocks are now
        # strictly causal, so this setting cannot admit future observations.
        self.future_skew_ms = max(0, int(future_skew_ms))

    def resolve(
        self,
        coin: str,
        *,
        now_ms: int | float | None = None,
        bbo: Mapping[str, Mapping[str, Any]] | None = None,
        carnet: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> LiveL2Snapshot | None:
        normalized = str(coin or "").strip().upper()
        if not normalized:
            return None
        if now_ms is None:
            now = time.time_ns() // 1_000_000
        elif type(now_ms) is int and 0 < now_ms <= MAX_SUPPORTED_EPOCH_MS:
            now = now_ms
        else:
            return None
        candidates: list[tuple[int, int, LiveL2Snapshot]] = []

        if self.on_demand_reader is not None:
            try:
                observed = self.on_demand_reader(normalized)
            except Exception:
                observed = None
            snapshot = snapshot_from_mapping(
                normalized,
                observed,
                source="hyperliquid:on_demand:l2Book",
                now_ms=now,
            )
            self._append_if_fresh(candidates, snapshot, now_ms=now, priority=4)

        dynamic = _read_dynamic_mapping(self.root).get(normalized)
        snapshot = snapshot_from_mapping(
            normalized,
            dynamic,
            source="hyperliquid:ws:l2Book:dynamic",
            now_ms=now,
        )
        self._append_if_fresh(candidates, snapshot, now_ms=now, priority=3)

        bbo_rows = bbo if bbo is not None else _latest_jsonl_by_coin(self.root / BBO_RELPATH)
        snapshot = snapshot_from_mapping(
            normalized,
            bbo_rows.get(normalized),
            source="hyperliquid:ws:bbo",
            now_ms=now,
        )
        self._append_if_fresh(candidates, snapshot, now_ms=now, priority=2)

        carnet_rows = carnet if carnet is not None else _latest_jsonl_by_coin(self.root / CARNET_RELPATH)
        snapshot = snapshot_from_mapping(
            normalized,
            carnet_rows.get(normalized),
            source="hyperliquid:/info:l2Book:bounded",
            now_ms=now,
        )
        self._append_if_fresh(candidates, snapshot, now_ms=now, priority=1)

        if not candidates:
            return None
        return max(candidates, key=lambda item: (item[0], item[1]))[2]

    def as_legacy_reader(self) -> Callable[[str], dict[str, Any] | None]:
        def read(coin: str) -> dict[str, Any] | None:
            now = time.time_ns() // 1_000_000
            snapshot = self.resolve(coin, now_ms=now)
            return None if snapshot is None else snapshot.as_legacy_payload(now_ms=now)

        return read

    def _append_if_fresh(
        self,
        candidates: list[tuple[int, int, LiveL2Snapshot]],
        snapshot: LiveL2Snapshot | None,
        *,
        now_ms: int,
        priority: int,
    ) -> None:
        if snapshot is None:
            return
        age = now_ms - snapshot.received_ts_ms
        # A local receipt timestamp is produced by this machine's wall clock;
        # tolerating a future value here would make age_ms clamp it to zero and
        # could leak a future book through the legacy adapter.
        if age < 0 or age > self.max_age_ms:
            return
        candidates.append((snapshot.received_ts_ms, priority, snapshot))


def snapshot_from_mapping(
    coin: str,
    payload: Mapping[str, Any] | None,
    *,
    source: str,
    now_ms: int,
) -> LiveL2Snapshot | None:
    if not payload:
        return None
    try:
        bids, asks = _extract_levels(payload)
        bid = _positive(payload.get("hl_bid"))
        ask = _positive(payload.get("hl_ask"))
        if bids:
            bid = bids[0][0]
        if asks:
            ask = asks[0][0]
        if bid is None or ask is None or ask < bid:
            return None
        received_ts_ms, parsed_received_raw, parsed_received_unit = _received_timestamp(payload)
        if received_ts_ms is None:
            return None
        received_ts_raw = payload.get("received_ts_raw", parsed_received_raw)
        received_ts_unit = payload.get("received_ts_unit", parsed_received_unit)
        if received_ts_unit not in {
            "ms_since_unix_epoch",
            "s_since_unix_epoch_utc",
        }:
            return None
        raw_exchange_ts = _first_present(
            payload,
            (
                "exchange_ts_raw",
                "exchange_ts_ms",
                "exchange_ts_hl_ms",
                "ts_ex_hl",
                "time",
            ),
        )
        exchange_ts_ms, exchange_ts_status = _parse_exchange_ts_ms(raw_exchange_ts)
        depth = _positive(
            payload.get("depth_usd")
            or payload.get("taille_top_usd")
            or payload.get("taille_min_usd")
        )
        if bids and asks:
            bid_depth = _visible_notional_usd(bids)
            ask_depth = _visible_notional_usd(asks)
            if bid_depth is None or ask_depth is None:
                return None
            if depth is None:
                depth = min(bid_depth, ask_depth)
        actual_source = str(payload.get("source") or payload.get("src") or source).strip() or source
        origin = str(payload.get("data_origin") or "REAL").strip().upper()
        if origin not in {"REAL", "RECORDED_REAL"}:
            return None
        return LiveL2Snapshot(
            coin=str(coin).strip().upper(),
            best_bid=bid,
            best_ask=ask,
            depth_usd=float(depth or 0.0),
            source=actual_source,
            received_ts_ms=received_ts_ms,
            exchange_ts_ms=exchange_ts_ms,
            bids=bids,
            asks=asks,
            data_origin=origin,
            exchange_ts_raw=raw_exchange_ts,
            exchange_ts_status=exchange_ts_status,
            received_ts_raw=received_ts_raw,
            received_ts_unit=received_ts_unit,
        )
    except (TypeError, ValueError, OverflowError):
        return None


def write_dynamic_snapshot(
    root: str | Path,
    snapshot: LiveL2Snapshot,
    *,
    relpath: Path = DYNAMIC_L2_RELPATH,
) -> None:
    """Atomically publish one full dynamic snapshot for other processes."""

    path = Path(root) / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    current = _read_json_object(path)
    current[snapshot.coin] = {
        "hl_bid": snapshot.best_bid,
        "hl_ask": snapshot.best_ask,
        "depth_usd": snapshot.depth_usd,
        "source": snapshot.source,
        "received_ts_ms": snapshot.received_ts_ms,
        "received_ts_raw": (
            str(snapshot.received_ts_raw)
            if isinstance(snapshot.received_ts_raw, Decimal)
            else snapshot.received_ts_ms
            if snapshot.received_ts_raw is None
            else snapshot.received_ts_raw
        ),
        "received_ts_unit": snapshot.received_ts_unit,
        "exchange_ts_ms": snapshot.exchange_ts_ms,
        "exchange_ts_raw": snapshot.exchange_ts_raw,
        "exchange_ts_status": snapshot.exchange_ts_status,
        "collecte_ts": snapshot.received_ts_ms / 1_000.0,
        "data_origin": snapshot.data_origin,
        "bids": [list(level) for level in snapshot.bids],
        "asks": [list(level) for level in snapshot.asks],
    }
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(current, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


def _extract_levels(payload: Mapping[str, Any]) -> tuple[Levels, Levels]:
    raw_bids = payload.get("bids")
    raw_asks = payload.get("asks")
    levels = payload.get("levels")
    if (raw_bids is None or raw_asks is None) and isinstance(levels, Sequence) and len(levels) >= 2:
        raw_bids, raw_asks = levels[0], levels[1]
    bids = _clean_levels(raw_bids, reverse=True)
    asks = _clean_levels(raw_asks, reverse=False)
    if bool(bids) != bool(asks):
        return (), ()
    return bids, asks


def _clean_levels(raw: Any, *, reverse: bool) -> Levels:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return ()
    clean: list[tuple[float, float]] = []
    for row in raw:
        try:
            if isinstance(row, Mapping):
                price = float(row.get("px"))
                size = float(row.get("sz"))
            else:
                price = float(row[0])
                size = float(row[1])
        except (TypeError, ValueError, KeyError, IndexError):
            continue
        if math.isfinite(price) and math.isfinite(size) and price > 0 and size > 0:
            clean.append((price, size))
    clean.sort(key=lambda level: level[0], reverse=reverse)
    return tuple(clean)


def _positive(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def _visible_notional_usd(levels: Levels) -> float | None:
    total = 0.0
    for price, size in levels:
        notional = price * size
        if not math.isfinite(notional) or notional <= 0.0:
            return None
        total += notional
        if not math.isfinite(total):
            return None
    return total if total > 0.0 else None


def _received_ts_ms(payload: Mapping[str, Any]) -> int | None:
    return _received_timestamp(payload)[0]


def _received_timestamp(
    payload: Mapping[str, Any],
) -> tuple[int | None, object, str]:
    for key in (
        "received_ts_ms",
        "recv_wall_ts_ms",
        "recv_wall_hl_ms",
        "snapshot_wall_ts_ms",
        "write_wall_ts_ms",
        "ts_ms",
    ):
        if key in payload:
            value = payload.get(key)
            parsed = (
                value
                if type(value) is int and 0 < value <= MAX_SUPPORTED_EPOCH_MS
                else None
            )
            return parsed, value, "ms_since_unix_epoch"
    if "collecte_ts" in payload:
        value = payload.get("collecte_ts")
        if type(value) is int:
            seconds = Decimal(value)
        elif isinstance(value, (float, Decimal)) and not isinstance(value, bool):
            seconds = Decimal(str(value))
        else:
            return None, value, "s_since_unix_epoch_utc"
        try:
            milliseconds = seconds * 1_000
        except (InvalidOperation, ValueError, TypeError):
            return None, value, "s_since_unix_epoch_utc"
        if (
            not milliseconds.is_finite()
            or milliseconds <= 0
            or milliseconds > MAX_SUPPORTED_EPOCH_MS
        ):
            return None, value, "s_since_unix_epoch_utc"
        # The legacy source is a wall-clock float in seconds and commonly has
        # sub-millisecond precision. Floor to the stored millisecond boundary;
        # this is conservative for freshness and never rounds the observation
        # forward into the future.
        return (
            int(milliseconds.to_integral_value(rounding=ROUND_FLOOR)),
            value,
            "s_since_unix_epoch_utc",
        )
    return None, None, "ms_since_unix_epoch"


def _first_present(payload: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _parse_exchange_ts_ms(value: object) -> tuple[int | None, str]:
    if value is None:
        return None, "MISSING"
    if (
        type(value) is not int
        or value < 100_000_000_000
        or value > MAX_SUPPORTED_EPOCH_MS
    ):
        return None, "INVALID"
    return value, "VALID"


def _read_dynamic_mapping(root: Path) -> dict[str, Mapping[str, Any]]:
    raw = _read_json_object(root / DYNAMIC_L2_RELPATH)
    return {
        str(coin).strip().upper(): value
        for coin, value in raw.items()
        if isinstance(value, Mapping)
    }


def _latest_jsonl_by_coin(path: Path) -> dict[str, Mapping[str, Any]]:
    rows: dict[str, Mapping[str, Any]] = {}
    if not path.exists():
        return rows
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - DEFAULT_JSONL_TAIL_BYTES))
            raw = handle.read()
    except OSError:
        return rows
    if size > len(raw):
        raw = raw.split(b"\n", 1)[-1]
    for line in raw.decode("utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line, parse_float=Decimal)
        except (TypeError, ValueError):
            continue
        if not isinstance(row, Mapping):
            continue
        coin = str(row.get("coin") or "").strip().upper()
        if coin:
            rows[coin] = row
    return rows


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    except (OSError, ValueError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _legacy_source(source: str) -> str:
    normalized = str(source or "").lower()
    if "on_demand" in normalized:
        return "on_demand"
    if "dynamic" in normalized:
        return "l2_ws_dynamic"
    if ":bbo" in normalized:
        return "bbo_ws"
    if "bounded" in normalized or "carnet" in normalized:
        return "carnet"
    return str(source)


def _l2_base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _l2_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _l2_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def l2_safety_receipt(payload: Mapping[str, Any], *, coin: str = "BTC", now_ms: int) -> dict[str, Any]:
    snapshot = snapshot_from_mapping(coin, payload, source="hyperliquid:ws:l2Book", now_ms=now_ms)
    valid = snapshot is not None and snapshot.has_full_book and snapshot.data_origin in {"REAL", "RECORDED_REAL"}
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_FULL_BOOK_SAFE" if valid else "L2_NOT_SAFE", has_full_book=bool(snapshot and snapshot.has_full_book), fail_closed=not valid)


def l2_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_FIELD_PRESENT" if valid else "L2_FIELD_MISSING", field=field, fail_closed=not valid)


def l2_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_FIELD_NON_NULL" if valid else "L2_FIELD_NULL", field=field, fail_closed=not valid)


def l2_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_FIELD_TYPE_VALID" if valid else "L2_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def l2_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _l2_finite(value)
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_VALUE_FINITE" if valid else "L2_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def l2_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _l2_integer(event_ts_ms) and _l2_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_EVENT_WITHIN_CUTOFF" if valid else "L2_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def l2_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _l2_integer(event_ts_ms) and _l2_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_EVENT_AGE_VALID" if valid else "L2_EVENT_TOO_OLD", fail_closed=not valid)


def l2_duplicate_receipt(*, event_ids: list[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_EVENTS_UNIQUE" if valid else "L2_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def l2_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _l2_integer(attempts) and _l2_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_RETRY_BOUNDED" if valid else "L2_RETRY_UNSAFE", fail_closed=not valid)


def l2_replay_receipt(*, outputs: list[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_REPLAY_DETERMINISTIC" if valid else "L2_REPLAY_DIVERGED", fail_closed=not valid)


def l2_depth_receipt(*, bids: Sequence[Sequence[Any]], asks: Sequence[Sequence[Any]], is_bbo: bool) -> dict[str, Any]:
    valid = bool(bids) and bool(asks) and is_bbo is False and all(len(level) >= 2 and _l2_finite(level[0]) and _l2_finite(level[1]) and float(level[1]) > 0 for level in (*bids, *asks))
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_FULL_DEPTH" if valid else "L2_BBO_OR_INVALID_DEPTH", fail_closed=not valid)


def l2_crossed_book_receipt(*, best_bid: Any, best_ask: Any) -> dict[str, Any]:
    valid = _l2_finite(best_bid) and _l2_finite(best_ask) and float(best_ask) >= float(best_bid) > 0
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_BOOK_NOT_CROSSED" if valid else "L2_BOOK_CROSSED_OR_INVALID", fail_closed=not valid)


def l2_negative_size_receipt(*, sizes: Sequence[Any]) -> dict[str, Any]:
    valid = bool(sizes) and all(_l2_finite(size) and float(size) > 0 for size in sizes)
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_SIZES_POSITIVE" if valid else "L2_NEGATIVE_OR_ZERO_SIZE", fail_closed=not valid)


def l2_tick_receipt(*, prices: Sequence[Any], tick_size: Any) -> dict[str, Any]:
    try:
        tick = Decimal(str(tick_size))
        valid = tick > 0 and bool(prices) and all(Decimal(str(price)) % tick == 0 for price in prices)
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        valid = False
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_TICK_ALIGNED" if valid else "L2_TICK_INVALID", fail_closed=not valid)


def l2_delta_receipt(*, has_snapshot: bool, delta_count: Any) -> dict[str, Any]:
    valid = has_snapshot is True and _l2_integer(delta_count) and delta_count > 0
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_DELTA_HAS_SNAPSHOT" if valid else "L2_DELTA_WITHOUT_SNAPSHOT", fail_closed=not valid)


def l2_staleness_receipt(*, now_ms: Any, received_ts_ms: Any, max_age_ms: Any) -> dict[str, Any]:
    valid = all(_l2_integer(value) for value in (now_ms, received_ts_ms, max_age_ms)) and now_ms >= received_ts_ms and now_ms - received_ts_ms <= max_age_ms
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_FRESH" if valid else "L2_STALE", age_ms=(now_ms - received_ts_ms) if valid else None, fail_closed=not valid)


def l2_quantity_receipt(*, requested_quantity: Any, visible_depth: Any) -> dict[str, Any]:
    valid = _l2_finite(requested_quantity) and _l2_finite(visible_depth) and 0 < float(requested_quantity) <= float(visible_depth)
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_QUANTITY_WITHIN_DEPTH" if valid else "L2_QUANTITY_EXCEEDS_DEPTH", fail_closed=not valid)


def l2_consumption_receipt(*, consumed_quantity: Any, available_quantity: Any, already_consumed: Any) -> dict[str, Any]:
    valid = all(_l2_finite(value) for value in (consumed_quantity, available_quantity, already_consumed)) and min(float(consumed_quantity), float(available_quantity), float(already_consumed)) >= 0 and float(consumed_quantity) + float(already_consumed) <= float(available_quantity)
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_CONSUMPTION_ONCE" if valid else "L2_DOUBLE_CONSUMPTION", fail_closed=not valid)


def l2_maker_touch_receipt(*, touched: bool, executed: bool) -> dict[str, Any]:
    valid = touched is False or executed is True
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_MAKER_EXECUTION_CONFIRMED" if valid else "L2_TOUCH_ONLY_NOT_FILL", fail_closed=not valid)


def l2_fee_order_receipt(*, maker_fee_bps: Any, taker_fee_bps: Any) -> dict[str, Any]:
    valid = _l2_finite(maker_fee_bps) and _l2_finite(taker_fee_bps) and float(maker_fee_bps) >= 0 and float(taker_fee_bps) >= float(maker_fee_bps)
    return _l2_base("PROVEN" if valid else "REJECTED", verdict="L2_FEE_ORDER_VALID" if valid else "L2_FEE_ORDER_INVERTED", fail_closed=not valid)


__all__ = [
    "BBO_RELPATH",
    "CARNET_RELPATH",
    "DEFAULT_MAX_AGE_MS",
    "DYNAMIC_L2_RELPATH",
    "LiveL2Service",
    "LiveL2Snapshot",
    "snapshot_from_mapping",
    "write_dynamic_snapshot",
    "l2_safety_receipt",
    "l2_required_field_receipt",
    "l2_null_field_receipt",
    "l2_field_type_receipt",
    "l2_finite_receipt",
    "l2_cutoff_receipt",
    "l2_age_receipt",
    "l2_duplicate_receipt",
    "l2_retry_receipt",
    "l2_replay_receipt",
    "l2_depth_receipt",
    "l2_crossed_book_receipt",
    "l2_negative_size_receipt",
    "l2_tick_receipt",
    "l2_delta_receipt",
    "l2_staleness_receipt",
    "l2_quantity_receipt",
    "l2_consumption_receipt",
    "l2_maker_touch_receipt",
    "l2_fee_order_receipt",
]
