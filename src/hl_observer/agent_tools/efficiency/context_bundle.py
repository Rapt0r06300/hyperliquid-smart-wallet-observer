"""Budgeted task-context compilation over the incremental repository index."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .parallel_reads import read_many
from .prompt_cache import build_cache_key
from .repo_index import RepoIndex

WORD_RE = re.compile(r"[a-z0-9_]{2,}", re.I)


@dataclass(frozen=True, slots=True)
class ContextRequest:
    task: str
    changed_files: tuple[str, ...] = ()
    max_chars: int = 24_000
    max_files: int = 24


@dataclass(frozen=True, slots=True)
class SelectedContextFile:
    path: str
    score: float
    reason: str
    content: str
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "score": self.score,
            "reason": self.reason,
            "content": self.content,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class ContextBundle:
    task: str
    files: tuple[SelectedContextFile, ...]
    omitted_files: int
    estimated_chars: int
    estimated_tokens: int
    cache_key: str
    index_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "files": [item.to_dict() for item in self.files],
            "omitted_files": self.omitted_files,
            "estimated_chars": self.estimated_chars,
            "estimated_tokens": self.estimated_tokens,
            "cache_key": self.cache_key,
            "index_fingerprint": self.index_fingerprint,
        }


def compile_context(root: Path, index: RepoIndex, request: ContextRequest) -> ContextBundle:
    root = root.resolve()
    terms = _tokens(request.task)
    changed = {Path(path).as_posix() for path in request.changed_files}
    ranked: list[tuple[float, str, str]] = []
    for path, record in index.records.items():
        score = _score(path, record.symbols, record.imports, terms, path in changed)
        if score > 0:
            reason = "changed" if path in changed else "matched_path_or_symbol"
            ranked.append((score, path, reason))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = ranked[: max(0, int(request.max_files))]
    reads = read_many(root, (path for _score, path, _reason in selected), max_workers=4, max_bytes=max(4_000, request.max_chars))
    by_path = {item.path: item for item in reads}
    files: list[SelectedContextFile] = []
    remaining = max(0, int(request.max_chars))
    for score, path, reason in selected:
        result = by_path[path]
        if result.content is None or remaining <= 0:
            continue
        content = result.content[:remaining]
        files.append(SelectedContextFile(path, round(score, 3), reason, content, hashlib.sha256(content.encode("utf-8")).hexdigest()))
        remaining -= len(content)
    total = sum(len(item.content) for item in files)
    return ContextBundle(
        task=request.task,
        files=tuple(files),
        omitted_files=max(0, len(ranked) - len(files)),
        estimated_chars=total,
        estimated_tokens=(total + 3) // 4,
        cache_key=build_cache_key(model_family="coding-agent", policy_text="stable-project-context", repository_fingerprint=index.fingerprint),
        index_fingerprint=index.fingerprint,
    )


def _score(path: str, symbols: tuple[str, ...], imports: tuple[str, ...], terms: set[str], changed: bool) -> float:
    if changed:
        return 100.0
    haystack = set(_tokens(path)) | set(symbols) | set(imports)
    matches = len(terms & {item.lower() for item in haystack})
    if matches == 0:
        return 0.0
    return float(matches * 10 + (4 if path.startswith("tests/") else 0))


def _tokens(text: str) -> set[str]:
    return {item.lower() for item in WORD_RE.findall(text)}


__all__ = ["ContextBundle", "ContextRequest", "SelectedContextFile", "compile_context"]
