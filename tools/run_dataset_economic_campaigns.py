"""Copy-Vault-only FULL/COLD adapter around the canonical campaign runner.

The wrapper supplies Copy-Vault's deterministic multi-source inputs and
provenance. Lead-Lag and Cross-Venue remain disabled; their strategy loaders
are not installed or invoked. The canonical function runs with isolated
globals so dataset paths never leak into the code checkout.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from types import FunctionType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting.copy_vault_v21_frozen import SCHEMA_VERSION as COPY_V21_EVALUATION_SCHEMA  # noqa: E402
from hl_observer.backtesting.copy_vault_v21_frozen import evaluate_frozen_v21  # noqa: E402
from hl_observer.backtesting.economic_vnext_pack import run_economic_vnext_pack  # noqa: E402
from hl_observer.datasets.economic_multi_source import (  # noqa: E402
    install_copy_vault_adapter,
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
    """Return Copy-Vault data plus its shared Hyperliquid book-side source."""
    copy = load_family_source_paths(root, "copy_vault")
    shared_books = [
        path
        for path in load_family_source_paths(root, "cross_venue")
        if path.name.casefold() == "carnet_venues.jsonl"
    ]
    return _unique_paths([*copy, *shared_books])


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
    original_tool_loader = canonical._tool
    adapter_state: dict[str, object] = {}
    runtime_tools: dict[str, object] = {}

    def dataset_tool_loader(name: str, path: Path):
        tool = original_tool_loader(name, path)
        if name == "hypersmart_copy_pipeline":
            runtime_tools["copy_vault"] = tool
            adapter_state["copy_vault"] = install_copy_vault_adapter(
                data_root,
                copy_tool=tool,
                copy_executable=canonical.copy_vault_executable,
            )
        return tool

    original_provenance = canonical.dataset_provenance

    def dataset_provenance(root_value, paths):
        values = list(paths)
        resolved = Path(root_value).resolve()
        if resolved == data_root and _looks_like_copy_provenance(values):
            return original_provenance(data_root, copy_sources)
        return original_provenance(root_value, values)

    isolated_run = _isolated_run_campaigns(
        canonical,
        tool_loader=dataset_tool_loader,
        provenance_builder=dataset_provenance,
    )
    result = isolated_run(
        data_root,
        start_collection=False,
    )
    # Strong postcondition: the canonical loaded module was never changed.
    if canonical._tool is not original_tool_loader or canonical.dataset_provenance is not original_provenance:
        raise RuntimeError("canonical economic runner globals changed unexpectedly")

    coverage_json, coverage_md, coverage = write_economic_source_coverage(
        data_root,
        copy_consumed=copy_sources,
        lead_consumed=[],
        cross_consumed=[],
    )
    # vNext research is intentionally downstream of the canonical campaign.
    # It can only propose a later freeze and cannot alter the just-computed
    # canonical verdicts or scoreboards.
    vnext_research = run_economic_vnext_pack(data_root, lead_sources=[])

    copy_v21: dict[str, Any] = {
        "schema_version": COPY_V21_EVALUATION_SCHEMA,
        "family": "copy_vault",
        "objective_status": "NON_PROUVE",
        "status": "COPY_V21_RUNTIME_TOOL_MISSING",
        "economically_proven": False,
        "paper_read_only": True,
        "real_execution": False,
    }
    copy_tool = runtime_tools.get("copy_vault")
    freeze_path = ROOT / "runtime" / "codex_research" / "COPY_V21_PHYSICAL_FREEZE.json"
    if copy_tool is not None and freeze_path.is_file():
        freeze_payload = json.loads(freeze_path.read_text(encoding="utf-8"))
        entries, entries_audit = copy_tool.charger_entrees_alpha_notional_fixe_avec_audit(
            data_root
        )
        metaorders, metaorder_audit = canonical.copy_vault_executable.cluster_metaorders(
            entries
        )
        books, books_audit = canonical.copy_vault_executable.load_observed_books(
            data_root,
            coins={str(row["coin"]) for row in metaorders},
        )
        causal_metaorders, causal_books, protocol_audit = (
            canonical.copy_vault_executable.select_causal_protocol_inputs(
                metaorders, books
            )
        )
        continuous_books = {
            coin: sorted(
                [
                    dict(row)
                    for row in rows
                    if row.get("causal_observation") is True
                    and not row.get("checkpoint_id")
                    and str(row.get("source") or "") == "HYPERLIQUID_L2_WS"
                ],
                key=lambda row: int(row["ts_ms"]),
            )
            for coin, rows in causal_books.items()
        }
        continuous_books = {
            coin: rows for coin, rows in continuous_books.items() if rows
        }
        try:
            copy_v21 = evaluate_frozen_v21(
                causal_metaorders,
                continuous_books,
                freeze_payload,
                input_audit={
                    "entries": entries_audit,
                    "metaorders": metaorder_audit,
                    "books": books_audit,
                    "protocol": protocol_audit,
                    "continuous_causal_rows": sum(
                        len(rows) for rows in continuous_books.values()
                    ),
                },
            )
        except ValueError as exc:
            copy_v21.update({
                "status": "COPY_V21_FREEZE_REJECTED",
                "reason": str(exc),
                "economically_proven": False,
            })
        copy_v21_path = (
            data_root
            / "runtime"
            / "reports"
            / "economic_campaigns"
            / "research_vnext"
            / "copy_vault_v21_frozen_evaluation.json"
        )
        copy_v21_path.parent.mkdir(parents=True, exist_ok=True)
        copy_v21_path.write_text(
            json.dumps(copy_v21, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        result["copy_vault_v21_frozen_report"] = str(copy_v21_path)

    result["dataset_adapters"] = adapter_state
    result["source_coverage"] = coverage
    result["source_coverage_json"] = str(coverage_json)
    result["source_coverage_markdown"] = str(coverage_md)
    result["source_release_id"] = 371149058
    result["vnext_research"] = vnext_research
    result["copy_vault_v21_frozen"] = copy_v21
    result["paper_read_only"] = True
    result["real_execution"] = False
    result["canonical_globals_mutated"] = False
    result["disabled_families"] = {
        "lead_lag": "DISABLED_BY_SCOPE",
        "cross_venue_dislocation": "DISABLED_BY_SCOPE",
    }
    result["ignored_legacy_family_options"] = {
        "cross_budget_s": cross_budget_s,
        "cross_current_only": cross_current_only,
        "lead_history_sources": lead_history_sources,
        "collection_duration_s": collection_duration_s,
        "collection_startup_wait_s": collection_startup_wait_s,
    }
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
            f"{row['family']}: OBJECTIF +5 USD {row['objective_status']} | net={exact}",
            flush=True,
        )
    coverage = result.get("source_coverage") or {}
    print(f"source_coverage_all_full={coverage.get('all_families_full')}", flush=True)
    copy_v21 = result.get("copy_vault_v21_frozen") or {}
    print(
        "copy_vault_v21_frozen="
        f"{copy_v21.get('objective_status')} "
        f"validation={((copy_v21.get('validation') or {}).get('status'))} "
        f"oos={((copy_v21.get('oos') or {}).get('status'))} "
        f"forward={((copy_v21.get('forward') or {}).get('status'))}",
        flush=True,
    )
    print(f"vnext_summary={((result.get('vnext_research') or {}).get('summary_path'))}", flush=True)
    print(f"report={result.get('report_path')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
