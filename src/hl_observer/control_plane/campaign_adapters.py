"""Deterministic bounded adapters for resumable GitHub-hosted campaigns."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[3]
ECONOMIC_KINDS = frozenset({"backtest", "module_pnl_proof"})


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
    ):
        value = ctx.partition.get(key)
        if value is not None:
            args.extend([flag, str(int(value))])
    return args


def _materialize_command(ctx: AdapterContext, workspace: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "hl_observer.ops.v2_dataset_bridge",
        "materialize",
        "--output",
        str(workspace),
        *_selection_args(ctx),
    ]


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
            "--duration-s",
            str(duration),
            "--collector-version",
            version,
            "--collection-run-id",
            run_id,
            "--rotate-mb",
            str(_bounded_int(ctx.partition.get("rotate_mb"), 64, 1, 512)),
        ], out

    if ctx.kind == "copy_vault_collection":
        duration = _bounded_float(ctx.partition.get("duration_s"), 3600.0, 18_000.0)
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
            str(_bounded_int(ctx.partition.get("max_vaults"), 20, 1, 100)),
            "--vault-shard-count",
            str(_bounded_int(ctx.partition.get("vault_shard_count"), 1, 1, 20)),
            "--vault-shard-index",
            str(_bounded_int(ctx.partition.get("vault_shard_index"), 0, 0, 19)),
            "--rotate-mb",
            str(_bounded_int(ctx.partition.get("rotate_mb"), 64, 1, 512)),
        ]
        selection = ctx.partition.get("selection_file")
        if selection:
            cmd.extend(["--selection-file", str(selection)])
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
        return _materialize_command(ctx, workspace), workspace

    if ctx.kind in ECONOMIC_KINDS:
        return [
            py,
            str(ROOT / "tools" / "run_economic_objective_campaigns.py"),
            "--root",
            str(workspace),
            "--no-start-collection",
        ], workspace

    raise ValueError(f"unsupported campaign kind: {ctx.kind}")


def _run(
    runner: Callable[..., Any],
    cmd: list[str],
    *,
    timeout: int,
) -> Any:
    return runner(
        cmd,
        capture_output=True,
        text=True,
        timeout=max(1, int(timeout)),
        check=False,
        cwd=str(ROOT),
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


def run_one_unit(
    ctx: AdapterContext,
    runner: Callable[..., Any] = subprocess.run,
) -> AdapterResult:
    remaining = ctx.soft_deadline_epoch - time.time()
    if remaining <= 5:
        payload = {"status": "CONTINUATION_REQUIRED", "reason": "soft_deadline"}
        return AdapterResult(payload["status"], _digest(payload), payload, False)

    try:
        cmd, output_root = build_command(ctx)
    except ValueError as exc:
        payload = {
            "status": "FAILED",
            "reason": "invalid_partition",
            "failure_category": "QUALITY",
            "detail": str(exc),
        }
        return AdapterResult(payload["status"], _digest(payload), payload, False)

    if output_root is not None:
        output_root.mkdir(parents=True, exist_ok=True)

    materialize_payload: dict[str, Any] | None = None
    if ctx.kind in ECONOMIC_KINDS:
        workspace = _workspace(ctx)
        materialize_cmd = _materialize_command(ctx, workspace)
        materialize_timeout = max(
            60,
            min(7200, int(max(60.0, remaining * 0.45))),
        )
        try:
            materialized = _run(
                runner,
                materialize_cmd,
                timeout=materialize_timeout,
            )
        except subprocess.TimeoutExpired:
            payload = {
                "status": "CONTINUATION_REQUIRED",
                "reason": "dataset_materialization_timeout",
                "command": materialize_cmd[:4],
            }
            return AdapterResult(payload["status"], _digest(payload), payload, False)
        if materialized.returncode != 0:
            payload = _failure_payload(materialize_cmd, materialized)
            payload["reason"] = "dataset_materialization_failed"
            return AdapterResult("FAILED", _digest(payload), payload, False)
        materialize_payload = {
            "returncode": 0,
            "stdout": str(materialized.stdout or "")[-8000:],
            "stderr": str(materialized.stderr or "")[-8000:],
        }
        remaining = ctx.soft_deadline_epoch - time.time()
        if remaining <= 10:
            payload = {
                "status": "CONTINUATION_REQUIRED",
                "reason": "soft_deadline_after_materialization",
                "materialization": materialize_payload,
            }
            return AdapterResult(payload["status"], _digest(payload), payload, False)

    timeout = max(1, int(ctx.soft_deadline_epoch - time.time() - 5))
    try:
        cp = _run(runner, cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        payload = {
            "status": "CONTINUATION_REQUIRED",
            "reason": "adapter_timeout",
            "command": cmd[:4],
        }
        return AdapterResult(payload["status"], _digest(payload), payload, False)

    if cp.returncode != 0:
        payload = _failure_payload(cmd, cp)
        return AdapterResult("FAILED", _digest(payload), payload, False)

    payload = {
        "status": "COMPLETE",
        "returncode": 0,
        "stdout": str(cp.stdout or "")[-8000:],
        "stderr": str(cp.stderr or "")[-8000:],
        "output_root": str(output_root) if output_root is not None else None,
        "bundle_root": (
            str(output_root)
            if ctx.kind
            in {
                "market_collection",
                "copy_vault_collection",
                "official_archive_collection",
                "event_intelligence_collection",
            }
            else None
        ),
    }
    if materialize_payload is not None:
        payload["materialization"] = materialize_payload
        payload["safe_workspace"] = str(_workspace(ctx))
    return AdapterResult("COMPLETE", _digest(payload), payload, True)
