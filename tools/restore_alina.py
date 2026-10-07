#!/usr/bin/env python3
"""Restore the complete canonical Alina evidence set after a fresh git clone.

A plain git clone restores Git history and tracked files. Heavy immutable evidence
(trades, L2, replay inputs, recovery capsules and analysis assets) lives in GitHub
Releases of the same repository and is therefore restored separately by this tool.

The tool is read-only against GitHub. It uses only Python's standard library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping

DEFAULT_REPOSITORY = "Rapt0r06300/hyperliquid-smart-wallet-observer"
USER_AGENT = "alina-smartflow-disaster-restore/1"
SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


class RestoreError(RuntimeError):
    pass


def _safe_component(value: str) -> str:
    cleaned = SAFE_COMPONENT.sub("_", str(value)).strip("._")
    if not cleaned:
        raise RestoreError(f"unsafe empty path component derived from {value!r}")
    return cleaned[:220]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _request(url: str, *, token: str | None = None, retries: int = 8) -> bytes:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            transient = exc.code in {403, 429, 500, 502, 503, 504}
            if not transient or attempt >= retries:
                detail = exc.read().decode("utf-8", errors="replace")[:800]
                raise RestoreError(f"HTTP {exc.code} for {url}: {detail}") from exc
            reset = exc.headers.get("X-RateLimit-Reset")
            delay = min(120.0, float(2 ** min(attempt, 6)))
            if reset and reset.isdigit():
                delay = max(delay, min(120.0, int(reset) - time.time() + 2.0))
            time.sleep(max(1.0, delay))
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt >= retries:
                raise RestoreError(f"network failure for {url}: {exc}") from exc
            time.sleep(min(60.0, float(2 ** attempt)))
    raise RestoreError(f"unreachable retry state for {url}")


def _json(url: str, *, token: str | None = None) -> Any:
    try:
        return json.loads(_request(url, token=token).decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RestoreError(f"GitHub returned invalid JSON for {url}") from exc


def iter_releases(repository: str, *, token: str | None = None) -> Iterable[Mapping[str, Any]]:
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repository}/releases?per_page=100&page={page}"
        payload = _json(url, token=token)
        if not isinstance(payload, list):
            raise RestoreError("release listing is not a JSON array")
        if not payload:
            return
        for row in payload:
            if isinstance(row, Mapping):
                yield row
        if len(payload) < 100:
            return
        page += 1


def _expected_digest(asset: Mapping[str, Any]) -> str | None:
    raw = str(asset.get("digest") or "")
    if raw.lower().startswith("sha256:") and len(raw.split(":", 1)[1]) == 64:
        return raw.split(":", 1)[1].lower()
    return None


def _asset_ok(path: Path, asset: Mapping[str, Any]) -> bool:
    if not path.is_file():
        return False
    expected_size = int(asset.get("size") or 0)
    if expected_size > 0 and path.stat().st_size != expected_size:
        return False
    digest = _expected_digest(asset)
    return digest is None or _sha256(path) == digest


def download_asset(
    asset: Mapping[str, Any],
    destination: Path,
    *,
    token: str | None = None,
) -> dict[str, Any]:
    name = str(asset.get("name") or "")
    url = str(asset.get("browser_download_url") or "")
    if not name or not url:
        raise RestoreError("release asset is missing name/browser_download_url")
    target = destination / _safe_component(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    if _asset_ok(target, asset):
        return {"name": name, "path": str(target), "status": "SKIPPED_VERIFIED"}

    tmp = target.with_suffix(target.suffix + ".partial")
    tmp.unlink(missing_ok=True)
    tmp.write_bytes(_request(url, token=token))
    expected_size = int(asset.get("size") or 0)
    if expected_size > 0 and tmp.stat().st_size != expected_size:
        tmp.unlink(missing_ok=True)
        raise RestoreError(f"size mismatch for {name}")
    expected_sha = _expected_digest(asset)
    if expected_sha and _sha256(tmp) != expected_sha:
        tmp.unlink(missing_ok=True)
        raise RestoreError(f"sha256 mismatch for {name}")
    tmp.replace(target)
    return {"name": name, "path": str(target), "status": "DOWNLOADED_VERIFIED"}


def _verify_run_manifests(root: Path) -> list[dict[str, Any]]:
    asset_lookup: dict[tuple[str, str], Path] = {}
    for release_dir in root.iterdir() if root.exists() else []:
        if not release_dir.is_dir():
            continue
        for path in release_dir.iterdir():
            if path.is_file():
                asset_lookup[(release_dir.name, path.name)] = path

    checks: list[dict[str, Any]] = []
    for manifest_path in root.glob("*/RUN_MANIFEST.json"):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            checks.append({"manifest": str(manifest_path), "status": "INVALID", "detail": str(exc)})
            continue
        rows = payload.get("manifests") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            checks.append({"manifest": str(manifest_path), "status": "INVALID", "detail": "missing manifests list"})
            continue
        missing = 0
        bad = 0
        verified = 0
        for row in rows:
            if not isinstance(row, Mapping):
                bad += 1
                continue
            raw_tag = str(
                row.get("release_tag")
                or payload.get("data_release_base_tag")
                or payload.get("release_tag")
                or ""
            )
            name = str(row.get("release_asset") or "")
            expected = str(row.get("sha256") or "").lower()
            tag = _safe_component(raw_tag) if raw_tag else ""
            safe_name = _safe_component(name) if name else ""
            path = asset_lookup.get((tag, safe_name)) if tag and safe_name else None
            if path is None:
                missing += 1
                continue
            if len(expected) == 64 and _sha256(path) != expected:
                bad += 1
            else:
                verified += 1
        status = "OK" if missing == 0 and bad == 0 else "FAIL"
        checks.append(
            {
                "manifest": str(manifest_path),
                "status": status,
                "verified_assets": verified,
                "missing_assets": missing,
                "bad_assets": bad,
            }
        )
    return checks


def restore_everything(
    repository: str,
    destination: Path,
    *,
    token: str | None = None,
) -> dict[str, Any]:
    releases_root = destination / "releases"
    releases_root.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema": "alina.full_restore_report.v1",
        "repository": repository,
        "destination": str(destination),
        "release_count": 0,
        "asset_count": 0,
        "downloaded": 0,
        "skipped_verified": 0,
        "failures": [],
        "releases": [],
        "read_only": True,
        "real_execution": False,
    }

    for release in iter_releases(repository, token=token):
        tag = str(release.get("tag_name") or "")
        if not tag:
            continue
        safe_tag = _safe_component(tag)
        release_dir = releases_root / safe_tag
        assets = release.get("assets")
        assets = assets if isinstance(assets, list) else []
        row = {"tag": tag, "asset_count": len(assets), "assets": []}
        report["release_count"] += 1
        for asset in assets:
            if not isinstance(asset, Mapping):
                continue
            report["asset_count"] += 1
            try:
                result = download_asset(asset, release_dir, token=token)
                row["assets"].append(result)
                if result["status"] == "DOWNLOADED_VERIFIED":
                    report["downloaded"] += 1
                else:
                    report["skipped_verified"] += 1
            except RestoreError as exc:
                failure = {"tag": tag, "asset": asset.get("name"), "error": str(exc)}
                report["failures"].append(failure)
                row["assets"].append({"name": asset.get("name"), "status": "FAIL", "error": str(exc)})
        report["releases"].append(row)

    report["run_manifest_checks"] = _verify_run_manifests(releases_root)
    report["verification_failures"] = sum(
        1 for row in report["run_manifest_checks"] if row.get("status") != "OK"
    )
    report_path = destination / "RESTORE_REPORT.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Restore every canonical Alina GitHub Release asset after cloning the repository."
    )
    parser.add_argument("--everything", action="store_true", help="restore all canonical release evidence")
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--destination", default="runtime/recovery/full")
    args = parser.parse_args(argv)

    if not args.everything:
        parser.error("--everything is required to make the destructive-looking intent explicit")

    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    destination = Path(args.destination).resolve()
    try:
        report = restore_everything(args.repository, destination, token=token)
    except RestoreError as exc:
        print(f"ALINA_RESTORE_FAIL: {exc}", file=sys.stderr)
        return 2

    failures = len(report["failures"]) + int(report["verification_failures"])
    print(
        json.dumps(
            {
                "status": "OK" if failures == 0 else "FAIL",
                "release_count": report["release_count"],
                "asset_count": report["asset_count"],
                "downloaded": report["downloaded"],
                "skipped_verified": report["skipped_verified"],
                "failures": failures,
                "report": str(destination / "RESTORE_REPORT.json"),
            },
            indent=2,
        )
    )
    return 0 if failures == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
