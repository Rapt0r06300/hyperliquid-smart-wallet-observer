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
import sys
import tempfile
import time


MANIFEST_NAME = "RUN_MANIFEST.json"
PRODUCTION_RELEASE_PREFIXES = ("data-v2-", "copy-vault-v2-", "archive-v2-", "event-intelligence-v2-")
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


def _api_page(
    endpoint: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    sleeper: Callable[[float], object],
    attempts: int = 5,
) -> list[dict[str, object]]:
    """One bounded REST page at a time; restart only a failing page on HTTP 504."""
    if attempts < 1:
        raise ValueError("attempts must be positive")
    for attempt in range(1, attempts + 1):
        command = ["gh", "api", "--method", "GET", endpoint]
        try:
            proc = runner(
                command, check=False, capture_output=True, text=True, timeout=50
            )
        except subprocess.TimeoutExpired:
            proc = subprocess.CompletedProcess(command, 124, "", "request timeout")
        if proc.returncode == 0:
            try:
                body = json.loads(proc.stdout)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid GitHub JSON for {endpoint}") from exc
            if not isinstance(body, list) or not all(
                isinstance(row, dict) for row in body
            ):
                raise RuntimeError(f"malformed GitHub page {endpoint}")
            return body
        error = (proc.stderr or proc.stdout or "unknown API failure")[:350]
        # A depleted installation allowance will not recover via short retries.
        if "rate limit exceeded for installation" in error.lower() or "api rate limit exceeded" in error.lower():
            raise RuntimeError(f"Primary GitHub API allowance exhausted at {endpoint}; defer to scheduled retry")
        transient = bool(re.search(
            r"(?:HTTP\s*(?:403|429|5\d\d)|rate.limit|stream error|"
            r"timeout|timed out|connection reset|temporar)",
            error, re.IGNORECASE
        ))
        if not transient or attempt == attempts:
            raise RuntimeError(
                f"GitHub page {endpoint} failed after {attempt} attempt(s): {error}"
            )
        delay = min(45.0, float(2 ** min(attempt, 5)))
        print(f"GitHub transient API failure page retry {attempt}/{attempts}: {endpoint}")
        sleeper(delay)
    raise RuntimeError("unreachable GitHub page retry state")


def list_release_manifest_tags(
    repository: str,
    *,
    skip_tags: set[str] | None = None,
    only_production: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    sleeper: Callable[[float], object] = time.sleep,
    page_size: int = 50,
    attempts: int = 5,
    max_pages: int = 2000,
) -> list[tuple[str, bool]]:
    """Enumerate all Release identities, but inspect only new production assets.

    Reconciliation-only filters omit known/unrelated tags from results without
    skipping any Release page or weakening strict pagination for candidates.
    """
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be in 1..100")
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    pages = 0
    stagnant_pages = 0
    seen_ids: dict[int, str] = {}
    seen_tags: dict[str, int] = {}
    shifted_page_duplicates = 0
    rows: list[tuple[str, bool]] = []
    while True:
        pages += 1
        if pages > max_pages:
            raise RuntimeError("Release listing page budget exhausted; partial inventory refused")
        prior_unique = len(seen_ids)
        endpoint = f"repos/{repository}/releases?per_page={page_size}&page={pages}"
        page = _api_page(
            endpoint, runner=runner, sleeper=sleeper, attempts=attempts
        )
        current_page_ids: set[int] = set()
        current_page_tags: set[str] = set()
        for release in page:
            ident = release.get("id")
            tag = release.get("tag_name")
            if type(ident) is not int or ident <= 0:
                raise RuntimeError(f"invalid Release id on page {pages}")
            if not isinstance(tag, str) or not TAG_PATTERN.fullmatch(tag):
                raise RuntimeError(f"invalid Release tag on page {pages}")
            if ident in current_page_ids or tag in current_page_tags:
                raise RuntimeError(f"duplicated Release id or tag within page {pages}")
            current_page_ids.add(ident)
            current_page_tags.add(tag)
            # The list is ordered newest-first, while collectors keep adding
            # Releases. An insertion before the current offset makes a
            # previously seen release reappear on a later page. Such benign
            # page overlaps are not evidence loss; silently accepting a
            # conflicting identity, however, is forbidden.
            if ident in seen_ids or tag in seen_tags:
                if seen_ids.get(ident) != tag or seen_tags.get(tag) != ident:
                    raise RuntimeError(f"conflicting Release id/tag on page {pages}")
                shifted_page_duplicates += 1
                continue
            seen_ids[ident] = tag
            seen_tags[tag] = ident
            assets = release.get("assets")
            if not isinstance(assets, list):
                raise RuntimeError(f"missing assets for Release {tag}")
            # Keep checking every Release identity, but never burn rate-limit
            # budget on deep assets for cataloged or unrelated Releases.
            if (skip_tags is not None and tag in skip_tags) or (
                only_production and not tag.startswith(PRODUCTION_RELEASE_PREFIXES)
            ):
                continue
            # The list embeds at most 30 assets; inspect extra pages only
            # when the manifest is NOT already visible in that first batch.
            visible = any(
                isinstance(asset, dict) and asset.get("name") == MANIFEST_NAME
                for asset in assets
            )
            if len(assets) >= 30 and not visible:
                all_assets: list[dict[str, object]] = []
                asset_page = 1
                while True:
                    batch = _api_page(
                        f"repos/{repository}/releases/{ident}/assets"
                        f"?per_page=100&page={asset_page}",
                        runner=runner, sleeper=sleeper, attempts=attempts,
                    )
                    all_assets.extend(batch)
                    if len(batch) < 100:
                        break
                    asset_page += 1
                assets = all_assets
            if not all(isinstance(a, dict) and isinstance(a.get("name"), str) for a in assets):
                raise RuntimeError(f"malformed asset listing for Release {tag}")
            has_manifest = any(a["name"] == MANIFEST_NAME for a in assets)
            rows.append((tag, has_manifest))
        if len(page) == page_size:
            # Concurrent Releases can shift offsets. Two complete pages with
            # zero new IDs indicate a stuck service; fail closed, never spin.
            stagnant_pages = stagnant_pages + 1 if len(seen_ids) == prior_unique else 0
            if stagnant_pages >= 2:
                raise RuntimeError(
                    "Release listing pagination made no progress; "
                    "partial inventory refused"
                )
        if len(page) < page_size:
            print(
                f"GitHub Release inventory enumerated: {len(seen_ids)} unique tags, "
                f"{len(rows)} candidate tags across {pages} pages, "
                f"{shifted_page_duplicates} stable page overlaps"
            )
            return rows


