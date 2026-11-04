"""Fail-closed audit primitives for the 136-item implementation roadmap.

The roadmap verifier records evidence, but this module is the runtime-facing
contract that decides whether an audit is complete.  It never upgrades a
missing receipt, stale SHA, partial result or unknown task into success.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

VALID_STATUSES = frozenset({"VERIFIED_DONE", "TODO", "BLOCKED"})
SCIENTIFIC_STATES = frozenset({"PROVEN", "PROMISING", "MORE_DATA", "UNMEASURABLE", "REJECTED"})


@dataclass(frozen=True)
class RoadmapAudit:
    expected_count: int
    observed_count: int
    duplicate_ids: tuple[str, ...]
    missing_ids: tuple[str, ...]
    unknown_ids: tuple[str, ...]
    stale_receipts: tuple[str, ...]
    invalid_receipts: tuple[str, ...]
    closure_allowed: bool


@dataclass(frozen=True)
class ScientificRecord:
    experiment_id: str
    status: str
    code_sha: str
    corpus_sha: str
    config_sha: str
    observations: int
    fabricated_values: bool


@dataclass(frozen=True)
class ScientificLedgerEntry:
    record: ScientificRecord
    previous_sha256: str | None
    entry_sha256: str


def _canonical_json(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _scientific_entry_payload(
    record: ScientificRecord, previous_sha256: str | None,
) -> dict[str, object]:
    return {
        "schema": "alina.scientific_record.v1",
        "record": {
            "experiment_id": record.experiment_id,
            "status": record.status,
            "code_sha": record.code_sha,
            "corpus_sha": record.corpus_sha,
            "config_sha": record.config_sha,
            "observations": record.observations,
            "fabricated_values": False,
        },
        "previous_sha256": previous_sha256,
    }


def load_scientific_ledger(path: str | Path) -> tuple[ScientificLedgerEntry, ...]:
    """Read an append-only scientific ledger and verify its hash chain."""

    ledger_path = Path(path)
    if not ledger_path.is_file():
        return ()
    entries: list[ScientificLedgerEntry] = []
    seen_experiments: set[str] = set()
    previous: str | None = None
    with ledger_path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            try:
                envelope = json.loads(line)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"scientific ledger line {number} is invalid JSON") from exc
            if not isinstance(envelope, Mapping):
                raise ValueError(f"scientific ledger line {number} is not an object")
            raw_record = envelope.get("record")
            if not isinstance(raw_record, Mapping):
                raise ValueError(f"scientific ledger line {number} has no record")
            record = validate_scientific_record(raw_record)
            previous_sha = envelope.get("previous_sha256")
            if previous_sha not in (None, previous):
                raise ValueError(f"scientific ledger line {number} breaks the hash chain")
            payload = _scientific_entry_payload(record, previous)
            actual = hashlib.sha256(_canonical_json(payload)).hexdigest()
            if envelope.get("schema") != payload["schema"] or envelope.get("entry_sha256") != actual:
                raise ValueError(f"scientific ledger line {number} has an invalid entry hash")
            if record.experiment_id in seen_experiments:
                raise ValueError(f"duplicate scientific experiment: {record.experiment_id}")
            seen_experiments.add(record.experiment_id)
            entries.append(ScientificLedgerEntry(record, previous, actual))
            previous = actual
    return tuple(entries)


def append_scientific_record(
    path: str | Path, record: Mapping[str, object] | ScientificRecord,
) -> ScientificLedgerEntry:
    """Append one hash-bound, non-fabricated scientific observation."""

    validated = record if isinstance(record, ScientificRecord) else validate_scientific_record(record)
    existing = load_scientific_ledger(path)
    if any(item.record.experiment_id == validated.experiment_id for item in existing):
        raise ValueError(f"duplicate scientific experiment: {validated.experiment_id}")
    previous = existing[-1].entry_sha256 if existing else None
    payload = _scientific_entry_payload(validated, previous)
    digest = hashlib.sha256(_canonical_json(payload)).hexdigest()
    envelope = {**payload, "entry_sha256": digest}
    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return ScientificLedgerEntry(validated, previous, digest)


def certify_technical_closure(
    receipts: Mapping[str, Mapping[str, object]],
    *,
    head_sha: str,
    code_sha256: str,
    paper_read_only_fail_closed: bool,
    real_execution: bool,
    expected_count: int = 136,
) -> dict[str, object]:
    """Return a certificate only when every exact-HEAD receipt is complete."""

    audit = audit_receipts(
        receipts,
        head_sha=head_sha,
        code_sha256=code_sha256,
        expected_count=expected_count,
    )
    require_technical_closure(
        audit,
        paper_read_only_fail_closed=paper_read_only_fail_closed,
        real_execution=real_execution,
    )
    payload: dict[str, object] = {
        "schema": "alina.technical_closure.v1",
        "status": "VERIFIED_DONE",
        "expected_count": audit.expected_count,
        "observed_count": audit.observed_count,
        "head_sha": head_sha,
        "working_tree_code_sha256": code_sha256,
        "paper_read_only_fail_closed": paper_read_only_fail_closed,
        "real_execution": real_execution,
        "receipt_ids": sorted(receipts),
    }
    return {**payload, "certificate_sha256": hashlib.sha256(_canonical_json(payload)).hexdigest()}


def _normalise_ids(task_ids: Iterable[str]) -> tuple[str, ...]:
    return tuple(str(value).strip().upper() for value in task_ids)


def audit_task_ids(task_ids: Iterable[str], *, expected_count: int = 136) -> RoadmapAudit:
    """Check exact T001..Tn coverage without interpreting task content."""

    observed = _normalise_ids(task_ids)
    expected = tuple(f"T{number:03d}" for number in range(1, expected_count + 1))
    expected_set = set(expected)
    counts: dict[str, int] = {}
    for task_id in observed:
        counts[task_id] = counts.get(task_id, 0) + 1
    duplicate_ids = tuple(sorted(task_id for task_id, count in counts.items() if count > 1))
    unknown_ids = tuple(sorted(set(observed) - expected_set))
    missing_ids = tuple(task_id for task_id in expected if task_id not in counts)
    return RoadmapAudit(
        expected_count=expected_count,
        observed_count=len(observed),
        duplicate_ids=duplicate_ids,
        missing_ids=missing_ids,
        unknown_ids=unknown_ids,
        stale_receipts=(),
        invalid_receipts=(),
        closure_allowed=not duplicate_ids and not missing_ids and not unknown_ids and len(observed) == expected_count,
    )


def audit_receipts(
    receipts: Mapping[str, Mapping[str, object]],
    *,
    head_sha: str,
    code_sha256: str,
    expected_count: int = 136,
) -> RoadmapAudit:
    """Validate receipt identity and exact code binding.

    A receipt can only contribute to closure when it is complete, current and
    explicitly ``VERIFIED_DONE``.  This function reports all deficiencies so
    callers can repair them in one pass.
    """

    base = audit_task_ids(receipts.keys(), expected_count=expected_count)
    stale: list[str] = []
    invalid: list[str] = []
    for task_id, receipt in receipts.items():
        status = receipt.get("status")
        if status not in VALID_STATUSES or status != "VERIFIED_DONE":
            invalid.append(str(task_id))
            continue
        if receipt.get("head_sha") != head_sha or receipt.get("working_tree_code_sha256") != code_sha256:
            stale.append(str(task_id))
            continue
        required_lists = ("commands", "tests", "proofs", "files")
        if any(
            not isinstance(receipt.get(name), list)
            or not receipt.get(name)
            or any(not isinstance(value, str) or not value.strip() for value in receipt[name])
            for name in required_lists
        ):
            invalid.append(str(task_id))
    payload = {
        **base.__dict__,
        "stale_receipts": tuple(sorted(stale)),
        "invalid_receipts": tuple(sorted(invalid)),
    }
    payload["closure_allowed"] = base.closure_allowed and not stale and not invalid
    return RoadmapAudit(**payload)


def require_technical_closure(
    audit: RoadmapAudit,
    *,
    paper_read_only_fail_closed: bool,
    real_execution: bool,
) -> None:
    """Raise instead of certifying when any closure precondition is unsafe."""

    if not audit.closure_allowed:
        raise ValueError("technical closure is not proven")
    if not paper_read_only_fail_closed or real_execution:
        raise ValueError("unsafe execution boundary")


def validate_scientific_record(record: Mapping[str, object]) -> ScientificRecord:
    """Validate an append-only scientific record without filling absent values."""

    required = ("experiment_id", "status", "code_sha", "corpus_sha", "config_sha", "observations")
    if any(not str(record.get(key) or "").strip() for key in required[:-1]):
        raise ValueError("scientific record identity is incomplete")
    status = str(record.get("status") or "")
    if status not in SCIENTIFIC_STATES:
        raise ValueError("unknown scientific status")
    observations = record.get("observations")
    if isinstance(observations, bool) or not isinstance(observations, int) or observations < 0:
        raise ValueError("observations must be an exact non-negative integer")
    fabricated = record.get("fabricated_values", False)
    if fabricated is not False:
        raise ValueError("fabricated values are forbidden")
    return ScientificRecord(
        experiment_id=str(record["experiment_id"]),
        status=status,
        code_sha=str(record["code_sha"]),
        corpus_sha=str(record["corpus_sha"]),
        config_sha=str(record["config_sha"]),
        observations=observations,
        fabricated_values=False,
    )
