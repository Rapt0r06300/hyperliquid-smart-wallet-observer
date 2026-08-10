"""Single writer for local paper economics.

The dashboard is an observer.  SL/TP, legacy quality exits, fusion paper intents and
canonical equity persistence are applied here on a clock owned by the UI server,
never as a side effect of an HTTP GET.  The writer is paper/read-only with respect
to external venues: it consumes only local BBO/DB evidence and never calls /exchange.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any

from sqlalchemy import desc, select

from hl_observer.config.settings import Settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine
from hl_observer.storage.models import MarketSnapshot
from hl_observer.ui.fusion_persistent_adapter import apply_fusion_paper_orders_to_state
from hl_observer.ui.fusion_status_provider import build_fusion_status_payload
from hl_observer.ui.persistent_state import persist_simulation_state
from hl_observer.ui.state import UiState
from hl_observer.utils.time import now_ms
from hl_observer.ops.echec_silencieux import noter as _noter_echec
import hl_observer.ui.status_routes as status_helpers


def latest_local_market_marks(
    settings: Settings | None,
    raw_positions: list[dict[str, Any]],
    *,
    current_ms: int,
) -> dict[str, Any]:
    """Resolve executable marks without any network I/O.

    Priority is the local Hyperliquid BBO tape, then persisted market snapshots.
    A dashboard refresh can therefore never change API traffic or execution timing.
    """
    if not raw_positions:
        return status_helpers._empty_market_marks("NO_OPEN_POSITION")
    bbo = status_helpers._local_bbo_marks(
        settings,
        raw_positions=raw_positions,
        current_ms=current_ms,
    )
    requested = {
        status_helpers._infer_status_coin(row, index=index)
        for index, row in enumerate(raw_positions)
        if isinstance(row, dict)
    }
    requested.discard("")
    available = {
        str(key).split("|", 1)[0]
        for key in (bbo.get("prices") or {})
    }
    if requested and requested.issubset(available):
        return bbo
    if settings is None:
        return bbo
    try:
        factory = create_session_factory(create_sqlite_engine(settings.database_url))
        with factory() as session:
            snapshots = list(
                session.scalars(
                    select(MarketSnapshot)
                    .order_by(desc(MarketSnapshot.exchange_ts), desc(MarketSnapshot.id))
                    .limit(status_helpers.MARK_SNAPSHOT_LIMIT)
                )
            )
    except Exception as exc:  # DB projection is best-effort; BBO remains authoritative.
        _noter_echec("hl_observer/ui/economic_writer.py:market_snapshot_read", exc)
        return bbo
    db_marks = status_helpers._latest_market_marks_from_snapshots(snapshots)
    return status_helpers._merge_market_marks(bbo, db_marks)


class EconomicWriter:
    """Own every mutation that used to happen inside `/api/simulation/status`."""

    def __init__(
        self,
        state: UiState,
        settings: Settings,
        *,
        lock: threading.RLock | None = None,
        interval_ms: int | None = None,
    ) -> None:
        self.state = state
        self.settings = settings
        self.lock = lock or threading.RLock()
        env_interval = int(float(os.getenv("HYPERSMART_ECONOMIC_WRITER_INTERVAL_MS", "1000")))
        self.interval_ms = max(250, int(interval_ms if interval_ms is not None else env_interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_tick_ms = 0
        self.last_error: str | None = None
        self.last_sltp_report: dict[str, Any] = {"writer_owned": True, "closed_count": 0, "reason": "NOT_TICKED"}
        self.last_quality_report: dict[str, Any] = {"writer_owned": True, "closed_count": 0, "reason": "NOT_TICKED"}
        self.last_fusion_report: dict[str, Any] = {"writer_owned": True, "applied_count": 0, "reason": "NOT_TICKED"}

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())

    def start(self) -> None:
        if self.running or str(os.getenv("HYPERSMART_DISABLE_ECONOMIC_WRITER", "")).lower() in {"1", "true", "yes", "on"}:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="hypersmart-paper-economic-writer",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout)))

    def _run(self) -> None:
        # Tick immediately: economic correctness must not depend on the first browser request.
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self.tick()
                self.last_error = None
            except Exception as exc:  # writer must survive one bad tick, but never hide it.
                self.last_error = f"{exc.__class__.__name__}: {exc}"
                _noter_echec("hl_observer/ui/economic_writer.py:tick", exc)
            elapsed = time.monotonic() - started
            wait_s = max(0.01, self.interval_ms / 1000.0 - elapsed)
            self._stop.wait(wait_s)

    def tick(self, *, current_ms: int | None = None) -> dict[str, Any]:
        ts = int(current_ms if current_ms is not None else now_ms())
        with self.lock:
            state = self.state
            raw_positions = list((getattr(state, "simulation_virtual_positions", {}) or {}).values())
            market_marks = latest_local_market_marks(
                self.settings,
                raw_positions,
                current_ms=ts,
            )
            sltp = status_helpers._apply_fast_status_sltp(state, market_marks, current_ms=ts)
            if int(sltp.get("closed_count") or 0):
                raw_positions = list((getattr(state, "simulation_virtual_positions", {}) or {}).values())
                market_marks = latest_local_market_marks(self.settings, raw_positions, current_ms=ts)
            quality = status_helpers._apply_fast_status_quality_exits(state, market_marks, current_ms=ts)
            if int(quality.get("closed_count") or 0):
                raw_positions = list((getattr(state, "simulation_virtual_positions", {}) or {}).values())
                market_marks = latest_local_market_marks(self.settings, raw_positions, current_ms=ts)

            engine_status = status_helpers._read_engine_status(self.settings)
            scanner = status_helpers._scanner_payload_from_engine_status(engine_status, ts)
            fusion_status = build_fusion_status_payload(
                state=state,
                engine_status=engine_status,
                scanner=scanner,
                settings=self.settings,
                current_ms=ts,
            )
            fusion = apply_fusion_paper_orders_to_state(state, fusion_status, current_ms=ts)
            if int(fusion.get("applied_count") or 0):
                raw_positions = list((getattr(state, "simulation_virtual_positions", {}) or {}).values())
                market_marks = latest_local_market_marks(self.settings, raw_positions, current_ms=ts)

            starting = float(getattr(state, "simulation_starting_equity_usdt", 1000.0) or 1000.0)
            realized = float(getattr(state, "simulation_realized_pnl_usdc", 0.0) or 0.0)
            marked = status_helpers._mark_to_market_positions(
                raw_positions,
                starting_equity_usdt=starting,
                realized_pnl_usdc=realized,
                market_marks=market_marks,
                current_ms=ts,
            )
            if int(marked.get("marks_used") or 0) > 0:
                status_helpers._append_fast_equity_point(self.settings, state, marked, ts)
            elif int(sltp.get("closed_count") or 0) or int(quality.get("closed_count") or 0) or int(fusion.get("applied_count") or 0):
                persist_simulation_state(self.settings, state)

            self.last_tick_ms = ts
            self.last_sltp_report = {**sltp, "writer_owned": True}
            self.last_quality_report = {**quality, "writer_owned": True}
            self.last_fusion_report = {**fusion, "writer_owned": True}
            return {
                "timestamp_ms": ts,
                "sltp": self.last_sltp_report,
                "quality": self.last_quality_report,
                "fusion": self.last_fusion_report,
                "open_positions": len(raw_positions),
                "read_only_external": True,
                "real_execution": False,
            }


__all__ = ["EconomicWriter", "latest_local_market_marks"]
