"""Partition replay evidence by source/channel/instrument without changing TickEnvelope."""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from hl_observer.collection.tick_dataset import TickDatasetWriter, TickEnvelope

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _component(value: object) -> str:
    clean = _SAFE.sub("_", str(value or "").strip())
    return clean.strip("._") or "unknown"


class PartitionedTickDatasetWriter:
    """Write immutable tick shards in replay-selectable partitions.

    One partition owns exactly one source/channel/instrument tuple. The original
    TickEnvelope and raw payload remain unchanged.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        rotate_bytes: int = 128 * 1024 * 1024,
        flush_every: int = 1,
    ) -> None:
        self.root = Path(root)
        self.rotate_bytes = max(1, int(rotate_bytes))
        self.flush_every = max(1, int(flush_every))
        self._writers: dict[tuple[str, str, str], TickDatasetWriter] = {}

    def _key(self, envelope: TickEnvelope) -> tuple[str, str, str]:
        return (
            str(envelope.source_id),
            str(envelope.channel),
            str(envelope.instrument),
        )

    def _writer(self, envelope: TickEnvelope) -> TickDatasetWriter:
        key = self._key(envelope)
        writer = self._writers.get(key)
        if writer is not None:
            return writer
        source, channel, instrument = key
        directory = (
            self.root
            / _component(source)
            / _component(channel)
            / _component(instrument)
        )
        writer = TickDatasetWriter(
            directory,
            stream_name="ticks",
            rotate_bytes=self.rotate_bytes,
            flush_every=self.flush_every,
        )
        self._writers[key] = writer
        return writer

    def append(self, envelope: TickEnvelope) -> int:
        return self._writer(envelope).append(envelope)

    def append_batch(self, envelopes: Iterable[TickEnvelope]) -> int:
        return len(self.append_batch_records(envelopes))

    def append_batch_records(self, envelopes: Iterable[TickEnvelope]) -> list[dict[str, Any]]:
        batch = list(envelopes)
        if not batch:
            return []
        grouped: dict[tuple[str, str, str], list[tuple[int, TickEnvelope]]] = defaultdict(list)
        for index, envelope in enumerate(batch):
            grouped[self._key(envelope)].append((index, envelope))

        output: list[dict[str, Any] | None] = [None] * len(batch)
        for rows in grouped.values():
            writer = self._writer(rows[0][1])
            records = writer.append_batch_records(envelope for _index, envelope in rows)
            for (index, _envelope), record in zip(rows, records):
                output[index] = record
        if any(record is None for record in output):
            raise RuntimeError("partitioned writer failed to persist the full batch")
        return [record for record in output if record is not None]

    def rotate_all(self) -> list[Path]:
        shards: list[Path] = []
        for writer in self._writers.values():
            shard = writer.rotate()
            if shard is not None:
                shards.append(shard)
        return sorted(shards)

    def stats(self) -> dict[str, Any]:
        partitions = {
            "|".join(key): writer.stats()
            for key, writer in sorted(self._writers.items())
        }
        return {
            "partitions": partitions,
            "partition_count": len(partitions),
            "records_written": sum(
                int(row["records_written"]) for row in partitions.values()
            ),
            "bytes_written": sum(
                int(row["bytes_written"]) for row in partitions.values()
            ),
            "read_only": True,
            "real_execution": False,
        }


__all__ = ["PartitionedTickDatasetWriter"]
