"""Reproducible, fail-closed economic campaign evidence.

This module converts family-specific paper replays into one strict proof
shape.  It never creates market data, signals, fills, or execution.  Missing
measurements remain ``None`` and therefore fail the shared +4 USD objective.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hl_observer.backtesting.copy_vault_protocol import CHECKPOINT_INTEGRITY_SCHEMA
from hl_observer.economics.proof_binding import audit_economic_contract_receipt
from hl_observer.simulation.economic_campaign_provenance import (
    dataset_provenance,
    find_oldest_parameter_freeze,
    freeze_or_reuse_parameters,
    freeze_parameters,
    freeze_train_selected_parameters,
    merge_sources_with_frozen_provenance,
)

from .economic_objective import (
    STARTING_CAPITAL_USD,
    canonical_family,
    evaluate_daily_net,
    evaluate_objective,
)

SCHEMA_VERSION = "hypersmart.economic_campaign_evidence.v1"
REPORT_DIR = Path("runtime") / "reports" / "economic_campaigns"


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)



def _base(
    family: str,
    *,
    freeze: Mapping[str, Any] | None,
    datasets: Mapping[str, Any],
    evidence_paths: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "family": canonical_family(family),
        "campaign_id": freeze.get("campaign_id") if freeze else None,
        "generated_at_ms": int(time.time() * 1000),
        "starting_capital_usd": STARTING_CAPITAL_USD,
        "paper_read_only": True,
        "real_execution": False,
        "parameters_frozen": bool(freeze and freeze.get("selected_before_final_evaluation") is True),
        "parameter_freeze": dict(freeze) if freeze else None,
        "dataset_provenance": dict(datasets),
        "signal_count": None,
        "opened_positions": None,
        "closed_positions": None,
        "gross_pnl_usd": None,
        "fees_usd": None,
        "spread_cost_usd": None,
        "slippage_cost_usd": None,
        "latency_cost_usd": None,
        "net_pnl_usd": None,
        "roi_pct": None,
        "max_drawdown_usd": None,
        "hit_rate": None,
        "profit_factor": None,
        "liquidatable_net": False,
        "duplicate_trade_ids": None,
        "trade_ids_count": None,
        "trade_ids_sha256": None,
        "oos": None,
        "forward": None,
        "placebos": None,
        "evidence_paths": list(dict.fromkeys(evidence_paths)),
        "economic_contract": None,
        "assumption_snapshot_hash": None,
    }


def _extract_economic_contract(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    candidates: list[Mapping[str, Any]] = [payload]
    for key in ("executable_campaign", "walk_forward"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            candidates.append(nested)
    for candidate in candidates:
        contract = candidate.get("economic_contract")
        if isinstance(contract, Mapping):
            return contract
        trades = candidate.get("trades")
        if isinstance(trades, list):
            for trade in trades:
                if not isinstance(trade, Mapping):
                    continue
                contract = trade.get("economic_contract")
                if isinstance(contract, Mapping):
                    return contract
    return None


def _attach_economic_contract(row: dict[str, Any], payload: Mapping[str, Any]) -> None:
    contract = _extract_economic_contract(payload)
    if contract is None:
        return
    row["economic_contract"] = dict(contract)
    row["assumption_snapshot_hash"] = contract.get("assumption_snapshot_hash")


def _finish(row: dict[str, Any]) -> dict[str, Any]:
    binding = audit_economic_contract_receipt(
        row.get("economic_contract"),
        expected_family=row.get("family"),
        require_certifiable_mode=True,
    )
    row["economic_binding"] = binding
    objective = evaluate_objective(row)
    if objective.get("objective_status") == "ATTEINT" and binding.get("ready") is not True:
        objective["objective_status"] = "NON_ATTEINT"
        objective["eligible_net_pnl_usd"] = None
        objective["objective_reasons"] = list(
            dict.fromkeys(
                [
                    *list(objective.get("objective_reasons") or []),
                    *[
                        f"ECONOMIC_BINDING_INVALID:{reason}"
                        for reason in binding.get("issues") or ["UNKNOWN"]
                    ],
                ]
            )
        )
    row.update(objective)
    return row


def _trade_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    direct = payload.get("trades")
    if isinstance(direct, list):
        return [dict(item) for item in direct if isinstance(item, Mapping)]
    for container_key in ("walk_forward", "executable_campaign"):
        container = payload.get(container_key)
        if not isinstance(container, Mapping):
            continue
        nested = container.get("trades")
        if isinstance(nested, list):
            return [dict(item) for item in nested if isinstance(item, Mapping)]
        if isinstance(nested, Mapping):
            flattened: list[dict[str, Any]] = []
            for segment, values in nested.items():
                if not isinstance(values, list):
                    continue
                for item in values:
                    if isinstance(item, Mapping):
                        trade = dict(item)
                        trade.setdefault("walk_forward_segment", str(segment))
                        flattened.append(trade)
            return flattened
    return []


def _attach_daily_evidence(
    row: dict[str, Any], payload: Mapping[str, Any], *, require_daily: bool
) -> None:
    trades = _trade_rows(payload)
    liquidatable = [
        trade
        for trade in trades
        if trade.get("liquidatable_net") is True
        or trade.get("LIQUIDATABLE_NET") is True
    ]
    proof_trades = [
        trade
        for trade in liquidatable
        if str(
            trade.get("walk_forward_segment") or trade.get("segment") or ""
        ).lower()
        in {"oos", "forward"}
    ]
    row["daily_target_required"] = bool(require_daily)
    row["daily_observed"] = evaluate_daily_net(
        liquidatable, complete_utc_days_only=False
    )
    row["daily_evidence"] = evaluate_daily_net(proof_trades) if proof_trades else None


def _copy_checkpoint_integrity(report: Mapping[str, Any]) -> dict[str, Any]:
    book_meta = report.get("book_meta")
    book_meta = book_meta if isinstance(book_meta, Mapping) else {}
    receipt = book_meta.get("clean_epoch_receipt")
    receipt = receipt if isinstance(receipt, Mapping) else {}
    temporal = report.get("temporal_evidence")
    temporal = temporal if isinstance(temporal, Mapping) else {}
    expected_proof_count = sum(
        int(segment.get("sample_count") or 0)
        for name in ("oos", "forward")
        for segment in [temporal.get(name)]
        if isinstance(segment, Mapping)
    )
    trades = _trade_rows(report)
    proof_trades = [
        trade
        for trade in trades
        if isinstance(trade, Mapping)
        and trade.get("walk_forward_segment") in {"oos", "forward"}
    ]
    writer_run_id = str(receipt.get("writer_run_id") or "").strip()
    try:
        clean_epoch_ms = int(receipt.get("clean_epoch_ms") or 0)
    except (TypeError, ValueError, OverflowError):
        clean_epoch_ms = 0
    complete_count = bool(
        expected_proof_count > 0 and len(proof_trades) == expected_proof_count
    )
    return {
        "schema_version": CHECKPOINT_INTEGRITY_SCHEMA,
        "receipt_valid": receipt.get("receipt_valid") is True,
        "writer_role": receipt.get("writer_role"),
        "writer_run_id": writer_run_id or None,
        "clean_epoch_ms": clean_epoch_ms or None,
        "duplicate_checkpoint_ids": receipt.get("duplicate_checkpoint_ids"),
        "quarantined_checkpoint_metaorders": receipt.get(
            "quarantined_checkpoint_metaorders"
        ),
        "proof_trade_count": len(proof_trades),
        "expected_proof_trade_count": expected_proof_count,
        "all_proof_trades_exact_checkpoint_bound": bool(
            complete_count
            and all(
                trade.get("book_binding_method") == "EXACT_METAORDER_CHECKPOINTS"
                for trade in proof_trades
            )
        ),
        "all_proof_trades_same_writer_run": bool(
            complete_count
            and writer_run_id
            and clean_epoch_ms > 0
            and all(
                str(trade.get("checkpoint_writer_run_id") or "") == writer_run_id
                and int(trade.get("checkpoint_clean_epoch_ms") or 0)
                == clean_epoch_ms
                for trade in proof_trades
            )
        ),
        "all_proof_trades_post_clean_epoch": bool(
            complete_count
            and all(
                trade.get("all_checkpoints_post_clean_epoch") is True
                for trade in proof_trades
            )
        ),
    }


def build_copy_campaign(
    report: Mapping[str, Any],
    *,
    freeze: Mapping[str, Any] | None,
    datasets: Mapping[str, Any],
    require_daily: bool = False,
) -> dict[str, Any]:
    row = _base(
        "copy_vault",
        freeze=freeze,
        datasets=datasets,
        evidence_paths=("runtime/data/copy_edge_rapport_reel.json",),
    )
    _attach_economic_contract(row, report)
    if report.get("schema_version") == "hypersmart.copy_vault_executable_campaign.v1":
        summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
        temporal = (
            report.get("temporal_evidence")
            if isinstance(report.get("temporal_evidence"), Mapping)
            else {}
        )
        metaorder_audit = (
            report.get("metaorder_audit")
            if isinstance(report.get("metaorder_audit"), Mapping)
            else {}
        )
        calibration = (
            report.get("calibration")
            if isinstance(report.get("calibration"), Mapping)
            else {}
        )
        closed_count = int(summary.get("positions_fermees") or 0)
        measured = closed_count > 0
        def economic_value(key: str) -> Any:
            return summary.get(key) if measured else None
        row.update(
            {
                "signal_count": metaorder_audit.get("metaorders"),
                "source_status": (
                    calibration.get("status")
                    or (report.get("params") or {}).get("selection_status")
                ),
                "opened_positions": summary.get("positions_ouvertes"),
                "closed_positions": summary.get("positions_fermees"),
                "gross_pnl_usd": economic_value("gross_pnl_usd"),
                "fees_usd": economic_value("fees_usd"),
                "spread_cost_usd": economic_value("spread_cost_usd"),
                "slippage_cost_usd": economic_value("slippage_cost_usd"),
                "latency_cost_usd": economic_value("latency_cost_usd"),
                "net_pnl_usd": economic_value("net_pnl_usd"),
                "roi_pct": economic_value("roi_pct"),
                "max_drawdown_usd": economic_value("max_drawdown_usd"),
                "hit_rate": economic_value("hit_rate"),
                "profit_factor": economic_value("profit_factor"),
                "liquidatable_net": summary.get("LIQUIDATABLE_NET") is True,
                "duplicate_trade_ids": summary.get("duplicate_trade_ids"),
                "trade_ids_count": summary.get("trade_ids_count"),
                "trade_ids_sha256": summary.get("trade_ids_sha256"),
                "oos": temporal.get("oos") if isinstance(temporal.get("oos"), Mapping) else None,
                "forward": (
                    temporal.get("forward")
                    if isinstance(temporal.get("forward"), Mapping)
                    else None
                ),
                "placebos": (
                    temporal.get("placebos")
                    if isinstance(temporal.get("placebos"), Mapping)
                    else None
                ),
                "period": {
                    "walk_forward_bounds": (report.get("params") or {}).get(
                        "walk_forward_bounds"
                    ),
                    "book_meta": report.get("book_meta"),
                    "canonical_input_audit": report.get("canonical_input_audit"),
                    "metaorder_audit": metaorder_audit,
                },
                "copy_checkpoint_integrity": _copy_checkpoint_integrity(report),
            }
        )
        executable_generalization = (
            report.get("vault_generalization")
            if isinstance(report.get("vault_generalization"), Mapping)
            else None
        )
        row["vault_generalization"] = (
            dict(executable_generalization)
            if executable_generalization is not None
            else None
        )
        _attach_daily_evidence(row, report, require_daily=require_daily)
        return _finish(row)

    measure = report.get("mesure") if isinstance(report.get("mesure"), Mapping) else {}
    legacy_generalization = (
        measure.get("generalisation_par_vault")
        if isinstance(measure.get("generalisation_par_vault"), Mapping)
        else None
    )
    row["vault_generalization"] = (
        {
            "sample_count": legacy_generalization.get("n"),
            "net_bps": legacy_generalization.get("net_bps"),
            "vaults_held_out": list(legacy_generalization.get("vaults_held_out") or []),
            "role": "SECONDARY_ROBUSTNESS_REQUIRED_FOR_ECONOMIC_CLAIM",
        }
        if legacy_generalization is not None
        else None
    )
    simulation = (
        report.get("simulation_paper_oos")
        if isinstance(report.get("simulation_paper_oos"), Mapping)
        else None
    )
    row["signal_count"] = report.get("n_entrees_alpha")
    row["source_status"] = measure.get("statut")
    row["source_decision"] = measure.get("decision")
    row["period"] = {
        "t_cut_ms": measure.get("t_cut_ms"),
        "source_price": report.get("source_prix"),
        "copy_delay_ms": report.get("delai_copie_ms"),
    }
    if simulation:
        opened = simulation.get("positions_ouvertes")
        closed = simulation.get("positions_fermees")
        row.update(
            {
                "opened_positions": opened,
                "closed_positions": closed,
                "gross_pnl_usd": simulation.get("pnl_brut_realise_usd"),
                "fees_usd": simulation.get("fees_usd"),
                "spread_cost_usd": simulation.get("spread_usd"),
                "slippage_cost_usd": simulation.get("slippage_usd"),
                "latency_cost_usd": simulation.get("latency_usd"),
                "net_pnl_usd": simulation.get("pnl_net_usd"),
                "roi_pct": simulation.get("roi_cumulatif_pct"),
                "max_drawdown_usd": simulation.get("drawdown_usd"),
                "hit_rate": (
                    float(simulation["winrate_pct"]) / 100.0
                    if simulation.get("winrate_pct") is not None
                    else None
                ),
                "profit_factor": simulation.get("profit_factor"),
                "liquidatable_net": simulation.get("LIQUIDATABLE_NET") is True,
                "duplicate_trade_ids": (
                    0 if simulation.get("trade_ids_count") == closed else None
                ),
                "source_duplicate_events_rejected": simulation.get("duplicate_events_rejected"),
                "trade_ids_count": simulation.get("trade_ids_count"),
                "trade_ids_sha256": simulation.get("trade_ids_sha256"),
                "oos": {
                    "net_pnl_usd": simulation.get("pnl_net_usd"),
                    "sample_count": closed,
                    "no_lookahead": True,
                },
            }
        )
    oos_measure = measure.get("oos") if isinstance(measure.get("oos"), Mapping) else {}
    if oos_measure:
        row["placebos"] = {
            "beaten": float(oos_measure.get("edge_vs_placebo_bps") or 0.0) > 0,
            "candidate_net_bps": oos_measure.get("net_bps"),
            "placebo_net_bps": oos_measure.get("placebo_bps"),
        }
    row["forward"] = None  # Must be collected after the physical freeze.
    _attach_daily_evidence(row, report, require_daily=require_daily)
    return _finish(row)


def build_lead_lag_campaign(
    analysis: Mapping[str, Any],
    *,
    freeze: Mapping[str, Any] | None,
    datasets: Mapping[str, Any],
    require_daily: bool = False,
) -> dict[str, Any]:
    row = _base(
        "lead_lag",
        freeze=freeze,
        datasets=datasets,
        evidence_paths=("runtime/data/bbo_tape.jsonl",),
    )
    _attach_economic_contract(row, analysis)
    row["source_status"] = analysis.get("statut")
    row["source_detail"] = analysis.get("detail")
    row["signal_count"] = analysis.get("chocs_test")
    row["period"] = {
        "observable_horizons_ms": analysis.get("horizons_observables"),
        "hl_intervals": analysis.get("intervalles_hl"),
    }
    executable = (
        analysis.get("executable_campaign")
        if isinstance(analysis.get("executable_campaign"), Mapping)
        else None
    )
    if not executable:
        _attach_daily_evidence(row, analysis, require_daily=require_daily)
        return _finish(row)
    summary = executable.get("summary") if isinstance(executable.get("summary"), Mapping) else {}
    temporal = (
        executable.get("temporal_evidence")
        if isinstance(executable.get("temporal_evidence"), Mapping)
        else {}
    )
    closed = int(summary.get("positions_fermees") or 0)
    measured = closed > 0

    def economic_value(key: str) -> Any:
        return summary.get(key) if measured else None

    row.update(
        {
            "signal_count": (executable.get("diagnostics") or {}).get(
                "candidate_observations"
            ),
            "source_status": (
                "EXECUTABLE_LEDGER_MEASURED" if measured else "FUTURE_SIZED_BBO_REQUIRED"
            ),
            "opened_positions": summary.get("positions_ouvertes"),
            "closed_positions": summary.get("positions_fermees"),
            "gross_pnl_usd": economic_value("gross_pnl_usd"),
            "fees_usd": economic_value("fees_usd"),
            "spread_cost_usd": economic_value("spread_cost_usd"),
            "slippage_cost_usd": economic_value("slippage_cost_usd"),
            "latency_cost_usd": economic_value("latency_cost_usd"),
            "net_pnl_usd": economic_value("net_pnl_usd"),
            "roi_pct": economic_value("roi_pct"),
            "max_drawdown_usd": economic_value("max_drawdown_usd"),
            "hit_rate": economic_value("hit_rate"),
            "profit_factor": economic_value("profit_factor"),
            "liquidatable_net": summary.get("LIQUIDATABLE_NET") is True,
            "duplicate_trade_ids": summary.get("duplicate_trade_ids"),
            "trade_ids_count": summary.get("trade_ids_count"),
            "trade_ids_sha256": summary.get("trade_ids_sha256"),
            "oos": temporal.get("oos") if isinstance(temporal.get("oos"), Mapping) else None,
            "forward": (
                temporal.get("forward")
                if isinstance(temporal.get("forward"), Mapping)
                else None
            ),
            "placebos": (
                temporal.get("placebos")
                if isinstance(temporal.get("placebos"), Mapping)
                else None
            ),
            "period": {
                **row["period"],
                "walk_forward_bounds": executable.get("walk_forward_bounds"),
                "execution_model": executable.get("execution_model"),
                "segment_summaries": executable.get("segment_summaries"),
                "diagnostics": executable.get("diagnostics"),
            },
        }
    )
    _attach_daily_evidence(row, analysis, require_daily=require_daily)
    return _finish(row)


def build_cross_campaign(
    report: Mapping[str, Any],
    *,
    freeze: Mapping[str, Any] | None,
    datasets: Mapping[str, Any],
    require_daily: bool = False,
) -> dict[str, Any]:
    row = _base(
        "cross_venue_dislocation_v2",
        freeze=freeze,
        datasets=datasets,
        evidence_paths=("runtime/research/dislocation_final_verdict.json",),
    )
    _attach_economic_contract(row, report)
    realistic = (
        report.get("verdict_realiste_16bps")
        if isinstance(report.get("verdict_realiste_16bps"), Mapping)
        else {}
    )
    trades = report.get("trades") if isinstance(report.get("trades"), list) else []
    temporal = (
        report.get("temporal_evidence")
        if isinstance(report.get("temporal_evidence"), Mapping)
        else {}
    )
    row.update(
        {
            "source_status": realistic.get("verdict"),
            "signal_count": realistic.get("n_trades"),
            "opened_positions": realistic.get("positions_ouvertes"),
            "closed_positions": realistic.get("positions_fermees"),
            "gross_pnl_usd": realistic.get("gross_pnl_usd"),
            "fees_usd": realistic.get("fees_usd"),
            "spread_cost_usd": realistic.get("spread_cost_usd"),
            "slippage_cost_usd": realistic.get("slippage_cost_usd"),
            "latency_cost_usd": realistic.get("latency_cost_usd"),
            "net_pnl_usd": realistic.get("net_total_usd"),
            "roi_pct": realistic.get("roi_pct"),
            "max_drawdown_usd": realistic.get("max_drawdown_usd"),
            "hit_rate": realistic.get("hit_rate"),
            "profit_factor": realistic.get("profit_factor", realistic.get("pf")),
            "liquidatable_net": realistic.get("LIQUIDATABLE_NET") is True,
            "all_positions_two_leg_closed": realistic.get("all_positions_two_leg_closed") is True,
            "duplicate_trade_ids": realistic.get("duplicate_trade_ids"),
            "trade_ids_count": realistic.get("trade_ids_count"),
            "trade_ids_sha256": realistic.get("trade_ids_sha256"),
            "period": {
                "first_detection_ms": min((trade.get("ts_detect") for trade in trades), default=None),
                "last_close_ms": max((trade.get("ts_out") for trade in trades), default=None),
                "collection_meta": report.get("meta"),
            },
            "oos": temporal.get("oos") if isinstance(temporal.get("oos"), Mapping) else None,
            "forward": (
                temporal.get("forward")
                if isinstance(temporal.get("forward"), Mapping) else None
            ),
            "placebos": (
                temporal.get("placebos")
                if isinstance(temporal.get("placebos"), Mapping) else None
            ),
            "hypothesis_audit": (
                report.get("hypothesis_audit")
                if isinstance(report.get("hypothesis_audit"), Mapping) else None
            ),
        }
    )
    _attach_daily_evidence(row, report, require_daily=require_daily)
    return _finish(row)


def write_campaign(root: str | Path, evidence: Mapping[str, Any]) -> Path:
    project_root = Path(root).resolve()
    family = canonical_family(evidence.get("family"))
    target = project_root / REPORT_DIR / f"{family}.json"
    _atomic_json(target, evidence)
    return target


def render_campaign_report(campaigns: Iterable[Mapping[str, Any]]) -> str:
    labels = {
        "copy_vault": "Copy-Vault",
        "lead_lag": "Cross-Venue (Lead-Lag)",
        "cross_venue_dislocation_v2": "Arbitrage (Cross-Venue Dislocation v2)",
    }
    lines = [
        "# Campagnes economiques HyperSmart",
        "",
        "Capital paper consolide: 1 000 USD. Cible: +4 USD nets par jour et par module. Carry OFF. Cross-Venue v1 OFF.",
        "Chaque resultat est separe; aucun PnL latent ou inter-famille n'est additionne.",
        "",
    ]
    for campaign in campaigns:
        family = canonical_family(campaign.get("family"))
        status = str(campaign.get("objective_status") or "NON_ATTEINT")
        net = campaign.get("net_pnl_usd")
        eligible_net = campaign.get("eligible_net_pnl_usd")
        net_text = "NON MESURABLE" if net is None else f"{float(net):+.6f} USD"
        eligible_text = (
            "NON ELIGIBLE A LA PREUVE"
            if eligible_net is None
            else f"{float(eligible_net):+.6f} USD"
        )
        oos = campaign.get("oos") if isinstance(campaign.get("oos"), Mapping) else {}
        forward = (
            campaign.get("forward")
            if isinstance(campaign.get("forward"), Mapping)
            else {}
        )
        placebos = (
            campaign.get("placebos")
            if isinstance(campaign.get("placebos"), Mapping)
            else {}
        )
        freeze = (
            campaign.get("parameter_freeze")
            if isinstance(campaign.get("parameter_freeze"), Mapping)
            else {}
        )
        datasets = (
            campaign.get("dataset_provenance")
            if isinstance(campaign.get("dataset_provenance"), Mapping)
            else {}
        )
        proof_economics = (
            campaign.get("proof_economics")
            if isinstance(campaign.get("proof_economics"), Mapping)
            else {}
        )
        lines.extend(
            [
                f"## {labels.get(family, family)} - OBJECTIF +4 USD / JOUR : {status}",
                "",
                f"- PnL net observe (diagnostic): {net_text}",
                f"- PnL net de preuve OOS + forward: {campaign.get('proof_net_pnl_usd')}",
                f"- PnL net eligible a la preuve: {eligible_text}",
                f"- Parametres geles avant evaluation: {campaign.get('parameters_frozen')}",
                f"- Freeze ID: {freeze.get('campaign_id')}",
                f"- Dataset SHA-256: {datasets.get('dataset_fingerprint')}",
                f"- Signaux: {campaign.get('signal_count')}",
                f"- Positions ouvertes/fermees: {campaign.get('opened_positions')} / {campaign.get('closed_positions')}",
                f"- PnL brut realise (diagnostic global): {campaign.get('gross_pnl_usd')}",
                f"- Frais entree/sortie (diagnostic global): {campaign.get('fees_usd')}",
                f"- Cout spread (diagnostic global): {campaign.get('spread_cost_usd')}",
                f"- Cout slippage (diagnostic global): {campaign.get('slippage_cost_usd')}",
                f"- Cout latence (diagnostic global): {campaign.get('latency_cost_usd')}",
                f"- Preuve OOS+forward brut: {proof_economics.get('gross_pnl_usd')}",
                f"- Preuve OOS+forward frais: {proof_economics.get('fees_usd')}",
                f"- Preuve OOS+forward spread: {proof_economics.get('spread_cost_usd')}",
                f"- Preuve OOS+forward slippage: {proof_economics.get('slippage_cost_usd')}",
                f"- Preuve OOS+forward latence: {proof_economics.get('latency_cost_usd')}",
                f"- Preuve OOS+forward trades/hash: {proof_economics.get('trade_ids_count')} / {proof_economics.get('trade_ids_sha256')}",
                f"- LIQUIDATABLE_NET: {campaign.get('liquidatable_net')}",
                f"- ROI: {campaign.get('roi_pct')}",
                f"- Drawdown max USD: {campaign.get('max_drawdown_usd')}",
                f"- Hit rate: {campaign.get('hit_rate')}",
                f"- Profit factor: {campaign.get('profit_factor')}",
                f"- Trades uniques / doublons: {campaign.get('trade_ids_count')} / {campaign.get('duplicate_trade_ids')}",
                f"- Hash des trades: {campaign.get('trade_ids_sha256')}",
                f"- OOS: n={oos.get('sample_count')} net={oos.get('net_pnl_usd')} no-lookahead={oos.get('no_lookahead')}",
                f"- Forward post-gel: n={forward.get('sample_count')} net={forward.get('net_pnl_usd')} post-freeze={forward.get('post_freeze')}",
                f"- Cible journaliere requise: {campaign.get('daily_target_required')}",
                f"- Preuve journaliere: jours={((campaign.get('daily_evidence') or {}).get('sample_count'))} moyenne={((campaign.get('daily_evidence') or {}).get('mean_daily_net_pnl_usd'))} minimum={((campaign.get('daily_evidence') or {}).get('min_daily_net_pnl_usd'))} tous_jours>=4={((campaign.get('daily_evidence') or {}).get('all_days_at_or_above_target'))}",
                f"- Jours observes (diagnostic): {((campaign.get('daily_observed') or {}).get('sample_count'))} moyenne={((campaign.get('daily_observed') or {}).get('mean_daily_net_pnl_usd'))}",
                f"- Placebo battu: {placebos.get('beaten')}",
                f"- Raisons: {', '.join(campaign.get('objective_reasons') or [])}",
                "",
            ]
        )
    lines.extend(
        [
            "## Securite",
            "",
            "Lecture seule et paper local. Aucune execution reelle. Carry et ancien Cross-Venue v1 desactives.",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "REPORT_DIR",
    "SCHEMA_VERSION",
    "build_copy_campaign",
    "build_cross_campaign",
    "build_lead_lag_campaign",
    "dataset_provenance",
    "freeze_parameters",
    "freeze_or_reuse_parameters",
    "find_oldest_parameter_freeze",
    "freeze_train_selected_parameters",
    "merge_sources_with_frozen_provenance",
    "render_campaign_report",
    "write_campaign",
]
