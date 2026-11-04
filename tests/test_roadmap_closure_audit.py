from __future__ import annotations

import pytest

from hl_observer.ops.roadmap_closure_audit import (
    append_scientific_record,
    audit_receipts,
    audit_task_ids,
    certify_technical_closure,
    load_scientific_ledger,
    require_technical_closure,
    validate_scientific_record,
)


def _ids(count: int = 136) -> list[str]:
    return [f"T{number:03d}" for number in range(1, count + 1)]


def _receipt(task_id: str, *, head: str = "head", code: str = "code") -> dict[str, object]:
    return {
        "task_id": task_id,
        "status": "VERIFIED_DONE",
        "head_sha": head,
        "working_tree_code_sha256": code,
        "commands": ["pytest"],
        "tests": ["returncode=0"],
        "proofs": ["exact local proof"],
        "files": ["src/hl_observer"],
    }


def test_task_id_audit_rejects_missing_duplicate_and_unknown():
    report = audit_task_ids(_ids()[:-1] + ["T001", "T999"])
    assert report.missing_ids == ("T136",)
    assert report.duplicate_ids == ("T001",)
    assert report.unknown_ids == ("T999",)
    assert report.closure_allowed is False


def test_receipt_audit_rejects_stale_and_partial_receipts():
    receipts = {task_id: _receipt(task_id) for task_id in _ids()}
    receipts["T001"]["head_sha"] = "old"
    receipts["T002"]["proofs"] = []
    report = audit_receipts(receipts, head_sha="head", code_sha256="code")
    assert report.stale_receipts == ("T001",)
    assert report.invalid_receipts == ("T002",)
    assert report.closure_allowed is False


def test_technical_closure_is_fail_closed():
    report = audit_task_ids(_ids())
    with pytest.raises(ValueError, match="unsafe"):
        require_technical_closure(report, paper_read_only_fail_closed=False, real_execution=False)
    with pytest.raises(ValueError, match="unsafe"):
        require_technical_closure(report, paper_read_only_fail_closed=True, real_execution=True)


def test_scientific_record_does_not_fill_missing_values():
    record = validate_scientific_record(
        {
            "experiment_id": "exp-1",
            "status": "MORE_DATA",
            "code_sha": "code",
            "corpus_sha": "corpus",
            "config_sha": "config",
            "observations": 0,
            "fabricated_values": False,
        }
    )
    assert record.observations == 0
    with pytest.raises(ValueError, match="fabricated"):
        validate_scientific_record({**record.__dict__, "fabricated_values": True})


def test_scientific_ledger_is_append_only_and_hash_bound(tmp_path):
    ledger = tmp_path / "science.jsonl"
    first = append_scientific_record(
        ledger,
        {
            "experiment_id": "exp-1",
            "status": "MORE_DATA",
            "code_sha": "code-1",
            "corpus_sha": "corpus-1",
            "config_sha": "config-1",
            "observations": 0,
            "fabricated_values": False,
        },
    )
    second = append_scientific_record(
        ledger,
        {
            "experiment_id": "exp-2",
            "status": "UNMEASURABLE",
            "code_sha": "code-2",
            "corpus_sha": "corpus-2",
            "config_sha": "config-2",
            "observations": 3,
            "fabricated_values": False,
        },
    )
    entries = load_scientific_ledger(ledger)
    assert entries == (first, second)
    assert second.previous_sha256 == first.entry_sha256
    with pytest.raises(ValueError, match="duplicate scientific experiment"):
        append_scientific_record(ledger, first.record)

    lines = ledger.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace("exp-1", "tampered")
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid entry hash"):
        load_scientific_ledger(ledger)


def test_technical_closure_certificate_requires_all_exact_head_receipts():
    receipts = {task_id: _receipt(task_id) for task_id in _ids()}
    certificate = certify_technical_closure(
        receipts,
        head_sha="head",
        code_sha256="code",
        paper_read_only_fail_closed=True,
        real_execution=False,
    )
    assert certificate["status"] == "VERIFIED_DONE"
    assert len(certificate["certificate_sha256"]) == 64

    del receipts["T136"]
    with pytest.raises(ValueError, match="technical closure"):
        certify_technical_closure(
            receipts,
            head_sha="head",
            code_sha256="code",
            paper_read_only_fail_closed=True,
            real_execution=False,
        )
