#!/usr/bin/env python3
"""Carry immutable, SHA-bound replay receipts across racing main publications.

A rejected git push must never trigger a blind merge of generated catalog files.
Capture only newly verified Release receipts, reset to the latest main, and
reclassify the exact same immutable assets under the current canonical policy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

import backfill_replay_compatibility as replay

LOCATOR_FIELDS = ("release_repository", "release_tag", "release_asset",
                  "release_container_asset", "release_member")
IDENTITY_FIELDS = ("family", "venue", "symbol", "source")


def _previous_results() -> dict:
    command = subprocess.run(
        ["git", "show", "HEAD:catalog/REPLAY_COMPAT_PATCH.json"],
        capture_output=True, text=True, check=False,
    )
    if command.returncode:
        raise replay.BackfillError("cannot read original replay receipts from HEAD")
    try:
        data = json.loads(command.stdout)
        results = data["results"]
    except (ValueError, KeyError, TypeError) as exc:
        raise replay.BackfillError("invalid original replay receipt patch") from exc
    if not isinstance(results, dict):
        raise replay.BackfillError("invalid original replay receipt map")
    return results


def _bound(row: dict, result: dict) -> bool:
    sha = str(row.get("sha256") or "").lower()
    return (
        bool(re.fullmatch("[0-9a-f]{64}", sha))
        and type(row.get("bytes")) is int
        and row["bytes"] > 0
        and result.get("verified_from_release") is True
        and str(result.get("asset_sha256") or "").lower() == sha
        and type(result.get("asset_size")) is int
        and result["asset_size"] == row["bytes"]
        and result.get("verifier_version") == replay.VERIFIER_VERSION
    )


def _identity(row: dict, root: Path) -> dict:
    manifest = replay._manifest_for_row(row)
    if manifest is None:
        raise replay.BackfillError("missing indexed manifest for replay receipt")
    if (manifest.get("dataset_id") != row.get("dataset_id")
            or str(manifest.get("sha256") or "").lower() != str(row.get("sha256") or "").lower()):
        raise replay.BackfillError("receipt manifest SHA or dataset identity mismatch")
    hydrated = dict(row)
    replay._hydrate_release_fields(hydrated, manifest)
    fields = {}
    for key in LOCATOR_FIELDS:
        fields[key] = hydrated.get(key) or None
    for key in IDENTITY_FIELDS:
        fields[key] = manifest.get(key) or hydrated.get(key) or None
    if not all(fields.get(k) for k in LOCATOR_FIELDS[:3]):
        raise replay.BackfillError("replay receipt requires immutable Release coordinates")
    return fields


def capture(path: Path) -> int:
    before = _previous_results()
    patch = replay._load_patch()
    now = patch.get("results")
    index = replay._load_json(replay.INDEX_PATH)
    if not isinstance(now, dict) or not isinstance(index.get("shards"), list):
        raise replay.BackfillError("invalid replay patch or index")
    rows = {
        str(row.get("dataset_id")): row for row in index["shards"]
        if isinstance(row, dict) and row.get("dataset_id")
    }
    receipts = {}
    for dataset_id, proof in sorted(now.items()):
        if proof == before.get(dataset_id):
            continue
        row = rows.get(dataset_id)
        if not isinstance(proof, dict) or row is None or not _bound(row, proof):
            raise replay.BackfillError("changed replay receipt lacks immutable SHA proof: " + dataset_id)
        receipts[dataset_id] = {
            "sha256": row["sha256"], "bytes": row["bytes"],
            "identity": _identity(row, replay.ROOT), "proof": proof,
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "alina.replay_publish_bundle.v1",
                                "receipts": receipts}, sort_keys=True) + "\n",
                    encoding="utf-8")
    return len(receipts)


def apply(path: Path) -> int:
    bundle = replay._load_json(path)
    receipts = bundle.get("receipts")
    if bundle.get("schema") != "alina.replay_publish_bundle.v1" or not isinstance(receipts, dict):
        raise replay.BackfillError("unrecognized replay receipt bundle")
    index = replay._load_json(replay.INDEX_PATH)
    rows = index.get("shards")
    if not isinstance(rows, list):
        raise replay.BackfillError("invalid current index")
    indexed = {
        str(row.get("dataset_id")): row for row in rows
        if isinstance(row, dict) and row.get("dataset_id")
    }
    current = replay._load_patch()
    known = current.get("results")
    if not isinstance(known, dict):
        raise replay.BackfillError("invalid current replay results")

    # Check the whole bundle against the NEW main before changing ANY manifest.
    pending = []
    for dataset_id, entry in sorted(receipts.items()):
        row = indexed.get(dataset_id)
        if not isinstance(entry, dict) or row is None:
            raise replay.BackfillError("replay receipt target absent from current index")
        proof = entry.get("proof")
        if not isinstance(proof, dict) or not _bound(row, proof):
            raise replay.BackfillError("stale or unverified replay receipt: " + dataset_id)
        if (row.get("sha256") != entry.get("sha256")
                or row.get("bytes") != entry.get("bytes")
                or _identity(row, replay.ROOT) != entry.get("identity")):
            raise replay.BackfillError("replay receipt source changed: " + dataset_id)
        previous = known.get(dataset_id)
        if (isinstance(previous, dict)
                and previous.get("verifier_version") == replay.VERIFIER_VERSION
                and previous.get("verified_from_release") is True
                and previous.get("asset_sha256") == proof.get("asset_sha256")
                and previous != proof):
            raise replay.BackfillError("conflicting current-version replay proof: " + dataset_id)
        if previous == proof and row.get("replay_compatible") == proof.get("replay_compatible"):
            continue
        pending.append((dataset_id, row, proof))

    for dataset_id, row, proof in pending:
        replay._apply_result(row, proof, root=replay.ROOT)
        known[dataset_id] = dict(proof)
    if pending:
        current["results"] = dict(sorted(known.items()))
        current["processed_assets"] = len(known)
        replay._write_json(replay.PATCH_PATH, current)
        replay._refresh_catalog(index, replay.ROOT)
    return len(pending)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("capture", "apply"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        count = capture(args.path) if args.command == "capture" else apply(args.path)
    except (replay.BackfillError, OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(2, f"REPLAY_RECEIPT_NO_GO: {exc}\n")
    print(json.dumps({"action": args.command, "verified_receipts": count}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
