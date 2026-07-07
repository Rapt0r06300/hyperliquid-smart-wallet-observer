import importlib

import pytest

from hl_observer.storage.run_context import RunContext
from hl_observer.strategies import (
    ApprovedPaperIntent,
    CopyFollowStrategy,
    IntentAction,
    IntentSide,
    MarketMakingSimStrategy,
    PaperIntent,
    PaperStrategyRegistry,
    StrategyKind,
    approve_with_risk,
    is_actionable,
    make_strategy,
)


# ---- registry basics ----

def test_register_versions_and_latest():
    reg = PaperStrategyRegistry()
    reg.register(make_strategy(strategy_id="copy", version=1, kind=StrategyKind.COPY_FOLLOW))
    reg.register(make_strategy(strategy_id="copy", version=2, kind=StrategyKind.COPY_FOLLOW))
    assert reg.versions("copy") == [1, 2]
    assert reg.get("copy").version == 2          # latest by default
    assert reg.get("copy", version=1).version == 1


def test_duplicate_version_rejected_unless_replace():
    reg = PaperStrategyRegistry()
    reg.register(make_strategy(strategy_id="mm", version=1, kind=StrategyKind.MARKET_MAKING_SIM))
    with pytest.raises(ValueError):
        reg.register(make_strategy(strategy_id="mm", version=1, kind=StrategyKind.MARKET_MAKING_SIM))
    reg.register(
        make_strategy(strategy_id="mm", version=1, kind=StrategyKind.MARKET_MAKING_SIM, name="v1b"),
        replace=True,
    )
    assert reg.get("mm").name == "v1b"


def test_deny_by_default_unregistered_and_disabled():
    reg = PaperStrategyRegistry()
    assert reg.is_usable("ghost", context=RunContext.LIVE) is False
    reg.register(make_strategy(strategy_id="off", version=1, kind=StrategyKind.COPY_FOLLOW, enabled=False))
    assert reg.is_usable("off", context=RunContext.LIVE) is False


def test_for_context_filters_by_allowed_contexts():
    reg = PaperStrategyRegistry()
    reg.register(make_strategy(
        strategy_id="backtest_only", version=1, kind=StrategyKind.ARBITRAGE_SIM,
        contexts=[RunContext.BACKTEST],
    ))
    assert reg.is_usable("backtest_only", context=RunContext.BACKTEST) is True
    assert reg.is_usable("backtest_only", context=RunContext.LIVE) is False
    assert [d.strategy_id for d in reg.for_context(RunContext.LIVE)] == []


def test_params_are_immutable_and_hashed():
    d = make_strategy(strategy_id="x", version=1, kind=StrategyKind.COPY_FOLLOW,
                      params={"min_edge_bps": 10})
    snapshot = d.params
    snapshot["min_edge_bps"] = 999          # mutating the copy must not leak
    assert d.params["min_edge_bps"] == "10"
    assert len(d.params_hash) == 16


# ---- mandated V12 tests (roadmap §443) ----

def test_strategy_registry_has_no_external_action():
    pub = {n for n in dir(PaperStrategyRegistry) if not n.startswith("_")}
    for bad in ("submit", "place", "order", "sign", "send", "execute", "deposit", "withdraw"):
        assert not any(bad in n.lower() for n in pub), f"forbidden surface: {bad}"
    mod = importlib.import_module("hl_observer.strategies.paper_registry")
    for bad in ("submit", "place_order", "send_order", "sign"):
        assert not hasattr(mod, bad)


def test_copy_strategy_builds_paper_intent_only():
    strat = CopyFollowStrategy.default()
    intent = strat.propose(
        coin="BTC", leader_side=IntentSide.LONG, edge_net_bps=25.0,
        signal_age_ms=5_000, now_ms=1_000,
    )
    assert isinstance(intent, PaperIntent)
    assert intent.simulation_only is True
    assert intent.requires_risk_approval is True
    assert intent.action is IntentAction.OPEN and intent.side is IntentSide.LONG
    # stale / thin-edge => no intent (NO_TRADE)
    assert strat.propose(coin="BTC", leader_side=IntentSide.LONG, edge_net_bps=25.0,
                         signal_age_ms=999_999, now_ms=1) is None
    assert strat.propose(coin="BTC", leader_side=IntentSide.LONG, edge_net_bps=1.0,
                         signal_age_ms=100, now_ms=1) is None


def test_market_making_strategy_simulates_only():
    strat = MarketMakingSimStrategy.default()
    intent = strat.propose(coin="ETH", bid_depth=80.0, ask_depth=20.0, now_ms=1)
    assert isinstance(intent, PaperIntent)
    assert intent.simulation_only is True
    assert intent.side is IntentSide.LONG  # bid-heavy book
    # no execution method on the strategy object
    pub = {n for n in dir(strat) if not n.startswith("_")}
    assert not any(b in n.lower() for n in pub for b in ("submit", "place", "send", "execute"))
    # balanced book => no intent
    assert strat.propose(coin="ETH", bid_depth=50.0, ask_depth=50.0, now_ms=1) is None


def test_every_strategy_goes_through_risk_engine():
    strat = CopyFollowStrategy.default()
    intent = strat.propose(coin="BTC", leader_side=IntentSide.LONG, edge_net_bps=25.0,
                           signal_age_ms=1_000, now_ms=1)
    # a bare intent is NOT actionable
    assert is_actionable(intent) is False
    # only after passing the risk engine, and only if risk says OK
    rejected = approve_with_risk(intent, lambda i: (False, ["RISK_BLOCK"]))
    assert is_actionable(rejected) is False
    approved = approve_with_risk(intent, lambda i: (True, []))
    assert isinstance(approved, ApprovedPaperIntent) and is_actionable(approved) is True
    # you cannot fabricate an approval without going through approve_with_risk
    with pytest.raises(ValueError):
        ApprovedPaperIntent(intent=intent, risk_ok=True)


def test_paper_intent_cannot_disable_simulation():
    with pytest.raises(ValueError):
        PaperIntent(strategy_id="x", coin="BTC", side=IntentSide.LONG,
                    action=IntentAction.OPEN, simulation_only=False)
