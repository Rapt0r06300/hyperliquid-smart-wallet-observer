"""Loss-aware compaction of noisy tool output."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

IMPORTANT_LINE = re.compile(r"(error|fail|traceback|exception|assert|warning|timeout|return code|command|no_go|critical)", re.I)


@dataclass(frozen=True, slots=True)
class CompactionResult:
    compacted: str
    original_sha256: str
    original_chars: int
    original_lines: int
    kept_lines: int
    omitted_line_ranges: tuple[tuple[int, int], ...]
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "compacted": self.compacted,
            "original_sha256": self.original_sha256,
            "original_chars": self.original_chars,
            "original_lines": self.original_lines,
            "kept_lines": self.kept_lines,
            "omitted_line_ranges": [list(item) for item in self.omitted_line_ranges],
            "truncated": self.truncated,
        }


def compact_output(text: str, *, max_chars: int = 8_000, max_lines: int = 160) -> CompactionResult:
    raw = str(text)
    lines = raw.splitlines()
    if len(raw) <= max_chars and len(lines) <= max_lines:
        return CompactionResult(raw, _sha256(raw), len(raw), len(lines), len(lines), (), False)
    important = sorted(index for index, line in enumerate(lines) if IMPORTANT_LINE.search(line))
    boundary = set(range(min(40, len(lines)))) | set(range(max(0, len(lines) - 40), len(lines)))
    ordered = important + sorted(boundary - set(important))
    selected: list[str] = []
    selected_indices: list[int] = []
    for index in ordered:
        candidate = lines[index]
        if sum(len(item) + 1 for item in selected) + len(candidate) + 1 <= max_chars:
            selected.append(candidate)
            selected_indices.append(index)
        if len(selected) >= max_lines:
            break
    kept = set(selected_indices)
    if important and not kept.intersection(important):
        # The marker plus one short evidence line is more valuable than noise.
        index = important[0]
        selected = [lines[index]][:1]
        selected_indices = [index]
        kept = {index}
    omitted = _ranges(index + 1 for index in range(len(lines)) if index not in kept)
    digest = _sha256(raw)
    marker = f"[COMPACTED original_sha256={digest} omitted_lines={len(lines) - len(kept)}]"
    budget_for_lines = max(0, max_chars - len(marker) - 1)
    selected = [line[:budget_for_lines] for line in selected]
    compacted = "\n".join([marker, *selected])[:max_chars]
    return CompactionResult(compacted, _sha256(raw), len(raw), len(lines), len(kept), tuple(omitted), True)


def _ranges(values: Any) -> list[tuple[int, int]]:
    ordered = sorted(values)
    if not ordered:
        return []
    result: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value != previous + 1:
            result.append((start, previous))
            start = value
        previous = value
    result.append((start, previous))
    return result


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = ["CompactionResult", "compact_output"]
