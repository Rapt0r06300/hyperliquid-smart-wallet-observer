from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from hl_observer.storage.models import Wallet, WalletCandidateModel, WalletDiscoveryRun
from hl_observer.utils.time import now_ms
from hl_observer.wallets.leaderboard_models import candidate_from_persisted_row
from hl_observer.wallets.leaderboard_queries import latest_leaderboard_candidate_rows
from hl_observer.wallets.leaderboard_validation import is_truncated_wallet_display

WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


class WalletDiscoveryCandidate(BaseModel):
    address: str | None
    coin: str | None = None
    source_name: str
    source_type: str
    label: str | None = None
    external_pnl_usdc: float | None = None
    external_roi_pct: float | None = None
    external_volume_usdc: float | None = None
    external_win_rate: float | None = None
    external_position_usdc: float | None = None
    external_unrealized_pnl: float | None = None
    external_funding_fee: float | None = None
    first_seen_ms: int = Field(default_factory=now_ms)
    last_seen_ms: int = Field(default_factory=now_ms)
    activity_evidence_verified: bool = False
    activity_trade_count: int | None = None
    activity_window_start_ms: int | None = None
    activity_window_end_ms: int | None = None
    last_trade_event_ms: int | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    confidence_score: float = 0.0


class WalletDiscoverySourceResult(BaseModel):
    source_name: str
    source_type: str
    url: str | None = None
    reliability_score: float
    status: str
    candidates: list[WalletDiscoveryCandidate] = Field(default_factory=list)
    error_message: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    fetched_at_ms: int = Field(default_factory=now_ms)


class WalletDiscoverySource(ABC):
    name: str
    source_type: str
    url: str | None = None
    reliability_score: float = 0.5

    @abstractmethod
    def fetch_candidates(self, *, session: Session | None = None, limit: int = 50) -> WalletDiscoverySourceResult:
        raise NotImplementedError

    def health_check(self) -> bool:
        return True


class LocalDbWalletSource(WalletDiscoverySource):
    name = "local_db"
    source_type = "local_db"
    reliability_score = 0.85

    def fetch_candidates(self, *, session: Session | None = None, limit: int = 50) -> WalletDiscoverySourceResult:
        if session is None:
            return WalletDiscoverySourceResult(
                source_name=self.name,
                source_type=self.source_type,
                reliability_score=self.reliability_score,
                status="source_failed",
                error_message="database session missing",
            )
        wallets = session.scalars(select(Wallet).order_by(Wallet.created_at.desc()).limit(limit)).all()
        candidates = [
            WalletDiscoveryCandidate(
                address=wallet.address,
                source_name=self.name,
                source_type=self.source_type,
                label=wallet.label,
                raw_payload={"status": wallet.status},
                confidence_score=self.reliability_score,
            )
            for wallet in wallets
        ]
        return WalletDiscoverySourceResult(
            source_name=self.name,
            source_type=self.source_type,
            reliability_score=self.reliability_score,
            status="ok",
            candidates=candidates,
            raw_payload={"wallets_count": len(candidates)},
        )


class ConfigWalletSource(WalletDiscoverySource):
    name = "local_config"
    source_type = "local_config"
    reliability_score = 0.75

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or Path("config/wallets.yaml")

    def fetch_candidates(self, *, session: Session | None = None, limit: int = 50) -> WalletDiscoverySourceResult:
        _ = session
        path = self.config_path if self.config_path.exists() else Path("config/wallets.example.yaml")
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
            wallet_items = _extract_wallet_items(raw or {})
            candidates = []
            for item in wallet_items[:limit]:
                if isinstance(item, str):
                    address = item
                    label = None
                    payload: dict[str, Any] = {"address": item}
                elif isinstance(item, dict):
                    address = _normalize_config_address(item.get("address") or item.get("wallet") or "")
                    label = item.get("label")
                    payload = item
                else:
                    continue
                candidates.append(
                    WalletDiscoveryCandidate(
                        address=address,
                        coin=_normalize_config_coin(payload.get("coin") or payload.get("asset")),
                        source_name=self.name,
                        source_type=self.source_type,
                        label=label,
                        raw_payload=payload,
                        confidence_score=self.reliability_score,
                    )
                )
        except Exception as exc:  # noqa: BLE001 - source failure is reported and stored.
            return WalletDiscoverySourceResult(
                source_name=self.name,
                source_type=self.source_type,
                reliability_score=self.reliability_score,
                status="source_failed",
                error_message=str(exc),
            )
        return WalletDiscoverySourceResult(
            source_name=self.name,
            source_type=self.source_type,
            reliability_score=self.reliability_score,
            status="ok",
            candidates=candidates,
            raw_payload={"path": str(path), "wallets_count": len(candidates)},
        )


