"""GitHub idea distillation matrix for HyperSmart.

External repositories are research inputs, not runtime trade engines. This
module records which ideas are worth porting into the single HyperSmart pipeline:

source data -> features -> signal -> risk -> PaperEngine -> ledger -> dashboard.

No upstream repo code is executed from here, and no external profile can bypass
the canonical risk/PaperEngine path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DistilledGithubIdea:
    repo_id: str
    repo_name: str
    priority: int
    pattern: str
    hyperliquid_port: str
    target_modules: tuple[str, ...]
    activation_rule: str
    status: str = "SHADOW_RESEARCH"
    direct_runtime_execution: bool = False


def priority_distillation_matrix() -> tuple[DistilledGithubIdea, ...]:
    """Return the first-priority GitHub distillation queue.

    The list is intentionally small and biased toward ideas that can improve the
    current Hyperliquid paper simulation without importing incompatible
    Polymarket/Solana/CEX runtimes.
    """

    return (
        DistilledGithubIdea(
            repo_id="17_rezzecup_whale_wallet_mirror_copy_trader",
            repo_name="whale-wallet-mirror-copy-trader",
            priority=1,
            pattern="whale mirror consensus, copy-lag awareness, proportional paper sizing",
            hyperliquid_port="cluster fresh leader deltas by coin/side before opening paper positions",
            target_modules=(
                "hl_observer.copying.copy_conflict_resolver",
                "hl_observer.risk.risk_engine_v3",
                "hl_observer.paper_trading",
            ),
            activation_rule="activate only after replay proves positive profit factor after fees and no-lookahead checks",
        ),
        DistilledGithubIdea(
            repo_id="15_chaininsighter_solana_copy_trading_bot",
            repo_name="Solana-Copy-trading-bot",
            priority=2,
            pattern="leader discovery, wallet-following latency budget, session evidence logs",
            hyperliquid_port="measure leader fill age and reject stale copy attempts before risk approval",
            target_modules=(
                "hl_observer.copying.latency",
                "hl_observer.logs",
                "hl_observer.dashboard",
            ),
            activation_rule="shadow until live logs show sub-second freshness and replay PF improves",
        ),
        DistilledGithubIdea(
            repo_id="28_jackhuang166_hyberliquid_arbitrage_bot",
            repo_name="hyberliquid-arbitrage-bot",
            priority=3,
            pattern="cross-venue discrepancy, spread sanity, source reconciliation",
            hyperliquid_port="read-only discrepancy signal used as evidence, never direct order source",
            target_modules=(
                "hl_observer.arbitrage",
                "hl_observer.source_health",
                "hl_observer.features",
            ),
            activation_rule="activate only when both sources are live and discrepancy survives conservative fees",
        ),
        DistilledGithubIdea(
            repo_id="22_freqtrade",
            repo_name="freqtrade",
            priority=4,
            pattern="dry-run discipline, walk-forward evaluation, parameter guards",
            hyperliquid_port="replay A/B flags and enable only settings that improve out-of-sample PF",
            target_modules=(
                "hl_observer.backtest",
                "hl_observer.experiments",
                "hl_observer.risk",
            ),
            activation_rule="no live flag promotion without walk-forward and anti-overfit report",
        ),
        DistilledGithubIdea(
            repo_id="33_hummingbot",
            repo_name="hummingbot",
            priority=5,
            pattern="connector abstraction, market microstructure discipline, inventory limits",
            hyperliquid_port="normalize exchange adapters and keep inventory/risk caps independent from signals",
            target_modules=(
                "hl_observer.connectors",
                "hl_observer.risk",
                "hl_observer.paper_trading",
            ),
            activation_rule="port abstractions only; no connector may place real orders in HyperSmart runtime",
        ),
        DistilledGithubIdea(
            repo_id="35_enarjord_passivbot",
            repo_name="passivbot",
            priority=6,
            pattern="position sizing, exposure caps, grid/risk discipline",
            hyperliquid_port="use sizing ideas as capped paper risk rules, not autonomous averaging-down",
            target_modules=(
                "hl_observer.risk.sizing",
                "hl_observer.exits",
                "hl_observer.paper_trading",
            ),
            activation_rule="shadow only until replay proves drawdown reduction; martingale-like behavior stays blocked",
        ),
        DistilledGithubIdea(
            repo_id="11_prediction_market_backtesting",
            repo_name="prediction-market-backtesting",
            priority=7,
            pattern="event replay, no-lookahead experiments, reproducible reports",
            hyperliquid_port="standardize ledger replay and compare live paper to replay paper",
            target_modules=(
                "hl_observer.backtest.replay",
                "hl_observer.paper_ledger",
                "hl_observer.reports",
            ),
            activation_rule="always active for validation; never used to force a trade",
            status="VALIDATION",
        ),
        DistilledGithubIdea(
            repo_id="13_polymarket_agents",
            repo_name="Polymarket agents",
            priority=8,
            pattern="agent as analyst, not hot-path executor",
            hyperliquid_port="LLM/Ollama explanations stay shadow-only and cannot approve orders",
            target_modules=(
                "hl_observer.ai",
                "hl_observer.evidence",
                "hl_observer.dashboard",
            ),
            activation_rule="read-only diagnostics only; no AI hot-path authority",
        ),
        DistilledGithubIdea(
            repo_id="14_tradingview_lightweight_charts",
            repo_name="TradingView lightweight-charts",
            priority=9,
            pattern="stable chart primitives and tooltip behavior",
            hyperliquid_port="UI charting only, backed by canonical ledger and real mark prices",
            target_modules=(
                "hl_observer.ui.static",
                "hl_observer.dashboard",
            ),
            activation_rule="active only when chart reads canonical ledger; no synthetic chart points",
            status="UI_ONLY",
        ),
    )


def distillation_status_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for idea in priority_distillation_matrix():
        counts[idea.status] = counts.get(idea.status, 0) + 1
    return counts


__all__ = [
    "DistilledGithubIdea",
    "priority_distillation_matrix",
    "distillation_status_counts",
]
