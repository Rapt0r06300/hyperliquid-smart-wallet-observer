#!/usr/bin/env python3
"""Download GitHub release manifests after bounded eventual-consistency polling."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


MANIFEST_NAME = "RUN_MANIFEST.json"
TAG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class DownloadSummary:
    downloaded: tuple[str, ...]
    missing: tuple[str, ...]
    attempts: int


def _unique_tags(tags: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw_tag in tags:
        tag = raw_tag.strip()
        if not tag:
            continue
        if not TAG_PATTERN.fullmatch(tag):
            raise ValueError(f"invalid release tag: {tag!r}")
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def _run_gh(
    command: list[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str]:
    return runner(command, check=False, capture_output=True, text=True)


def _asset_is_visible(
    repository: str,
    tag: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> bool:
    result = _run_gh(
        [
            "gh",
            "release",
            "view",
            tag,
            "--repo",
            repository,
            "--json",
            "assets",
            "--jq",
            ".assets[].name",
        ],
        runner=runner,
    )
    return result.returncode == 0 and MANIFEST_NAME in result.stdout.splitlines()


def _download_one(
    repository: str,
    tag: str,
    destination: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> bool:
    final_directory = destination / tag
    final_manifest = final_directory / MANIFEST_NAME
    if final_manifest.is_file() and final_manifest.stat().st_size > 0:
        return True
    final_manifest.unlink(missing_ok=True)

    with tempfile.TemporaryDirectory(prefix=f".{tag}-", dir=destination) as raw_temp:
        temp_directory = Path(raw_temp)
        result = _run_gh(
            [
                "gh",
                "release",
                "download",
                tag,
                "--repo",
                repository,
                "--pattern",
                MANIFEST_NAME,
                "--dir",
                os.fspath(temp_directory),
            ],
            runner=runner,
        )
        candidate = temp_directory / MANIFEST_NAME
        if result.returncode != 0 or not candidate.is_file() or candidate.stat().st_size <= 0:
            return False
        final_directory.mkdir(parents=True, exist_ok=True)
        os.replace(candidate, final_manifest)
        return True


def download_release_manifests(
    *,
    repository: str,
    tags: Iterable[str],
    destination: Path,
    attempts: int = 12,
    poll_seconds: float = 10.0,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    sleeper: Callable[[float], object] = time.sleep,
) -> DownloadSummary:
    """Poll all pending tags in rounds and download only real, non-empty manifests."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    if poll_seconds < 0:
        raise ValueError("poll_seconds must be non-negative")

    ordered_tags = _unique_tags(tags)
    destination.mkdir(parents=True, exist_ok=True)
    pending = list(ordered_tags)
    downloaded: set[str] = set()
    attempts_used = 0

    for attempt in range(1, attempts + 1):
        if not pending:
            break
        attempts_used = attempt
        next_pending: list[str] = []
        for tag in pending:
            if not _asset_is_visible(repository, tag, runner=runner):
                next_pending.append(tag)
                continue
            if _download_one(repository, tag, destination, runner=runner):
                downloaded.add(tag)
                print(f"release manifest ready: {tag}")
            else:
                next_pending.append(tag)
                print(f"release manifest listed but not downloadable yet: {tag}")
        pending = next_pending
        if pending and attempt < attempts:
            print(
                f"waiting for {len(pending)} release manifest(s); "
                f"attempt {attempt}/{attempts}"
            )
            if poll_seconds:
                sleeper(poll_seconds)

    for tag in pending:
        print(f"release manifest unavailable after {attempts_used} attempt(s): {tag}")

    return DownloadSummary(
        downloaded=tuple(tag for tag in ordered_tags if tag in downloaded),
        missing=tuple(sorted(pending)),
        attempts=attempts_used,
    )


def _read_tags(paths: Sequence[Path], positional: Sequence[str]) -> list[str]:
    tags = list(positional)
    for path in paths:
        tags.extend(path.read_text(encoding="utf-8").splitlines())
    return tags


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Poll GitHub Releases until RUN_MANIFEST.json is both visible and "
            "downloadable, within a fixed global retry budget."
        )
    )
    parser.add_argument("tags", nargs="*")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--tags-file", action="append", type=Path, default=[])
    parser.add_argument("--attempts", type=int, default=12)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    args = parser.parse_args()

    try:
        summary = download_release_manifests(
            repository=args.repository,
            tags=_read_tags(args.tags_file, args.tags),
            destination=args.destination,
            attempts=args.attempts,
            poll_seconds=args.poll_seconds,
        )
    except ValueError as exc:
        parser.error(str(exc))

    print(
        json.dumps(
            {
                "downloaded": len(summary.downloaded),
                "missing": list(summary.missing),
                "attempts": summary.attempts,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
