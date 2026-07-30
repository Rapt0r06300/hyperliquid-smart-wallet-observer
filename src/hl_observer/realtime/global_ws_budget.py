"""Host-wide Hyperliquid WebSocket resource budget.

Limits are enforced across processes through a small locked state file.  A
per-object counter is insufficient when the launcher starts several collectors.
The budget is read-only transport governance; it does not contain venue actions.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from hl_observer.hyperliquid.rate_weights import (
    HYPERSMART_WS_MAX_CONNECTIONS as WS_MAX_CONNECTIONS,
)
from hl_observer.hyperliquid.rate_weights import (
    HYPERSMART_WS_MAX_MESSAGES_PER_MIN as WS_MAX_MESSAGES_PER_MINUTE,
)
from hl_observer.hyperliquid.rate_weights import (
    HYPERSMART_WS_MAX_NEW_CONNECTIONS_PER_MIN as WS_MAX_NEW_CONNECTIONS_PER_MINUTE,
)
from hl_observer.hyperliquid.rate_weights import (
    HYPERSMART_WS_MAX_SUBSCRIPTIONS as WS_MAX_SUBSCRIPTIONS,
)
from hl_observer.hyperliquid.rate_weights import (
    HYPERSMART_WS_MAX_UNIQUE_USERS as WS_MAX_UNIQUE_USERS,
)


class GlobalWsBudgetError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GlobalWsBudgetDecision:
    allowed: bool
    reasons: tuple[str, ...]
    active_connections: int
    unique_users: int
    subscriptions: int
    messages_last_minute: int
    new_connections_last_minute: int


def _empty_state() -> dict[str, Any]:
    return {
        "version": 1,
        "leases": {},
        "connection_attempts_ms": [],
        "message_batches": [],
    }


class GlobalWsBudget:
    def __init__(
        self,
        state_path: str | Path,
        *,
        lease_ttl_ms: int = 90_000,
    ) -> None:
        self.state_path = Path(state_path)
        self.lock_path = self.state_path.with_suffix(self.state_path.suffix + ".lock")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.lease_ttl_ms = max(1_000, int(lease_ttl_ms))

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                deadline = time.monotonic() + 10.0
                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise GlobalWsBudgetError("timed out acquiring WS budget lock")
                        time.sleep(0.01)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return _empty_state()
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GlobalWsBudgetError(
                f"invalid global WS budget state: {self.state_path}"
            ) from exc
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise GlobalWsBudgetError("unsupported global WS budget state")
        return payload

    def _save(self, state: dict[str, Any]) -> None:
        temporary = self.state_path.with_name(
            f".{self.state_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    state,
                    handle,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.state_path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _clean(state: dict[str, Any], *, now_ms: int) -> None:
        leases = state.setdefault("leases", {})
        for lease_id in list(leases):
            if int(leases[lease_id].get("expires_at_ms", 0)) <= now_ms:
                leases.pop(lease_id, None)
        cutoff = now_ms - 60_000
        state["connection_attempts_ms"] = [
            int(value)
            for value in state.get("connection_attempts_ms", [])
            if int(value) > cutoff
        ]
        state["message_batches"] = [
            {"at_ms": int(row["at_ms"]), "count": int(row["count"])}
            for row in state.get("message_batches", [])
            if int(row.get("at_ms", 0)) > cutoff
        ]

    @staticmethod
    def _snapshot(state: dict[str, Any], reasons: list[str]) -> GlobalWsBudgetDecision:
        leases = state.get("leases", {})
        users = {
            str(user).lower()
            for lease in leases.values()
            for user in lease.get("users", [])
        }
        subscriptions = sum(
            int(lease.get("subscriptions", 0))
            for lease in leases.values()
        )
        messages = sum(
            int(row.get("count", 0))
            for row in state.get("message_batches", [])
        )
        return GlobalWsBudgetDecision(
            allowed=not reasons,
            reasons=tuple(reasons),
            active_connections=len(leases),
            unique_users=len(users),
            subscriptions=subscriptions,
            messages_last_minute=messages,
            new_connections_last_minute=len(state.get("connection_attempts_ms", [])),
        )

    def reserve_connection(
        self,
        *,
        connection_id: str,
        users: list[str] | tuple[str, ...] = (),
        subscriptions: int = 0,
        now_ms: int | None = None,
    ) -> GlobalWsBudgetDecision:
        timestamp = int(time.time() * 1000 if now_ms is None else now_ms)
        clean_users = sorted(
            {str(user).strip().lower() for user in users if str(user).strip()}
        )
        requested_subscriptions = max(0, int(subscriptions))
        with self._locked():
            state = self._load()
            self._clean(state, now_ms=timestamp)
            leases = state["leases"]
            existing = leases.pop(str(connection_id), None)
            active_users = {
                str(user).lower()
                for lease in leases.values()
                for user in lease.get("users", [])
            }
            active_subscriptions = sum(
                int(lease.get("subscriptions", 0))
                for lease in leases.values()
            )
            reasons: list[str] = []
            if len(leases) + 1 > WS_MAX_CONNECTIONS:
                reasons.append("WS_CONNECTION_CAP_EXCEEDED")
            if len(active_users | set(clean_users)) > WS_MAX_UNIQUE_USERS:
                reasons.append("WS_UNIQUE_USER_CAP_EXCEEDED")
            if active_subscriptions + requested_subscriptions > WS_MAX_SUBSCRIPTIONS:
                reasons.append("WS_SUBSCRIPTION_CAP_EXCEEDED")
            if (
                existing is None
                and len(state["connection_attempts_ms"]) + 1
                > WS_MAX_NEW_CONNECTIONS_PER_MINUTE
            ):
                reasons.append("WS_NEW_CONNECTIONS_PER_MINUTE_CAP_EXCEEDED")
            if reasons:
                if existing is not None:
                    leases[str(connection_id)] = existing
                self._save(state)
                return self._snapshot(state, reasons)
            leases[str(connection_id)] = {
                "users": clean_users,
                "subscriptions": requested_subscriptions,
                "expires_at_ms": timestamp + self.lease_ttl_ms,
            }
            if existing is None:
                state["connection_attempts_ms"].append(timestamp)
            self._save(state)
            return self._snapshot(state, [])

    def heartbeat(self, connection_id: str, *, now_ms: int | None = None) -> bool:
        timestamp = int(time.time() * 1000 if now_ms is None else now_ms)
        with self._locked():
            state = self._load()
            self._clean(state, now_ms=timestamp)
            lease = state["leases"].get(str(connection_id))
            if lease is None:
                self._save(state)
                return False
            lease["expires_at_ms"] = timestamp + self.lease_ttl_ms
            self._save(state)
            return True

    def reserve_messages(
        self,
        count: int,
        *,
        now_ms: int | None = None,
    ) -> GlobalWsBudgetDecision:
        timestamp = int(time.time() * 1000 if now_ms is None else now_ms)
        requested = max(0, int(count))
        with self._locked():
            state = self._load()
            self._clean(state, now_ms=timestamp)
            current = sum(int(row["count"]) for row in state["message_batches"])
            reasons: list[str] = []
            if current + requested > WS_MAX_MESSAGES_PER_MINUTE:
                reasons.append("WS_MESSAGES_PER_MINUTE_CAP_EXCEEDED")
            if not reasons and requested:
                state["message_batches"].append(
                    {"at_ms": timestamp, "count": requested}
                )
            self._save(state)
            return self._snapshot(state, reasons)

    def release(self, connection_id: str, *, now_ms: int | None = None) -> None:
        timestamp = int(time.time() * 1000 if now_ms is None else now_ms)
        with self._locked():
            state = self._load()
            self._clean(state, now_ms=timestamp)
            state["leases"].pop(str(connection_id), None)
            self._save(state)

    def status(self, *, now_ms: int | None = None) -> GlobalWsBudgetDecision:
        timestamp = int(time.time() * 1000 if now_ms is None else now_ms)
        with self._locked():
            state = self._load()
            self._clean(state, now_ms=timestamp)
            self._save(state)
            return self._snapshot(state, [])


__all__ = [
    "GlobalWsBudget",
    "GlobalWsBudgetDecision",
    "GlobalWsBudgetError",
    "WS_MAX_CONNECTIONS",
    "WS_MAX_MESSAGES_PER_MINUTE",
    "WS_MAX_NEW_CONNECTIONS_PER_MINUTE",
    "WS_MAX_SUBSCRIPTIONS",
    "WS_MAX_UNIQUE_USERS",
]
