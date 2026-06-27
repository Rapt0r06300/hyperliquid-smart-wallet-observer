from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(slots=True)
class ChunkIngestionResult:
    path: str
    rows_seen: int
    chunks_committed: int
    checkpoint_row: int
    network_used: bool = False
    stopped_reason: str = "INGESTION_COMPLETE"


def ingest_jsonl_chunks(
    path: Path,
    *,
    chunk_size: int = 50_000,
    resume_from_row: int = 0,
    on_chunk: Callable[[list[dict]], None] | None = None,
) -> ChunkIngestionResult:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not path.exists():
        return ChunkIngestionResult(str(path), 0, 0, resume_from_row, stopped_reason="PATH_NOT_FOUND")
    rows_seen = 0
    chunks = 0
    buffer: list[dict] = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            if rows_seen < resume_from_row:
                rows_seen += 1
                continue
            rows_seen += 1
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                buffer.append(payload)
            if len(buffer) >= chunk_size:
                if on_chunk:
                    on_chunk(buffer)
                chunks += 1
                buffer = []
    if buffer:
        if on_chunk:
            on_chunk(buffer)
        chunks += 1
    return ChunkIngestionResult(str(path), rows_seen, chunks, rows_seen)
