from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from hl_observer.markets.universe import is_exotic_market
from hl_observer.storage.models import PositionDeltaModel


DEFAULT_SIMULATION_MIN_EDGE_BPS = 15.0
DEFAULT_SIMULATION_MAX_SIGNAL_AGE_MS = 15_000
DEFAULT_SIMULATION_MIN_LIQUIDITY_SCORE = 0.22
DEFAULT_SIMULATION_MAX_COPY_DEGRADATION_BPS = 40.0
DEFAULT_SIMULATION_SINGLE_WALLET_MIN_EDGE_BPS = 28.0
DEFAULT_SIMULATION_ALLOW_ADD_AS_ENTRY = True
DEFAULT_HARD_STALE_SIGNAL_CAP_MS = 60_000


ENTRY_ACTIONS = {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}
EXIT_ACTIONS = {"REDUCE", "CLOSE_LONG", "CLOSE_SHORT"}
LIVE_DETECTED_SOURCE_TOKENS = (
    "hyperliquid_ws:userfills",
    "public_trades_ws",
    "publictradesws",
    "live",
    "fresh_opportunity_cluster",
)


def calibrated_float_env(name: str, default: float) -> float:
    try:
        return float(__import__("os").environ.get(name, ""))
    except (TypeError, ValueError):
        return float(default)


def calibrated_bool_env(name: str, default: bool) -> bool:
    raw = __import__("os").environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def hard_stale_signal_limit_ms(max_signal_age_ms: int) -> int:
    """Hard gate for live entries: never score historical fills as fresh."""

    return min(DEFAULT_HARD_STALE_SIGNAL_CAP_MS, max(1_000, int(max_signal_age_ms) * 2))


def is_hard_stale_signal(*, signal_time_ms: int | None, now_ms: int, max_signal_age_ms: int) -> bool:
    if not signal_time_ms or signal_time_ms <= 0:
        return True
    return max(0, int(now_ms) - int(signal_time_ms)) > hard_stale_signal_limit_ms(max_signal_age_ms)


def is_live_detected_delta_source(source: str | None) -> bool:
    normalized = str(source or "").lower()
    return any(token in normalized for token in LIVE_DETECTED_SOURCE_TOKENS)


def copy_candidate_signal_time_ms(row: PositionDeltaModel) -> int:
    """Use detection time only for truly live sources; REST/backfill uses fill time."""

    detected_at = int(row.detected_at_ms or 0)
    exchange_at = int(row.exchange_ts or 0)
    raw = row.raw_json if isinstance(row.raw_json, dict) else {}
    if "fresh_opportunity_cluster" in str(row.source or "").lower():
        try:
            leader_signal_ts = int(raw.get("leader_signal_ts") or 0)
        except (TypeError, ValueError):
            leader_signal_ts = 0
        if leader_signal_ts > 0:
            return leader_signal_ts
    if is_live_detected_delta_source(row.source) and detected_at > 0:
        return detected_at
    for key in ("time", "timestamp", "T"):
        try:
            value = int(raw.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return exchange_at or detected_at


def should_skip_exotic_for_copy(coin: str | None, *, include_builder_and_rwa_perps: bool) -> bool:
    if include_builder_and_rwa_perps:
        return False
    return is_exotic_market(str(coin or ""))


def should_skip_orphan_exit_or_unknown(action: str, has_matching_position: bool) -> bool:
    if action == "UNKNOWN":
        return True
    if action in EXIT_ACTIONS and not has_matching_position:
        return True
    return False


def fill_identity(row: PositionDeltaModel) -> str | None:
    """Stable raw-fill identity across polls, even if DB ids or delta_hash differ."""

    raw = row.raw_json if isinstance(row.raw_json, dict) else {}
    fill_hash = _first(raw, "hash", "fill_hash", "tx_hash")
    tid = _first(raw, "tid", "trade_id")
    oid = _first(raw, "oid", "order_id")
    timestamp = _first(raw, "time", "timestamp", "T")
    direction = _first(raw, "dir", "direction", "side")
    price = _first(raw, "px", "price")
    size = _first(raw, "sz", "size")

    if fill_hash or tid or oid:
        payload = {
            "wallet": str(row.wallet_address or "").lower(),
            "coin": str(row.coin or "").upper(),
            "hash": fill_hash,
            "tid": tid,
            "oid": oid,
            "time": timestamp or row.exchange_ts,
            "dir": direction or row.delta_type or row.action,
            "px": price or row.price,
            "sz": size or row.fill_size or row.delta_size,
        }
        return "fill:" + sha256(_stable_json(payload).encode("utf-8")).hexdigest()
    return None


def delta_identity(row: PositionDeltaModel) -> str:
    raw_identity = fill_identity(row)
    if raw_identity:
        return raw_identity
    if row.delta_hash:
        return f"hash:{row.delta_hash}"
    if row.id is not None:
        return f"id:{row.id}"
    payload = {
        "wallet": str(row.wallet_address or "").lower(),
        "coin": str(row.coin or "").upper(),
        "exchange_ts": row.exchange_ts,
        "detected_at_ms": row.detected_at_ms,
        "delta_type": row.delta_type,
        "previous_size": row.previous_size,
        "new_size": row.new_size,
        "delta_size": row.delta_size,
        "price": row.price,
    }
    return "raw:" + sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _first(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return None


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
