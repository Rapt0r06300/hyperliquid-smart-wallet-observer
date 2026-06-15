"""
Configuration dYdX v4 — valeurs sûres par défaut.

TOUTES les options dangereuses sont désactivées par défaut.
Aucune clé privée, aucun seed, aucune mnemonic n'est demandé.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum):
        """Compatibilité Python 3.10."""
        def __str__(self) -> str:
            return self.value



class DydxNetwork(StrEnum):
    TESTNET = "testnet"
    MAINNET = "mainnet"


class DydxMode(StrEnum):
    LIVE = "live"
    BACKTEST = "backtest"
    REPLAY = "replay"
    TEST_FIXTURE = "test_fixture"
    DEMO = "demo"  # mode démo — wallets synthétiques, aucun appel réseau réel


# --------------------------------------------------------------------------- #
# Endpoints publics Indexer (READ-ONLY, pas d'authentification)
# --------------------------------------------------------------------------- #
INDEXER_REST_ENDPOINTS = {
    DydxNetwork.TESTNET: "https://indexer.v4testnet.dydx.exchange",
    DydxNetwork.MAINNET: "https://indexer.dydx.trade",
}

INDEXER_WS_ENDPOINTS = {
    DydxNetwork.TESTNET: "wss://indexer.v4testnet.dydx.exchange/v4/ws",
    DydxNetwork.MAINNET: "wss://indexer.dydx.trade/v4/ws",
}

# Marchés autorisés par défaut (whitelist prudente)
DEFAULT_MARKET_WHITELIST = {
    "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "LINK-USD",
    "SUI-USD", "XRP-USD", "LTC-USD", "BNB-USD", "NEAR-USD", "APT-USD",
    "ARB-USD", "OP-USD", "TIA-USD", "WLD-USD", "DOGE-USD",
    "HYPE-USD", "TAO-USD", "SEI-USD", "HBAR-USD", "MORPHO-USD",
    "ZEC-USD", "VVV-USD", "MEGA-USD", "LIT-USD",
}

# Marchés blacklistés (inconnus, illiquides, expérimentaux)
DEFAULT_MARKET_BLACKLIST: set[str] = {"XYZ:CL"}


@dataclass
class DydxV4Config:
    """
    Configuration principale dYdX v4.

    Toutes les valeurs dangereuses sont False par défaut.
    Ne jamais mettre DYDX_ALLOW_TRADING=True en production.
    """

    # --- Activation globale ---
    enabled: bool = False  # DYDX_ENABLED

    # --- Réseau ---
    # Par défaut MAINNET READ-ONLY (Indexer public, pas d'auth).
    # TESTNET n'a quasi aucune activité → 0 wallets → simulation vide.
    network: DydxNetwork = DydxNetwork.MAINNET  # DYDX_NETWORK
    require_testnet: bool = False  # DYDX_REQUIRE_TESTNET

    # --- Safety absolue ---
    read_only: bool = True            # DYDX_READ_ONLY
    paper_only: bool = True           # DYDX_PAPER_ONLY
    allow_trading: bool = False       # DYDX_ALLOW_TRADING — JAMAIS True
    allow_private_key: bool = False   # DYDX_ALLOW_PRIVATE_KEY — JAMAIS True
    allow_node_private_api: bool = False  # DYDX_ALLOW_NODE_PRIVATE_API

    # --- Filtres signaux ---
    max_signal_age_ms: int = 30000      # DYDX_MAX_SIGNAL_AGE_MS (20s: aligné avec edge_calculator)
    hard_max_signal_age_ms: int = 30000 # DYDX_HARD_MAX_SIGNAL_AGE_MS (30s hard limit)
    min_edge_bps: float = 3.0           # DYDX_MIN_EDGE_BPS (3bps: filtre le bruit, laisse passer les modestes)
    edge_safety_multiplier: float = 1.0  # edge > 1.2x total_cost_bps (assoupli)

    # --- Paper trading ---
    starting_balance_usdc: float = 1000.0  # DYDX_STARTING_BALANCE_USDC
    max_open_paper_trades: int = 25          # DYDX_MAX_OPEN_PAPER_TRADES (25: max positions, edge-gated)
    max_position_pct: float = 0.12          # max 12% de la balance par position
    max_total_exposure_pct: float = 0.95    # max 95% d'exposition totale (25 positions edge-gated)
    dynamic_sizing_enabled: bool = True      # DYDX_DYNAMIC_SIZING
    paper_notional_min_usdc: float = 20.0    # DYDX_PAPER_NOTIONAL_MIN_USDC
    paper_notional_base_usdc: float = 75.0   # DYDX_PAPER_NOTIONAL_BASE_USDC
    paper_notional_max_usdc: float = 100.0   # DYDX_PAPER_NOTIONAL_MAX_USDC
    dynamic_sizing_edge_full_bps: float = 25.0  # DYDX_DYNAMIC_SIZING_EDGE_FULL_BPS
    dynamic_sizing_atr_high_pct: float = 0.03   # DYDX_DYNAMIC_SIZING_ATR_HIGH_PCT
    dynamic_sizing_loss_penalty: float = 0.25   # DYDX_DYNAMIC_SIZING_LOSS_PENALTY

    # --- Coûts estimés (bps) ---
    taker_fee_bps: float = 5.0       # frais taker dYdX v4
    maker_fee_bps: float = 2.0       # frais maker dYdX v4
    estimated_spread_bps: float = 3.0
    estimated_slippage_bps: float = 5.0
    estimated_latency_bps: float = 2.0
    copy_degradation_bps: float = 5.0

    # --- Marchés ---
    market_whitelist: set[str] = field(default_factory=lambda: set(DEFAULT_MARKET_WHITELIST))
    market_blacklist: set[str] = field(default_factory=lambda: set(DEFAULT_MARKET_BLACKLIST))

    # --- Réseau / HTTP ---
    rest_timeout_s: float = 8.0
    rest_max_retries: int = 2         # réduit: moins d'attente au démarrage
    rest_backoff_base_s: float = 0.5  # réduit: 0.5s → 1s max
    rest_rate_limit_rps: float = 5.0
    # Health check spécifique — rapide, non-bloquant
    health_check_retries: int = 0     # 0 = une seule tentative, échec → continue
    ws_ping_interval_s: float = 30.0
    ws_reconnect_delay_s: float = 5.0
    ws_max_reconnect_attempts: int = 10

    # --- Base de données ---
    db_path: str = "data/dydx_v4.sqlite3"
    decision_log_enabled: bool = True          # DYDX_DECISION_LOG
    decision_log_path: str = "logs/structured/decisions.jsonl"  # DYDX_DECISION_LOG_PATH

    # --- Mode ---
    mode: DydxMode = DydxMode.LIVE
    # demo_mode: injecte des wallets synthétiques si discovery retourne 0 wallets
    # Utile quand le réseau est instable ou le Cosmos LCD inaccessible.
    demo_mode: bool = False  # DYDX_DEMO_MODE

    # --- Sélection v2 / consensus (standards bot viral) ---
    # Entrée valide seulement si ≥K comptes shortlistés convergent
    # (même marché, même sens) dans la fenêtre.
    consensus_required: bool = True            # DYDX_CONSENSUS_REQUIRED
    consensus_min_wallets: int = 2             # DYDX_CONSENSUS_MIN_WALLETS
    consensus_window_ms: int = 3 * 60 * 1000   # DYDX_CONSENSUS_WINDOW_MS
    consensus_recency_bonus_window_ms: int = 30_000  # DYDX_CONSENSUS_RECENCY_BONUS_WINDOW_MS
    consensus_recency_edge_multiplier: float = 1.06  # DYDX_CONSENSUS_RECENCY_EDGE_MULTIPLIER

    # --- Exits adaptatifs (ATR) ---
    atr_period: int = 14
    atr_stop_mult: float = 1.0          # SL = entry -/+ 1.0xATR (couper vite, limiter les pertes)
    atr_take_profit_mult: float = 3.0   # TP = entry +/- 3xATR (R:R = 3:1)
    atr_trail_mult: float = 0.8         # trailing = 0.8xATR (armé après +0.8xATR, plus serré)
    max_holding_hours: float = 48.0     # time-stop
    partial_tp_enabled: bool = True      # DYDX_PARTIAL_TP
    partial_tp_fraction: float = 0.50    # DYDX_PARTIAL_TP_FRACTION
    partial_tp2_multiplier: float = 2.0  # DYDX_PARTIAL_TP2_MULTIPLIER
    funding_adverse_threshold_hourly: float = 0.0001  # 0.01%/h adverse → durée /2
    breakeven_stop_enabled: bool = True       # DYDX_BREAKEVEN_STOP — protège les gains acquis
    breakeven_trigger_atr_mult: float = 1.5   # armer le breakeven après +1.5×ATR de profit
    breakeven_offset_atr_mult: float = 0.1    # SL = entry + 0.1×ATR (micro-profit garanti)

    # --- Fills honnêtes (jamais au mid) ---
    use_orderbook_fills: bool = True
    max_book_participation_pct: float = 0.10  # max 10% de la profondeur visible
    fill_latency_extra_bps: float = 2.0       # pénalité adverse de latence

    # --- Trend / regime filters (paper-only) ---
    trend_filter_enabled: bool = True          # DYDX_TREND_FILTER
    regime_detector_enabled: bool = True       # DYDX_REGIME_DETECTOR
    market_context_ttl_s: float = 60.0         # DYDX_MARKET_CONTEXT_TTL_S
    trend_min_move_pct: float = 0.0015         # DYDX_TREND_MIN_MOVE_PCT
    choppy_efficiency_max: float = 0.18        # DYDX_CHOPPY_EFFICIENCY_MAX
    choppy_atr_pct_min: float = 0.001          # DYDX_CHOPPY_ATR_PCT_MIN
    volume_spike_enabled: bool = True          # DYDX_VOLUME_SPIKE
    volume_spike_zscore_min: float = 2.0       # DYDX_VOLUME_SPIKE_ZSCORE_MIN
    volume_spike_imbalance_min: float = 0.62   # DYDX_VOLUME_SPIKE_IMBALANCE_MIN
    volume_spike_edge_multiplier: float = 1.08 # DYDX_VOLUME_SPIKE_EDGE_MULTIPLIER
    correlation_gate_enabled: bool = True      # DYDX_CORRELATION_GATE
    max_correlated_same_side: int = 5          # DYDX_MAX_CORRELATED_SAME_SIDE (2: permet BTC+ETH ou SOL+AVAX)
    confluence_enabled: bool = True            # DYDX_CONFLUENCE
    confluence_window_ms: int = 30_000         # DYDX_CONFLUENCE_WINDOW_MS
    confluence_edge_multiplier: float = 1.10   # DYDX_CONFLUENCE_EDGE_MULTIPLIER
    funding_edge_enabled: bool = True          # DYDX_FUNDING_EDGE
    funding_edge_horizon_hours: float = 1.0    # DYDX_FUNDING_EDGE_HORIZON_HOURS

    # --- Scan rapide multi-wallets (défaut ON) ---
    # Quand True: l'observer abonne les wallets chauds en WebSocket et poll
    # immédiatement ceux qui viennent de trader (latence 8–58s → ~1s).
    # Sans ça: REST seul → 10-30s de latence → tous les signaux sont stale.
    fast_scanner_enabled: bool = True          # DYDX_FAST_SCANNER
    fast_scanner_hot_capacity: int = 1000       # DYDX_FAST_SCANNER_HOT_CAPACITY

    # --- Politique de risque (défaut ON) — anti-perte ---
    # Anti-churn (hold mini + cooldown), exits ATR, coupe-circuit, anti-scalper.
    risk_policy_enabled: bool = True           # DYDX_RISK_POLICY
    min_hold_seconds: float = 30.0             # anti-churn: hold 60s mini (ancien 20s → flip-flop)
    reopen_cooldown_seconds: float = 15.0      # cooldown 45s — laisser re-rentrer plus vite sur un bon signal
    circuit_max_consecutive_losses: int = 6    # coupe-circuit: pertes d'affilée
    circuit_max_daily_drawdown_pct: float = 0.05  # coupe-circuit: perte jour max
    scalper_min_hold_seconds: float = 60.0     # anti-scalper: leaders < 60s écartés
    adaptive_exits_enabled: bool = True        # exits ATR dans la politique de risque
    # Élargir le shortlist de DÉCISION avec les wallets découverts (Cosmos/harvester)
    # → plus de wallets suivis = plus de chances de consensus de qualité.
    max_decision_wallets: int = 500            # DYDX_MAX_DECISION_WALLETS (scan large)
    # Réalisme des fills paper: "orderbook_real" (carnet réel + frais+spread+
    # slippage+funding) ou "mark_simple" (mark + frais forfaitaires). Dans les
    # deux cas le PnL est marké aux VRAIS prix mainnet → reflète le mainnet.
    fill_realism_mode: str = "orderbook_real"  # DYDX_FILL_REALISM

    # Sélectivité extrême: n'ouvrir que si assez de leaders PROUVÉS gagnants
    # participent au consensus. Graceful: ignoré si aucun wallet n'a de métrique
    # (évite de tout bloquer quand l'enrichissement n'a pas encore tourné).
    # OFF par défaut: trop strict, ça bloquait toutes les entrées tant que les
    # wallets n'avaient pas de métriques. La qualité vient du consensus + risk
    # policy + exits ATR + le sweep. Réactivable via DYDX_REQUIRE_PROVEN_LEADERS=1.
    require_proven_leaders: bool = False       # DYDX_REQUIRE_PROVEN_LEADERS
    min_leader_winrate: float = 0.45
    min_leader_profit_factor: float = 1.3
    min_leader_trades: int = 15
    min_proven_in_consensus: int = 1

    # Full Node gRPC Streaming — le firehose: TOUS les fills de TOUS les wallets
    # avec adresse, en temps réel. Nécessite un node avec --grpc-streaming-enabled.
    # Voir docs/migration/DYDX_FULL_NODE_STREAMING_RUNBOOK.md.
    full_node_stream_enabled: bool = False             # DYDX_FULL_NODE_STREAM
    full_node_stream_endpoint: str = "127.0.0.1:9090"  # DYDX_FULL_NODE_STREAM_ENDPOINT
    # Consensus temps réel direct (zéro REST): K wallets distincts même marché+sens
    # dans la fenêtre → signal. C'est ce qui exploite le firehose à grande échelle.
    stream_consensus_min_wallets: int = 3              # DYDX_STREAM_CONSENSUS_MIN_WALLETS (1→3: qualité)
    stream_window_ms: int = 8000                       # DYDX_STREAM_WINDOW_MS (plus de clusters)
    market_flow_enabled: bool = True                   # DYDX_MARKET_FLOW
    market_flow_min_volume_usdc: float = 10000.0       # DYDX_MARKET_FLOW_MIN_VOLUME ($10k en 8s: plus de conviction)
    market_flow_min_imbalance: float = 0.65            # DYDX_MARKET_FLOW_MIN_IMBALANCE (65%: signal plus fort)
    rest_poll_cap: int = 100                            # DYDX_REST_POLL_CAP
    max_spread_bps: float = 40.0                       # DYDX_MAX_SPREAD_BPS (25bps: altcoins inclus)
    flow_min_trades: int = 5                           # DYDX_FLOW_MIN_TRADES (5 trades en 8s: plus de conviction)
    # Gate wallet_count pour les signaux flow — DOIT rester 1.
    # Les flow signals sont du momentum de marché (v4_trades), PAS du consensus wallet.
    # wallet_count=1 est normal (build_cluster_from_flow fixe toujours 1).
    # La qualité vient du volume, imbalance et min_trades, PAS du wallet_count.
    flow_consensus_min_wallets: int = 1                # DYDX_FLOW_CONSENSUS_MIN_WALLETS (1: flow ≠ consensus)

    def __post_init__(self) -> None:
        self._assert_safety()

    def _assert_safety(self) -> None:
        """Lever une erreur si des options dangereuses sont activées."""
        if self.allow_trading:
            raise ValueError(
                "SAFETY VIOLATION: allow_trading=True est interdit. "
                "Ce module est READ-ONLY / PAPER-ONLY uniquement."
            )
        if self.allow_private_key:
            raise ValueError(
                "SAFETY VIOLATION: allow_private_key=True est interdit. "
                "Aucune clé privée, seed ou mnemonic ne doit être utilisé."
            )
        if not self.paper_only:
            raise ValueError(
                "SAFETY VIOLATION: paper_only=False est interdit. "
                "Seuls les paper trades sont autorisés."
            )
        if not self.read_only:
            raise ValueError(
                "SAFETY VIOLATION: read_only=False est interdit."
            )
        # require_testnet est maintenant False par défaut — mainnet READ-ONLY autorisé
        if self.require_testnet and self.network == DydxNetwork.MAINNET:
            raise ValueError(
                "SAFETY VIOLATION: require_testnet=True mais network=mainnet. "
                "Mettre require_testnet=False explicitement pour utiliser mainnet (READ-ONLY seulement)."
            )

    @property
    def indexer_rest_url(self) -> str:
        return INDEXER_REST_ENDPOINTS[self.network]

    @property
    def indexer_ws_url(self) -> str:
        return INDEXER_WS_ENDPOINTS[self.network]

    @property
    def total_round_trip_cost_bps(self) -> float:
        """Coût total aller-retour estimé en bps."""
        return (
            self.taker_fee_bps * 2  # entrée + sortie
            + self.estimated_spread_bps
            + self.estimated_slippage_bps
            + self.estimated_latency_bps
            + self.copy_degradation_bps
        )


def load_config_from_env(base: DydxV4Config | None = None) -> DydxV4Config:
    """
    Charge la configuration depuis les variables d'environnement.
    Les valeurs dangereuses restent bloquées même si l'env les active.
    """
    cfg = base or DydxV4Config()

    def _bool(key: str, default: bool) -> bool:
        v = os.environ.get(key, "").lower()
        if v in ("1", "true", "yes"):
            return True
        if v in ("0", "false", "no"):
            return False
        return default

    def _int(key: str, default: int) -> int:
        try:
            return int(os.environ.get(key, str(default)))
        except (ValueError, TypeError):
            return default

    def _float(key: str, default: float) -> float:
        try:
            return float(os.environ.get(key, str(default)))
        except (ValueError, TypeError):
            return default

    # Réseau — MAINNET par défaut (Indexer public READ-ONLY)
    net_str = os.environ.get("DYDX_NETWORK", cfg.network.value).lower()
    if net_str == "testnet":
        network = DydxNetwork.TESTNET
    else:
        network = DydxNetwork.MAINNET  # défaut mainnet

    # demo_mode: activé si DYDX_DEMO_MODE=1 ou si réseau=testnet (pas d'activité)
    demo_env = os.environ.get("DYDX_DEMO_MODE", "").lower()
    demo_mode = demo_env in ("1", "true", "yes") or cfg.demo_mode

    # Construire sans allow_trading ni allow_private_key
    return DydxV4Config(
        enabled=_bool("DYDX_ENABLED", cfg.enabled),
        network=network,
        require_testnet=False,    # TOUJOURS False — mainnet READ-ONLY autorisé
        read_only=True,           # TOUJOURS True — non surchargeable
        paper_only=True,          # TOUJOURS True — non surchargeable
        allow_trading=False,      # TOUJOURS False — non surchargeable
        allow_private_key=False,  # TOUJOURS False — non surchargeable
        allow_node_private_api=False,
        max_signal_age_ms=_int("DYDX_MAX_SIGNAL_AGE_MS", cfg.max_signal_age_ms),
        hard_max_signal_age_ms=_int("DYDX_HARD_MAX_SIGNAL_AGE_MS", cfg.hard_max_signal_age_ms),
        min_edge_bps=_float("DYDX_MIN_EDGE_BPS", cfg.min_edge_bps),
        edge_safety_multiplier=_float("DYDX_EDGE_SAFETY_MULTIPLIER", cfg.edge_safety_multiplier),
        starting_balance_usdc=_float("DYDX_STARTING_BALANCE_USDC", cfg.starting_balance_usdc),
        max_open_paper_trades=_int("DYDX_MAX_OPEN_PAPER_TRADES", cfg.max_open_paper_trades),
        max_position_pct=_float("DYDX_MAX_POSITION_PCT", cfg.max_position_pct),
        max_total_exposure_pct=_float("DYDX_MAX_TOTAL_EXPOSURE_PCT", cfg.max_total_exposure_pct),
        dynamic_sizing_enabled=_bool("DYDX_DYNAMIC_SIZING", cfg.dynamic_sizing_enabled),
        paper_notional_min_usdc=_float("DYDX_PAPER_NOTIONAL_MIN_USDC", cfg.paper_notional_min_usdc),
        paper_notional_base_usdc=_float("DYDX_PAPER_NOTIONAL_BASE_USDC", cfg.paper_notional_base_usdc),
        paper_notional_max_usdc=_float("DYDX_PAPER_NOTIONAL_MAX_USDC", cfg.paper_notional_max_usdc),
        dynamic_sizing_edge_full_bps=_float("DYDX_DYNAMIC_SIZING_EDGE_FULL_BPS", cfg.dynamic_sizing_edge_full_bps),
        dynamic_sizing_atr_high_pct=_float("DYDX_DYNAMIC_SIZING_ATR_HIGH_PCT", cfg.dynamic_sizing_atr_high_pct),
        dynamic_sizing_loss_penalty=_float("DYDX_DYNAMIC_SIZING_LOSS_PENALTY", cfg.dynamic_sizing_loss_penalty),
        db_path=os.environ.get("DYDX_DB_PATH", cfg.db_path),
        decision_log_enabled=_bool("DYDX_DECISION_LOG", cfg.decision_log_enabled),
        decision_log_path=os.environ.get("DYDX_DECISION_LOG_PATH", cfg.decision_log_path),
        partial_tp_enabled=_bool("DYDX_PARTIAL_TP", cfg.partial_tp_enabled),
        partial_tp_fraction=_float("DYDX_PARTIAL_TP_FRACTION", cfg.partial_tp_fraction),
        partial_tp2_multiplier=_float("DYDX_PARTIAL_TP2_MULTIPLIER", cfg.partial_tp2_multiplier),
        demo_mode=demo_mode,
        consensus_required=_bool("DYDX_CONSENSUS_REQUIRED", cfg.consensus_required),
        consensus_min_wallets=_int("DYDX_CONSENSUS_MIN_WALLETS", cfg.consensus_min_wallets),
        consensus_window_ms=_int("DYDX_CONSENSUS_WINDOW_MS", cfg.consensus_window_ms),
        consensus_recency_bonus_window_ms=_int(
            "DYDX_CONSENSUS_RECENCY_BONUS_WINDOW_MS",
            cfg.consensus_recency_bonus_window_ms,
        ),
        consensus_recency_edge_multiplier=_float(
            "DYDX_CONSENSUS_RECENCY_EDGE_MULTIPLIER",
            cfg.consensus_recency_edge_multiplier,
        ),
        fast_scanner_enabled=_bool("DYDX_FAST_SCANNER", cfg.fast_scanner_enabled),
        fast_scanner_hot_capacity=_int("DYDX_FAST_SCANNER_HOT_CAPACITY", cfg.fast_scanner_hot_capacity),
        risk_policy_enabled=_bool("DYDX_RISK_POLICY", cfg.risk_policy_enabled),
        min_hold_seconds=_float("DYDX_MIN_HOLD_SECONDS", cfg.min_hold_seconds),
        reopen_cooldown_seconds=_float("DYDX_REOPEN_COOLDOWN_SECONDS", cfg.reopen_cooldown_seconds),
        circuit_max_consecutive_losses=_int("DYDX_CIRCUIT_MAX_CONSECUTIVE_LOSSES", cfg.circuit_max_consecutive_losses),
        circuit_max_daily_drawdown_pct=_float("DYDX_CIRCUIT_MAX_DAILY_DD_PCT", cfg.circuit_max_daily_drawdown_pct),
        scalper_min_hold_seconds=_float("DYDX_SCALPER_MIN_HOLD_SECONDS", cfg.scalper_min_hold_seconds),
        adaptive_exits_enabled=_bool("DYDX_ADAPTIVE_EXITS", cfg.adaptive_exits_enabled),
        trend_filter_enabled=_bool("DYDX_TREND_FILTER", cfg.trend_filter_enabled),
        regime_detector_enabled=_bool("DYDX_REGIME_DETECTOR", cfg.regime_detector_enabled),
        market_context_ttl_s=_float("DYDX_MARKET_CONTEXT_TTL_S", cfg.market_context_ttl_s),
        trend_min_move_pct=_float("DYDX_TREND_MIN_MOVE_PCT", cfg.trend_min_move_pct),
        choppy_efficiency_max=_float("DYDX_CHOPPY_EFFICIENCY_MAX", cfg.choppy_efficiency_max),
        choppy_atr_pct_min=_float("DYDX_CHOPPY_ATR_PCT_MIN", cfg.choppy_atr_pct_min),
        volume_spike_enabled=_bool("DYDX_VOLUME_SPIKE", cfg.volume_spike_enabled),
        volume_spike_zscore_min=_float("DYDX_VOLUME_SPIKE_ZSCORE_MIN", cfg.volume_spike_zscore_min),
        volume_spike_imbalance_min=_float("DYDX_VOLUME_SPIKE_IMBALANCE_MIN", cfg.volume_spike_imbalance_min),
        volume_spike_edge_multiplier=_float("DYDX_VOLUME_SPIKE_EDGE_MULTIPLIER", cfg.volume_spike_edge_multiplier),
        correlation_gate_enabled=_bool("DYDX_CORRELATION_GATE", cfg.correlation_gate_enabled),
        max_correlated_same_side=_int("DYDX_MAX_CORRELATED_SAME_SIDE", cfg.max_correlated_same_side),
        confluence_enabled=_bool("DYDX_CONFLUENCE", cfg.confluence_enabled),
        confluence_window_ms=_int("DYDX_CONFLUENCE_WINDOW_MS", cfg.confluence_window_ms),
        confluence_edge_multiplier=_float("DYDX_CONFLUENCE_EDGE_MULTIPLIER", cfg.confluence_edge_multiplier),
        funding_edge_enabled=_bool("DYDX_FUNDING_EDGE", cfg.funding_edge_enabled),
        funding_edge_horizon_hours=_float("DYDX_FUNDING_EDGE_HORIZON_HOURS", cfg.funding_edge_horizon_hours),
        max_decision_wallets=_int("DYDX_MAX_DECISION_WALLETS", cfg.max_decision_wallets),
        fill_realism_mode=os.environ.get("DYDX_FILL_REALISM", cfg.fill_realism_mode),
        require_proven_leaders=_bool("DYDX_REQUIRE_PROVEN_LEADERS", cfg.require_proven_leaders),
        min_leader_winrate=_float("DYDX_MIN_LEADER_WINRATE", cfg.min_leader_winrate),
        min_leader_profit_factor=_float("DYDX_MIN_LEADER_PF", cfg.min_leader_profit_factor),
        min_leader_trades=_int("DYDX_MIN_LEADER_TRADES", cfg.min_leader_trades),
        min_proven_in_consensus=_int("DYDX_MIN_PROVEN_IN_CONSENSUS", cfg.min_proven_in_consensus),
        full_node_stream_enabled=_bool("DYDX_FULL_NODE_STREAM", cfg.full_node_stream_enabled),
        full_node_stream_endpoint=os.environ.get("DYDX_FULL_NODE_STREAM_ENDPOINT", cfg.full_node_stream_endpoint),
        stream_consensus_min_wallets=_int("DYDX_STREAM_CONSENSUS_MIN_WALLETS", cfg.stream_consensus_min_wallets),
        stream_window_ms=_int("DYDX_STREAM_WINDOW_MS", cfg.stream_window_ms),
        market_flow_enabled=_bool("DYDX_MARKET_FLOW", cfg.market_flow_enabled),
        market_flow_min_volume_usdc=_float("DYDX_MARKET_FLOW_MIN_VOLUME", cfg.market_flow_min_volume_usdc),
        market_flow_min_imbalance=_float("DYDX_MARKET_FLOW_MIN_IMBALANCE", cfg.market_flow_min_imbalance),
        rest_poll_cap=_int("DYDX_REST_POLL_CAP", cfg.rest_poll_cap),
        max_spread_bps=_float("DYDX_MAX_SPREAD_BPS", cfg.max_spread_bps),
        flow_min_trades=_int("DYDX_FLOW_MIN_TRADES", cfg.flow_min_trades),
        flow_consensus_min_wallets=_int("DYDX_FLOW_CONSENSUS_MIN_WALLETS", cfg.flow_consensus_min_wallets),
        breakeven_stop_enabled=_bool("DYDX_BREAKEVEN_STOP", cfg.breakeven_stop_enabled),
        breakeven_trigger_atr_mult=_float("DYDX_BREAKEVEN_TRIGGER_ATR_MULT", cfg.breakeven_trigger_atr_mult),
        breakeven_offset_atr_mult=_float("DYDX_BREAKEVEN_OFFSET_ATR_MULT", cfg.breakeven_offset_atr_mult),
    )


# Instance par defaut (safe) -- MAINNET READ-ONLY
DEFAULT_CONFIG = DydxV4Config()
