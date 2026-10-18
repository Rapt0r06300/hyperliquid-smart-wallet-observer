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
INITIAL_RELEASE_WINDOW = 24
MAX_RELEASE_WINDOW = 96
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
    run("git", "clean", "-fd", "--", "datasets/sharded", "catalog/data-index-parts",
        "catalog/quarantine-audit-parts")


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
        enforce_quarantine_before_import(candidates)
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


def select_with_bounded_oversized_retry(
    tags: list[str], root: Path, *, shard_budget: int,
    manifest_budget_bytes: int = 64 * 1024 * 1024,
) -> tuple[list[str], int, int]:
    """Boundedly retry a large first Release; never skip it."""
    budget = shard_budget
    if not 5000 <= budget <= 100000:
        raise ValueError("invalid bounded reconciliation budget")
    if not 64 * 1024 * 1024 <= manifest_budget_bytes <= 128 * 1024 * 1024:
        raise ValueError("invalid bounded historical manifest byte budget")
    while True:
        try:
            selected, count = select_prefix(
                tags, root, max_shards=budget,
                max_manifest_bytes=manifest_budget_bytes,
            )
            return selected, count, budget
        except ValueError as exc:
            if "single Release exceeds safe publication budget" not in str(exc):
                raise
            if budget >= 100000:
                raise
            increased = min(100000, max(budget + 5000, budget * 2))
            print(
                f"HISTORICAL_SINGLE_RELEASE_BUDGET_RAISED "
                f"from={budget} to={increased}", flush=True,
            )
            budget = increased


