from __future__ import annotations

from hl_observer.features import build_market_feature_vector
from hl_observer.hyperliquid.schemas import RiskDecision, SignalCandidate, SignalDecision
from hl_observer.ledger import build_evidence_entry, find_evidence, load_evidence_ledger, write_evidence_ledger
from hl_observer.paper.paper_executor import PaperExecutor


def _signal() -> SignalCandidate:
    return SignalCandidate(
        id="sig-1",
        source_wallet="0x" + "a" * 40,
        coin="BTC",
        side="long",
        signal_type="open",
        observed_price=100.25,
        timestamp_ms=1_800_000_200_000,
        signal_age_ms=300,
        wallet_score=90,
        signal_score=80,
        edge_remaining_bps=42.0,
        estimated_spread_bps=4.0,
        estimated_slippage_bps=3.0,
        orderbook_depth_usdc=25_000,
    )


def _market():
    return build_market_feature_vector(
        timestamp_ms=1_800_000_200_000,
        source_ts_ms=1_800_000_199_900,
        coin="BTC",
        l2_book={
            "levels": [
                [{"px": "100.0", "sz": "20"}],
                [{"px": "100.5", "sz": "20"}],
            ]
        },
        all_mids={"BTC": "100.25"},
        candles=[
            {"c": "100", "h": "100.2", "l": "99.9", "T": "1800000000000"},
            {"c": "100.1", "h": "100.3", "l": "100.0", "T": "1800000060000"},
            {"c": "100.2", "h": "100.4", "l": "100.1", "T": "1800000120000"},
        ],
    )


def test_v9_evidence_chain_links_signal_market_risk_and_paper_order() -> None:
    signal = _signal()
    risk = RiskDecision(
        allowed=True,
        decision=SignalDecision.PAPER_TRADE,
        reasons=["all paper gates passed"],
        gates={"edge_remaining": True},
    )
    paper = PaperExecutor().submit(signal, risk, notional_usdc=100.0)
    market = _market()

    entry = build_evidence_entry(run_id="run/1", signal=signal, market=market, risk_decision=risk, paper_order=paper)

    assert entry.decision_type == "PAPER_SIMULATED"
    assert entry.feature_hash == market.feature_hash
    assert entry.paper_order_id == paper.order_id
    assert entry.paper_notional_usdc == 100.0
    assert entry.evidence_hash.startswith("ev:")
    assert "all paper gates passed" in entry.risk_reasons


def test_v9_evidence_chain_records_no_trade_without_market_features() -> None:
    signal = _signal()
    risk = RiskDecision(
        allowed=False,
        decision=SignalDecision.REJECT_EDGE_TOO_SMALL,
        reasons=["edge remaining below minimum"],
        gates={"edge_remaining": False},
    )

    entry = build_evidence_entry(run_id="run/2", signal=signal, market=None, risk_decision=risk)

    assert entry.decision_type == "NO_TRADE"
    assert entry.feature_hash is None
    assert entry.market_quality_mode == "NO_TRADE"
    assert entry.market_quality_reasons == ("MARKET_FEATURES_MISSING",)
    assert entry.risk_decision == "REJECT_EDGE_TOO_SMALL"
    assert entry.evidence_hash.startswith("ev:")


def test_v9_evidence_hash_is_reproducible_and_roundtrips(tmp_path) -> None:
    signal = _signal()
    risk = RiskDecision(
        allowed=True,
        decision=SignalDecision.PAPER_TRADE,
        reasons=["all paper gates passed"],
        gates={"edge_remaining": True},
    )
    market = _market()
    paper = PaperExecutor().submit(signal, risk, notional_usdc=50.0)

    entry_1 = build_evidence_entry(run_id="same", signal=signal, market=market, risk_decision=risk, paper_order=paper)
    entry_2 = build_evidence_entry(run_id="same", signal=signal, market=market, risk_decision=risk, paper_order=paper)
    assert entry_1.evidence_hash == entry_2.evidence_hash

    result = write_evidence_ledger([entry_1], tmp_path, run_id="same/run")
    loaded = load_evidence_ledger(result.json_path)
    row = find_evidence(loaded, "sig-1")

    assert result.entries == 1
    assert result.csv_path.exists()
    assert row is not None
    assert row["evidence_hash"] == entry_1.evidence_hash
    assert row["feature_hash"] == market.feature_hash
