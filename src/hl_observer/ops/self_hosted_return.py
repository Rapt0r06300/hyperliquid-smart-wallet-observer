from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from hl_observer.ops.autonomous_research_brain import build_decision
from hl_observer.simulation.economic_objective import CANONICAL_FAMILIES

SCHEMA = "alina.self_hosted_return.v1"
CAMPAIGN_DIR = Path("runtime") / "reports" / "economic_campaigns"
MAX_REASON_COUNT = 50
MAX_REASON_CHARS = 500

# Allowlist volontaire : le retour GitHub doit rester petit, lisible et sans payload brut.
METRIC_KEYS = (
    "objective_status",
    "net_pnl_usd",
    "gross_pnl_usd",
    "total_costs_usd",
    "fees_usd",
    "spread_cost_usd",
    "slippage_cost_usd",
    "latency_cost_usd",
    "roi",
    "roi_pct",
    "signal_count",
    "trade_count",
    "sample_count",
    "max_drawdown_usd",
    "max_drawdown_pct",
    "profit_factor",
    "win_rate",
    "proof_status",
    "oos_status",
    "forward_status",
    "placebo_status",
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


def compact_campaign(payload: Mapping[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in METRIC_KEYS:
        value = payload.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            compact[key] = value
    compact["objective_reasons"] = _safe_reasons(payload.get("objective_reasons"))
    return compact


def load_family_summaries(workspace: Path | None) -> dict[str, dict[str, Any] | None]:
    summaries: dict[str, dict[str, Any] | None] = {}
    for family in CANONICAL_FAMILIES:
        if workspace is None:
            summaries[family] = None
            continue
        payload = _load_object(workspace / CAMPAIGN_DIR / f"{family}.json")
        summaries[family] = compact_campaign(payload) if payload is not None else None
    return summaries


def build_return(result_dir: str | Path) -> dict[str, Any]:
    result_path = Path(result_dir).resolve()
    job_result = _load_object(result_path / "JOB_RESULT.json")
    if job_result is None:
        return {
            "schema": SCHEMA,
            "status": "RESULT_MISSING",
            "technical_status": "NO_GO",
            "job_id": None,
            "project_sha": None,
            "suite": None,
            "mode": None,
            "family_summaries": {family: None for family in CANONICAL_FAMILIES},
            "brain_decision": None,
            "next_recommended_job": None,
            "paper_only": True,
            "real_execution": False,
            "message_fr": "JOB_RESULT.json est absent; aucune conclusion économique ne doit être tirée.",
        }

    raw_workspace = job_result.get("workspace")
    workspace = Path(str(raw_workspace)).resolve() if raw_workspace else None
    workspace_exists = bool(workspace and workspace.is_dir())
    families = load_family_summaries(workspace if workspace_exists else None)

    brain: dict[str, Any] | None = None
    if workspace_exists and any(value is not None for value in families.values()):
        try:
            brain = build_decision(workspace)
        except (OSError, ValueError, TypeError):
            brain = None

    next_job = brain.get("next_recommended_job") if isinstance(brain, Mapping) else None
    return {
        "schema": SCHEMA,
        "status": "READY_FOR_ANALYSIS",
        "technical_status": job_result.get("status"),
        "job_id": job_result.get("job_id"),
        "project_sha": job_result.get("project_sha"),
        "request_digest": job_result.get("request_digest"),
        "suite": job_result.get("suite"),
        "mode": job_result.get("mode"),
        "exit_code": job_result.get("exit_code"),
        "workspace_available": workspace_exists,
        "family_summaries": families,
        "brain_decision": brain,
        "next_recommended_job": dict(next_job) if isinstance(next_job, Mapping) else None,
        "paper_only": True,
        "real_execution": False,
        "message_fr": (
            "Retour compact prêt pour analyse GitHub/ChatGPT. Les gros logs et données brutes restent locaux."
        ),
    }


def write_return(result_dir: str | Path, payload: Mapping[str, Any]) -> tuple[Path, Path]:
    target = Path(result_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "ALINA_RETURN.json"
    md_path = target / "ALINA_RETURN.md"
    json_path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Alina SmartFlow — retour compact du gros run",
        "",
        f"- Job : `{payload.get('job_id')}`",
        f"- Statut technique : **{payload.get('technical_status')}**",
        f"- Suite : `{payload.get('suite')}`",
        f"- Mode : `{payload.get('mode')}`",
        f"- SHA : `{payload.get('project_sha')}`",
        "- Trading réel : **NON**",
        "",
        "## Familles économiques",
        "",
        "| Famille | Statut objectif | PnL net USD | Signaux/trades |",
        "|---|---|---:|---:|",
    ]
    families = payload.get("family_summaries")
    if isinstance(families, Mapping):
        for family in CANONICAL_FAMILIES:
            row = families.get(family)
            if isinstance(row, Mapping):
                count = row.get("signal_count") if row.get("signal_count") is not None else row.get("trade_count")
                lines.append(
                    f"| `{family}` | `{row.get('objective_status')}` | {row.get('net_pnl_usd')} | {count} |"
                )
            else:
                lines.append(f"| `{family}` | `NON_MESURE` | - | - |")
    next_job = payload.get("next_recommended_job")
    lines.extend(["", "## Prochain run proposé par le cerveau", ""])
    if isinstance(next_job, Mapping):
        lines.extend(
            [
                f"- Suite : `{next_job.get('suite')}`",
                f"- Mode : `{next_job.get('mode')}`",
                f"- Famille prioritaire : `{next_job.get('top_family')}`",
                f"- Raison : {next_job.get('reason')}",
            ]
        )
    else:
        lines.append("- Aucune recommandation machine-lisible disponible.")
    lines.extend(
        [
            "",
            "> Ce retour résume les preuves disponibles. Il ne transforme jamais un backtest en promesse de rendement.",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Construit le petit retour machine-lisible d'un gros run self-hosted.")
    parser.add_argument("--result-dir", required=True)
    args = parser.parse_args(argv)
    payload = build_return(args.result_dir)
    json_path, md_path = write_return(args.result_dir, payload)
    print(
        "ALINA_RETURN_READY "
        f"status={payload.get('status')} technical={payload.get('technical_status')} "
        f"json={json_path} md={md_path}",
        flush=True,
    )
    return 0 if payload.get("status") == "READY_FOR_ANALYSIS" else 4


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CAMPAIGN_DIR",
    "METRIC_KEYS",
    "SCHEMA",
    "build_return",
    "compact_campaign",
    "load_family_summaries",
    "write_return",
]