class PreparedExternalWalletSource(WalletDiscoverySource):
    def __init__(self, name: str, source_type: str, url: str | None, reliability_score: float) -> None:
        self.name = name
        self.source_type = source_type
        self.url = url
        self.reliability_score = reliability_score

    def fetch_candidates(self, *, session: Session | None = None, limit: int = 50) -> WalletDiscoverySourceResult:
        _ = (session, limit)
        return WalletDiscoverySourceResult(
            source_name=self.name,
            source_type=self.source_type,
            url=self.url,
            reliability_score=self.reliability_score,
            status="not_implemented",
            candidates=[],
            error_message="source externe preparee mais non active sans endpoint stable teste",
            raw_payload={"active": False},
        )


class HyperliquidLeaderboardSource(WalletDiscoverySource):
    name = "hyperliquid_leaderboard"
    source_type = "official_leaderboard"
    url = "https://app.hyperliquid.xyz/leaderboard"
    reliability_score = 0.90

    def fetch_candidates(self, *, session: Session | None = None, limit: int = 50) -> WalletDiscoverySourceResult:
        if session is None:
            return WalletDiscoverySourceResult(
                source_name=self.name,
                source_type=self.source_type,
                url=self.url,
                reliability_score=self.reliability_score,
                status="source_failed",
                error_message="database session missing",
            )
        rows = latest_leaderboard_candidate_rows(session, limit=limit)
        candidates = []
        for row in rows:
            if not is_valid_discovery_address(row.wallet_address):
                continue
            current = candidate_from_persisted_row(row)
            candidates.append(WalletDiscoveryCandidate(
                address=row.wallet_address,
                source_name=self.name,
                source_type=self.source_type,
                external_pnl_usdc=row.pnl_usdc,
                external_roi_pct=row.roi_pct,
                external_volume_usdc=row.volume_usdc,
                raw_payload={
                    "rank": row.rank,
                    "period": row.period,
                    "account_value_usdc": row.account_value_usdc,
                    "leaderboard_score": current.leaderboard_score,
                },
                confidence_score=self.reliability_score,
            ))
        candidates.sort(
            key=lambda candidate: float(candidate.raw_payload["leaderboard_score"]),
            reverse=True,
        )
        status = "ok" if candidates else "import_required"
        error = None if candidates else "leaderboard sans adresse complete stockee; import CSV/JSON/TXT requis"
        return WalletDiscoverySourceResult(
            source_name=self.name,
            source_type=self.source_type,
            url=self.url,
            reliability_score=self.reliability_score,
            status=status,
            candidates=candidates,
            error_message=error,
            raw_payload={"leaderboard_candidates": len(candidates)},
        )


