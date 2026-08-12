"""Run the three separate read-only/paper economic evidence campaigns.

Each family is evaluated independently against the strict +4 USD realized-net
contract. The runner is deliberately fail-closed: missing depth, costs or
forward evidence remains NON_ATTEINT rather than becoming a modelled gain.
"""

from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting import lead_lag_shadow  # noqa: E402
from hl_observer.backtesting.lead_lag_multitape import (  # noqa: E402
    discover_sources as discover_lead_sources,
    load_multitape,
)
from hl_observer.ops.superviseur_collecteurs import demarrer_tous  # noqa: E402
from hl_observer.simulation.copy_campaign_adapter import build_strict_copy_campaign  # noqa: E402
from hl_observer.simulation.copy_cost_adapter import measure_copy_cost_components  # noqa: E402
from hl_observer.simulation.cross_venue_depth_adapter import (  # noqa: E402
    DEFAULT_DEPTH_FRESHNESS_MS,
    enrich_trades_with_depth,
    finalize_judgement as finalize_cross_judgement,
    load_depth_snapshots,
)
from hl_observer.simulation.economic_campaigns import (  # noqa: E402
    REPORT_DIR,
    build_cross_campaign,
    dataset_provenance,
    freeze_parameters,
    render_campaign_report,
    write_campaign,
)
from hl_observer.simulation.economic_family_scoreboard import export_scoreboards  # noqa: E402
from hl_observer.simulation.lead_lag_campaign_adapter import (  # noqa: E402
    campaign_from_replay,
    run_ledger as run_lead_lag_ledger,
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


def _copy_tape_and_forward(copy_tool: Any, root: Path, source: str):
    """Recreate exactly the price source chosen by the Copy research pipeline."""
    if source == "candles_5m":
        tape = copy_tool.charger_prix_tape_candles(root, intervalle="5m")
        forward = functools.partial(
            copy_tool.rendement_forward_candles,
            delai_ms=copy_tool.DELAI_COPIE_MS,
        )
    elif source == "candles_1m":
        tape = copy_tool.charger_prix_tape_candles(root, intervalle="1m")
        forward = functools.partial(
            copy_tool.rendement_forward_candles,
            delai_ms=copy_tool.DELAI_COPIE_MS,
        )
    else:
        tape = copy_tool.charger_prix_tape(root)
        forward = copy_tool.rendement_forward
    return tape, forward


def _enrich_copy_cost_evidence(
    copy_tool: Any,
    root: Path,
    report: dict[str, Any],
    depth_snapshots: dict[str, list[dict[str, Any]]],
) -> None:
    """Attach measured Copy costs without changing TRAIN-selected parameters.

    A complete vector exists only if every economically replayed OOS event has
    causal entry+exit depth and enough top-of-book capacity. Latency is not
    subtracted twice: candle forward returns already enter after DELAI_COPIE_MS.
    """
    measure = report.get("mesure") if isinstance(report.get("mesure"), dict) else {}
    oos = measure.get("oos") if isinstance(measure.get("oos"), dict) else {}
    if measure.get("statut") not in {"PRELIMINAIRE", "VALIDATION"} or not oos:
        report["cost_evidence"] = {
            "complete": False,
            "reason": "NO_SELECTED_OOS_CONFIGURATION",
            "paper_read_only": True,
            "real_execution": False,
        }
        return

    source = str(report.get("source_prix") or "")
    tape, forward = _copy_tape_and_forward(copy_tool, root, source)
    all_events = copy_tool.charger_entrees_alpha(root)
    t_cut = int(measure.get("t_cut_ms") or 0)
    threshold = float(oos["seuil"])
    horizon_ms = float(oos["horizon_ms"])
    oos_events = [event for event in all_events if int(event.get("ts_ms") or 0) >= t_cut]

    replayed_events: list[dict[str, Any]] = []
    for event in oos_events:
        if float(event.get("move_frac") or 0.0) < threshold:
            continue
        series = tape.get(str(event.get("coin") or "").upper())
        if series and forward(event, series, horizon_ms) is not None:
            replayed_events.append(event)

    notional_usd = 150.0
    evidence = measure_copy_cost_components(
        replayed_events,
        depth_snapshots,
        notional_usd=notional_usd,
        copy_delay_ms=float(copy_tool.DELAI_COPIE_MS),
        horizon_ms=horizon_ms,
        threshold=threshold,
        freshness_ms=DEFAULT_DEPTH_FRESHNESS_MS,
    )
    report["cost_evidence"] = evidence
    components = evidence.get("components_bps") if isinstance(evidence, dict) else None
    if not isinstance(components, dict):
        return

    keys = ("fees_bps", "spread_bps", "slippage_bps", "latency_bps")
    total_cost_bps = sum(float(components[key]) for key in keys)
    report["simulation_paper_oos"] = copy_tool.simuler_paper(
        oos_events,
        tape,
        horizon_ms=horizon_ms,
        seuil=threshold,
        notional_usd=notional_usd,
        cout_ar_bps=total_cost_bps,
        forward_fn=forward,
        cost_components_bps=components,
    )

    # Held-out vault robustness must use the exact same measured cost vector as
    # the OOS ledger. The research-time 12 bps assumption cannot promote a
    # family if actual executable costs are worse.
    generalization = (
        measure.get("generalisation_par_vault")
        if isinstance(measure.get("generalisation_par_vault"), dict)
        else None
    )
    if generalization is not None:
        held_out = {str(value) for value in generalization.get("vaults_held_out") or []}
        held_events = [
            event for event in oos_events
            if str(event.get("vault") or "") in held_out
        ]
        held_sim = copy_tool.simuler_paper(
            held_events,
            tape,
            horizon_ms=horizon_ms,
            seuil=threshold,
            notional_usd=notional_usd,
            cout_ar_bps=total_cost_bps,
            forward_fn=forward,
            cost_components_bps=components,
        )
        generalization["n"] = held_sim.get("n_trades")
        generalization["net_bps"] = held_sim.get("roi_par_trade_bps")
        generalization["measured_cost_bps"] = round(total_cost_bps, 6)
        generalization["LIQUIDATABLE_NET"] = held_sim.get("LIQUIDATABLE_NET") is True


def run_campaigns(
    root: Path,
    *,
    cross_budget_s: float = 20.0,
    cross_current_only: bool = False,
    lead_budget_s: float = 45.0,
    lead_max_lines: int = 2_000_000,
    start_collection: bool = True,
) -> dict[str, Any]:
    assert_execution_disabled()
    root = Path(root).resolve()
    copy_tool = _tool("hypersmart_copy_pipeline", root / "tools" / "pipeline_copie_reel.py")
    cross_tool = _tool("hypersmart_cross_campaign", root / "tools" / "backtest_dislocation_2jambes.py")
    depth_snapshots = load_depth_snapshots(root)

    # ---------------------------------------------------------------- Copy-Vault
    copy_data = dataset_provenance(
        root,
        (
            "runtime/data/vault_fills.jsonl",
            "runtime/data/vault_episodes.jsonl",
            "runtime/data/vault_snapshots.jsonl",
            "runtime/data/hl_allmids_tape.jsonl",
            "runtime/data/carnet_venues.jsonl",
        ),
    )
    copy_freeze: dict[str, Any] | None = None

    def freeze_copy(parameters: dict[str, Any]) -> None:
        nonlocal copy_freeze
        copy_freeze = freeze_parameters(root, "copy_vault", parameters, copy_data)

    copy_raw = copy_tool.construire(
        root,
        geler_si_valide=False,
        on_parameters_selected=freeze_copy,
        cost_components_bps=None,
    )
    _enrich_copy_cost_evidence(copy_tool, root, copy_raw, depth_snapshots)
    copy_raw_path = _write_raw(root, "copy_vault", copy_raw)
    copy_campaign = build_strict_copy_campaign(copy_raw, freeze=copy_freeze, datasets=copy_data)
    copy_campaign["evidence_paths"].append(copy_raw_path.relative_to(root).as_posix())
    write_campaign(root, copy_campaign)

    # ---------------------------------------------------------------- Lead-Lag
    lead_sources = discover_lead_sources(root)
    lead_data = dataset_provenance(
        root,
        [*lead_sources, root / "runtime" / "data" / "carnet_venues.jsonl"],
    )
    lead_horizon_ms = 1_000
    lead_min_history = 5
    lead_cost_config = {
        "notional": 100.0,
        # Conservative single follower leg round trip: 4.5 bps taker on entry
        # and 4.5 bps on exit. This fee value alone does not make costs measured.
        "fee_bps": 9.0,
        # Still estimates until causally aligned executable depth is attached.
        # Consequently costs_measured MUST remain false and objective fails closed.
        "demi_spread_bps": 4.0,
        "slippage_bps": 1.0,
        "min_fill_ratio": 0.5,
        "costs_measured": False,
        "equity": 1000.0,
    }
    lead_params = {
        "seuil_choc_bps": lead_lag_shadow.SEUIL_CHOC_BPS,
        "horizon_ms": lead_horizon_ms,
        "minimum_history": lead_min_history,
        "minimum_episodes": 5,
        "cost_model": lead_cost_config,
        "loader_max_lines": int(lead_max_lines),
        "loader_time_budget_s": float(lead_budget_s),
        "selection_rule": "FIXED_PRE_EVALUATION",
    }
    lead_freeze = freeze_parameters(root, "lead_lag", lead_params, lead_data)
    lead_tape, lead_loader_meta = load_multitape(
        root,
        max_lines=max(0, int(lead_max_lines)),
        time_budget_s=max(0.0, float(lead_budget_s)),
    )
    lead_raw = run_lead_lag_ledger(
        lead_tape,
        shock_threshold_bps=lead_lag_shadow.SEUIL_CHOC_BPS,
        horizon_ms=lead_horizon_ms,
        min_history=lead_min_history,
        config=lead_cost_config,
        min_episodes=5,
    )
    lead_raw["multitape_meta"] = lead_loader_meta
    lead_raw["paper_read_only"] = True
    lead_raw["real_execution"] = False
    lead_raw_path = _write_raw(root, "lead_lag", lead_raw)
    lead_campaign = campaign_from_replay(
        lead_raw,
        freeze=lead_freeze,
        datasets=lead_data,
        evidence_paths=[lead_raw_path.relative_to(root).as_posix()],
    )
    write_campaign(root, lead_campaign)

    # ---------------------------------------------------------------- Cross-Venue v2
    cross_data = dataset_provenance(
        root,
        (
            "runtime/data/bbo_tape.jsonl",
            "runtime/data/bbo_tape.jsonl.prev",
            "runtime/data/carnet_venues.jsonl",
        ),
    )
    cross_params = {
        "seuil_entree_bps": cross_tool.SEUIL_ENTREE_BPS,
        "seuil_sortie_bps": cross_tool.SEUIL_SORTIE_BPS,
        "stop_aggravation_bps": cross_tool.STOP_AGGRAVATION_BPS,
        "horizon_max_s": cross_tool.HORIZON_MAX_S,
        "fraicheur_max_ms": cross_tool.FRAICHEUR_MAX_MS,
        "latence_ms": cross_tool.LATENCE_MS,
        "fees_ar_bps": cross_tool.FEES_AR_BPS,
        "notional_usd": cross_tool.NOTIONAL_USD,
        "depth_freshness_ms": DEFAULT_DEPTH_FRESHNESS_MS,
        "depth_rule": "AT_OR_BEFORE_ENTRY_AND_EXIT_TOP_CAPACITY",
    }
    cross_freeze = freeze_parameters(root, "cross_venue_dislocation_v2", cross_params, cross_data)
    series = cross_tool.collecter_series(
        root,
        budget_s=max(0.0, cross_budget_s),
        current_only=cross_current_only,
    )
    cross_meta = series.pop("_meta", {})
    cross_trades = cross_tool.backtester(series)
    cross_trades = enrich_trades_with_depth(
        cross_trades,
        depth_snapshots,
        notional_usd=cross_tool.NOTIONAL_USD,
        freshness_ms=DEFAULT_DEPTH_FRESHNESS_MS,
    )
    cross_judgement = finalize_cross_judgement(
        cross_trades,
        cross_tool.juger(cross_trades),
        notional_usd=cross_tool.NOTIONAL_USD,
    )
    cross_raw = {
        "schema_version": "hypersmart.cross_venue_campaign.v2",
        "meta": {
            **cross_meta,
            "depth_coins": len(depth_snapshots),
            "depth_freshness_ms": DEFAULT_DEPTH_FRESHNESS_MS,
        },
        "quotes_par_coin": {coin: len(values) for coin, values in series.items() if values},
        "params": cross_params,
        "verdict_realiste_16bps": cross_judgement,
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

    collector_state = None
    if start_collection and any(row["objective_status"] != "ATTEINT" for row in campaigns):
        collector_state = demarrer_tous(root, profil="harvest")
        collection_path = root / REPORT_DIR / "collection_resume_state.json"
        _write_raw(root, "collection_resume_state", collector_state)
        campaigns_with_need = [
            row["family"] for row in campaigns if row["objective_status"] != "ATTEINT"
        ]
        collection_path.write_text(
            json.dumps(
                {
                    **collector_state,
                    "families_requiring_more_data": campaigns_with_need,
                    "paper_read_only": True,
                    "real_execution": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return {
        "campaigns": campaigns,
        "report_path": str(report_path),
        "scoreboards_path": str(scoreboards_path),
        "collector_state": collector_state,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--cross-budget-s", type=float, default=20.0)
    parser.add_argument("--cross-current-only", action="store_true")
    parser.add_argument("--lead-budget-s", type=float, default=45.0)
    parser.add_argument("--lead-max-lines", type=int, default=2_000_000)
    parser.add_argument("--no-start-collection", action="store_true")
    args = parser.parse_args(argv)
    result = run_campaigns(
        Path(args.root).resolve(),
        cross_budget_s=args.cross_budget_s,
        cross_current_only=args.cross_current_only,
        lead_budget_s=args.lead_budget_s,
        lead_max_lines=args.lead_max_lines,
        start_collection=not args.no_start_collection,
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
