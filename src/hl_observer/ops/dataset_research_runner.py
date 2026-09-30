"""Run the existing historical research stack against an isolated FULL/COLD workspace.

This module deliberately does not implement a strategy. It separates the
project/code root from the historical data root so the canonical local replay,
A/B, walk-forward and diagnostic tools can consume a materialized dataset suite.
It also connects the large SQLite and Research Lab archives through read-only,
streaming inventory stages before deeper economic interpretation.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from hl_observer.datasets.github_release_bridge import DatasetBridgeError
from hl_observer.datasets.source_discovery import (
    source_manifest_summary,
    write_family_source_manifest,
)
from hl_observer.ops.historical_analysis_suite import (
    DEFAULT_STAGE_TIMEOUT_SECONDS,
    REPORTS_RELATIVE_PATH,
    AnalysisStage,
    StageResult,
    _utc_now,
    build_input_inventory,
    run_stage,
    set_below_normal_priority,
    write_reports,
)


def _logs_dir(data_root: Path) -> Path:
    accented = data_root / "logs" / "logs à envoyer"
    plain = data_root / "logs" / "logs a envoyer"
    if accented.exists():
        return accented
    return plain


def build_dataset_stage_plan(
    project_root: Path,
    data_root: Path,
    output_dir: Path,
    *,
    full: bool = False,
    deep: bool = False,
    timeout_seconds: int = DEFAULT_STAGE_TIMEOUT_SECONDS,
) -> tuple[AnalysisStage, ...]:
    project_root = project_root.resolve()
    data_root = data_root.resolve()
    py = sys.executable
    replay = data_root / "runtime" / "replay"
    merged = replay / "_merged"
    candidates = merged / "candidates.jsonl"
    marks = merged / "marks.jsonl"
    logs = _logs_dir(data_root)
    research_lab = data_root / "runtime" / "research_lab"
    cache = (
        project_root
        / REPORTS_RELATIVE_PATH
        / "_dataset_cache"
        / "ab_replay_fixed_50_usdt.json"
    )

    stages: list[AnalysisStage] = [
        AnalysisStage(
            "sqlite_inventory",
            "Inventaire SQLite FULL/COLD",
            "Ouvre les bases saines en lecture seule, décrit leur schéma et quarantaine les noms corrompus.",
            (
                py,
                "-m",
                "hl_observer.ops.dataset_sqlite_inventory",
                "--root",
                str(data_root),
            ),
            required_paths=(data_root,),
            timeout_seconds=max(timeout_seconds, 1_800),
        ),
        AnalysisStage(
            "sqlite_research_catalog",
            "Catalogue de recherche SQLite FULL/COLD",
            "Expose uniquement les tables/colonnes économiques autorisées comme sources historiques read-only.",
            (
                py,
                "-m",
                "hl_observer.ops.dataset_sqlite_research",
                "--root",
                str(data_root),
            ),
            required_paths=(data_root,),
            timeout_seconds=max(timeout_seconds, 1_800),
        ),
        AnalysisStage(
            "research_lab_probe",
            "Sonde streaming du Research Lab",
            "Parcourt jusqu'à 0,25 Gio sur chacun des trois plus gros JSONL et conserve un checkpoint reprenable.",
            (
                py,
                "-m",
                "hl_observer.ops.dataset_research_inventory",
                "--root",
                str(data_root),
                "--max-files",
                "3",
                "--max-gib-per-file",
                "0.25",
                "--heartbeat-seconds",
                "5",
            ),
            required_paths=(research_lab,),
            timeout_seconds=max(timeout_seconds, 3_600),
        ),
        AnalysisStage(
            "merge_replay",
            "Consolidation replay FULL/COLD",
            "Fusionne les fragments candidates/marks du workspace, sans modifier les sources archivées.",
            (py, "-m", "hl_observer.runtime.replay_recorder", "--base", str(replay)),
            required_paths=(replay,),
            timeout_seconds=timeout_seconds,
        ),
        AnalysisStage(
            "pnl_improvement_lab",
            "Laboratoire historique PnL FULL/COLD",
            "Rejoue les logs présents dans le workspace avec train/validation/holdout chronologiques.",
            (
                py,
                "-m",
                "hl_observer.ops.pnl_improvement_lab",
                "--logs-dir",
                str(logs),
                "--output-dir",
                str(output_dir),
                "--comparison-notional",
                "50",
            ),
            required_paths=(logs,),
            timeout_seconds=timeout_seconds,
        ),
        AnalysisStage(
            "replay_data_quality",
            "Qualité des données FULL/COLD",
            "Mesure couverture, timestamps, résolution et doublons avec l'outil canonique du projet.",
            (
                py,
                str(project_root / "tools" / "qualite_donnees_replay.py"),
                str(data_root),
            ),
            required_paths=(candidates, marks),
            timeout_seconds=timeout_seconds,
        ),
        AnalysisStage(
            "market_truth_replay",
            "Vérité de marché FULL/COLD",
            "Mesure l'exécutabilité et les coûts sur les ticks présents dans le workspace.",
            (
                py,
                "-m",
                "hl_observer.ops.market_truth_replay",
                "--root",
                str(data_root),
                "--output-dir",
                str(output_dir / "market_truth"),
                "--notional",
                "50",
            ),
            required_paths=(data_root / "runtime" / "data" / "market_ticks",),
            timeout_seconds=timeout_seconds,
        ),
        AnalysisStage(
            "lead_lag_evidence",
            "Preuve Lead-Lag FULL/COLD",
            "Relance la preuve causale gelée sur les sources présentes dans le workspace.",
            (
                py,
                "-m",
                "hl_observer.ops.lead_lag_evidence",
                "--root",
                str(data_root),
                "--output",
                str(output_dir / "lead_lag_shadow.json"),
                "--freeze",
            ),
            required_paths=(data_root / "runtime" / "data" / "bbo_tape.jsonl",),
            timeout_seconds=timeout_seconds,
        ),
        AnalysisStage(
            "ab_exact",
            "Replay A/B exact FULL/COLD",
            "Compare le bras de référence et le bras candidat sur candidates/marks historiques.",
            (
                py,
                "-m",
                "hl_observer.backtesting.ab_flag_replay",
                "--candidates",
                str(candidates),
                "--marks",
                str(marks),
                "--out",
                str(output_dir / "ab_replay.json"),
                "--notional-usd",
                "50",
                "--cache-path",
                str(cache),
            ),
            required_paths=(candidates, marks),
            timeout_seconds=timeout_seconds,
        ),
        AnalysisStage(
            "realtime_replay",
            "Replay du flux FULL/COLD",
            "Rejoue les décisions archivées sans réseau.",
            (
                py,
                "-m",
                "hl_observer",
                "realtime-replay",
                "--from-logs",
                str(logs),
                "--speed",
                "5x",
                "--limit",
                "2000",
            ),
            required_paths=(logs,),
            timeout_seconds=timeout_seconds,
        ),
        AnalysisStage(
            "closed_ledger_replay",
            "Replay causal du ledger FULL/COLD",
            "Rejoue les trades clôturés archivés sans lookahead.",
            (
                py,
                "-m",
                "hl_observer",
                "closed-ledger-replay",
                "--from-logs",
                str(logs),
                "--output-dir",
                str(output_dir / "closed_ledger"),
            ),
            required_paths=(logs,),
            timeout_seconds=timeout_seconds,
        ),
        AnalysisStage(
            "strategy_tournament",
            "Tournoi historique FULL/COLD",
            "Compare les stratégies sur fenêtres train/validation/holdout séparées.",
            (
                py,
                "-m",
                "hl_observer",
                "strategy-tournament",
                "--from-logs",
                str(logs),
                "--output-dir",
                str(output_dir / "strategy_tournament"),
            ),
            required_paths=(logs,),
            timeout_seconds=timeout_seconds,
        ),
        AnalysisStage(
            "pnl_audit",
            "Audit PnL FULL/COLD",
            "Réconcilie décisions, coûts et PnL à partir des données archivées.",
            (
                py,
                "-m",
                "hl_observer",
                "pnl-audit",
                "--from-logs",
                str(logs),
                "--output-dir",
                str(output_dir / "pnl_audit"),
            ),
            required_paths=(logs,),
            timeout_seconds=timeout_seconds,
        ),
        AnalysisStage(
            "loss_attribution",
            "Attribution des gains et pertes FULL/COLD",
            "Ventile PnL, frais et causes racines.",
            (py, "-m", "hl_observer", "loss-attribution", "--from-logs", str(logs)),
            required_paths=(logs,),
            timeout_seconds=timeout_seconds,
        ),
        AnalysisStage(
            "latency_report",
            "Latence FULL/COLD",
            "Mesure l'âge des signaux archivés.",
            (py, "-m", "hl_observer", "realtime-latency-report", "--from-logs", str(logs)),
            required_paths=(logs,),
            timeout_seconds=timeout_seconds,
        ),
        AnalysisStage(
            "freshness_diagnostics",
            "Fraîcheur FULL/COLD",
            "Explique les signaux stale et les limites de la collecte historique.",
            (py, "-m", "hl_observer", "freshness-diagnostics", "--from-logs", str(logs)),
            required_paths=(logs,),
            timeout_seconds=timeout_seconds,
        ),
    ]

    if full or deep:
        long_timeout = max(timeout_seconds, 21_600)
        stages.extend(
            [
                AnalysisStage(
                    "research_lab_full_stream",
                    "Scan complet reprenable du Research Lab",
                    "Reprend les checkpoints puis parcourt tous les JSONL Research Lab jusqu'à EOF, sans limite de volume.",
                    (
                        py,
                        "-m",
                        "hl_observer.ops.dataset_research_inventory",
                        "--root",
                        str(data_root),
                        "--heartbeat-seconds",
                        "5",
                    ),
                    required_paths=(research_lab,),
                    timeout_seconds=long_timeout,
                    optional=True,
                ),
                AnalysisStage(
                    "walk_forward",
                    "Walk-forward FULL/COLD",
                    "Valide la robustesse temporelle sur les logs archivés.",
                    (
                        py,
                        "-m",
                        "hl_observer",
                        "walk-forward-profit-validation",
                        "--from-logs",
                        str(logs),
                        "--output-dir",
                        str(output_dir / "walk_forward"),
                    ),
                    required_paths=(logs,),
                    timeout_seconds=timeout_seconds,
                ),
                AnalysisStage(
                    "anti_overfit",
                    "Anti-overfit FULL/COLD",
                    "Refuse les configurations qui ne survivent pas hors entraînement.",
                    (
                        py,
                        "-m",
                        "hl_observer",
                        "anti-overfit-audit",
                        "--from-logs",
                        str(logs),
                        "--output-dir",
                        str(output_dir / "anti_overfit"),
                    ),
                    required_paths=(logs,),
                    timeout_seconds=timeout_seconds,
                ),
            ]
        )

    if deep:
        deep_timeout = max(timeout_seconds, 7_200)
        stages.append(
            AnalysisStage(
                "scenario_search",
                "Recherche de scénarios FULL/COLD",
                "Explore les scénarios existants de façon reprenable; jamais dans le runtime live.",
                (
                    py,
                    "-c",
                    (
                        "from hl_observer.backtesting.recherche_scenario import chercher_toutes;"
                        f" chercher_toutes({str(data_root)!r})"
                    ),
                ),
                required_paths=(candidates, marks),
                timeout_seconds=deep_timeout,
                optional=True,
            )
        )
    return tuple(stages)


def _read_optional_json(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _augment_report(
    report_json: Path,
    *,
    project_root: Path,
    data_root: Path,
    suite: str,
    source_manifest: Path,
) -> None:
    try:
        payload = json.loads(report_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    dataset_reports = data_root / "runtime" / "reports" / "datasets"
    payload["dataset_suite"] = suite
    payload["project_root"] = str(project_root)
    payload["data_root"] = str(data_root)
    payload["dataset_source_manifest"] = str(source_manifest)
    payload["dataset_source_summary"] = source_manifest_summary(data_root)
    payload["source_release_id"] = 371149058
    payload["sqlite_inventory"] = _read_optional_json(dataset_reports / "SQLITE_INVENTORY.json")
    payload["sqlite_research_catalog"] = _read_optional_json(
        dataset_reports / "SQLITE_RESEARCH_CATALOG.json"
    )
    payload["research_lab_stream_profile"] = _read_optional_json(
        dataset_reports / "RESEARCH_LAB_STREAM_PROFILE.json"
    )
    report_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_dataset_suite(
    project_root: Path,
    data_root: Path,
    *,
    suite: str,
    full: bool = False,
    deep: bool = False,
    timeout_seconds: int = DEFAULT_STAGE_TIMEOUT_SECONDS,
    stage_runner=run_stage,
) -> tuple[int, Path, tuple[StageResult, ...]]:
    project_root = project_root.resolve()
    data_root = data_root.resolve()
    if not data_root.is_dir():
        raise DatasetBridgeError(f"Workspace de données absent: {data_root}")
    source_manifest = write_family_source_manifest(data_root)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = (
        project_root
        / "runtime"
        / "reports"
        / "datasets"
        / "historical"
        / suite
        / f"run_{stamp}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    set_below_normal_priority()
    mode = "deep" if deep else ("full" if full else "standard")
    plan = build_dataset_stage_plan(
        project_root,
        data_root,
        output_dir,
        full=full,
        deep=deep,
        timeout_seconds=timeout_seconds,
    )
    results: list[StageResult] = []
    print(
        f"[DATASET-LAB] suite={suite} mode={mode} data_root={data_root} etapes={len(plan)}",
        flush=True,
    )
    started_at = _utc_now()
    for index, stage in enumerate(plan, 1):
        print(f"[{index}/{len(plan)}] {stage.title}", flush=True)
        result = stage_runner(stage, root=project_root, output_dir=output_dir)
        results.append(result)
        print(f"  -> {result.status}: {result.message}", flush=True)
        if result.status == "INTERRUPTED":
            break

    inventory = build_input_inventory(data_root)
    finished_at = _utc_now()
    markdown_path, json_path = write_reports(
        output_dir,
        root=data_root,
        started_at=started_at,
        finished_at=finished_at,
        mode=f"dataset:{suite}:{mode}",
        inventory=inventory,
        results=results,
    )
    _augment_report(
        json_path,
        project_root=project_root,
        data_root=data_root,
        suite=suite,
        source_manifest=source_manifest,
    )
    latest_dir = output_dir.parent
    canonical_md = latest_dir / "RAPPORT_DATASET_LATEST.md"
    canonical_json = latest_dir / "report_dataset_latest.json"
    canonical_md.write_text(markdown_path.read_text(encoding="utf-8"), encoding="utf-8")
    canonical_json.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
    passed = sum(result.status == "PASSED" for result in results)
    failed = sum(result.status == "FAILED" for result in results)
    if passed == 0:
        return 2, markdown_path, tuple(results)
    if failed:
        return 1, markdown_path, tuple(results)
    return 0, markdown_path, tuple(results)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Branche le laboratoire historique principal sur un workspace FULL/COLD."
    )
    parser.add_argument("--root", default=".", help="Racine du code Alina SmartFlow.")
    parser.add_argument("--data-root", required=True, help="Workspace FULL/COLD reconstruit.")
    parser.add_argument("--suite", required=True)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--deep", action="store_true")
    parser.add_argument(
        "--stage-timeout-seconds",
        type=int,
        default=DEFAULT_STAGE_TIMEOUT_SECONDS,
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    timeout = max(60, int(args.stage_timeout_seconds))
    try:
        code, report, _ = run_dataset_suite(
            Path(args.root),
            Path(args.data_root),
            suite=str(args.suite),
            full=bool(args.full or args.deep),
            deep=bool(args.deep),
            timeout_seconds=timeout,
        )
    except (DatasetBridgeError, OSError, json.JSONDecodeError) as exc:
        print(f"DATASET_LAB_NO_GO: {exc}")
        return 2
    print(f"[DATASET-LAB] rapport={report}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
