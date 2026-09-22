"""Read-only Hyperliquid WebSocket clock-synchronisation evidence.

Hyperliquid market messages expose exchange timestamps, but the market feeds do not
carry an explicit server-clock offset. The documented webData3 stream includes
userState.serverTime. This helper samples that value on the same public WebSocket
connection used by the bounded cloud collector, using a zero-address read-only
subscription solely as clock evidence.

Missing, stale or high-RTT evidence stays missing. No account mutation, signature,
credential or exchange endpoint is involved.
"""
from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from hl_observer.collection.feed_integrity import ClockSyncSample, estimate_clock_sync

CLOCK_PROBE_USER = "0x0000000000000000000000000000000000000000"
DEFAULT_MAX_PROBE_RTT_MS = 100.0
DEFAULT_MAX_SAMPLE_AGE_MS = 600_000


class HyperliquidClockSyncProbe:
    """Track one bounded Hyperliquid webData3.serverTime clock sample."""

    def __init__(
        self,
        *,
        user: str = CLOCK_PROBE_USER,
        max_probe_rtt_ms: float = DEFAULT_MAX_PROBE_RTT_MS,
        max_sample_age_ms: int = DEFAULT_MAX_SAMPLE_AGE_MS,
    ) -> None:
        normalized = str(user or "").strip()
        if (
            len(normalized) != 42
            or not normalized.startswith("0x")
            or any(char not in "0123456789abcdefABCDEF" for char in normalized[2:])
        ):
            raise ValueError("Hyperliquid clock probe user must be a full 0x address")
        self.user = normalized
        self.max_probe_rtt_ms = max(0.0, float(max_probe_rtt_ms))
        self.max_sample_age_ms = max(1, int(max_sample_age_ms))
        self.last_sample: ClockSyncSample | None = None
        self._pending_send_wall_ts_ms: int | None = None
        self.attempts = 0
        self.accepted_samples = 0
        self.failures = 0
        self.last_error = ""

    def subscription_message(self) -> dict[str, Any]:
        return {
            "method": "subscribe",
            "subscription": {
                "type": "webData3",
                "user": self.user,
            },
        }

    def mark_subscribe_sent(self, sent_wall_ts_ms: int | None = None) -> int:
        sent = (
            int(time.time() * 1_000)
            if sent_wall_ts_ms is None
            else int(sent_wall_ts_ms)
        )
        self._pending_send_wall_ts_ms = sent
        self.attempts += 1
        return sent

    def observe(
        self,
        message: Mapping[str, Any],
        *,
        received_wall_ts_ms: int | None = None,
    ) -> ClockSyncSample | None:
        """Accept only the first documented serverTime after a marked subscribe."""
        server_ts = _server_time_from_message(message)
        if server_ts is None:
            return None
        sent = self._pending_send_wall_ts_ms
        if sent is None:
            return None
        received = (
            int(time.time() * 1_000)
            if received_wall_ts_ms is None
            else int(received_wall_ts_ms)
        )
        self._pending_send_wall_ts_ms = None
        try:
            sample = estimate_clock_sync(
                venue="hyperliquid",
                server_ts_ms=server_ts,
                send_wall_ts_ms=sent,
                receive_wall_ts_ms=received,
            )
        except (TypeError, ValueError, OverflowError) as exc:
            self.failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"[:500]
            return None
        if sample.rtt_ms > self.max_probe_rtt_ms:
            self.failures += 1
            self.last_error = "CLOCK_PROBE_RTT_TOO_HIGH"
            return None
        self.last_sample = sample
        self.accepted_samples += 1
        self.last_error = ""
        return sample

    def evidence(self, *, now_ms: int | None = None) -> dict[str, float | int]:
        sample = self.last_sample
        if sample is None:
            return {}
        now = int(time.time() * 1_000) if now_ms is None else int(now_ms)
        age = now - int(sample.receive_wall_ts_ms)
        if age < 0 or age > self.max_sample_age_ms:
            return {}
        return {
            "clock_offset_ms": float(sample.offset_ms),
            "clock_probe_rtt_ms": float(sample.rtt_ms),
            "clock_probe_server_ts_ms": int(sample.server_ts_ms),
            "clock_probe_receive_wall_ts_ms": int(sample.receive_wall_ts_ms),
        }

    def health(self, *, now_ms: int | None = None) -> dict[str, Any]:
        evidence = self.evidence(now_ms=now_ms)
        return {
            "status": "OK" if evidence else "UNAVAILABLE",
            "attempts": int(self.attempts),
            "accepted_samples": int(self.accepted_samples),
            "failures": int(self.failures),
            "last_error": self.last_error,
            "clock_source": "webData3.userState.serverTime",
            **evidence,
        }


def _server_time_from_message(message: Mapping[str, Any]) -> int | None:
    if str(message.get("channel") or "") != "webData3":
        return None
    data = message.get("data")
    if not isinstance(data, Mapping):
        return None
    user_state = data.get("userState")
    if not isinstance(user_state, Mapping):
        return None
    value = user_state.get("serverTime")
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = [
    "CLOCK_PROBE_USER",
    "DEFAULT_MAX_PROBE_RTT_MS",
    "DEFAULT_MAX_SAMPLE_AGE_MS",
    "HyperliquidClockSyncProbe",
]
