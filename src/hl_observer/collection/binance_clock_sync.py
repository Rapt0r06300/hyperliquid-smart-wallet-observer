"""Shared public Binance USD-M clock synchronisation probe."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from hl_observer.collection.feed_integrity import ClockSyncSample, estimate_clock_sync

REST_BASE_URL = "https://fapi.binance.com"


class BinanceClockSyncProbe:
    def __init__(
        self,
        *,
        rest_base_url: str = REST_BASE_URL,
        interval_s: float = 60.0,
        http_client: httpx.AsyncClient | None = None,
        wall_time: Callable[[], float] | None = None,
    ) -> None:
        self.rest_base_url = rest_base_url.rstrip("/")
        self.interval_s = max(10.0, float(interval_s))
        self._owns_http = http_client is None
        self.http = http_client or httpx.AsyncClient(
            base_url=self.rest_base_url,
            timeout=10.0,
        )
        self._wall_time = wall_time or time.time
        self.last_sample: ClockSyncSample | None = None
        self.failures = 0
        self.last_error = ""

    async def sample_once(self) -> ClockSyncSample | None:
        sent = int(self._wall_time() * 1_000)
        try:
            response = await self.http.get("/fapi/v1/time")
            response.raise_for_status()
            payload = response.json()
            server = int(payload["serverTime"])
        except Exception as exc:
            self.failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"[:500]
            return None
        received = int(self._wall_time() * 1_000)
        sample = estimate_clock_sync(
            venue="binance",
            server_ts_ms=server,
            send_wall_ts_ms=sent,
            receive_wall_ts_ms=received,
        )
        self.last_sample = sample
        self.last_error = ""
        return sample

    async def run(self) -> None:
        await self.sample_once()
        while True:
            await asyncio.sleep(self.interval_s)
            await self.sample_once()

    def evidence(self) -> dict[str, float | int]:
        sample = self.last_sample
        if sample is None:
            return {}
        return {
            "clock_offset_ms": float(sample.offset_ms),
            "clock_probe_rtt_ms": float(sample.rtt_ms),
            "clock_probe_server_ts_ms": int(sample.server_ts_ms),
            "clock_probe_receive_wall_ts_ms": int(sample.receive_wall_ts_ms),
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "OK" if self.last_sample is not None else "UNAVAILABLE",
            "failures": self.failures,
            "last_error": self.last_error,
            **self.evidence(),
        }

    async def close(self) -> None:
        if self._owns_http:
            await self.http.aclose()


__all__ = ["BinanceClockSyncProbe", "REST_BASE_URL"]
