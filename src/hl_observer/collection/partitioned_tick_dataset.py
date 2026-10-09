"""Partition replay evidence by source/channel/instrument without changing TickEnvelope."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from hl_observer.collection.tick_dataset import TickDatasetWriter, TickEnvelope

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _component(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "unknown"
    clean = _SAFE.sub("_", raw).strip("._") or "unknown"
    if clean == raw:
        return clean
    # Lossy sanitisation must never alias two real exchange identifiers onto the
    # same on-disk partition (for example multiple Unicode Bitget symbols -> USDT).
    suffix = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{clean}-{suffix}"


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
        self._last_connection: dict[tuple[str, str, str], str | None] = {}
        # Track exchange-authenticated L2 predecessor evidence per partition.
        # A genuine subsequent full snapshot can seal the damaged interval,
        # allowing later clean frames to be recovered as a separate shard.
        self._last_l2_sequence: dict[tuple[str, str, str], int] = {}
        self._l2_gap_pending: set[tuple[str, str, str]] = set()

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
        # Route single events through the same reconnect-epoch barriers as
        # batch ingestion. Direct writer.append silently merged connections.
        return len(self.append_batch_records((envelope,)))

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
        for key, rows in grouped.items():
            # A reconnect defines a new causal epoch. Never let one immutable
            # shard span two websocket connection_ids.
            chunks: list[list[tuple[int, TickEnvelope]]] = []
            current: list[tuple[int, TickEnvelope]] = []
            current_connection: str | None | object = object()
            for row in rows:
                connection = (
                    str(row[1].connection_id)
                    if row[1].connection_id is not None
                    else None
                )
                if current and connection != current_connection:
                    chunks.append(current)
                    current = []
                current.append(row)
                current_connection = connection
            if current:
                chunks.append(current)

            writer = self._writer(rows[0][1])
            for chunk in chunks:
                connection = (
                    str(chunk[0][1].connection_id)
                    if chunk[0][1].connection_id is not None
                    else None
                )
                previous = self._last_connection.get(key)
                if key in self._last_connection and connection != previous:
                    writer.rotate()
                    self._last_l2_sequence.pop(key, None)
                    self._l2_gap_pending.discard(key)
                self._last_connection[key] = connection

                # Segment at the FIRST authentic exchange re-anchor after a
                # provable gap. This does not repair missing deltas: they stay
                # in the preceding damaged shard, never in the new SAFE epoch.
                buffered: list[tuple[int, TickEnvelope]] = []
                def flush_segment() -> None:
                    if not buffered:
                        return
                    persisted = writer.append_batch_records(
                        envelope for _index, envelope in buffered
                    )
                    for (index, _envelope), record in zip(buffered, persisted):
                        output[index] = record
                    buffered.clear()

                for indexed in chunk:
                    envelope = indexed[1]
                    source = str(envelope.source_id)
                    native_l2 = (
                        envelope.channel == "l2Book"
                        and source in {
                            "bybit_public_ws", "okx_public_ws",
                            "gate_public_ws", "bitget_public_ws",
                        }
                    )
                    if native_l2:
                        summary = envelope.parsed_summary
                        summary = summary if isinstance(summary, dict) else {}
                        is_snapshot = str(envelope.event_kind).upper().endswith("SNAPSHOT")
                        if is_snapshot:
                            if key in self._l2_gap_pending:
                                flush_segment()
                                writer.rotate()
                            self._l2_gap_pending.discard(key)
                            self._last_l2_sequence.pop(key, None)
                        else:
                            before = self._last_l2_sequence.get(key)
                            seq = envelope.sequence
                            prev = summary.get("prev_sequence")
                            first = summary.get("first_update_id")
                            if before is not None and (
                                (type(prev) is int and prev not in {-1, before})
                                or (type(first) is int and first > before + 1)
                                or (type(seq) is int and seq < before)
                            ):
                                self._l2_gap_pending.add(key)
                        seq = envelope.sequence
                        if type(seq) is int:
                            before = self._last_l2_sequence.get(key)
                            if before is None or seq > before:
                                self._last_l2_sequence[key] = seq
                    buffered.append(indexed)
                flush_segment()
        if any(record is None for record in output):
            raise RuntimeError("partitioned writer failed to persist the full batch")
        return [record for record in output if record is not None]

    def rotate_all(self) -> list[Path]:
        """Return EVERY sealed shard, including automatic size/reconnect rotations.

        TickDatasetWriter can seal files internally while append_batch_records
        is writing. The old implementation returned only the final rotate()
        result, omitting earlier durable gzip assets from the publish bundle.
        Do not use in-memory counters as a surrogate for on-disk evidence.
        """
        shards: set[Path] = set()
        for writer in self._writers.values():
            writer.rotate()
            shards.update(
                writer.shards_directory.glob(f"{writer.stream_name}.*.jsonl.gz")
            )
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