def _known_tags_from_index(path: Path) -> set[str]:
    """Use canonical Release identities, including reversible run-tag aliases."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("shards"), list):
        raise RuntimeError("invalid canonical DATA_INDEX for Release enumeration")
    aliases = doc.get("run_manifest_release_tags_by_release") or {}
    if not isinstance(aliases, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in aliases.items()
    ):
        raise RuntimeError("invalid canonical run manifest tag aliases")
    known: set[str] = set()
    for row in doc["shards"]:
        if not isinstance(row, dict):
            raise RuntimeError("invalid canonical DATA_INDEX row")
        tag = row.get("release_tag")
        if not isinstance(tag, str) or not tag:
            continue
        canonical = row.get("run_manifest_release_tag") or aliases.get(tag) or tag
        if not isinstance(canonical, str) or not TAG_PATTERN.fullmatch(canonical):
            raise RuntimeError("invalid canonical run tag in DATA_INDEX")
        known.add(canonical)
    return known


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
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--list-tags-output", type=Path)
    parser.add_argument("--list-page-size", type=int, default=50)
    parser.add_argument("--reconcile-index", type=Path,
                        help="inspect deep assets only for unindexed production releases")
    parser.add_argument("--tags-file", action="append", type=Path, default=[])
    parser.add_argument("--attempts", type=int, default=12)
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    args = parser.parse_args()

    if args.list_tags_output is not None:
        if args.destination is not None or args.tags or args.tags_file:
            parser.error("--list-tags-output cannot be combined with download options")
        try:
            known = _known_tags_from_index(args.reconcile_index) if args.reconcile_index else None
            inventory = list_release_manifest_tags(
                args.repository, page_size=args.list_page_size,
                skip_tags=known, only_production=args.reconcile_index is not None,
            )
        except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
            print(f"RELEASE_INVENTORY_INCOMPLETE: {exc}", file=sys.stderr)
            return 2
        args.list_tags_output.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.list_tags_output.with_name(args.list_tags_output.name + ".tmp")
        tmp.write_text(
            "".join(f"{tag}\t{str(has_manifest).lower()}\n" for tag, has_manifest in inventory),
            encoding="utf-8",
        )
        os.replace(tmp, args.list_tags_output)
        return 0
    if args.reconcile_index is not None:
        parser.error("--reconcile-index is only valid with --list-tags-output")
    if args.destination is None:
        parser.error("--destination is required to download manifests")

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
