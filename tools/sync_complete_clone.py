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
import sqlite3
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
        # An existing multi-GB checkout can spend a long time fetching. Keep
        # Git's real stderr progress visible instead of silently buffering it.
        fetching = bool(args) and args[0] == "fetch"
        command = ["git", "-C", str(root), *args]
        if fetching and "--progress" not in args:
            command.insert(4, "--progress")
            print("ALINA_SYNC_PHASE=FETCH_MAIN", file=sys.stderr, flush=True)
        done = subprocess.run(
            command, check=False, text=True,
            stdout=subprocess.PIPE,
            stderr=None if fetching else subprocess.PIPE,
        )
        if fetching and done.returncode == 0:
            print("ALINA_SYNC_PHASE=FETCH_MAIN_COMPLETE", file=sys.stderr, flush=True)
    except OSError as exc:
        raise SyncError("Git is required to synchronize Alina") from exc
    if done.returncode:
        detail = (done.stderr or done.stdout).strip()[:600]
        raise SyncError(f"git {args[0]} failed (exit {done.returncode}): {detail}")
    return done.stdout.strip()


def _tracked_files_changed(root: Path) -> bool:
    """Return whether tracked content differs, ignoring Windows stat-cache noise."""
    checks = (
        ("diff", "--quiet", "--no-ext-diff", "--ignore-submodules", "--"),
        ("diff", "--cached", "--quiet", "--no-ext-diff", "--ignore-submodules", "--"),
    )
    for args in checks:
        try:
            done = subprocess.run(
                ["git", "-C", str(root), *args],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            raise SyncError("Git is required to verify local tracked files") from exc
        if done.returncode == 1:
            return True
        if done.returncode != 0:
            detail = (done.stderr or "").strip()[:600]
            raise SyncError(
                f"git tracked-file safety check failed (exit {done.returncode}): {detail}"
            )
    return False


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
    if _tracked_files_changed(root):
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
                      max_download_gib: int | None = None,
                      prune_only: bool = False,
                      unlimited_download: bool = False,
                      copy_vault_only: bool = False) -> int:
    """Delegate all byte-verification and SAFE gates to the ONE restore engine."""
    root = root.resolve()
    cmd = [
        sys.executable, "-u", str(root / "tools" / "restore_alina.py"),
        "--replay-ready", "--recover-verifiable",
        "--destination", str(root / "runtime" / "recovery" / "full"),
        "--catalog", str(root / "catalog" / "DATA_INDEX.json"),
        "--metrics", str(root / "catalog" / "DATA_METRICS.json"),
    ]
    if copy_vault_only:
        cmd.append("--copy-vault-only")
    if preflight and prune_only:
        raise SyncError("cannot combine cache pruning with restoration preflight")
    if prune_only:
        # Metadata/SHA checks and local cache deletion only: hard zero-byte
        # network payload cap is a second independent safety barrier.
        cmd.extend(("--prune-cache-only", "--max-download-gib", "0"))
    elif preflight:
        cmd.append("--preflight-only")
    elif unlimited_download:
        cmd.append("--unlimited-download")
    else:
        # Keep all historical/unselected local cache copies unless the operator
        # explicitly requested --prune-cache-only in a separate operation.
        if max_download_gib is not None:
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



