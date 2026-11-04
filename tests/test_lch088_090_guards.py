from __future__ import annotations

from hl_observer.research.ollama_advisor import (
    ADVISOR_SAFETY_CONTRACT,
    advise_json_from_summary,
    validate_advisor_payload,
)
from hl_observer.risk.risk_gate_runtime import (
    compose_risk_fn,
    source_staleness_check,
)


def test_ollama_is_explanatory_and_cannot_authorize_a_decision() -> None:
    payload = advise_json_from_summary({"reason_counts": {"STALE": 1}})
    assert validate_advisor_payload(payload)
    assert payload["paper_only"] is True
    assert payload["external_action"] is False
    assert payload["decision_authority"] is False
    assert set(ADVISOR_SAFETY_CONTRACT) <= set(payload)


def test_stale_source_blocks_entries_but_preserves_close_only() -> None:
    assert source_staleness_check({"action": "OPEN", "source_stale": True}) == (
        False,
        ("SOURCE_STALE_ENTRY_BLOCKED",),
    )
    assert source_staleness_check({"action": "ADD", "source_stale": True})[0] is False
    assert source_staleness_check({"action": "CLOSE", "source_stale": True}) == (
        True,
        ("SOURCE_STALE_CLOSE_ONLY",),
    )


def test_composed_risk_function_applies_source_defect_gate() -> None:
    gate = compose_risk_fn(lambda _intent: (True, ()))
    ok, reasons = gate({"action": "OPEN", "source_stale": True})
    assert ok is False
    assert "SOURCE_STALE_ENTRY_BLOCKED" in reasons
