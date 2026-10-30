"""Bounded deterministic soak harness for Copy-Vault collector recovery.

This is a test/diagnostic harness only.  It never opens a network connection,
publishes a SAFE shard, or submits an order.  The harness exercises the
properties that a hosted collector workflow must later prove: bounded input,
stable deduplication, explicit queue pressure, durable checkpoint identity,
and exact equivalence between continuous and interrupted/resumed processing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tracemalloc
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

SCHEMA = "hypersmart.copy_vault_collector_soak.v1"
MAX_EVENTS = 100_000
DEFAULT_EVENTS = 10_000
DEFAULT_BATCH_SIZE = 128
DEFAULT_QUEUE_LIMIT = 256


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validate_output_path(path: Path, *, prefix: str) -> None:
    """Reject output paths that could escape through links or a directory."""
    if path.is_symlink():
        raise ValueError(f"{prefix}_SYMLINKED")
    if path.exists() and not path.is_file():
        raise ValueError(f"{prefix}_DIRECTORY")
    for parent in path.parents:
        if parent.is_symlink():
            raise ValueError(f"{prefix}_SYMLINKED_PARENT")


def generate_events(count: int) -> list[dict[str, Any]]:
    """Generate a bounded, repeatable stream with intentional exact duplicates."""
    if type(count) is not int or count < 1 or count > MAX_EVENTS:
        raise ValueError("SOAK_INPUT_OUT_OF_BOUNDS")
    return [
        {
            "event_id": f"fill-{index:08d}",
            "sequence": index,
            "coin": "BTC" if index % 2 == 0 else "ETH",
            "ts_ms": 1_700_000_000_000 + index * 100,
            "notional_usd": 10 + (index % 17),
            "duplicate": False,
        }
        for index in range(count)
    ] + [
        {
            "event_id": f"fill-{index:08d}",
            "sequence": index,
            "coin": "BTC" if index % 2 == 0 else "ETH",
            "ts_ms": 1_700_000_000_000 + index * 100,
            "notional_usd": 10 + (index % 17),
            "duplicate": True,
        }
        for index in range(0, count, 97)
    ]


def _checkpoint(
    *,
    input_sha256: str,
    cursor: int,
    accepted: Iterable[Mapping[str, Any]],
    duplicate_count: int,
) -> dict[str, Any]:
    accepted_rows = list(accepted)
    body = {
        "schema": "hypersmart.copy_vault_collector_soak_checkpoint.v2",
        "input_sha256": input_sha256,
        "cursor": cursor,
        "accepted_count": len(accepted_rows),
        "accepted_sha256": _sha256(accepted_rows),
        "duplicate_count": duplicate_count,
    }
    return body | {"checkpoint_sha256": _sha256(body)}


def _verify_checkpoint(checkpoint: Mapping[str, Any], input_sha256: str) -> None:
    body = {key: value for key, value in checkpoint.items() if key != "checkpoint_sha256"}
    if (
        checkpoint.get("schema") != "hypersmart.copy_vault_collector_soak_checkpoint.v2"
        or not _is_sha256(checkpoint.get("input_sha256"))
        or checkpoint.get("input_sha256") != input_sha256
        or type(checkpoint.get("cursor")) is not int
        or checkpoint.get("cursor", -1) < 0
        or type(checkpoint.get("accepted_count")) is not int
        or checkpoint.get("accepted_count", -1) < 0
        or type(checkpoint.get("duplicate_count")) is not int
        or checkpoint.get("duplicate_count", -1) < 0
        or not _is_sha256(checkpoint.get("accepted_sha256"))
        or not _is_sha256(checkpoint.get("checkpoint_sha256"))
        or checkpoint.get("checkpoint_sha256") != _sha256(body)
    ):
        raise ValueError("SOAK_CHECKPOINT_INVALID_OR_STALE")


def run_soak(
    events: Iterable[Mapping[str, Any]],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    queue_limit: int = DEFAULT_QUEUE_LIMIT,
    interrupt_after: int | None = None,
    checkpoint_path: str | Path | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Process a bounded stream and optionally resume from a durable checkpoint."""
    rows = [dict(row) for row in events]
    if not rows or len(rows) > MAX_EVENTS * 2:
        raise ValueError("SOAK_INPUT_OUT_OF_BOUNDS")
    if type(batch_size) is not int or not 1 <= batch_size <= 10_000:
        raise ValueError("SOAK_BATCH_SIZE_OUT_OF_BOUNDS")
    if type(queue_limit) is not int or not 1 <= queue_limit <= MAX_EVENTS:
        raise ValueError("SOAK_QUEUE_LIMIT_OUT_OF_BOUNDS")
    if interrupt_after is not None and (
        type(interrupt_after) is not int or interrupt_after < 1
    ):
        raise ValueError("SOAK_INTERRUPT_AFTER_OUT_OF_BOUNDS")
    input_sha256 = _sha256(rows)
    checkpoint_file = Path(checkpoint_path) if checkpoint_path is not None else None
    if checkpoint_file is not None:
        _validate_output_path(checkpoint_file, prefix="SOAK_CHECKPOINT")

    cursor = 0
    accepted: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    duplicates = 0
    queue_high_water = 0
    interrupted = False
    if resume:
        if checkpoint_file is None or not checkpoint_file.is_file():
            raise ValueError("SOAK_RESUME_CHECKPOINT_UNAVAILABLE")
        checkpoint = json.loads(checkpoint_file.read_text(encoding="utf-8"))
        if not isinstance(checkpoint, Mapping):
            raise ValueError("SOAK_CHECKPOINT_INVALID_OR_STALE")
        _verify_checkpoint(checkpoint, input_sha256)
        cursor = checkpoint["cursor"]
        duplicates = checkpoint["duplicate_count"]
        if cursor > len(rows):
            raise ValueError("SOAK_CHECKPOINT_CURSOR_OUT_OF_RANGE")
        for row in rows[:cursor]:
            event_id = str(row.get("event_id") or "")
            if not event_id:
                raise ValueError("SOAK_EVENT_ID_MISSING")
            payload = {key: value for key, value in row.items() if key != "duplicate"}
            payload_sha256 = _sha256(payload)
            previous_payload_sha256 = seen.get(event_id)
            if previous_payload_sha256 is not None:
                if previous_payload_sha256 != payload_sha256:
                    raise ValueError("SOAK_EVENT_ID_CONFLICT")
                continue
            seen[event_id] = payload_sha256
            accepted.append(payload)
        if len(accepted) != checkpoint.get("accepted_count") or _sha256(accepted) != checkpoint.get("accepted_sha256"):
            raise ValueError("SOAK_CHECKPOINT_CONTENT_MISMATCH")

    while cursor < len(rows):
        batch_end = min(len(rows), cursor + batch_size)
        batch = rows[cursor:batch_end]
        queue_high_water = max(queue_high_water, min(len(batch), queue_limit))
        for row in batch:
            event_id = str(row.get("event_id") or "")
            if not event_id:
                raise ValueError("SOAK_EVENT_ID_MISSING")
            payload = {key: value for key, value in row.items() if key != "duplicate"}
            payload_sha256 = _sha256(payload)
            previous_payload_sha256 = seen.get(event_id)
            if previous_payload_sha256 is not None:
                if previous_payload_sha256 != payload_sha256:
                    raise ValueError("SOAK_EVENT_ID_CONFLICT")
                duplicates += 1
                continue
            seen[event_id] = payload_sha256
            accepted.append(payload)
        cursor = batch_end
        if checkpoint_file is not None:
            record = _checkpoint(
                input_sha256=input_sha256,
                cursor=cursor,
                accepted=accepted,
                duplicate_count=duplicates,
            )
            checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
            _validate_output_path(checkpoint_file, prefix="SOAK_CHECKPOINT")
            temporary = checkpoint_file.with_suffix(checkpoint_file.suffix + ".tmp")
            _validate_output_path(temporary, prefix="SOAK_CHECKPOINT_TEMP")
            temporary.write_bytes(_canonical(record))
            _validate_output_path(temporary, prefix="SOAK_CHECKPOINT_TEMP")
            _validate_output_path(checkpoint_file, prefix="SOAK_CHECKPOINT")
            temporary.replace(checkpoint_file)
        if interrupt_after is not None and cursor >= interrupt_after and cursor < len(rows):
            interrupted = True
            break

    complete = cursor == len(rows)
    result = {
        "schema": SCHEMA,
        "status": "COMPLETE" if complete else "CONTINUATION_REQUIRED",
        "input_count": len(rows),
        "processed_count": cursor,
        "accepted_count": len(accepted),
        "duplicate_count": duplicates,
        "queue_high_water": queue_high_water,
        "queue_limit": queue_limit,
        "queue_drops": 0,
        "interrupted": interrupted,
        "input_sha256": input_sha256,
        "accepted_sha256": _sha256(accepted),
        "checkpoint_path": str(checkpoint_file) if checkpoint_file is not None else None,
        "paper_read_only": True,
        "real_execution": False,
        "safe_publication": False,
    }
    return result


