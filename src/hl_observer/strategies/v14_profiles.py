"""V14 strategy profiles ported from public bot patterns into HyperSmart.

These are parameter bundles, not copied external source. They make the runtime
explicitly reproducible: a session can say which profile drove copy sizing,
freshness, slippage and risk requirements.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.strategies.models import StrategyKind, make_strategy


@dataclass(frozen=True, slots=True)
class V14StrategyProfile:
    profile_id: str
    name: str
    kind: StrategyKind
    params: dict[str, object] = field(default_factory=dict)
    source_patterns: tuple[str, ...] = ()
    paper_only: bool = True
    external_action: bool = False

    def strategy_definition(self):
        return make_strategy(
            strategy_id=self.profile_id,
            version=1,
            kind=self.kind,
            name=self.name,
            params={**self.params, "paper_only": True, "external_action": False},
            tags=("v14", "github-pattern-port", *self.source_patterns),
        )


def v14_default_profiles() -> tuple[V14StrategyProfile, ...]:
    return (
        V14StrategyProfile(
            profile_id="v14_wallet_mirror_conservative",
            name="V14 wallet mirror conservative",
            kind=StrategyKind.COPY_FOLLOW,
            source_patterns=("whale-wallet-mirror", "polymarket-copy-trading", "solana-copy-trading"),
            params={
                "copy_ratio": 0.05,
                "max_mirror_notional_usdt": 50,
                "max_equity_pct": 5,
                "min_same_side_leaders": 2,
                "max_signal_age_ms": 3000,
                "max_slippage_bps": 18,
                "min_wallet_score": 0.55,
                "min_copyability_score": 0.55,
            },
        ),
        V14StrategyProfile(
            profile_id="v14_consensus_fast_path",
            name="V14 consensus fast path",
            kind=StrategyKind.FAST_TIMING,
            source_patterns=("terauss-hot-path", "chaininsighter-latency", "hummingbot-connectors"),
            params={
                "max_signal_age_ms": 1500,
                "min_same_side_leaders": 3,
                "latency_warn_ms": 1000,
                "market_cache_ttl_ms": 750,
                "no_llm_hot_path": True,
            },
        ),
        V14StrategyProfile(
            profile_id="v14_funding_arb_paper",
            name="V14 funding/arbitrage paper",
            kind=StrategyKind.ARBITRAGE_SIM,
            source_patterns=("hyperliquid-arbitrage", "funding-arb", "triangular-arbitrage"),
            params={
                "require_two_sources": True,
                "min_net_edge_bps": 20,
                "max_leg_skew_bps": 25,
                "funding_history_hours": 24,
                "funding_spike_sigma": 2,
                "max_hold_hours": 48,
            },
        ),
        V14StrategyProfile(
            profile_id="v14_framework_risk_pro",
            name="V14 framework risk pro",
            kind=StrategyKind.STRATEGY_ENSEMBLE,
            source_patterns=("freqtrade", "octobot", "hummingbot", "passivbot"),
            params={
                "lookahead_analysis": True,
                "recursive_analysis": True,
                "optimization_local_only": True,
                "equity_hard_stop_pct": 5,
                "drawdown_halt_pct": 8,
                "kelly_enabled": False,
                "kelly_fraction": 0.25,
                "margin_of_safety": 0.85,
            },
        ),
    )


def register_v14_profiles(registry) -> int:
    count = 0
    for profile in v14_default_profiles():
        registry.register(profile.strategy_definition(), replace=True)
        count += 1
    return count


__all__ = ["V14StrategyProfile", "register_v14_profiles", "v14_default_profiles"]
