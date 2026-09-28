from hl_observer.event_intelligence.economic_pipeline import build_economic_research_evidence


def test_empty_economic_pipeline_is_fail_closed():
    evidence = build_economic_research_evidence((), ())

    assert evidence["schema"] == "alina.event_intelligence_economic_research.v1"
    assert evidence["cost_model_complete"] is False
    assert evidence["measured_markout_count"] == 0
    assert evidence["copy_vault_context"]["status"] == "UNMEASURABLE"
    assert evidence["copy_vault_context"]["may_infer_motive"] is False
    assert evidence["proof_state"] == "UNMEASURABLE"
    assert evidence["promotion_allowed"] is False
    assert evidence["paper_only"] is True
    assert evidence["read_only"] is True
    assert evidence["real_execution"] is False
