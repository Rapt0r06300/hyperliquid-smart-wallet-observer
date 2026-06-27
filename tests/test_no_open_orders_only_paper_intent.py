"""Preuve de la règle absolue copy-trading Hyperliquid (SIMULATION ONLY).

Règle: des `openOrders` seuls (sans fill ni changement de position) ne doivent
JAMAIS produire un PaperIntent / PaperTrade. Ils ne sont qu'un contexte.

Cette preuve exerce la vraie chaîne `run_copy_dry_run` avec un faux client /info
read-only qui ne renvoie AUCUN fill et AUCUNE position, mais renvoie des
openOrders. On vérifie:
  1. qu'une NoTradeDecision `OPEN_ORDERS_CONTEXT_ONLY` est émise;
  2. qu'aucun signal n'est généré;
  3. qu'aucun paper trade n'est ouvert (preuve openOrders != PaperIntent).

Aucun réseau, aucun ordre réel, base SQLite temporaire (tmp_path).
Compatible Python 3.10 et 3.11 (pas d'usage de datetime.UTC).
"""

from __future__ import annotations

from time import time

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run, shortlist_path
from hyper_smart_observer.copy_mode.copy_models import (
    LeaderCandidateInput,
    NoTradeReason,
)
from hyper_smart_observer.copy_mode.leaderboard_selector import (
    LeaderboardSelectionConfig,
    select_leaderboard_shortlist,
    write_shortlist_report,
)
from hyper_smart_observer.hyperliquid_client.info_client import PaginationResult
from hyper_smart_observer.storage.database import get_connection
from hyper_smart_observer.storage.repositories import paper_trades_repo


GOOD_ADDRESS = "0x" + "d" * 40


class OpenOrdersOnlyFakeInfoClient:
    """Faux client /info: openOrders présents, mais 0 fill et 0 position.

    C'est le cas exact où un copieur naïf pourrait être tenté d'ouvrir une
    position alors qu'aucune preuve d'exécution (fill / delta) n'existe.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.now_ms = int(time() * 1000)

    def get_all_mids(self):
        self.calls.append("allMids")
        return {"BTC": "100.2"}

    def get_clearinghouse_state(self, address: str):
        self.calls.append("clearinghouseState")
        # Equity présente mais AUCUNE position ouverte -> aucun delta possible.
        return {"marginSummary": {"accountValue": "1000"}, "assetPositions": []}

    def collect_user_fills_by_time_paginated(
        self, address: str, start_time_ms: int, end_time_ms: int, *, max_pages=None
    ):
        self.calls.append("userFillsByTime")
        # Aucun fill -> aucune preuve d'exécution.
        return PaginationResult(
            fills=[], pages_fetched=1, stopped_reason="empty_response", warnings=[]
        )

    def get_user_fills(self, address: str, *, aggregate_by_time: bool = False):
        self.calls.append("userFills")
        return []

    def get_open_orders(self, address: str):
        self.calls.append("openOrders")
        # Contexte uniquement: des ordres ouverts, mais jamais une preuve.
        return [{"coin": "BTC", "oid": 777, "side": "B", "sz": "1", "limitPx": "99.5"}]

    def get_frontend_open_orders(self, address: str):
        self.calls.append("frontendOpenOrders")
        return [{"coin": "BTC", "oid": 777, "side": "B", "sz": "1", "limitPx": "99.5"}]

    def get_user_fees(self, address: str):
        self.calls.append("userFees")
        return {}

    def get_user_rate_limit(self, address: str):
        self.calls.append("userRateLimit")
        return {}


def _config(tmp_path) -> AppConfig:
    return AppConfig(
        runtime_root=tmp_path,
        database_path=tmp_path / "data" / "hypersmart.sqlite3",
        reports_dir=tmp_path / "data" / "reports",
        dashboard_dir=tmp_path / "data" / "dashboard",
        info_min_request_interval_ms=0,
        paper_max_open_trades=5,
    )


def _write_shortlist(config: AppConfig) -> None:
    report = select_leaderboard_shortlist(
        [
            LeaderCandidateInput(
                wallet_address=GOOD_ADDRESS,
                history_days=30,
                closed_pnl_points=50,
                total_closed_pnl=1000.0,
                max_single_trade_pnl=100.0,
                max_drawdown_pct=10.0,
                consistency_score=90.0,
                per_coin_stability_score=85.0,
                execution_quality_score=85.0,
                sample_confidence=90.0,
                copyability_score=90.0,
            )
        ],
        config=LeaderboardSelectionConfig(min_score=1),
    )
    write_shortlist_report(report, shortlist_path(config))


def test_open_orders_only_emits_context_only_no_trade(tmp_path):
    """openOrders seuls -> NoTradeDecision OPEN_ORDERS_CONTEXT_ONLY, zéro signal."""
    config = _config(tmp_path)
    _write_shortlist(config)
    fake = OpenOrdersOnlyFakeInfoClient()

    report = run_copy_dry_run(
        config, interval_seconds=300, network_read=True, info_client=fake
    )

    # Le client a bien lu les openOrders en read-only.
    assert "openOrders" in fake.calls
    # Aucun delta (pas de fill, pas de position) => zéro signal candidat.
    assert report.deltas_seen == 0
    assert not report.signal_candidates
    # La décision explicite "contexte uniquement" doit être présente.
    assert any(
        decision.reason == NoTradeReason.OPEN_ORDERS_CONTEXT_ONLY
        for decision in report.no_trade_decisions
    )


def test_open_orders_only_never_opens_paper_trade(tmp_path):
    """Preuve directe: openOrders seuls n'ouvrent JAMAIS de paper trade."""
    config = _config(tmp_path)
    _write_shortlist(config)
    fake = OpenOrdersOnlyFakeInfoClient()

    run_copy_dry_run(
        config, interval_seconds=300, network_read=True, info_client=fake
    )

    with get_connection(config) as conn:
        open_trades = paper_trades_repo.list_open_paper_trades(conn)
    assert open_trades == [] or not open_trades


def test_open_orders_reason_alias_maps_to_canonical_value():
    """Le nom du brief (OPEN_ORDERS_ONLY_NOT_EVIDENCE) == code existant."""
    from hyper_smart_observer.copy_mode.copy_models import (
        OPEN_ORDERS_ONLY_NOT_EVIDENCE,
        REASON_CODE_ALIASES,
    )

    assert OPEN_ORDERS_ONLY_NOT_EVIDENCE == NoTradeReason.OPEN_ORDERS_CONTEXT_ONLY
    assert (
        REASON_CODE_ALIASES["OPEN_ORDERS_ONLY_NOT_EVIDENCE"]
        == NoTradeReason.OPEN_ORDERS_CONTEXT_ONLY
    )