class PublicTradesWalletSource(WalletDiscoverySource):
    """Use only timestamp-verified public trades from the latest complete scan.

    These observations prioritize wallet history backfill; they do not establish
    direction, closed-trade PnL, or copyable economic edge.
    """

    name = "public_trades_ws"
    source_type = "websocket_read_only"
    url = "https://api.hyperliquid.xyz/ws"
    reliability_score = 0.85

    def fetch_candidates(self, *, session: Session | None = None, limit: int = 50) -> WalletDiscoverySourceResult:
        if session is None:
            return WalletDiscoverySourceResult(
                source_name=self.name,
                source_type=self.source_type,
                url=self.url,
                reliability_score=self.reliability_score,
                status="source_failed",
                error_message="database session missing",
            )
        run = session.scalar(
            select(WalletDiscoveryRun)
            .where(
                WalletDiscoveryRun.status == "COMPLETED",
                WalletDiscoveryRun.notes.like("public_trades_ws;%"),
            )
            .order_by(WalletDiscoveryRun.id.desc())
            .limit(1)
        )
        if run is None or limit <= 0:
            return WalletDiscoverySourceResult(
                source_name=self.name,
                source_type=self.source_type,
                url=self.url,
                reliability_score=self.reliability_score,
                status="no_observations",
                candidates=[],
                raw_payload={"latest_complete_scan_found": run is not None},
            )

        rows = session.scalars(
            select(WalletCandidateModel)
            .where(
                WalletCandidateModel.run_id == run.id,
                WalletCandidateModel.source_name == self.name,
            )
            .order_by(WalletCandidateModel.confidence_score.desc(), WalletCandidateModel.id.asc())
            .limit(limit)
        ).all()
        candidates: list[WalletDiscoveryCandidate] = []
        for row in rows:
            if not is_valid_discovery_address(row.address):
                continue
            payload = row.raw_payload_json if isinstance(row.raw_payload_json, dict) else {}
            count = _nonnegative_int(payload.get("trades_count"))
            window_start = _positive_int(payload.get("activity_window_start_ms"))
            window_end = _positive_int(payload.get("activity_window_end_ms"))
            last_trade = _positive_int(payload.get("last_trade_event_ms"))
            verified = (
                payload.get("activity_timestamps_verified") is True
                and count is not None
                and window_start is not None
                and window_end is not None
                and last_trade is not None
                and 0 < window_end - window_start <= 300_000
                and window_start - 60_000 <= last_trade <= window_end + 60_000
            )
            candidates.append(
                WalletDiscoveryCandidate(
                    address=row.address,
                    coin=(row.coin.split(",", 1)[0] if row.coin else None),
                    source_name=self.name,
                    source_type=self.source_type,
                    label=row.label,
                    first_seen_ms=row.first_seen_ms,
                    last_seen_ms=row.last_seen_ms,
                    activity_evidence_verified=verified,
                    activity_trade_count=count if verified else None,
                    activity_window_start_ms=window_start if verified else None,
                    activity_window_end_ms=window_end if verified else None,
                    last_trade_event_ms=last_trade if verified else None,
                    raw_payload={
                        "run_id": run.id,
                        "exchange_activity_verified": verified,
                        "activity_timestamps_verified": payload.get("activity_timestamps_verified") is True,
                        "trades_count": count,
                        "observed_notional_usdc": row.external_volume_usdc,
                        "coins": payload.get("coins", []),
                        "research_only": True,
                        "warning": "public prints do not prove wallet direction or copyable net edge",
                    },
                    confidence_score=self.reliability_score,
                )
            )
        return WalletDiscoverySourceResult(
            source_name=self.name,
            source_type=self.source_type,
            url=self.url,
            reliability_score=self.reliability_score,
            status="ok" if candidates else "no_observations",
            candidates=candidates,
            raw_payload={"run_id": run.id, "candidate_count": len(candidates)},
        )


