"""JSON-Lines adapter (V12, repo 08): legacy interop for agent tool I/O. Pure / round-trips."""

from __future__ import annotations

import json


def to_jsonl(rows: list[dict]) -> str:
    return "\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows)


def from_jsonl(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


__all__ = ["to_jsonl", "from_jsonl"]
