import json

from hl_observer.connectors.hyperliquid_readonly import HyperliquidReadonlyConnector
from hl_observer.connectors.public_research import PublicResearchConnector
import hl_observer.connectors.base as base_mod
import hl_observer.connectors.hyperliquid_readonly as hl_mod
from hl_observer.research.decision_explainer import explain_decision
from hl_observer.research.wallet_thesis import build_wallet_thesis
from hl_observer.research.rag_evidence import RagEvidenceStore, affects_decision


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
