#!/usr/bin/env python3
"""Checkpoint more than one complete historical batch per hosted runner."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

try:
    from tools.partitioned_data_index import read_index
    from tools.select_reconciliation_batch import select_prefix
except ModuleNotFoundError:
    from partitioned_data_index import read_index
    from select_reconciliation_batch import select_prefix

REPO = "Rapt0r06300/hyperliquid-smart-wallet-observer"
PREFIX = ("data-v2-", "copy-vault-v2-", "archive-v2-", "event-intelligence-v2-")
TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PACK = re.compile(r"remote unpack failed|index-pack failed|tree.{0,80}too large|pack exceeds|pack.{0,80}too large|unpacker error", re.I)


def pending(inventory: str, index: dict, quarantine: set[str]) -> list[str]:
    aliases = index.get("run_manifest_release_tags_by_release") or {}
    if not isinstance(aliases, dict):
        raise ValueError("invalid release aliases")
    known = set()
    for row in index.get("shards", []):
        if not isinstance(row, dict):
            raise ValueError("invalid index row")
        tag = row.get("release_tag")
        if tag and (row.get("release_repository") or index.get("release_repository_default")) == REPO:
            known.add(str(row.get("run_manifest_release_tag") or aliases.get(tag) or tag))
    found, result = set(), []
    for line in inventory.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            raise ValueError("invalid release inventory")
        tag, has_manifest = parts
        if not TAG.fullmatch(tag) or has_manifest not in ("true", "false"):
            raise ValueError("invalid release identity")
        if tag not in found and has_manifest == "true" and tag.startswith(PREFIX) and tag not in known and tag not in quarantine:
            result.append(tag)
        found.add(tag)
    return result


def run(*argv: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    out = subprocess.run(argv, capture_output=True, text=True, check=False)
    if check and out.returncode:
        raise RuntimeError(f"{argv[:3]} failed: {(out.stderr or out.stdout)[-900:]}")
    return out


def synced() -> None:
    run("git", "fetch", "origin", "main")
    run("git", "reset", "--hard", "origin/main")
    # Only untracked generated receipts in this ephemeral GitHub-hosted checkout.
    run("git", "clean", "-fd", "--", "datasets/sharded", "catalog/data-index-parts")


def remote_contains_head() -> bool:
    """Verify publication with Git object ancestry, even after a lost response."""
    run("git", "fetch", "origin", "main")
    sha = run("git", "rev-parse", "HEAD").stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("invalid local publication SHA")
    return run(
        "git", "merge-base", "--is-ancestor", sha, "origin/main", check=False
    ).returncode == 0


def try_disjoint_campaign_rebase() -> tuple[bool, bool]:
    """Retry only across previously proven, non-overlapping campaign paths.

    Returns (published, pack_failure). Never force-push and never accept
    rebase across catalog/data, metadata, or code changes.
    """
    for _ in range(5):
        safe = run(
            "python", "tools/rebase_disjoint_catalog_publication.py",
            "--remote", "origin/main", check=False,
        )
        if safe.returncode:
            return False, False
        pushed = run("git", "push", "--no-thin", "origin", "HEAD:main", check=False)
        if remote_contains_head():
            return True, False
        if PACK.search(pushed.stdout + pushed.stderr):
            return False, True
    return False, False


def publish(paths: list[Path]) -> int:
    candidates = list(paths)
    for attempt in range(1, 9):
        synced()
        run("python", "tools/index_run_manifest.py", *map(str, candidates))
        for tool in ("build_catalog_metrics.py", "build_quarantine_audit.py", "check_dataset_quality.py"):
            run("python", f"tools/{tool}")
        run("python", "-c", "from tools.build_catalog_metrics import verify_metrics_source; verify_metrics_source()")
        run("git", "add", "catalog", "datasets")
        if run("git", "diff", "--cached", "--quiet", check=False).returncode == 0:
            raise RuntimeError("empty catalog publication, no checkpoint possible")
        run("git", "commit", "-q", "-m", "data: historical V2 checkpoint")
        sha = run("git", "rev-parse", "HEAD").stdout.strip()
        result = run("git", "push", "--no-thin", "origin", "HEAD:main", check=False)
        if remote_contains_head():
            sha = run("git", "rev-parse", "HEAD").stdout.strip()
            print(f"HISTORICAL_BATCH_PUBLISHED sha={sha} releases={len(candidates)}", flush=True)
            return len(candidates)
        output = result.stderr + result.stdout
        pack_failure = bool(PACK.search(output))
        if not pack_failure:
            rebased, pack_failure = try_disjoint_campaign_rebase()
            if rebased:
                sha = run("git", "rev-parse", "HEAD").stdout.strip()
                print(
                    f"HISTORICAL_BATCH_PUBLISHED sha={sha} "
                    f"releases={len(candidates)} disjoint_rebase=verified", flush=True,
                )
                return len(candidates)
        if pack_failure:
            if len(candidates) == 1:
                raise RuntimeError("single Release pack rejected; do not skip")
            candidates = candidates[:(len(candidates) + 1) // 2]
            print(f"HISTORICAL_BATCH_SHRUNK to={len(candidates)}", flush=True)
        elif attempt == 8:
            raise RuntimeError("GitHub publish failed: " + output[-900:])
        time.sleep(min(attempt, 6))
    raise RuntimeError("publication retries exhausted")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--work-root", type=Path, required=True)
    p.add_argument("--max-minutes", type=int, default=265)
    p.add_argument("--max-waves", type=int, default=60)
    a = p.parse_args()
    if not 1 <= a.max_minutes <= 280 or not 1 <= a.max_waves <= 100:
        raise SystemExit("invalid runner budget")
    start = time.monotonic()
    document = json.loads(Path("control/legacy-release-migration.json").read_text()) if Path("control/legacy-release-migration.json").is_file() else {}
    quarantine = set(document.get("quarantined_tags") or [])
    snapshot = a.inventory.read_text(encoding="utf-8")
    a.work_root.mkdir(parents=True, exist_ok=True)
    waves = 0
    try:
        while waves < a.max_waves and time.monotonic() - start < a.max_minutes * 60:
            synced()
            tags = pending(snapshot, read_index(Path("catalog/DATA_INDEX.json")), quarantine)
            if not tags:
                break
            next_tags = tags[:96]
            missing = [tag for tag in next_tags if not (a.work_root / tag / "RUN_MANIFEST.json").is_file()]
            if missing:
                tags_file = a.work_root / "pending-tags.txt"
                tags_file.write_text("\n".join(missing) + "\n", encoding="utf-8")
                run("python", "tools/download_release_manifests.py",
                    "--repository", REPO, "--destination", str(a.work_root),
                    "--tags-file", str(tags_file), "--attempts", "3",
                    "--poll-seconds", "2", "--workers", "4")
            selected, shard_count = select_prefix(next_tags, a.work_root,
                    max_shards=100000, max_manifest_bytes=80 * 1024 * 1024)
            print(f"HISTORICAL_BATCH_READY wave={waves+1} releases={len(selected)} shards={shard_count}", flush=True)
            publish([a.work_root / tag / "RUN_MANIFEST.json" for tag in selected])
            waves += 1
        synced()
        remaining = len(pending(snapshot, read_index(Path("catalog/DATA_INDEX.json")), quarantine))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"HISTORICAL_RECONCILE_FAIL_CLOSED {exc}", file=sys.stderr)
        return 2
    print(f"HISTORICAL_RUNNER_CHECKPOINT waves={waves} snapshot_remaining={remaining}", flush=True)
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as env:
        env.write(f"REMAINING_NEW_TAGS={remaining}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
