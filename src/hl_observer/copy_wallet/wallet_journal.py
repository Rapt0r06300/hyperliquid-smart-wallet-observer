from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class WalletJournalRecord:
    event_type: str
    candidate_id: str
    leader_wallet: str
    coin: str
    decision: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    payload: Mapping[str, Any] = field(default_factory=dict)
    paper_only: bool = True
    real_execution: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        payload["payload"] = dict(self.payload)
        payload["paper_only"] = True
        payload["real_execution"] = False
        return payload


def append_wallet_journal(record: WalletJournalRecord, path: Path) -> Path:
    """Append a paper-only wallet mirror evidence record as JSONL."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    return path


__all__ = ["WalletJournalRecord", "append_wallet_journal"]
