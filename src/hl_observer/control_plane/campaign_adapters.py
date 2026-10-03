"""Deterministic bounded adapters for resumable GitHub-hosted campaigns."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[3]
ECONOMIC_KINDS = frozenset({"backtest", "oos", "forward_paper", "module_pnl_proof", "scoreboard"})
ANALYSIS_STAGE_BY_KIND = {
    "replay": "REPLAY",
    "backtest": "BACKTEST",
    "oos": "OOS",
    "forward_paper": "FORWARD_PAPER",
    "module_pnl_proof": "PNL_PROOF",
    "scoreboard": "SCOREBOARD",
}


def _analysis_stage(kind: str) -> str | None:
    return ANALYSIS_STAGE_BY_KIND.get(str(kind))


@dataclass(frozen=True)
class AdapterContext:
    campaign_id: str
    kind: str
    unit_id: str
    soft_deadline_epoch: float
    partition: dict[str, Any]


@dataclass(frozen=True)
class AdapterResult:
    status: str
    sha256: str
    payload: dict[str, Any]
    progressed: bool = True


def _digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _bounded_float(value: Any, default: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(1.0, min(parsed, maximum))


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _output_root(ctx: AdapterContext) -> Path:
    configured = ctx.partition.get("output_root")
    root = Path(str(configured)) if configured else Path.cwd() / "campaign-output"
    return root / ctx.campaign_id / ctx.unit_id


def _workspace(ctx: AdapterContext) -> Path:
    configured = ctx.partition.get("workspace_root")
    if configured:
        return Path(str(configured))
    return Path.cwd() / "campaign-workspaces" / ctx.campaign_id / ctx.unit_id


def _cutoff_ts_ms(value: Any) -> int | None:
    if not value:
        return None
    try:
        from datetime import datetime
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return int(parsed.timestamp() * 1000)
    except (TypeError, ValueError, OverflowError):
        return None


def _selection_args(ctx: AdapterContext) -> list[str]:
    args: list[str] = []
    for key, flag in (
        ("families", "--families"),
        ("venues", "--venues"),
        ("symbols", "--symbols"),
    ):
        value = ctx.partition.get(key)
        if value:
            args.extend([flag, str(value)])
    for key, flag in (
        ("start_ts_ms", "--start-ts-ms"),
        ("end_ts_ms", "--end-ts-ms"),
        ("max_shards", "--max-shards"),
    ):
        value = ctx.partition.get(key)
        if value is not None:
            args.extend([flag, str(int(value))])
    if ctx.partition.get("end_ts_ms") is None:
        cutoff = _cutoff_ts_ms(ctx.partition.get("collection_cutoff_at_utc"))
        if cutoff is not None:
            args.extend(["--end-ts-ms", str(cutoff)])
    for key, flag in (
        ("dataset_selection_id", "--dataset-selection-id"),
        ("collection_cutoff_at_utc", "--collection-cutoff-at-utc"),
    ):
        value = ctx.partition.get(key)
        if value:
            args.extend([flag, str(value)])
    if ctx.partition.get("source_collection_epoch") is not None:
        args.extend(["--source-collection-epoch", str(int(ctx.partition["source_collection_epoch"]))])
    return args


def _dataset_bridge_command(
    ctx: AdapterContext,
    workspace: Path,
    *,
    action: str,
) -> list[str]:
    if action not in {"plan", "materialize"}:
        raise ValueError("dataset bridge action must be plan or materialize")
    return [
        sys.executable,
        "-m",
        "hl_observer.ops.v2_dataset_bridge",
        action,
        "--output",
        str(workspace),
        *_selection_args(ctx),
    ]


def _materialize_command(ctx: AdapterContext, workspace: Path) -> list[str]:
    return _dataset_bridge_command(ctx, workspace, action="materialize")


def _economic_proof_status(workspace: Path) -> str | None:
    """Read the semantic PnL-proof verdict produced by the audit.

    This is intentionally separate from subprocess success. A valid audit may
    conclude that evidence is incomplete/unmeasurable without meaning that the
    orchestration itself crashed.
    """
    path = (
        workspace
        / "runtime"
        / "reports"
        / "economic_campaigns"
        / "HYPERSMART_ECONOMIC_PROOF_AUDIT.json"
    )
    if not path.is_file():
        return None
    try:
        audit = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if (
        audit.get("schema_version") != "hypersmart.economic_proof_audit.v1"
        or audit.get("paper_read_only") is not True
        or audit.get("real_execution") is not False
    ):
        return None
    if audit.get("missing_families") or audit.get("all_ledgers_valid") is not True:
        return "UNMEASURABLE"
    if audit.get("all_objectives_met") is True:
        return "PASS"
    classifications = {
        str(row.get("classification") or "")
        for row in (audit.get("families") or [])
        if isinstance(row, dict)
    }
    if "INCOMPLETE" in classifications:
        return "MORE_DATA"
    return "KILL"


def build_command(ctx: AdapterContext) -> tuple[list[str], Path | None]:
    """Build one real bounded command for the requested campaign kind."""
    out = _output_root(ctx)
    version = str(
        ctx.partition.get("code_sha")
        or ctx.partition.get("collector_version")
        or "campaign"
    )
    run_id = str(
        ctx.partition.get("collection_run_id")
        or f"{ctx.campaign_id}-{ctx.unit_id}"
    )
    py = sys.executable

    if ctx.kind == "market_collection":
        duration = _bounded_float(ctx.partition.get("duration_s"), 3600.0, 18_000.0)
        coins = str(ctx.partition.get("coins") or "BTC,ETH,SOL")
        return [
            py,
            str(ROOT / "tools" / "collect_cloud_window.py"),
            "--output",
            str(out),
            "--coins",
            coins,
            *(
                ["--plan-file", str(ctx.partition["plan_file"])]
                if ctx.partition.get("plan_file")
                else []
            ),
            "--duration-s",
            str(duration),
            "--collector-version",
            version,
            "--collection-run-id",
            run_id,
            "--rotate-mb",
            str(_bounded_int(ctx.partition.get("rotate_mb"), 64, 1, 512)),
            "--require-l2",
        ], out

    if ctx.kind == "copy_vault_collection":
        duration = _bounded_float(ctx.partition.get("duration_s"), 3600.0, 18_000.0)
        max_vaults = _bounded_int(ctx.partition.get("max_vaults"), 10, 1, 100_000)
        shard_count = _bounded_int(ctx.partition.get("vault_shard_count"), 1, 1, 10_000)
        shard_index = _bounded_int(
            ctx.partition.get("vault_shard_index"),
            0,
            0,
            max(0, shard_count - 1),
        )
        mode = str(ctx.partition.get("copy_vault_mode") or "legacy_sharded_ws")
        raw_max_ws_vaults = ctx.partition.get("max_ws_vaults", 10)
        try:
            requested_max_ws_vaults = int(raw_max_ws_vaults)
        except (TypeError, ValueError, OverflowError):
            requested_max_ws_vaults = 10
        if not 1 <= requested_max_ws_vaults <= 10:
            raise ValueError(
                "copy-vault two-speed mode allows 1..10 unique WS users per IP"
            )
        max_ws_vaults = requested_max_ws_vaults
        if mode == "two_speed_broad_rest_priority_ws":
            if shard_count != 1 or shard_index != 0:
                raise ValueError("two-speed Copy-Vault mode requires one broad universe lane")
        else:
            users_in_largest_lane = (max_vaults + shard_count - 1) // shard_count
            if users_in_largest_lane > 10:
                raise ValueError(
                    "copy-vault partition exceeds Hyperliquid 10 unique users per IP"
                )
        cmd = [
            py,
            str(ROOT / "tools" / "collect_cloud_copy_vault.py"),
            "--output",
            str(out),
            "--duration-s",
            str(duration),
            "--collector-version",
            version,
            "--collection-run-id",
            run_id,
            "--max-vaults",
            str(max_vaults),
            "--vault-shard-count",
            str(shard_count),
            "--vault-shard-index",
            str(shard_index),
            "--max-ws-vaults",
            str(max_ws_vaults),
            *(
                ["--two-speed"]
                if mode == "two_speed_broad_rest_priority_ws"
                else []
            ),
            "--rotate-mb",
            str(_bounded_int(ctx.partition.get("rotate_mb"), 64, 1, 512)),
        ]
        selection = ctx.partition.get("selection_file")
        if selection:
            selection_path = Path(str(selection))
            if not selection_path.is_file():
                raise ValueError("copy-vault frozen selection file is missing")
            expected_sha = str(ctx.partition.get("selection_sha256") or "").lower()
            if expected_sha:
                actual_sha = hashlib.sha256(selection_path.read_bytes()).hexdigest()
                if actual_sha != expected_sha:
                    raise ValueError("copy-vault frozen selection digest mismatch")
            cmd.extend(["--selection-file", str(selection_path)])
        return cmd, out

    if ctx.kind == "official_archive_collection":
        venue = str(ctx.partition.get("venue") or "binance").lower()
        if venue not in {"binance", "bybit"}:
            raise ValueError("official archive venue must be binance or bybit")
        coin = str(ctx.partition.get("coin") or "BTC").upper()
        symbol = str(ctx.partition.get("symbol") or f"{coin}USDT").upper()
        start_date = str(ctx.partition.get("start_date") or "")
        if not start_date:
            raise ValueError("official archive campaign requires start_date")
        return [
            py,
            str(ROOT / "tools" / "collect_official_archive_backfill.py"),
            "--venue",
            venue,
            "--coin",
            coin,
            "--symbol",
            symbol,
            "--start-date",
            start_date,
            "--end-date",
            str(ctx.partition.get("end_date") or start_date),
            "--output",
            str(out),
            "--collector-version",
            version,
            "--collection-run-id",
            run_id,
            "--max-days",
            str(_bounded_int(ctx.partition.get("max_days"), 1, 1, 3)),
            "--max-events-per-day",
            str(
                _bounded_int(
                    ctx.partition.get("max_events_per_day"),
                    2_000_000,
                    1,
                    2_000_000,
                )
            ),
        ], out / "bundle"

    if ctx.kind == "event_intelligence_collection":
        return [
            py,
            str(ROOT / "tools" / "collect_event_intelligence_v2.py"),
            "--output",
            str(out),
            "--collector-version",
            version,
            "--collection-run-id",
            run_id,
        ], out

    workspace = _workspace(ctx)
    if ctx.kind == "replay":
        # The dedicated resume-proof replay campaign deliberately splits one
        # canonical replay into two useful fresh-runner units: unit 0 freezes and
        # verifies the exact SAFE selection without materializing it; unit 1
        # restores from durable Dataset V2 and materializes that same selection.
        # No completed replay/materialization work is repeated across segments.
        if ctx.partition.get("resume_proof") is True and int(ctx.partition.get("chunk_index") or 0) == 0:
            return _dataset_bridge_command(ctx, workspace, action="plan"), workspace
        return _materialize_command(ctx, workspace), workspace

    if ctx.kind in ECONOMIC_KINDS:
        return [
            py,
            str(ROOT / "tools" / "run_economic_objective_campaigns.py"),
            "--root",
            str(workspace),
            "--no-start-collection",
            "--analysis-stage",
            _analysis_stage(ctx.kind) or str(ctx.kind).upper(),
        ], workspace

    raise ValueError(f"unsupported campaign kind: {ctx.kind}")


def _run(
    runner: Callable[..., Any],
    cmd: list[str],
    *,
    timeout: int,
    analysis_stage: str | None = None,
) -> Any:
    env = os.environ.copy()
    if analysis_stage:
        env["ALINA_ANALYSIS_STAGE"] = analysis_stage
    return runner(
        cmd,
        capture_output=True,
        text=True,
        timeout=max(1, int(timeout)),
        check=False,
        cwd=str(ROOT),
        env=env,
    )


def _failure_payload(cmd: list[str], cp: Any) -> dict[str, Any]:
    stdout = str(getattr(cp, "stdout", "") or "")[-8000:]
    stderr = str(getattr(cp, "stderr", "") or "")[-8000:]
    combined = (stdout + "\n" + stderr).lower()
    category = (
        "TEMPORARY_EXTERNAL"
        if any(
            token in combined
            for token in (
                "timeout",
                "temporar",
                "503",
                "502",
                "connection reset",
                "rate limit",
                "temporary external",
            )
        )
        else "QUALITY"
    )
    return {
        "status": "FAILED",
        "reason": "adapter_failed",
        "failure_category": category,
        "returncode": int(getattr(cp, "returncode", 1) or 1),
        "command": cmd[:4],
        "stdout": stdout,
        "stderr": stderr,
    }


def _collection_checkpoint_metrics(output_root: Path) -> dict[str, Any]:
    """Read compact exact counters from one completed collection bundle."""
    summary_path = output_root / "collection_summary.json"
    index_path = output_root / "BUNDLE_INDEX.json"
    summary: dict[str, Any] = {}
    index: dict[str, Any] = {}
    try:
        loaded = json.loads(summary_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            summary = loaded
    except (OSError, ValueError, TypeError):
        pass
    try:
        loaded = json.loads(index_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            index = loaded
    except (OSError, ValueError, TypeError):
        pass

    trade_count = 0
    record_count = 0
    compressed_bytes = 0
    uncompressed_bytes = 0
    uncompressed_exact_shards = 0
    bbo_frames = 0
    l2_manifest_frames = 0
    manifest_count = 0
    trade_shards = 0
    trade_shards_exact = 0
    manifest_paths = index.get("manifests")
    if isinstance(manifest_paths, list):
        for rel in manifest_paths:
            try:
                row = json.loads((output_root / str(rel)).read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if not isinstance(row, dict):
                continue
            manifest_count += 1
            records = _bounded_int(
                row.get("record_count") or row.get("event_count"), 0, 0, 2**63 - 1
            )
            record_count += records
            compressed_bytes += _bounded_int(row.get("bytes"), 0, 0, 2**63 - 1)
            if row.get("uncompressed_size_exact") is True:
                uncompressed_exact_shards += 1
                uncompressed_bytes += _bounded_int(
                    row.get("uncompressed_bytes"), 0, 0, 2**63 - 1
                )
            family = str(row.get("family") or "").lower()
            if family in {"l2book", "copy_vault_l2", "native_market"}:
                l2_manifest_frames += records
            elif family == "bbo":
                bbo_frames += records
            if family in {
                "trades",
                "agg_trades",
                "fills",
                "userfills",
                "user_fills",
                "copy_vault_fills",
            }:
                trade_shards += 1
                if row.get("trade_count_exact") is True:
                    trade_shards_exact += 1
                    trade_count += _bounded_int(
                        row.get("trade_count"), 0, 0, 2**63 - 1
                    )

    drops = summary.get("queue_drops")
    if isinstance(drops, dict):
        queue_drops = sum(_bounded_int(v, 0, 0, 2**63 - 1) for v in drops.values())
    else:
        queue_drops = _bounded_int(drops, 0, 0, 2**63 - 1)

    return {
        "trade_count_observed": trade_count,
        "trade_count_coverage_complete": trade_shards == trade_shards_exact,
        "trade_shard_count": trade_shards,
        "trade_shards_exact": trade_shards_exact,
        "record_count_observed": record_count,
        "accepted_frames": _bounded_int(
            summary.get("accepted_frames"), 0, 0, 2**63 - 1
        ),
        "persisted_frames": _bounded_int(
            summary.get("persisted_frames"), 0, 0, 2**63 - 1
        ),
        "l2_frames": max(
            l2_manifest_frames,
            _bounded_int(summary.get("l2_frames"), 0, 0, 2**63 - 1),
        ),
        "bbo_frames": bbo_frames,
        "queue_drops": queue_drops,
        "shard_count": _bounded_int(index.get("shard_count"), 0, 0, 2**63 - 1),
        "safe_count": _bounded_int(index.get("safe_count"), 0, 0, 2**63 - 1),
        "partial_count": _bounded_int(
            index.get("partial_count"), 0, 0, 2**63 - 1
        ),
        "reject_count": _bounded_int(index.get("reject_count"), 0, 0, 2**63 - 1),
        "compressed_bytes": compressed_bytes,
        "uncompressed_bytes": uncompressed_bytes,
        "uncompressed_size_coverage_complete": (
            manifest_count == uncompressed_exact_shards
        ),
        "basis": "published_bundle_manifests",
    }


def run_one_unit(
    ctx: AdapterContext,
    runner: Callable[..., Any] = subprocess.run,
) -> AdapterResult:
    """Run one bounded deterministic unit.

    Economic proof units first materialize the selected SAFE Dataset V2 shards,
    then run the economic campaign in the same GitHub-hosted job. This avoids
    relying on ephemeral runner state across continuations.
    """
    remaining = ctx.soft_deadline_epoch - time.time()
    if remaining <= 5:
        payload = {"status": "CONTINUATION_REQUIRED", "reason": "soft_deadline"}
        return AdapterResult(payload["status"], _digest(payload), payload, False)

    commands: list[tuple[list[str], Path | None, str]]
    if ctx.kind in ECONOMIC_KINDS:
        workspace = _workspace(ctx)
        commands = [
            (_materialize_command(ctx, workspace), workspace, "materialize_safe_v2"),
            (
                [
                    sys.executable,
                    str(ROOT / "tools" / "run_economic_objective_campaigns.py"),
                    "--root",
                    str(workspace),
                    "--no-start-collection",
                    "--analysis-stage",
                    _analysis_stage(ctx.kind) or str(ctx.kind).upper(),
                ],
                workspace,
                "economic_campaign",
            ),
        ]
        if ctx.kind == "module_pnl_proof":
            commands.append(
                (
                    [
                        sys.executable,
                        str(ROOT / "tools" / "audit_economic_objectives.py"),
                        "--root",
                        str(workspace),
                    ],
                    workspace,
                    "module_pnl_audit",
                )
            )
    else:
        try:
            cmd, output_root = build_command(ctx)
        except ValueError as exc:
            payload = {
                "status": "FAILED",
                "reason": "invalid_partition",
                "detail": str(exc),
            }
            return AdapterResult("FAILED", _digest(payload), payload, False)
        commands = [(cmd, output_root, "unit")]

    phases: list[dict[str, Any]] = []
    economic_proof_status: str | None = None
    for cmd, output_root, phase_name in commands:
        remaining = ctx.soft_deadline_epoch - time.time()
        if remaining <= 5:
            payload = {
                "status": "CONTINUATION_REQUIRED",
                "reason": "soft_deadline",
                "phases": phases,
            }
            return AdapterResult(
                "CONTINUATION_REQUIRED",
                _digest(payload),
                payload,
                bool(phases),
            )

        if output_root is not None:
            output_root.mkdir(parents=True, exist_ok=True)
        try:
            cp = _run(runner, cmd, timeout=max(1, int(remaining - 5)), analysis_stage=_analysis_stage(ctx.kind))
        except subprocess.TimeoutExpired:
            payload = {
                "status": "CONTINUATION_REQUIRED",
                "reason": "adapter_timeout",
                "phase": phase_name,
                "command": cmd[:4],
                "phases": phases,
            }
            return AdapterResult(
                "CONTINUATION_REQUIRED",
                _digest(payload),
                payload,
                bool(phases),
            )

        stdout = str(getattr(cp, "stdout", "") or "")[-8000:]
        stderr = str(getattr(cp, "stderr", "") or "")[-8000:]
        returncode = int(getattr(cp, "returncode", 1) or 0)
        phases.append(
            {
                "name": phase_name,
                "command": cmd[:4],
                "returncode": returncode,
                "stdout": stdout,
                "stderr": stderr,
                "analysis_stage": (
                    _analysis_stage(ctx.kind)
                ),
            }
        )

        if phase_name == "module_pnl_audit" and ctx.kind == "module_pnl_proof":
            economic_proof_status = _economic_proof_status(output_root or _workspace(ctx))
            if economic_proof_status is not None and returncode in {0, 2}:
                phases[-1]["semantic_status"] = economic_proof_status
                phases[-1]["certifying"] = economic_proof_status == "PASS"
                # Exit code 2 from audit_economic_objectives.py means the audit
                # was produced but mandatory economic evidence is not certifying.
                # That is a semantic verdict, not an orchestration crash.
                continue

        if returncode != 0:
            payload = _failure_payload(cmd, cp)
            combined = (stdout + "\n" + stderr).lower()
            if (
                ctx.kind in {"replay", "backtest", "module_pnl_proof"}
                and "no safe shards match the selection" in combined
            ):
                payload["status"] = "UNAVAILABLE"
                payload["reason"] = "no_safe_dataset_v2"
                payload["failure_category"] = "DATA_AVAILABILITY"
                payload["phase"] = phase_name
                payload["phases"] = phases
                return AdapterResult("UNAVAILABLE", _digest(payload), payload, False)
            if phase_name == "materialize_safe_v2":
                payload["reason"] = "dataset_materialization_failed"
            payload["phase"] = phase_name
            payload["phases"] = phases
            return AdapterResult("FAILED", _digest(payload), payload, False)

    if (
        ctx.kind == "replay"
        and ctx.partition.get("resume_proof") is True
        and int(ctx.partition.get("chunk_index") or 0) == 0
    ):
        plan_stdout = phases[-1]["stdout"] if phases else ""
        payload = {
            "status": "CONTINUATION_REQUIRED",
            "reason": "resume_proof_selection_checkpoint",
            "analysis_stage": "REPLAY",
            "selection_plan_sha256": hashlib.sha256(plan_stdout.encode()).hexdigest(),
            "phase": "dataset_selection_plan",
            "phases": phases,
            "resume_proof": True,
            "next_unit": 1,
        }
        return AdapterResult(
            "CONTINUATION_REQUIRED",
            _digest(payload),
            payload,
            True,
        )

    last_cmd, output_root, _ = commands[-1]
    collection_plan_sha256 = None
    if output_root is not None:
        digest_path = output_root / "collection_plan.sha256"
        if digest_path.is_file():
            collection_plan_sha256 = digest_path.read_text(
                encoding="utf-8"
            ).strip().split()[0]
    stdout = phases[-1]["stdout"] if phases else ""
    stderr = phases[-1]["stderr"] if phases else ""
    payload = {
        "status": "COMPLETE",
        "analysis_stage": (
            _analysis_stage(ctx.kind)
        ),
        "returncode": 0,
        "stdout": stdout,
        "stderr": stderr,
        "output_root": str(output_root) if output_root is not None else None,
        "collection_plan_sha256": collection_plan_sha256,
        "universe_discovery_required": ctx.kind == "market_collection",
        "safe_workspace": (
            str(output_root) if ctx.kind in ECONOMIC_KINDS and output_root is not None else None
        ),
        "bundle_root": (
            str(output_root)
            if ctx.kind in {
                "market_collection",
                "copy_vault_collection",
                "official_archive_collection",
                "event_intelligence_collection",
            }
            and output_root is not None
            else None
        ),
        "phases": phases,
    }
    if (
        ctx.kind in {
            "market_collection",
            "copy_vault_collection",
            "official_archive_collection",
            "event_intelligence_collection",
        }
        and output_root is not None
    ):
        payload["collection_metrics"] = _collection_checkpoint_metrics(output_root)
    if ctx.kind == "module_pnl_proof":
        payload["economic_proof_status"] = economic_proof_status
        payload["economic_proof_certifying"] = economic_proof_status == "PASS"
    return AdapterResult("COMPLETE", _digest(payload), payload, True)
