from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets
from sqlalchemy.orm import Session

from hl_observer.config.settings import Settings
from hl_observer.hyperliquid.rest_info_client import HyperliquidInfoClient
from hl_observer.storage.repositories import CollectionRepository
from hl_observer.utils.time import now_ms
from hl_observer.wallets.snapshot_service import record_robust_snapshot
from hl_observer.wallets.user_fills_live import user_fills_from_message, store_user_fills_live_result, UserFillsLiveResult

logger = logging.getLogger(__name__)

class HyperliquidIndexerService:
    """Persistent indexer service for Hyperliquid.

    Handles WebSocket userFills and REST gap recovery.
    Deduplicates and persists data in SQLite.
    """

    def __init__(self, settings: Settings, session_factory: Any):
        self.settings = settings
        self.session_factory = session_factory
        self.info_client = HyperliquidInfoClient(settings.hyperliquid.info_base_url)
        self.active_wallets: set[str] = set()
        self._running = False
        self._ws_task: asyncio.Task | None = None

    async def start(self, wallets: list[str]):
        self.active_wallets = {w.lower() for w in wallets[:10]} # Limit 10 users as per HL rules
        self._running = True
        self._ws_task = asyncio.create_task(self._ws_loop())
        logger.info(f"Indexer started for {len(self.active_wallets)} wallets.")

    async def stop(self):
        self._running = False
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        logger.info("Indexer stopped.")

    async def _ws_loop(self):
        while self._running:
            try:
                async with websockets.connect(self.settings.hyperliquid.ws_base_url) as ws:
                    for wallet in self.active_wallets:
                        await ws.send(json.dumps({
                            "method": "subscribe",
                            "subscription": {"type": "userFills", "user": wallet}
                        }))

                    async for message in ws:
                        if not self._running:
                            break
                        await self._handle_ws_message(message)
            except Exception as e:
                logger.error(f"WebSocket error in indexer: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    async def _handle_ws_message(self, message: str | bytes):
        wallet, is_snapshot, fills = user_fills_from_message(message)
        if not wallet or wallet not in self.active_wallets or not fills:
            return

        logger.debug(f"Received {len(fills)} fills for {wallet} via WS.")
        received_at_ms = now_ms()
        enriched_fills = []
        for fill in fills:
            enriched = dict(fill)
            enriched["_hypersmart_source"] = "hyperliquid_ws:userFills"
            enriched["_hypersmart_ws_received_at_ms"] = received_at_ms
            enriched_fills.append(enriched)

        result = UserFillsLiveResult(
            wallets=[wallet],
            duration_seconds=0,
            network_read=True,
            wallet_fills={wallet: enriched_fills}
        )

        with self.session_factory() as session:
            store_user_fills_live_result(session, result)
            record_robust_snapshot(session, wallet, source="indexer_ws")
            session.commit()

    async def recover_gaps(self, wallet: str, start_time_ms: int, end_time_ms: int):
        """Recover fills via REST for a specific time range."""
        logger.info(f"Recovering gaps for {wallet} from {start_time_ms} to {end_time_ms}")
        try:
            fills = await self.info_client.user_fills_by_time(wallet, start_time_ms, end_time_ms)
            if not fills:
                return

            logger.info(f"Recovered {len(fills)} fills via REST.")
            with self.session_factory() as session:
                repo = CollectionRepository(session)
                repo.store_fills(wallet, fills)
                record_robust_snapshot(session, wallet, source="indexer_rest_recovery")
                session.commit()
        except Exception as e:
            logger.error(f"Failed to recover gaps for {wallet}: {e}")
