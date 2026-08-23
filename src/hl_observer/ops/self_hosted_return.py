from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.ops.autonomous_research_brain import build_decision
from hl_observer.ops.final_economic_certification import certify_workspace
from hl_observer.simulation.economic_objective import CANONICAL_FAMILIES

SCHEMA = "alina.self_hosted_return.v1"
CAMPAIGN_DIR = Path("runtime") / "reports" / "economic_campaigns"
VNEXT_SUMMARY_RELATIVE = CAMPAIGN_DIR / "research_vnext" / "VNext_SUMMARY.json"
LEAD_LAG_DIAGNOSTIC_FILENAME = "LEAD_LAG_CAUSAL_GAP_DIAGNOSTIC.json"
LEAD_LAG_DIAGNOSTIC_FALLBACK = CAMPAIGN_DIR / "raw" / "lead_lag_causal_coverage.json"
MAX_REASON_COUNT = 50
MAX_REASON_CHARS = 500
MAX_DIAGNOSTIC_EVENTS = 20

METRIC_KEYS = (
    "objective_status", "eligible_net_pnl_usd", "proof_net_pnl_usd",
    "net_pnl_usd", "gross_pnl_usd", "total_costs_usd", "fees_usd",
    "spread_cost_usd", "slippage_cost_usd", "latency_cost_usd", "roi",
    "roi_pct", "signal_count", "trade_count", "sample_count",
    "opened_positions", "closed_positions", "max_drawdown_usd",
    "max_drawdown_pct", "profit_factor", "win_rate", "liquidatable_net",
    "parameters_frozen", "duplicate_trade_ids", "trade_ids_count",
    "proof_status", "oos_status", "forward_status", "placebo_status",
)


