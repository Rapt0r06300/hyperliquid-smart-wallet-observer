import json

from hl_observer.connectors.hyperliquid_readonly import HyperliquidReadonlyConnector
from hl_observer.connectors.public_research import PublicResearchConnector
import hl_observer.connectors.base as base_mod
import hl_observer.connectors.hyperliquid_readonly as hl_mod
from hl_observer.paper_trading.paper_connector import PaperSimConnector
from hl_observer.research.decision_explainer import explain_decision
from hl_observer.research.wallet_thesis import build_wallet_thesis
from hl_observer.research.rag_evidence import RagEvidenceStore, affects_decision
from hl_observer.strategies import IntentAction, IntentSide, PaperIntent, approve_with_risk


def test_connectors_normalize_to_common_model():
    hl = HyperliquidReadonlyConnector().normalize_fill({"coin": "btc", "side": "b", "px": "60000", "sz": "0.1", "time": 5})
    pub = PublicResearchConnector().normalize_fill({"symbol": "eth", "direction": "short", "price": 3000, "amount": 1, "ts": 9})
    assert set(hl) == set(pub) == {"coin", "side", "px", "sz", "ts_ms", "source"}
    assert hl["coin"] == "BTC" and hl["side"] == "LONG" and hl["source"] == "hyperliquid"
    assert pub["coin"] == "ETH" and pub["side"] == "SHORT"
    json.dumps([hl, pub])


def test_connectors_have_no_execution_surface():
    for mod in (base_mod, hl_mod):
        for n in dir(mod):
            if n.startswith("_"):
                continue
            assert not any(b in n.lower() for b in ("submit", "place", "order", "sign", "send", "deposit"))


def test_hyperliquid_connector_builds_readonly_snapshot():
    connector = HyperliquidReadonlyConnector()
    snapshot = connector.snapshot_from_payload(
        observed_at_ms=123,
        fills=({"coin": "hype", "dir": "Open Long", "px": "25", "sz": "2", "time": 120},),
        positions=({"coin": "HYPE", "szi": "2"},),
        mids={"hype": 25.1},
        public_flows=({"coin": "HYPE", "side": "buy"},),
        raw={"kind": "fixture"},
        evidence_refs=("fetch:1",),
    )

    assert snapshot.read_only is True
    assert snapshot.source == "hyperliquid"
    assert snapshot.fills[0]["coin"] == "HYPE"
    assert snapshot.fills[0]["side"] == "LONG"
    assert snapshot.mids == {"HYPE": 25.1}
    payload = snapshot.as_dict()
    assert payload["read_only"] is True
    assert payload["evidence_refs"] == ["fetch:1"]


def test_paper_sim_connector_requires_risk_approved_intent_and_records_evidence():
    intent = PaperIntent(
        strategy_id="copy_follow",
        coin="HYPE",
        side=IntentSide.LONG,
        action=IntentAction.OPEN,
        target_notional_usdt=50.0,
        confidence=0.8,
        reasons=("cluster=3",),
        created_at_ms=100,
    )
    connector = PaperSimConnector()

    rejected = connector.apply_intent(
        approve_with_risk(intent, lambda i: (False, ["RISK_BLOCK"])),
        mid_price=25.0,
        top_depth_usdt=10_000.0,
        observed_at_ms=101,
    )
    assert rejected.accepted is False
    assert "RISK_NOT_APPROVED" in rejected.reason_codes
    assert rejected.as_dict()["external_action"] is False

    accepted = connector.apply_intent(
        approve_with_risk(intent, lambda i: (True, [])),
        mid_price=25.0,
        top_depth_usdt=10_000.0,
        observed_at_ms=102,
    )
    assert accepted.accepted is True
    assert accepted.fill is not None
    assert accepted.fill.coin == "HYPE"
    assert accepted.fill.fill_price > 25.0
    assert accepted.evidence["paper_only"] is True
    assert accepted.evidence["external_action"] is False
    assert len(connector.fills) == 1


def test_paper_sim_connector_refuses_missed_depth_fill():
    intent = PaperIntent(
        strategy_id="copy_follow",
        coin="HYPE",
        side=IntentSide.LONG,
        action=IntentAction.OPEN,
        target_notional_usdt=1_000.0,
        confidence=0.8,
    )
    connector = PaperSimConnector()
    result = connector.apply_intent(
        approve_with_risk(intent, lambda i: (True, [])),
        mid_price=25.0,
        top_depth_usdt=10.0,
        observed_at_ms=200,
        asks=((25.1, 1.0),),  # roughly 25 USDT available, far below request
        min_fill_ratio=0.85,
    )

    assert result.accepted is False
    assert "MISSED_FILL" in result.reason_codes
    assert result.evidence["depth_execution"]["fill_ratio"] < 0.85
    assert len(connector.fills) == 0


def test_paper_sim_connector_uses_depth_average_for_fill_price():
    intent = PaperIntent(
        strategy_id="copy_follow",
        coin="HYPE",
        side=IntentSide.LONG,
        action=IntentAction.OPEN,
        target_notional_usdt=100.0,
        confidence=0.8,
    )
    connector = PaperSimConnector()
    result = connector.apply_intent(
        approve_with_risk(intent, lambda i: (True, [])),
        mid_price=25.0,
        top_depth_usdt=500.0,
        observed_at_ms=201,
        asks=((25.0, 2.0), (25.5, 3.0)),
        min_fill_ratio=0.85,
    )

    assert result.accepted is True
    assert result.fill is not None
    assert result.evidence["depth_execution"]["reason"] == "FILLED"
    assert result.evidence["depth_execution"]["average_fill_price"] > 25.0
    assert result.fill.fill_price > result.evidence["depth_execution"]["average_fill_price"]


def test_decision_explainer_uses_evidence_refs_and_is_read_only():
    out = explain_decision({"reason_code": "SIGNAL_TOO_OLD", "dashboard_message": "trop vieux"},
                           evidence_refs=["fetch:abc", "feature:xyz"])
    assert out["evidence_refs"] == ["fetch:abc", "feature:xyz"]
    assert out["changes_decision"] is False and out["context_only"] is True


def test_wallet_thesis_requires_sources():
    assert build_wallet_thesis(wallet="0xabc", stats={"winrate": 0.6}, sources=[]) is None
    th = build_wallet_thesis(wallet="0xabcdef0000", stats={"winrate": 0.6, "total_pnl_usdc": 5000}, sources=["hl_fills"])
    assert th is not None and th["sources"] == ["hl_fills"]


def test_rag_is_context_only():
    assert affects_decision() is False
    store = RagEvidenceStore()
    store.add(ref="r1", text="BTC whale accumulation observed")
    hits = store.recall("whale")
    assert hits and hits[0]["context_only"] is True
