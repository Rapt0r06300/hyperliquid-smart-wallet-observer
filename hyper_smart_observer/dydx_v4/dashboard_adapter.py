"""
Adaptateur dashboard dYdX v4 — READ-ONLY.

Aucun bouton de trading. Aucune action dangereuse.
Expose uniquement des données en lecture.
"""

from __future__ import annotations

import time
from typing import Optional

from hyper_smart_observer.dydx_v4.models import SimulationMode


class DydxDashboardAdapter:
    """
    Adaptateur pour le dashboard.

    READ-ONLY. Pas de bouton buy/sell/trade/execute/deposit/withdraw.
    Expose: statut REST, WS, réseau, safety, marchés, accounts,
            shortlist, positions, signaux, no-trade, paper PnL.
    """

    DISCLAIMER = (
        "Dashboard READ-ONLY. dYdX v4 PAPER-ONLY simulation. "
        "No real orders. No real money. No private keys."
    )

    def __init__(
        self,
        config: Optional[Any] = None,  # noqa: F821
        storage: Optional[Any] = None,  # noqa: F821
        indexer: Optional[Any] = None,  # noqa: F821
        ws_client: Optional[Any] = None,  # noqa: F821
        paper_simulator: Optional[Any] = None,  # noqa: F821
        no_trade_engine: Optional[Any] = None,  # noqa: F821
    ) -> None:
        self._config = config
        self._storage = storage
        self._indexer = indexer
        self._ws = ws_client
        self._paper = paper_simulator
        self._no_trade = no_trade_engine

    def get_status(self) -> dict:
        """Statut global du système dYdX."""
        now_ms = int(time.time() * 1000)

        rest_status = "UNKNOWN"
        ws_status = "UNKNOWN"
        indexer_stats = {}

        if self._indexer:
            health = self._indexer.health_check()
            rest_status = health.get("status", "UNKNOWN")
            indexer_stats = {
                "fills_ingested": self._indexer.stats.fills_ingested,
                "fills_deduplicated": self._indexer.stats.fills_deduplicated,
                "markets_updated": self._indexer.stats.markets_updated,
                "errors": self._indexer.stats.errors,
                "gap_recoveries": self._indexer.stats.gap_recoveries,
                "last_backfill_ms": self._indexer.stats.last_backfill_ms,
            }

        if self._ws:
            ws_status = self._ws.status.value if hasattr(self._ws, "status") else "UNKNOWN"

        config_info = {}
        if self._config:
            config_info = {
                "network": self._config.network.value,
                "paper_only": True,
                "read_only": True,
                "allow_trading": False,
                "allow_private_key": False,
                "max_signal_age_ms": self._config.max_signal_age_ms,
                "min_edge_bps": self._config.min_edge_bps,
                "market_whitelist": sorted(self._config.market_whitelist),
            }

        return {
            "disclaimer": self.DISCLAIMER,
            "timestamp_ms": now_ms,
            "exchange": "dydx_v4",
            "safety_mode": "READ_ONLY|PAPER_ONLY|TESTNET_FIRST|DENY_BY_DEFAULT",
            "rest_status": rest_status,
            "ws_status": ws_status,
            "config": config_info,
            "indexer": indexer_stats,
            "paper_only": True,
            "no_real_orders": True,
            "no_real_money": True,
            "no_private_keys": True,
        }

    def get_paper_summary(self, mode: SimulationMode = SimulationMode.LIVE) -> dict:
        """Résumé paper trading READ-ONLY."""
        if self._paper:
            return self._paper.get_session_stats(mode)
        return {
            "disclaimer": self.DISCLAIMER,
            "mode": mode.value,
            "status": "NOT_INITIALIZED",
            "paper_only": True,
        }

    def get_no_trade_summary(self) -> dict:
        """Résumé des refus NO_TRADE."""
        if self._no_trade:
            report = self._no_trade.report()
            return {
                "total_refused": report.total_refused,
                "by_reason": report.by_reason,
                "top_reason": report.top_reason,
            }
        return {"status": "NOT_INITIALIZED"}

    def get_storage_stats(self) -> dict:
        """Statistiques de la base de données SQLite."""
        if self._storage:
            return self._storage.get_stats()
        return {"status": "NOT_INITIALIZED"}

    def render_text_report(self) -> str:
        """Rapport texte lisible pour CLI."""
        lines = [
            "=" * 60,
            "dYdX v4 Dashboard — READ-ONLY PAPER SIMULATION",
            "=" * 60,
            self.DISCLAIMER,
            "",
        ]

        status = self.get_status()
        lines.append(f"Network:    {status.get('config', {}).get('network', 'unknown')}")
        lines.append(f"REST:       {status.get('rest_status', 'UNKNOWN')}")
        lines.append(f"WebSocket:  {status.get('ws_status', 'UNKNOWN')}")
        lines.append(f"Safety:     {status.get('safety_mode', '')}")
        lines.append("")

        paper = self.get_paper_summary()
        if paper.get("status") != "NOT_INITIALIZED":
            lines.append("--- Paper PnL (LIVE) ---")
            lines.append(f"Equity:     {paper.get('equity_usdc', 0):.4f} USDC")
            lines.append(f"Net PnL:    {paper.get('net_pnl_usdc', 0):.4f} USDC")
            lines.append(f"Gross PnL:  {paper.get('gross_pnl_usdc', 0):.4f} USDC")
            lines.append(f"Fees:       {paper.get('total_fees_usdc', 0):.4f} USDC")
            lines.append(f"Trades:     {paper.get('total_trades', 0)}")
            lines.append(f"Open pos:   {paper.get('open_positions', 0)}")
            wr = paper.get("winrate")
            lines.append(f"Winrate:    {f'{wr:.1%}' if wr is not None else 'N/A'}")
            lines.append("")

        no_trade = self.get_no_trade_summary()
        lines.append("--- No-Trade Decisions ---")
        lines.append(f"Total refused: {no_trade.get('total_refused', 0)}")
        by_reason = no_trade.get("by_reason", {})
        for reason, count in sorted(by_reason.items(), key=lambda x: -x[1])[:5]:
            lines.append(f"  {reason}: {count}")
        lines.append("")

        stats = self.get_storage_stats()
        lines.append("--- Database ---")
        for table, count in stats.items():
            lines.append(f"  {table}: {count}")
        lines.append("=" * 60)

        return "\n".join(lines)


# Type alias
Any = object
