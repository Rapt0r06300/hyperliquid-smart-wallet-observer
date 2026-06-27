"""
Observateur temps réel dYdX v4 — copy-trading paper uniquement.

Réglages calibrés sur l'analyse de 1,482,013 events Hyperliquid:
- Focus ETH-USD (seul coin prouvé rentable +$9.07 net, signal age moyen 3s)
- WebSocket temps réel → signal age <500ms (vs 47s en polling HL)
- Stop-loss -1.5% OBLIGATOIRE (HYPE SHORT = -$20 sans stop dans les logs HL)
- Take-profit +2.5%
- 2+ wallets dans la même direction = signal fort (pas besoin de 7+ wallets)
- Poll REST toutes les 5s en fallback (vs 47s dans HL → résout 47% NO_MATCHING)

RÈGLE ABSOLUE: PAPER-ONLY. Aucun ordre réel. Aucune clé privée.
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from hyper_smart_observer.dydx_v4.cluster_detector import (
    ClusterSignal,
    DydxClusterDetector,
    PositionEvent,
)
from hyper_smart_observer.dydx_v4.config import DydxV4Config
from hyper_smart_observer.dydx_v4.models import (
    NoTradeReason,
    PaperPosition,
    PaperTrade,
    PaperTradeStatus,
    PositionSide,
    SimulationMode,
)
from hyper_smart_observer.dydx_v4.rest_client import DydxIndexerRestClient, RestError
from hyper_smart_observer.dydx_v4.safety import assert_paper_only
from hyper_smart_observer.dydx_v4.edge_calculator import calculate_edge, MIN_EDGE_BPS
from hyper_smart_observer.dydx_v4.wallet_discovery import DydxWalletDiscovery, WalletScore
from hyper_smart_observer.dydx_v4.adaptive_exits import (
    ExitPlan,
    TrailingState,
    build_exit_plan,
    compute_atr,
    is_time_stop_hit,
)
from hyper_smart_observer.dydx_v4.fill_simulator import (
    DATA_SOURCE_FALLBACK,
    DATA_SOURCE_REAL,
    simulate_market_fill,
)
from hyper_smart_observer.dydx_v4.decision_log import DecisionLogger
from hyper_smart_observer.dydx_v4.market_regime import (
    REGIME_CHOPPY,
    REGIME_UNKNOWN,
    VOLUME_SPIKE,
    MarketContext,
    analyze_market_context,
    correlation_group,
    is_volume_spike,
    side_opposes_trend,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Réglages calibrés sur l'analyse empirique HL
# ─────────────────────────────────────────────

# Stop-loss: -1.0% (resserré) → coupe les pertes plus tôt
STOP_LOSS_PCT = 0.8

# Take-profit: +3.5% → R:R = 3.5:1
TAKE_PROFIT_PCT = 2.5

# Fenêtre de fraîcheur: signal vieux > 30s = NO_TRADE (REST polling réaliste)
# ETH avg signal age = 3s en WS, mais REST polling = 10-15s de latence
MAX_SIGNAL_AGE_MS = 30_000

# Intervalle de poll REST (fallback si WebSocket unavailable)
# 5s au lieu de 47s → résout 47% NO_MATCHING refusals
POLL_INTERVAL_S = 3.0

# Découverte shortlist: refresh toutes les 6 heures
DISCOVERY_REFRESH_S = 6 * 3600

# Timeout force-close: position perdante sans signal frais > N secondes → clôture préventive
# Empêche les pertes non surveillées quand le flux de signaux tarit
STALE_POSITION_TIMEOUT_S = 300.0

# Marchés prioritaires (ETH en premier d'après l'analyse)
FOCUS_MARKETS = [
    "BTC-USD", "ETH-USD", "SOL-USD", "DOGE-USD", "AVAX-USD", "LINK-USD",
    "SUI-USD", "XRP-USD", "LTC-USD", "BNB-USD", "NEAR-USD", "APT-USD",
    "ARB-USD", "OP-USD", "TIA-USD", "WLD-USD", "HYPE-USD",
    "TAO-USD", "SEI-USD", "HBAR-USD", "MORPHO-USD",
    "ZEC-USD", "VVV-USD", "MEGA-USD", "LIT-USD",
]

# Taille max paper par trade (USDT fictifs)
PAPER_NOTIONAL_USDT = 75.0

# Max positions paper ouvertes (edge-gated, peut ouvrir tant que PnL positif probable)
MAX_OPEN_PAPER_POSITIONS = 25

# Frais taker dYdX v4: 5 bps (0.05%)
TAKER_FEE_BPS = 5.0


@dataclass
class PaperPositionState:
    """État d'une position paper ouverte."""
    position_id: str
    market_id: str
    side: str           # "LONG" ou "SHORT"
    size: float         # en USDT fictifs
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    opened_at_ms: int
    cluster_id: str
    wallet_count: int
    fee_paid: float = 0.0
    simulation_mode: SimulationMode = SimulationMode.LIVE
    # — Selection Engine v2 —
    data_source: str = DATA_SOURCE_REAL      # REAL_INDEXER | LEGACY_ARTIFICIAL | FALLBACK_ESTIMATED
    entry_slippage_bps: float = 0.0          # slippage payé à l'entrée (honnête)
    max_holding_ms: int = 0                  # time-stop (0 = désactivé)
    exit_method: str = "FIXED_PCT_FALLBACK"  # ATR | FIXED_PCT_FALLBACK
    trailing: Optional[TrailingState] = None
    entry_edge_bps: float = 0.0
    market_regime: str = REGIME_UNKNOWN
    sizing_reason: str = ""
    initial_size: float = 0.0
    partial_tp_taken: bool = False
    first_take_profit_price: float = 0.0

    @property
    def unrealized_pnl(self) -> float:
        """PnL non réalisé (nécessite mark_price)."""
        return 0.0  # Calculé dans calculate_pnl()

    def calculate_pnl(self, mark_price: float) -> float:
        """
        PnL réalisé en USDT.
        size = notionnel USDT (ex: 50.0).
        LONG: (mark - entry) / entry * size_usdt
        SHORT: (entry - mark) / entry * size_usdt
        """
        if self.entry_price <= 0:
            return 0.0
        if self.side == "LONG":
            return (mark_price - self.entry_price) / self.entry_price * self.size
        else:
            return (self.entry_price - mark_price) / self.entry_price * self.size

    def unrealized_pnl_pct(self, mark_price: float) -> float:
        """PnL non réalisé en % de la taille notionnelle."""
        if self.entry_price <= 0:
            return 0.0
        if self.side == "LONG":
            return (mark_price - self.entry_price) / self.entry_price * 100.0
        else:
            return (self.entry_price - mark_price) / self.entry_price * 100.0

    def is_stop_loss_hit(self, mark_price: float) -> bool:
        if self.side == "LONG":
            return mark_price <= self.stop_loss_price
        else:
            return mark_price >= self.stop_loss_price

    def is_take_profit_hit(self, mark_price: float) -> bool:
        if self.side == "LONG":
            return mark_price >= self.take_profit_price
        else:
            return mark_price <= self.take_profit_price


@dataclass
class ObserverStats:
    """Statistiques de session paper trading."""
    session_id: str
    started_at_ms: int
    starting_balance_usdc: float = 1000.0
    total_signals_seen: int = 0
    signals_accepted: int = 0
    signals_refused: int = 0
    positions_opened: int = 0
    positions_closed: int = 0
    total_net_pnl_usdc: float = 0.0
    total_fees_paid: float = 0.0
    winning_trades: int = 0
    losing_trades: int = 0
    stale_signals_refused: int = 0
    no_matching_refused: int = 0
    stop_loss_exits: int = 0
    take_profit_exits: int = 0
    partial_take_profit_exits: int = 0
    trailing_stop_exits: int = 0
    time_stop_exits: int = 0
    demo_data: bool = False                  # True si AU MOINS un trade vient de données démo
    entry_fills_real: int = 0
    entry_fills_fallback: int = 0
    markets_traded: dict = field(default_factory=dict)
    disclaimer: str = (
        "PAPER SIMULATION ONLY. No real orders, no real money, no private keys. "
        "Positive paper PnL does not guarantee positive real PnL."
    )

    @property
    def winrate(self) -> float:
        total = self.winning_trades + self.losing_trades
        return self.winning_trades / total if total > 0 else 0.0

    @property
    def equity(self) -> float:
        return self.starting_balance_usdc + self.total_net_pnl_usdc

    def to_summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "equity_usdt": round(self.equity, 4),
            "net_pnl_usdt": round(self.total_net_pnl_usdc, 4),
            "winrate": f"{self.winrate:.0%}",
            "trades": self.positions_closed,
            "wins": self.winning_trades,
            "losses": self.losing_trades,
            "stop_loss_exits": self.stop_loss_exits,
            "take_profit_exits": self.take_profit_exits,
            "partial_take_profit_exits": self.partial_take_profit_exits,
            "fees_paid": round(self.total_fees_paid, 4),
            "signals_refused": self.signals_refused,
            "stale_refused": self.stale_signals_refused,
            "trailing_stop_exits": self.trailing_stop_exits,
            "time_stop_exits": self.time_stop_exits,
            "demo_data": self.demo_data,
            "entry_fills": {
                "real_orderbook": self.entry_fills_real,
                "fallback_estimated": self.entry_fills_fallback,
            },
            "disclaimer": self.disclaimer,
        }


