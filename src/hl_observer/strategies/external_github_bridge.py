"""Bridge external GitHub bot repos into HyperSmart paper strategies.

The repos under runtime/research/github_repos_v24 are preserved as upstream
installations. This bridge does not import or execute their code. It exposes
their strategy families as priority paper profiles so HyperSmart can route its
own Hyperliquid read-only data through equivalent local simulation behavior.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from hl_observer.strategies.models import StrategyDefinition, StrategyKind, make_strategy
from hl_observer.strategies.paper_registry import PaperStrategyRegistry

REPO_ROOT_RELATIVE = Path("runtime") / "research" / "github_repos_v24"
MANIFEST_NAME = "EXTERNAL_REPOS_MANIFEST.json"
INSTALLED_STATUSES = frozenset({"CLONED", "ALREADY_PRESENT", "UPDATED_FETCHED"})


@dataclass(frozen=True, slots=True)
class ExternalStrategyProfileSpec:
    profile_id: str
    name: str
    kind: StrategyKind
    params: dict[str, object]


@dataclass(frozen=True, slots=True)
class ExternalRepoSpec:
    local_id: str
    url: str
    family: str
    priority: int
    role: str
    target_modules: tuple[str, ...]
    profiles: tuple[ExternalStrategyProfileSpec, ...]


@dataclass(frozen=True, slots=True)
class ExternalRepoCapability:
    local_id: str
    url: str
    family: str
    priority: int
    role: str
    installed: bool
    status: str
    path: str
    branch: str | None
    commit: str | None
    file_count: int
    size_bytes: int
    unavailable_reason: str
    target_modules: tuple[str, ...]
    profile_ids: tuple[str, ...]
    upstream_preserved: bool = True
    direct_execution: bool = False
    paper_only: bool = True

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["target_modules"] = list(self.target_modules)
        payload["profile_ids"] = list(self.profile_ids)
        return payload


def requested_external_repos() -> tuple[ExternalRepoSpec, ...]:
    return (
        ExternalRepoSpec(
            local_id="15_chaininsighter_solana_copy_trading_bot",
            url="https://github.com/ChainInsighter/Solana-Copy-trading-bot",
            family="copy_wallet_session",
            priority=10,
            role="multi-wallet copy session, latency and session UX",
            target_modules=("realtime/latency_report", "runtime/session_logs", "ui/simulation_log_export"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_chaininsighter_priority_copy_session",
                    name="External ChainInsighter priority copy session",
                    kind=StrategyKind.COPY_FOLLOW,
                    params={
                        "source_priority": 10,
                        "max_signal_age_ms": 2500,
                        "session_latency_required": True,
                        "multi_wallet_session": True,
                    },
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="16_immutal0_solana_copytrading_bot",
            url="https://github.com/Immutal0/Solana-CopyTrading-Bot",
            family="copy_wallet_filters",
            priority=20,
            role="wallet tracking filters and risk caps",
            target_modules=("wallets/leader_hotness", "risk/risk_engine_v3"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_immutal0_wallet_filter_caps",
                    name="External Immutal0 wallet filter caps",
                    kind=StrategyKind.COPY_FOLLOW,
                    params={
                        "source_priority": 20,
                        "require_wallet_filter": True,
                        "max_equity_pct": 4.0,
                        "max_open_positions": 5,
                    },
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="17_rezzecup_whale_wallet_mirror_copy_trader",
            url="https://github.com/Rezzecup/whale-wallet-mirror-copy-trader",
            family="whale_wallet_mirror",
            priority=0,
            role="whale mirror, proportional sizing and copy-risk gate",
            target_modules=("copy_wallet/wallet_mirror_runtime", "scoring/wallet_score_v2", "risk/risk_engine_v3"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_rezzecup_whale_mirror_primary",
                    name="External Rezzecup whale mirror primary",
                    kind=StrategyKind.COPY_FOLLOW,
                    params={
                        "source_priority": 0,
                        "copy_ratio": 0.04,
                        "min_same_side_leaders": 2,
                        "max_slippage_bps": 14,
                        "require_copy_risk_gate": True,
                    },
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="18_neron888_polymarket_copy_trading_bot",
            url="https://github.com/Neron888/Polymarket-copy-trading-bot",
            family="copy_loop_unavailable",
            priority=90,
            role="copy loop and leader filters, unavailable upstream",
            target_modules=("copying/signal_detector",),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_neron888_copy_loop_pending",
                    name="External Neron888 copy loop pending",
                    kind=StrategyKind.COPY_FOLLOW,
                    params={"source_priority": 90, "pending_upstream": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="19_terauss_polymarket_copy_trading_bot",
            url="https://github.com/terauss/Polymarket-Copy-Trading-Bot",
            family="hot_path_unavailable",
            priority=15,
            role="hot-path/research-path split and conflicting leaders, unavailable upstream",
            target_modules=("copying/simulation_pipeline", "evidence/decision_ledger"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_terauss_hot_path_pending",
                    name="External terauss hot path pending",
                    kind=StrategyKind.FAST_TIMING,
                    params={"source_priority": 15, "pending_upstream": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="20_warp_id_solana_trading_bot",
            url="https://github.com/warp-id/solana-trading-bot",
            family="risk_process",
            priority=45,
            role="monitoring, risk config and wallet rules",
            target_modules=("risk/gates",),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_warp_risk_process_caps",
                    name="External warp risk process caps",
                    kind=StrategyKind.STRATEGY_ENSEMBLE,
                    params={"source_priority": 45, "risk_config_required": True, "wallet_rule_guard": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="21_tony_42069_trader_tony_v4",
            url="https://github.com/tony-42069/trader-tony-v4",
            family="autonomous_sltp",
            priority=5,
            role="autonomous scan, SL/TP/trailing and manipulation flags",
            target_modules=("signals/entry_quality_gate", "paper_trading/sltp_runtime"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_tony_autonomous_sltp_priority",
                    name="External Tony autonomous SLTP priority",
                    kind=StrategyKind.FAST_TIMING,
                    params={
                        "source_priority": 5,
                        "trailing_stop_required": True,
                        "partial_tp_required": True,
                        "manipulation_flags_required": True,
                    },
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="22_freqtrade",
            url="https://github.com/freqtrade/freqtrade",
            family="backtest_discipline",
            priority=30,
            role="dry-run, backtesting, optimization and no-lookahead discipline",
            target_modules=("optimization/profit_optimizer", "backtest/no_lookahead_guard", "backtest/experiment_runner"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_freqtrade_backtest_discipline",
                    name="External freqtrade backtest discipline",
                    kind=StrategyKind.STRATEGY_ENSEMBLE,
                    params={
                        "source_priority": 30,
                        "dry_run_required": True,
                        "no_lookahead_guard": True,
                        "walk_forward_required": True,
                    },
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="23_octobot",
            url="https://github.com/drakkar-software/octobot",
            family="bot_framework",
            priority=35,
            role="strategy framework, evaluators, risk management",
            target_modules=("strategies/library", "strategies/paper_registry"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_octobot_framework_priority",
                    name="External OctoBot framework priority",
                    kind=StrategyKind.STRATEGY_ENSEMBLE,
                    params={"source_priority": 35, "evaluator_stack": True, "risk_framework": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="24_jlowo_gengar_polymarket_bot",
            url="https://github.com/JLowo/gengar_polymarket_bot",
            family="lightweight_decision_bot",
            priority=55,
            role="simple scanner and structured decisions",
            target_modules=("signals/entry_quality_gate", "evidence/decision_ledger"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_jlowo_structured_decision",
                    name="External JLowo structured decision",
                    kind=StrategyKind.DIRECTION_HUNT,
                    params={"source_priority": 55, "structured_decision_log": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="25_djienne_polymarket_bot",
            url="https://github.com/djienne/Polymarket-bot",
            family="bot_logging_resilience",
            priority=60,
            role="bot ergonomics, resilience tests and logging",
            target_modules=("simulation/log_metrics", "runtime/session_logs"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_djienne_resilience_logging",
                    name="External djienne resilience logging",
                    kind=StrategyKind.STRATEGY_ENSEMBLE,
                    params={"source_priority": 60, "decision_logging_required": True, "resilience_guard": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="26_jonmaa_btc_polymarket_bot",
            url="https://github.com/Jonmaa/btc-polymarket-bot",
            family="single_market_discipline",
            priority=65,
            role="single-market strategy discipline and market-specific rules",
            target_modules=("risk/risk_engine_v3",),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_jonmaa_single_market_rules",
                    name="External Jonmaa single market rules",
                    kind=StrategyKind.DIRECTION_HUNT,
                    params={"source_priority": 65, "market_specific_rules": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="27_carlosibcu_polymarket_kalshi_btc_arbitrage_bot",
            url="https://github.com/CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot",
            family="cross_source_reconcile",
            priority=25,
            role="cross-source comparison and BTC divergence",
            target_modules=("signals/source_reconcile", "edge/edge_calculator"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_carlos_cross_source_reconcile",
                    name="External Carlos cross source reconcile",
                    kind=StrategyKind.CROSS_SOURCE_DISCREPANCY,
                    params={
                        "source_priority": 25,
                        "require_two_sources": True,
                        "divergence_guard": True,
                    },
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="01_cloddsbot",
            url="https://github.com/alsk1992/CloddsBot",
            family="agentic_prediction_bot",
            priority=70,
            role="agent-style research loop, prompts and decision logging adapted to local paper simulation",
            target_modules=("research/ollama_advisor", "evidence/decision_ledger", "ui/simulation_log_export"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_cloddsbot_agentic_research_loop",
                    name="External CloddsBot agentic research loop",
                    kind=StrategyKind.RAG_EVIDENCE_CONTEXT,
                    params={"source_priority": 70, "agentic_research": True, "paper_decision_explainer": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="02_harrier_prediction_markets_toolkits",
            url="https://github.com/HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits",
            family="toolkit_decision_stack",
            priority=72,
            role="prediction-market toolkit patterns mapped to Hyperliquid read-only feature extraction",
            target_modules=("agent_tools/manifest", "features/scan_features", "ledger/evidence"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_harrier_toolkit_decision_stack",
                    name="External Harrier toolkit decision stack",
                    kind=StrategyKind.STRATEGY_ENSEMBLE,
                    params={"source_priority": 72, "toolkit_stack": True, "feature_extraction_required": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="03_mrfadiai_polymarket_bot",
            url="https://github.com/MrFadiAi/Polymarket-bot",
            family="copy_wallet_rules",
            priority=58,
            role="simple bot rules and wallet monitoring adapted to Hyperliquid leaders",
            target_modules=("copying/signal_detector", "copy_wallet/wallet_mirror_runtime"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_mrfadiai_copy_rules",
                    name="External MrFadiAi copy rules",
                    kind=StrategyKind.COPY_FOLLOW,
                    params={"source_priority": 58, "copy_rules": True, "leader_monitoring": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="04_polymarket_lp_tool",
            url="https://github.com/lihanyu81/polymarket_lp_tool",
            family="liquidity_provider_tool",
            priority=52,
            role="liquidity and quote discipline adapted as paper-only market quality guard",
            target_modules=("market_making", "risk/liquidity_cliff_detector", "features/orderbook_imbalance"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_polymarket_lp_liquidity_guard",
                    name="External Polymarket LP liquidity guard",
                    kind=StrategyKind.MARKET_MAKING_SIM,
                    params={"source_priority": 52, "liquidity_provider_logic": True, "quote_quality_guard": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="05_polyweather",
            url="https://github.com/yangyuan-zhen/PolyWeather",
            family="external_context_features",
            priority=95,
            role="external context feature pattern, retained as offline research context only",
            target_modules=("features/scan_features",),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_polyweather_context_features",
                    name="External PolyWeather context features",
                    kind=StrategyKind.RAG_EVIDENCE_CONTEXT,
                    params={"source_priority": 95, "external_context_only": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="06_composio_polymarket_kalshi_arbitrage_bot",
            url="https://github.com/Composio-HQ/polymarket-kalshi-arbitrage-bot",
            family="cross_market_arbitrage_unavailable",
            priority=88,
            role="cross-market arbitrage pattern, unavailable upstream URL",
            target_modules=("signals/source_reconcile", "arbitrage"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_composio_cross_market_arb_pending",
                    name="External Composio cross-market arbitrage pending",
                    kind=StrategyKind.CROSS_SOURCE_DISCREPANCY,
                    params={"source_priority": 88, "pending_upstream": True, "cross_market_arb": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="07_awesome_prediction_market_tools",
            url="https://github.com/aarora4/Awesome-Prediction-Market-Tools",
            family="research_index",
            priority=98,
            role="curated research index, used for documentation and idea classification",
            target_modules=("docs/research",),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_awesome_prediction_tools_index",
                    name="External Awesome Prediction Market Tools index",
                    kind=StrategyKind.RAG_EVIDENCE_CONTEXT,
                    params={"source_priority": 98, "research_index": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="08_polyterm",
            url="https://github.com/NYTEMODEONLY/polyterm",
            family="terminal_ops",
            priority=82,
            role="terminal UX and bot operations adapted to local launcher/status tooling",
            target_modules=("clitools", "ui/local_commands"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_polyterm_terminal_ops",
                    name="External PolyTerm terminal operations",
                    kind=StrategyKind.STRATEGY_ENSEMBLE,
                    params={"source_priority": 82, "terminal_ops": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="09_mlmodelpoly",
            url="https://github.com/txbabaxyz/mlmodelpoly",
            family="ml_shadow_model",
            priority=40,
            role="ML scoring pattern adapted as shadow-only local model",
            target_modules=("ml/model", "ml/inference", "calibration"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_mlmodelpoly_shadow_score",
                    name="External mlmodelpoly shadow score",
                    kind=StrategyKind.SHADOW_MODEL,
                    params={"source_priority": 40, "shadow_only": True, "requires_closed_trade_training": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="10_polyrec",
            url="https://github.com/txbabaxyz/polyrec",
            family="recommendation_shadow_model",
            priority=42,
            role="recommendation model pattern adapted to wallet/coin ranking shadow mode",
            target_modules=("ml/model", "wallets/leaderboard_robustness"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_polyrec_shadow_recommender",
                    name="External polyrec shadow recommender",
                    kind=StrategyKind.SHADOW_MODEL,
                    params={"source_priority": 42, "wallet_coin_recommender": True, "shadow_only": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="11_prediction_market_backtesting",
            url="https://github.com/evan-kolberg/prediction-market-backtesting",
            family="backtesting_methodology",
            priority=32,
            role="backtesting experiment discipline and anti-lookahead controls",
            target_modules=("backtest/experiment_runner", "backtest/no_lookahead_guard"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_prediction_market_backtesting_guard",
                    name="External prediction-market backtesting guard",
                    kind=StrategyKind.STRATEGY_ENSEMBLE,
                    params={"source_priority": 32, "backtest_guard": True, "no_lookahead_guard": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="12_polybot",
            url="https://github.com/ent0n29/polybot",
            family="lightweight_bot_rules",
            priority=62,
            role="simple rule bot adapted as lightweight signal sanity check",
            target_modules=("signals/entry_quality_gate",),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_polybot_lightweight_rules",
                    name="External polybot lightweight rules",
                    kind=StrategyKind.DIRECTION_HUNT,
                    params={"source_priority": 62, "lightweight_rules": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="13_polymarket_agents",
            url="https://github.com/Polymarket/agents",
            family="agent_framework_research",
            priority=78,
            role="agent patterns adapted to local explanation/research path, not hot-path execution",
            target_modules=("research/ollama_advisor", "agent_tools"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_polymarket_agents_research_path",
                    name="External Polymarket agents research path",
                    kind=StrategyKind.RAG_EVIDENCE_CONTEXT,
                    params={"source_priority": 78, "agent_framework": True, "hot_path": False},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="14_tradingview_lightweight_charts",
            url="https://github.com/tradingview/lightweight-charts",
            family="charting_runtime",
            priority=68,
            role="charting UX patterns for simulation metagraph and market views",
            target_modules=("ui/static", "ui/charts"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_tradingview_chart_runtime",
                    name="External TradingView lightweight chart runtime",
                    kind=StrategyKind.STRATEGY_ENSEMBLE,
                    params={"source_priority": 68, "charting_runtime": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="28_jackhuang166_hyberliquid_arbitrage_bot",
            url="https://github.com/Jackhuang166/hyberliquid-arbitrage-bot",
            family="hyperliquid_arbitrage",
            priority=12,
            role="Hyperliquid arbitrage spread detection adapted to paper-only edge checks",
            target_modules=("arbitrage", "edge/edge_calculator", "connectors/hyperliquid_readonly"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_jack_hl_arbitrage_spread",
                    name="External Jack Hyperliquid arbitrage spread",
                    kind=StrategyKind.ARBITRAGE_SIM,
                    params={"source_priority": 12, "hyperliquid_native": True, "spread_edge_required": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="29_jackhuang166_hyberliquid_arbitrage",
            url="https://github.com/Jackhuang166/hyberliquid-arbitrage",
            family="hyperliquid_arbitrage_alt",
            priority=13,
            role="alternate Hyperliquid arbitrage patterns adapted to source reconciliation",
            target_modules=("arbitrage", "signals/source_reconcile"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_jack_hl_arbitrage_alt",
                    name="External Jack Hyperliquid arbitrage alt",
                    kind=StrategyKind.ARBITRAGE_SIM,
                    params={"source_priority": 13, "hyperliquid_native": True, "reconcile_sources": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="30_rustjesty_hyperliquid_drift_arbitrage_bot",
            url="https://github.com/rustjesty/hyperliquid-drift-arbitrage-bot",
            family="hyperliquid_drift_arbitrage",
            priority=18,
            role="Hyperliquid/Drift spread and funding comparison adapted to local paper simulation",
            target_modules=("funding", "arbitrage", "copy_fidelity/exec_cost_model"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_hl_drift_funding_spread",
                    name="External Hyperliquid Drift funding spread",
                    kind=StrategyKind.SPREAD_FARM,
                    params={"source_priority": 18, "funding_spread_required": True, "cross_venue_paper_only": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="31_notlelouch_arbibot",
            url="https://github.com/notlelouch/ArbiBot",
            family="cross_exchange_arbitrage",
            priority=24,
            role="cross-exchange arbitrage ranking adapted to Hyperliquid price-discrepancy panels",
            target_modules=("arbitrage", "market_data/multi_source_price_stream"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_arbibot_cross_exchange_spread",
                    name="External ArbiBot cross-exchange spread",
                    kind=StrategyKind.ARBITRAGE_SIM,
                    params={"source_priority": 24, "cross_exchange_spread": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="32_gajesh2007_funding_arb_bot",
            url="https://github.com/gajesh2007/funding-arb-bot",
            family="funding_arbitrage",
            priority=19,
            role="funding-rate arbitrage patterns mapped to paper-only funding edge",
            target_modules=("funding", "edge/edge_calculator"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_funding_arb_basis",
                    name="External funding arbitrage basis",
                    kind=StrategyKind.SPREAD_FARM,
                    params={"source_priority": 19, "funding_basis_required": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="33_hummingbot",
            url="https://github.com/hummingbot/hummingbot",
            family="market_making_framework",
            priority=26,
            role="market-making framework concepts adapted to paper-only quote and liquidity simulation",
            target_modules=("market_making", "paper_trading/liquidity_route_simulator", "strategies/library"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_hummingbot_market_making_framework",
                    name="External Hummingbot market-making framework",
                    kind=StrategyKind.MARKET_MAKING_SIM,
                    params={"source_priority": 26, "market_making_framework": True, "paper_quotes_only": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="34_drakkar_triangular_arbitrage",
            url="https://github.com/Drakkar-Software/Triangular-Arbitrage",
            family="triangular_arbitrage",
            priority=23,
            role="triangular arbitrage graph pattern adapted to Hyperliquid synthetic route checks",
            target_modules=("arbitrage/triangular", "backtest/book_replay"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_drakkar_triangular_arbitrage",
                    name="External Drakkar triangular arbitrage",
                    kind=StrategyKind.ARBITRAGE_SIM,
                    params={"source_priority": 23, "triangular_graph": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="35_enarjord_passivbot",
            url="https://github.com/enarjord/passivbot",
            family="grid_risk_management",
            priority=28,
            role="grid/DCA risk concepts adapted to constrained local paper sizing",
            target_modules=("risk/tiered_copy_sizing", "paper_trading/position_tracking"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_passivbot_grid_risk",
                    name="External passivbot grid risk",
                    kind=StrategyKind.DCA_SIM,
                    params={"source_priority": 28, "grid_risk": True, "max_exposure_required": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="36_pydevtop_interexchange_arbitrage_bot",
            url="https://github.com/pydevtop/interexchange-arbitrage-bot",
            family="interexchange_arbitrage",
            priority=27,
            role="interexchange spread detection adapted to multi-source paper reconciliation",
            target_modules=("arbitrage", "market_data/multi_source_price_stream"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_interexchange_arbitrage",
                    name="External interexchange arbitrage",
                    kind=StrategyKind.ARBITRAGE_SIM,
                    params={"source_priority": 27, "interexchange_spread": True},
                ),
            ),
        ),
        ExternalRepoSpec(
            local_id="37_ramilexe_crypto_arbitrage_bot",
            url="https://github.com/ramilexe/crypto-arbitrage-bot",
            family="crypto_arbitrage",
            priority=29,
            role="crypto arbitrage spread model adapted to Hyperliquid paper opportunity ranking",
            target_modules=("arbitrage", "edge/edge_calculator"),
            profiles=(
                ExternalStrategyProfileSpec(
                    profile_id="ext_crypto_arbitrage_spread",
                    name="External crypto arbitrage spread",
                    kind=StrategyKind.ARBITRAGE_SIM,
                    params={"source_priority": 29, "crypto_spread": True},
                ),
            ),
        ),
    )


def project_root_from_here() -> Path:
    return Path(__file__).resolve().parents[3]


def external_repo_root(project_root: Path | None = None) -> Path:
    return (project_root or project_root_from_here()) / REPO_ROOT_RELATIVE


def external_repo_manifest_path(project_root: Path | None = None) -> Path:
    return external_repo_root(project_root) / MANIFEST_NAME


def external_repo_manifest_candidates(project_root: Path | None = None) -> tuple[Path, ...]:
    root = external_repo_root(project_root)
    candidates = [external_repo_manifest_path(project_root)]
    try:
        candidates.extend(root.glob("EXTERNAL_REPOS_MANIFEST_*.json"))
    except OSError:
        pass
    return tuple(
        sorted(
            {path for path in candidates if path.exists()},
            key=lambda path: path.stat().st_mtime if path.exists() else 0,
            reverse=True,
        )
    )


def load_external_repo_manifest(project_root: Path | None = None) -> dict[str, dict[str, Any]]:
    raw: Any = None
    for path in external_repo_manifest_candidates(project_root):
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            break
        except (OSError, json.JSONDecodeError):
            raw = None
    if raw is None:
        return {}
    if not isinstance(raw, list):
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            rows[str(item["id"])] = item
    return rows


def discover_external_repo_capabilities(project_root: Path | None = None) -> tuple[ExternalRepoCapability, ...]:
    root = external_repo_root(project_root)
    manifest = load_external_repo_manifest(project_root)
    capabilities: list[ExternalRepoCapability] = []
    for spec in sorted(requested_external_repos(), key=lambda row: row.priority):
        row = manifest.get(spec.local_id, {})
        status = str(row.get("status") or ("PRESENT_NO_MANIFEST" if (root / spec.local_id).exists() else "MISSING"))
        path = Path(str(row.get("target") or root / spec.local_id))
        installed = status in INSTALLED_STATUSES and path.exists()
        unavailable_reason = "" if installed else str(row.get("message") or status or "MISSING")
        capabilities.append(
            ExternalRepoCapability(
                local_id=spec.local_id,
                url=spec.url,
                family=spec.family,
                priority=spec.priority,
                role=spec.role,
                installed=installed,
                status=status,
                path=str(path),
                branch=_none_or_str(row.get("branch")),
                commit=_none_or_str(row.get("commit")),
                file_count=_safe_int(row.get("file_count")),
                size_bytes=_safe_int(row.get("size_bytes")),
                unavailable_reason=unavailable_reason,
                target_modules=spec.target_modules,
                profile_ids=tuple(profile.profile_id for profile in spec.profiles),
            )
        )
    return tuple(capabilities)


def external_strategy_definitions(project_root: Path | None = None) -> tuple[StrategyDefinition, ...]:
    caps = {cap.local_id: cap for cap in discover_external_repo_capabilities(project_root)}
    definitions: list[StrategyDefinition] = []
    for spec in sorted(requested_external_repos(), key=lambda row: row.priority):
        cap = caps[spec.local_id]
        for profile in spec.profiles:
            definitions.append(
                make_strategy(
                    strategy_id=profile.profile_id,
                    version=1,
                    kind=profile.kind,
                    name=profile.name,
                    description=f"Priority paper adapter for {spec.url}",
                    enabled=cap.installed,
                    tags=(
                        "external-github-priority",
                        "upstream-preserved",
                        "hyperliquid-paper-adapter",
                        spec.family,
                    ),
                    params={
                        **profile.params,
                        "source_repo": spec.url,
                        "source_local_id": spec.local_id,
                        "source_path": cap.path,
                        "source_status": cap.status,
                        "source_commit": cap.commit or "",
                        "upstream_preserved": True,
                        "paper_only": True,
                        "read_only": True,
                        "direct_execution": False,
                        "external_action": False,
                        "priority_over_internal": True,
                    },
                )
            )
    return tuple(definitions)


def external_strategy_catalog() -> tuple[str, ...]:
    return tuple(
        profile.profile_id
        for spec in sorted(requested_external_repos(), key=lambda row: row.priority)
        for profile in spec.profiles
    )


def register_external_github_profiles(
    registry: PaperStrategyRegistry,
    *,
    project_root: Path | None = None,
    replace: bool = True,
) -> int:
    count = 0
    for definition in external_strategy_definitions(project_root):
        if not definition.enabled:
            continue
        registry.register(definition, replace=replace)
        count += 1
    return count


def build_external_github_bridge_payload(project_root: Path | None = None) -> dict[str, object]:
    caps = discover_external_repo_capabilities(project_root)
    definitions = external_strategy_definitions(project_root)
    enabled = [definition for definition in definitions if definition.enabled]
    unavailable = [cap for cap in caps if not cap.installed]
    return {
        "available": bool(caps),
        "mode": "EXTERNAL_REPOS_PRESERVED_PRIORITY_PAPER_ADAPTER",
        "priority_over_internal": True,
        "direct_external_execution": False,
        "paper_only": True,
        "read_only": True,
        "installed_count": sum(1 for cap in caps if cap.installed),
        "unavailable_count": len(unavailable),
        "enabled_strategy_count": len(enabled),
        "manifest_path": str(external_repo_manifest_path(project_root)),
        "repo_root": str(external_repo_root(project_root)),
        "repos": [cap.as_dict() for cap in caps],
        "priority_strategy_catalog": [definition.strategy_id for definition in enabled],
        "disabled_strategy_catalog": [definition.strategy_id for definition in definitions if not definition.enabled],
        "notes": (
            "Upstream repos stay installed unchanged under runtime/research. "
            "HyperSmart uses local paper adapters only."
        ),
    }


def _safe_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _none_or_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


__all__ = [
    "ExternalRepoCapability",
    "ExternalRepoSpec",
    "ExternalStrategyProfileSpec",
    "build_external_github_bridge_payload",
    "discover_external_repo_capabilities",
    "external_repo_manifest_path",
    "external_repo_root",
    "external_strategy_catalog",
    "external_strategy_definitions",
    "load_external_repo_manifest",
    "register_external_github_profiles",
    "requested_external_repos",
]
