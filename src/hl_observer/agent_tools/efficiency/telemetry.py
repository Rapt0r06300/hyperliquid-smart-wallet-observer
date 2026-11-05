"""Small, provider-neutral efficiency receipts."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


def estimate_tokens(text_or_chars: str | int) -> int:
    chars = len(text_or_chars) if isinstance(text_or_chars, str) else max(0, int(text_or_chars))
    return (chars + 3) // 4


@dataclass(slots=True)
class EfficiencyReceipt:
    task_id: str
    tool_calls: int = 0
    input_chars: int = 0
    output_chars: int = 0
    cached_prefix_hits: int = 0
    cache_misses: int = 0
    compacted_outputs: int = 0
    tests_run: int = 0
    tests_skipped: int = 0
    retries: int = 0
    latency_ms: float = 0.0
    notes: list[str] = field(default_factory=list)

    def record_context(self, *, input_chars: int, cached: bool) -> None:
        self.input_chars += max(0, int(input_chars))
        if cached:
            self.cached_prefix_hits += 1
        else:
            self.cache_misses += 1

    def finalize(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema": "agent_efficiency_receipt.v1",
            "task_id": self.task_id,
            "tool_calls": self.tool_calls,
            "input_chars": self.input_chars,
            "input_tokens_estimate": estimate_tokens(self.input_chars),
            "output_chars": self.output_chars,
            "output_tokens_estimate": estimate_tokens(self.output_chars),
            "cached_prefix_hits": self.cached_prefix_hits,
            "cache_misses": self.cache_misses,
            "compacted_outputs": self.compacted_outputs,
            "tests_run": self.tests_run,
            "tests_skipped": self.tests_skipped,
            "retries": self.retries,
            "latency_ms": round(float(self.latency_ms), 3),
            "notes": list(self.notes),
            "paper_read_only": True,
            "real_execution": False,
        }
        payload["receipt_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
        return payload


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


__all__ = ["EfficiencyReceipt", "estimate_tokens"]
