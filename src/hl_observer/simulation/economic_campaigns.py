"""Reproducible, fail-closed economic campaign evidence.

This module converts family-specific paper replays into one strict proof
shape.  It never creates market data, signals, fills, or execution.  Missing
measurements remain ``None`` and therefore fail the shared +4 USD objective.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .economic_objective import (
    STARTING_CAPITAL_USD,
    canonical_family,
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


def _sha256(path: Path, *, full_limit_bytes: int = 128 * 1024 * 1024) -> tuple[str, str]:
    """Hash a complete small file or both edges of a large append-only tape."""

    size = path.stat().st_size
    digest = hashlib.sha256()
    if size <= full_limit_bytes:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest(), "FULL_SHA256"
    edge = 1024 * 1024
    with path.open("rb") as handle:
        digest.update(handle.read(edge))
        handle.seek(max(0, size - edge))
        digest.update(handle.read(edge))
    digest.update(str(size).encode("ascii"))
    return digest.hexdigest(), "EDGE_SHA256_WITH_SIZE"


def dataset_provenance(root: str | Path, paths: Iterable[str | Path]) -> dict[str, Any]:
    """Describe the exact local inputs without pretending a partial hash is full."""

    project_root = Path(root).resolve()
    files: list[dict[str, Any]] = []
    for value in paths:
        path = Path(value)
        if not path.is_absolute():
            path = project_root / path
        if not path.is_file():
            files.append({"path": str(value).replace("\\", "/"), "exists": False})
            continue
        digest, method = _sha256(path)
        try:
            display = path.relative_to(project_root).as_posix()
        except ValueError:
            display = str(path)
        stat = path.stat()
        files.append(
            {
                "path": display,
                "exists": True,
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "fingerprint": digest,
                "fingerprint_method": method,
            }
        )
    material = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return {
        "files": files,
        "dataset_fingerprint": hashlib.sha256(material.encode("utf-8")).hexdigest(),
    }


def freeze_parameters(
    root: str | Path,
    family: str,
    parameters: Mapping[str, Any],
    datasets: Mapping[str, Any],
    *,
    campaign_id: str | None = None,
    frozen_at_ms: int | None = None,
) -> dict[str, Any]:
    """Write an immutable parameter selection before final evaluation."""

    project_root = Path(root).resolve()
    normalized = canonical_family(family)
    timestamp = int(frozen_at_ms if frozen_at_ms is not None else time.time() * 1000)
    parameter_hash = hashlib.sha256(
        json.dumps(dict(parameters), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    identifier = campaign_id or f"{timestamp}-{parameter_hash[:12]}"
    relative = REPORT_DIR / "freezes" / normalized / f"{identifier}.json"
    target = project_root / relative
    payload: dict[str, Any] = {
        "schema_version": "hypersmart.economic_parameter_freeze.v1",
        "campaign_id": identifier,
        "family": normalized,
        "frozen_at_ms": timestamp,
        "selected_before_final_evaluation": True,
        "parameters": dict(parameters),
        "parameters_sha256": parameter_hash,
        "dataset_provenance": dict(datasets),
        "path": relative.as_posix(),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != payload:
            raise RuntimeError(f"immutable freeze collision: {target}")
    return payload


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
    }


def _finish(row: dict[str, Any]) -> dict[str, Any]:
    row.update(evaluate_objective(row))
    return row


def build_copy_campaign(
    report: Mapping[str, Any],
    *,
    freeze: Mapping[str, Any] | None,
    datasets: Mapping[str, Any],
) -> dict[str, Any]:
    row = _base(
        "copy_vault",
        freeze=freeze,
        datasets=datasets,
        evidence_paths=("runtime/data/copy_edge_rapport_reel.json",),
    )
    measure = report.get("mesure") if isinstance(report.get("mesure"), Mapping) else {}
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
    return _finish(row)


def build_lead_lag_campaign(
    analysis: Mapping[str, Any],
    *,
    freeze: Mapping[str, Any] | None,
    datasets: Mapping[str, Any],
) -> dict[str, Any]:
    row = _base(
        "lead_lag",
        freeze=freeze,
        datasets=datasets,
        evidence_paths=("runtime/data/bbo_tape.jsonl",),
    )
    row["source_status"] = analysis.get("statut")
    row["source_detail"] = analysis.get("detail")
    row["signal_count"] = analysis.get("chocs_test")
    row["period"] = {
        "observable_horizons_ms": analysis.get("horizons_observables"),
        "hl_intervals": analysis.get("intervalles_hl"),
    }
    # The shadow aggregate is not a position ledger.  Leave economic fields
    # unmeasured until causal paper episodes exist.
    return _finish(row)


def build_cross_campaign(
    report: Mapping[str, Any],
    *,
    freeze: Mapping[str, Any] | None,
    datasets: Mapping[str, Any],
) -> dict[str, Any]:
    row = _base(
        "cross_venue_dislocation_v2",
        freeze=freeze,
        datasets=datasets,
        evidence_paths=("runtime/research/dislocation_final_verdict.json",),
    )
    realistic = (
        report.get("verdict_realiste_16bps")
        if isinstance(report.get("verdict_realiste_16bps"), Mapping)
        else {}
    )
    trades = report.get("trades") if isinstance(report.get("trades"), list) else []
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
        }
    )
    # Existing BBO replay has no independent post-freeze segment and no depth
    # slippage.  Reporting either as proven would manufacture eligibility.
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
        "lead_lag": "Lead-Lag",
        "cross_venue_dislocation_v2": "Cross-Venue Dislocation v2",
    }
    lines = [
        "# Campagnes economiques HyperSmart",
        "",
        "Capital paper consolide: 1 000 USD. Carry OFF. Cross-Venue v1 OFF.",
        "Chaque resultat est separe; aucun PnL latent ou inter-famille n'est additionne.",
        "",
    ]
    for campaign in campaigns:
        family = canonical_family(campaign.get("family"))
        status = str(campaign.get("objective_status") or "NON_ATTEINT")
        net = campaign.get("net_pnl_usd")
        net_text = "NON MESURABLE" if net is None else f"{float(net):+.6f} USD"
        lines.extend(
            [
                f"## {labels.get(family, family)} - OBJECTIF +4 USD : {status}",
                "",
                f"- PnL net realise rapporte: {net_text}",
                f"- Positions ouvertes/fermees: {campaign.get('opened_positions')} / {campaign.get('closed_positions')}",
                f"- LIQUIDATABLE_NET: {campaign.get('liquidatable_net')}",
                f"- ROI: {campaign.get('roi_pct')}",
                f"- Drawdown max USD: {campaign.get('max_drawdown_usd')}",
                f"- Hit rate: {campaign.get('hit_rate')}",
                f"- Profit factor: {campaign.get('profit_factor')}",
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
    "render_campaign_report",
    "write_campaign",
]
