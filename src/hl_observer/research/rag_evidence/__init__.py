"""RAG evidence store (V12, repo 13): context retrieval that NEVER changes the hot path.

Stores and retrieves evidence snippets for narration. Retrieval is flagged context-only and
has no decision surface — the decision hot-path never consumes it. Pure / read-only.
"""

from __future__ import annotations


class RagEvidenceStore:
    context_only = True

    def __init__(self) -> None:
        self._docs: list[dict] = []

    def add(self, *, ref: str, text: str) -> None:
        self._docs.append({"ref": str(ref), "text": str(text)})

    def recall(self, query: str, *, limit: int = 5) -> list[dict]:
        q = str(query).lower()
        hits = [d for d in self._docs if q in d["text"].lower()]
        return [{**d, "context_only": True} for d in hits[: int(limit)]]


def affects_decision() -> bool:
    return False  # RAG is context only; it must never alter a trading decision


__all__ = ["RagEvidenceStore", "affects_decision"]
