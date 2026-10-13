#!/usr/bin/env python3
"""Fail-closed one-step local main update + certified replay-ready corpus.

This CLI only runs when explicitly invoked in a local checkout. It cannot wake
or depend on a user's PC from cloud GitHub Actions. No trading or uploads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPOSITORY = "Rapt0r06300/hyperliquid-smart-wallet-observer"
TRUSTED_ORIGINS = {
    f"https://github.com/{REPOSITORY}",
    f"https://github.com/{REPOSITORY}.git",
    f"git@github.com:{REPOSITORY}",
    f"git@github.com:{REPOSITORY}.git",
    f"ssh://git@github.com/{REPOSITORY}",
    f"ssh://git@github.com/{REPOSITORY}.git",
}


class SyncError(RuntimeError):
    """An update cannot be completed without risking locally owned files."""


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False, capture_output=True, text=True,
        )
    except OSError as exc:
        raise SyncError("Git is required to synchronize Alina") from exc
    if done.returncode:
        detail = (done.stderr or done.stdout).strip()[:600]
        raise SyncError(f"git {args[0]} failed (exit {done.returncode}): {detail}")
    return done.stdout.strip()


def synchronize_main(root: Path, *, update: bool = True) -> str:
    """Fast-forward ONLY canonical main; never reset/rebase/stash local changes."""
    root = root.resolve()
    actual_root = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    if actual_root != root:
        raise SyncError("execute from the canonical Alina repository root")
    branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch != "main":
        raise SyncError(f"refusing update outside main (current: {branch})")
    origin = _git(root, "remote", "get-url", "origin")
    if origin not in TRUSTED_ORIGINS:
        raise SyncError("origin is not the single canonical Alina GitHub repository")
    if not update:
        return _git(root, "rev-parse", "HEAD")

    # This intentionally ignores untracked/ignored research files; Git itself
    # must refuse a merge that would overwrite any of those paths.
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise SyncError(
            "local tracked files were modified: commit or preserve them before "
            "sync; no reset, stash, forced checkout or overwritten files"
        )
    _git(root, "fetch", "--no-tags", "origin", "main")
    remote_sha = _git(root, "rev-parse", "refs/remotes/origin/main")
    # Non-fast-forward local history is an error, never hidden by an auto-rebase.
    _git(root, "merge", "--ff-only", "refs/remotes/origin/main")
    head = _git(root, "rev-parse", "HEAD")
    if head != remote_sha:
        raise SyncError("main is not identical to the fetched origin/main")
    return head


def restore_published(root: Path, *, preflight: bool = False,
                      snapshot: bool = True,
                      max_download_gib: int | None = None) -> int:
    """Delegate all byte-verification and SAFE gates to the ONE restore engine."""
    root = root.resolve()
    cmd = [
        sys.executable, "-u", str(root / "tools" / "restore_alina.py"),
        "--replay-ready", "--recover-verifiable",
        "--destination", str(root / "runtime" / "recovery" / "full"),
        "--catalog", str(root / "catalog" / "DATA_INDEX.json"),
        "--metrics", str(root / "catalog" / "DATA_METRICS.json"),
    ]
    if preflight:
        cmd.append("--preflight-only")
    elif max_download_gib is not None:
        if type(max_download_gib) is not int or max_download_gib <= 0:
            raise SyncError("download cap must be a positive whole number of GiB")
        cmd.extend(("--max-download-gib", str(max_download_gib)))
    # Workspace snapshots and historical recovery capsules belong to the
    # explicit full-archive profile, not the clean replay/backtest corpus.
    env = os.environ.copy()
    env["GIT_LFS_SKIP_SMUDGE"] = "1"
    env["PYTHONUTF8"] = "1"
    if not env.get("GH_TOKEN") and not env.get("GITHUB_TOKEN"):
        try:
            auth = subprocess.run(
                ["gh", "auth", "token"], check=False,
                capture_output=True, text=True,
            )
            if auth.returncode == 0 and auth.stdout.strip():
                env["GH_TOKEN"] = auth.stdout.strip()
        except OSError:
            pass
    try:
        return subprocess.run(cmd, cwd=root, env=env, check=False).returncode
    except OSError as exc:
        raise SyncError("Python restore could not be launched") from exc



def calculate_catalog_budget(index_path: Path, metrics_path: Path) -> dict:
    """Offline, SHA-bound storage budget; never equate archive size with replay data.

    These are manifest bytes, NOT downloaded/verified bytes or economic proof.
    """
    try:
        from tools.partitioned_data_index import read_index
        from tools.restore_alina import _load_replay_ready_plan
    except ModuleNotFoundError:
        from partitioned_data_index import read_index
        from restore_alina import _load_replay_ready_plan

    # This existing canonical verifier rejects stale metrics, malformed SAFE
    # asset identities, and incompletely reconstructed index partitions.
    _safe, proof, replay_rows, required = _load_replay_ready_plan(
        index_path, metrics_path
    )
    index = read_index(index_path)
    by_quality: dict[str, dict[str, int]] = {}
    by_venue: dict[str, dict[str, int]] = {}
    by_family: dict[str, dict[str, int]] = {}
    total_logical_bytes = 0

    def accumulate(buckets: dict[str, dict[str, int]], key: str, size: int) -> None:
        bucket = buckets.setdefault(key, {"shards": 0, "logical_bytes": 0})
        bucket["shards"] += 1
        bucket["logical_bytes"] += size

    for row in index["shards"]:
        if not isinstance(row, dict):
            raise ValueError("BUDGET_INVALID_INDEX_ROW")
        status = row.get("quality_status")
        if status not in {"SAFE", "PARTIAL", "REJECT", "STALE"}:
            raise ValueError("BUDGET_UNKNOWN_QUALITY_STATUS")
        size = row.get("bytes")
        if type(size) is not int or size < 0:
            raise ValueError("BUDGET_UNKNOWN_SHARD_SIZE")
        quality = (
            "SAFE_REPLAY" if row.get("replay_compatible") is True
            else "SAFE_NOT_REPLAY"
        ) if status == "SAFE" else status
        accumulate(by_quality, quality, size)
        accumulate(by_venue, str(row.get("venue") or "unknown").lower(), size)
        accumulate(by_family, str(row.get("family") or "unknown").lower(), size)
        total_logical_bytes += size

    replay_logical_bytes = sum(int(row["bytes"]) for row in replay_rows)
    if replay_logical_bytes != proof["safe_logical_bytes"]:
        raise ValueError("BUDGET_REPLAY_TOTAL_MISMATCH")
    if by_quality.get("SAFE_REPLAY", {}).get("shards", 0) != len(replay_rows):
        raise ValueError("BUDGET_REPLAY_SHARD_COUNT_MISMATCH")

    # One Release ZIP can hold many logical shards: count its network bytes
    # once, and do not claim that a PARTIAL member makes the whole ZIP waste.
    selected_outer_bytes = sum(size for size, _digest in required.values())
    return {
        "schema": "alina.catalog_storage_budget.v1",
        "status": "CATALOG_ONLY_NOT_RESTORED",
        "source_index_sha256": proof["source_index_sha256"],
        "indexed_shards": proof["indexed_shards"],
        "logical_shard_bytes_all_qualities": total_logical_bytes,
        "by_quality": dict(sorted(by_quality.items())),
        "by_venue": dict(sorted(by_venue.items())),
        "by_family": dict(sorted(by_family.items())),
        "replay_selected_shards": len(replay_rows),
        "replay_selected_logical_bytes": replay_logical_bytes,
        "replay_selected_release_assets": len(required),
        "replay_selected_release_download_bytes": selected_outer_bytes,
        "selected_release_asset_sizes_sha_bound": True,
        "historical_release_total_bytes": None,
        "local_disk_requirement_bytes": None,
        "unselected_assets_proven_unrecoverable": False,
        "unselected_payloads_deleted": False,
        "note": (
            "Catalog accounting only. SAFE+replay-compatibility does not prove "
            "time synchronization, cross-venue continuity, net PnL, downloaded "
            "SHA-256 parity, or total disk space. To measure disk capacity and "
            "analysis receipts, use --preflight-only; it does not download "
            "market payloads. PARTIAL/REJECT data must be preserved for repair."
        ),
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }


def _read_restore_status(
    report_path: Path, *, expected_catalog_sha256: str | None = None
) -> tuple[str, str | None, str | None]:
    """Read the byte-level certificate; a process exit code alone is not proof."""
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return "RESTORE_INCOMPLETE", None, "missing or invalid restore report"
    if not isinstance(payload, dict):
        return "RESTORE_INCOMPLETE", None, "restore report is not an object"
    status = str(payload.get("status") or "RESTORE_INCOMPLETE")
    inventory_sha = payload.get("source_inventory_sha256")
    if not isinstance(inventory_sha, str) or re.fullmatch(r"[0-9a-f]{64}", inventory_sha) is None:
        return "RESTORE_INCOMPLETE", None, "restore report has no valid inventory SHA-256"
    if payload.get("repository") != REPOSITORY:
        return "RESTORE_INCOMPLETE", inventory_sha, "restore report repository mismatch"
    if expected_catalog_sha256 is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_catalog_sha256):
            return "RESTORE_INCOMPLETE", inventory_sha, "invalid canonical index digest"
        verified = payload.get("catalog_verification")
        if (not isinstance(verified, dict)
                or verified.get("source_index_sha256") != expected_catalog_sha256):
            return (
                "RESTORE_INCOMPLETE", inventory_sha,
                "restore report is not bound to the current canonical DATA_INDEX SHA-256",
            )
    return status, inventory_sha, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Update canonical main safely and hydrate every current "
                    "SAFE/replayable shard with SHA-256 verification."
    )
    parser.add_argument(
        "--skip-update", action="store_true",
        help="restore after a fresh git clone without another fetch",
    )
    parser.add_argument(
        "--preflight-only", action="store_true",
        help="inventory historical data and disk without downloading it",
    )
    parser.add_argument(
        "--no-snapshot-materialization", action="store_true",
        help="keep ignored workspace files intact; still download snapshot assets",
    )
    parser.add_argument(
        "--download-safe", action="store_true",
        help="explicit opt-in to download SAFE/replay-compatible assets; "
             "by default only inventory and preflight run",
    )
    parser.add_argument(
        "--max-download-gib", type=int, default=8,
        help="limit NEW SAFE payload transfers to this many GiB (default 8); "
             "requires --download-safe to transfer data",
    )
    parser.add_argument(
        "--catalog-budget", action="store_true",
        help="offline SAFE/PARTIAL/REJECT and replay-ready byte accounting; "
             "no git fetch, GitHub API, payload download or local mutations",
    )
    args = parser.parse_args(argv)
    if args.catalog_budget:
        root = Path(__file__).resolve().parents[1]
        try:
            report = calculate_catalog_budget(
                root / "catalog" / "DATA_INDEX.json",
                root / "catalog" / "DATA_METRICS.json",
            )
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            print(f"ALINA_BUDGET_FAIL: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if args.max_download_gib <= 0:
        print("ALINA_SYNC_FAIL: --max-download-gib must be positive", file=sys.stderr)
        return 2
    if args.download_safe and args.preflight_only:
        print("ALINA_SYNC_FAIL: choose --download-safe OR --preflight-only", file=sys.stderr)
        return 2
    effective_preflight = not args.download_safe
    if sys.version_info < (3, 10):
        print("ALINA_SYNC_FAIL: Python 3.10 or newer is required", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[1]
    try:
        head = synchronize_main(root, update=not args.skip_update)
        print(f"ALINA_MAIN_SHA={head}", flush=True)
        if effective_preflight:
            print("ALINA_PREVIEW_ONLY: no market payload download. "
                  "Use --download-safe for bounded SAFE-only restoration.", flush=True)
        code = restore_published(
            root, preflight=effective_preflight,
            snapshot=not args.no_snapshot_materialization,
            max_download_gib=args.max_download_gib if args.download_safe else None,
        )
    except SyncError as exc:
        print(f"ALINA_SYNC_FAIL: {exc}", file=sys.stderr)
        return 2
    # Bind the local update and Release result to a durable, non-secret checkpoint.
    try:
        report_dir = root / "runtime" / "recovery" / "full"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_name = (
            "RESTORE_PREFLIGHT.json" if effective_preflight else "RESTORE_REPORT.json"
        )
        index_file = root / "catalog" / "DATA_INDEX.json"
        catalog_sha256 = hashlib.sha256(index_file.read_bytes()).hexdigest()
        restore_status, inventory_sha, report_error = _read_restore_status(
            report_dir / report_name,
            expected_catalog_sha256=catalog_sha256 if not args.preflight_only else None,
        )
        certified = (
            not effective_preflight
            and code == 0
            and restore_status == "REPLAY_READY_COMPLETE"
            and report_error is None
        )
        effective_code = code
        if not effective_preflight and code == 0 and not certified:
            effective_code = 2
        checkpoint = {
            "schema": "alina.main_sync.v1",
            "repository": REPOSITORY,
            "branch": "main",
            "git_head": head,
            "catalog_index_sha256": catalog_sha256,
            "restore_exit_code": code,
            "market_payload_download_opt_in": bool(args.download_safe),
            "download_cap_gib": args.max_download_gib if args.download_safe else None,
            "status": "REPLAY_READY_COMPLETE" if certified else "RESTORE_INCOMPLETE",
            "restore_report": report_name,
            "restore_report_status": restore_status,
            "source_inventory_sha256": inventory_sha,
            "report_validation_error": report_error,
        }
        path = report_dir / "SYNC_REPORT.json"
        temporary = path.with_suffix(".json.partial")
        temporary.write_text(json.dumps(checkpoint, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        print(f"ALINA_SYNC_FAIL: cannot persist sync checkpoint: {exc}", file=sys.stderr)
        return 2
    if effective_code:
        print(
            "ALINA_SYNC_INCOMPLETE: code is synchronized but published evidence "
            "is not proven byte-complete; see "
            "runtime/recovery/full/RESTORE_REPORT.json or RESTORE_PREFLIGHT.json",
            file=sys.stderr,
        )
    return effective_code


if __name__ == "__main__":
    raise SystemExit(main())
