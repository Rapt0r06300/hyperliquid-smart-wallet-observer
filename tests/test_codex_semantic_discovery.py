from hl_observer.research.semantic_discovery import generate_semantic_plans, rank_semantic_plans


def _catalog():
    return {
        "families": {
            "lead_lag": {
                "events": ["external-bbo-move", "trade-burst"],
                "contexts": ["liquid", "volatile"],
                "data_surfaces": ["binance-bbo", "hl-bbo"],
                "temporal_operators": ["lag-100ms", "lag-500ms"],
                "regimes": ["normal", "high-vol"],
                "targets": ["hl-markout"],
                "executions": ["paper-taker"],
            }
        }
    }


def test_generation_is_deterministic_structured_and_deduplicated():
    first = generate_semantic_plans(_catalog(), "lead_lag", 20, 7)
    second = generate_semantic_plans(_catalog(), "lead_lag", 20, 7)
    assert first == second
    assert len({p["semantic_key"] for p in first}) == len(first)
    assert all(p["family"] == "lead_lag" for p in first)


def test_ranking_vetoes_failed_motif_and_returns_diverse_deterministic_shortlist():
    plans = generate_semantic_plans(_catalog(), "lead_lag", 20, 3)
    failed = [{
        "record_id": "PM-1", "family": "lead_lag", "mechanism_signature": plans[0]["mechanism_signature"],
        "context": [plans[0]["context"]], "change_motif": "candidate", "outcome": "FAILURE",
        "evidence_count": 10, "confidence": 0.99, "failure_reason": "no-edge", "success_evidence": None,
        "provenance": "runtime", "certifying": False, "retest_condition": "new-data",
    }, {
        "record_id": "PM-2", "family": "lead_lag", "mechanism_signature": plans[0]["mechanism_signature"],
        "context": [plans[0]["context"]], "change_motif": "candidate", "outcome": "FAILURE",
        "evidence_count": 10, "confidence": 0.99, "failure_reason": "no-edge", "success_evidence": None,
        "provenance": "runtime", "certifying": False, "retest_condition": "new-data",
    }]
    ranked = rank_semantic_plans(plans, [], failed, 5)
    assert ranked == rank_semantic_plans(plans, [], failed, 5)
    assert all(p["mechanism_signature"] != plans[0]["mechanism_signature"] for p in ranked)
    assert len(ranked) <= 5
