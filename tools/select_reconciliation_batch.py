#!/usr/bin/env python3
"""Select a deterministic, bounded prefix of downloaded immutable Releases.

Only a validated prefix may enter the canonical index. Deferred manifests are
removed from this disposable checkout before the existing SHA-bound pipeline.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil

TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REPOSITORY = "Rapt0r06300/hyperliquid-smart-wallet-observer"


def select_prefix(tags: list[str], root: Path, *, max_shards: int,
                  max_manifest_bytes: int) -> tuple[list[str], int]:
    if max_shards < 1 or max_manifest_bytes < 1:
        raise ValueError("positive shard/byte limits are required")
    chosen: list[str] = []
    count = 0
    manifest_bytes = 0
    seen: set[str] = set()
    for tag in tags:
        if not TAG.fullmatch(tag) or tag in seen:
            raise ValueError("invalid or repeated Release tag")
        seen.add(tag)
        manifest = root / tag / "RUN_MANIFEST.json"
        if manifest.is_symlink() or not manifest.is_file():
            raise ValueError(f"Release manifest missing or linked: {tag}")
        raw = manifest.read_bytes()
        doc = json.loads(raw)
        if (not isinstance(doc, dict)
                or doc.get("schema") != "alina.dataset_run_manifest.v2"
                or doc.get("repository") != REPOSITORY
                or not isinstance(doc.get("manifests"), list)
                or not doc["manifests"]
                or not all(isinstance(item, dict) for item in doc["manifests"])):
            raise ValueError(f"invalid immutable Release manifest: {tag}")
        incoming = len(doc["manifests"])
        if incoming > max_shards or len(raw) > max_manifest_bytes:
            if not chosen:
                raise ValueError(
                    f"single Release exceeds safe publication budget: {tag}"
                )
            break
        if chosen and (count + incoming > max_shards
                       or manifest_bytes + len(raw) > max_manifest_bytes):
            break
        chosen.append(tag)
        count += incoming
        manifest_bytes += len(raw)
    return chosen, count


def apply_plan(root: Path, tags_file: Path, total_file: Path, env_file: Path,
               *, max_shards: int, max_manifest_bytes: int,
               max_first_shards: int | None = None) -> tuple[int, int]:
    tags = tags_file.read_text(encoding="utf-8").splitlines()
    total = int(total_file.read_text(encoding="utf-8"))
    if not tags or total < len(tags) or total < 0:
        raise ValueError("invalid candidate/total Release counts")
    # Validate *all* names before pruning downloaded, disposable manifests.
    # select_prefix() may stop early at the byte/shard budget.
    if any(not TAG.fullmatch(tag) for tag in tags) or len(set(tags)) != len(tags):
        raise ValueError("invalid or repeated deferred Release tag")
    if max_first_shards is not None and not (
        max_shards <= max_first_shards <= 100000
    ):
        raise ValueError("invalid bounded first-Release shard cap")
    try:
        selected, shard_count = select_prefix(
            tags, root, max_shards=max_shards,
            max_manifest_bytes=max_manifest_bytes,
        )
    except ValueError as exc:
        # Exceptional first Release: retry ONLY its exact immutable manifest.
        # Never skip a candidate or apply the elevated cap to an entire batch.
        if (max_first_shards is None
                or "single Release exceeds safe publication budget:" not in str(exc)
                or max_first_shards == max_shards):
            raise
        selected, shard_count = select_prefix(
            tags[:1], root, max_shards=max_first_shards,
            max_manifest_bytes=max_manifest_bytes,
        )
        print(
            f"RECONCILE_OVERSIZED_FIRST_RELEASE accepted={selected[0]} "
            f"shards={shard_count} cap={max_first_shards}",
            flush=True,
        )
    if not selected:
        raise ValueError("no durable Release selected")
    # No mutation until the full prefix is validated and within both limits.
    for tag in tags[len(selected):]:
        directory = root / tag
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(f"deferred Release directory missing or linked: {tag}")
    for tag in tags[len(selected):]:
        shutil.rmtree(root / tag)
    tags_file.write_text("\n".join(selected) + "\n", encoding="utf-8")
    remaining = total - len(selected)
    with env_file.open("a", encoding="utf-8") as env:
        env.write(f"RUN_MANIFEST_COUNT={len(selected)}\n")
        env.write(f"REMAINING_NEW_TAGS={remaining}\n")
    print(
        f"RECONCILE_FAST_BATCH selected_releases={len(selected)} "
        f"selected_shards={shard_count} remaining_releases={remaining}"
    )
    return len(selected), remaining


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--tags-file", type=Path, required=True)
    parser.add_argument("--total-file", type=Path, required=True)
    parser.add_argument("--github-env", type=Path, required=True)
    parser.add_argument("--max-shards", type=int, default=50000)
    parser.add_argument("--max-first-shards", type=int, default=None)
    parser.add_argument("--max-manifest-bytes", type=int, default=80 * 1024 * 1024)
    args = parser.parse_args()
    apply_plan(
        args.root, args.tags_file, args.total_file, args.github_env,
        max_shards=args.max_shards,
        max_manifest_bytes=args.max_manifest_bytes,
        max_first_shards=args.max_first_shards,
    )


if __name__ == "__main__":
    main()