class DydxLiveObserver:
    """
    Observateur paper trading dYdX v4.

    Architecture:
    1. Discovery: Cosmos LCD → shortlist des meilleurs wallets (background, non-bloquant)
    2. Poll REST toutes les 5s pour chaque wallet shortlisté
    3. Cluster detector: détecte 2+ wallets même direction dans 60s
    4. Paper entry: si cluster frais + marché prioritaire + pas max_open
    5. Paper exit: stop-loss (-1.5%), take-profit (+2.5%), ou timeout stale signal

    RÉGLAGES EMPIRIQUES:
    - ETH-USD en priorité (signal age 3s prouvé dans HL)
    - Stop-loss OBLIGATOIRE (HYPE sans stop = -$20)
    - Poll 5s au lieu de 47s (résout 47% NO_MATCHING)
    - 2 wallets min (pas 5+, contre-productif d'après l'analyse)
    - Stale position timeout 180s: ferme les positions perdantes sans signal frais

    PAPER-ONLY. AUCUN ORDRE RÉEL. AUCUNE CLÉ PRIVÉE.
    """

    DISCLAIMER = (
        "PAPER SIMULATION ONLY. READ-ONLY data. No real orders. No real money. "
        "No private keys. No deposits. No withdrawals."
    )

    def __init__(
        self,
        config: DydxV4Config,
        rest_client: DydxIndexerRestClient,
        cluster_detector: DydxClusterDetector,
        discovery: Optional[DydxWalletDiscovery] = None,
        initial_shortlist: Optional[list[WalletScore]] = None,
        poll_interval_s: float = POLL_INTERVAL_S,
        max_signal_age_ms: int = MAX_SIGNAL_AGE_MS,
        stop_loss_pct: float = STOP_LOSS_PCT,
        take_profit_pct: float = TAKE_PROFIT_PCT,
        focus_markets: Optional[list[str]] = None,
        ws_client: object = None,
        cosmos_client: object = None,
    ) -> None:
        assert_paper_only(config)

        self.config = config
        self.rest = rest_client
        self.cluster = cluster_detector
        self.discovery = discovery
        self.poll_interval_s = poll_interval_s
        self.max_signal_age_ms = max_signal_age_ms
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        # None → liste vide = TOUS les marchés autorisés (filtrés par liquidité/edge).
        # Évite le blocage "marché hors liste" quand les wallets tradent ailleurs.
        self.focus_markets = focus_markets if focus_markets is not None else []

        # Shortlist wallets à suivre
        self._shortlist: list[WalletScore] = initial_shortlist or []

        # Positions paper ouvertes
        self._open_positions: dict[str, PaperPositionState] = {}
        # Historique des trades fermés
        self._closed_trades: list[dict] = []

        # Stats session
        session_id = hashlib.sha256(f"session:{int(time.time()*1000)}".encode()).hexdigest()[:12]
        self.stats = ObserverStats(
            session_id=session_id,
            started_at_ms=int(time.time() * 1000),
            starting_balance_usdc=float(getattr(config, "starting_balance_usdc", 1000.0)),
        )

        # Cache prix oracle
        self._mark_prices: dict[str, float] = {}
        # Initialiser à "maintenant" pour éviter le run de découverte synchrone
        # au 1er tour — la découverte démarre en background dans run()
        self._last_discovery_ms: int = int(time.time() * 1000)
        self._running: bool = False
        # Flag background discovery en cours
        self._discovery_running: bool = False
        # Job B viral bot: snapshots des positions par wallet → détection CLOSE
        # {wallet_key: {pos_key: {market, side, size, entry_price}}}
        self._position_snapshots: dict[str, dict] = {}
        # Journal des NO_TRADE par raison (viral bot: "afficher les refus autant que les entrées")
        self._no_trade_reasons: dict[str, int] = {}
        # Compteur de ticks pour la simulation démo (cycles de rotation positions)
        self._market_context_cache: dict[str, tuple[int, MarketContext]] = {}
        self._recent_signal_sources: dict[tuple[str, str, str], int] = {}
        # PAPER-only session memory: market+side that recently lost must prove
        # stronger edge before the bot re-enters. This prevents repeated churn
        # on the same bad context without fabricating profitable outcomes.
        self._market_side_perf: dict[tuple[str, str], dict[str, float | int]] = {}
        self._decision_log = DecisionLogger(
            getattr(config, "decision_log_path", "logs/structured/decisions.jsonl"),
            enabled=bool(getattr(config, "decision_log_enabled", True)),
        )
        self._bootstrap_market_side_performance()

        # ── Scan rapide multi-wallets (opt-in, défaut OFF) ──────────────────
        # Si DYDX_FAST_SCANNER est activé: abonne les wallets chauds en WS et
        # poll immédiatement ceux qui bougent. Sinon self.fast_scan reste None et
        # le comportement REST historique est strictement inchangé. Tout est gardé
        # par try/except → un échec d'init retombe proprement sur le REST seul.
        self.fast_scan = None
        self._fast_scan_ws = None
        if getattr(config, "fast_scanner_enabled", False):
            try:
                from hyper_smart_observer.dydx_v4.fast_scan_integration import (
                    FastScanIntegration,
                )
                ws = ws_client
                if ws is None:
                    try:
                        from hyper_smart_observer.dydx_v4.ws_client import (
                            DydxIndexerWsClient,
                        )
                        ws = DydxIndexerWsClient(config.indexer_ws_url)
                    except Exception as e:
                        logger.warning("WS indisponible pour fast_scan: %s", e)
                        ws = None
                self.fast_scan = FastScanIntegration(
                    ws_client=ws,
                    max_age_ms=self.max_signal_age_ms,
                    hot_capacity=getattr(config, "fast_scanner_hot_capacity", 500),
                )
                self._fast_scan_ws = ws
                if cosmos_client is not None:
                    self.fast_scan.enable_cosmos_discovery(cosmos_client)
                if ws is not None and hasattr(ws, "start"):
                    ws.start()
                logger.info("fast_scan ACTIVÉ (READ-ONLY) ws=%s", ws is not None)
            except Exception as e:
                logger.warning("fast_scan init échec (ignoré, REST seul): %s", e)
                self.fast_scan = None

        # ── Politique de risque (opt-in, défaut OFF) ────────────────────────
        # Anti-churn (min-hold + cooldown), coupe-circuit, anti-scalper. Les exits
        # ATR (SL/TP/trailing/time-stop) sont déjà gérés par _check_exits.
        self._risk_breaker = None
        self._risk_last_close_ms: dict[str, int] = {}
        if getattr(config, "risk_policy_enabled", False):
            try:
                from hyper_smart_observer.dydx_v4.risk_policy import CircuitBreaker
                self._risk_breaker = CircuitBreaker(
                    max_consecutive_losses=getattr(config, "circuit_max_consecutive_losses", 4),
                    starting_equity=getattr(config, "starting_balance_usdc", 1000.0),
                    max_daily_drawdown_pct=getattr(config, "circuit_max_daily_drawdown_pct", 0.05),
                )
                logger.info("risk_policy ACTIVÉ (anti-churn, coupe-circuit, anti-scalper)")
            except Exception as e:
                logger.warning("risk_policy init échec (ignoré): %s", e)
                self._risk_breaker = None

        # ── Full Node Streaming (firehose tous fills + adresses, opt-in) ────
        # Si DYDX_FULL_NODE_STREAM=1 ET un node est joignable: démarre au run().
        # Le thread du flux ne fait que COLLECTER (thread-safe); la boucle
        # principale intègre (découverte + poll). Défaut OFF → rien ne change.
        self._stream_client = None
        self._stream_thread = None
        self._stream_lock = threading.Lock()
        self._stream_pending: list = []          # (ts, owner, clob_pair_id, direction)
        self._clob_to_market: dict = {}
        self._stream_window = None
        self._stream_stats = {"fills_seen": 0, "wallets_seen": 0, "consensus_detected": 0}
        self._stream_wallets_seen: set = set()
        try:
            from hyper_smart_observer.dydx_v4.stream_consensus import StreamFillWindow
            self._stream_window = StreamFillWindow(window_ms=getattr(config, "stream_window_ms", 4000))
        except Exception:
            self._stream_window = None
        if getattr(config, "full_node_stream_enabled", False):
            try:
                from hyper_smart_observer.dydx_v4.full_node_stream import FullNodeStreamClient
                self._stream_client = FullNodeStreamClient(
                    endpoint=getattr(config, "full_node_stream_endpoint", "127.0.0.1:9090"),
                    clob_pair_ids=list(range(0, 200)),  # tous les marchés
                    on_fill=self._on_stream_fill,
                    clob_to_market=None,
                )
                logger.info("Full node stream ARMÉ (%s)", getattr(config, "full_node_stream_endpoint", ""))
            except Exception as e:
                logger.warning("Full node stream init échec (ignoré, REST seul): %s", e)
                self._stream_client = None

    # ─────────────────────────────────────────────
        self._flow_monitor = None
        if getattr(config, "market_flow_enabled", False):
            try:
                from hyper_smart_observer.dydx_v4.market_flow import MarketFlowMonitor
                # Utiliser market_whitelist de la config, pas la constante FOCUS_MARKETS
                flow_markets = list(getattr(config, "market_whitelist", None) or FOCUS_MARKETS)
                self._flow_monitor = MarketFlowMonitor(
                    config.indexer_ws_url,
                    flow_markets,
                    window_ms=getattr(config, "stream_window_ms", 8000),
                )
                logger.info("market_flow ARME (v4_trades, READ-ONLY) %d marches", len(flow_markets))
            except Exception as e:
                logger.warning("market_flow init echec (ignore): %s", e)
                self._flow_monitor = None

    # Boucle principale (REST polling)
    # ─────────────────────────────────────────────
    def run(
        self,
        max_iterations: Optional[int] = None,
        discovery_refresh_s: float = DISCOVERY_REFRESH_S,
    ) -> ObserverStats:
        """
        Boucle principale paper trading.

        Args:
            max_iterations: arrêter après N itérations (None = infini)
            discovery_refresh_s: fréquence de refresh de la shortlist

        Returns:
            ObserverStats (paper only, jamais de vrais ordres)
        """
        assert_paper_only(self.config)
        self._running = True
        iteration = 0

        logger.info(
            "DydxLiveObserver START session=%s mode=%s | %s",
            self.stats.session_id, self.config.mode.value, self.DISCLAIMER
        )

        # Lancer la découverte en arrière-plan dès le démarrage (non-bloquant)
        if self.discovery:
            self._start_background_discovery()

        # Démarrer le full node stream (firehose) si armé — auto au lancement.
        if self._stream_client is not None and self._stream_thread is None:
            t = threading.Thread(
                target=self._stream_client.run_forever,
                name="dydx-fullnode-stream", daemon=True,
            )
            t.start()
            self._stream_thread = t
            logger.info("Full node stream DÉMARRÉ (firehose tous fills + adresses)")

        if self._flow_monitor is not None:
            self._flow_monitor.start()

        try:
            while self._running:
                if max_iterations and iteration >= max_iterations:
                    break

                iteration += 1
                now_ms = int(time.time() * 1000)

                # 1. Refresh shortlist si nécessaire (refresh périodique après init)
                if (
                    self.discovery
                    and not self._discovery_running
                    and now_ms - self._last_discovery_ms > discovery_refresh_s * 1000
                ):
                    self._start_background_discovery()
                    self._last_discovery_ms = now_ms

                # 2. Mettre à jour prix oracle
                self._refresh_market_prices()

                # 3. Vérifier stop-loss / take-profit sur positions ouvertes
                self._check_exits()

                # 3b. Fermer les positions sans signal frais depuis trop longtemps
                self._check_stale_positions()

                # 4. Poller les wallets shortlistés
                self._poll_shortlist()

                # 4b. Consensus TEMPS RÉEL (zéro REST) à partir des fills WS:
                #     Indexer PUBLIC (fast_scanner, ~500 wallets) ou node firehose.
                #     C'est le scan 'à mort de wallets' sans node.
                if self.fast_scan is not None or self._stream_client is not None:
                    try:
                        self._process_stream_consensus()
                    except Exception as e:
                        logger.debug("stream consensus: %s", e)

                # 5. Détecter clusters
                if self._flow_monitor is not None:
                    try:
                        sigs = self._flow_monitor.drain_and_detect(
                            getattr(self.config, "market_flow_min_volume_usdc", 5000.0),
                            getattr(self.config, "market_flow_min_imbalance", 0.55),
                            min_trades=int(getattr(self.config, "flow_min_trades", 3)),
                        )
                        from hyper_smart_observer.dydx_v4.market_flow import build_cluster_from_flow
                        for sig in sigs:
                            mark = self._mark_prices.get(sig.market)
                            if mark and mark > 0:
                                self._evaluate_cluster(build_cluster_from_flow(sig, mark, now_ms))
                    except Exception as e:
                        logger.debug("market_flow: %s", e)

                clusters = self.cluster.detect_clusters(
                    min_wallets=getattr(self.config, "consensus_min_wallets", 2)
                )

                # 6. Évaluer et exécuter signaux paper
                for cluster in clusters:
                    self._evaluate_cluster(cluster)

                # 7. Log de statut
                if iteration % 12 == 0:  # toutes les ~60s
                    logger.info(
                        "Observer status: equity=%.4f pnl=%+.4f positions=%d/%d "
                        "shortlist=%d signals_refused=%d discovery=%s",
                        self.stats.equity,
                        self.stats.total_net_pnl_usdc,
                        len(self._open_positions),
                        int(getattr(self.config, "max_open_paper_trades", MAX_OPEN_PAPER_POSITIONS)),
                        len(self._shortlist),
                        self.stats.signals_refused,
                        "running" if self._discovery_running else "idle",
                    )

                time.sleep(self.poll_interval_s)

        except KeyboardInterrupt:
            logger.info("Observer arrêté (KeyboardInterrupt)")
        finally:
            self._running = False
            if self._flow_monitor is not None:
                try:
                    self._flow_monitor.stop()
                except Exception:
                    pass
            logger.info(
                "Observer STOP: pnl=%+.4f trades=%d winrate=%.0f%% | %s",
                self.stats.total_net_pnl_usdc,
                self.stats.positions_closed,
                self.stats.winrate * 100,
                self.DISCLAIMER,
            )

        return self.stats

    # ─────────────────────────────────────────────
    # Refresh shortlist
    # ─────────────────────────────────────────────

    def _start_background_discovery(self) -> None:
        """Lancer la découverte de wallets dans un thread daemon (non-bloquant)."""
        if self._discovery_running:
            logger.debug("Discovery déjà en cours, skip")
            return
        self._discovery_running = True

        def _do():
            try:
                logger.info("Background discovery START")
                result = self.discovery.fast_discover(
                    n=getattr(self.config, "max_decision_wallets", 250)
                )
                self._shortlist = result.shortlisted
                self._last_discovery_ms = int(time.time() * 1000)
                if self.fast_scan is not None:
                    try:
                        self.fast_scan.track_shortlist(self._shortlist)
                    except Exception as e:
                        logger.debug("fast_scan track_shortlist: %s", e)
                    try:
                        # Découverte on-chain Cosmos (max d'adresses) en background
                        self.fast_scan.refresh_discovery()
                        # Élargir le shortlist de décision avec les wallets découverts
                        self._merge_harvester_into_shortlist()
                    except Exception as e:
                        logger.debug("fast_scan refresh_discovery: %s", e)
                logger.info(
                    "Background discovery DONE: %d wallets en %.1fs",
                    len(self._shortlist),
                    (result.finished_at_ms - result.started_at_ms) / 1000,
                )
            except Exception as e:
                logger.error("Background discovery error: %s", e)
            finally:
                self._discovery_running = False

        t = threading.Thread(target=_do, name="dydx-discovery", daemon=True)
        t.start()

    def _refresh_shortlist(self) -> None:
        """Refresh périodique (appelé par le timer 6h). Délègue au background thread."""
        self._start_background_discovery()

    def _check_stale_positions(self) -> None:
        """
        Fermer les positions paper si aucun signal frais depuis trop longtemps ET perte.

        Logique: si une position est ouverte depuis > STALE_POSITION_TIMEOUT_S secondes
        ET que la shortlist est vide (plus de wallets à suivre pour confirmer le signal)
        ET que la position est actuellement en perte → clôture préventive.

        Ceci évite de laisser des pertes s'accumuler quand le flux de données tarit.
        """
        if not self._open_positions:
            return

        now_ms = int(time.time() * 1000)
        timeout_ms = STALE_POSITION_TIMEOUT_S * 1000
        to_close: list[tuple[str, float]] = []

        for pos_key, pos in self._open_positions.items():
            age_ms = now_ms - pos.opened_at_ms
            if age_ms < timeout_ms:
                continue  # Position encore jeune, pas de timeout

            mark_price = self._mark_prices.get(pos.market_id)
            if not mark_price:
                continue  # Pas de prix oracle, on ne ferme pas à l'aveugle

            unrealized_pct = pos.unrealized_pnl_pct(mark_price)
            shortlist_empty = len(self._shortlist) == 0

            # Fermer si: timeout dépassé ET (shortlist vide OU perte > 0.5%)
            if shortlist_empty and unrealized_pct < 0:
                to_close.append((pos_key, mark_price))
            elif unrealized_pct < -0.5:
                # Perte > 0.5% avec position âgée → sortie avant stop-loss à -1.5%
                to_close.append((pos_key, mark_price))

        for pos_key, exit_price in to_close:
            logger.info(
                "STALE_TIMEOUT: Fermeture préventive position %s age=%.0fs",
                pos_key,
                (now_ms - self._open_positions[pos_key].opened_at_ms) / 1000
                if pos_key in self._open_positions else 0,
            )
            self._close_paper_position(pos_key, exit_price, "STALE_SIGNAL_TIMEOUT")

    # ─────────────────────────────────────────────
    # Prix oracle
    # ─────────────────────────────────────────────

    def _refresh_market_prices(self) -> None:
        """Récupérer les prix oracle pour les marchés focus.
        Si REST inaccessible et mode démo → utiliser des prix synthétiques avec drift.
        """
        try:
            markets = self.rest.get_markets()
            fetched_any = False
            for ticker, data in markets.get("markets", {}).items():
                try:
                    oracle = float(data.get("oraclePrice") or data.get("indexPrice") or 0)
                    if oracle > 0:
                        self._mark_prices[ticker] = oracle
                        fetched_any = True
                except (ValueError, TypeError):
                    pass
        except Exception as e:
            logger.debug("Market price refresh error: %s", e)
            # Donnees reelles uniquement: jamais de prix synthetiques injectes.

    def _poll_shortlist(self) -> None:
        """
        Job B du viral bot: poller les positions de chaque wallet shortlisté.
        """
        # Mode demo supprime: donnees reelles uniquement.
        self._poll_shortlist_live()

    def get_status(self) -> dict:
        """Retourne un snapshot thread-safe de l'état courant."""
        # PnL LATENT des positions ouvertes, marqué aux VRAIS prix courants.
        # Sans ça, le solde ne bougeait pas tant qu'une position restait ouverte
        # (c'était l'incohérence: position ouverte mais PnL figé).
        unrealized = 0.0
        for _pos in self._open_positions.values():
            _mk = self._mark_prices.get(_pos.market_id)
            if _mk and _mk > 0:
                unrealized += _pos.calculate_pnl(_mk)
        total_pnl = self.stats.total_net_pnl_usdc + unrealized
        status = {
            "running": self._running,
            "session_id": self.stats.session_id,
            "mode": self.config.mode.value if hasattr(self.config.mode, "value") else str(self.config.mode),
            "shortlist_size": len(self._shortlist),
            "open_positions": len(self._open_positions),
            "iteration": self.stats.total_signals_seen,
            "net_pnl_usdc": round(total_pnl, 4),
            "realized_pnl_usdc": round(self.stats.total_net_pnl_usdc, 4),
            "unrealized_pnl_usdc": round(unrealized, 4),
            "equity": round(self.stats.starting_balance_usdc + total_pnl, 4),
            "total_trades": self.stats.positions_closed,
            "winrate": f"{self.stats.winrate * 100:.2f}%",
            "winning_trades": self.stats.winning_trades,
            "losing_trades": self.stats.losing_trades,
            "signals_refused": self.stats.signals_refused,
            "stale_refused": self.stats.stale_signals_refused,
            "fees_paid": round(self.stats.total_fees_paid, 4),
            "discovery_running": self._discovery_running,
            "no_trade_reasons": dict(
                sorted(self._no_trade_reasons.items(), key=lambda x: -x[1])[:10]
            ),
            "leader_exits": sum(
                1 for t in self._closed_trades if t.get("reason") == "LEADER_EXIT"
            ),
            "disclaimer": self.DISCLAIMER,
        }
        if self.fast_scan is not None:
            try:
                status["fast_scan"] = self.fast_scan.stats()
            except Exception:
                pass
        if self._stream_client is not None or self.fast_scan is not None:
            try:
                status["stream"] = {
                    "fills_seen": self._stream_stats.get("fills_seen", 0),
                    "wallets_seen": self._stream_stats.get("wallets_seen", 0),
                    "consensus_detected": self._stream_stats.get("consensus_detected", 0),
                    "window": len(self._stream_window) if self._stream_window else 0,
                }
            except Exception:
                pass
        if self._flow_monitor is not None:
            try:
                status["market_flow"] = dict(self._flow_monitor.stats)
            except Exception:
                pass
        rest_cap = max(0, int(getattr(self.config, "rest_poll_cap", 50)))
        fast_stats = status.get("fast_scan", {}) if isinstance(status.get("fast_scan"), dict) else {}
        stream_stats = status.get("stream", {}) if isinstance(status.get("stream"), dict) else {}
        flow_stats = status.get("market_flow", {}) if isinstance(status.get("market_flow"), dict) else {}
        status["scan"] = {
            "discovery_wallets": len(self._shortlist),
            "ws_tracked": int(fast_stats.get("hot_wallets", 0) or 0),
            "rest_polled": min(len(self._shortlist), rest_cap),
            "rest_poll_cap": rest_cap,
            "flow_trades_seen": int(flow_stats.get("trades_seen", 0) or 0),
            "flow_signals": int(flow_stats.get("signals", 0) or 0),
            "stream_fills_seen": int(stream_stats.get("fills_seen", 0) or 0),
        }
        return status

    # ─────────────────────────────────────────────
    # Poll wallets shortlistés
    # ─────────────────────────────────────────────

    _rest_poll_offset: int = 0  # rotation index pour le poll REST

    def _poll_shortlist_live(self) -> None:
        """
        Job B du viral bot: poller les positions de chaque wallet shortlisté.
        Détecte les OPEN (nouveau cluster) et les CLOSE (position disparue).
        Suit les sorties du leader (LEADER_EXIT).
        ROTATION: à chaque cycle, on avance dans la liste pour couvrir tous
        les wallets, pas seulement les 50 premiers.
        """
        cap = max(1, int(getattr(self.config, "rest_poll_cap", 50)))
        total = len(self._shortlist)
        if total == 0:
            return
        # Rotation: avance de `cap` wallets à chaque cycle
        start = self._rest_poll_offset % total
        end = start + cap
        if end <= total:
            batch = self._shortlist[start:end]
        else:
            # Wrap around
            batch = self._shortlist[start:] + self._shortlist[:end - total]
        self._rest_poll_offset = end % total
        for wallet in batch:
            self._poll_one_wallet(wallet)

    def _poll_one_wallet(self, wallet) -> None:
        """
        Poll d'UN seul wallet (positions OPEN) + diff de snapshot → OPEN/CLOSE.

        Extrait de _poll_shortlist_live pour permettre le poll événementiel du
        scan rapide (poller un wallet dès qu'il trade en temps réel). Comportement
        strictement identique à l'ancienne boucle. READ-ONLY.
        """
        try:
            resp = self.rest.get_positions(
                address=wallet.address,
                subaccount_number=wallet.subaccount_number,
                status="OPEN",
                limit=50,
            )
            positions = resp.get("positions", [])
            wallet_key = f"{wallet.address}/{wallet.subaccount_number}"

            # ── Snapshot actuel ─────────────────────────────────────────
            current_snapshot: dict[str, dict] = {}
            for pos in positions:
                market = pos.get("market", "")
                side = pos.get("side", "")
                if not market or not side:
                    continue
                try:
                    sz = float(pos.get("size", 0) or 0)
                    ep = float(pos.get("entryPrice", 0) or 0)
                except (ValueError, TypeError):
                    continue
                pk = f"{market}:{side}"
                current_snapshot[pk] = {
                    "market": market, "side": side,
                    "size": sz, "entry_price": ep,
                }

            # ── Détection CLOSE: position présente avant, disparue maintenant ──
            prev_snapshot = self._position_snapshots.get(wallet_key, {})
            for pk, prev_pos in prev_snapshot.items():
                if pk not in current_snapshot:
                    self._handle_leader_close(
                        prev_pos["market"], prev_pos["side"], wallet.address
                    )

            # Sauvegarder le nouveau snapshot
            self._position_snapshots[wallet_key] = current_snapshot

            # ── Cluster detector (détection OPEN) ─────────────────────
            events = self.cluster.update_positions(
                address=wallet.address,
                positions_raw=positions,
                fetched_at_ms=int(time.time() * 1000),
            )
            for event in events:
                if event.event_type in ("OPEN", "ADD"):
                    self.stats.total_signals_seen += 1

        except RestError as e:
            if e.status_code != 404:
                logger.debug("Poll error %s: %s", wallet.address[:12], e)
        except Exception as e:
            logger.debug("Poll error %s: %s", wallet.address[:12], e)

    def _poll_priority_wallets(self) -> None:
        """
        Scan rapide (opt-in): poll immédiat des wallets qui viennent de trader.

        Le FastScanner (WS temps réel) signale les adresses ayant un fill frais ;
        on poll uniquement celles présentes dans la shortlist, ce qui réutilise
        toute la logique de cluster/close existante sans la modifier. READ-ONLY.
        """
        if self.fast_scan is None:
            return
        moved = self.fast_scan.wallets_that_just_moved()
        if not moved:
            return
        by_addr = {w.address: w for w in self._shortlist}
        for addr in moved:
            wallet = by_addr.get(addr)
            if wallet is not None:
                self._poll_one_wallet(wallet)

    def _merge_harvester_into_shortlist(self) -> None:
        """
        Élargir le shortlist de DÉCISION avec les wallets découverts (Cosmos /
        harvester), plafonné à max_decision_wallets. Plus de wallets suivis = plus
        de chances qu'un consensus de qualité apparaisse → des trades réels.
        READ-ONLY. Remplacement atomique de la liste (sûr vis-à-vis du poll).
        """
        if self.fast_scan is None:
            return
        cap = getattr(self.config, "max_decision_wallets", 60)
        try:
            top = self.fast_scan.harvester.top_for_scanner(n=cap)
        except Exception:
            return
        if not top:
            return
        merged = list(self._shortlist)
        existing = {w.address for w in merged}
        for addr, score in top:
            if len(merged) >= cap:
                break
            if addr in existing:
                continue
            try:
                merged.append(
                    WalletScore(address=addr, total_score=float(score), source="cosmos_harvest")
                )
            except Exception:
                continue
            existing.add(addr)
        self._shortlist = merged

    def _on_stream_fill(self, fill) -> None:
        """
        Callback du full node stream (exécuté dans le thread du flux).
        Thread-safe: on ne fait que COLLECTER l'adresse vue; l'intégration
        (découverte + poll) est faite dans la boucle principale.
        """
        owner = getattr(fill, "owner", None)
        if not owner:
            return
        from hyper_smart_observer.dydx_v4.stream_consensus import side_to_direction
        direction = side_to_direction(getattr(fill, "side", ""))
        clob = getattr(fill, "clob_pair_id", None)
        now = int(time.time() * 1000)
        with self._stream_lock:
            self._stream_pending.append((now, owner, clob, direction))
            self._stream_stats["fills_seen"] += 1
            self._stream_wallets_seen.add(owner)
            if len(self._stream_pending) > 50000:
                self._stream_pending = self._stream_pending[-25000:]

    def _process_stream_consensus(self) -> None:
        """
        Consensus TEMPS RÉEL (boucle principale, ZÉRO REST) à partir des fills WS —
        node (firehose) OU Indexer PUBLIC (fast_scanner, ~500 wallets en direct).
        Fenêtre glissante → K wallets distincts même marché+sens →
        ClusterSignal(origin='stream') → _evaluate_cluster (toutes les gates).
        C'est le scan 'à mort de wallets' SANS node.
        """
        if self._stream_window is None:
            return
        from hyper_smart_observer.dydx_v4.stream_consensus import (
            build_cluster_signal, detect_consensus, side_to_direction,
        )
        now_ms = int(time.time() * 1000)
        # 1) Fills du node (firehose) si actif
        with self._stream_lock:
            pending = self._stream_pending
            self._stream_pending = []
        for (ts, owner, clob, direction) in pending:
            self._stream_window.add(owner, clob, direction, ts)
        # 2) Fills WS PUBLICS (fast_scanner) — temps réel, SANS node
        if self.fast_scan is not None:
            try:
                for f in self.fast_scan.scanner.drain_fresh(limit=5000):
                    owner = getattr(f, "address", None)
                    market = getattr(f, "market_id", None)
                    if not owner or not market:
                        continue
                    self._stream_window.add(owner, market, side_to_direction(getattr(f, "side", "")), now_ms)
                    self._stream_stats["fills_seen"] += 1
                    self._stream_wallets_seen.add(owner)
            except Exception as e:
                logger.debug("scanner feed: %s", e)
        self._stream_stats["wallets_seen"] = len(self._stream_wallets_seen)
        # 3) Détection consensus + évaluation (réutilise toutes les gates)
        self._stream_window.prune(now_ms)
        if len(self._stream_window) == 0:
            return
        self._ensure_clob_market_map()
        min_w = getattr(self.config, "stream_consensus_min_wallets", 3)
        for sig in detect_consensus(self._stream_window.items(), min_w):
            key = sig.clob_pair_id
            market = key if isinstance(key, str) else self._clob_to_market.get(key)
            if not market:
                continue
            mark = self._mark_prices.get(market)
            if not mark or mark <= 0:
                continue
            self._stream_stats["consensus_detected"] += 1
            self._evaluate_cluster(build_cluster_signal(sig, market, mark, now_ms))

    def _ensure_clob_market_map(self) -> None:
        """Construire (une fois) le mapping clob_pair_id → ticker via l'Indexer."""
        if self._clob_to_market:
            return
        try:
            resp = None
            for meth in ("get_perpetual_markets", "get_markets"):
                fn = getattr(self.rest, meth, None)
                if callable(fn):
                    resp = fn()
                    break
            markets = resp.get("markets", resp) if isinstance(resp, dict) else {}
            if isinstance(markets, dict):
                for ticker, m in markets.items():
                    cid = m.get("clobPairId") or m.get("clob_pair_id") if isinstance(m, dict) else None
                    if cid is not None:
                        try:
                            self._clob_to_market[int(cid)] = ticker
                        except (TypeError, ValueError):
                            pass
        except Exception as e:
            logger.debug("clob market map: %s", e)

    def _handle_leader_close(self, market: str, side: str, leader_addr: str) -> None:
        """
        Fermer le paper trade correspondant quand un leader clôture sa position.

        C'est le mécanisme SELL du viral bot (Job B): quand la position
        disparaît du snapshot → fermer notre paper trade au prix oracle.

        PAPER-ONLY. Aucun ordre réel.
        """
        pos_key = f"{market}:{side}"
        if pos_key not in self._open_positions:
            return

        mark_price = self._mark_prices.get(market)
        if not mark_price or mark_price <= 0:
            return

        pos = self._open_positions[pos_key]
        # Anti-churn: hold minimum avant de fermer sur sortie leader (évite le
        # flip-flop 1-2 s). Défaut 5 s ; si risk_policy actif → min_hold_seconds.
        age_ms = int(time.time() * 1000) - pos.opened_at_ms
        min_hold_ms = 5_000
        if self._risk_breaker is not None:
            min_hold_ms = int(getattr(self.config, "min_hold_seconds", 5.0) * 1000)
        if age_ms < min_hold_ms:
            logger.debug("LEADER_EXIT skip (hold %dms < %dms): %s", age_ms, min_hold_ms, pos_key)
            return

        logger.info(
            "LEADER_EXIT: %s %s fermé par %s → paper close @ %.4f | PAPER-ONLY",
            side, market, leader_addr[:12], mark_price,
        )
        self._close_paper_position(pos_key, mark_price, "LEADER_EXIT")

    # ─────────────────────────────────────────────
    # Évaluation cluster → signal paper
    # ─────────────────────────────────────────────

    def _market_context(self, market: str) -> MarketContext:
        """Contexte candles 5m/1h public, cache court, jamais bloquant."""
        if not getattr(self.config, "trend_filter_enabled", True) and not getattr(
            self.config, "regime_detector_enabled", True
        ):
            return MarketContext(market_id=market)
        now_ms = int(time.time() * 1000)
        cached = self._market_context_cache.get(market)
        ttl_ms = int(float(getattr(self.config, "market_context_ttl_s", 60.0)) * 1000)
        if cached and now_ms - cached[0] <= ttl_ms:
            return cached[1]
        try:
            candles_5m = self.rest.get_candles(market, resolution="5MINS", limit=80)
        except Exception as e:
            logger.debug("market_context 5m unavailable %s: %s", market, e)
            candles_5m = None
        try:
            candles_1h = self.rest.get_candles(market, resolution="1HOUR", limit=80)
        except Exception as e:
            logger.debug("market_context 1h unavailable %s: %s", market, e)
            candles_1h = None
        ctx = analyze_market_context(
            market,
            candles_5m,
            candles_1h,
            atr_period=int(getattr(self.config, "atr_period", 14)),
            trend_min_move_pct=float(getattr(self.config, "trend_min_move_pct", 0.0015)),
            choppy_efficiency_max=float(getattr(self.config, "choppy_efficiency_max", 0.18)),
            choppy_atr_pct_min=float(getattr(self.config, "choppy_atr_pct_min", 0.001)),
        )
        self._market_context_cache[market] = (now_ms, ctx)
        return ctx

    def _cluster_imbalance(self, cluster: ClusterSignal) -> float:
        """Approximation conservative du desequilibre de flux pour volume spike."""
        strength = float(getattr(cluster, "signal_strength", 0.0) or 0.0)
        if strength <= 1.0:
            return max(-1.0, min(1.0, strength))
        return max(-1.0, min(1.0, strength / 100.0))

    def _is_strong_public_flow_paper_opportunity(self, cluster: ClusterSignal) -> tuple[bool, str]:
        """Return whether anonymous public flow is strong enough for tiny paper simulation.

        This is not wallet copy-trading proof. It is a read-only market-flow
        opportunity path used only when the flow is fresh, large, and imbalanced.
        """
        if not bool(getattr(self.config, "allow_strong_public_flow_paper_entries", False)):
            return False, "STRONG_PUBLIC_FLOW_DISABLED"
        age_ms = int(getattr(cluster, "signal_age_ms", 0) or 0)
        max_age = int(getattr(self.config, "strong_public_flow_max_age_ms", 4_000) or 4_000)
        if age_ms > max_age:
            return False, f"STRONG_PUBLIC_FLOW_STALE age={age_ms}>{max_age}"
        trades = int(getattr(cluster, "flow_trade_count", 0) or 0)
        min_trades = int(getattr(self.config, "strong_public_flow_min_trades", 8) or 8)
        if trades < min_trades:
            return False, f"STRONG_PUBLIC_FLOW_TRADES {trades}<{min_trades}"
        volume = float(getattr(cluster, "total_notional_usdc", 0.0) or 0.0)
        min_volume = float(getattr(self.config, "strong_public_flow_min_volume_usdc", 40_000.0) or 40_000.0)
        if volume < min_volume:
            return False, f"STRONG_PUBLIC_FLOW_VOLUME {volume:.0f}<{min_volume:.0f}"
        imbalance = abs(self._cluster_imbalance(cluster))
        min_imb = float(getattr(self.config, "strong_public_flow_min_imbalance", 0.72) or 0.72)
        if imbalance < min_imb:
            return False, f"STRONG_PUBLIC_FLOW_IMBALANCE {imbalance:.2f}<{min_imb:.2f}"
        large_trade = float(getattr(cluster, "flow_large_trade_usdc", 0.0) or 0.0)
        return True, (
            f"STRONG_PUBLIC_FLOW_OK volume={volume:.0f} trades={trades} "
            f"imbalance={imbalance:.2f} large_trade={large_trade:.0f} age={age_ms}ms"
        )

    def _leader_metrics_for_cluster(self, cluster: ClusterSignal) -> tuple[float, float, float, int, float, float]:
        """Retourne winrate, PF, expectancy, trades, recent_score, confidence du marche."""
        by_addr = {w.address: w for w in self._shortlist}
        rows: list[tuple[float, float, float, int, float, float]] = []
        for addr in getattr(cluster, "participating_wallets", []) or []:
            ws = by_addr.get(addr)
            if not ws:
                continue
            stats = getattr(ws, "market_stats", {}) or {}
            market_stats = stats.get(cluster.market_id)
            if market_stats:
                rows.append((
                    float(market_stats.get("winrate", 0.0) or 0.0),
                    float(market_stats.get("profit_factor", 1.0) or 1.0),
                    float(market_stats.get("expectancy_usdc", 0.0) or 0.0),
                    int(market_stats.get("trade_count", 0) or 0),
                    float(market_stats.get("recent_score", 1.0) or 1.0),
                    float(market_stats.get("confidence", 0.0) or 0.0),
                ))
                continue
            if getattr(ws, "trade_count", 0) > 0:
                rows.append((
                    float(getattr(ws, "winrate", 0.0) or 0.0),
                    float(getattr(ws, "profit_factor", 1.0) or 1.0),
                    float(getattr(ws, "net_pnl_usdc", 0.0) or 0.0)
                    / max(1, int(getattr(ws, "trade_count", 1) or 1)),
                    int(getattr(ws, "trade_count", 0) or 0),
                    float(getattr(ws, "recent_score", 1.0) or 1.0),
                    min(1.0, float(getattr(ws, "trade_count", 0) or 0) / 20.0),
                ))
        if not rows:
            return 0.0, 0.0, 0.0, -1, 1.0, 0.0
        n = len(rows)
        return (
            sum(r[0] for r in rows) / n,
            sum(r[1] for r in rows) / n,
            sum(r[2] for r in rows) / n,
            int(sum(r[3] for r in rows) / n),
            sum(r[4] for r in rows) / n,
            sum(r[5] for r in rows) / n,
        )

    def _consensus_recency_multiplier(self, cluster: ClusterSignal) -> tuple[float, str]:
        now_ms = int(time.time() * 1000)
        window = int(getattr(self.config, "consensus_recency_bonus_window_ms", 30_000))
        first_age = max(0, now_ms - int(getattr(cluster, "first_wallet_opened_ms", now_ms)))
        last_age = max(0, now_ms - int(getattr(cluster, "last_wallet_opened_ms", now_ms)))
        spread = max(0, int(getattr(cluster, "last_wallet_opened_ms", now_ms)) - int(getattr(cluster, "first_wallet_opened_ms", now_ms)))
        if last_age <= window and spread <= window:
            mult = float(getattr(self.config, "consensus_recency_edge_multiplier", 1.06))
            return mult, f"RECENT_CONSENSUS spread={spread}ms last_age={last_age}ms"
        return 1.0, ""

    def _precision_cluster_block_reason(self, cluster: ClusterSignal) -> Optional[str]:
        if not getattr(self.config, "precision_cluster_gate_enabled", True):
            return None
        if str(getattr(cluster, "origin", "rest") or "rest").lower() != "rest":
            return None
        wallet_count = int(getattr(cluster, "wallet_count", 0) or 0)
        threshold = max(1, int(getattr(self.config, "precision_cluster_wallet_threshold", 2) or 2))
        # A proven single leader is handled by leader/market stats and edge gates.
        # This precision gate targets weak 2-wallet micro-consensus patterns,
        # which logs showed were repeatedly over-traded.
        if wallet_count < 2 or wallet_count > threshold:
            return None
        now_ms = int(time.time() * 1000)
        first_ms = int(getattr(cluster, "first_wallet_opened_ms", now_ms) or now_ms)
        last_ms = int(getattr(cluster, "last_wallet_opened_ms", now_ms) or now_ms)
        spread_ms = max(0, last_ms - first_ms)
        last_age_ms = max(0, now_ms - last_ms)
        max_spread = max(0, int(getattr(self.config, "precision_cluster_max_spread_ms", 350) or 350))
        max_last_age = max(0, int(getattr(self.config, "precision_cluster_max_last_age_ms", 350) or 350))
        strength = abs(self._cluster_imbalance(cluster))
        min_strength = max(0.0, min(1.0, float(getattr(self.config, "precision_cluster_min_strength", 0.88) or 0.88)))
        failures: list[str] = []
        if spread_ms > max_spread:
            failures.append(f"spread={spread_ms}ms>{max_spread}ms")
        if last_age_ms > max_last_age:
            failures.append(f"last_age={last_age_ms}ms>{max_last_age}ms")
        if strength < min_strength:
            failures.append(f"strength={strength:.2f}<{min_strength:.2f}")
        if failures:
            return (
                f"PRECISION_CLUSTER_TOO_WEAK {cluster.market_id} {cluster.side} "
                f"wallets={wallet_count} " + " ".join(failures)
            )
        return None

    def _funding_penalty_bps(self, market: str, side: str) -> float:
        if not getattr(self.config, "funding_edge_enabled", True):
            return 0.0
        try:
            raw = self.rest.get_market(market)
            data = raw.get("markets", {}).get(market, raw.get("market", {})) or {}
            rate = float(data.get("nextFundingRate", 0) or 0)
        except Exception:
            return 0.0
        adverse = rate if side.upper() == "LONG" else -rate
        if adverse <= 0:
            return 0.0
        hours = float(getattr(self.config, "funding_edge_horizon_hours", 1.0))
        return adverse * hours * 10_000.0

    def _confluence_multiplier(self, cluster: ClusterSignal) -> tuple[float, str]:
        if not getattr(self.config, "confluence_enabled", True):
            return 1.0, ""
        now_ms = int(time.time() * 1000)
        origin = str(getattr(cluster, "origin", "rest") or "rest").lower()
        side = cluster.side.upper()
        window = int(getattr(self.config, "confluence_window_ms", 30_000))
        other_origins = ("flow", "stream") if origin == "rest" else ("rest",)
        for other in other_origins:
            ts = self._recent_signal_sources.get((cluster.market_id, side, other))
            if ts is not None and 0 <= now_ms - ts <= window:
                mult = float(getattr(self.config, "confluence_edge_multiplier", 1.10))
                return mult, "REST_FLOW_CONFLUENCE"
        self._recent_signal_sources[(cluster.market_id, side, origin)] = now_ms
        return 1.0, ""

    def _correlated_exposure_reason(self, market: str, side: str) -> Optional[str]:
        if not getattr(self.config, "correlation_gate_enabled", True):
            return None
        group = correlation_group(market)
        exposure = 0.0
        count = 0
        for pos in self._open_positions.values():
            if pos.side.upper() != side.upper():
                continue
            if correlation_group(pos.market_id) != group:
                continue
            exposure += abs(float(pos.size or 0.0))
            count += 1
        limit = float(getattr(self.config, "max_correlated_same_side", 5) or 5)
        if exposure > limit:
            return f"CORRELATED_EXPOSURE group={group} side={side} exposure={exposure:.2f}>{limit:.2f} count={count}"
        return None

    def _market_side_key(self, market: str, side: str) -> tuple[str, str]:
        return (str(market or ""), str(side or "").upper())

    def _bootstrap_market_side_performance(self) -> None:
        if not getattr(self.config, "market_side_performance_guard_enabled", True):
            return
        try:
            limit = int(getattr(self.config, "market_side_history_bootstrap_trades", 300))
        except (TypeError, ValueError):
            limit = 300
        limit = max(0, limit)
        if limit <= 0:
            return
        loaded = 0
        try:
            rows = self._decision_log.tail(limit=limit, event_type="PAPER_CLOSE")
        except Exception as e:
            logger.debug("market_side history bootstrap skipped: %s", e)
            return
        for row in rows:
            market = str(row.get("market_id") or "")
            side = str(row.get("side") or "")
            if not market or not side:
                continue
            try:
                net = float(row.get("net_pnl", row.get("trade_net_pnl", 0.0)) or 0.0)
            except (TypeError, ValueError):
                continue
            try:
                closed_at = int(row.get("closed_at_ms") or row.get("recorded_at_ms") or 0)
            except (TypeError, ValueError):
                closed_at = 0
            self._record_market_side_outcome(market, side, net, closed_at_ms=closed_at or None)
            loaded += 1
        if loaded:
            logger.info("market_side performance bootstrap: %d PAPER_CLOSE loaded", loaded)

    def _record_market_side_outcome(self, market: str, side: str, net_pnl: float, closed_at_ms: int | None = None) -> None:
        if not getattr(self.config, "market_side_performance_guard_enabled", True):
            return
        key = self._market_side_key(market, side)
        now_ms = int(closed_at_ms or time.time() * 1000)
        row = self._market_side_perf.setdefault(key, {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "consecutive_losses": 0,
            "net_pnl": 0.0,
            "last_closed_ms": 0,
            "last_loss_ms": 0,
            "last_win_ms": 0,
        })
        row["trades"] = int(row.get("trades", 0)) + 1
        row["net_pnl"] = float(row.get("net_pnl", 0.0)) + float(net_pnl)
        row["last_closed_ms"] = now_ms
        if net_pnl > 0:
            row["wins"] = int(row.get("wins", 0)) + 1
            row["consecutive_losses"] = 0
            row["last_win_ms"] = now_ms
        elif net_pnl < 0:
            row["losses"] = int(row.get("losses", 0)) + 1
            row["consecutive_losses"] = int(row.get("consecutive_losses", 0)) + 1
            row["last_loss_ms"] = now_ms

    def _market_side_performance_block_reason(self, market: str, side: str, edge_bps: float) -> Optional[str]:
        if not getattr(self.config, "market_side_performance_guard_enabled", True):
            return None
        row = self._market_side_perf.get(self._market_side_key(market, side))
        if not row:
            return None
        consecutive = int(row.get("consecutive_losses", 0) or 0)
        max_losses = max(1, int(getattr(self.config, "market_side_max_consecutive_losses", 2) or 2))
        if consecutive < max_losses:
            return None
        now_ms = int(time.time() * 1000)
        last_loss_ms = int(row.get("last_loss_ms", 0) or 0)
        try:
            cooldown_s = float(getattr(self.config, "market_side_loss_cooldown_seconds", 180.0))
        except (TypeError, ValueError):
            cooldown_s = 180.0
        cooldown_ms = max(0, int(cooldown_s * 1000))
        elapsed_ms = now_ms - last_loss_ms if last_loss_ms else cooldown_ms + 1
        if elapsed_ms < cooldown_ms:
            left_s = (cooldown_ms - elapsed_ms) / 1000.0
            return f"MARKET_SIDE_LOSS_COOLDOWN {market} {side} losses={consecutive} left={left_s:.1f}s"
        min_edge = float(getattr(self.config, "market_side_min_edge_after_loss_bps", 12.0) or 12.0)
        if edge_bps < min_edge:
            return f"MARKET_SIDE_EDGE_AFTER_LOSS {market} {side} edge={edge_bps:.1f}bps < {min_edge:.1f}bps"
        return None

    def _market_side_size_factor(self, market: str, side: str) -> tuple[float, str]:
        if not getattr(self.config, "market_side_performance_guard_enabled", True):
            return 1.0, "market_side_perf=off"
        row = self._market_side_perf.get(self._market_side_key(market, side))
        if not row:
            return 1.0, "market_side_perf=fresh"
        wins = int(row.get("wins", 0) or 0)
        losses = int(row.get("losses", 0) or 0)
        consecutive = int(row.get("consecutive_losses", 0) or 0)
        net = float(row.get("net_pnl", 0.0) or 0.0)
        if consecutive <= 0 and losses <= wins and net >= 0:
            return 1.0, f"market_side_perf=healthy wins={wins} losses={losses}"
        penalty = max(0.05, min(1.0, float(getattr(self.config, "market_side_size_penalty_after_loss", 0.50) or 0.50)))
        max_losses = max(1, int(getattr(self.config, "market_side_max_consecutive_losses", 2) or 2))
        if consecutive >= max_losses:
            penalty = min(penalty, 0.25)
        return penalty, f"market_side_perf=penalty:{penalty:.2f} wins={wins} losses={losses} streak={consecutive} net={net:.2f}"

    def _sizing_confidence_factor(self, ctx: MarketContext, cluster: ClusterSignal) -> tuple[float, str]:
        wallets = int(getattr(cluster, "wallet_count", 0) or 0)
        age_ms = int(getattr(cluster, "signal_age_ms", 999_999) or 999_999)
        regime = str(getattr(ctx, "regime", "UNKNOWN") or "UNKNOWN").upper()
        if wallets >= 2 and regime == "TRENDING" and age_ms < 5_000:
            return 1.0, "HIGH"
        if wallets >= 2 or regime == "TRENDING" or age_ms < 15_000:
            return 0.60, "MEDIUM"
        return 0.30, "LOW"

    def _dynamic_notional(self, edge_bps: float, ctx: MarketContext, cluster: ClusterSignal) -> tuple[float, str]:
        base = float(getattr(self.config, "paper_notional_base_usdc", PAPER_NOTIONAL_USDT))
        if not getattr(self.config, "dynamic_sizing_enabled", True):
            return base, "fixed sizing"
        mn = float(getattr(self.config, "paper_notional_min_usdc", 20.0))
        mx = min(100.0, float(getattr(self.config, "paper_notional_max_usdc", 100.0)))
        edge_full = max(1.0, float(getattr(self.config, "dynamic_sizing_edge_full_bps", 25.0)))
        edge_factor = 0.55 + 0.70 * max(0.0, min(1.0, edge_bps / edge_full))
        atr_high = max(0.0001, float(getattr(self.config, "dynamic_sizing_atr_high_pct", 0.03)))
        vol_factor = 1.0
        if ctx.atr_pct > 0:
            vol_factor = max(0.45, min(1.10, 1.0 - (ctx.atr_pct / atr_high) * 0.35))
        conviction = 0.80 + 0.08 * max(0, min(5, int(cluster.wallet_count)))
        if ctx.regime == "TRENDING":
            conviction += 0.08
        if self.stats.losing_trades > self.stats.winning_trades:
            conviction *= max(0.5, 1.0 - float(getattr(self.config, "dynamic_sizing_loss_penalty", 0.25)))
        raw_notional = base * edge_factor * vol_factor * conviction
        notional = max(mn, min(mx, raw_notional))
        flow_note = ""
        is_public_flow = (
            str(getattr(cluster, "origin", "rest") or "rest").lower() == "stream"
            and getattr(cluster, "flow_trade_count", None) is not None
            and not bool(getattr(self.config, "allow_market_flow_solo_entries", False))
        )
        if is_public_flow:
            factor = max(0.05, min(1.0, float(getattr(self.config, "strong_public_flow_notional_factor", 0.35) or 0.35)))
            notional = max(mn, min(mx, notional * factor))
            flow_note = f" strong_public_flow_micro={factor:.2f}"
        confidence_factor, confidence_label = self._sizing_confidence_factor(ctx, cluster)
        notional = max(mn, min(mx, notional * confidence_factor))
        perf_factor, perf_note = self._market_side_size_factor(cluster.market_id, cluster.side)
        notional = max(mn, min(mx, notional * perf_factor))
        return notional, (
            f"dynamic edge={edge_bps:.1f}bps edge_factor={edge_factor:.2f} "
            f"vol_factor={vol_factor:.2f} conviction={conviction:.2f}{flow_note} "
            f"confidence={confidence_label}:{confidence_factor:.2f} {perf_note}"
        )

    def _record_decision(self, event_type: str, payload: dict) -> None:
        try:
            payload = {
                "session_id": self.stats.session_id,
                "net_pnl_usdc": round(self.stats.total_net_pnl_usdc, 6),
                "equity_usdc": round(self.stats.equity, 6),
                "paper_only": True,
                "read_only": True,
                **payload,
            }
            self._decision_log.record(event_type, payload)
        except Exception as e:
            logger.debug("decision_log write skipped: %s", e)

    def get_recent_decisions(self, limit: int = 100, event_type: Optional[str] = None) -> list[dict]:
        return self._decision_log.tail(limit=limit, event_type=event_type)

    def get_refused_decisions(self, limit: int = 100) -> list[dict]:
        return self.get_recent_decisions(limit=limit, event_type="NO_TRADE")

    def _evaluate_cluster(self, cluster: ClusterSignal) -> None:
        """
        Évaluer un cluster et potentiellement ouvrir une position paper.

        Gates:
        1. Marché dans focus_markets
        2. Signal frais (< max_signal_age_ms)
        3. 2+ wallets
        4. Pas déjà une position ouverte sur ce marché
        5. Max positions paper non atteint
        6. Prix oracle disponible
        """
        self.stats.total_signals_seen += 1
        market = cluster.market_id

        # Gate 0a: Market name validation — reject garbage/invalid markets
        if not market or "/" in market or ":" in market or market.startswith("@"):
            self._refuse(f"INVALID_MARKET_NAME ({market})")
            return

        # Gate 0: Politique de risque (opt-in) — coupe-circuit, cooldown, anti-scalper
        if self._risk_breaker is not None:
            now_ms = int(time.time() * 1000)
            tripped, cb_reason = self._risk_breaker.status(now_ms)
            if tripped:
                self._refuse(cb_reason or "CIRCUIT_TRIPPED")
                return
            from hyper_smart_observer.dydx_v4.risk_policy import is_scalper, reopen_allowed
            if not reopen_allowed(
                self._risk_last_close_ms.get(market), now_ms,
                getattr(self.config, "reopen_cooldown_seconds", 0.0),
            ):
                self._refuse(f"REOPEN_COOLDOWN ({market})")
                return
            if is_scalper(
                getattr(cluster, "leader_median_hold_seconds", None),
                getattr(self.config, "scalper_min_hold_seconds", 0.0),
            ):
                self._refuse("SCALPER_LEADER_SKIPPED")
                return

        # Gate 1: Marché autorisé. focus_markets VIDE = TOUS les marchés autorisés.
        # La qualité est filtrée par la liquidité du carnet (honest fill) + l'edge,
        # pas par une liste blanche manuelle qui bloquait tout ("marché hors liste").
        if self.focus_markets and market not in self.focus_markets:
            self._refuse(f"MARKET_NOT_IN_FOCUS ({market})")
            return

        # Gate 2: Fraîcheur signal
        if market in getattr(self.config, "market_blacklist", set()):
            self._refuse(f"MARKET_BLACKLISTED ({market})")
            return

        if cluster.signal_age_ms > self.max_signal_age_ms:
            self.stats.stale_signals_refused += 1
            self._refuse(f"STALE_SIGNAL age={cluster.signal_age_ms}ms")
            return

        # Gate 3: Wallets minimum. Flow signals (momentum) utilisent un seuil
        # séparé car wallet_count=1 (c'est du flux, pas du consensus wallet).
        _is_flow = getattr(cluster, "origin", "rest") == "stream"
        _is_public_market_flow = _is_flow and getattr(cluster, "flow_trade_count", None) is not None
        if _is_public_market_flow and not bool(getattr(self.config, "allow_market_flow_solo_entries", False)):
            strong_ok, strong_reason = self._is_strong_public_flow_paper_opportunity(cluster)
            if not strong_ok:
                self._refuse(f"PUBLIC_FLOW_CONTEXT_ONLY {strong_reason}")
                return
            setattr(cluster, "_paper_opportunity_source", "STRONG_PUBLIC_FLOW")
            setattr(cluster, "_paper_opportunity_reason", strong_reason)
        if _is_flow:
            _min_w = int(getattr(self.config, "flow_consensus_min_wallets", 1))
        else:
            _min_w = getattr(self.config, "consensus_min_wallets", 2)
        if cluster.wallet_count < _min_w:
            self._refuse(f"NOT_ENOUGH_WALLETS count={cluster.wallet_count}/{_min_w}")
            return

        # Gate 3b: leaders PROUVÉS gagnants (sélectivité extrême — opt-in, graceful).
        # On n'agit que si assez de wallets du consensus ont un historique prouvé.
        # Ignoré tant qu'aucun wallet n'a de métrique (n'inventons pas, ne bloquons
        # pas tout): le gate s'active dès que l'enrichissement fournit des winrate/PF.
        if getattr(self.config, "require_proven_leaders", False) and getattr(cluster, "origin", "rest") != "stream":
            from hyper_smart_observer.dydx_v4.leader_quality import (
                LeaderThresholds, any_track_record, count_proven,
            )
            if any_track_record(self._shortlist):
                score_by_addr = {w.address: w for w in self._shortlist}
                th = LeaderThresholds(
                    min_winrate=getattr(self.config, "min_leader_winrate", 0.45),
                    min_profit_factor=getattr(self.config, "min_leader_profit_factor", 1.3),
                    min_trades=getattr(self.config, "min_leader_trades", 15),
                )
                proven = count_proven(cluster.participating_wallets, score_by_addr, th)
                if proven < getattr(self.config, "min_proven_in_consensus", 1):
                    self._refuse(f"LEADERS_NOT_PROVEN proven={proven}")
                    return

        # Gate 4: Position existante — pyramide autorisée si edge frais et fort
        pos_key = f"{market}:{cluster.side}"
        if pos_key in self._open_positions:
            existing = self._open_positions[pos_key]
            age_s = (int(time.time() * 1000) - existing.opened_at_ms) / 1000
            # Pyramid: autorisé si signal frais (<10s) ET position <5min ET pas plus de 2 adds
            _pyramid_count = getattr(existing, "_pyramid_count", 0)
            if cluster.signal_age_ms > 10_000 or age_s > 300 or _pyramid_count >= 2:
                self._refuse(f"ALREADY_IN_POSITION {pos_key}")
                return
            # On laisse passer: la position sera renforcée (on ouvre une 2e entrée indépendante)
            pos_key = f"{market}:{cluster.side}:add{_pyramid_count + 1}"
            logger.info("PYRAMID ADD %s %s (add #%d) | PAPER-ONLY", cluster.side, market, _pyramid_count + 1)

        # Gate 5: Max positions
        max_open_positions = int(getattr(self.config, "max_open_paper_trades", MAX_OPEN_PAPER_POSITIONS))
        if len(self._open_positions) >= max_open_positions:
            self._refuse(f"MAX_OPEN_REACHED {len(self._open_positions)}/{max_open_positions}")
            return

        # Gate 6: Prix disponible
        mark_price = self._mark_prices.get(market)
        if not mark_price or mark_price <= 0:
            self._refuse(f"NO_ORACLE_PRICE {market}")
            return

        market_ctx = self._market_context(market)
        sizing_notes: list[str] = []
        opportunity_source = str(getattr(cluster, "_paper_opportunity_source", "") or "")
        opportunity_reason = str(getattr(cluster, "_paper_opportunity_reason", "") or "")
        if opportunity_source:
            sizing_notes.append(f"opportunity={opportunity_source}")
            if opportunity_reason:
                sizing_notes.append(opportunity_reason)
        market_edge_multiplier = 1.0
        if market_ctx.has_data:
            sizing_notes.append(f"regime={market_ctx.regime}")
            if getattr(self.config, "regime_detector_enabled", True) and market_ctx.regime == REGIME_CHOPPY:
                self._refuse(f"CHOPPY_MARKET {market} atr_pct={market_ctx.atr_pct:.4f}")
                return
            if getattr(self.config, "trend_filter_enabled", True) and side_opposes_trend(cluster.side, market_ctx):
                self._refuse(
                    f"TREND_OPPOSITION {market} side={cluster.side} "
                    f"5m={market_ctx.trend_5m} 1h={market_ctx.trend_1h}"
                )
                return
            if getattr(self.config, "volume_spike_enabled", True) and is_volume_spike(
                market_ctx,
                self._cluster_imbalance(cluster),
                min_zscore=float(getattr(self.config, "volume_spike_zscore_min", 2.0)),
                min_imbalance=float(getattr(self.config, "volume_spike_imbalance_min", 0.62)),
            ):
                market_edge_multiplier *= float(getattr(self.config, "volume_spike_edge_multiplier", 1.08))
                sizing_notes.append(VOLUME_SPIKE)

        corr_reason = self._correlated_exposure_reason(market, cluster.side)
        if corr_reason:
            self._refuse(corr_reason)
            return

        # Flow trade count safety net — detect_flow_signals() already filters,
        # but clusters injected directly (e.g. tests) must also be validated.
        if getattr(cluster, "origin", "rest") == "stream" and getattr(cluster, "flow_trade_count", None) is not None:
            _ftc = int(cluster.flow_trade_count or 0)
            _min_ft = int(getattr(self.config, "flow_min_trades", 3))
            if _ftc < _min_ft:
                self._refuse(f"FLOW_MIN_TRADES {market} trades={_ftc} < min={_min_ft}")
                return
            logger.debug(
                "FLOW signal %s %s: volume=%.0f trades=%d imbalance=%.2f",
                cluster.market_id, cluster.side,
                cluster.total_notional_usdc, _ftc,
                getattr(cluster, "signal_strength", 0),
            )

        # Gate 7: Edge net positif après coûts (viral bot edge formula)
        # leader_winrate/pf depuis wallet scores si disponibles
        edge_remaining_bps = float(getattr(self.config, "min_edge_bps", MIN_EDGE_BPS)) + 1.0
        avg_wr = 0.0
        avg_pf = 0.0
        avg_exp = 0.0
        n_sc = 0
        for ws in self._shortlist:
            if hasattr(ws, "winrate") and ws.winrate > 0:
                avg_wr += ws.winrate
                avg_pf += getattr(ws, "profit_factor", 1.0)
                avg_exp += getattr(ws, "net_pnl_usdc", 0.0) / max(1, getattr(ws, "trade_count", 1))
                n_sc += 1
        if n_sc > 0:
            avg_wr /= n_sc
            avg_pf /= n_sc
            avg_exp /= n_sc
        else:
            n_sc = -1  # sentinel: skip edge gate

        market_wr, market_pf, market_exp, market_trades, recent_score, leader_conf = self._leader_metrics_for_cluster(cluster)
        recency_mult, recency_note = self._consensus_recency_multiplier(cluster)
        confluence_mult, confluence_note = self._confluence_multiplier(cluster)
        funding_penalty_bps = self._funding_penalty_bps(market, cluster.side)
        market_edge_multiplier *= recency_mult * confluence_mult
        if recent_score > 0 and market_trades > 0:
            market_edge_multiplier *= max(0.92, min(1.08, recent_score))
        if leader_conf > 0:
            market_edge_multiplier *= 0.90 + 0.10 * min(1.0, leader_conf)
        if market_trades >= 0:
            avg_wr, avg_pf, avg_exp, n_sc = market_wr, market_pf, market_exp, 1
            sizing_notes.append(
                f"leader_market trades={market_trades} wr={avg_wr:.2f} pf={avg_pf:.2f} exp={avg_exp:.2f}"
            )
        if recency_note:
            sizing_notes.append(recency_note)
        if confluence_note:
            sizing_notes.append(confluence_note)
        if funding_penalty_bps > 0:
            sizing_notes.append(f"funding_penalty={funding_penalty_bps:.1f}bps")

        # Le chemin STREAM saute cette gate: le consensus de K wallets EST le
        # signal d'edge (on n'a pas de winrate par leader sur des fills temps réel).
        if n_sc >= 0 and getattr(cluster, "origin", "rest") != "stream":
            delay_ms = max(0, int(time.time() * 1000) - cluster.last_wallet_opened_ms)
            edge = calculate_edge(
                signal_age_ms=cluster.signal_age_ms,
                wallet_count=cluster.wallet_count,
                leader_winrate=avg_wr,
                leader_profit_factor=avg_pf,
                leader_trade_count=market_trades if market_trades >= 0 else 0,
                leader_expectancy_usdc=avg_exp,
                paper_notional_usdc=float(getattr(self.config, "paper_notional_base_usdc", PAPER_NOTIONAL_USDT)),
                spread_bps=3.0,
                slippage_bps=1.0,
                fee_bps=10.0,
                delay_ms=delay_ms,
                funding_penalty_bps=funding_penalty_bps,
                market_edge_multiplier=market_edge_multiplier,
                min_edge_bps=float(getattr(self.config, "min_edge_bps", MIN_EDGE_BPS)),
                market_context=market_ctx,
            )
            if not edge.accepted:
                self._refuse(f"EDGE_INSUFFICIENT ({edge.reject_reason})")
                return
            edge_remaining_bps = edge.edge_remaining_bps

        if getattr(cluster, "origin", "rest") == "stream" and n_sc < 0:
            edge_remaining_bps = max(
                edge_remaining_bps,
                float(getattr(self.config, "min_edge_bps", MIN_EDGE_BPS))
                + 10.0 * max(0.0, min(1.0, self._cluster_imbalance(cluster))),
            )

        precision_block_reason = self._precision_cluster_block_reason(cluster)
        if precision_block_reason:
            self._refuse(precision_block_reason)
            return

        perf_block_reason = self._market_side_performance_block_reason(market, cluster.side, edge_remaining_bps)
        if perf_block_reason:
            self._refuse(perf_block_reason)
            return

        paper_notional, sizing_note = self._dynamic_notional(edge_remaining_bps, market_ctx, cluster)
        sizing_notes.append(sizing_note)

        # Gate 8: Fill HONNÊTE depuis le carnet — jamais au mid
        # (un paper qui fill au mid surestime le PnL de 30-100%)
        entry_price, entry_slippage_bps, fill_source = self._honest_entry_price(
            market, cluster.side, paper_notional, mark_price
        )
        if fill_source in {"SPREAD_TOO_WIDE", "BOOK_TOO_THIN"}:
            self._refuse(f"{fill_source} {market}")
            return
        if entry_price is None or entry_price <= 0:
            # Repli PROPRE: pas de carnet exploitable → fill au prix mark réel
            # pénalisé (demi-spread + slippage estimés), au lieu de tout bloquer.
            # Réaliste (jamais au mid), et le PnL reste marké aux vrais prix.
            try:
                from hyper_smart_observer.dydx_v4.paper_fill import simple_mark_fill
                entry_price = simple_mark_fill(cluster.side, mark_price, 3.0, 5.0)
                entry_slippage_bps = 4.0
                fill_source = "mark_simple_fallback"
            except Exception:
                self._refuse(f"NO_HONEST_FILL {market}")
                return

        # Exits adaptatifs: ATR si candles disponibles, sinon % fixes (fallback)
        plan = self._build_position_exit_plan(market, cluster.side, entry_price)
        stop_price, tp_price = plan.stop_price, plan.take_profit_price

        # Calcul frais
        _notional = float(paper_notional)
        fee = _notional * (TAKER_FEE_BPS / 10_000)
        size_notional = _notional  # en USDT fictifs

        # Ouvrir position paper
        position_id = hashlib.sha256(
            f"paper:{market}:{cluster.side}:{cluster.cluster_id}".encode()
        ).hexdigest()[:16]

        # Breakeven stop: calcul des prix trigger/stop
        be_trigger_price = 0.0
        be_stop_price = 0.0
        if getattr(self.config, "breakeven_stop_enabled", True) and plan.atr > 0:
            be_trigger_mult = float(getattr(self.config, "breakeven_trigger_atr_mult", 1.5))
            be_offset_mult = float(getattr(self.config, "breakeven_offset_atr_mult", 0.1))
            if cluster.side.upper() == "LONG":
                be_trigger_price = entry_price + be_trigger_mult * plan.atr
                be_stop_price = entry_price + be_offset_mult * plan.atr
            else:
                be_trigger_price = entry_price - be_trigger_mult * plan.atr
                be_stop_price = entry_price - be_offset_mult * plan.atr

        trailing = (
            TrailingState(
                side=cluster.side,
                trail_distance=plan.trail_distance,
                trail_arm_price=plan.trail_arm_price,
                breakeven_trigger_price=be_trigger_price,
                breakeven_stop_price=be_stop_price,
                entry_price=entry_price,
                atr=plan.atr,
                trail_tighten_distance=plan.trail_tighten_distance,
                momentum_pullback_distance=plan.momentum_pullback_distance,
            )
            if plan.trail_distance > 0 else None
        )

        pos = PaperPositionState(
            position_id=position_id,
            market_id=market,
            side=cluster.side,
            size=size_notional,
            entry_price=entry_price,
            stop_loss_price=stop_price,
            take_profit_price=tp_price,
            opened_at_ms=int(time.time() * 1000),
            cluster_id=cluster.cluster_id,
            wallet_count=cluster.wallet_count,
            fee_paid=fee,
            simulation_mode=self.config.mode,
            data_source=fill_source,
            entry_slippage_bps=entry_slippage_bps,
            max_holding_ms=plan.max_holding_ms,
            exit_method=plan.method,
            trailing=trailing,
            entry_edge_bps=edge_remaining_bps,
            market_regime=market_ctx.regime,
            sizing_reason=" | ".join(sizing_notes),
            initial_size=size_notional,
            first_take_profit_price=tp_price,
        )

        # Comptabilité honnête des sources de données
        if fill_source == DATA_SOURCE_REAL:
            self.stats.entry_fills_real += 1
        else:
            self.stats.entry_fills_fallback += 1

        self._open_positions[pos_key] = pos
        self.stats.positions_opened += 1
        self.stats.signals_accepted += 1
        self.stats.total_fees_paid += fee
        self.stats.total_net_pnl_usdc -= fee  # Frais d'entrée déduits immédiatement

        markets_key = f"{market}:{cluster.side}"
        self.stats.markets_traded[markets_key] = (
            self.stats.markets_traded.get(markets_key, 0) + 1
        )

        logger.info(
            "PAPER OPEN %s %s @ %.4f SL=%.4f TP=%.4f wallets=%d cluster=%s | PAPER-ONLY",
            cluster.side, market, mark_price, stop_price, tp_price,
            cluster.wallet_count, cluster.cluster_id[:8],
        )
        self._record_decision("PAPER_OPEN", {
            "position_id": position_id,
            "market_id": market,
            "side": cluster.side,
            "entry_price": entry_price,
            "mark_price": mark_price,
            "size": size_notional,
            "fee_paid": fee,
            "wallet_count": cluster.wallet_count,
            "cluster_id": cluster.cluster_id,
            "edge_remaining_bps": edge_remaining_bps,
            "market_regime": market_ctx.regime,
            "sizing_reason": pos.sizing_reason,
            "data_source": fill_source,
            "entry_slippage_bps": entry_slippage_bps,
            "opportunity_source": opportunity_source or "WALLET_CLUSTER",
            "opportunity_reason": opportunity_reason,
            "flow_trade_count": getattr(cluster, "flow_trade_count", None),
            "flow_total_notional_usdc": getattr(cluster, "total_notional_usdc", None),
            "flow_large_trade_usdc": getattr(cluster, "flow_large_trade_usdc", None),
            "flow_imbalance": self._cluster_imbalance(cluster),
            "paper_only": True,
        })

    # ─────────────────────────────────────────────
    # Vérification exits (stop-loss / take-profit)
    # ─────────────────────────────────────────────

    def _check_exits(self) -> None:
        """
        Vérifier les exits sur toutes les positions ouvertes.
        Ordre: STOP_LOSS → TAKE_PROFIT → TRAILING_STOP → TIME_STOP.
        (LEADER_EXIT est géré séparément par _handle_leader_close.)
        """
        to_close: list[tuple[str, float, str]] = []
        now_ms = int(time.time() * 1000)

        for pos_key, pos in self._open_positions.items():
            mark_price = self._mark_prices.get(pos.market_id)
            if not mark_price:
                continue
            # Breakeven stop: upgrade SL to entry+micro-profit once armed
            if (pos.trailing is not None
                    and pos.trailing.breakeven_armed
                    and not pos.trailing.armed):
                if pos.stop_loss_price != pos.trailing.breakeven_stop_price:
                    pos.stop_loss_price = pos.trailing.breakeven_stop_price
                    logger.info(
                        "BREAKEVEN UPGRADE %s %s SL=%.6f | PAPER-ONLY",
                        pos.side, pos.market_id, pos.stop_loss_price,
                    )
            if pos.is_stop_loss_hit(mark_price):
                to_close.append((pos_key, mark_price, "STOP_LOSS"))
                continue
            if pos.is_take_profit_hit(mark_price):
                if self._partial_take_profit_position(pos_key, mark_price):
                    continue
                to_close.append((pos_key, mark_price, "TAKE_PROFIT"))
                continue
            if pos.trailing is not None:
                trigger_price = pos.trailing.update(mark_price)
                if trigger_price is not None:
                    to_close.append((pos_key, trigger_price, "TRAILING_STOP"))
                    continue
            if is_time_stop_hit(pos.opened_at_ms, now_ms, pos.max_holding_ms):
                to_close.append((pos_key, mark_price, "TIME_STOP"))

        for pos_key, exit_price, reason in to_close:
            self._close_paper_position(pos_key, exit_price, reason)

    def _honest_entry_price(
        self,
        market: str,
        side: str,
        notional_usdc: float,
        mark_price: float,
    ) -> tuple[Optional[float], float, str]:
        """
        Prix d'entrée HONNÊTE: (prix, slippage_bps, data_source).

        1. Carnet réel (Indexer) → VWAP en traversant le spread.
           Profondeur réelle insuffisante → refus dur (None).
        2. Carnet inaccessible (réseau) → fallback estimé: mid PÉNALISÉ
           de spread/2 + slippage + latence, étiqueté FALLBACK_ESTIMATED.
        """
        order_side = "BUY" if side.upper() == "LONG" else "SELL"

        try:
            raw = self.rest.get_orderbook(market)
            res = simulate_market_fill(
                raw, order_side, notional_usdc, data_source=DATA_SOURCE_REAL
            )
            if res.ok:
                max_spread_bps = float(getattr(self.config, "max_spread_bps", 8.0))
                if res.spread_bps > max_spread_bps:
                    logger.info(
                        "HONEST_FILL refus %s: spread %.2fbps > %.2fbps",
                        market,
                        res.spread_bps,
                        max_spread_bps,
                    )
                    return None, res.slippage_bps, "SPREAD_TOO_WIDE"
                return res.fill_price, res.slippage_bps, DATA_SOURCE_REAL
            if "INSUFFICIENT_DEPTH" in res.reason or "NO_ORDERBOOK" in res.reason:
                # Profondeur réelle insuffisante → on REFUSE, pas de fantasme
                logger.info("HONEST_FILL refus %s: %s", market, res.reason)
                return None, 0.0, "BOOK_TOO_THIN"
            if "CROSSED_BOOK" in res.reason:
                logger.info("HONEST_FILL refus %s: %s", market, res.reason)
                return None, 0.0, "SPREAD_TOO_WIDE"
        except Exception as e:  # réseau KO → fallback pénalisé
            logger.debug("Orderbook indisponible %s: %s", market, e)

        penalty_bps = (
            self.config.estimated_spread_bps / 2.0
            + self.config.estimated_slippage_bps
            + self.config.estimated_latency_bps
        )
        if side.upper() == "LONG":
            price = mark_price * (1 + penalty_bps / 10_000)
        else:
            price = mark_price * (1 - penalty_bps / 10_000)
        return price, penalty_bps, DATA_SOURCE_FALLBACK

    def _build_position_exit_plan(
        self, market: str, side: str, entry_price: float
    ) -> ExitPlan:
        """Plan de sortie ATR (candles 1h) + funding; fallback % fixes."""
        atr = 0.0
        funding_hourly = 0.0
        if True:
            try:
                candles_raw = self.rest.get_candles(
                    market, resolution="1HOUR", limit=max(48, self.config.atr_period * 3)
                )
                atr = compute_atr(
                    candles_raw.get("candles", []), period=self.config.atr_period
                )
            except Exception as e:
                logger.debug("Candles indisponibles %s: %s — fallback %% fixes", market, e)
            try:
                m_raw = self.rest.get_market(market)
                m_data = m_raw.get("markets", {}).get(market, m_raw.get("market", {})) or {}
                rate = float(m_data.get("nextFundingRate", 0) or 0)
                # Adverse si NOUS paierions: LONG paie quand rate>0, SHORT quand rate<0
                funding_hourly = rate if side.upper() == "LONG" else -rate
            except Exception:
                funding_hourly = 0.0

        return build_exit_plan(
            entry_price,
            side,
            atr,
            stop_mult=self.config.atr_stop_mult,
            tp_mult=self.config.atr_take_profit_mult,
            trail_mult=self.config.atr_trail_mult,
            max_holding_hours=self.config.max_holding_hours,
            funding_rate_hourly=funding_hourly,
            funding_adverse_threshold=self.config.funding_adverse_threshold_hourly,
            fallback_stop_pct=self.stop_loss_pct,
            fallback_tp_pct=self.take_profit_pct,
        )

    def _partial_take_profit_position(self, pos_key: str, exit_price: float) -> bool:
        """Encaisser TP1 partiel et laisser courir TP2 pour les exits ATR."""
        pos = self._open_positions.get(pos_key)
        if pos is None:
            return False
        if not getattr(self.config, "partial_tp_enabled", True):
            return False
        if pos.partial_tp_taken or pos.exit_method != "ATR":
            return False
        frac = max(0.05, min(0.95, float(getattr(self.config, "partial_tp_fraction", 0.50))))
        close_size = pos.size * frac
        if close_size <= 0 or pos.entry_price <= 0:
            return False
        if pos.side == "LONG":
            gross = (exit_price - pos.entry_price) / pos.entry_price * close_size
        else:
            gross = (pos.entry_price - exit_price) / pos.entry_price * close_size
        exit_fee = close_size * (TAKER_FEE_BPS / 10_000)
        net = gross - exit_fee
        self.stats.total_net_pnl_usdc += net
        self.stats.total_fees_paid += exit_fee
        self.stats.partial_take_profit_exits += 1

        remaining = pos.size - close_size
        entry_fee_remaining = pos.fee_paid * (remaining / pos.size) if pos.size else 0.0
        pos.size = remaining
        pos.fee_paid = entry_fee_remaining
        pos.partial_tp_taken = True
        if pos.stop_loss_price:
            pos.stop_loss_price = pos.entry_price
        distance = abs((pos.first_take_profit_price or pos.take_profit_price) - pos.entry_price)
        mult = max(1.0, float(getattr(self.config, "partial_tp2_multiplier", 2.0)))
        if distance > 0:
            if pos.side == "LONG":
                pos.take_profit_price = pos.entry_price + distance * mult
            else:
                pos.take_profit_price = pos.entry_price - distance * mult
        if pos.trailing is not None:
            pos.trailing.breakeven_armed = True
            pos.trailing.breakeven_stop_price = pos.entry_price
        self._record_decision("PAPER_PARTIAL_TP", {
            "reason": "TAKE_PROFIT_PARTIAL",
            "position_id": pos.position_id,
            "market_id": pos.market_id,
            "side": pos.side,
            "entry_price": pos.entry_price,
            "exit_price": exit_price,
            "closed_size": close_size,
            "remaining_size": pos.size,
            "net_pnl": net,
            "paper_only": True,
        })
        return True

    def _close_paper_position(self, pos_key: str, exit_price: float, reason: str) -> None:
        """Clôturer une position paper et mettre à jour les stats."""
        pos = self._open_positions.pop(pos_key, None)
        if not pos:
            return

        gross_pnl = pos.calculate_pnl(exit_price)
        exit_fee = pos.size * (TAKER_FEE_BPS / 10_000)
        net_pnl = gross_pnl - exit_fee

        self.stats.total_net_pnl_usdc += net_pnl
        self.stats.total_fees_paid += exit_fee
        self.stats.positions_closed += 1

        if net_pnl > 0:
            self.stats.winning_trades += 1
        else:
            self.stats.losing_trades += 1

        self._record_market_side_outcome(pos.market_id, pos.side, net_pnl)

        # Politique de risque (opt-in): alimenter le coupe-circuit + cooldown
        if self._risk_breaker is not None:
            risk_now_ms = int(time.time() * 1000)
            self._risk_breaker.record(net_pnl, risk_now_ms)
            self._risk_last_close_ms[pos.market_id] = risk_now_ms

        if reason == "STOP_LOSS":
            self.stats.stop_loss_exits += 1
        elif reason == "TAKE_PROFIT":
            self.stats.take_profit_exits += 1
        elif reason == "TRAILING_STOP":
            self.stats.trailing_stop_exits += 1
        elif reason == "TIME_STOP":
            self.stats.time_stop_exits += 1

        trade_record = {
            "position_id": pos.position_id,
            "market_id": pos.market_id,
            "side": pos.side,
            "entry_price": round(pos.entry_price, 6),
            "exit_price": round(exit_price, 6),
            "size": round(pos.size, 6),
            "gross_pnl": round(gross_pnl, 4),
            "fees": round(pos.fee_paid + exit_fee, 4),
            "net_pnl": round(net_pnl, 4),
            "reason": reason,
            "opened_at_ms": pos.opened_at_ms,
            "closed_at_ms": int(time.time() * 1000),
            "wallet_count": pos.wallet_count,
            "cluster_id": pos.cluster_id,
            "data_source": pos.data_source,
            "entry_slippage_bps": round(pos.entry_slippage_bps, 2),
            "exit_method": pos.exit_method,
            "disclaimer": "PAPER TRADE ONLY",
        }
        self._closed_trades.append(trade_record)
        self._record_decision("PAPER_CLOSE", trade_record)

        logger.info(
            "PAPER CLOSE %s %s entry=%.4f exit=%.4f net_pnl=%+.4f reason=%s | PAPER-ONLY",
            pos.side, pos.market_id, pos.entry_price, exit_price, net_pnl, reason,
        )

    def _refuse(self, reason: str) -> None:
        """Enregistrer un refus de signal (viral bot: log autant les refus que les entrées)."""
        self.stats.signals_refused += 1
        reason_key = reason.split(" ")[0].rstrip("(").split("(")[0]
        self._no_trade_reasons[reason_key] = self._no_trade_reasons.get(reason_key, 0) + 1
        self._record_decision("NO_TRADE", {
            "reason": reason_key,
            "detail": reason,
            "open_positions": len(self._open_positions),
            "shortlist_size": len(self._shortlist),
            "paper_only": True,
        })
        logger.debug("NO_TRADE: %s", reason)

    def stop(self) -> None:
        """Arrêter l'observateur proprement."""
        self._running = False
        if self._stream_client is not None:
            try:
                self._stream_client.stop()
            except Exception:
                pass
        if self._flow_monitor is not None:
            try:
                self._flow_monitor.stop()
            except Exception:
                pass
        logger.info("DydxLiveObserver stop requested | %s", self.DISCLAIMER)
