"""
DydxEngine — moteur dYdX v4 thread-safe.

Demarre DydxLiveObserver dans un thread daemon.
Expose l'etat via des accesseurs thread-safe.
PAPER-ONLY. Aucun ordre reel. Aucune cle privee.
"""
from __future__ import annotations

import logging
import logging.handlers
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import MethodType
from typing import Optional

from hyper_smart_observer.dydx_v4.cluster_detector import DydxClusterDetector
from hyper_smart_observer.dydx_v4.config import DydxV4Config, DydxNetwork, load_config_from_env
from hyper_smart_observer.dydx_v4.cosmos_client import DydxCosmosLcdClient
from hyper_smart_observer.dydx_v4.live_observer import DydxLiveObserver
from hyper_smart_observer.dydx_v4.rest_client import DydxIndexerRestClient, RestError
from hyper_smart_observer.dydx_v4.wallet_discovery import DydxWalletDiscovery
from hyper_smart_observer.dydx_v4.safety import assert_paper_only
from hyper_smart_observer.dydx_v4.runtime_guards import correlated_count_reason, neutral_demo_price
from hyper_smart_observer.dydx_v4.real_flow_calibration import apply_real_flow_calibration

logger = logging.getLogger(__name__)

_logging_configured = False


def _ensure_file_logging() -> None:
    """Ajoute un FileHandler si aucun n'est deja configure sur le root logger."""
    global _logging_configured
    if _logging_configured:
        return
    _logging_configured = True
    root = logging.getLogger()
    if any(isinstance(h, logging.FileHandler) for h in root.handlers):
        return
    try:
        here = Path(__file__).resolve()
        project_root = Path.cwd()
        for parent in here.parents:
            if (parent / "pyproject.toml").exists():
                project_root = parent
                break
        log_dir = project_root / "logs" / "logs à envoyer"
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_dir / "hypersmart_observer.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        ))
        root.addHandler(fh)
        if root.level == logging.WARNING or root.level == 0:
            root.setLevel(logging.INFO)
        logger.info("File logging actif: %s", log_dir / "hypersmart_observer.log")
    except OSError as e:
        logger.warning("File logging impossible: %s", e)


DISCLAIMER = (
    "dYdX v4 PAPER SIMULATION — READ-ONLY public Indexer API. "
    "No real orders. No real money. No private keys. No deposits. No withdrawals."
)


@dataclass
class EngineStatus:
    running: bool = False
    started_at_ms: int = 0
    network: str = "mainnet"
    demo_mode: bool = False
    rest_url: str = ""
    rest_healthy: bool = False
    iteration: int = 0
    wallets_in_shortlist: int = 0
    open_positions: int = 0
    net_pnl_usdt: float = 0.0
    equity_usdt: float = 0.0
    total_trades: int = 0
    winrate: float = 0.0
    signals_refused: int = 0
    stale_refused: int = 0
    fees_paid: float = 0.0
    last_error: str = ""
    disclaimer: str = DISCLAIMER
    session_id: str = ""
    no_trade_reasons: dict = field(default_factory=dict)
    leader_exits: int = 0
    observer_status: dict = field(default_factory=dict)


class DydxEngine:
    """
    Moteur dYdX v4 -- thread daemon paper-only.

    Usage:
        engine = DydxEngine()
        engine.start()
        status = engine.get_status()
        engine.stop()
    """

    def __init__(self, config: Optional[DydxV4Config] = None) -> None:
        self._config = config or load_config_from_env()
        self._config = apply_real_flow_calibration(self._config)
        if getattr(self._config, 'network', None) and str(self._config.network) == "testnet" and not config:
            import dataclasses
            self._config = dataclasses.replace(
                self._config, network=DydxNetwork.MAINNET, require_testnet=False
            )
        assert_paper_only(self._config)

        self._rest = DydxIndexerRestClient(
            base_url=self._config.indexer_rest_url,
            timeout_s=self._config.rest_timeout_s,
            max_retries=self._config.rest_max_retries,
            backoff_base_s=self._config.rest_backoff_base_s,
            rate_limit_rps=self._config.rest_rate_limit_rps,
        )

        self._health_rest = DydxIndexerRestClient(
            base_url=self._config.indexer_rest_url,
            timeout_s=4.0,
            max_retries=getattr(self._config, 'health_check_retries', 0),
            backoff_base_s=0.0,
            rate_limit_rps=10.0,
        )

        self._cosmos = DydxCosmosLcdClient()
        self._cluster = DydxClusterDetector(
            consensus_window_ms=60_000,
            min_notional_usdc=5_000.0,
        )
        self._discovery = DydxWalletDiscovery(
            rest_client=self._rest,
            cosmos_client=self._cosmos,
            demo_mode=getattr(self._config, 'demo_mode', False),
        )
        self._observer: Optional[DydxLiveObserver] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._realtime_lock = threading.Lock()
        self._last_realtime_price_refresh_ms = 0
        self._status = EngineStatus(
            network=str(self._config.network.value)
            if hasattr(self._config.network, "value")
            else str(self._config.network),
            rest_url=self._config.indexer_rest_url,
        )

    # -- public API --
