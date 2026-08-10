"""Pure `/api/simulation/status` projection.

This router is intentionally registered before the legacy compatibility router.
It performs no network request, no position mutation, no ledger mutation and no disk
write.  All paper-economic mutations are owned by :mod:`economic_writer`.
"""
from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter

from hl_observer.config.settings import Settings
from hl_observer.strategies.external_github_bridge import build_external_github_bridge_payload
from hl_observer.ui.economic_writer import EconomicWriter, latest_local_market_marks
from hl_observer.ui.fusion_status_provider import build_fusion_status_payload
from hl_observer.ui.state import UiState
from hl_observer.ui.v12_status_provider import build_v12_status_payload
from hl_observer.utils.time import now_ms
import hl_observer.ui.status_routes as status_helpers


def create_read_only_status_router(
    state: UiState,
    *,
    settings: Settings | None,
    economic_writer: EconomicWriter | None,
    lock: threading.RLock,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/simulation/status")
    def simulation_status_read_only() -> dict[str, Any]:
        current_ms = now_ms()
        with lock:
            starting = float(getattr(state, "simulation_starting_equity_usdt", 1000.0) or 1000.0)
            realized = float(getattr(state, "simulation_realized_pnl_usdc", 0.0) or 0.0)
            raw_positions = list((getattr(state, "simulation_virtual_positions", {}) or {}).values())
            engine_status = status_helpers._read_engine_status(settings)
            scanner = status_helpers._scanner_payload_from_engine_status(engine_status, current_ms)
            market_marks = (
                latest_local_market_marks(settings, raw_positions, current_ms=current_ms)
                if raw_positions
                else status_helpers._empty_market_marks("NO_OPEN_POSITION")
            )
            marked = status_helpers._mark_to_market_positions(
                raw_positions,
                starting_equity_usdt=starting,
                realized_pnl_usdc=realized,
                market_marks=market_marks,
                current_ms=current_ms,
            )
            if int(marked.get("marks_used") or 0) > 0:
                equity = float(marked["current_equity_usdt"])
                net_pnl = float(marked["estimated_net_pnl_usdc"])
            else:
                # Historical graph points are evidence of the past, not current accounting truth.
                equity = round(starting + realized, 6)
                net_pnl = round(realized, 6)
                marked["current_equity_usdt"] = equity
                marked["estimated_net_pnl_usdc"] = net_pnl
                marked["realized_pnl_usdc"] = round(realized, 6)

            fusion_status = build_fusion_status_payload(
                state=state,
                engine_status=engine_status,
                scanner=scanner,
                settings=settings,
                current_ms=current_ms,
            )
            paper_ledger = status_helpers._paper_ledger_projection_from_status_state(
                state=state,
                starting_equity_usdt=starting,
                marked=marked,
                current_ms=current_ms,
            )
            ledger_events = getattr(state, "simulation_ledger_events", None)
            if not isinstance(ledger_events, list):
                ledger_events = []
            position_integrity = status_helpers._position_integrity_payload(
                raw_positions=raw_positions,
                marked=marked,
                ledger_events=ledger_events,
                current_ms=current_ms,
            )
            closed_stats = paper_ledger.get("closed_trade_stats") if isinstance(paper_ledger, dict) else {}
            if not isinstance(closed_stats, dict):
                closed_stats = {}
            closed_trades = int(closed_stats.get("closed_trades") or 0)
            winning_trades = int(closed_stats.get("winning_trades") or 0)
            losing_trades = int(closed_stats.get("losing_trades") or 0)
            winrate_pct = float(closed_stats.get("winrate_pct") or 0.0)
            experimental_status = status_helpers._read_experimental_paper_status(settings)
            sltp_report = (
                dict(economic_writer.last_sltp_report)
                if economic_writer is not None
                else {"writer_owned": True, "closed_count": 0, "reason": "WRITER_UNAVAILABLE"}
            )
            quality_report = (
                dict(economic_writer.last_quality_report)
                if economic_writer is not None
                else {"writer_owned": True, "closed_count": 0, "reason": "WRITER_UNAVAILABLE"}
            )
            fusion_apply_report = (
                dict(economic_writer.last_fusion_report)
                if economic_writer is not None
                else {"writer_owned": True, "applied_count": 0, "reason": "WRITER_UNAVAILABLE"}
            )
            latest_graph_point = {
                "timestamp_ms": current_ms,
                "current_equity_usdt": round(equity, 6),
                "current_pnl_usdc": round(net_pnl, 6),
                "realized_pnl_usdc": round(realized, 6),
                "unrealized_pnl_usdc": round(float(marked.get("unrealized_pnl_usdc") or 0.0), 6),
                "source": "SIMULATION_STATUS_READ_ONLY_PROJECTION",
            }
            payload = {
                "running": True,
                "server_running": True,
                "engine_running": scanner["engine_running"],
                "economic_writer_running": bool(economic_writer and economic_writer.running),
                "economic_writer_last_tick_ms": int(economic_writer.last_tick_ms if economic_writer else 0),
                "economic_writer_error": economic_writer.last_error if economic_writer else None,
                "read_only": True,
                "status_projection_pure": True,
                "network_reads_from_status": False,
                "real_execution": False,
                "mode": "LOCAL_PAPER_SIMULATION_REAL_HYPERLIQUID_DATA",
                "current_time_ms": current_ms,
                "engine_status": engine_status,
                "scanner": scanner,
                "equity_usdt": equity,
                "net_pnl_usdt": net_pnl,
                "realized_pnl_usdt": round(realized, 6),
                "unrealized_pnl_usdt": round(float(marked.get("unrealized_pnl_usdc") or 0.0), 6),
                "open_exposure_usdt": round(float(marked.get("open_exposure_usdt") or 0.0), 6),
                "open_positions": len(marked["positions"]),
                "total_trades": closed_trades,
                "closed_trades": closed_trades,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "flat_trades": int(closed_stats.get("flat_trades") or 0),
                "winrate_pct": round(winrate_pct, 2),
                "winrate": f"{winrate_pct:.0f}%" if closed_trades else "0%",
                "positions": marked["positions"],
                "mark_to_market": marked["mark_to_market"],
                "mark_diagnostics": marked["mark_diagnostics"],
                "position_integrity": position_integrity,
                "paper_ledger": paper_ledger,
                "ledger_recent_events": [row for row in ledger_events if isinstance(row, dict)][-20:],
                "latest_graph_point": latest_graph_point,
                "lanes": {
                    "MAIN": {
                        "positions": marked["positions"],
                        "equity_usdt": equity,
                        "net_pnl_usdt": net_pnl,
                        "real_execution": False,
                    },
                    "EXPERIMENTAL": experimental_status,
                },
                "v12": build_v12_status_payload(engine_status=engine_status, scanner=scanner),
                "fusion_runtime": fusion_status,
                "fusion_persistent_adapter": fusion_apply_report,
                "sltp_runtime": sltp_report,
                "quality_guard_runtime": quality_report,
                "external_github_bridge": build_external_github_bridge_payload(),
                "equity": {
                    "current_equity_usdt": equity,
                    "current_pnl_usdc": net_pnl,
                    "realized_pnl_usdc": round(realized, 6),
                    "unrealized_pnl_usdc": round(float(marked.get("unrealized_pnl_usdc") or 0.0), 6),
                    "open_exposure_usdt": round(float(marked.get("open_exposure_usdt") or 0.0), 6),
                    "market_marks_available": int(marked.get("marks_used") or 0),
                    "market_marks_missing": int(marked.get("marks_missing") or 0),
                },
                "bot_simulation": {
                    "open_positions": marked["positions"],
                    "current_equity_usdt": equity,
                    "estimated_net_pnl_usdc": net_pnl,
                    "realized_net_pnl_usdc": round(realized, 6),
                    "unrealized_pnl_usdc": round(float(marked.get("unrealized_pnl_usdc") or 0.0), 6),
                    "open_exposure_usdt": round(float(marked.get("open_exposure_usdt") or 0.0), 6),
                    "total_trades": closed_trades,
                    "closed_trades": closed_trades,
                    "winning_trades": winning_trades,
                    "losing_trades": losing_trades,
                    "flat_trades": int(closed_stats.get("flat_trades") or 0),
                    "winrate_pct": round(winrate_pct, 2),
                    "closed_trade_stats": closed_stats,
                    "paper_ledger": paper_ledger,
                    "position_integrity": position_integrity,
                },
                "counts": {},
                "message": "Projection locale pure; mutations paper détenues par economic_writer.",
            }
            return payload

    return router


__all__ = ["create_read_only_status_router"]
