"""Forward-only causal L2 checkpoints for Copy-Vault economic evidence.

The main ``userfills-live`` collector owns the live fill stream.  This small
companion tails only bytes appended after its first startup and captures public
Hyperliquid ``/info`` L2 books after predeclared REFERENCE, ENTRY and EXIT
instants.  It never reads historical books, interpolates a quote, or performs
an exchange action.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from hl_observer.backtesting.copy_vault_executable import PROTOCOL_NAME
from hl_observer.experimental.metaorder_l2_tape import metaorder_id

SCHEMA_VERSION = "hypersmart.copy_vault_checkpoint_tail.v1"
COMPANION_PROTOCOL = f"copy_vault_checkpoint_companion_v1_for_{PROTOCOL_NAME}"
INPUT_RELPATH = Path("runtime") / "data" / "vault_fills_live.jsonl"
OUTPUT_RELPATH = Path("runtime") / "data" / "copy_vault_l2_tape.jsonl"
STATE_RELPATH = Path("runtime") / "data" / "copy_vault_checkpoint_tail_state.json"
INFO_URL = "https://api.hyperliquid.xyz/info"

COPY_DELAY_MS = 60_000
HORIZONS_MS = (300_000, 900_000, 1_800_000, 3_600_000)
MAX_TARGET_LAG_MS = 30_000
METAORDER_GAP_MS = 60_000
MAX_EVENT_IDS = 20_000
MAX_CHECKPOINT_IDS = 20_000
MAX_PENDING = 5_000
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

BookFetcher = Callable[[str], Mapping[str, Any] | None]
Clock = Callable[[], int]


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.01 * (attempt + 1))
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def fetch_hyperliquid_l2_book(coin: str, *, timeout_s: float = 2.0) -> dict[str, Any] | None:
    """Fetch one public read-only Hyperliquid L2 book.

    The only network destination is the official ``/info`` endpoint.  No
    credential, signature or write payload exists in this module.
    """

    body = json.dumps({"type": "l2Book", "coin": str(coin).upper()}).encode("utf-8")
    request = urllib.request.Request(
        INFO_URL,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "HyperSmart/read-only"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(0.2, float(timeout_s))) as response:
            if int(response.status) != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _default_state(*, offset: int, now_ms: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "paper_read_only": True,
        "real_execution": False,
        "protocol": COMPANION_PROTOCOL,
        "initialized_at_ms": int(now_ms),
        "input_offset": max(0, int(offset)),
        "recent_event_ids": [],
        "captured_checkpoint_ids": [],
        "metaorder_state": {},
        "pending": [],
        "counters": {
            "complete_lines": 0,
            "valid_live_fills": 0,
            "duplicates_rejected": 0,
            "invalid_rejected": 0,
            "stale_rejected": 0,
            "out_of_order_rejected": 0,
            "metaorders_started": 0,
            "continuations": 0,
            "checkpoints_captured": 0,
            "checkpoints_expired": 0,
            "fetch_retries": 0,
            "input_rotations": 0,
        },
    }


def _event_identity(fill: Mapping[str, Any]) -> str:
    material = (
        str(fill.get("stable_event_id") or ""),
        str(fill.get("hash") or ""),
        str(fill.get("tid") or ""),
        str(fill.get("oid") or ""),
        int(fill.get("ts_ms") or 0),
        str(fill.get("vault") or "").lower(),
        str(fill.get("coin") or "").upper(),
        str(fill.get("sz") or ""),
        str(fill.get("px") or ""),
    )
    return hashlib.sha256(repr(material).encode("utf-8")).hexdigest()


def _trim(values: list[str], limit: int) -> list[str]:
    return values[-max(1, int(limit)) :]


def _parse_book(raw: Mapping[str, Any], *, received_at_ms: int) -> dict[str, Any] | None:
    try:
        exchange_ts_ms = int(raw["time"])
        raw_bids, raw_asks = raw["levels"][0], raw["levels"][1]
        bids = [[float(row["px"]), float(row["sz"])] for row in raw_bids[:5]]
        asks = [[float(row["px"]), float(row["sz"])] for row in raw_asks[:5]]
    except (KeyError, IndexError, TypeError, ValueError, OverflowError):
        return None
    if (
        exchange_ts_ms <= 0
        or received_at_ms < exchange_ts_ms
        or received_at_ms - exchange_ts_ms > MAX_TARGET_LAG_MS
        or not bids
        or not asks
        or any(px <= 0 or size <= 0 for px, size in bids + asks)
        or bids[0][0] >= asks[0][0]
    ):
        return None
    capacity_usd = min(
        sum(px * size for px, size in bids),
        sum(px * size for px, size in asks),
    )
    if capacity_usd <= 0:
        return None
    return {
        "exchange_ts_ms": exchange_ts_ms,
        "bid": bids[0][0],
        "ask": asks[0][0],
        "bids5": bids,
        "asks5": asks,
        "capacity_usd": capacity_usd,
    }


class CopyVaultCheckpointTail:
    """Durable forward-only tail and causal checkpoint scheduler."""

    def __init__(
        self,
        root: str | Path,
        *,
        fetch_book: BookFetcher = fetch_hyperliquid_l2_book,
        clock_ms: Clock | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.input_path = self.root / INPUT_RELPATH
        self.output_path = self.root / OUTPUT_RELPATH
        self.state_path = self.root / STATE_RELPATH
        self.fetch_book = fetch_book
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self.state = self._load_or_initialize()

    def _load_or_initialize(self) -> dict[str, Any]:
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            loaded = None
        if (
            isinstance(loaded, dict)
            and loaded.get("schema_version") == SCHEMA_VERSION
            and loaded.get("paper_read_only") is True
            and loaded.get("real_execution") is False
            and loaded.get("protocol") == COMPANION_PROTOCOL
        ):
            return loaded
        try:
            offset = self.input_path.stat().st_size
        except OSError:
            offset = 0
        state = _default_state(offset=offset, now_ms=self.clock_ms())
        _atomic_write(self.state_path, state)
        return state

    def _read_appended_lines(self) -> list[dict[str, Any]]:
        try:
            size = self.input_path.stat().st_size
        except OSError:
            return []
        offset = int(self.state.get("input_offset") or 0)
        if size < offset:
            self.state["input_offset"] = size
            self.state["counters"]["input_rotations"] += 1
            return []
        if size == offset:
            return []
        try:
            with self.input_path.open("rb") as handle:
                handle.seek(offset)
                chunk = handle.read()
        except OSError:
            return []
        complete_end = chunk.rfind(b"\n")
        if complete_end < 0:
            return []
        consumed = chunk[: complete_end + 1]
        self.state["input_offset"] = offset + len(consumed)
        rows: list[dict[str, Any]] = []
        for line in consumed.splitlines():
            if not line.strip():
                continue
            self.state["counters"]["complete_lines"] += 1
            try:
                row = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, TypeError):
                self.state["counters"]["invalid_rejected"] += 1
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                self.state["counters"]["invalid_rejected"] += 1
        return rows

    def _schedule_fill(self, fill: Mapping[str, Any], *, now_ms: int) -> None:
        try:
            vault = str(fill["vault"]).lower()
            coin = str(fill["coin"]).upper().strip()
            direction = int(fill.get("signe") or fill.get("sens") or 0)
            fill_ts_ms = int(fill["ts_ms"])
            received_at_ms = int(fill["received_at_ms"])
        except (KeyError, TypeError, ValueError, OverflowError):
            self.state["counters"]["invalid_rejected"] += 1
            return
        if (
            fill.get("source") != "LIVE_WS"
            or fill.get("isSnapshot") is not False
            or not ADDRESS_RE.fullmatch(vault)
            or not coin
            or direction not in (-1, 1)
            or fill_ts_ms <= 0
            or received_at_ms < fill_ts_ms
            or received_at_ms - fill_ts_ms > MAX_TARGET_LAG_MS
        ):
            self.state["counters"]["invalid_rejected"] += 1
            return
        if now_ms < received_at_ms or now_ms - received_at_ms > MAX_TARGET_LAG_MS:
            self.state["counters"]["stale_rejected"] += 1
            return
        event_id = _event_identity(fill)
        recent = list(self.state.get("recent_event_ids") or [])
        if event_id in set(recent):
            self.state["counters"]["duplicates_rejected"] += 1
            return
        recent.append(event_id)
        self.state["recent_event_ids"] = _trim(recent, MAX_EVENT_IDS)
        self.state["counters"]["valid_live_fills"] += 1

        key = f"{vault}|{coin}"
        meta_state = dict(self.state.get("metaorder_state") or {})
        previous = meta_state.get(key) if isinstance(meta_state.get(key), dict) else None
        if previous is not None and fill_ts_ms < int(previous.get("last_fill_ts_ms") or 0):
            self.state["counters"]["out_of_order_rejected"] += 1
            return
        continuation = bool(
            previous
            and int(previous.get("direction") or 0) == direction
            and fill_ts_ms - int(previous.get("last_fill_ts_ms") or 0) <= METAORDER_GAP_MS
        )
        if continuation:
            previous["last_fill_ts_ms"] = fill_ts_ms
            meta_state[key] = previous
            self.state["metaorder_state"] = meta_state
            self.state["counters"]["continuations"] += 1
            return

        identifier = metaorder_id(vault, coin, direction, fill_ts_ms)
        meta_state[key] = {
            "direction": direction,
            "last_fill_ts_ms": fill_ts_ms,
            "metaorder_id": identifier,
        }
        self.state["metaorder_state"] = meta_state
        self.state["counters"]["metaorders_started"] += 1
        base = {"coin": coin, "metaorder_id": identifier, "attempts": 0}
        pending = list(self.state.get("pending") or [])
        pending.extend([
            {
                **base,
                "stage": "REFERENCE",
                "checkpoint_id": f"{identifier}:REFERENCE",
                "target_wall_ms": received_at_ms,
            },
            {
                **base,
                "stage": "ENTRY",
                "checkpoint_id": f"{identifier}:ENTRY",
                "target_wall_ms": received_at_ms + COPY_DELAY_MS,
            },
        ])
        self.state["pending"] = pending[-MAX_PENDING:]

    @staticmethod
    def _exit_checkpoints(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "coin": str(entry["coin"]),
                "metaorder_id": str(entry["metaorder_id"]),
                "stage": f"EXIT_{horizon_ms}",
                "checkpoint_id": f"{entry['metaorder_id']}:EXIT:{horizon_ms}",
                "target_wall_ms": int(entry["captured_wall_ms"]) + horizon_ms,
                "attempts": 0,
            }
            for horizon_ms in HORIZONS_MS
        ]

    def _capture_due(self, *, now_ms: int) -> tuple[int, int]:
        captured_ids = list(self.state.get("captured_checkpoint_ids") or [])
        captured_set = set(captured_ids)
        remaining: list[dict[str, Any]] = []
        additions: list[dict[str, Any]] = []
        captured_now = 0
        expired_now = 0
        for checkpoint in sorted(
            list(self.state.get("pending") or []),
            key=lambda row: (int(row.get("target_wall_ms") or 0), str(row.get("checkpoint_id") or "")),
        ):
            checkpoint_id = str(checkpoint.get("checkpoint_id") or "")
            target_ms = int(checkpoint.get("target_wall_ms") or 0)
            if not checkpoint_id or checkpoint_id in captured_set:
                continue
            if now_ms < target_ms:
                remaining.append(checkpoint)
                continue
            if now_ms - target_ms > MAX_TARGET_LAG_MS:
                expired_now += 1
                continue
            try:
                raw = self.fetch_book(str(checkpoint["coin"]))
            except Exception:  # noqa: BLE001 - collection must remain alive on network errors
                raw = None
            received_at_ms = self.clock_ms()
            parsed = _parse_book(raw, received_at_ms=received_at_ms) if isinstance(raw, Mapping) else None
            if parsed is None or not (0 <= received_at_ms - target_ms <= MAX_TARGET_LAG_MS):
                checkpoint["attempts"] = int(checkpoint.get("attempts") or 0) + 1
                self.state["counters"]["fetch_retries"] += 1
                remaining.append(checkpoint)
                continue
            row = {
                "schema_version": "hypersmart.copy_vault_l2.v1",
                "coin": str(checkpoint["coin"]).upper(),
                "received_at_ms": received_at_ms,
                **parsed,
                "source": "HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT",
                "data_origin": "REAL_OBSERVED",
                "causal_observation": True,
                "paper_read_only": True,
                "real_execution": False,
                "checkpoint_stage": str(checkpoint["stage"]),
                "checkpoint_target_ms": target_ms,
                "checkpoint_id": checkpoint_id,
                "metaorder_id": str(checkpoint["metaorder_id"]),
                "collector_protocol": COMPANION_PROTOCOL,
            }
            _append_jsonl(self.output_path, row)
            captured_ids.append(checkpoint_id)
            captured_set.add(checkpoint_id)
            captured_now += 1
            if checkpoint.get("stage") == "ENTRY":
                additions.extend(self._exit_checkpoints({
                    **checkpoint,
                    "captured_wall_ms": received_at_ms,
                }))
        self.state["pending"] = (remaining + additions)[-MAX_PENDING:]
        self.state["captured_checkpoint_ids"] = _trim(captured_ids, MAX_CHECKPOINT_IDS)
        self.state["counters"]["checkpoints_captured"] += captured_now
        self.state["counters"]["checkpoints_expired"] += expired_now
        return captured_now, expired_now

    def poll_once(self) -> dict[str, Any]:
        now_ms = self.clock_ms()
        rows = self._read_appended_lines()
        for row in rows:
            self._schedule_fill(row, now_ms=now_ms)
        captured, expired = self._capture_due(now_ms=self.clock_ms())
        self.state["updated_at_ms"] = self.clock_ms()
        _atomic_write(self.state_path, self.state)
        return {
            "protocol": COMPANION_PROTOCOL,
            "lines": len(rows),
            "captured": captured,
            "expired": expired,
            "pending": len(self.state.get("pending") or []),
            "counters": dict(self.state.get("counters") or {}),
            "paper_read_only": True,
            "real_execution": False,
        }


__all__ = [
    "COMPANION_PROTOCOL",
    "CopyVaultCheckpointTail",
    "HORIZONS_MS",
    "INFO_URL",
    "INPUT_RELPATH",
    "MAX_TARGET_LAG_MS",
    "OUTPUT_RELPATH",
    "SCHEMA_VERSION",
    "STATE_RELPATH",
    "fetch_hyperliquid_l2_book",
]