def _load_object(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _safe_reasons(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:MAX_REASON_COUNT]:
        text = str(item).strip()
        if text:
            result.append(text[:MAX_REASON_CHARS])
    return result


def _safe_scalar(value: object) -> str | int | float | bool | None:
    return value if isinstance(value, (str, int, float, bool)) or value is None else None


def _compact_segment(value: object, *, kind: str) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    keys = ("sample_count", "gross_pnl_usd", "fees_usd", "spread_cost_usd", "slippage_cost_usd", "latency_cost_usd", "net_pnl_usd", "liquidatable_net", "LIQUIDATABLE_NET", "duplicate_trade_ids", "trade_ids_count")
    compact = {key: value.get(key) for key in keys if isinstance(value.get(key), (str, int, float, bool)) or value.get(key) is None}
    if kind == "oos":
        compact["no_lookahead"] = value.get("no_lookahead") is True
    elif kind == "forward":
        compact["post_freeze"] = value.get("post_freeze") is True
    return compact


def compact_campaign(payload: Mapping[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in METRIC_KEYS:
        value = payload.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[key] = value
    compact["objective_reasons"] = _safe_reasons(payload.get("objective_reasons"))
    compact["oos"] = _compact_segment(payload.get("oos"), kind="oos")
    compact["forward"] = _compact_segment(payload.get("forward"), kind="forward")
    placebos = payload.get("placebos")
    compact["placebos"] = {"beaten": placebos.get("beaten") is True} if isinstance(placebos, Mapping) else None
    return compact


def compact_vnext_summary(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    raw_families = payload.get("families")
    families: dict[str, dict[str, Any]] = {}
    if isinstance(raw_families, Mapping):
        for family in ("copy_vault", "lead_lag", "cross_venue"):
            row = raw_families.get(family)
            if not isinstance(row, Mapping):
                continue
            families[family] = {"status": _safe_scalar(row.get("status")), "selection_eligible": row.get("selection_eligible") is True, "physical_freeze_allowed": row.get("physical_freeze_allowed") is True, "freeze_candidate_sha256": _safe_scalar(row.get("freeze_candidate_sha256"))}
    return {"schema_version": _safe_scalar(payload.get("schema_version")), "selection_scope": _safe_scalar(payload.get("selection_scope")), "heldout_evaluated": payload.get("heldout_evaluated") is True, "canonical_campaigns_mutated": payload.get("canonical_campaigns_mutated") is True, "families": families, "paper_read_only": payload.get("paper_read_only") is True, "real_execution": payload.get("real_execution") is True}


def compact_lead_lag_diagnostic(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    availability = payload.get("causal_book_availability")
    if not isinstance(availability, Mapping):
        availability = payload
    raw_counts = availability.get("classification_counts")
    if not isinstance(raw_counts, Mapping):
        raw_counts = availability.get("classifications")
    counts: dict[str, int] = {}
    if isinstance(raw_counts, Mapping):
        for key, value in raw_counts.items():
            try:
                counts[str(key)[:120]] = int(value)
            except (TypeError, ValueError, OverflowError):
                continue
    compact_events: list[dict[str, Any]] = []
    raw_events = availability.get("events")
    if isinstance(raw_events, list):
        for row in raw_events[:MAX_DIAGNOSTIC_EVENTS]:
            if not isinstance(row, Mapping):
                continue
            compact_events.append({"event_ts_ms": _safe_scalar(row.get("event_ts_ms", row.get("trigger_ts_ms"))), "classification": _safe_scalar(row.get("classification")), "next_book_delay_ms": _safe_scalar(row.get("next_book_delay_ms", row.get("following_book_delay_ms"))), "gap_count_delta": _safe_scalar(row.get("gap_count_delta")), "reconnect_count_delta": _safe_scalar(row.get("reconnect_count_delta")), "explicit_collector_gap": row.get("explicit_collector_gap") is True or bool(row.get("explicit_gap_evidence")), "loader_incomplete": bool(row.get("loader_incomplete_evidence"))})
    return {"schema_version": _safe_scalar(payload.get("schema_version")), "purpose": _safe_scalar(payload.get("purpose")), "diagnostic_threshold_bps": _safe_scalar(payload.get("diagnostic_threshold_bps", payload.get("diagnostic_shock_threshold_bps"))), "economic_threshold_bps": _safe_scalar(payload.get("economic_threshold_bps", payload.get("economic_shock_threshold_bps_unchanged"))), "economic_parameters_modified": payload.get("economic_parameters_modified") is True, "event_count": _safe_scalar(availability.get("event_count", availability.get("shock_count"))), "root_cause": _safe_scalar(availability.get("root_cause")), "classification_counts": counts, "max_causal_book_delay_ms": _safe_scalar(availability.get("max_causal_book_delay_ms", availability.get("max_book_delay_ms"))), "first_book_delay_p50_ms": _safe_scalar(availability.get("first_book_delay_p50_ms")), "first_book_delay_p95_ms": _safe_scalar(availability.get("first_book_delay_p95_ms")), "events": compact_events, "events_truncated": isinstance(raw_events, list) and len(raw_events) > MAX_DIAGNOSTIC_EVENTS, "paper_read_only": payload.get("paper_read_only") is True, "real_execution": payload.get("real_execution") is True}


def load_family_summaries(workspace: Path | None) -> dict[str, dict[str, Any] | None]:
    summaries: dict[str, dict[str, Any] | None] = {}
    for family in CANONICAL_FAMILIES:
        if workspace is None:
            summaries[family] = None
            continue
        payload = _load_object(workspace / CAMPAIGN_DIR / f"{family}.json")
        summaries[family] = compact_campaign(payload) if payload is not None else None
    return summaries


def _load_vnext_summary(workspace: Path | None) -> dict[str, Any] | None:
    return None if workspace is None else compact_vnext_summary(_load_object(workspace / VNEXT_SUMMARY_RELATIVE))


def _load_lead_lag_diagnostic(result_path: Path, workspace: Path | None) -> dict[str, Any] | None:
    direct = _load_object(result_path / LEAD_LAG_DIAGNOSTIC_FILENAME)
    if direct is not None:
        return compact_lead_lag_diagnostic(direct)
    if workspace is None:
        return None
    return compact_lead_lag_diagnostic(_load_object(workspace / LEAD_LAG_DIAGNOSTIC_FALLBACK))


def build_return(result_dir: str | Path) -> dict[str, Any]:
    result_path = Path(result_dir).resolve()
    job_result = _load_object(result_path / "JOB_RESULT.json")
    if job_result is None:
        return {"schema": SCHEMA, "status": "RESULT_MISSING", "technical_status": "NO_GO", "job_id": None, "project_sha": None, "suite": None, "mode": None, "family_summaries": {family: None for family in CANONICAL_FAMILIES}, "economic_certification": None, "brain_decision": None, "next_recommended_job": None, "vnext_research": None, "lead_lag_causal_diagnostic": None, "paper_only": True, "real_execution": False, "message_fr": "JOB_RESULT.json est absent; aucune conclusion économique ne doit être tirée."}
    raw_workspace = job_result.get("workspace")
    workspace = Path(str(raw_workspace)).resolve() if raw_workspace else None
    workspace_exists = bool(workspace and workspace.is_dir())
    usable_workspace = workspace if workspace_exists else None
    families = load_family_summaries(usable_workspace)
    economic_certification = certify_workspace(workspace) if workspace_exists and any(value is not None for value in families.values()) else None
    brain: dict[str, Any] | None = None
    if workspace_exists and any(value is not None for value in families.values()):
        try:
            brain = build_decision(workspace)
        except (OSError, ValueError, TypeError):
            brain = None
    next_job = brain.get("next_recommended_job") if isinstance(brain, Mapping) else None
    all_certified = bool(isinstance(economic_certification, Mapping) and economic_certification.get("all_families_certified") is True)
    return {"schema": SCHEMA, "status": "READY_FOR_ANALYSIS", "technical_status": job_result.get("status"), "job_id": job_result.get("job_id"), "project_sha": job_result.get("project_sha"), "request_digest": job_result.get("request_digest"), "suite": job_result.get("suite"), "mode": job_result.get("mode"), "exit_code": job_result.get("exit_code"), "workspace_available": workspace_exists, "family_summaries": families, "economic_certification": economic_certification, "brain_decision": brain, "next_recommended_job": dict(next_job) if isinstance(next_job, Mapping) else None, "vnext_research": _load_vnext_summary(usable_workspace), "lead_lag_causal_diagnostic": _load_lead_lag_diagnostic(result_path, usable_workspace), "paper_only": True, "real_execution": False, "message_fr": "Les trois familles sont certifiées séparément avec la gate économique canonique; aucune compensation inter-familles." if all_certified else "Retour compact prêt. La certification économique reste fail-closed tant que chaque famille n'est pas certifiée séparément; aucune compensation inter-familles."}


def write_return(result_dir: str | Path, payload: Mapping[str, Any]) -> tuple[Path, Path]:
    target = Path(result_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "ALINA_RETURN.json"
    md_path = target / "ALINA_RETURN.md"
    json_path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    certification = payload.get("economic_certification")
    all_certified = isinstance(certification, Mapping) and certification.get("all_families_certified") is True
    lines = ["# Alina SmartFlow — retour compact du gros run", "", f"- Job : `{payload.get('job_id')}`", f"- Statut technique : **{payload.get('technical_status')}**", f"- Suite : `{payload.get('suite')}`", f"- Mode : `{payload.get('mode')}`", f"- SHA : `{payload.get('project_sha')}`", "- Trading réel : **NON**", f"- Certification économique 3/3 : **{'OUI' if all_certified else 'NON'}**", "- Compensation PnL entre familles : **INTERDITE**", "", "## Familles économiques", "", "| Famille | Certification | Objectif | Net éligible USD | LIQUIDATABLE_NET | OOS+ | Forward+ post-freeze | Placebo battu |", "|---|---|---|---:|---|---|---|---|"]
    families = payload.get("family_summaries")
    cert_rows = certification.get("families") if isinstance(certification, Mapping) else {}
    if isinstance(families, Mapping):
        for family in CANONICAL_FAMILIES:
            row = families.get(family)
            cert = cert_rows.get(family) if isinstance(cert_rows, Mapping) else None
            if isinstance(row, Mapping):
                lines.append(f"| `{family}` | `{cert.get('status') if isinstance(cert, Mapping) else 'NO_GO'}` | `{row.get('objective_status')}` | {row.get('eligible_net_pnl_usd')} | {cert.get('liquidatable_net') if isinstance(cert, Mapping) else False} | {cert.get('oos_positive') if isinstance(cert, Mapping) else False} | {(cert.get('forward_positive') is True and cert.get('forward_post_freeze') is True) if isinstance(cert, Mapping) else False} | {cert.get('placebo_beaten') if isinstance(cert, Mapping) else False} |")
            else:
                lines.append(f"| `{family}` | `NO_GO` | `NON_MESURE` | - | False | False | False | False |")
    vnext = payload.get("vnext_research")
    lines.extend(["", "## Recherche vNext TRAIN-only", ""])
    if isinstance(vnext, Mapping):
        lines.append(f"- Scope : `{vnext.get('selection_scope')}` ; heldout évalué : `{vnext.get('heldout_evaluated')}`")
        vnext_families = vnext.get("families")
        if isinstance(vnext_families, Mapping):
            for family, row in vnext_families.items():
                if isinstance(row, Mapping):
                    lines.append(f"- `{family}` : status=`{row.get('status')}` ; selection_eligible=`{row.get('selection_eligible')}` ; physical_freeze_allowed=`{row.get('physical_freeze_allowed')}` ; freeze_candidate=`{row.get('freeze_candidate_sha256')}`")
    else:
        lines.append("- Aucun résumé vNext allowlisté disponible.")
    diagnostic = payload.get("lead_lag_causal_diagnostic")
    lines.extend(["", "## Diagnostic causal Lead-Lag", ""])
    if isinstance(diagnostic, Mapping):
        lines.extend([f"- Cause racine : `{diagnostic.get('root_cause')}`", f"- Événements : `{diagnostic.get('event_count')}`", f"- Classes : `{json.dumps(diagnostic.get('classification_counts') or {}, sort_keys=True)}`", f"- Délai premier carnet p50/p95 : `{diagnostic.get('first_book_delay_p50_ms')}` / `{diagnostic.get('first_book_delay_p95_ms')}` ms", f"- Événements publics détaillés : `{len(diagnostic.get('events') or [])}` (bornés à {MAX_DIAGNOSTIC_EVENTS})"])
    else:
        lines.append("- Aucun diagnostic causal allowlisté disponible.")
    next_job = payload.get("next_recommended_job")
    lines.extend(["", "## Prochain run proposé par le cerveau", ""])
    if isinstance(next_job, Mapping):
        lines.extend([f"- Suite : `{next_job.get('suite')}`", f"- Mode : `{next_job.get('mode')}`", f"- Famille prioritaire : `{next_job.get('top_family')}`", f"- Raison : {next_job.get('reason')}"])
    else:
        lines.append("- Aucune recommandation machine-lisible disponible.")
    lines.extend(["", "> Ce retour résume les preuves disponibles. Il ne transforme jamais un backtest en promesse de rendement.", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Construit le petit retour machine-lisible d'un gros run self-hosted.")
    parser.add_argument("--result-dir", required=True)
    args = parser.parse_args(argv)
    payload = build_return(args.result_dir)
    json_path, md_path = write_return(args.result_dir, payload)
    print("ALINA_RETURN_READY " f"status={payload.get('status')} technical={payload.get('technical_status')} " f"json={json_path} md={md_path}", flush=True)
    return 0 if payload.get("status") == "READY_FOR_ANALYSIS" else 4


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CAMPAIGN_DIR", "LEAD_LAG_DIAGNOSTIC_FILENAME", "MAX_DIAGNOSTIC_EVENTS", "METRIC_KEYS", "SCHEMA", "VNEXT_SUMMARY_RELATIVE", "build_return", "compact_campaign", "compact_lead_lag_diagnostic", "compact_vnext_summary", "load_family_summaries", "write_return"]
