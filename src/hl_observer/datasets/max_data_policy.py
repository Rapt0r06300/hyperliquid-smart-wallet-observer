from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hl_observer.datasets.archive_library import suite_names

SCHEMA = "alina.max_data_policy.v1"
COMPLETED_REGISTRY_SCHEMA = "alina.completed_dataset_suites.v1"
COMPLETED_REGISTRY_RELATIVE = (
    Path("runtime") / "reports" / "autonomous_research" / "COMPLETED_SUITES.json"
)
COMPLETED_HISTORY_LIMIT = 100
DEFAULT_RESERVE_GIB = 25.0
MAX_JOB_DOWNLOAD_GIB = 220.0
TARGET_NET_USD_PER_FAMILY = 4.0
ANALYSIS_MODES = {"economic", "historical", "historical-full", "historical-deep"}

FAMILY_SUITES = {
    "copy_vault": "copy-vault-full",
    "lead_lag": "lead-lag-full",
    "cross_venue_dislocation_v2": "cross-venue-full",
}
REQUIRED_FAMILIES = tuple(FAMILY_SUITES)


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if result < 0:
        return None
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON illisible: {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Objet JSON attendu: {path}")
    return raw


def _valid_sha(value: object) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 40 and all(ch in "0123456789abcdef" for ch in text)


def _explicit_zero(value: object) -> bool:
    """Only a real integer 0 is success; bool/string/None fail closed."""

    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def completed_registry_path(lab_root: str | Path) -> Path:
    return Path(lab_root).resolve() / COMPLETED_REGISTRY_RELATIVE


def _empty_completed_registry() -> dict[str, Any]:
    return {
        "schema": COMPLETED_REGISTRY_SCHEMA,
        "suites": {},
        "history": [],
        "paper_only": True,
        "real_execution": False,
    }


def load_completed_suite_registry(lab_root: str | Path) -> dict[str, Any]:
    """Charge le registre persistant; un registre présent mais corrompu échoue fermé."""

    path = completed_registry_path(lab_root)
    if not path.is_file():
        return _empty_completed_registry()
    raw = _load_json(path)
    if raw.get("schema") != COMPLETED_REGISTRY_SCHEMA:
        raise ValueError(f"Schéma de registre inattendu: {raw.get('schema')}")
    suites = raw.get("suites")
    history = raw.get("history")
    if not isinstance(suites, Mapping) or not isinstance(history, list):
        raise ValueError("Registre des suites terminé incomplet ou invalide.")
    if raw.get("paper_only") is not True or raw.get("real_execution") is not False:
        raise ValueError("Registre des suites sans garde-fous paper/read-only.")
    return {
        **raw,
        "suites": {str(name): dict(row) for name, row in suites.items() if isinstance(row, Mapping)},
        "history": [dict(row) for row in history if isinstance(row, Mapping)],
    }


def completed_suites_from_registry(
    lab_root: str | Path,
    *,
    project_sha: str | None = None,
) -> tuple[str, ...]:
    registry = load_completed_suite_registry(lab_root)
    if project_sha is None:
        return tuple(sorted(str(name) for name in registry["suites"]))
    sha = str(project_sha).strip().lower()
    if not _valid_sha(sha):
        raise ValueError("project_sha invalide pour filtrer les suites terminées.")
    completed = {
        str(row.get("suite") or "")
        for row in registry["history"]
        if str(row.get("project_sha") or "").strip().lower() == sha
        and row.get("completed") is True
    }
    completed.discard("")
    return tuple(sorted(completed))


def record_completed_suite(
    lab_root: str | Path,
    *,
    suite: str,
    mode: str,
    job_id: str,
    project_sha: str,
    workspace: str | Path,
    completed_at_utc: str | None = None,
) -> Path:
    """Enregistre atomiquement une analyse réellement terminée, jamais une simple préparation."""

    suite_name = str(suite).strip()
    if suite_name not in suite_names():
        raise ValueError(f"Suite inconnue dans le registre: {suite_name}")
    mode_name = str(mode).strip()
    if mode_name not in ANALYSIS_MODES:
        raise ValueError(f"Mode non analysant refusé dans le registre: {mode_name}")
    job = str(job_id).strip()
    if not job:
        raise ValueError("job_id absent du registre.")
    sha = str(project_sha).strip().lower()
    if not _valid_sha(sha):
        raise ValueError("project_sha invalide dans le registre.")

    root = Path(lab_root).resolve()
    workspace_path = Path(workspace).resolve()
    try:
        workspace_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Workspace terminé hors du laboratoire persistant.") from exc

    timestamp = completed_at_utc or datetime.now(timezone.utc).isoformat()
    entry = {
        "suite": suite_name,
        "mode": mode_name,
        "job_id": job,
        "project_sha": sha,
        "workspace": str(workspace_path),
        "completed_at_utc": str(timestamp),
        "completed": True,
        "paper_only": True,
        "real_execution": False,
    }
    registry = load_completed_suite_registry(root)
    suites = dict(registry["suites"])
    history = list(registry["history"])
    suites[suite_name] = entry
    history.append(entry)
    history = history[-COMPLETED_HISTORY_LIMIT:]
    payload = {
        "schema": COMPLETED_REGISTRY_SCHEMA,
        "suites": suites,
        "history": history,
        "completed_suite_count": len(suites),
        "history_count": len(history),
        "paper_only": True,
        "real_execution": False,
    }
    path = completed_registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def record_completed_suite_from_result(
    lab_root: str | Path,
    job_result_path: str | Path,
) -> Path:
    """Importe uniquement un JOB_RESULT déjà certifié par le completion guard.

    Ce helper n'est pas le chemin primaire de finalisation : il sert à rejouer/importer
    une preuve déjà finalisée. Toute ambiguïté échoue donc fermée.
    """

    result = _load_json(Path(job_result_path))
    if result.get("schema") != "alina.autonomous_research_result.v1":
        raise ValueError("JOB_RESULT n'a pas le schéma autonome attendu.")
    if result.get("status") != "SUCCESS" or not _explicit_zero(result.get("exit_code")):
        raise ValueError(
            "Seul un job SUCCESS avec exit_code entier explicite 0 peut compléter une suite."
        )
    if result.get("analysis_complete") is not True:
        raise ValueError("JOB_RESULT sans preuve analysis_complete=true.")
    if result.get("completion_recorded") is not True:
        raise ValueError("JOB_RESULT non finalisé: completion_recorded=true est obligatoire.")
    if result.get("paper_only") is not True or result.get("real_execution") is not False:
        raise ValueError("JOB_RESULT sans preuve paper/read-only stricte.")
    if result.get("start_live_collection") is not False:
        raise ValueError(
            "Une collecte live ne peut pas être enregistrée comme analyse FULL/COLD autonome."
        )
    mode = str(result.get("mode") or "")
    if mode not in ANALYSIS_MODES:
        raise ValueError("prepare-only ou mode inconnu ne complète jamais une suite analysée.")
    return record_completed_suite(
        lab_root,
        suite=str(result.get("suite") or ""),
        mode=mode,
        job_id=str(result.get("job_id") or ""),
        project_sha=str(result.get("project_sha") or ""),
        workspace=str(result.get("workspace") or ""),
    )


def load_suite_plans(lab_root: str | Path) -> dict[str, dict[str, Any]]:
    path = Path(lab_root).resolve() / "runtime" / "reports" / "datasets" / "BIBLIOTHEQUE_180GO.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    plans = raw.get("plans") if isinstance(raw, Mapping) else None
    if not isinstance(plans, Mapping):
        return {}
    return {str(name): dict(plan) for name, plan in plans.items() if isinstance(plan, Mapping)}


def _top_family(family_decisions: Iterable[Mapping[str, Any]]) -> str | None:
    rows = [row for row in family_decisions if str(row.get("family") or "") in FAMILY_SUITES]
    if not rows:
        return None
    rows.sort(key=lambda row: (-int(row.get("priority") or 0), str(row.get("family") or "")))
    return str(rows[0].get("family"))


def suite_ladder(top_family: str | None) -> list[str]:
    family_suite = FAMILY_SUITES.get(str(top_family or ""))
    ordered = [
        "economic-full",
        family_suite,
        "microstructure-full",
        "research-lab-full",
        "sqlite-all-safe",
        "full-archive",
    ]
    return list(dict.fromkeys(item for item in ordered if item))


def targets_reached_from_brain(family_decisions: Iterable[Mapping[str, Any]]) -> bool:
    by_family = {
        str(row.get("family") or ""): row
        for row in family_decisions
        if isinstance(row, Mapping)
    }
    return all(
        str(by_family.get(family, {}).get("phase") or "") == "FREEZE_AND_CONFIRM_FORWARD"
        for family in REQUIRED_FAMILIES
    )


def choose_max_data_job(
    *,
    family_decisions: Iterable[Mapping[str, Any]],
    suite_plans: Mapping[str, Mapping[str, Any]],
    completed_suites: Iterable[str] = (),
    free_disk_gib: float,
    all_targets_reached: bool,
    reserve_gib: float = DEFAULT_RESERVE_GIB,
) -> dict[str, Any]:
    """Choisit la prochaine suite utile sans utiliser le PnL holdout comme gradient."""
    decisions = [dict(row) for row in family_decisions if isinstance(row, Mapping)]
    free_gib = _number(free_disk_gib)
    reserve = _number(reserve_gib)
    if free_gib is None or reserve is None:
        raise ValueError("free_disk_gib et reserve_gib doivent être des nombres positifs.")

    completed = {str(value) for value in completed_suites}
    top_family = _top_family(decisions)
    ladder = suite_ladder(top_family)
    target_contract = {
        "target_net_usd_per_family": TARGET_NET_USD_PER_FAMILY,
        "required_families": list(REQUIRED_FAMILIES),
        "independent_targets_required": True,
        "aggregate_substitution_allowed": False,
    }

    if all_targets_reached:
        return {
            "schema": SCHEMA,
            "status": "STOP_PROOF_REACHED",
            "reason": "Les trois objectifs économiques indépendants sont atteints; ne pas consommer plus de données pour retuner le holdout.",
            "recommended_suite": None,
            "recommended_mode": None,
            "download_budget_gib": 0.0,
            "top_family": top_family,
            "completed_suites": sorted(completed),
            "suite_ladder": ladder,
            "target_contract": target_contract,
            "holdout_used_for_ranking": False,
            "paper_read_only": True,
            "real_execution": False,
        }

    rejected: list[dict[str, Any]] = []
    for suite in ladder:
        if suite in completed:
            rejected.append({"suite": suite, "reason": "ALREADY_COMPLETED_FOR_THIS_CODE"})
            continue
        plan = suite_plans.get(suite)
        if not isinstance(plan, Mapping):
            rejected.append({"suite": suite, "reason": "PLAN_MISSING"})
            continue
        missing_assets = int(plan.get("missing_asset_count") or 0)
        if missing_assets:
            rejected.append({
                "suite": suite,
                "reason": "RELEASE_ASSETS_MISSING",
                "missing_asset_count": missing_assets,
            })
            continue
        remaining = _number(plan.get("remaining_download_gib"))
        if remaining is None:
            remaining = _number(plan.get("download_gib"))
        if remaining is None:
            rejected.append({"suite": suite, "reason": "DOWNLOAD_SIZE_UNKNOWN"})
            continue
        required = remaining + reserve
        if required > free_gib:
            rejected.append(
                {
                    "suite": suite,
                    "reason": "INSUFFICIENT_DISK",
                    "remaining_download_gib": round(remaining, 4),
                    "required_with_reserve_gib": round(required, 4),
                    "free_disk_gib": round(free_gib, 4),
                }
            )
            continue

        mode = "economic" if suite == "economic-full" else "historical-deep"
        budget = min(MAX_JOB_DOWNLOAD_GIB, max(1.0, remaining + min(1.0, reserve / 10.0)))
        return {
            "schema": SCHEMA,
            "status": "READY",
            "reason": "Première suite utile non encore traitée pour ce SHA qui tient sur le disque avec réserve de sécurité.",
            "recommended_suite": suite,
            "recommended_mode": mode,
            "download_budget_gib": round(budget, 4),
            "remaining_download_gib": round(remaining, 4),
            "free_disk_gib": round(free_gib, 4),
            "reserve_gib": round(reserve, 4),
            "top_family": top_family,
            "completed_suites": sorted(completed),
            "suite_ladder": ladder,
            "rejected_before_selection": rejected,
            "target_contract": target_contract,
            "holdout_used_for_ranking": False,
            "paper_read_only": True,
            "real_execution": False,
        }

    return {
        "schema": SCHEMA,
        "status": "NO_GO",
        "reason": "Aucune suite supplémentaire utile ne peut être sélectionnée avec les plans, le SHA et l'espace disque actuels.",
        "recommended_suite": None,
        "recommended_mode": None,
        "download_budget_gib": 0.0,
        "top_family": top_family,
        "completed_suites": sorted(completed),
        "suite_ladder": ladder,
        "rejected": rejected,
        "target_contract": target_contract,
        "holdout_used_for_ranking": False,
        "paper_read_only": True,
        "real_execution": False,
    }


def write_decision(output_dir: str | Path, decision: Mapping[str, Any]) -> tuple[Path, Path]:
    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "MAX_DATA_DECISION.json"
    md_path = target / "MAX_DATA_DECISION.md"
    json_path.write_text(
        json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Alina SmartFlow — décision MAX DATA",
        "",
        f"- Statut : **{decision.get('status')}**",
        f"- Prochaine suite : `{decision.get('recommended_suite')}`",
        f"- Mode : `{decision.get('recommended_mode')}`",
        f"- Budget téléchargement : **{decision.get('download_budget_gib')} Gio**",
        f"- Famille prioritaire : `{decision.get('top_family')}`",
        f"- SHA de code pris en compte : `{decision.get('project_sha_scope')}`",
        "- Objectif : **≥ 4,00 $ net séparément sur Copy-Vault, Lead-Lag et Cross-Venue**",
        "- Compensation entre familles : **INTERDITE**",
        "- OOS/forward utilisés comme gradient : **NON**",
        "",
        f"Pourquoi : {decision.get('reason')}",
        "",
        "## Échelle d'escalade",
        "",
    ]
    lines.extend(f"- `{suite}`" for suite in decision.get("suite_ladder") or [])
    lines.extend(
        [
            "",
            "> MAX DATA signifie utiliser le maximum de données utiles et reproductibles, pas retuner sur un holdout déjà observé.",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Choisit la prochaine suite FULL/COLD utile avec garde disque et objectif +4 USD par famille."
    )
    parser.add_argument("--brain-json", required=True)
    parser.add_argument("--lab-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--completed-suite", action="append", default=[])
    parser.add_argument("--project-sha", default=None)
    parser.add_argument("--reserve-gib", type=float, default=DEFAULT_RESERVE_GIB)
    args = parser.parse_args(argv)

    brain = _load_json(Path(args.brain_json))
    decisions_raw = brain.get("family_decisions")
    if not isinstance(decisions_raw, list):
        raise ValueError("family_decisions absent du rapport du cerveau.")
    decisions = [row for row in decisions_raw if isinstance(row, Mapping)]
    lab_root = Path(args.lab_root).resolve()
    plans = load_suite_plans(lab_root)
    if not plans:
        raise ValueError(
            "BIBLIOTHEQUE_180GO.json absente ou sans plans; exécute dataset_bridge plan-all."
        )
    persisted = completed_suites_from_registry(lab_root, project_sha=args.project_sha)
    completed = sorted(set(args.completed_suite) | set(persisted))
    free_gib = shutil.disk_usage(lab_root).free / (1024**3)
    decision = choose_max_data_job(
        family_decisions=decisions,
        suite_plans=plans,
        completed_suites=completed,
        free_disk_gib=free_gib,
        all_targets_reached=targets_reached_from_brain(decisions),
        reserve_gib=args.reserve_gib,
    )
    decision["completed_registry_path"] = str(completed_registry_path(lab_root))
    decision["project_sha_scope"] = str(args.project_sha or "ALL_RECORDED_SHA")
    json_path, md_path = write_decision(args.output_dir, decision)
    print(
        "ALINA_MAX_DATA "
        f"status={decision['status']} suite={decision.get('recommended_suite')} "
        f"mode={decision.get('recommended_mode')} json={json_path} md={md_path}",
        flush=True,
    )
    return 0 if decision["status"] in {"READY", "STOP_PROOF_REACHED"} else 4


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ANALYSIS_MODES",
    "COMPLETED_REGISTRY_RELATIVE",
    "COMPLETED_REGISTRY_SCHEMA",
    "DEFAULT_RESERVE_GIB",
    "FAMILY_SUITES",
    "MAX_JOB_DOWNLOAD_GIB",
    "REQUIRED_FAMILIES",
    "SCHEMA",
    "TARGET_NET_USD_PER_FAMILY",
    "choose_max_data_job",
    "completed_registry_path",
    "completed_suites_from_registry",
    "load_completed_suite_registry",
    "load_suite_plans",
    "record_completed_suite",
    "record_completed_suite_from_result",
    "suite_ladder",
    "targets_reached_from_brain",
    "write_decision",
]
