from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.app.safety import SafetyViolation, validate_runtime_config
from hyper_smart_observer.hyperliquid_client.info_client import HyperliquidInfoClient
from hyper_smart_observer.hyperliquid_client.models import Wallet
from hyper_smart_observer.hyperliquid_client.normalization import (
    NormalizationError,
    normalize_position_snapshot,
    normalize_user_fill,
)
from hyper_smart_observer.hyperliquid_client.validation import (
    is_valid_wallet_address,
    normalize_wallet_address,
)
from hyper_smart_observer.storage.database import get_connection, initialize_database
from hyper_smart_observer.storage.repositories.fills_repo import insert_many_fills
from hyper_smart_observer.storage.repositories.positions_repo import insert_many_position_snapshots
from hyper_smart_observer.storage.repositories.wallet_repo import insert_wallet


@dataclass(frozen=True)
class CollectionReport:
    wallets_requested: int = 0
    wallets_collected: int = 0
    fills_inserted: int = 0
    position_snapshots_inserted: int = 0
    errors: dict[str, str] = field(default_factory=dict)
    pages_by_wallet: dict[str, int] = field(default_factory=dict)
    network_reads_enabled: bool = False


def is_valid_manual_wallet_address(address: str) -> bool:
    return is_valid_wallet_address(address)


def collect_manual_wallets(addresses: list[str], *, source: str = "manual") -> list[Wallet]:
    seen: set[str] = set()
    wallets: list[Wallet] = []
    for raw in addresses:
        address = raw.strip().lower()
        if not is_valid_wallet_address(address) or address in seen:
            continue
        seen.add(address)
        wallets.append(Wallet(address=address, source=source))
    return wallets


class HyperliquidReadOnlyCollector:
    """Controlled read-only collector for Hyperliquid public wallet data."""

    def __init__(self, config: AppConfig, *, client: HyperliquidInfoClient | None = None):
        self.config = config
        self.client = client or HyperliquidInfoClient(config)

    def collect_wallets(
        self,
        wallet_addresses: list[str],
        *,
        start_time_ms: int,
        end_time_ms: int,
        max_pages: int | None = None,
        network_read: bool = False,
        max_wallets: int = 10,
    ) -> CollectionReport:
        validate_runtime_config(self.config)
        if not (network_read and self.config.enable_network_reads):
            raise SafetyViolation(
                "CONFIGURATION_REFUSED",
                "Read-only network collection requires explicit network-read opt-in.",
            )

        normalized_wallets = [normalize_wallet_address(address) for address in wallet_addresses]
        bounded_wallets = normalized_wallets[: max(0, max_wallets)]
        initialize_database(self.config)

        report = CollectionReport(
            wallets_requested=len(wallet_addresses),
            network_reads_enabled=True,
        )
        errors: dict[str, str] = {}
        pages_by_wallet: dict[str, int] = {}
        wallets_collected = 0
        fills_inserted = 0
        positions_inserted = 0

        with get_connection(self.config) as conn:
            for wallet_address in bounded_wallets:
                try:
                    insert_wallet(conn, Wallet(address=wallet_address, source="hyperliquid_info"))
                    paginated = self.client.collect_user_fills_by_time_paginated(
                        wallet_address,
                        start_time_ms,
                        end_time_ms,
                        max_pages=max_pages,
                    )
                    fills = []
                    for raw_fill in paginated.fills:
                        try:
                            fills.append(normalize_user_fill(raw_fill, wallet_address))
                        except NormalizationError:
                            continue
                    fills_inserted += insert_many_fills(conn, fills)
                    state = self.client.get_clearinghouse_state(wallet_address)
                    snapshots = _extract_position_snapshots(state, wallet_address)
                    positions_inserted += insert_many_position_snapshots(conn, snapshots)
                    pages_by_wallet[wallet_address] = paginated.pages_fetched
                    wallets_collected += 1
                except Exception as exc:  # noqa: BLE001 - per-wallet errors stay in report.
                    errors[wallet_address] = str(exc)
            conn.commit()

        return CollectionReport(
            wallets_requested=report.wallets_requested,
            wallets_collected=wallets_collected,
            fills_inserted=fills_inserted,
            position_snapshots_inserted=positions_inserted,
            errors=errors,
            pages_by_wallet=pages_by_wallet,
            network_reads_enabled=True,
        )


def _extract_position_snapshots(state: dict[str, Any], wallet_address: str):
    raw_positions = state.get("assetPositions") or state.get("positions") or []
    snapshots = []
    if not isinstance(raw_positions, list):
        return snapshots
    for raw_position in raw_positions:
        if not isinstance(raw_position, dict):
            continue
        try:
            snapshots.append(normalize_position_snapshot(raw_position, wallet_address))
        except NormalizationError:
            continue
    return snapshots