class HyperliquidExplorerSource(WalletDiscoverySource):
    name = "hyperliquid_explorer"
    source_type = "public_explorer"
    url = "https://app.hyperliquid.xyz/explorer"
    reliability_score = 0.80

    def fetch_candidates(self, *, session: Session | None = None, limit: int = 50) -> WalletDiscoverySourceResult:
        if session is None:
            return WalletDiscoverySourceResult(
                source_name=self.name,
                source_type=self.source_type,
                url=self.url,
                reliability_score=self.reliability_score,
                status="source_failed",
                error_message="database session missing",
            )
        from hl_observer.storage.models import ExplorerWalletCandidate

        rows = session.scalars(
            select(ExplorerWalletCandidate)
            .order_by(ExplorerWalletCandidate.activity_score.desc())
            .limit(limit)
        ).all()
        candidates = [
            WalletDiscoveryCandidate(
                address=row.wallet_address,
                coin=(row.coins_json[0] if row.coins_json else None),
                source_name=self.name,
                source_type=self.source_type,
                raw_payload={
                    "events_count": row.events_count,
                    "first_tx_hash": row.first_tx_hash,
                    "coins": row.coins_json,
                    "activity_score": row.activity_score,
                },
                confidence_score=self.reliability_score,
            )
            for row in rows
            if is_valid_discovery_address(row.wallet_address)
        ]
        status = "ok" if candidates else "import_required"
        error = None if candidates else "explorer sans adresse complete stockee; probe ou import requis"
        return WalletDiscoverySourceResult(
            source_name=self.name,
            source_type=self.source_type,
            url=self.url,
            reliability_score=self.reliability_score,
            status=status,
            candidates=candidates,
            error_message=error,
            raw_payload={"explorer_candidates": len(candidates)},
        )


def build_discovery_sources(source_names: list[str]) -> list[WalletDiscoverySource]:
    registry: dict[str, WalletDiscoverySource] = {
        "local_db": LocalDbWalletSource(),
        "local": LocalDbWalletSource(),
        "local_config": ConfigWalletSource(),
        "config": ConfigWalletSource(),
        "leaderboard": HyperliquidLeaderboardSource(),
        "hyperliquid_leaderboard": HyperliquidLeaderboardSource(),
        "hyperliquid-leaderboard": HyperliquidLeaderboardSource(),
        "public_trades_ws": PublicTradesWalletSource(),
        "public-trades-ws": PublicTradesWalletSource(),
        "explorer": HyperliquidExplorerSource(),
        "hyperliquid_explorer": HyperliquidExplorerSource(),
        "hyperliquid-explorer": HyperliquidExplorerSource(),
        "coinglass": PreparedExternalWalletSource(
            "coinglass_whale_tracker",
            "coinglass_whale_tracker",
            "https://www.coinglass.com/",
            0.55,
        ),
        "coinglass_whale_tracker": PreparedExternalWalletSource(
            "coinglass_whale_tracker",
            "coinglass_whale_tracker",
            "https://www.coinglass.com/",
            0.55,
        ),
        "hyperdash": PreparedExternalWalletSource("hyperdash", "third_party_dashboard", None, 0.50),
        "hypertracker": PreparedExternalWalletSource("hypertracker", "third_party_dashboard", None, 0.50),
    }
    if not source_names or "all" in source_names:
        source_names = [
            "hyperliquid_leaderboard",
            "hyperliquid_explorer",
            "local_db",
            "local_config",
            "public_trades_ws",
            "hyperdash",
            "hypertracker",
        ]
    return [registry[name] for name in source_names if name in registry]


def _extract_wallet_items(raw: dict[str, Any]) -> list[Any]:
    wallets = raw.get("wallets", raw)
    if not isinstance(wallets, dict):
        return []
    items: list[Any] = []
    for key in ("watchlist", "candidates", "shortlist"):
        value = wallets.get(key)
        if isinstance(value, list):
            items.extend(value)
    return items


def _normalize_config_address(value: Any) -> str:
    if isinstance(value, int):
        # YAML may parse an unquoted 0x... address as an integer; this reverses
        # that exact parse, not a fuzzy completion of a truncated address.
        return f"0x{value:040x}"
    return str(value)


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _normalize_config_coin(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value).upper()


def is_valid_discovery_address(address: str | None) -> bool:
    if not address:
        return False
    if is_truncated_wallet_display(address) or "..." in address:
        return False
    return bool(WALLET_RE.fullmatch(address))
