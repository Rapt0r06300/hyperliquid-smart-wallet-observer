"""
Indexer dYdX v4 — relançable, gap recovery, déduplication.

Modes: LIVE, BACKTEST, REPLAY, TEST_FIXTURE.
Pas de mélange des données entre modes.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from hyper_smart_observer.dydx_v4.config import DydxV4Config
from hyper_smart_observer.dydx_v4.normalizer import (
    normalize_fill,
    normalize_market,
    normalize_position,
    normalize_subaccount,
    normalize_trade,
)
from hyper_smart_observer.dydx_v4.rest_client import DydxIndexerRestClient, RestError
from hyper_smart_observer.dydx_v4.storage import DydxStorage

logger = logging.getLogger(__name__)


@dataclass
class IndexerStats:
    """Statistiques de l'indexer."""
    fills_ingested: int = 0
    fills_deduplicated: int = 0
    markets_updated: int = 0
    positions_updated: int = 0
    subaccounts_updated: int = 0
    errors: int = 0
    last_backfill_ms: int = 0
    last_ws_message_ms: int = 0
    gap_recoveries: int = 0


class DydxIndexer:
    """
    Indexer dYdX v4 relançable.

    REST: snapshots/backfills (initial + gap recovery).
    WebSocket: données temps réel.
    SQLite: stockage persistant avec déduplication.
    """

    def __init__(
        self,
        config: DydxV4Config,
        rest_client: DydxIndexerRestClient,
        storage: DydxStorage,
    ) -> None:
        self.config = config
        self.rest = rest_client
        self.storage = storage
        self.stats = IndexerStats()

    # ----------------------------------------------------------------------- #
    # Backfill REST
    # ----------------------------------------------------------------------- #

    def backfill_markets(self) -> int:
        """Backfiller tous les marchés actifs."""
        count = 0
        try:
            resp = self.rest.get_markets()
            markets_raw = resp.get("markets", {})
            for ticker, raw in markets_raw.items():
                raw["ticker"] = ticker
                market = normalize_market(raw)
                if market and market.is_active:
                    self.storage.upsert_market(market)
                    count += 1
            logger.info("backfill_markets: %d marchés", count)
            self.stats.markets_updated += count
        except RestError as e:
            logger.error("backfill_markets error: %s", e)
            self.stats.errors += 1
        return count

    def backfill_subaccount(
        self,
        address: str,
        subaccount_number: int = 0,
    ) -> bool:
        """Backfiller un subaccount (positions + subaccount info)."""
        try:
            sub_resp = self.rest.get_subaccount(address, subaccount_number)
            subaccount_raw = sub_resp.get("subaccount", {})
            if not subaccount_raw:
                logger.warning("backfill_subaccount: aucune donnée pour %s/%d", address, subaccount_number)
                return False

            sub = normalize_subaccount(subaccount_raw)
            if sub:
                self.stats.subaccounts_updated += 1
                logger.debug("backfill_subaccount: %s/%d equity=%.2f", address, subaccount_number, sub.equity)

            # Positions ouvertes
            pos_resp = self.rest.get_positions(address, subaccount_number, status="OPEN")
            positions_raw = pos_resp.get("positions", [])
            for pos_raw in positions_raw:
                pos_raw["address"] = address
                pos_raw["subaccountNumber"] = subaccount_number
                pos = normalize_position(pos_raw)
                if pos:
                    self.stats.positions_updated += 1

            return True

        except RestError as e:
            logger.error("backfill_subaccount %s/%d error: %s", address, subaccount_number, e)
            self.stats.errors += 1
            return False

    def backfill_fills(
        self,
        address: str,
        subaccount_number: int = 0,
        max_pages: int = 10,
    ) -> int:
        """
        Backfiller les fills d'un subaccount avec pagination.
        Reprend depuis le dernier fill connu (cursor relançable).
        """
        # Trouver le dernier fill connu
        last_known_ms = self.storage.get_latest_fill_ms(address, subaccount_number)
        if last_known_ms:
            logger.info(
                "backfill_fills: reprise depuis %d ms (%s/%d)",
                last_known_ms, address, subaccount_number
            )

        new_fills = 0
        dup_fills = 0

        try:
            all_fills = self.rest.paginate_fills(
                address=address,
                subaccount_number=subaccount_number,
                max_pages=max_pages,
            )

            for fill_raw in all_fills:
                fill_raw["address"] = address
                fill_raw["subaccountNumber"] = subaccount_number
                fill = normalize_fill(fill_raw)
                if fill:
                    # Skip si plus vieux que le dernier connu
                    if last_known_ms and fill.created_at_ms <= last_known_ms:
                        dup_fills += 1
                        continue
                    is_new = self.storage.insert_fill(fill)
                    if is_new:
                        new_fills += 1
                    else:
                        dup_fills += 1

            self.stats.fills_ingested += new_fills
            self.stats.fills_deduplicated += dup_fills
            self.stats.last_backfill_ms = int(time.time() * 1000)

            logger.info(
                "backfill_fills %s/%d: new=%d dup=%d total_pages=%d",
                address, subaccount_number, new_fills, dup_fills, max_pages
            )

        except RestError as e:
            logger.error("backfill_fills %s/%d error: %s", address, subaccount_number, e)
            self.stats.errors += 1

        return new_fills

    def health_check(self) -> dict:
        """Vérifier la santé de l'Indexer REST."""
        try:
            resp = self.rest.get_health()
            height = resp.get("height") or resp.get("blockHeight")
            status = "OK" if height else "DEGRADED"
            self.storage.record_health("rest_indexer", status, str(resp))
            return {"status": status, "height": height, "raw": resp}
        except RestError as e:
            self.storage.record_health("rest_indexer", "ERROR", str(e))
            return {"status": "ERROR", "error": str(e)}
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def gap_recovery(
        self,
        address: str,
        subaccount_number: int = 0,
        gap_size_threshold: int = 5,
    ) -> int:
        """
        Récupérer les fills manquants depuis le REST.

        Appelé quand un trou de données est détecté sur le WebSocket.
        """
        logger.info(
            "GAP_RECOVERY: démarrage pour %s/%d", address, subaccount_number
        )
        self.stats.gap_recoveries += 1
        recovered = self.backfill_fills(address, subaccount_number, max_pages=3)
        logger.info("GAP_RECOVERY: %d fills récupérés pour %s/%d", recovered, address, subaccount_number)
        return recovered

    def process_ws_message(
        self,
        channel: str,
        msg_type: str,
        data: dict,
        network: str,
    ) -> int:
        """
        Traiter un message WebSocket et persister les données.

        Retourne le nombre d'éléments traités.
        """
        count = 0
        self.stats.last_ws_message_ms = int(time.time() * 1000)

        if channel == "v4_trades" and msg_type == "channel_data":
            trades_raw = data.get("trades", [])
            for t_raw in trades_raw:
                trade = normalize_trade(t_raw)
                if trade:
                    count += 1

        elif channel == "v4_markets":
            contents = data.get("markets", {}) or data
            for ticker, m_raw in (contents.items() if isinstance(contents, dict) else {}.items()):
                if isinstance(m_raw, dict):
                    m_raw["ticker"] = ticker
                    market = normalize_market(m_raw)
                    if market:
                        self.storage.upsert_market(market)
                        count += 1

        elif channel == "v4_subaccounts":
            # Mises à jour fills/positions d'un subaccount
            fills = data.get("fills", []) or data.get("fill", [])
            if isinstance(fills, dict):
                fills = [fills]
            for fill_raw in fills:
                fill = normalize_fill(fill_raw)
                if fill:
                    is_new = self.storage.insert_fill(fill)
                    if is_new:
                        count += 1
                        self.stats.fills_ingested += 1
                    else:
                        self.stats.fills_deduplicated += 1

        return count
