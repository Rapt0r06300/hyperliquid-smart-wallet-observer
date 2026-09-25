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


def build_command(ctx: AdapterContext) -> tuple[list[str], Path | None]:
    """Build one real bounded command for the requested campaign kind."""
    out = _output_root(ctx)
    version = str(ctx.partition.get("code_sha") or ctx.partition.get("collector_version") or "campaign")
    run_id = str(ctx.partition.get("collection_run_id") or f"{ctx.campaign_id}-{ctx.unit_id}")
    py = sys.executable

    if ctx.kind == "market_collection":
        duration = _bounded_float(ctx.partition.get("duration_s"), 600.0, 18_000.0)
        coins = str(ctx.partition.get("coins") or "BTC,ETH,SOL")
        return [
            py, str(ROOT / "tools" / "collect_cloud_window.py"),
            "--output", str(out),
            "--coins", coins,
            "--duration-s", str(duration),
            "--collector-version", version,
            "--collection-run-id", run_id,
            "--rotate-mb", str(_bounded_int(ctx.partition.get("rotate_mb"), 64, 1, 512)),
        ], out

    if ctx.kind == "copy_vault_collection":
        duration = _bounded_float(ctx.partition.get("duration_s"), 600.0, 18_000.0)
        cmd = [
            py, str(ROOT / "tools" / "collect_cloud_copy_vault.py"),
            "--output", str(out),
            "--duration-s", str(duration),
            "--collector-version", version,
            "--collection-run-id", run_id,
            "--max-vaults", str(_bounded_int(ctx.partition.get("max_vaults"), 20, 1, 100)),
            "--vault-shard-count", str(_bounded_int(ctx.partition.get("vault_shard_count"), 1, 1, 20)),
            "--vault-shard-index", str(_bounded_int(ctx.partition.get("vault_shard_index"), 0, 0, 19)),
            "--rotate-mb", str(_bounded_int(ctx.partition.get("rotate_mb"), 64, 1, 512)),
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
            py, str(ROOT / "tools" / "collect_official_archive_backfill.py"),
            "--venue", venue,
            "--coin", coin,
            "--symbol", symbol,
            "--start-date", start_date,
            "--end-date", str(ctx.partition.get("end_date") or start_date),
            "--output", str(out),
            "--collector-version", version,
            "--collection-run-id", run_id,
            "--max-days", str(_bounded_int(ctx.partition.get("max_days"), 1, 1, 3)),
            "--max-events-per-day", str(_bounded_int(ctx.partition.get("max_events_per_day"), 2_000_000, 1, 2_000_000)),
        ], out / "bundle"

    if ctx.kind == "event_intelligence_collection":
        return [
            py, str(ROOT / "tools" / "collect_event_intelligence_v2.py"),
            "--output", str(out),
            "--collector-version", version,
            "--collection-run-id", run_id,
        ], out

    workspace = Path(str(ctx.partition.get("workspace_root") or out / "workspace"))
    if ctx.kind == "replay":
        cmd = [
            py, "-m", "hl_observer.ops.v2_dataset_bridge", "materialize",
            "--output", str(workspace),
        ]
        for key, flag in (
            ("families", "--families"),
            ("venues", "--venues"),
            ("symbols", "--symbols"),
        ):
            value = ctx.partition.get(key)
            if value:
                cmd.extend([flag, str(value)])
        for key, flag in (
            ("start_ts_ms", "--start-ts-ms"),
            ("end_ts_ms", "--end-ts-ms"),
        ):
            value = ctx.partition.get(key)
            if value is not None:
                cmd.extend([flag, str(int(value))])
        return cmd, workspace

    if ctx.kind in {"backtest", "module_pnl_proof"}:
        marker = workspace / ".alina_campaign_materialized"
        if not marker.is_file():
            materialize = [
                py, "-m", "hl_observer.ops.v2_dataset_bridge", "materialize",
                "--output", str(workspace),
            ]
            return materialize, workspace
        return [
            py, str(ROOT / "tools" / "run_economic_objective_campaigns.py"),
            "--root", str(workspace),
            "--no-start-collection",
        ], workspace

    raise ValueError(f"unsupported campaign kind: {ctx.kind}")


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
        payload = {"status": "FAILED", "reason": "invalid_partition", "detail": str(exc)}
        return AdapterResult(payload["status"], _digest(payload), payload, False)

    if output_root is not None:
        output_root.mkdir(parents=True, exist_ok=True)
    timeout = max(1, int(remaining - 5))
    try:
        cp = runner(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            cwd=str(ROOT),
        )
    except subprocess.TimeoutExpired:
        payload = {
            "status": "CONTINUATION_REQUIRED",
            "reason": "adapter_timeout",
            "command": cmd[:3],
        }
        return AdapterResult(payload["status"], _digest(payload), payload, False)

    stdout = cp.stdout[-8000:]
    stderr = cp.stderr[-8000:]
    if cp.returncode == 0:
        if (
            ctx.kind in {"backtest", "module_pnl_proof"}
            and output_root is not None
            and "hl_observer.ops.v2_dataset_bridge" in cmd
            and "materialize" in cmd
        ):
            marker = Path(output_root) / ".alina_campaign_materialized"
            marker.write_text("SAFE_V2_MATERIALIZED\n", encoding="utf-8")
            payload = {
                "status": "CONTINUATION_REQUIRED",
                "reason": "safe_workspace_materialized",
                "returncode": 0,
                "stdout": stdout,
                "stderr": stderr,
                "output_root": str(output_root),
            }
            return AdapterResult(
                "CONTINUATION_REQUIRED",
                _digest(payload),
                payload,
                True,
            )
        payload = {
            "status": "COMPLETE",
            "returncode": 0,
            "stdout": stdout,
            "stderr": stderr,
            "output_root": str(output_root) if output_root is not None else None,
            "bundle_root": (
                str(output_root)
                if ctx.kind in {
                    "market_collection",
                    "copy_vault_collection",
                    "official_archive_collection",
                    "event_intelligence_collection",
                }
                else None
            ),
        }
        return AdapterResult("COMPLETE", _digest(payload), payload, True)

    category = "TEMPORARY_EXTERNAL" if any(
        token in (stdout + stderr).lower()
        for token in ("timeout", "temporar", "503", "502", "connection reset")
    ) else "QUALITY"
    payload = {
        "status": "FAILED",
        "reason": "adapter_failed",
        "failure_category": category,
        "returncode": cp.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }
    return AdapterResult("FAILED", _digest(payload), payload, False)