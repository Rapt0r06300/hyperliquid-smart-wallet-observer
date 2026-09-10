import json
import subprocess
import sys
from pathlib import Path

from hl_observer.research.semantic_discovery import generate_semantic_plans, rank_semantic_plans

ROOT = Path(__file__).resolve().parents[1]


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
                "invalid_combinations": [
                    {"event": "trade-burst", "context": "volatile", "regime": "normal"}
                ],
                "priority_hints": {
                    "data_feasibility": {"binance-bbo": 0.9, "hl-bbo": 1.0},
                    "falsification_cost": {"external-bbo-move": 0.2, "trade-burst": 0.5},
                    "executable_headroom": {"paper-taker": 0.4},
                },
            }
        }
    }


def _ledger_record(plan, *, temporal_operator=None):
    operator = temporal_operator or plan["temporal_operator"]
    mechanism = (
        f"{plan['event']} on {plan['data_surface']} predicts {plan['target']} via {operator}"
    )
    return {
        "record_id": "R-1",
        "hypothesis_id": "H-1",
        "family": plan["family"],
        "stage": "DISCOVERY",
        "mechanism": mechanism,
        "data_surfaces": [plan["data_surface"]],
        "temporal_operator": operator,
        "conditioning": [plan["context"], plan["regime"]],
        "prediction_target": plan["target"],
        "execution_translation": plan["execution"],
        "change_class": "NEW_MECHANISM",
        "rationale": "test",
        "falsification_test": "test",
        "trial_count": 1,
        "baseline": False,
    }


def test_generation_is_deterministic_structured_deduplicated_and_filters_invalid():
    first = generate_semantic_plans(_catalog(), "lead_lag", 40, 7)
    second = generate_semantic_plans(_catalog(), "lead_lag", 40, 7)
    assert first == second
    assert len({p["semantic_key"] for p in first}) == len(first)
    assert all(p["family"] == "lead_lag" for p in first)
    assert not any(
        p["event"] == "trade-burst"
        and p["context"] == "volatile"
        and p["regime"] == "normal"
        for p in first
    )
    assert all("data_feasibility" in p for p in first)


def test_ranking_vetoes_only_matching_failed_context_and_is_deterministic():
    plans = generate_semantic_plans(_catalog(), "lead_lag", 40, 3)
    failed_plan = plans[0]
    failed = [{
        "record_id": "PM-1", "family": "lead_lag",
        "mechanism_signature": failed_plan["mechanism_signature"],
        "context": [failed_plan["context"]], "change_motif": "candidate", "outcome": "FAILURE",
        "evidence_count": 10, "confidence": 0.99, "failure_reason": "no-edge", "success_evidence": None,
        "provenance": "runtime", "certifying": False, "retest_condition": "new-data",
    }, {
        "record_id": "PM-2", "family": "lead_lag",
        "mechanism_signature": failed_plan["mechanism_signature"],
        "context": [failed_plan["context"]], "change_motif": "candidate", "outcome": "FAILURE",
        "evidence_count": 10, "confidence": 0.99, "failure_reason": "no-edge", "success_evidence": None,
        "provenance": "runtime", "certifying": False, "retest_condition": "new-data",
    }]
    ranked = rank_semantic_plans(plans, [], failed, 5)
    assert ranked == rank_semantic_plans(plans, [], failed, 5)
    assert all(
        not (
            p["mechanism_signature"] == failed_plan["mechanism_signature"]
            and p["context"] == failed_plan["context"]
        )
        for p in ranked
    )
    assert len(ranked) <= 5
    assert all("priority_components" in p for p in ranked)


def test_ranking_filters_near_semantic_duplicate_from_ledger():
    plans = generate_semantic_plans(_catalog(), "lead_lag", 80, 11)
    left = next(
        plan
        for plan in plans
        if any(
            other["event"] == plan["event"]
            and other["context"] == plan["context"]
            and other["data_surface"] == plan["data_surface"]
            and other["regime"] == plan["regime"]
            and other["target"] == plan["target"]
            and other["execution"] == plan["execution"]
            and other["temporal_operator"] != plan["temporal_operator"]
            for other in plans
        )
    )
    right = next(
        other
        for other in plans
        if other["event"] == left["event"]
        and other["context"] == left["context"]
        and other["data_surface"] == left["data_surface"]
        and other["regime"] == left["regime"]
        and other["target"] == left["target"]
        and other["execution"] == left["execution"]
        and other["temporal_operator"] != left["temporal_operator"]
    )
    ranked = rank_semantic_plans([right], [_ledger_record(left)], [], 1)
    assert ranked == []


def test_semantic_cli_runs_from_clean_interpreter_without_touching_repo_runtime(tmp_path):
    output = tmp_path / "shortlist.json"
    status = tmp_path / "status.json"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(ROOT / "tools/codex_semantic_discovery.py"),
            "--family",
            "lead_lag",
            "--pool-size",
            "40",
            "--shortlist",
            "5",
            "--out",
            str(output),
            "--status-out",
            str(status),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    accounting = json.loads(status.read_text(encoding="utf-8"))
    assert payload["certifying"] is False
    assert accounting["filtered_before_llm"] == accounting["generated"] - 5
