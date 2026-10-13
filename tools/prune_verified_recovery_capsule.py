#!/usr/bin/env python3
"""Prove a completed recovery capsule redundant before deleting its GitHub Release.

Manual, GitHub-hosted use only. By default this is read-only. It never touches
collectors, campaigns, the user's PC or trading. Exact SHA-256 payload parity is
required for --execute; an absent/unreadable byte causes a hard refusal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.partitioned_data_index import read_index
except ModuleNotFoundError:
    from partitioned_data_index import read_index

REPOSITORY = "Rapt0r06300/hyperliquid-smart-wallet-observer"
SHA64 = re.compile(r"[0-9a-f]{64}\Z")
TAG = re.compile(r"[A-Za-z0-9._-]{1,180}\Z")


class Refuse(RuntimeError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request(url: str, *, method: str = "GET"):
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        raise Refuse("GH_TOKEN_REQUIRED_ON_GITHUB_HOSTED_RUNNER")
    req = urllib.request.Request(url, method=method, headers={
        "Authorization": "Bearer " + token,
        "User-Agent": "alina-recovery-gc/1",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    return urllib.request.urlopen(req, timeout=120)


def release(tag: str) -> dict[str, Any]:
    if not TAG.fullmatch(tag):
        raise Refuse("UNSAFE_RELEASE_TAG")
    with request(f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{tag}") as response:
        payload = json.load(response)
    if not isinstance(payload, dict) or payload.get("tag_name") != tag:
        raise Refuse("RELEASE_TAG_IDENTITY_MISMATCH")
    return payload


def assets(release_row: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = release_row.get("assets")
    if not isinstance(rows, list):
        raise Refuse("ASSET_LIST_MISSING")
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row.get("name") if isinstance(row, dict) else None
        digest = str(row.get("digest") or "").removeprefix("sha256:") if isinstance(row, dict) else ""
        if (not isinstance(name, str) or name in out or not name
                or not SHA64.fullmatch(digest)
                or type(row.get("size")) is not int or row["size"] < 0
                or row.get("state") != "uploaded"):
            raise Refuse("UNVERIFIABLE_REMOTE_ASSET")
        out[name] = row
    return out


def download(asset: Mapping[str, Any], target: Path, *, max_bytes: int) -> str:
    size = asset["size"]
    digest = asset["digest"].removeprefix("sha256:")
    url = asset.get("browser_download_url")
    if (size > max_bytes or not isinstance(url, str)
            or not url.startswith(f"https://github.com/{REPOSITORY}/releases/download/")):
        raise Refuse("SOURCE_ASSET_OVER_LIMIT_OR_BAD_URL")
    h = hashlib.sha256()
    total = 0
    # Release browser links redirect to a different CDN hostname. Never send
    # the GitHub token through that redirect: the canonical repo is public.
    source = urllib.request.Request(url, headers={
        "User-Agent": "alina-recovery-gc/1",
    })
    with urllib.request.urlopen(source, timeout=120) as response, target.open("wb") as output:
        while chunk := response.read(8 * 1024 * 1024):
            total += len(chunk)
            if total > size:
                raise Refuse("REMOTE_ASSET_EXCEEDS_DECLARED_SIZE")
            h.update(chunk)
            output.write(chunk)
    if total != size or h.hexdigest() != digest:
        raise Refuse("REMOTE_ASSET_SHA256_OR_SIZE_MISMATCH")
    return h.hexdigest()


def control_json(asset: Mapping[str, Any], root: Path, name: str) -> dict:
    target = root / name
    download(asset, target, max_bytes=64 * 1024 * 1024)
    try:
        parsed = json.loads(target.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise Refuse("INVALID_CONTROL_JSON") from exc
    if not isinstance(parsed, dict):
        raise Refuse("INVALID_CONTROL_ROOT")
    return parsed


def verify_capsule(tag: str, *, max_bytes: int) -> dict[str, Any]:
    if not isinstance(tag, str) or not tag.startswith("alina-recovery-"):
        raise Refuse("NOT_A_RECOVERY_CAPSULE_TAG")
    rec = release(tag)
    rec_assets = assets(rec)
    idx_asset = rec_assets.get("ALINA_RECOVERY_INDEX.json")
    complete_asset = rec_assets.get("CANONICAL_PUBLICATION.json")
    if idx_asset is None or complete_asset is None:
        raise Refuse("NO_CANONICAL_COMPLETION_PROOF_KEEP_UNIQUE_RECOVERY")

    with tempfile.TemporaryDirectory(prefix="alina-capsule-parity-") as temporary:
        root = Path(temporary)
        idx = control_json(idx_asset, root, "recovery-index.json")
        done = control_json(complete_asset, root, "canonical-completion.json")
        if (idx.get("schema") != "alina.recovery_capsule.v1"
                or done.get("schema") != "alina.recovery_capsule_completion.v1"
                or idx.get("repository") != REPOSITORY
                or done.get("repository") != REPOSITORY
                or done.get("recovery_release_tag") != tag):
            raise Refuse("CAPSULE_PROVENANCE_MISMATCH")
        canonical_tag = done.get("canonical_release_tag")
        canonical = release(canonical_tag)
        main_asset = assets(canonical).get("RUN_MANIFEST.json")
        if main_asset is None:
            raise Refuse("CANONICAL_MANIFEST_ABSENT_KEEP_RECOVERY")
        if (done.get("run_manifest_sha256") != main_asset["digest"].removeprefix("sha256:")
                or done.get("run_manifest_bytes") != main_asset["size"]):
            raise Refuse("CANONICAL_MANIFEST_CHANGED_KEEP_RECOVERY")
        run = control_json(main_asset, root, "canonical-manifest.json")
        if (run.get("release_tag") != canonical_tag
                or run.get("repository") != REPOSITORY
                or (run.get("recovery_capsule") or {}).get("release_tag") != tag):
            raise Refuse("RUN_MANIFEST_RECOVERY_LINK_MISSING")
        manifests = run.get("manifests")
        if (not isinstance(manifests, list) or not manifests
                or run.get("shard_count") != len(manifests)
                or run.get("safe_count") != len(manifests)
                or run.get("partial_count") != 0 or run.get("reject_count") != 0):
            raise Refuse("CANONICAL_NOT_SAFE_ONLY")
        expected: dict[str, tuple[str, int, str]] = {}
        catalog_bindings: list[dict[str, Any]] = []
        release_cache: dict[str, dict] = {}
        for row in manifests:
            if (not isinstance(row, dict) or row.get("quality_status") != "SAFE"
                    or row.get("replay_compatible") is not True
                    or row.get("asset_verified") is not True):
                raise Refuse("UNQUALIFIED_CANONICAL_SHARD")
            member = row.get("release_asset")
            digest = str(row.get("sha256") or "").lower()
            count = row.get("bytes")
            dataset_id = row.get("dataset_id")
            locator = row.get("release")
            if (not isinstance(member, str) or not member or "/" in member
                    or member in expected or not SHA64.fullmatch(digest)
                    or type(count) is not int or count <= 0
                    or not isinstance(dataset_id, str) or not dataset_id
                    or not isinstance(locator, dict)
                    or locator.get("repository") != REPOSITORY):
                raise Refuse("CANONICAL_SHARD_IDENTITY_INVALID")
            rel_tag = locator.get("release_tag")
            rel_asset = locator.get("asset_name")
            if not isinstance(rel_tag, str) or not TAG.fullmatch(rel_tag):
                raise Refuse("CANONICAL_ASSET_TAG_INVALID")
            if rel_tag not in release_cache:
                release_cache[rel_tag] = assets(release(rel_tag))
            remote = release_cache[rel_tag].get(rel_asset)
            if (remote is None or locator.get("remote_size") != remote["size"]
                    or locator.get("remote_digest") != remote["digest"]):
                raise Refuse("CANONICAL_ASSET_NOT_VERIFIED")
            expected[member] = (digest, count, dataset_id)
            catalog_bindings.append({
                "dataset_id": dataset_id, "sha256": digest, "bytes": count,
                "release_tag": rel_tag, "release_asset": member,
                "outer_asset": rel_asset,
            })

        parts = idx.get("parts")
        if not isinstance(parts, list) or not parts:
            raise Refuse("CAPSULE_PART_INDEX_MISSING")
        part_names = {x.get("name") for x in parts if isinstance(x, dict)}
        if (len(part_names) != len(parts)
                or set(rec_assets) != part_names | {
                    "ALINA_RECOVERY_INDEX.json", "CANONICAL_PUBLICATION.json"
                }):
            raise Refuse("CAPSULE_ASSET_INVENTORY_INCONSISTENT")
        if sum(rec_assets[name]["size"] for name in part_names) > max_bytes:
            raise Refuse("CAPSULE_SOURCE_EXCEEDS_CLOUD_VERIFY_BUDGET")

        observed_assets: set[str] = set()
        observed_manifests: set[str] = set()
        original_index = None
        for i, part in enumerate(parts):
            name = part["name"]
            remote = rec_assets[name]
            if (part.get("bytes") != remote["size"]
                    or part.get("sha256") != remote["digest"].removeprefix("sha256:")):
                raise Refuse("CAPSULE_PART_SHA256_MISMATCH")
            archive_path = root / f"part-{i}.tar"
            download(remote, archive_path, max_bytes=max_bytes)
            with tarfile.open(archive_path, mode="r:") as archive:
                for entry in archive:
                    if not entry.isfile() or entry.size < 0:
                        raise Refuse("UNSAFE_CAPSULE_TAR_ENTRY")
                    source = archive.extractfile(entry)
                    if source is None:
                        raise Refuse("MISSING_CAPSULE_TAR_STREAM")
                    if entry.name == "BUNDLE_INDEX.json":
                        body = source.read(64 * 1024 * 1024 + 1)
                        if len(body) > 64 * 1024 * 1024 or sha(body) != idx.get("bundle_index_sha256"):
                            raise Refuse("CAPSULE_BUNDLE_INDEX_CHANGED")
                        parsed = json.loads(body)
                        if original_index is not None and original_index != parsed:
                            raise Refuse("CAPSULE_INDEX_INCONSISTENT_ACROSS_PARTS")
                        original_index = parsed
                    elif entry.name.startswith("assets/"):
                        member = entry.name.removeprefix("assets/")
                        if member not in expected or member in observed_assets:
                            raise Refuse("EXTRA_OR_DUPLICATE_CAPSULE_DATA")
                        want_digest, want_size, _ = expected[member]
                        h = hashlib.sha256()
                        size = 0
                        while block := source.read(8 * 1024 * 1024):
                            h.update(block)
                            size += len(block)
                            if size > want_size:
                                raise Refuse("CAPSULE_MEMBER_OVERSIZED")
                        if size != want_size or h.hexdigest() != want_digest:
                            raise Refuse("CAPSULE_MEMBER_NOT_EQUAL_TO_CANONICAL")
                        observed_assets.add(member)
                    elif entry.name.startswith("manifests/"):
                        body = source.read(1024 * 1024 + 1)
                        if len(body) > 1024 * 1024 or entry.name in observed_manifests:
                            raise Refuse("BAD_CAPSULE_SHARD_MANIFEST")
                        row = json.loads(body)
                        member = row.get("release_asset")
                        if (member not in expected
                                or (row.get("sha256"), row.get("bytes"), row.get("dataset_id"))
                                != expected[member]):
                            raise Refuse("CAPSULE_SHARD_NOT_EQUAL_TO_CANONICAL")
                        observed_manifests.add(entry.name)
                    else:
                        raise Refuse("UNEXPECTED_CAPSULE_TAR_ENTRY")
            archive_path.unlink()
        if (original_index is None
                or set(observed_assets) != set(expected)
                or set(original_index.get("assets") or []) != {
                    "assets/" + name for name in expected
                }
                or set(original_index.get("manifests") or []) != observed_manifests
                or len(observed_manifests) != len(expected)):
            raise Refuse("CAPSULE_FULL_PARITY_NOT_PROVEN")
        return {
            "status": "REDUNDANT_CAPSULE_BYTES_VERIFIED",
            "recovery_tag": tag,
            "recovery_release_id": rec["id"],
            "canonical_tag": canonical_tag,
            "canonical_sha256": main_asset["digest"].removeprefix("sha256:"),
            "safe_shards_verified": len(expected),
            "safe_catalog_bindings": catalog_bindings,
            "recovery_bytes_verified": sum(a["size"] for a in rec_assets.values()),
            "recovery_asset_identities": sorted(
                (a["name"], a["size"], a["digest"]) for a in rec_assets.values()
            ),
        }



def verify_current_safe_catalog(
    report: Mapping[str, Any],
    *,
    index_path: Path = Path("catalog/DATA_INDEX.json"),
    metrics_path: Path = Path("catalog/DATA_METRICS.json"),
) -> str:
    """Refuse deletion if ANY capsule shard was downgraded or lost from main.

    A historical RUN_MANIFEST is immutable, but the latest canonical catalog
    can revoke SAFE after later reconciliation. The capsule then remains
    recoverable evidence and must NOT be deleted.
    """
    try:
        raw = index_path.read_bytes()
        index = read_index(index_path)
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise Refuse("CURRENT_CATALOG_NOT_VERIFIABLE") from exc
    digest = sha(raw)
    rows = index.get("shards") if isinstance(index, Mapping) else None
    totals = metrics.get("totals") if isinstance(metrics, Mapping) else None
    if (
        not isinstance(rows, list) or not isinstance(totals, Mapping)
        or metrics.get("schema_version") != "alina.data_metrics.v4"
        or metrics.get("source_index_sha256") != digest
        or type(totals.get("TOTAL_SHARDS")) is not int
        or totals["TOTAL_SHARDS"] != len(rows)
    ):
        raise Refuse("CURRENT_CATALOG_METRICS_NOT_SHA_BOUND")
    bindings = report.get("safe_catalog_bindings")
    if not isinstance(bindings, list) or len(bindings) != report.get("safe_shards_verified"):
        raise Refuse("MISSING_CAPSULE_CATALOG_BINDINGS")
    wanted = {r.get("dataset_id") for r in bindings if isinstance(r, Mapping)}
    if len(wanted) != len(bindings) or None in wanted:
        raise Refuse("DUPLICATE_CAPSULE_DATASET_IDENTITIES")
    observed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise Refuse("CURRENT_CATALOG_MALFORMED_ROW")
        identity = row.get("dataset_id")
        if identity in wanted:
            if identity in observed:
                raise Refuse("CURRENT_CATALOG_DUPLICATE_IDENTITY")
            observed[identity] = row
    if len(observed) != len(bindings):
        raise Refuse("CURRENT_CATALOG_MISSING_CAPSULE_SHARD")
    canonical_repo = "Rapt0r06300/hyperliquid-smart-wallet-observer"
    for binding in bindings:
        row = observed[binding["dataset_id"]]
        if (
            row.get("quality_status") != "SAFE"
            or row.get("replay_compatible") is not True
            or row.get("sha256") != binding["sha256"]
            or row.get("bytes") != binding["bytes"]
            or row.get("release_tag") != binding["release_tag"]
            or row.get("release_asset") != binding["release_asset"]
            or (row.get("release_container_asset") or row.get("release_asset"))
                != binding["outer_asset"]
            or (row.get("release_repository")
                or index.get("release_repository_default")) != canonical_repo
        ):
            raise Refuse("CAPSULE_SHARD_NOT_CURRENTLY_SAFE_KEEP_RECOVERY")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovery-tag", required=True)
    parser.add_argument("--max-cloud-verify-gib", type=int, default=2)
    parser.add_argument("--execute", action="store_true",
                        help="delete the verified redundant Release, never used automatically")
    parser.add_argument("--expected-release-id", type=int,
                        help="required if --execute; prevents deleting a changed Release")
    parser.add_argument("--expected-canonical-sha256",
                        help="required if --execute; bind deletion to inspected SAFE source")
    args = parser.parse_args()
    try:
        if args.max_cloud_verify_gib < 1 or args.max_cloud_verify_gib > 2:
            raise Refuse("INVALID_CLOUD_VERIFY_BUDGET")
        report = verify_capsule(
            args.recovery_tag, max_bytes=args.max_cloud_verify_gib * 1024**3
        )
        if args.execute:
            if (report["recovery_release_id"] != args.expected_release_id
                    or report["canonical_sha256"] != args.expected_canonical_sha256):
                raise Refuse("DELETE_EXPECTED_ID_AND_SHA_MUST_MATCH")
            report["current_catalog_sha256"] = verify_current_safe_catalog(report)
            current = release(args.recovery_tag)
            current_assets = sorted(
                (a["name"], a["size"], a["digest"]) for a in assets(current).values()
            )
            if (current["id"] != report["recovery_release_id"]
                    or current_assets != report["recovery_asset_identities"]):
                raise Refuse("DELETE_ABORT_RELEASE_CHANGED")
            url = f"https://api.github.com/repos/{REPOSITORY}/releases/{current['id']}"
            with request(url, method="DELETE") as response:
                if response.status != 204:
                    raise Refuse("DELETE_GITHUB_NOT_CONFIRMED")
            report["status"] = "VERIFIED_REDUNDANT_RELEASE_DELETED"
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, Refuse) as exc:
        print(json.dumps({"status": "KEEP_RECOVERY_FAIL_CLOSED", "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
