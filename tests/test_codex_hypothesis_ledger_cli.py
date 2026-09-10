from __future__ import annotations

import json
from pathlib import Path

from tools.codex_hypothesis_ledger import main


def payload(*, record_id: str = "R-1", hypothesis_id: str = "H-1") -> dict:
    return {
        "schema_version": 1,
        "record_id": record_id,
        "created_at_utc": "2026-09-10T12:00:00Z",
        "hypothesis_id": hypothesis_id,
        "family": "lead_lag",
        "parent_hypothesis_id": None,
        "stage": "DISCOVERY",
        "mechanism": "cross venue asynchronous price discovery",
        "data_surfaces": ["binance_bbo", "hl_bbo"],
        "temporal_operator": "lagged response",
        "conditioning": ["liquid regime"],
        "prediction_target": "30s executable markout",
        "execution_translation": "paper taker on Hyperliquid",
        "change_class": "NEW_MECHANISM",
        "rationale": "One venue may lead another.",
        "falsification_test": "Reject if held-out executable headroom is non-positive.",
        "source_refs": [],
        "experiment_ids": [],
        "scientific_signatures": [],
        "trial_count": 0,
        "verdict": None,
        "economic_progress": {},
        "notes": None,
    }


def test_register_then_status_round_trip(tmp_path: Path, capsys) -> None:
    ledger = tmp_path / "ledger.jsonl"
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(payload()), encoding="utf-8")
    assert main(["--ledger", str(ledger), "register", str(candidate)]) == 0
    registered = json.loads(capsys.readouterr().out)
    assert registered["status"] == "REGISTERED"
    assert registered["hypothesis_id"] == "H-1"
    assert main(["--ledger", str(ledger), "status", "--family", "lead_lag"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["records"] == 1
    assert status["unique_hypotheses"] == 1


def test_score_does_not_write_and_detects_duplicate(tmp_path: Path, capsys) -> None:
    ledger = tmp_path / "ledger.jsonl"
    first = tmp_path / "first.json"
    duplicate = tmp_path / "duplicate.json"
    first.write_text(json.dumps(payload()), encoding="utf-8")
    dupe_payload = payload(record_id="R-2")
    duplicate.write_text(json.dumps(dupe_payload), encoding="utf-8")
    assert main(["--ledger", str(ledger), "register", str(first)]) == 0
    capsys.readouterr()
    before = ledger.read_bytes()
    assert main(["--ledger", str(ledger), "score", str(duplicate)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["duplicate"] is True
    assert result["novelty_score"] == 0.0
    assert ledger.read_bytes() == before


def test_needs_rediscovery_reports_machine_boolean(tmp_path: Path, capsys) -> None:
    ledger = tmp_path / "ledger.jsonl"
    for idx, delta in enumerate((0.0, -0.1), start=1):
        p = payload(record_id=f"R-{idx}")
        p["stage"] = "EXPLOIT"
        p["change_class"] = "PARAMETER_ONLY"
        p["economic_progress"] = {"comparable": True, "delta_net_usd_per_day": delta}
        p["created_at_utc"] = f"2026-09-10T12:0{idx}:00Z"
        candidate = tmp_path / f"candidate-{idx}.json"
        candidate.write_text(json.dumps(p), encoding="utf-8")
        assert main(["--ledger", str(ledger), "register", str(candidate)]) == 0
        capsys.readouterr()
    assert main(["--ledger", str(ledger), "needs-rediscovery", "H-1"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {
        "hypothesis_id": "H-1",
        "rediscovery_required": True,
        "status": "REDISCOVERY_REQUIRED",
    }


def test_invalid_candidate_returns_two(tmp_path: Path, capsys) -> None:
    ledger = tmp_path / "ledger.jsonl"
    candidate = tmp_path / "bad.json"
    candidate.write_text("{}", encoding="utf-8")
    assert main(["--ledger", str(ledger), "register", str(candidate)]) == 2
    err = json.loads(capsys.readouterr().err)
    assert err["status"] == "BLOCKED"
