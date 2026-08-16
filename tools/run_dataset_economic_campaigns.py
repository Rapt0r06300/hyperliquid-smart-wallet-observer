"""FULL/COLD adapter around the canonical economic campaign runner.

The canonical economic strategies stay untouched.  This wrapper is used only
for materialized dataset workspaces: it installs deterministic multi-source
views for Copy-Vault/Cross-Venue, lets Lead-Lag consume its manifest sources,
and replaces canonical-only provenance with provenance of all original files.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

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

    canonical._tool = dataset_tool_loader

    original_provenance = canonical.dataset_provenance

    def dataset_provenance(root_value, paths):
        values = list(paths)
        resolved = Path(root_value).resolve()
        if resolved == data_root and _looks_like_copy_provenance(values):
            return original_provenance(data_root, copy_sources)
        if resolved == data_root and _looks_like_cross_provenance(values):
            return original_provenance(data_root, cross_sources)
        return original_provenance(root_value, values)

    canonical.dataset_provenance = dataset_provenance

    result = canonical.run_campaigns(
        data_root,
        cross_budget_s=cross_budget_s,
        cross_current_only=cross_current_only,
        lead_history_sources=lead_history_sources,
        start_collection=False,
        collection_duration_s=collection_duration_s,
        collection_startup_wait_s=collection_startup_wait_s,
    )
    coverage_json, coverage_md, coverage = write_economic_source_coverage(
        data_root,
        copy_consumed=copy_sources,
        lead_consumed=lead_sources,
        cross_consumed=cross_sources,
    )
    result["dataset_adapters"] = adapter_state
    result["source_coverage"] = coverage
    result["source_coverage_json"] = str(coverage_json)
    result["source_coverage_markdown"] = str(coverage_md)
    result["source_release_id"] = 371149058
    result["paper_read_only"] = True
    result["real_execution"] = False
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
    print(f"report={result.get('report_path')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
