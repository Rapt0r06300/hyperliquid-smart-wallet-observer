#!/usr/bin/env python3
"""Deterministic, SHA-bound catalogue partition snapshots (never a SAFE promotion).

This is a lossless bridge to a partitioned canonical DATA_INDEX. It does not
silently replace the current index or bypass any quality/metrics gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping


class PartitionError(ValueError):
    pass


def _serialize(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_json(path: Path) -> tuple[Mapping[str, Any], bytes]:
    data = path.read_bytes()
    try:
        value = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PartitionError(f"invalid JSON in {path}") from exc
    if not isinstance(value, dict):
        raise PartitionError(f"expected object in {path}")
    return value, data


def build_snapshot(
    index_path: Path, output_root: Path, *,
    max_partition_bytes: int = 16 * 1024 * 1024,
) -> dict[str, Any]:
    """Create a complete parallel snapshot; do not mutate DATA_INDEX or metrics."""
    if max_partition_bytes < 1024:
        raise PartitionError("partition size too small")
    index, data = _read_json(index_path)
    rows = index.get("shards")
    if not isinstance(rows, list):
        raise PartitionError("missing shards array")
    by_bucket: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = set()
    for entry in rows:
        if not isinstance(entry, dict):
            raise PartitionError("invalid shard row")
        identity = entry.get("dataset_id")
        if not isinstance(identity, str) or not identity or identity in seen:
            raise PartitionError("duplicate or missing dataset_id")
        seen.add(identity)
        bucket = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:2]
        by_bucket.setdefault(bucket, []).append(entry)

    source_sha = _digest(data)
    name = f"index-{source_sha}"
    output_root = Path(output_root)
    destination = output_root / name
    if destination.exists():
        existing = load_snapshot(destination / "MANIFEST.json")
        if existing["source_index_sha256"] != source_sha:
            raise PartitionError("existing snapshot provenance mismatch")
        if sorted(existing["shards"], key=lambda r: r["dataset_id"]) != sorted(rows, key=lambda r: r["dataset_id"]):
            raise PartitionError("existing snapshot parity mismatch")
        return {"status": "VERIFIED_EXISTING", "shards": len(rows),
                "source_index_sha256": source_sha, "directory": str(destination)}

    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".index-staging-", dir=output_root) as staging:
        working = Path(staging)
        partitions: list[dict[str, Any]] = []
        for bucket in sorted(by_bucket):
            ordered = sorted(by_bucket[bucket], key=lambda x: x["dataset_id"])
            part_name = f"{bucket}.json"
            encoded = _serialize({"shards": ordered})
            if len(encoded) >= max_partition_bytes:
                raise PartitionError(f"partition {bucket} too large: {len(encoded)}")
            (working / part_name).write_bytes(encoded)
            partitions.append({"name": part_name, "sha256": _digest(encoded),
                               "bytes": len(encoded), "shards": len(ordered)})
        envelope = {
            "schema": "alina.partitioned_data_index.v1",
            "source_index_sha256": source_sha,
            "source_index_bytes": len(data),
            "source_metadata": {k: v for k, v in index.items() if k != "shards"},
            "total_shards": len(rows),
            "partitions": partitions,
        }
        (working / "MANIFEST.json").write_bytes(_serialize(envelope))
        verification = load_snapshot(working / "MANIFEST.json")
        if verification["shards"] != rows:
            # Order in DATA_INDEX may be chronological; partitions are sorted by
            # identity. Compare exact records without losing duplicate detection.
            original = sorted(rows, key=lambda r: r["dataset_id"])
            if sorted(verification["shards"], key=lambda r: r["dataset_id"]) != original:
                raise PartitionError("partition reconstruction parity mismatch")
        os.replace(working, destination)
    return {"status": "VERIFIED_NEW", "shards": len(rows),
            "source_index_sha256": source_sha, "partitions": len(partitions),
            "directory": str(destination)}


def load_snapshot(manifest_path: Path) -> dict[str, Any]:
    envelope, _ = _read_json(Path(manifest_path))
    if envelope.get("schema") != "alina.partitioned_data_index.v1":
        raise PartitionError("unsupported partition snapshot")
    files = envelope.get("partitions")
    if not isinstance(files, list):
        raise PartitionError("missing partition inventory")
    all_rows: list[dict[str, Any]] = []
    used: set[str] = set()
    ids: set[str] = set()
    for part in files:
        if not isinstance(part, dict):
            raise PartitionError("invalid partition descriptor")
        name = part.get("name")
        if (not isinstance(name, str) or len(name) != 7
                or name[:2] not in {f"{i:02x}" for i in range(256)}
                or name[2:] != ".json" or name in used):
            raise PartitionError("unsafe or duplicate partition name")
        used.add(name)
        blob = (Path(manifest_path).parent / name).read_bytes()
        if (len(blob) != part.get("bytes") or _digest(blob) != part.get("sha256")):
            raise PartitionError(f"partition SHA/size mismatch: {name}")
        try:
            obj = json.loads(blob)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PartitionError(f"invalid partition content: {name}") from exc
        rows = obj.get("shards") if isinstance(obj, dict) else None
        if not isinstance(rows, list) or len(rows) != part.get("shards"):
            raise PartitionError("partition count mismatch")
        for row in rows:
            identity = row.get("dataset_id") if isinstance(row, dict) else None
            if (not isinstance(identity, str) or not identity or identity in ids
                    or hashlib.sha256(identity.encode("utf-8")).hexdigest()[:2] != name[:2]):
                raise PartitionError("invalid, duplicated or misbucketed dataset_id")
            ids.add(identity)
        all_rows.extend(rows)
    if len(all_rows) != envelope.get("total_shards"):
        raise PartitionError("global shard count mismatch")
    return {"shards": all_rows, "source_index_sha256": envelope["source_index_sha256"],
            "source_metadata": envelope["source_metadata"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a lossless partition index snapshot")
    parser.add_argument("--index", type=Path, default=Path("catalog/DATA_INDEX.json"))
    parser.add_argument("--output", type=Path, default=Path("catalog/index-partition-snapshots"))
    args = parser.parse_args()
    print(json.dumps(build_snapshot(args.index, args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
