#!/usr/bin/env python3
"""SHA-bound Work/Codex handoff receipt for Alina read-only recovery evidence.

The bundle certifies its own completeness/integrity, NEVER that shards have
been downloaded, replayed, requalified, or economically validated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
FILES = (
    "git-head.txt",
    "preservation-census.json",
    "recovery-triage.jsonl",
    "triage-verification.json",
    "published-inventory-source.json",
    "RESTORE_INVENTORY.json.gz",
    "source-comparison.jsonl",
    "source-comparison-report.json",
)
RECEIPT = "WORK_RECOVERY_BUNDLE.json"


class BundleError(ValueError):
    pass


def _hash(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _json(root: Path, name: str) -> dict[str, Any]:
    value = json.loads((root / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BundleError("BUNDLE_INVALID_JSON_OBJECT:" + name)
    return value


def _inspect_jsonl(root: Path, name: str, *, triage: bool,
                   expected_catalog: str, expected_count: int) -> str:
    digest = hashlib.sha256()
    count = 0
    known_ids: set[str] = set()
    with (root / name).open("rb") as source:
        if triage:
            first = source.readline()
            header = json.loads(first)
            if (not isinstance(header, dict)
                    or header.get("schema") != "alina.recovery_triage.v1"
                    or header.get("catalog_index_sha256") != expected_catalog
                    or header.get("recoverability_certified") is not False):
                raise BundleError("BUNDLE_TRIAGE_HEADER_MISMATCH")
        for line in source:
            item = json.loads(line)
            if not isinstance(item, dict):
                raise BundleError("BUNDLE_INVALID_JSONL_ENTRY")
            if triage and item.get("kind") == "footer":
                if (item.get("candidate_count") != count
                        or item.get("candidates_sha256") != digest.hexdigest()
                        or source.read(1)):
                    raise BundleError("BUNDLE_TRIAGE_FOOTER_MISMATCH")
                if count != expected_count:
                    raise BundleError("BUNDLE_TRIAGE_COUNT_MISMATCH")
                return digest.hexdigest()
            if triage and item.get("kind") != "candidate":
                raise BundleError("BUNDLE_INVALID_TRIAGE_ENTRY")
            identity = item.get("dataset_id")
            if (not isinstance(identity, str) or not identity
                    or identity in known_ids
                    or item.get("validation_allowed") is not False
                    or item.get("recovery_status") != "NOT_ASSESSED"):
                raise BundleError("BUNDLE_UNSAFE_OR_DUPLICATE_CANDIDATE")
            known_ids.add(identity)
            count += 1
            digest.update(line)
    if triage:
        raise BundleError("BUNDLE_MISSING_TRIAGE_FOOTER")
    if count != expected_count:
        raise BundleError("BUNDLE_SOURCE_COMPARISON_COUNT_MISMATCH")
    return digest.hexdigest()


def inspect_bundle(root: Path) -> dict[str, Any]:
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise BundleError("BUNDLE_UNSAFE_DIRECTORY")
    file_receipts: dict[str, dict[str, Any]] = {}
    for name in FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise BundleError("BUNDLE_FILE_MISSING_OR_SYMLINKED:" + name)
        size, digest = _hash(path)
        if not size:
            raise BundleError("BUNDLE_EMPTY_EVIDENCE:" + name)
        file_receipts[name] = {"bytes": size, "sha256": digest}
    head = (root / "git-head.txt").read_text(encoding="ascii").strip()
    if not SHA40.fullmatch(head):
        raise BundleError("BUNDLE_INVALID_GIT_HEAD")
    census = _json(root, "preservation-census.json")
    triage = _json(root, "triage-verification.json")
    published = _json(root, "published-inventory-source.json")
    source = _json(root, "source-comparison-report.json")
    index_sha = census.get("catalog_index_sha256")
    initial = census.get("triage")
    verification = triage.get("triage")
    if (not isinstance(index_sha, str) or not SHA256.fullmatch(index_sha)
            or census.get("status") != "CATALOG_CLASSIFIED_NOT_RESTORED"
            or census.get("all_exploitable_data_restored") is not False
            or not isinstance(initial, dict) or not isinstance(verification, dict)
            or verification.get("status") != "TRIAGE_VERIFIED_NOT_RESTORED"
            or initial.get("candidate_count") != verification.get("candidate_count")
            or initial.get("candidates_sha256") != verification.get("candidates_sha256")
            or verification.get("catalog_index_sha256") != index_sha):
        raise BundleError("BUNDLE_CENSUS_TRIAGE_PARITY_FAILED")
    count = verification["candidate_count"]
    if type(count) is not int or count < 0:
        raise BundleError("BUNDLE_INVALID_CANDIDATE_COUNT")
    triage_sha = _inspect_jsonl(
        root, "recovery-triage.jsonl", triage=True,
        expected_catalog=index_sha, expected_count=count,
    )
    if triage_sha != verification.get("candidates_sha256"):
        raise BundleError("BUNDLE_TRIAGE_DIGEST_MISMATCH")
    inventory_file = file_receipts["RESTORE_INVENTORY.json.gz"]
    if (published.get("status") != "PUBLISHED_INVENTORY_ASSET_SHA256_VERIFIED_NOT_RESTORED"
            or published.get("asset_sha256") != inventory_file["sha256"]
            or published.get("asset_size_bytes") != inventory_file["bytes"]
            or published.get("raw_market_payloads_downloaded") != 0):
        raise BundleError("BUNDLE_PUBLISHED_INVENTORY_PARITY_FAILED")
    source_sha = _inspect_jsonl(
        root, "source-comparison.jsonl", triage=False,
        expected_catalog=index_sha, expected_count=count,
    )
    if (source.get("status") != "SOURCE_SNAPSHOT_COMPARED_NOT_RESTORED"
            or source.get("catalog_index_sha256") != index_sha
            or source.get("source_inventory_file_sha256") != inventory_file["sha256"]
            or source.get("source_comparison_jsonl_sha256") != source_sha
            or source.get("candidate_count") != count
            or source.get("recovered_shards") is not None
            or source.get("all_exploitable_data_restored") is not False):
        raise BundleError("BUNDLE_SOURCE_RECEIPT_PARITY_FAILED")
    return {
        "schema": "alina.work_recovery_bundle.v1",
        "status": "EVIDENCE_COMPLETE_NOT_RESTORED",
        "git_head": head,
        "catalog_index_sha256": index_sha,
        "candidate_count": count,
        "source_inventory_sha256": inventory_file["sha256"],
        "source_comparison_jsonl_sha256": source_sha,
        "files": file_receipts,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
        "replay_restore_certified": False,
        "economic_proof_allowed": False,
    }


def write_bundle(root: Path) -> dict[str, Any]:
    root = Path(root)
    receipt = inspect_bundle(root)
    target = root / RECEIPT
    if target.exists() or target.is_symlink():
        raise BundleError("BUNDLE_REFUSE_OVERWRITE")
    stage = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n",
            dir=root, prefix=".work-recovery-", suffix=".tmp", delete=False,
        ) as handle:
            stage = Path(handle.name)
            handle.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(stage, target)
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)
    return receipt


def verify_bundle(root: Path) -> dict[str, Any]:
    root = Path(root)
    path = root / RECEIPT
    if path.is_symlink() or not path.is_file():
        raise BundleError("BUNDLE_RECEIPT_MISSING_OR_SYMLINKED")
    expected = _json(root, RECEIPT)
    actual = inspect_bundle(root)
    if expected != actual:
        raise BundleError("BUNDLE_RECEIPT_MISMATCH")
    return actual


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = write_bundle(args.root) if args.write else verify_bundle(args.root)
    except (OSError, ValueError, TypeError, UnicodeError, EOFError) as exc:
        print(json.dumps({"status": "WORK_BUNDLE_INCOMPLETE", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