def next_shard_budget(current: int, requested: int, published: int) -> int:
    """Retire temporary oversized staging allowance after proven publication.

    An individually oversized Release may temporarily require 80k or 100k
    shards. Such a one-off must not crash the next adaptive wave, nor let the
    normal steady-state budget exceed 60k.
    """
    if not 5000 <= current <= 100000 or requested < 1 or not 1 <= published <= requested:
        raise ValueError("invalid adaptive wave progress")
    steady = min(current, 60000)
    if published < requested:
        return max(5000, steady // 2)
    if published >= 2:
        return min(60000, steady + max(5000, steady // 3))
    return steady


def next_manifest_budget(current: int, requested: int, published: int) -> int:
    """Grow staged immutable manifest bytes only after durable publication.

    This is not the Git blob size limit: SHA-bound per-shard receipts and the
    60k normal shard cap remain unchanged. Shrink promptly if the remote
    rejects a candidate pack. Never skip the rejected Release.
    """
    floor = 64 * 1024 * 1024
    ceiling = 128 * 1024 * 1024
    if not floor <= current <= ceiling or requested < 1 or not 1 <= published <= requested:
        raise ValueError("invalid adaptive manifest byte budget progress")
    if published < requested:
        return max(floor, current // 2)
    if published >= 2:
        return min(ceiling, current + 32 * 1024 * 1024)
    return current


def next_release_window(current: int, requested: int, published: int) -> int:
    """Increase tag prefetch only after durable multi-Release batches.

    Immutable manifest and shard budgets still decide the admitted prefix.
    A GitHub pack rejection reduces future prefetch; no tag is skipped.
    """
    if (not INITIAL_RELEASE_WINDOW <= current <= MAX_RELEASE_WINDOW
            or requested < 1 or not 1 <= published <= requested):
        raise ValueError("invalid adaptive Release window progress")
    if published < requested:
        return max(INITIAL_RELEASE_WINDOW, current // 2)
    if published >= 2:
        return min(MAX_RELEASE_WINDOW, current * 2)
    return current


def load_current_quarantine() -> set[str]:
    """Reload the live, typed quarantine policy from the synced checkout."""
    path = Path("control/legacy-release-migration.json")
    if not path.is_file():
        return set()
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("invalid legacy Release migration policy")
    raw = doc.get("quarantined_tags") or []
    if not isinstance(raw, list) or any(
        not isinstance(tag, str) or not TAG.fullmatch(tag) for tag in raw
    ):
        raise ValueError("invalid quarantined Release tag list")
    return set(raw)


def enforce_quarantine_before_import(paths: list[Path]) -> None:
    """Keep newly quarantined immutable Releases out of staged publications."""
    quarantined = load_current_quarantine()
    blocked = sorted({path.parent.name for path in paths}.intersection(quarantined))
    if blocked:
        raise ValueError(f"quarantined Releases cannot be imported: {blocked[:5]}")


def index_blob_sha() -> str:
    """Git-address the exact tracked index; never rely on an mtime."""
    sha = run("git", "rev-parse", "HEAD:catalog/DATA_INDEX.json").stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError("invalid canonical index Git blob identity")
    return sha


def current_pending(
    inventory: str, quarantine: set[str], blob_sha: str,
    cache_blob_sha: str | None, cache_tags: list[str] | None,
) -> list[str]:
    """Cache only when immutable Git index bytes have not changed."""
    if blob_sha == cache_blob_sha and cache_tags is not None:
        return list(cache_tags)
    return pending(
        inventory, read_index(Path("catalog/DATA_INDEX.json")), quarantine,
    )


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
    snapshot = a.inventory.read_text(encoding="utf-8")
    a.work_root.mkdir(parents=True, exist_ok=True)
    waves = 0
    shard_budget = 20000
    manifest_budget_bytes = 64 * 1024 * 1024
    release_window = INITIAL_RELEASE_WINDOW
    cache_blob_sha: str | None = None
    cache_tags: list[str] | None = None
    cache_quarantine: frozenset[str] | None = None
    completed_releases = 0
    try:
        while waves < a.max_waves and time.monotonic() - start < a.max_minutes * 60:
            synced()
            quarantine = load_current_quarantine()
            if cache_quarantine != frozenset(quarantine):
                cache_blob_sha = None
                cache_tags = None
            blob_sha = index_blob_sha()
            tags = current_pending(
                snapshot, quarantine, blob_sha, cache_blob_sha, cache_tags,
            )
            if not tags:
                break
            next_tags = tags[:release_window]
            missing = [tag for tag in next_tags if not (a.work_root / tag / "RUN_MANIFEST.json").is_file()]
            if missing:
                tags_file = a.work_root / "pending-tags.txt"
                tags_file.write_text("\n".join(missing) + "\n", encoding="utf-8")
                run("python", "tools/download_release_manifests.py",
                    "--repository", REPO, "--destination", str(a.work_root),
                    "--tags-file", str(tags_file), "--attempts", "3",
                    "--poll-seconds", "2", "--workers", "8")
            selected, shard_count, used_budget = select_with_bounded_oversized_retry(
                next_tags, a.work_root, shard_budget=shard_budget,
                manifest_budget_bytes=manifest_budget_bytes,
            )
            shard_budget = used_budget
            print(
                f"HISTORICAL_BATCH_READY wave={waves+1} releases={len(selected)} "
                f"shards={shard_count} shard_budget={shard_budget}", flush=True,
            )
            published = publish([
                a.work_root / tag / "RUN_MANIFEST.json" for tag in selected
            ])
            shard_budget = next_shard_budget(
                shard_budget, requested=len(selected), published=published,
            )
            manifest_budget_bytes = next_manifest_budget(
                manifest_budget_bytes, requested=len(selected), published=published,
            )
            release_window = next_release_window(
                release_window, requested=len(selected), published=published,
            )
            # Publication is already SHA-verified by publish(). Drop only its
            # proven prefix, then pin this cache to the local published index
            # blob. Any concurrent index update invalidates it next iteration.
            imported_tags = set(selected[:published])
            cache_tags = [tag for tag in tags if tag not in imported_tags]
            cache_blob_sha = index_blob_sha()
            cache_quarantine = frozenset(quarantine)
            completed_releases += published
            elapsed_minutes = max((time.monotonic() - start) / 60, 1e-6)
            print(
                f"HISTORICAL_ADAPTIVE_PROOF published_releases={published} "
                f"next_shard_budget={shard_budget} "
                f"next_manifest_budget_mib={manifest_budget_bytes // (1024 * 1024)} "
                f"release_window={release_window} "
                f"total_published_this_runner={completed_releases} "
                f"snapshot_remaining={len(cache_tags)} "
                f"throughput_releases_per_hour={completed_releases * 60 / elapsed_minutes:.2f}",
                flush=True,
            )
            waves += 1
        synced()
        quarantine = load_current_quarantine()
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
