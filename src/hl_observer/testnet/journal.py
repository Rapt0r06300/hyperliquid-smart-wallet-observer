from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hl_observer.testnet.models import TestnetOrderResult, unix_ms


@dataclass(frozen=True, slots=True)
class TestnetJournalEntry:
    event_type: str
    decision: str
    reasons: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at_ms: int = field(default_factory=unix_ms)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TestnetDecisionJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write_guard_refusal(self, reasons: list[str], evidence: dict[str, Any] | None = None) -> TestnetJournalEntry:
        entry = TestnetJournalEntry(
            event_type="testnet_guard",
            decision="REJECT_TESTNET_GUARD",
            reasons=list(reasons),
            evidence=evidence or {},
        )
        self._append(entry)
        return entry

    def write_result(self, result: TestnetOrderResult, evidence: dict[str, Any] | None = None) -> TestnetJournalEntry:
        entry = TestnetJournalEntry(
            event_type="testnet_order_result",
            decision=result.status.upper(),
            reasons=list(result.reasons),
            result=result.to_dict(),
            evidence=evidence or result.request.evidence,
        )
        self._append(entry)
        return entry

    def _append(self, entry: TestnetJournalEntry) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")


def default_testnet_journal_path(project_root: Path | None = None) -> Path:
    root = project_root or Path.cwd()
    return root / "logs" / "logs à envoyer" / "testnet_decisions_latest.jsonl"
