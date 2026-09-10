from __future__ import annotations

from pathlib import Path

from hl_observer.backtesting import copy_vault_vnext_integrity as module


def _valid_raw() -> dict[str, object]:
    return {
        "universe_integrity": {
            "universe_complete": True,
            "correlations_complete": True,
            "complete_universe": ["A", "B"],
            "observed_survivors": ["A"],
            "cohort": [
                {"wallet": "A", "liquide": False},
                {"wallet": "B", "liquide": True},
            ],
            "correlations": [
                {"left": "A", "right": "B", "correlation": 0.2},
            ],
            "entity_groups": {"A": "entity-a", "B": "entity-b"},
        }
    }


def test_missing_integrity_evidence_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        module,
        "evaluate_copy_vault_universe_integrity",
        lambda **_kwargs: {"eligible": False, "reasons": ["UNIVERSE_NOT_DECLARED"]},
    )

    evidence = module.evaluate_copy_vault_vnext_integrity({})

    assert evidence["eligible"] is False
    assert "UNIVERSE_INTEGRITY_INPUT_MISSING" in evidence["reasons"]
    assert evidence["paper_read_only"] is True
    assert evidence["real_execution"] is False


def test_json_correlation_rows_are_adapted_and_candidate_stays_eligible(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def evaluate(**kwargs):
        captured.update(kwargs)
        return {"eligible": True, "reasons": []}

    monkeypatch.setattr(module, "evaluate_copy_vault_universe_integrity", evaluate)
    evidence = module.evaluate_copy_vault_vnext_integrity(_valid_raw())
    gated = module.gate_copy_vault_candidate(
        {
            "status": "ROBUST_TRAIN_CANDIDATE",
            "selection_eligible": True,
            "physical_freeze_allowed": True,
            "freeze_candidate_sha256": "abc",
        },
        evidence,
    )

    assert captured["correlations"] == {("a", "b"): 0.2}
    assert evidence["eligible"] is True
    assert gated["selection_eligible"] is True
    assert gated["physical_freeze_allowed"] is True
    assert gated["freeze_candidate_sha256"] == "abc"


def test_incomplete_correlation_coverage_clears_freeze_candidate(monkeypatch) -> None:
    monkeypatch.setattr(
        module,
        "evaluate_copy_vault_universe_integrity",
        lambda **_kwargs: {"eligible": True, "reasons": []},
    )
    raw = _valid_raw()
    raw["universe_integrity"]["correlations_complete"] = False  # type: ignore[index]

    evidence = module.evaluate_copy_vault_vnext_integrity(raw)
    gated = module.gate_copy_vault_candidate(
        {
            "status": "ROBUST_TRAIN_CANDIDATE",
            "selection_eligible": True,
            "physical_freeze_allowed": True,
            "freeze_candidate_sha256": "abc",
        },
        evidence,
    )

    assert evidence["eligible"] is False
    assert "CORRELATION_COVERAGE_UNPROVEN" in evidence["reasons"]
    assert gated["selection_eligible"] is False
    assert gated["physical_freeze_allowed"] is False
    assert gated["freeze_candidate_sha256"] is None
    assert gated["universe_integrity"]["eligible"] is False


def test_malformed_cohort_and_nonfinite_correlation_fail_closed(monkeypatch) -> None:
    def evaluate(**kwargs):
        for row in kwargs["cohort"]:
            row.get("wallet")
        return {"eligible": True, "reasons": []}

    monkeypatch.setattr(module, "evaluate_copy_vault_universe_integrity", evaluate)
    raw = _valid_raw()
    raw["universe_integrity"]["cohort"] = ["not-a-row"]  # type: ignore[index]
    raw["universe_integrity"]["correlations"] = [  # type: ignore[index]
        {"left": "A", "right": "B", "correlation": float("nan")}
    ]

    evidence = module.evaluate_copy_vault_vnext_integrity(raw)

    assert evidence["eligible"] is False
    assert "COHORT_EVIDENCE_INVALID" in evidence["reasons"]
    assert "CORRELATION_EVIDENCE_INVALID" in evidence["reasons"]


def test_economic_pack_wires_integrity_before_copy_reports() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "src" / "hl_observer" / "backtesting" / "economic_vnext_pack.py").read_text(
        encoding="utf-8"
    )

    evaluate = text.index("copy_integrity = evaluate_copy_vault_vnext_integrity(copy_raw)")
    gate_family = text.index("copy = gate_copy_vault_candidate(copy, copy_integrity)")
    gate_v5 = text.index("copy_v5 = gate_copy_vault_candidate(copy_v5, copy_integrity)")
    write_reports = text.index("paths = {")
    assert evaluate < gate_family < gate_v5 < write_reports
    assert '"copy_vault_universe_integrity": copy_integrity' in text
