"""
Routes FastAPI dYdX v4 — READ-ONLY, PAPER-ONLY.

Aucun endpoint de trading, aucune clé privée, aucun ordre réel.
Toutes les données viennent du DydxEngine (paper simulation + public Indexer).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Response

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "dYdX v4 PAPER SIMULATION — READ-ONLY public Indexer API. "
    "No real orders. No real money. No private keys."
)


def create_dydx_router() -> APIRouter:
    router = APIRouter(prefix="/api/dydx", tags=["dydx-v4"])

    # Import ici pour éviter les imports circulaires au démarrage
    from hyper_smart_observer.dydx_v4.engine import get_engine

    @router.get("/status")
    async def dydx_status() -> dict[str, Any]:
        """Statut du moteur dYdX v4 (paper-only)."""
        try:
            return get_engine().get_status()
        except Exception as e:
            logger.error("dydx /status error: %s", e)
            return {
                "running": False,
                "error": str(e),
                "disclaimer": DISCLAIMER,
            }

    @router.get("/wallets")
    async def dydx_wallets() -> list[dict]:
        """Shortlist des wallets dYdX v4 suivis (Cosmos LCD + Indexer score)."""
        try:
            return get_engine().get_wallets()
        except Exception as e:
            logger.error("dydx /wallets error: %s", e)
            return []

    @router.get("/positions")
    async def dydx_positions() -> list[dict]:
        """Positions paper ouvertes (stop-loss -1.5%, take-profit +2.5%)."""
        try:
            return get_engine().get_open_positions()
        except Exception as e:
            logger.error("dydx /positions error: %s", e)
            return []

    @router.get("/trades")
    async def dydx_trades(limit: int = 50) -> list[dict]:
        """Historique des trades paper fermés (stop-loss ou take-profit)."""
        try:
            return get_engine().get_closed_trades(limit=min(limit, 200))
        except Exception as e:
            logger.error("dydx /trades error: %s", e)
            return []

    @router.get("/refused")
    async def dydx_refused(limit: int = 100) -> list[dict]:
        """Derniers refus NO_TRADE dYdX v4 (diagnostic read-only)."""
        try:
            return get_engine().get_refused_decisions(limit=min(limit, 500))
        except Exception as e:
            logger.error("dydx /refused error: %s", e)
            return []

    @router.get("/prices")
    async def dydx_prices() -> dict[str, float]:
        """Prix oracle dYdX v4 (ETH-USD, BTC-USD, SOL-USD…)."""
        try:
            return get_engine().get_mark_prices()
        except Exception as e:
            logger.error("dydx /prices error: %s", e)
            return {}

    @router.get("/pnl")
    async def dydx_pnl() -> dict[str, Any]:
        """Résumé PnL paper session courante."""
        try:
            s = get_engine().get_status()
            return {
                "session_id": s.get("session_id", ""),
                "net_pnl_usdt": s.get("net_pnl_usdt", 0.0),
                "equity_usdt": s.get("equity_usdt", 1000.0),
                "total_trades": s.get("total_trades", 0),
                "winrate": s.get("winrate", "0%"),
                "fees_paid": s.get("fees_paid", 0.0),
                "open_positions": s.get("open_positions", 0),
                "disclaimer": DISCLAIMER,
            }
        except Exception as e:
            logger.error("dydx /pnl error: %s", e)
            return {"error": str(e), "disclaimer": DISCLAIMER}

    @router.get("/simulation-truth")
    async def dydx_simulation_truth() -> dict[str, Any]:
        """Rapport vérité simulation paper: sources, PnL, V2, refus."""
        try:
            from hyper_smart_observer.dydx_v4.simulation_truth import truth_report
            report = truth_report()
            report["disclaimer"] = DISCLAIMER
            return report
        except Exception as e:
            logger.error("dydx /simulation-truth error: %s", e)
            return {"error": str(e), "read_only": True, "paper_only": True, "disclaimer": DISCLAIMER}

    @router.get("/realtime-tick")
    async def dydx_realtime_tick(response: Response) -> dict[str, Any]:
        """Tick leger pour animer la simulation paper en mark-to-market."""
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Hypersmart-Mode"] = "paper-read-only"
        try:
            return get_engine().get_realtime_tick()
        except Exception as e:
            logger.error("dydx /realtime-tick error: %s", e)
            return {
                "timestamp_ms": 0,
                "running": False,
                "paper_only": True,
                "read_only": True,
                "net_pnl_usdt": 0.0,
                "equity_usdt": 1000.0,
                "positions": [],
                "error": str(e),
                "disclaimer": DISCLAIMER,
            }

    @router.get("/health")
    async def dydx_health() -> dict[str, Any]:
        """Health check + état de la découverte de wallets."""
        try:
            s = get_engine().get_status()
            discovery_state = (
                "running" if s.get("last_error") == "DISCOVERY_RUNNING"
                else "idle"
            )
            return {
                "running": s.get("running", False),
                "rest_healthy": s.get("rest_healthy", False),
                "discovery": discovery_state,
                "wallets": s.get("wallets_in_shortlist", 0),
                "iteration": s.get("iteration", 0),
                "last_error": s.get("last_error", ""),
                "disclaimer": DISCLAIMER,
            }
        except Exception as e:
            return {"running": False, "error": str(e), "disclaimer": DISCLAIMER}

    @router.get("/whales")
    async def dydx_whales(limit: int = 20) -> dict[str, Any]:
        """Top performers dYdX (whale watchlist) — READ-ONLY, PAPER-ONLY."""
        try:
            eng = get_engine()
            stats = eng.get_whale_stats()
            top = eng.get_whale_top(n=min(limit, 100))
            return {
                "enabled": stats.get("enabled", False),
                "tracked": stats.get("total_tracked", 0),
                "hot_set_size": stats.get("hot_set_size", 0),
                "candidates_known": stats.get("candidates_known", 0),
                "last_refresh_ms": stats.get("last_refresh_ms", 0),
                "refresh_count": stats.get("refresh_count", 0),
                "avg_win_rate": round(float(stats.get("avg_win_rate") or 0), 3),
                "avg_pnl_usdc": round(float(stats.get("avg_pnl_usdc") or 0), 2),
                "top": top[:limit],
                "disclaimer": DISCLAIMER,
            }
        except Exception as e:
            return {"enabled": False, "error": str(e), "disclaimer": DISCLAIMER}

    return router


    return router
