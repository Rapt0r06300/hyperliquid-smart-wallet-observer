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
from hyper_smart_observer.dydx_v4.runtime_guards import correlated_count_reason

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
            demo_mode=False,
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

    def start(self) -> None:
        """Demarre le thread daemon paper-only."""
        _ensure_file_logging()
        assert_paper_only(self._config)
        if self._thread and self._thread.is_alive():
            logger.info("DydxEngine already running")
            return
        self._thread = threading.Thread(
            target=self._run_loop,
            name="dydx-engine",
            daemon=True,
        )
        self._thread.start()
        logger.info("DydxEngine started | %s", DISCLAIMER)

    def stop(self) -> None:
        """Arrete l'observateur proprement."""
        if self._observer:
            self._observer.stop()
        logger.info("DydxEngine stopped")

    def get_status(self) -> dict:
        with self._lock:
            s = self._status
            status = {
                "running": s.running,
                "started_at_ms": s.started_at_ms,
                "network": s.network,
                "rest_url": s.rest_url,
                "rest_healthy": s.rest_healthy,
                "iteration": s.iteration,
                "wallets_in_shortlist": s.wallets_in_shortlist,
                "open_positions": s.open_positions,
                "net_pnl_usdt": round(s.net_pnl_usdt, 4),
                "equity_usdt": round(s.equity_usdt, 4),
                "total_trades": s.total_trades,
                "winrate": f"{s.winrate:.0%}",
                "signals_refused": s.signals_refused,
                "stale_refused": s.stale_refused,
                "fees_paid": round(s.fees_paid, 4),
                "last_error": s.last_error,
                "disclaimer": s.disclaimer,
                "session_id": s.session_id,
                "no_trade_reasons": dict(
                    sorted(s.no_trade_reasons.items(), key=lambda x: -x[1])[:10]
                ),
                "leader_exits": s.leader_exits,
                "demo_mode": s.demo_mode,
            }
            observer_status = dict(s.observer_status or {})

        if observer_status:
            status.update(observer_status)
            if "net_pnl_usdc" in observer_status:
                status["net_pnl_usdt"] = round(float(observer_status.get("net_pnl_usdc") or 0.0), 4)
            if "realized_pnl_usdc" in observer_status:
                status["realized_pnl_usdt"] = round(float(observer_status.get("realized_pnl_usdc") or 0.0), 4)
            if "unrealized_pnl_usdc" in observer_status:
                status["unrealized_pnl_usdt"] = round(float(observer_status.get("unrealized_pnl_usdc") or 0.0), 4)
            if "equity" in observer_status:
                status["equity_usdt"] = round(float(observer_status.get("equity") or self._config.starting_balance_usdc), 4)
            status["wallets_in_shortlist"] = int(
                observer_status.get("shortlist_size", status.get("wallets_in_shortlist", 0)) or 0
            )
        return status

    def get_wallets(self) -> list[dict]:
        if not self._observer:
            return []
        return [
            {
                "address": w.address,
                "subaccount": w.subaccount_number,
                "usdc_balance": round(w.usdc_balance, 2),
                "score": round(w.total_score, 4),
                "markets": [p.get("market", "") for p in (w.open_positions or [])],
            }
            for w in (self._observer._shortlist or [])
        ]

    def get_open_positions(self) -> list[dict]:
        if not self._observer:
            return []
        with self._lock:
            marks = self._observer._mark_prices
            out = []
            for pos in self._observer._open_positions.values():
                mark = marks.get(pos.market_id) or pos.entry_price
                out.append({
                    "position_id": pos.position_id,
                    "market_id": pos.market_id,
                    "side": pos.side,
                    "size": round(pos.size, 4),
                    "entry_price": round(pos.entry_price, 4),
                    "mark_price": round(mark, 6),
                    "unrealized_pnl_usdc": round(pos.calculate_pnl(mark), 4),
                    "stop_loss": round(pos.stop_loss_price, 4),
                    "take_profit": round(pos.take_profit_price, 4),
                    "opened_at_ms": pos.opened_at_ms,
                    "wallet_count": pos.wallet_count,
                    "fee_paid": round(pos.fee_paid, 4),
                    "cluster_id": pos.cluster_id,
                    "data_source": getattr(pos, "data_source", ""),
                    "entry_edge_bps": round(float(getattr(pos, "entry_edge_bps", 0.0) or 0.0), 4),
                    "market_regime": getattr(pos, "market_regime", ""),
                })
            return out

    def get_closed_trades(self, limit: int = 50) -> list[dict]:
        if not self._observer:
            return []
        return list(self._observer._closed_trades[-limit:])

    def get_recent_decisions(self, limit: int = 100, event_type: str | None = None) -> list[dict]:
        if not self._observer:
            return []
        try:
            return self._observer.get_recent_decisions(limit=limit, event_type=event_type)
        except Exception:
            return []

    def get_refused_decisions(self, limit: int = 100) -> list[dict]:
        return self.get_recent_decisions(limit=limit, event_type="NO_TRADE")

    def get_mark_prices(self) -> dict:
        if not self._observer:
            return {}
        return dict(self._observer._mark_prices)

    def get_realtime_tick(self) -> dict:
        """
        Snapshot leger pour l'UI simulation.

        Cette methode reste READ-ONLY / PAPER-ONLY: elle rafraichit au plus une
        fois par seconde les marks publics puis recalcule le PnL latent local.
        Aucun ordre, aucune signature, aucun endpoint prive.
        """
        now_ms = int(time.time() * 1000)
        refreshed_prices = self._maybe_refresh_realtime_prices(now_ms)

        status = self.get_status()
        if self._observer is not None:
            try:
                live_status = self._observer.get_status()
                status.update(live_status)
                if "net_pnl_usdc" in live_status:
                    status["net_pnl_usdt"] = float(live_status.get("net_pnl_usdc") or 0.0)
                if "realized_pnl_usdc" in live_status:
                    status["realized_pnl_usdt"] = float(live_status.get("realized_pnl_usdc") or 0.0)
                if "unrealized_pnl_usdc" in live_status:
                    status["unrealized_pnl_usdt"] = float(live_status.get("unrealized_pnl_usdc") or 0.0)
                if "equity" in live_status:
                    status["equity_usdt"] = float(
                        live_status.get("equity") or self._config.starting_balance_usdc
                    )
            except Exception as e:
                logger.debug("live realtime status skipped: %s", e)
        positions = self.get_open_positions()
        prices = self.get_mark_prices()
        net_pnl = float(status.get("net_pnl_usdt") or 0.0)
        equity = float(status.get("equity_usdt") or self._config.starting_balance_usdc)
        realized = float(status.get("realized_pnl_usdt") or 0.0)
        unrealized = float(status.get("unrealized_pnl_usdt") or (net_pnl - realized))

        return {
            "timestamp_ms": now_ms,
            "session_id": status.get("session_id", ""),
            "running": bool(status.get("running", False)),
            "paper_only": True,
            "read_only": True,
            "mode": status.get("mode", "PAPER"),
            "refreshed_prices": refreshed_prices,
            "net_pnl_usdt": round(net_pnl, 6),
            "realized_pnl_usdt": round(realized, 6),
            "unrealized_pnl_usdt": round(unrealized, 6),
            "equity_usdt": round(equity, 6),
            "open_positions": len(positions),
            "positions": positions,
            "prices": prices,
            "total_trades": status.get("total_trades", 0),
            "winning_trades": status.get("winning_trades", 0),
            "winrate": status.get("winrate", "0%"),
            "wallets_in_shortlist": status.get("wallets_in_shortlist", 0),
            "signals_refused": status.get("signals_refused", 0),
            "stale_refused": status.get("stale_refused", 0),
            "market_flow": status.get("market_flow", {}),
            "stream": status.get("stream", {}),
            "scan": status.get("scan", {}),
            "disclaimer": DISCLAIMER,
        }

    def _maybe_refresh_realtime_prices(self, now_ms: int) -> bool:
        observer = self._observer
        if observer is None:
            return False
        applied_flow_prices = self._apply_realtime_flow_prices(observer)
        if now_ms - self._last_realtime_price_refresh_ms < 900:
            return applied_flow_prices
        with self._realtime_lock:
            if now_ms - self._last_realtime_price_refresh_ms < 900:
                return applied_flow_prices
            self._last_realtime_price_refresh_ms = now_ms
            refresh = getattr(observer, "_refresh_market_prices", None)
            if not callable(refresh):
                return applied_flow_prices
            try:
                refresh()
                return True
            except Exception as e:
                logger.debug("realtime mark refresh skipped: %s", e)
                return applied_flow_prices

    def _apply_realtime_flow_prices(self, observer: object) -> bool:
        """
        Appliquer les derniers prix du flux public `v4_trades` au mark-to-market.

        C'est purement visuel/comptable pour la simulation paper: aucune décision
        d'entrée n'est créée ici, aucun ordre n'est envoyé, et le REST reste le
        fallback si le flux public n'a rien de frais.
        """
        flow = getattr(observer, "_flow_monitor", None)
        latest = getattr(flow, "latest_prices", None)
        marks = getattr(observer, "_mark_prices", None)
        if not callable(latest) or not isinstance(marks, dict):
            return False
        try:
            prices = latest(max_age_ms=5_000)
        except Exception as e:
            logger.debug("realtime flow marks skipped: %s", e)
            return False
        updated = False
        for market, price in prices.items():
            try:
                value = float(price)
            except (TypeError, ValueError):
                continue
            if value <= 0:
                continue
            current = marks.get(market)
            if current != value:
                marks[market] = value
                updated = True
        return updated

    # -- internal --

    def _install_observer_integrity_hooks(self) -> None:
        """Installe les corrections d'intégration non destructives sur l'observer."""
        observer = self._observer
        if observer is None or getattr(observer, "_engine_integrity_hooks", False):
            return

        def _corr(self_observer, market: str, side: str):
            return correlated_count_reason(self_observer, market, side)

        observer._correlated_exposure_reason = MethodType(_corr, observer)
        observer._engine_integrity_hooks = True
        logger.info("DydxEngine integrity hooks active: correlation=count, artificial_prices=disabled")

    def _run_loop(self) -> None:
        """Boucle principale dans le thread daemon."""
        assert_paper_only(self._config)

        try:
            health = self._health_rest.get_health()
            with self._lock:
                self._status.rest_healthy = True
                self._status.last_error = ""
            logger.info("dYdX Indexer health OK: %s", health)
        except Exception as e:
            with self._lock:
                self._status.rest_healthy = False
                self._status.last_error = "REST_UNREACHABLE"
            logger.warning("dYdX Indexer health FAILED (non-bloquant): %s", e)
            logger.info("REST inaccessible -> no artificial fallback; waiting for real read-only data")

        _seed_shortlist = []
        logger.info("Engine seed: empty; real read-only data only")
        self._observer = DydxLiveObserver(
            config=self._config,
            rest_client=self._rest,
            cluster_detector=self._cluster,
            discovery=self._discovery,
            initial_shortlist=_seed_shortlist,
            poll_interval_s=5.0,
            max_signal_age_ms=self._config.max_signal_age_ms,
            cosmos_client=self._cosmos,
        )
        self._install_observer_integrity_hooks()

        with self._lock:
            self._status.running = True
            self._status.started_at_ms = int(time.time() * 1000)
            self._status.session_id = self._observer.stats.session_id
            self._status.demo_mode = False

        original_poll = self._observer._poll_shortlist

        def _patched_poll(*args, **kwargs):
            result = original_poll(*args, **kwargs)
            priority = getattr(self._observer, "_poll_priority_wallets", None)
            if callable(priority):
                try:
                    priority()
                except Exception as e:
                    logger.debug("priority WS poll skipped: %s", e)
            self._sync_stats()
            return result

        self._observer._poll_shortlist = _patched_poll

        def _sync_timer():
            while self._observer and self._status.running:
                self._sync_stats()
                time.sleep(3.0)

        sync_thread = threading.Thread(target=_sync_timer, name="dydx-sync", daemon=True)
        sync_thread.start()

        try:
            self._observer.run()
        except Exception as e:
            logger.error("DydxEngine loop error: %s", e, exc_info=True)
            with self._lock:
                self._status.last_error = str(e)
        finally:
            with self._lock:
                self._status.running = False
            logger.info("DydxEngine thread exited")

    def _sync_stats(self) -> None:
        """Synchronise les stats de l'observer vers EngineStatus."""
        if not self._observer:
            return
        s = self._observer.stats
        observer_status = self._observer.get_status()
        observer_status["winning_trades"] = s.winning_trades
        observer_status["losing_trades"] = s.losing_trades
        with self._lock:
            self._status.iteration += 1
            self._status.wallets_in_shortlist = len(self._observer._shortlist)
            self._status.open_positions = len(self._observer._open_positions)
            self._status.net_pnl_usdt = float(observer_status.get("net_pnl_usdc", s.total_net_pnl_usdc) or 0.0)
            self._status.equity_usdt = float(observer_status.get("equity", s.equity) or 1000.0)
            self._status.total_trades = s.positions_closed
            self._status.winrate = s.winrate
            self._status.signals_refused = s.signals_refused
            self._status.stale_refused = s.stale_signals_refused
            self._status.fees_paid = s.total_fees_paid
            if self._observer._discovery_running:
                self._status.last_error = "DISCOVERY_RUNNING"
            elif self._status.last_error == "DISCOVERY_RUNNING":
                self._status.last_error = ""
            self._status.no_trade_reasons = dict(self._observer._no_trade_reasons)
            self._status.leader_exits = sum(
                1 for t in self._observer._closed_trades
                if t.get("reason") == "LEADER_EXIT"
            )
            self._status.observer_status = observer_status


# Singleton global -- thread-safe via .start()
_engine: Optional[DydxEngine] = None
_engine_lock = threading.Lock()


def get_engine() -> DydxEngine:
    """Retourne le singleton DydxEngine (cree si inexistant)."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = DydxEngine()
        return _engine


def start_engine() -> DydxEngine:
    """Demarre le moteur dYdX v4 (idempotent)."""
    engine = get_engine()
    engine.start()
    return engine