def execute_soak(
    *,
    events_count: int = DEFAULT_EVENTS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    queue_limit: int = DEFAULT_QUEUE_LIMIT,
    interrupt_after: int | None = None,
    checkpoint_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run continuous and interrupted/resumed paths, returning a receipt."""
    events = generate_events(events_count)
    tracemalloc.start()
    try:
        continuous = run_soak(
            events, batch_size=batch_size, queue_limit=queue_limit,
        )
        interrupted = run_soak(
            events, batch_size=batch_size, queue_limit=queue_limit,
            interrupt_after=(
                interrupt_after if interrupt_after is not None else batch_size
            ), checkpoint_path=checkpoint_path,
        )
        resumed = run_soak(
            events, batch_size=batch_size, queue_limit=queue_limit,
            checkpoint_path=checkpoint_path, resume=True,
        ) if interrupted["status"] != "COMPLETE" else interrupted
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    same_result = (
        continuous["accepted_sha256"] == resumed["accepted_sha256"]
        and continuous["accepted_count"] == resumed["accepted_count"]
        and continuous["input_sha256"] == resumed["input_sha256"]
        and resumed["queue_drops"] == 0
    )
    return {
        "schema": SCHEMA,
        "status": "PASS" if same_result else "FAIL",
        "continuous": continuous,
        "interrupted": interrupted,
        "resumed": resumed,
        "same_result_after_resume": same_result,
        "peak_memory_bytes": peak,
        "bounded": events_count <= MAX_EVENTS,
        "paper_read_only": True,
        "real_execution": False,
        "safe_publication": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=DEFAULT_EVENTS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--queue-limit", type=int, default=DEFAULT_QUEUE_LIMIT)
    parser.add_argument("--interrupt-after", type=int, default=None)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()
    try:
        result = execute_soak(
            events_count=args.events, batch_size=args.batch_size,
            queue_limit=args.queue_limit, interrupt_after=args.interrupt_after,
            checkpoint_path=args.checkpoint,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "schema": SCHEMA,
            "status": "BLOCKED_EXTERNAL",
            "error": str(exc),
            "paper_read_only": True,
            "real_execution": False,
            "safe_publication": False,
        }
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.json is not None:
        try:
            _validate_output_path(args.json, prefix="SOAK_JSON_OUTPUT")
            args.json.parent.mkdir(parents=True, exist_ok=True)
            _validate_output_path(args.json, prefix="SOAK_JSON_OUTPUT")
            args.json.write_text(encoded, encoding="utf-8")
        except OSError as exc:
            print(json.dumps({"schema": SCHEMA, "status": "BLOCKED_EXTERNAL", "error": str(exc)}), file=sys.stderr)
            return 2
        except ValueError as exc:
            print(json.dumps({"schema": SCHEMA, "status": "BLOCKED_EXTERNAL", "error": str(exc)}), file=sys.stderr)
            return 2
    print(encoded, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

