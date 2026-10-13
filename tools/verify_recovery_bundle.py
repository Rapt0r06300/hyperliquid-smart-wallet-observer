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
    "hydration-plan.json",
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
    identities_digest = hashlib.sha256()
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
                return digest.hexdigest(), identities_digest.hexdigest()
            if triage and item.get("kind") != "candidate":
                raise BundleError("BUNDLE_INVALID_TRIAGE_ENTRY")
            identity = item.get("dataset_id")
            if (not isinstance(identity, str) or not identity
                    or identity in known_ids
                    or item.get("validation_allowed") is not False
                    or item.get("recovery_status") != "NOT_ASSESSED"):
                raise BundleError("BUNDLE_UNSAFE_OR_DUPLICATE_CANDIDATE")
            known_ids.add(identity)
            identities_digest.update((identity + "\n").encode("utf-8"))
            count += 1
            digest.update(line)
    if triage:
        raise BundleError("BUNDLE_MISSING_TRIAGE_FOOTER")
    if count != expected_count:
        raise BundleError("BUNDLE_SOURCE_COMPARISON_COUNT_MISMATCH")
    return digest.hexdigest(), identities_digest.hexdigest()


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
    hydration_plan = _json(root, "hydration-plan.json")
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
    triage_sha, triage_ids_sha = _inspect_jsonl(
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
    source_sha, source_ids_sha = _inspect_jsonl(
        root, "source-comparison.jsonl", triage=False,
        expected_catalog=index_sha, expected_count=count,
    )
    if triage_ids_sha != source_ids_sha:
        raise BundleError("BUNDLE_SOURCE_TRIAGE_ORDERED_IDENTITIES_DIFFER")
    if (source.get("status") != "SOURCE_SNAPSHOT_COMPARED_NOT_RESTORED"
            or source.get("catalog_index_sha256") != index_sha
            or source.get("source_inventory_file_sha256") != inventory_file["sha256"]
            or source.get("source_comparison_jsonl_sha256") != source_sha
            or source.get("candidate_count") != count
            or source.get("recovered_shards") is not None
            or source.get("all_exploitable_data_restored") is not False):
        raise BundleError("BUNDLE_SOURCE_RECEIPT_PARITY_FAILED")
    selected = hydration_plan.get("selection")
    dry = hydration_plan.get("hydration")
    if (hydration_plan.get("catalog_index_sha256") != index_sha
            or hydration_plan.get("source_inventory_file_sha256") != inventory_file["sha256"]
            or not isinstance(selected, dict) or not isinstance(dry, dict)
            or selected.get("status") != "HYDRATION_PLAN_NOT_REPLAY_CERTIFIED"
            or selected.get("replay_certified") is not False
            or selected.get("complete_coverage_claimed") is not False
            or dry.get("status") != "CACHED_RELEASE_BYTES_ONLY_NOT_REPLAY_CERTIFIED"
            or dry.get("executed") is not False
            or dry.get("replay_certified") is not False
            or dry.get("all_exploitable_data_restored") is not False
            or dry.get("downloaded_or_reused_verified_assets") != 0):
        raise BundleError("BUNDLE_HYDRATION_PLAN_NOT_READ_ONLY")
    planned = selected.get("selection")
    receipts = dry.get("source_asset_outcomes")
    count_selected = selected.get("selected_unique_outer_assets")
    bytes_selected = selected.get("selected_source_asset_bytes")
    if (not isinstance(planned, list) or not isinstance(receipts, list)
            or type(count_selected) is not int or not 0 <= count_selected <= 100
            or type(bytes_selected) is not int or not 0 <= bytes_selected <= 1_000_000_000
            or len(planned) != count_selected or len(receipts) != count_selected
            or dry.get("source_assets_selected") != count_selected):
        raise BundleError("BUNDLE_HYDRATION_PLAN_CARDINALITY_MISMATCH")
    seen_assets = set()
    checked_bytes = 0
    for item, receipt in zip(planned, receipts):
        if not isinstance(item, dict) or not isinstance(receipt, dict):
            raise BundleError("BUNDLE_HYDRATION_PLAN_INVALID_ASSET")
        tag, name = item.get("release_tag"), item.get("asset_name")
        sha, size = item.get("sha256"), item.get("size_bytes")
        if (not isinstance(tag, str) or not tag
                or not isinstance(name, str) or not name
                or not isinstance(sha, str) or not SHA256.fullmatch(sha)
                or type(size) is not int or size < 0
                or (tag, name) in seen_assets
                or receipt.get("release_tag") != tag
                or receipt.get("asset_name") != name
                or receipt.get("expected_size") != size
                or receipt.get("expected_sha256") != sha
                or receipt.get("status") != "NOT_DOWNLOADED_DRY_RUN"):
            raise BundleError("BUNDLE_HYDRATION_PLAN_UNVERIFIED_SOURCE")
        from urllib.parse import quote
        expected_url = (
            "https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer/releases/download/"
            + quote(tag, safe="") + "/" + quote(name, safe="")
        )
        if item.get("source_url") != expected_url:
            raise BundleError("BUNDLE_HYDRATION_PLAN_EXTERNAL_SOURCE")
        checked_bytes += size
        seen_assets.add((tag, name))
    if checked_bytes != bytes_selected:
        raise BundleError("BUNDLE_HYDRATION_PLAN_BYTES_MISMATCH")

    return {
        "schema": "alina.work_recovery_bundle.v1",
        "status": "EVIDENCE_COMPLETE_NOT_RESTORED",
        "git_head": head,
        "catalog_index_sha256": index_sha,
        "candidate_count": count,
        "source_inventory_sha256": inventory_file["sha256"],
        "source_comparison_jsonl_sha256": source_sha,
        "hydration_plan_assets": count_selected,
        "hydration_plan_bytes": bytes_selected,
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
