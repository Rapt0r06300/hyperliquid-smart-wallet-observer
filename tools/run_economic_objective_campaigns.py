"""Run the active Copy-Vault read-only/paper economic evidence campaign."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting import copy_vault_executable  # noqa: E402
from hl_observer.backtesting.copy_vault_generalization import (  # noqa: E402
    derive_heldout_vault_generalization,
)
from hl_observer.backtesting.copy_vault_v4_train import (  # noqa: E402
    explore_copy_vault_v4_train,
)
from hl_observer.backtesting.copy_vault_v5_lifecycle_train import (  # noqa: E402
    explore_copy_vault_v5_train,
)
from hl_observer.backtesting.copy_vault_v6_balanced_train import (  # noqa: E402
    explore_copy_vault_v6_balanced_train,
)
from hl_observer.backtesting.copy_vault_v7_exit_flow_train import (  # noqa: E402
    explore_copy_vault_v7_exit_flow_train,
)
from hl_observer.backtesting.copy_vault_v8_entry_efficiency_train import (  # noqa: E402
    explore_copy_vault_v8_entry_efficiency_train,
)
from hl_observer.backtesting.copy_vault_v9_online_leader_quality_train import (  # noqa: E402
    explore_copy_vault_v9_online_leader_quality_train,
)
from hl_observer.backtesting.economic_hypotheses_v3 import (  # noqa: E402
    qualify_copy_vault_train_only,
)
from hl_observer.datasets.source_discovery import (  # noqa: E402
    is_dataset_workspace,
    source_manifest_summary,
    write_family_source_manifest,
)
from hl_observer.economics.assumptions import EconomicRunMode  # noqa: E402
from hl_observer.ops.bounded_collection import inspect_bounded_collectors  # noqa: E402
from hl_observer.simulation.economic_campaigns import (  # noqa: E402
    REPORT_DIR,
    build_copy_campaign,
    dataset_provenance,
    find_oldest_parameter_freeze,
    freeze_train_selected_parameters,
    render_campaign_report,
    write_campaign,
)
from hl_observer.simulation.economic_collection_plan import (  # noqa: E402
    build_collection_plan,
    write_collection_plan,
)
from hl_observer.simulation.economic_family_scoreboard import export_scoreboards  # noqa: E402
from hl_observer.strategies.active_scope import active_strategy_families  # noqa: E402


def _tool(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load tool: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _enabled(name: str) -> bool:
    return os.environ.get(name, "0").strip().lower() in {"1", "true", "yes", "on", "oui"}


def assert_execution_disabled() -> None:
    active = [
        name
        for name in ("HL_ENABLE_MAINNET_EXECUTION", "HL_ENABLE_TESTNET_EXECUTION")
        if _enabled(name)
    ]
    if active:
        raise RuntimeError("economic campaigns require execution disabled: " + ", ".join(active))


def _write_raw(root: Path, name: str, payload: dict[str, Any]) -> Path:
    target = root / REPORT_DIR / "raw" / f"{name}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)
    return target


def _stable_json_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _environment_provenance(root: Path) -> dict[str, Any]:
    dependency_files = []
    for pattern in ("requirements*.txt", "pyproject.toml", "poetry.lock", "uv.lock"):
        dependency_files.extend(sorted(root.glob(pattern)))
    dependency_digest = _stable_json_sha256({
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in dependency_files
        if path.is_file()
    })
    return {
        "os": platform.platform(),
        "runner_architecture": platform.machine(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "timezone": os.environ.get("TZ") or time.tzname[0],
        "dependency_files": [str(path.relative_to(root)) for path in dependency_files if path.is_file()],
        "dependency_digest": dependency_digest,
        "github_runner_image": os.environ.get("ImageOS") or os.environ.get("RUNNER_OS"),
    }


def _microstructure_source_paths(metadata: object) -> list[str]:
    """Extract only local paths actually inspected by the L2/trade loader."""

    if not isinstance(metadata, dict):
        return []
    rows = [metadata]
    nested = metadata.get("source_metadata")
    if isinstance(nested, list):
        rows.extend(item for item in nested if isinstance(item, dict))
    return list(
        dict.fromkeys(
            str(path)
            for row in rows
            for path in (row.get("sources") or [])
            if isinstance(path, str) and path.strip()
        )
    )


def _lead_trade_window_ms(
    tape: dict[str, dict[str, list]],
    *,
    coin: str = "ETH",
    trailing_padding_ms: int = 10_000,
) -> tuple[int | None, int | None]:
    """Bound execution evidence to the same causal wall-clock range as lead trades."""

    timestamps_ms = [
        int(float(row[0])) // 1_000_000
        for row in (tape.get(str(coin).upper()) or {}).get("TRADE", ())
        if isinstance(row, (list, tuple)) and row and float(row[0]) > 0
    ]
    if not timestamps_ms:
        return None, None
    return min(timestamps_ms), max(timestamps_ms) + max(0, int(trailing_padding_ms))


def _finalize_campaign_run(
    root: Path,
    *,
    campaigns: list[dict[str, Any]],
    raw_reports: dict[str, dict[str, Any]],
    analysis_stage: str,
    dataset_mode: bool,
    dataset_manifest_path: Path | None,
    dataset_sources: dict[str, object] | None,
    environment_provenance: dict[str, Any],
) -> dict[str, Any]:
    for campaign in campaigns:
        campaign["analysis_stage"] = analysis_stage
        campaign["analysis_stage_contract"] = {
            "stage": analysis_stage,
            "paper_read_only": True,
            "real_execution": False,
            "input_selection": {
                "dataset_workspace": dataset_mode,
                "dataset_source_manifest": (
                    str(dataset_manifest_path) if dataset_manifest_path is not None else None
                ),
            },
        }
    scoreboards_path = export_scoreboards(root)
    report_path = root / REPORT_DIR / "HYPERSMART_ECONOMIC_OBJECTIVE_CAMPAIGN.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_campaign_report(campaigns), encoding="utf-8", newline="\n")

    stage_receipt = {
        "schema": "alina.analysis_stage_artifact.v1",
        "analysis_stage": analysis_stage,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
        "active_families": sorted(active_strategy_families()),
        "input_selection": {
            "dataset_workspace": dataset_mode,
            "dataset_source_manifest": (
                str(dataset_manifest_path) if dataset_manifest_path is not None else None
            ),
            "source_summary": dataset_sources,
        },
        "environment_provenance": environment_provenance,
        "campaigns": [
            {
                "family": row.get("family"),
                "analysis_stage": row.get("analysis_stage"),
                "objective_status": row.get("objective_status"),
                "daily_evidence": row.get("daily_evidence"),
            }
            for row in campaigns
        ],
        "scoreboard_artifact": str(scoreboards_path),
        "report_artifact": str(report_path),
    }
    stage_receipt_path = (
        root / "runtime" / "reports" / "analysis_stages" / f"{analysis_stage.lower()}.json"
    )
    stage_receipt_path.parent.mkdir(parents=True, exist_ok=True)
    stage_receipt["artifact_digest"] = _stable_json_sha256(stage_receipt)
    stage_receipt_path.write_text(
        json.dumps(stage_receipt, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    collector_state = inspect_bounded_collectors(root)
    collection_plan = build_collection_plan(
        campaigns,
        raw_reports,
        collector_state=collector_state,
    )
    collection_path, collection_report_path = write_collection_plan(root, collection_plan)
    return {
        "campaigns": campaigns,
        "report_path": str(report_path),
        "scoreboards_path": str(scoreboards_path),
        "collector_state": collector_state,
        "collection_plan_path": str(collection_path),
        "collection_plan_report_path": str(collection_report_path),
        "dataset_workspace": dataset_mode,
        "dataset_source_manifest": (
            str(dataset_manifest_path) if dataset_manifest_path is not None else None
        ),
        "dataset_source_summary": dataset_sources,
        "active_families": sorted(active_strategy_families()),
        "disabled_families": sorted(
            {"lead_lag", "cross_venue_dislocation_v2"} - active_strategy_families()
        ),
        "paper_read_only": True,
        "real_execution": False,
    }


def run_campaigns(
    root: Path,
    *,
    cross_budget_s: float = 20.0,
    cross_current_only: bool = False,
    lead_history_sources: int = 8,
    start_collection: bool = False,
    collection_duration_s: float = 24 * 60 * 60,
    collection_startup_wait_s: float = 3.0,
    analysis_stage: str | None = None,
) -> dict[str, Any]:
    assert_execution_disabled()
    active_families = active_strategy_families()
    if active_families != frozenset({"copy_vault"}):
        raise RuntimeError(
            "canonical economic campaign runner requires Copy-Vault-only active scope"
        )
    if start_collection:
        raise RuntimeError(
            "ANALYZE cannot start collectors; run COLLECT first, freeze the cutoff, then analyze"
        )
    environment_provenance = _environment_provenance(root)
    analysis_stage = str(analysis_stage or os.environ.get("ALINA_ANALYSIS_STAGE") or "BACKTEST").upper()
    allowed_stages = {"BACKTEST", "OOS", "FORWARD_PAPER", "PNL_PROOF", "SCOREBOARD"}
    if analysis_stage not in allowed_stages:
        raise ValueError(f"unsupported analysis stage: {analysis_stage}")
    dataset_mode = is_dataset_workspace(root)
    dataset_manifest_path = None
    dataset_sources: dict[str, object] | None = None
    if dataset_mode:
        dataset_manifest_path = write_family_source_manifest(root)
        dataset_sources = source_manifest_summary(root)

    # The data root may be an isolated materialized Dataset V2 workspace. Tool
    # modules belong to the checked-out Alina code repository, not to that data
    # workspace. Loading them from `root/tools` made GitHub-hosted backtest/OOS
    # campaigns fail with FileNotFoundError after materialization.
    copy_tool = _tool("hypersmart_copy_pipeline", ROOT / "tools" / "pipeline_copie_reel.py")

    copy_data = dataset_provenance(
        root,
        (
            "runtime/data/vault_fills.jsonl",
            "runtime/data/vault_fills_live.jsonl",
            "runtime/data/vault_episodes.jsonl",
            "runtime/data/vault_snapshots.jsonl",
            "runtime/data/carnet_venues.jsonl",
            "runtime/data/copy_vault_l2_tape.jsonl",
        ),
    )
    copy_entries, canonical_input_audit = copy_tool.charger_entrees_alpha_avec_audit(root)
    all_copy_metaorders, all_metaorder_audit = copy_vault_executable.cluster_metaorders(
        copy_entries
    )
    all_copy_books, copy_book_meta = copy_vault_executable.load_observed_books(
        root, coins={row["coin"] for row in all_copy_metaorders}
    )
    copy_metaorders, copy_books, copy_protocol_audit = (
        copy_vault_executable.select_causal_protocol_inputs(
            all_copy_metaorders, all_copy_books
        )
    )
    copy_v4_entries, copy_v4_input_audit = (
        copy_tool.charger_entrees_alpha_notional_fixe_avec_audit(root)
    )
    copy_v4_all_metaorders, copy_v4_metaorder_audit = (
        copy_vault_executable.cluster_metaorders(copy_v4_entries)
    )
    copy_v4_all_books, copy_v4_book_meta = copy_vault_executable.load_observed_books(
        root, coins={row["coin"] for row in copy_v4_all_metaorders}
    )
    copy_v4_metaorders, copy_v4_books, copy_v4_protocol_audit = (
        copy_vault_executable.select_causal_protocol_inputs(
            copy_v4_all_metaorders, copy_v4_all_books
        )
    )
    copy_v4 = explore_copy_vault_v4_train(
        copy_v4_metaorders,
        copy_v4_books,
        input_audit={
            "canonical_input": copy_v4_input_audit,
            "metaorders": copy_v4_metaorder_audit,
            "books": copy_v4_book_meta,
            "causal_protocol": copy_v4_protocol_audit,
        },
    )
    copy_lifecycle_events, copy_lifecycle_audit = (
        copy_tool.charger_evenements_lifecycle_avec_audit(root)
    )
    copy_v5 = explore_copy_vault_v5_train(
        copy_v4_metaorders,
        copy_v4_books,
        copy_lifecycle_events,
        input_audit={
            "canonical_input": copy_v4_input_audit,
            "metaorders": copy_v4_metaorder_audit,
            "books": copy_v4_book_meta,
            "causal_protocol": copy_v4_protocol_audit,
            "lifecycle": copy_lifecycle_audit,
        },
    )
    copy_v6 = explore_copy_vault_v6_balanced_train(
        copy_v4_metaorders,
        copy_v4_books,
        copy_lifecycle_events,
        input_audit={
            "canonical_input": copy_v4_input_audit,
            "metaorders": copy_v4_metaorder_audit,
            "books": copy_v4_book_meta,
            "causal_protocol": copy_v4_protocol_audit,
            "lifecycle": copy_lifecycle_audit,
        },
    )
    copy_v7 = explore_copy_vault_v7_exit_flow_train(
        copy_lifecycle_events,
        copy_v4_books,
        input_audit={
            "books": copy_v4_book_meta,
            "causal_protocol": copy_v4_protocol_audit,
            "lifecycle": copy_lifecycle_audit,
        },
    )
    copy_v8 = explore_copy_vault_v8_entry_efficiency_train(
        copy_v4_metaorders,
        copy_v4_books,
        copy_lifecycle_events,
        input_audit={
            "canonical_input": copy_v4_input_audit,
            "metaorders": copy_v4_metaorder_audit,
            "books": copy_v4_book_meta,
            "causal_protocol": copy_v4_protocol_audit,
            "lifecycle": copy_lifecycle_audit,
        },
    )
    copy_v9 = explore_copy_vault_v9_online_leader_quality_train(
        copy_v4_metaorders,
        copy_v4_books,
        copy_lifecycle_events,
        input_audit={
            "canonical_input": copy_v4_input_audit,
            "metaorders": copy_v4_metaorder_audit,
            "books": copy_v4_book_meta,
            "causal_protocol": copy_v4_protocol_audit,
            "lifecycle": copy_lifecycle_audit,
        },
    )
    metaorder_audit = {
        **all_metaorder_audit,
        "all_metaorders": int(all_metaorder_audit.get("metaorders") or 0),
        "metaorders": len(copy_metaorders),
        "historical_or_noncausal_metaorders_excluded": copy_protocol_audit[
            "historical_or_noncausal_metaorders_excluded"
        ],
        "protocol_scope": copy_protocol_audit["protocol_scope"],
    }
    copy_book_meta = {
        **copy_book_meta,
        "protocol_valid_rows": copy_protocol_audit["causal_protocol_book_rows"],
        "protocol_coins": copy_protocol_audit["causal_protocol_coins"],
        "historical_or_noncausal_rows_excluded": copy_protocol_audit[
            "historical_or_noncausal_book_rows_excluded"
        ],
    }
    copy_protocol = copy_vault_executable.protocol_signature()
    copy_freeze = find_oldest_parameter_freeze(
        root, "copy_vault", required_parameters=copy_protocol
    )
    copy_calibration = None
    if copy_freeze is None:
        copy_calibration = copy_vault_executable.calibrate_train_only(
            copy_metaorders, copy_books, require_causal_observation=True
        )
        copy_parameters = {
            **copy_protocol,
            "walk_forward_bounds": copy_calibration.get("bounds"),
            "selected_horizon_ms": copy_calibration.get("selected_horizon_ms"),
            "training_selection_eligible": copy_calibration.get("selection_eligible") is True,
            "selection_status": copy_calibration.get("status"),
        }
        copy_freeze = freeze_train_selected_parameters(
            root,
            "copy_vault",
            copy_parameters,
            copy_data,
            selection_eligible=copy_calibration.get("selection_eligible") is True,
        )
    else:
        copy_parameters = dict(copy_freeze["parameters"])
    provisional_cutoff_ms = max(
        (int(row["signal_ts_ms"]) for row in copy_metaorders), default=0
    )
    copy_walk_forward = copy_vault_executable.evaluate_frozen(
        copy_metaorders,
        copy_books,
        frozen_parameters=copy_parameters,
        frozen_at_ms=(
            int(copy_freeze["frozen_at_ms"]) if copy_freeze is not None
            else provisional_cutoff_ms
        ),
        economic_mode=EconomicRunMode.CERTIFIABLE,
    )
    copy_segment_trades = copy_walk_forward.get("trades", {})
    copy_trades = [
        {**trade, "walk_forward_segment": name}
        for name in ("train", "validation", "oos", "forward")
        for trade in copy_segment_trades.get(name, [])
    ] if isinstance(copy_segment_trades, dict) else []
    copy_bounds = copy_walk_forward.get("bounds") if isinstance(copy_walk_forward, dict) else {}
    copy_generalization = derive_heldout_vault_generalization(
        copy_trades,
        oos_start_ms=(copy_bounds or {}).get("oos_start_ms") if isinstance(copy_bounds, dict) else None,
    )
    copy_raw = {
        "schema_version": "hypersmart.copy_vault_executable_campaign.v1",
        "canonical_input_audit": canonical_input_audit,
        "metaorder_audit": metaorder_audit,
        "book_meta": copy_book_meta,
        "causal_protocol_audit": copy_protocol_audit,
        "params": copy_parameters,
        "calibration": copy_calibration,
        "walk_forward": {
            key: value for key, value in copy_walk_forward.items() if key != "trades"
        },
        "economic_contract": copy_walk_forward.get("economic_contract"),
        "assumption_snapshot_hash": copy_walk_forward.get(
            "assumption_snapshot_hash"
        ),
        "summary": copy_walk_forward.get("combined_summary"),
        "temporal_evidence": copy_vault_executable.temporal_evidence(copy_walk_forward),
        "vault_generalization": copy_generalization,
        "trades": copy_trades,
        "paper_read_only": True,
        "real_execution": False,
        "provisional_without_physical_freeze": copy_freeze is None,
        "dataset_workspace": dataset_mode,
        "dataset_source_summary": dataset_sources,
        "analysis_stage": analysis_stage,
        "analysis_stage_contract": {
            "stage": analysis_stage,
            "paper_read_only": True,
            "real_execution": False,
        },
    }
    copy_raw["next_hypothesis_v3"] = qualify_copy_vault_train_only(copy_trades)
    copy_raw["next_hypothesis_v4"] = copy_v4
    copy_raw["next_hypothesis_v5"] = copy_v5
    copy_raw["next_hypothesis_v6"] = copy_v6
    copy_raw["next_hypothesis_v7"] = copy_v7
    copy_raw["next_hypothesis_v8"] = copy_v8
    copy_raw["next_hypothesis_v9"] = copy_v9
    copy_raw_path = _write_raw(root, "copy_vault", copy_raw)
    copy_campaign = build_copy_campaign(
        copy_raw, freeze=copy_freeze, datasets=copy_data, require_daily=True
    )
    copy_campaign["evidence_paths"].append(copy_raw_path.relative_to(root).as_posix())
    write_campaign(root, copy_campaign)

    return _finalize_campaign_run(
        root,
        campaigns=[copy_campaign],
        raw_reports={"copy_vault": copy_raw},
        analysis_stage=analysis_stage,
        dataset_mode=dataset_mode,
        dataset_manifest_path=dataset_manifest_path,
        dataset_sources=dataset_sources,
        environment_provenance=environment_provenance,
    )

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    # Keep legacy flags parseable for existing automation, but do not advertise
    # non-Copy-Vault controls in the canonical runner's public help.
    parser.add_argument("--cross-budget-s", type=float, default=20.0, help=argparse.SUPPRESS)
    parser.add_argument("--cross-current-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--lead-history-sources",
        type=int,
        default=8,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--no-start-collection", action="store_true")
    parser.add_argument("--collection-duration-s", type=float, default=24 * 60 * 60)
    parser.add_argument("--collection-startup-wait-s", type=float, default=3.0)
    parser.add_argument(
        "--analysis-stage",
        choices=["BACKTEST", "OOS", "FORWARD_PAPER", "PNL_PROOF", "SCOREBOARD"],
        default=None,
    )
    args = parser.parse_args(argv)
    result = run_campaigns(
        Path(args.root).resolve(),
        cross_budget_s=args.cross_budget_s,
        cross_current_only=args.cross_current_only,
        lead_history_sources=args.lead_history_sources,
        start_collection=False,
        collection_duration_s=args.collection_duration_s,
        collection_startup_wait_s=args.collection_startup_wait_s,
        analysis_stage=args.analysis_stage,
    )
    for row in result["campaigns"]:
        net = row.get("net_pnl_usd")
        exact = "NON_MESURABLE" if net is None else f"{float(net):+.6f} USD"
        daily = row.get("daily_evidence")
        daily = daily if isinstance(daily, dict) else {}
        print(
            f"{row['family']}: RESULTAT PAPER net={exact} "
            f"| daily_mean={daily.get('mean_daily_net_pnl_usd')} "
            f"| daily_min={daily.get('min_daily_net_pnl_usd')} "
            f"| objectif_fixe_non_bloquant={row.get('objective_status')}",
            flush=True,
        )
    print(f"report={result['report_path']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
