"""Append-only local memory for reusing verified engineering outcomes."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

WORD_RE = re.compile(r"[a-z0-9_]{2,}", re.I)


@dataclass(frozen=True, slots=True)
class ExperienceRecord:
    task: str
    outcome: str
    actions: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    evidence_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["actions"] = list(self.actions)
        data["files"] = list(self.files)
        return data


class ExperienceStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: ExperienceRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")

    def retrieve(self, task: str, *, top_k: int = 1, min_similarity: float = 0.15) -> list[ExperienceRecord]:
        if not self.path.exists():
            return []
        query = _tokens(task)
        scored: list[tuple[float, ExperienceRecord]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                record = ExperienceRecord(
                    task=str(item["task"]), outcome=str(item["outcome"]),
                    actions=tuple(str(v) for v in item.get("actions", [])),
                    files=tuple(str(v) for v in item.get("files", [])),
                    evidence_sha256=str(item.get("evidence_sha256", "")),
                )
            except (ValueError, KeyError, TypeError):
                continue
            score = _similarity(query, _tokens(record.task))
            if score >= min_similarity:
                scored.append((score, record))
        scored.sort(key=lambda item: (-item[0], item[1].task, item[1].evidence_sha256))
        return [record for _score, record in scored[: max(0, int(top_k))]]


def _tokens(text: str) -> set[str]:
    return {item.lower() for item in WORD_RE.findall(text)}


def _similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


__all__ = ["ExperienceRecord", "ExperienceStore"]
