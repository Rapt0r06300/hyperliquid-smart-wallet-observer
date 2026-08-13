"""Run the three separate read-only/paper economic evidence campaigns."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting import copy_vault_executable, lead_lag_shadow  # noqa: E402
from hl_observer.ops.bounded_collection import start_bounded_collectors  # noqa: E402
from hl_observer.simulation.economic_campaigns import (  # noqa: E402
    REPORT_DIR,
    build_copy_campaign,
    build_cross_campaign,
    build_lead_lag_campaign,
    dataset_provenance,
    find_oldest_parameter_freeze,
    freeze_parameters,
    freeze_or_reuse_parameters,
    render_campaign_report,
    write_campaign,
)
from hl_observer.simulation.economic_family_scoreboard import export_scoreboards  # noqa: E402
from hl_observer.simulation.economic_collection_plan import (  # noqa: E402
    build_collection_plan,
    write_collection_plan,
)


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


def run_campaigns(
    root: Path,
    *,
    cross_budget_s: float = 20.0,
    cross_current_only: bool = False,
    lead_history_sources: int = lead_lag_shadow.DEFAULT_HISTORY_SOURCES,
    start_collection: bool = True,
    collection_duration_s: float = 24 * 60 * 60,
    collection_startup_wait_s: float = 3.0,
) -> dict[str, Any]:
    assert_execution_disabled()
    copy_tool = _tool("hypersmart_copy_pipeline", root / "tools" / "pipeline_copie_reel.py")
    cross_tool = _tool("hypersmart_cross_campaign", root / "tools" / "backtest_dislocation_2jambes.py")

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
        if copy_calibration.get("selection_eligible") is True:
            copy_freeze = freeze_parameters(
                root, "copy_vault", copy_parameters, copy_data
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
    )
    copy_segment_trades = copy_walk_forward.get("trades", {})
    copy_trades = [
        trade
        for name in ("train", "validation", "oos", "forward")
        for trade in copy_segment_trades.get(name, [])
    ] if isinstance(copy_segment_trades, dict) else []
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
        "summary": copy_walk_forward.get("combined_summary"),
        "temporal_evidence": copy_vault_executable.temporal_evidence(copy_walk_forward),
        "trades": copy_trades,
        "paper_read_only": True,
        "real_execution": False,
        "provisional_without_physical_freeze": copy_freeze is None,
    }
    copy_raw_path = _write_raw(root, "copy_vault", copy_raw)
    copy_campaign = build_copy_campaign(copy_raw, freeze=copy_freeze, datasets=copy_data)
    copy_campaign["evidence_paths"].append(copy_raw_path.relative_to(root).as_posix())
    write_campaign(root, copy_campaign)

    lead_sources = lead_lag_shadow.selectionner_sources(
        root,
        include_history=True,
        max_history_sources=max(0, int(lead_history_sources)),
    )
    lead_data = dataset_provenance(root, lead_sources)
    lead_params = {
        "seuil_choc_bps": lead_lag_shadow.SEUIL_CHOC_BPS,
        "frais_slippage_bps": lead_lag_shadow.FRAIS_SLIPPAGE_BPS,
        "horizons_ms": list(lead_lag_shadow.HORIZONS_MS),
        "economic_horizon_ms": lead_lag_shadow.CAMPAIGN_HORIZON_MS,
        "economic_notional_usd": lead_lag_shadow.CAMPAIGN_NOTIONAL_USD,
        "max_reference_lag_ms": lead_lag_shadow.CAMPAIGN_MAX_REFERENCE_LAG_MS,
        "max_exit_lag_ms": lead_lag_shadow.CAMPAIGN_MAX_EXIT_LAG_MS,
        "execution_model": lead_lag_shadow.CAMPAIGN_EXECUTION_MODEL,
        "minimum_shocks": lead_lag_shadow.MIN_CHOCS,
        "history_sources": len(lead_sources),
        "timestamp_clock": "ts_wall_ms_or_recv_wall_ts_ms;recu_ns_fallback",
    }
    lead_freeze = freeze_or_reuse_parameters(root, "lead_lag", lead_params, lead_data)
    lead_raw = lead_lag_shadow.backtest(
        root,
        sources=lead_sources,
        economic_frozen_at_ms=int(lead_freeze["frozen_at_ms"]),
        economic_horizon_ms=lead_lag_shadow.CAMPAIGN_HORIZON_MS,
        economic_notional_usd=lead_lag_shadow.CAMPAIGN_NOTIONAL_USD,
    )
    lead_raw_path = _write_raw(root, "lead_lag", lead_raw)
    lead_campaign = build_lead_lag_campaign(lead_raw, freeze=lead_freeze, datasets=lead_data)
    lead_campaign["evidence_paths"].append(lead_raw_path.relative_to(root).as_posix())
    write_campaign(root, lead_campaign)

    cross_data = dataset_provenance(
        root,
        (
            "runtime/data/carnet_venues.jsonl",
        ),
    )
    series, cross_depth, cross_meta = cross_tool.collecter_carnet_series(root)
    cross_meta["legacy_bbo_budget_s_unused"] = max(0.0, cross_budget_s)
    cross_meta["legacy_current_only_unused"] = bool(cross_current_only)
    cross_depth_meta = {
        "source": cross_meta.get("source"),
        "source_mode": cross_meta.get("source_mode"),
        "valid_snapshots": cross_meta.get("valid_snapshots"),
        "coins": cross_meta.get("coins"),
        "capacity_definition": "minimum USD capacity across HL/BIN bid/ask",
    }
    cross_protocol = cross_tool.walk_forward_protocol_signature()
    cross_freeze = find_oldest_parameter_freeze(
        root,
        "cross_venue_dislocation_v2",
        required_parameters=cross_protocol,
    )
    calibration = None
    if cross_freeze is None:
        calibration = cross_tool.calibrer_walk_forward(series, cross_depth)
        selection = calibration.get("selection") if isinstance(calibration, dict) else None
        selected = selection.get("selected") if isinstance(selection, dict) else None
        if not isinstance(selected, dict) or not isinstance(selected.get("parameters"), dict):
            selected_parameters = {
                "seuil_entree": cross_tool.SEUIL_ENTREE_BPS,
                "stop_bps": cross_tool.STOP_AGGRAVATION_BPS,
                "horizon_s": cross_tool.HORIZON_MAX_S,
                "min_executable_edge_bps": cross_tool.MIN_EXECUTABLE_EDGE_BPS,
            }
            selection_eligible = False
        else:
            selected_parameters = dict(selected["parameters"])
            selection_eligible = selected.get("eligible") is True
        cross_params = {
            **cross_protocol,
            "walk_forward_bounds": calibration.get("bounds"),
            "selected_strategy_parameters": selected_parameters,
            "training_selection_eligible": selection_eligible,
            "selection_status": calibration.get("status"),
            "seuil_sortie_bps": cross_tool.SEUIL_SORTIE_BPS,
            "fraicheur_max_ms": cross_tool.FRAICHEUR_MAX_MS,
            "latence_ms": cross_tool.LATENCE_MS,
            "fees_ar_bps": cross_tool.FEES_AR_BPS,
            "notional_usd": cross_tool.NOTIONAL_USD,
            "depth_freshness_ms": cross_tool.DEPTH_FRESHNESS_MS,
            "max_observation_gap_ms": cross_tool.MAX_OBSERVATION_GAP_MS,
            "source_mode": "ATOMIC_FOUR_SIDE_BOOK",
        }
        cross_freeze = freeze_parameters(
            root,
            "cross_venue_dislocation_v2",
            cross_params,
            cross_data,
        )
    else:
        cross_params = dict(cross_freeze["parameters"])

    cross_walk_forward = cross_tool.evaluer_walk_forward_gelé(
        series,
        cross_depth,
        frozen_parameters=cross_params,
        frozen_at_ms=float(cross_freeze["frozen_at_ms"]),
    )
    segment_trades = cross_walk_forward.get("trades", {})
    cross_trades = [
        trade
        for name in ("train", "validation", "oos", "forward")
        for trade in segment_trades.get(name, [])
    ] if isinstance(segment_trades, dict) else []
    cross_temporal = cross_tool.preuves_temporelles_walk_forward(cross_walk_forward)
    cross_hypothesis_audit = cross_tool.diagnostiquer_hypothese_walk_forward(
        cross_walk_forward
    )
    cross_raw = {
        "schema_version": "hypersmart.cross_venue_campaign.v2",
        "meta": cross_meta,
        "depth_meta": cross_depth_meta,
        "decision_diagnostics": cross_walk_forward.get("diagnostics"),
        "quotes_par_coin": {coin: len(values) for coin, values in series.items() if values},
        "params": cross_params,
        "calibration": calibration,
        "walk_forward": {
            key: value
            for key, value in cross_walk_forward.items()
            if key != "trades"
        },
        "verdict_realiste_16bps": cross_tool.juger(cross_trades),
        "temporal_evidence": cross_temporal,
        "hypothesis_audit": cross_hypothesis_audit,
        "trades": cross_trades,
        "paper_read_only": True,
        "real_execution": False,
    }
    cross_raw_path = _write_raw(root, "cross_venue_dislocation_v2", cross_raw)
    cross_campaign = build_cross_campaign(cross_raw, freeze=cross_freeze, datasets=cross_data)
    cross_campaign["evidence_paths"].append(cross_raw_path.relative_to(root).as_posix())
    write_campaign(root, cross_campaign)

    campaigns = [copy_campaign, lead_campaign, cross_campaign]
    scoreboards_path = export_scoreboards(root)
    markdown = render_campaign_report(campaigns)
    report_path = root / REPORT_DIR / "HYPERSMART_ECONOMIC_OBJECTIVE_CAMPAIGN.md"
    report_path.write_text(markdown, encoding="utf-8", newline="\n")

    raw_reports = {
        "copy_vault": copy_raw,
        "lead_lag": lead_raw,
        "cross_venue_dislocation_v2": cross_raw,
    }
    preliminary_plan = build_collection_plan(campaigns, raw_reports)
    collector_state = None
    if start_collection and any(row["objective_status"] != "ATTEINT" for row in campaigns):
        collector_state = start_bounded_collectors(
            root,
            preliminary_plan["required_collectors"],
            duration_s=collection_duration_s,
            startup_wait_s=collection_startup_wait_s,
        )
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
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--cross-budget-s", type=float, default=20.0)
    parser.add_argument("--cross-current-only", action="store_true")
    parser.add_argument(
        "--lead-history-sources",
        type=int,
        default=lead_lag_shadow.DEFAULT_HISTORY_SOURCES,
    )
    parser.add_argument("--no-start-collection", action="store_true")
    parser.add_argument("--collection-duration-s", type=float, default=24 * 60 * 60)
    parser.add_argument("--collection-startup-wait-s", type=float, default=3.0)
    args = parser.parse_args(argv)
    result = run_campaigns(
        Path(args.root).resolve(),
        cross_budget_s=args.cross_budget_s,
        cross_current_only=args.cross_current_only,
        lead_history_sources=args.lead_history_sources,
        start_collection=not args.no_start_collection,
        collection_duration_s=args.collection_duration_s,
        collection_startup_wait_s=args.collection_startup_wait_s,
    )
    for row in result["campaigns"]:
        net = row.get("net_pnl_usd")
        exact = "NON_MESURABLE" if net is None else f"{float(net):+.6f} USD"
        print(
            f"{row['family']}: OBJECTIF +4 USD {row['objective_status']} | net={exact}",
            flush=True,
        )
    print(f"report={result['report_path']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
