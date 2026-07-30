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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from hl_observer.paper_trading.execution_truth import ExecutionTruth, Levels

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

    def age_ms(self, now_ms: int) -> int:
        return max(0, int(now_ms) - self.received_ts_ms)

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
            exchange_ts_ms=self.exchange_ts_ms,
            source=self.source,
            data_origin=self.data_origin,
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
        now = int(now_ms if now_ms is not None else time.time() * 1_000)
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
            now = int(time.time() * 1_000)
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
        if age < -self.future_skew_ms or age > self.max_age_ms:
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
        received_ts_ms = _received_ts_ms(payload, now_ms=now_ms)
        exchange_ts_ms = _optional_ts_ms(
            payload.get("exchange_ts_ms")
            or payload.get("exchange_ts_hl_ms")
            or payload.get("ts_ex_hl")
            or payload.get("time")
        )
        depth = _positive(
            payload.get("depth_usd")
            or payload.get("taille_top_usd")
            or payload.get("taille_min_usd")
        )
        if depth is None and bids and asks:
            depth = min(
                sum(price * size for price, size in bids),
                sum(price * size for price, size in asks),
            )
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
        "exchange_ts_ms": snapshot.exchange_ts_ms,
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


def _received_ts_ms(payload: Mapping[str, Any], *, now_ms: int) -> int:
    for key in (
        "received_ts_ms",
        "recv_wall_ts_ms",
        "recv_wall_hl_ms",
        "snapshot_wall_ts_ms",
        "write_wall_ts_ms",
        "ts_ms",
    ):
        parsed = _optional_ts_ms(payload.get(key))
        if parsed is not None:
            return parsed
    collecte = _positive(payload.get("collecte_ts"))
    if collecte is not None:
        return int(collecte * 1_000)
    age = payload.get("age_ms")
    if age is not None:
        parsed_age = max(0, int(float(age)))
        return max(1, now_ms - parsed_age)
    return max(1, now_ms)


def _optional_ts_ms(value: Any) -> int | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0:
        return None
    if parsed < 100_000_000_000:
        parsed *= 1_000
    return int(parsed)


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
            row = json.loads(line)
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
        value = json.loads(path.read_text(encoding="utf-8"))
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


__all__ = [
    "BBO_RELPATH",
    "CARNET_RELPATH",
    "DEFAULT_MAX_AGE_MS",
    "DYNAMIC_L2_RELPATH",
    "LiveL2Service",
    "LiveL2Snapshot",
    "snapshot_from_mapping",
    "write_dynamic_snapshot",
]
