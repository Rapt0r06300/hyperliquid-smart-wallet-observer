from hl_observer.simulation.decision_replay_analyzer import trace_event_decision_path


def test_event_path_reaches_ledger_with_one_id():
    stages = ["INGESTION", "SIGNAL", "REFUSAL", "PAPER", "LEDGER"]
    result = trace_event_decision_path([{"event_id": "E-1", "stage": stage} for stage in stages])
    assert result["status"] == "PROVEN"
    assert result["event_count"] == 1


def test_event_path_missing_stage_is_unmeasurable():
    result = trace_event_decision_path([
        {"event_id": "E-1", "stage": "INGESTION"},
        {"event_id": "E-1", "stage": "SIGNAL"},
    ])
    assert result["status"] == "UNMEASURABLE"
    assert "LEDGER" in result["missing_stages"]["E-1"]
