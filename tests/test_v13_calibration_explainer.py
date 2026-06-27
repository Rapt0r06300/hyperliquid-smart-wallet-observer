from hl_observer.calibration.ledger_calibration_report import build_ledger_calibration_report
from hl_observer.research.local_llm_explainer import explain, rule_based_explanation, ollama_available


def test_calibration_report_buckets_and_brier():
    # well-calibrated-ish: high confidence -> mostly wins, low -> mostly losses
    preds = [(0.9, 1)] * 20 + [(0.8, 1)] * 15 + [(0.2, 0)] * 20 + [(0.1, 0)] * 15
    rep = build_ledger_calibration_report(predictions=preds,
                                          block_reasons={"STALE_SIGNAL": 50, "LIQUIDITY_TOO_LOW": 30})
    assert rep["empty"] is False and rep["n_predictions"] == 70
    assert rep["beats_baseline"] is True            # beats constant 0.5
    assert any(b["count"] > 0 for b in rep["buckets"])
    assert rep["block_reasons"][0]["reason"] == "STALE_SIGNAL"   # sorted by count desc
    assert "décisions" in rep["plain_summary"]


def test_calibration_report_empty_is_honest():
    rep = build_ledger_calibration_report(predictions=[], block_reasons=[])
    assert rep["empty"] is True and rep["brier"] is None and "Pas encore" in rep["plain_summary"]


def test_rule_based_explanation_reject_and_accept():
    rej = rule_based_explanation({"coin": "btc", "direction": "LONG",
        "reason": "STALE_SIGNAL|LIQUIDITY_TOO_LOW", "edge_remaining_bps": 3, "signal_age_ms": 30000})
    assert "BTC LONG écarté" in rej and "trop vieux" in rej and "liquide" in rej
    acc = rule_based_explanation({"coin": "eth", "side": "SHORT",
        "decision_reason": "EDGE_OK_FOR_LOCAL_SIMULATION", "net_edge_bps": 22,
        "signal_age_ms": 4000, "consensus_wallets": 3})
    assert "ETH SHORT retenu" in acc and "3 trader" in acc


def test_explain_degrades_gracefully_without_ollama():
    # Ollama disabled by default -> rule-based, never crashes, offline/context-only
    assert ollama_available() is False
    out = explain({"coin": "SOL", "side": "LONG", "reason": "REJECT_TOO_LATE"})
    assert out["llm_used"] is False and out["source"] == "regles"
    assert out["context_only"] is True and out["hot_path"] is False and out["text"]


def test_explain_cli_builds_items_from_events(tmp_path):
    from hl_observer.research.explain_cli import build_explanations_from_events
    events = [
        {"coin": "SOL", "leader_side": "LONG", "decision_reason": "REJECT_TOO_LATE",
         "observed_at_ms": 2, "signal_age_ms": 30000},
        {"coin": "BTC", "leader_side": "SHORT", "decision_reason": "LIQUIDITY_TOO_LOW",
         "observed_at_ms": 1},
    ]
    out = build_explanations_from_events(events)
    assert len(out["items"]) == 2
    assert out["items"][0]["coin"] == "SOL" and "trop tard" in out["items"][0]["text"]
    assert out["items"][0]["source"] == "regles"      # Ollama off by default
    assert out["ollama_enabled"] is False