def calculate_catalog_budget(
    index_path: Path, metrics_path: Path, *, copy_vault_only: bool = False,
) -> dict:
    """Offline, SHA-bound storage budget; never equate archive size with replay data.

    These are manifest bytes, NOT downloaded/verified bytes or economic proof.
    """
    try:
        from tools.restore_alina import _load_replay_ready_plan
        from tools.partitioned_data_index import select_index_rows
    except ModuleNotFoundError:
        from restore_alina import _load_replay_ready_plan
        from partitioned_data_index import select_index_rows

    # This existing canonical verifier rejects stale metrics, malformed SAFE
    # asset identities, and incomplete catalog partitions. The budget report
    # needs rows from every quality class, so scan again through the bounded
    # partition selector after releasing the SAFE replay row set. Bind both
    # passes to the same exact index SHA rather than retaining the full index.
    proof, replay_rows, required = _load_replay_ready_plan(
        index_path, metrics_path, copy_vault_only=copy_vault_only,
    )
    replay_shard_count = len(replay_rows)
    replay_logical_bytes = int(proof["safe_logical_bytes"])
    del replay_rows
    metadata, index_rows = select_index_rows(
        index_path,
        lambda row: (
            not copy_vault_only
            or str(row.get("family") or "").startswith("copy_vault_")
        ),
    )
    if (
        metadata.get("_verified_shard_count") != proof["indexed_shards"]
        or hashlib.sha256(index_path.read_bytes()).hexdigest()
        != proof["source_index_sha256"]
    ):
        raise ValueError("BUDGET_VERIFIED_CATALOG_CHANGED")
    by_quality: dict[str, dict[str, int]] = {}
    by_venue: dict[str, dict[str, int]] = {}
    by_family: dict[str, dict[str, int]] = {}
    safe_by_venue_family: dict[str, dict[str, dict]] = {}
    total_logical_bytes = 0

    def accumulate(buckets: dict[str, dict[str, int]], key: str, size: int) -> None:
        bucket = buckets.setdefault(key, {"shards": 0, "logical_bytes": 0})
        bucket["shards"] += 1
        bucket["logical_bytes"] += size

    for row in index_rows:
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
        if quality == "SAFE_REPLAY":
            # Only catalogue metadata. Time bounds are NOT a continuity,
            # synchronized-venues, replay or out-of-sample certificate.
            venue = str(row.get("venue") or "unknown").lower()
            family = str(row.get("family") or "unknown").lower()
            bucket = safe_by_venue_family.setdefault(venue, {}).setdefault(
                family, {
                    "shards": 0, "logical_bytes": 0,
                    "reported_events": 0, "event_count_missing_shards": 0,
                    "first_ts_ms": None, "last_ts_ms": None,
                    "time_bounds_missing_shards": 0,
                },
            )
            bucket["shards"] += 1
            bucket["logical_bytes"] += size
            events = row.get("event_count")
            if type(events) is int and events > 0:
                bucket["reported_events"] += events
            else:
                bucket["event_count_missing_shards"] += 1
            start, end = row.get("start_ts_ms"), row.get("end_ts_ms")
            if (type(start) is int and type(end) is int
                    and 0 <= start <= end):
                if bucket["first_ts_ms"] is None or start < bucket["first_ts_ms"]:
                    bucket["first_ts_ms"] = start
                if bucket["last_ts_ms"] is None or end > bucket["last_ts_ms"]:
                    bucket["last_ts_ms"] = end
            else:
                bucket["time_bounds_missing_shards"] += 1
        total_logical_bytes += size

    if by_quality.get("SAFE_REPLAY", {}).get("shards", 0) != replay_shard_count:
        raise ValueError("BUDGET_REPLAY_SHARD_COUNT_MISMATCH")

    # One Release ZIP can hold many logical shards: count its network bytes
    # once, and do not claim that a PARTIAL member makes the whole ZIP waste.
    selected_outer_bytes = sum(size for size, _digest in required.values())
    return {
        "schema": "alina.catalog_storage_budget.v1",
        "status": "CATALOG_ONLY_NOT_RESTORED",
        "selection_scope": proof["selection_scope"],
        "selection_families": proof["selection_families"],
        "source_index_sha256": proof["source_index_sha256"],
        "indexed_shards": proof["indexed_shards"],
        "logical_shard_bytes_all_qualities": total_logical_bytes,
        "by_quality": dict(sorted(by_quality.items())),
        "by_venue": dict(sorted(by_venue.items())),
        "by_family": dict(sorted(by_family.items())),
        "safe_by_venue_family": {
            venue: dict(sorted(families.items()))
            for venue, families in sorted(safe_by_venue_family.items())
        },
        "safe_time_bounds_meaning": (
            "Earliest and latest declared shard timestamps only; NOT continuous "
            "coverage or an executable replay/backtest certificate."
        ),
        "replay_selected_shards": replay_shard_count,
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
    if status == "REPLAY_READY_COMPLETE":
        classification = payload.get("classification")
        verification = payload.get("catalog_verification")
        if not isinstance(classification, dict) or not isinstance(verification, dict):
            return (
                "RESTORE_INCOMPLETE", inventory_sha,
                "restore report has no exact SAFE materialization parity",
            )
        expected_shards = classification.get("expected_usable_shards")
        usable_shards = classification.get("usable_shards")
        expected_bytes = classification.get("expected_usable_bytes")
        usable_bytes = classification.get("usable_bytes")
        catalog_safe = verification.get("safe_catalog_shards", expected_shards)
        if (
            type(expected_shards) is not int or expected_shards < 0
            or type(usable_shards) is not int or usable_shards != expected_shards
            or type(expected_bytes) is not int or expected_bytes < 0
            or type(usable_bytes) is not int or usable_bytes != expected_bytes
            or type(catalog_safe) is not int or catalog_safe != expected_shards
            or classification.get("materialization_complete") is not True
            or classification.get("failures") not in ([], None)
        ):
            return (
                "RESTORE_INCOMPLETE", inventory_sha,
                "restore report has no exact SAFE materialization parity",
            )
    return status, inventory_sha, None


def _read_safe_shard_summary(report_path: Path) -> dict[str, object]:
    """Expose only the AlinaSync-owned SAFE registry counters in SYNC_REPORT."""
    empty: dict[str, object] = {
        "safe_shard_database": None,
        "safe_replayable_shards": 0,
        "safe_backtestable_shards": 0,
        "registry_reused_shards": 0,
        "registry_recorded_shards": 0,
        "l2_certification_status": "NOT_AVAILABLE",
        "l2_catalog_sha256": None,
        "l2_snapshot_backtestable_shards": 0,
        "l2_continuous_replayable_shards": 0,
        "l2_reanchored_segment_assets": 0,
        "l2_blocked_shards": 0,
    }
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return empty
    classification = payload.get("classification")
    if not isinstance(classification, dict):
        return empty
    if (
        classification.get("materialization_complete") is not True
        or classification.get("failures") not in ([], None)
    ):
        return empty
    usable = classification.get("usable_shards")
    if type(usable) is not int or usable < 0:
        return empty
    database = classification.get("safe_shard_database")
    database_name = Path(database).name if isinstance(database, str) else None
    if database_name != "SAFE_SHARDS.sqlite3":
        database_name = None
    summary = {
        "safe_shard_database": database_name,
        "safe_replayable_shards": usable,
        "safe_backtestable_shards": usable,
        "registry_reused_shards": int(
            classification.get("registry_reused_shards") or 0
        ),
        "registry_recorded_shards": int(
            classification.get("registry_recorded_shards") or 0
        ),
        "l2_certification_status": "NOT_AVAILABLE",
        "l2_catalog_sha256": None,
        "l2_snapshot_backtestable_shards": 0,
        "l2_continuous_replayable_shards": 0,
        "l2_reanchored_segment_assets": 0,
        "l2_blocked_shards": 0,
    }
    if database_name is None:
        return summary
    database_path = report_path.parent / database_name
    if database_path.is_symlink() or not database_path.is_file():
        return summary
    verification = payload.get("catalog_verification")
    expected_catalog = (
        verification.get("source_index_sha256")
        if isinstance(verification, dict) else None
    )
    try:
        uri = database_path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5.0) as connection:
            meta = dict(connection.execute(
                "SELECT key, value FROM l2_certification_meta "
                "WHERE key IN ('run_status', 'active_catalog_sha256')"
            ))
            active_catalog = meta.get("active_catalog_sha256")
            if (
                meta.get("run_status") != "COMPLETE"
                or not isinstance(expected_catalog, str)
                or active_catalog != expected_catalog
            ):
                summary["l2_certification_status"] = "STALE_OR_INCOMPLETE"
                return summary
            counts = connection.execute("""
                SELECT
                    SUM(CASE WHEN snapshot_backtestable=1 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN continuous_replayable=1 THEN 1 ELSE 0 END),
                    SUM(CASE WHEN status='BLOCKED' THEN 1 ELSE 0 END)
                FROM l2_certifications
                WHERE catalog_sha256=?
            """, (active_catalog,)).fetchone()
            has_repaired = connection.execute("""
                SELECT 1 FROM sqlite_master
                WHERE type='table' AND name='l2_reanchored_segment_assets'
            """).fetchone()
            repaired_count = (
                connection.execute(
                    "SELECT COUNT(*) FROM l2_reanchored_segment_assets "
                    "WHERE catalog_sha256=?", (active_catalog,),
                ).fetchone()[0]
                if has_repaired else 0
            )
    except (OSError, sqlite3.Error, ValueError):
        return summary
    summary.update({
        "l2_certification_status": "COMPLETE",
        "l2_catalog_sha256": active_catalog,
        "l2_snapshot_backtestable_shards": int(counts[0] or 0),
        "l2_continuous_replayable_shards": int(counts[1] or 0),
        "l2_reanchored_segment_assets": int(repaired_count or 0),
        "l2_blocked_shards": int(counts[2] or 0),
    })
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Update canonical main and preflight SAFE/replayable "
                    "shards; downloads require --download-safe."
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
        "--prune-cache-only", action="store_true",
        help="remove only locally SHA-verified, unselected Release cache copies; "
             "no market payload downloads or remote deletions",
    )
    parser.add_argument(
        "--download-safe", action="store_true",
        help="explicitly hydrate SAFE/replayable assets after an explicit operator opt-in",
    )
    parser.add_argument(
        "--max-download-gib", type=int, default=8,
        help="limit NEW SAFE payload transfers to this many GiB "
             "(default %(default)s)",
    )
    parser.add_argument(
        "--unpack-safe", action="store_true",
        help="unpack certified SAFE gzip shards to JSONL with disk guard and SHA receipts",
    )
    parser.add_argument(
        "--all-safe", action="store_true",
        help="restore all catalog-selected SAFE/replayable assets without a download cap",
    )
    parser.add_argument(
        "--copy-vault-only", action="store_true",
        help="restrict SAFE restoration and catalog accounting to copy_vault_* families",
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
                copy_vault_only=args.copy_vault_only,
            )
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            print(f"ALINA_BUDGET_FAIL: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if args.all_safe and any(token == "--max-download-gib" or token.startswith("--max-download-gib=") for token in (argv if argv is not None else sys.argv[1:])):
        print("ALINA_SYNC_FAIL: --all-safe conflicts with --max-download-gib", file=sys.stderr)
        return 2
    if args.all_safe and not args.download_safe:
        print("ALINA_SYNC_FAIL: --all-safe requires --download-safe", file=sys.stderr)
        return 2
    if args.unpack_safe and not args.download_safe:
        print("ALINA_SYNC_FAIL: --unpack-safe requires --download-safe", file=sys.stderr)
        return 2
    if args.max_download_gib <= 0:
        print("ALINA_SYNC_FAIL: --max-download-gib must be positive", file=sys.stderr)
        return 2
    if sum((args.download_safe, args.preflight_only, args.prune_cache_only)) > 1:
        print("ALINA_SYNC_FAIL: choose exactly one of --download-safe, "
              "--preflight-only or --prune-cache-only", file=sys.stderr)
        return 2
    effective_download = args.download_safe
    effective_preflight = not (args.download_safe or args.prune_cache_only)
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
        if args.prune_cache_only:
            print("ALINA_LOCAL_CACHE_PRUNE_ONLY: no market downloads and no GitHub asset deletions.", flush=True)
        # A previous successful report must never certify a new restore run.
        # Preserve the historical report for diagnosis, but require this run
        # to replace it with fresh evidence before reporting success.
        report_dir = root / "runtime" / "recovery" / "full"
        report_name = "RESTORE_PREFLIGHT.json" if effective_preflight else "RESTORE_REPORT.json"
        prior_report = report_dir / report_name
        prior_identity = None
        if prior_report.is_symlink():
            raise SyncError("refusing symlinked restore report")
        try:
            stat = prior_report.stat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise SyncError(f"cannot inspect prior restore report: {exc}") from exc
        else:
            if not prior_report.is_file():
                raise SyncError("restore report path is not a regular file")
            prior_identity = (stat.st_mtime_ns, stat.st_ctime_ns)
        code = restore_published(
            root, preflight=effective_preflight,
            snapshot=not args.no_snapshot_materialization,
            max_download_gib=(None if args.all_safe else args.max_download_gib) if effective_download else None,
            prune_only=args.prune_cache_only,
            unlimited_download=args.all_safe,
            copy_vault_only=args.copy_vault_only,
        )
        if args.prune_cache_only:
            # The restore engine writes CACHE_PRUNE_REPORT.json; never turn a
            # maintenance success into a certified SYNC_REPORT.
            return code
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
            expected_catalog_sha256=catalog_sha256 if not effective_preflight else None,
        )
        safe_shard_summary = _read_safe_shard_summary(report_dir / report_name)
        current_report = report_dir / report_name
        if current_report.is_symlink() or not current_report.is_file():
            restore_status, report_error = "RESTORE_INCOMPLETE", "missing or unsafe restore report"
        elif prior_identity is not None:
            current = current_report.stat()
            if (current.st_mtime_ns, current.st_ctime_ns) == prior_identity:
                restore_status, report_error = "RESTORE_INCOMPLETE", "restore did not refresh its report"
        certified = (
            not effective_preflight
            and code == 0
            and restore_status == "REPLAY_READY_COMPLETE"
            and report_error is None
        )
        effective_code = code
        if not effective_preflight and code == 0 and not certified:
            effective_code = 2
        unpack_report = None
        if certified and args.unpack_safe:
            try:
                try:
                    from tools.unpack_verified_safe import expand_safe_corpus
                except ModuleNotFoundError:
                    from unpack_verified_safe import expand_safe_corpus
                unpack_report = expand_safe_corpus(
                    report_dir, catalog_sha256=catalog_sha256,
                    catalog_path=index_file,
                )
            except (OSError, ValueError, RuntimeError) as exc:
                report_error = f"SAFE_UNPACK_INCOMPLETE: {exc}"[:700]
                print(f"ALINA_UNPACK_FAIL: {report_error}", file=sys.stderr, flush=True)
                effective_code = 3
                certified = False
        checkpoint = {
            "schema": "alina.main_sync.v1",
            "repository": REPOSITORY,
            "branch": "main",
            "git_head": head,
            "catalog_index_sha256": catalog_sha256,
            "restore_exit_code": code,
            "market_payload_download_opt_in": bool(effective_download),
            "download_cap_gib": (None if args.all_safe else args.max_download_gib) if effective_download else None,
            "selection_scope": (
                "COPY_VAULT_ONLY" if args.copy_vault_only else "ALL_SAFE_REPLAYABLE"
            ),
            "status": "REPLAY_READY_COMPLETE" if certified else "RESTORE_INCOMPLETE",
            "restore_report": report_name,
            "restore_report_status": restore_status,
            "source_inventory_sha256": inventory_sha,
            "report_validation_error": report_error,
            "unpack_requested": bool(args.unpack_safe),
            "unpack_complete": bool(
                unpack_report and unpack_report.get("status") == "SAFE_UNPACK_COMPLETE"
            ),
            "unpack_report": "UNPACK_REPORT.json" if unpack_report else None,
            **safe_shard_summary,
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
