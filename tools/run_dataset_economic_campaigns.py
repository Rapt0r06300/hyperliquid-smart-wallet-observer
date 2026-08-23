"""FULL/COLD adapter around the canonical economic campaign runner.

The canonical economic strategies stay untouched. This wrapper is used only
for materialized dataset workspaces: it supplies deterministic multi-source
views for Copy-Vault/Cross-Venue, lets Lead-Lag consume its manifest sources,
and replaces canonical-only provenance with provenance of all original files.
No canonical module global is monkeypatched: run_campaigns executes with an
isolated copy of its globals containing the explicit adapters.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import FunctionType
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting.economic_vnext_pack import run_economic_vnext_pack  # noqa: E402
from hl_observer.backtesting.lead_lag_causal_diagnostics import (  # noqa: E402
    DIAGNOSTIC_SHOCK_THRESHOLD_BPS,
    diagnose_causal_book_coverage,
)
from hl_observer.datasets.economic_multi_source import (  # noqa: E402
    install_copy_vault_adapter,
    install_cross_venue_adapter,
    write_economic_source_coverage,
)
from hl_observer.datasets.source_discovery import (  # noqa: E402
    is_dataset_workspace,
    load_family_source_paths,
    write_family_source_manifest,
)


def _load_canonical_runner():
    path = ROOT / "tools" / "run_economic_objective_campaigns.py"
    spec = importlib.util.spec_from_file_location("hypersmart_canonical_economic_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load canonical economic runner: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _unique_paths(values: Iterable[Path]) -> list[Path]:
    return sorted(
        {Path(value).resolve() for value in values if Path(value).is_file()},
        key=lambda path: path.as_posix().casefold(),
    )


def _copy_original_sources(root: Path) -> list[Path]:
    copy = load_family_source_paths(root, "copy_vault")
    shared_books = [
        path
        for path in load_family_source_paths(root, "cross_venue")
        if path.name.casefold() == "carnet_venues.jsonl"
    ]
    return _unique_paths([*copy, *shared_books])


def _cross_original_sources(root: Path) -> list[Path]:
    return _unique_paths(load_family_source_paths(root, "cross_venue"))


def _looks_like_copy_provenance(paths: Iterable[str | Path]) -> bool:
    names = {Path(value).name.casefold() for value in paths}
    return bool(
        names
        & {
            "vault_fills.jsonl",
            "vault_fills_live.jsonl",
            "vault_episodes.jsonl",
            "vault_snapshots.jsonl",
            "copy_vault_l2_tape.jsonl",
        }
    )


def _looks_like_cross_provenance(paths: Iterable[str | Path]) -> bool:
    names = {Path(value).name.casefold() for value in paths}
    return names == {"carnet_venues.jsonl"}


def _isolated_run_campaigns(
    canonical,
    *,
    tool_loader,
    provenance_builder,
    overrides: dict[str, object] | None = None,
):
    """Clone the function globals instead of mutating the loaded module."""
    environment = dict(canonical.run_campaigns.__globals__)
    environment["_tool"] = tool_loader
    environment["dataset_provenance"] = provenance_builder
    for name, value in (overrides or {}).items():
        environment[name] = value
    isolated = FunctionType(
        canonical.run_campaigns.__code__,
        environment,
        name=canonical.run_campaigns.__name__,
        argdefs=canonical.run_campaigns.__defaults__,
        closure=canonical.run_campaigns.__closure__,
    )
    isolated.__kwdefaults__ = dict(canonical.run_campaigns.__kwdefaults__ or {})
    isolated.__annotations__ = dict(getattr(canonical.run_campaigns, "__annotations__", {}))
    return isolated


def _lead_lag_diagnostic_overrides(canonical) -> dict[str, object]:
    """Route every FULL/COLD Lead-Lag causal verdict through canonical v4.

    The canonical queue replay still detects/trades only its frozen 20-bps
    economic shocks. The 8-bps sample expands *diagnostic* event windows only.
    Crucially, campaign, replay and runner audit all consume the same v4
    classifier, including event-local counter deltas and loader-incomplete
    evidence. No alternative gap classifier remains active in this path.
    """

    original_detect = canonical.detect_rolling_shocks
    original_loader = canonical.load_market_microstructure_event_windows
    original_replay = canonical.replay_lead_lag_queue_maker
    state: dict[str, object] = {
        "diagnostic_shocks": [],
        "microstructure_meta": {},
    }

    def economic_detect_with_diagnostic_capture(trades, *args, **kwargs):
        economic = original_detect(trades, *args, **kwargs)
        diagnostic_kwargs = dict(kwargs)
        diagnostic_kwargs["threshold_bps"] = DIAGNOSTIC_SHOCK_THRESHOLD_BPS
        state["diagnostic_shocks"] = original_detect(trades, *args, **diagnostic_kwargs)
        return economic

    def loader_with_diagnostic_windows(root, event_ts_ms, **kwargs):
        economic_events = [int(value) for value in event_ts_ms]
        diagnostic_shocks = list(state.get("diagnostic_shocks") or [])
        diagnostic_events = [
            int(row["trigger_ts_ms"])
            for row in diagnostic_shocks
            if isinstance(row, dict) and row.get("trigger_ts_ms") is not None
        ]
        merged_events = sorted(set([*economic_events, *diagnostic_events]))
        books, trades, meta = original_loader(root, merged_events, **kwargs)
        meta = dict(meta)
        meta["economic_event_count_requested"] = len(economic_events)
        meta["diagnostic_event_count_8bps"] = len(diagnostic_events)
        meta["diagnostic_shock_threshold_bps"] = DIAGNOSTIC_SHOCK_THRESHOLD_BPS
        meta["diagnostic_only_expansion"] = True
        meta["economic_parameters_changed"] = False
        state["microstructure_meta"] = meta
        return books, trades, meta

    def canonical_causal_diagnostic(shocks, l2_history, **kwargs):
        max_delay = int(kwargs.get("max_book_delay_ms") or 750)
        return diagnose_causal_book_coverage(
            list(shocks),
            l2_history,
            dict(state.get("microstructure_meta") or {}),
            max_book_delay_ms=max_delay,
        )

    def replay_with_canonical_diagnostic(tape, l2_history, public_trade_history, **kwargs):
        replay = original_replay(tape, l2_history, public_trade_history, **kwargs)
        diagnostic_shocks = list(state.get("diagnostic_shocks") or [])
        replay = dict(replay)
        replay["causal_gap_diagnostic"] = canonical_causal_diagnostic(
            diagnostic_shocks,
            l2_history,
            max_book_delay_ms=int(
                (replay.get("parameters") or {}).get("max_book_delay_ms") or 750
            ),
        )
        replay["causal_gap_diagnostic"]["economic_shock_threshold_bps"] = (
            replay.get("parameters") or {}
        ).get("shock_threshold_bps")
        replay["causal_gap_diagnostic"]["economic_shocks_seen"] = replay.get(
            "strong_shocks_seen"
        )
        replay["causal_gap_diagnostic"]["diagnostic_shocks_seen"] = len(
            diagnostic_shocks
        )
        return replay

    return {
        "detect_rolling_shocks": economic_detect_with_diagnostic_capture,
        "load_market_microstructure_event_windows": loader_with_diagnostic_windows,
        "diagnose_causal_book_availability": canonical_causal_diagnostic,
        "replay_lead_lag_queue_maker": replay_with_canonical_diagnostic,
    }


def run_dataset_campaigns(
    data_root: Path,
    *,
    cross_budget_s: float = 20.0,
    cross_current_only: bool = False,
    lead_history_sources: int = 8,
    start_collection: bool = False,
    collection_duration_s: float = 24 * 60 * 60,
    collection_startup_wait_s: float = 3.0,
) -> dict[str, Any]:
    data_root = data_root.resolve()
    if not is_dataset_workspace(data_root):
        raise RuntimeError(
            "run_dataset_economic_campaigns exige un workspace FULL/COLD avec provenance."
        )
    if start_collection:
        raise RuntimeError("La collecte live est interdite dans un replay FULL/COLD.")

    write_family_source_manifest(data_root)
    canonical = _load_canonical_runner()
    canonical.assert_execution_disabled()

    copy_sources = _copy_original_sources(data_root)
    cross_sources = _cross_original_sources(data_root)
    lead_sources = _unique_paths(load_family_source_paths(data_root, "lead_lag"))

    original_tool_loader = canonical._tool
    adapter_state: dict[str, object] = {}

    def dataset_tool_loader(name: str, path: Path):
        tool = original_tool_loader(name, path)
        if name == "hypersmart_copy_pipeline":
            adapter_state["copy_vault"] = install_copy_vault_adapter(
                data_root,
                copy_tool=tool,
                copy_executable=canonical.copy_vault_executable,
            )
        elif name == "hypersmart_cross_campaign":
            adapter_state["cross_venue"] = install_cross_venue_adapter(
                data_root,
                cross_tool=tool,
            )
        return tool

    original_provenance = canonical.dataset_provenance

    def dataset_provenance(root_value, paths):
        values = list(paths)
        resolved = Path(root_value).resolve()
        if resolved == data_root and _looks_like_copy_provenance(values):
            return original_provenance(data_root, copy_sources)
        if resolved == data_root and _looks_like_cross_provenance(values):
            return original_provenance(data_root, cross_sources)
        return original_provenance(root_value, values)

    isolated_run = _isolated_run_campaigns(
        canonical,
        tool_loader=dataset_tool_loader,
        provenance_builder=dataset_provenance,
        overrides=_lead_lag_diagnostic_overrides(canonical),
    )
    result = isolated_run(
        data_root,
        cross_budget_s=cross_budget_s,
        cross_current_only=cross_current_only,
        lead_history_sources=lead_history_sources,
        start_collection=False,
        collection_duration_s=collection_duration_s,
        collection_startup_wait_s=collection_startup_wait_s,
    )
    # Strong postcondition: the canonical loaded module was never changed.
    if canonical._tool is not original_tool_loader or canonical.dataset_provenance is not original_provenance:
        raise RuntimeError("canonical economic runner globals changed unexpectedly")

    coverage_json, coverage_md, coverage = write_economic_source_coverage(
        data_root,
        copy_consumed=copy_sources,
        lead_consumed=lead_sources,
        cross_consumed=cross_sources,
    )
    # vNext research is intentionally downstream of the canonical campaign.
    # It can only propose a later freeze and cannot alter the just-computed
    # canonical verdicts or scoreboards.
    vnext_research = run_economic_vnext_pack(data_root, lead_sources=lead_sources)
    result["dataset_adapters"] = adapter_state
    result["source_coverage"] = coverage
    result["source_coverage_json"] = str(coverage_json)
    result["source_coverage_markdown"] = str(coverage_md)
    result["source_release_id"] = 371149058
    result["vnext_research"] = vnext_research
    result["paper_read_only"] = True
    result["real_execution"] = False
    result["canonical_globals_mutated"] = False
    result["lead_lag_diagnostic_threshold_bps"] = DIAGNOSTIC_SHOCK_THRESHOLD_BPS
    result["lead_lag_economic_parameters_changed"] = False
    result["lead_lag_causal_diagnostic_schema"] = "hypersmart.lead_lag_causal_book_coverage.v4"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Workspace FULL/COLD reconstruit.")
    parser.add_argument("--cross-budget-s", type=float, default=20.0)
    parser.add_argument("--cross-current-only", action="store_true")
    parser.add_argument("--lead-history-sources", type=int, default=8)
    parser.add_argument("--no-start-collection", action="store_true")
    parser.add_argument("--collection-duration-s", type=float, default=24 * 60 * 60)
    parser.add_argument("--collection-startup-wait-s", type=float, default=3.0)
    args = parser.parse_args(argv)
    if not args.no_start_collection:
        print("DATASET_ECONOMIC_NO_GO: --no-start-collection est obligatoire.")
        return 2
    try:
        result = run_dataset_campaigns(
            Path(args.root),
            cross_budget_s=args.cross_budget_s,
            cross_current_only=args.cross_current_only,
            lead_history_sources=args.lead_history_sources,
            start_collection=False,
            collection_duration_s=args.collection_duration_s,
            collection_startup_wait_s=args.collection_startup_wait_s,
        )
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"DATASET_ECONOMIC_NO_GO: {exc}")
        return 2
    for row in result.get("campaigns", []):
        net = row.get("net_pnl_usd")
        exact = "NON_MESURABLE" if net is None else f"{float(net):+.6f} USD"
        print(
            f"{row['family']}: OBJECTIF +4 USD {row['objective_status']} | net={exact}",
            flush=True,
        )
    coverage = result.get("source_coverage") or {}
    print(f"source_coverage_all_full={coverage.get('all_families_full')}", flush=True)
    print(f"vnext_summary={((result.get('vnext_research') or {}).get('summary_path'))}", flush=True)
    print(f"report={result.get('report_path')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
