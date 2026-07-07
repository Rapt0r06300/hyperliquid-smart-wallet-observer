"""#102: a strategy's PaperIntent only becomes actionable AFTER the risk engine.
Proves the StrategyRegistry -> PaperIntent -> approve_with_risk -> actionable chain."""

from hl_observer.storage.run_context import RunContext
from hl_observer.strategies import (
    CopyFollowStrategy,
    IntentSide,
    PaperStrategyRegistry,
    approve_with_risk,
    is_actionable,
    make_strategy,
)
from hl_observer.strategies.models import StrategyKind


def test_registry_serves_default_strategy():
    reg = PaperStrategyRegistry()
    reg.register(make_strategy(strategy_id="copy_follow", version=1, kind=StrategyKind.COPY_FOLLOW))
    assert reg.is_usable("copy_follow", context=RunContext.LIVE)


def test_strategy_intent_needs_risk_then_actionable():
    strat = CopyFollowStrategy.default()
    intent = strat.propose(coin="BTC", leader_side=IntentSide.LONG,
                           edge_net_bps=25.0, signal_age_ms=2000, now_ms=1)
    assert intent is not None and is_actionable(intent) is False     # bare intent never actionable
    rejected = approve_with_risk(intent, lambda i: (False, ["RISK"]))
    assert is_actionable(rejected) is False                           # risk says no
    approved = approve_with_risk(intent, lambda i: (True, []))
    assert is_actionable(approved) is True                            # only now actionable


def test_stale_or_thin_intent_not_produced():
    strat = CopyFollowStrategy.default()
    assert strat.propose(coin="BTC", leader_side=IntentSide.LONG, edge_net_bps=25.0,
                         signal_age_ms=10**9, now_ms=1) is None      # stale -> no intent
