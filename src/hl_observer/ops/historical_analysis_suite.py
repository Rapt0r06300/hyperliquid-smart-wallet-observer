"""Bounded orchestration for HyperSmart local replay and backtest tools.

This module does not implement another strategy engine. It runs the existing,
canonical analysis commands against local replay files and simulation logs,
captures every output, and writes one consolidated report.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

REPORTS_RELATIVE_PATH = Path("runtime") / "reports" / "backtest_replay"
DEFAULT_STAGE_TIMEOUT_SECONDS = 1_800
HEARTBEAT_SECONDS = 10.0


@dataclass(frozen=True)
class AnalysisStage:
    key: str
    title: str
    purpose: str
    command: tuple[str, ...]
    required_paths: tuple[Path, ...] = ()
    timeout_seconds: int = DEFAULT_STAGE_TIMEOUT_SECONDS
    optional: bool = False


@dataclass(frozen=True)
class StageResult:
    key: str
    title: str
    status: str
    return_code: int | None
    duration_seconds: float
    log_path: str
    message: str
    command: tuple[str, ...]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_has_data(path: Path) -> bool:
    if path.is_file():
        try:
            return path.stat().st_size > 0
        except OSError:
            return False
    if path.is_dir():
        try:
            return any(item.is_file() for item in path.iterdir())
        except OSError:
            return False
    return False


def _directory_inventory(path: Path) -> dict[str, object]:
    files = 0
    total_bytes = 0
    latest_mtime = 0.0
    if path.exists():
        try:
            for item in path.rglob("*"):
                if not item.is_file():
                    continue
                files += 1
                stat = item.stat()
                total_bytes += stat.st_size
                latest_mtime = max(latest_mtime, stat.st_mtime)
        except OSError:
            pass
    return {
        "path": str(path),
        "exists": path.exists(),
        "file_count": files,
        "total_bytes": total_bytes,
        "latest_mtime_utc": (
            datetime.fromtimestamp(latest_mtime, tz=timezone.utc).isoformat()
            if latest_mtime
            else None
        ),
    }


def build_input_inventory(root: Path) -> dict[str, object]:
    replay = root / "runtime" / "replay"
    logs = root / "logs" / "logs a envoyer"
    if not logs.exists():
        accented = root / "logs" / "logs à envoyer"
        if accented.exists():
            logs = accented
    merged = replay / "_merged"
    inventory = {
        "replay": _directory_inventory(replay),
        "logs_to_send": _directory_inventory(logs),
    }
    for name in ("candidates.jsonl", "marks.jsonl"):
        path = merged / name
        try:
            size = path.stat().st_size
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            size = 0
            mtime = None
        inventory[f"merged_{name.removesuffix('.jsonl')}"] = {
            "path": str(path),
            "exists": path.exists(),
            "bytes": size,
            "mtime_utc": mtime,
        }
    return inventory


def resolve_logs_dir(root: Path) -> Path:
    plain = root / "logs" / "logs a envoyer"
    accented = root / "logs" / "logs à envoyer"
    if accented.exists():
        return accented
    return plain


def build_stage_plan(
    root: Path,
    output_dir: Path,
    *,
    full: bool = False,
    deep: bool = False,
    timeout_seconds: int = DEFAULT_STAGE_TIMEOUT_SECONDS,
) -> tuple[AnalysisStage, ...]:
    """Return the deterministic analysis plan.

    Standard mode covers replay consolidation, data quality, exact A/B replay,
    causal ledger replay, walk-forward strategy comparison, PnL attribution,
    latency and freshness. ``full`` adds explicit anti-overfit and OOS reports.
    ``deep`` also runs the resumable exhaustive scenario search.
    """

    py = sys.executable
    replay = root / "runtime" / "replay"
    merged = replay / "_merged"
    candidates = merged / "candidates.jsonl"
    marks = merged / "marks.jsonl"
    logs = resolve_logs_dir(root)

    plan: list[AnalysisStage] = [
        AnalysisStage(
            "merge_replay",
            "Consolidation replay",
            "Fusionne les fragments et archives candidates/marks sans modifier les sources.",
            (py, "-m", "hl_observer.runtime.replay_recorder", "--base", str(replay)),
            timeout_seconds=timeout_seconds,
        ),
        AnalysisStage(
            "pnl_improvement_lab",
            "Laboratoire historique PnL",
            (
                "Reconstruit les sessions archivees, reconcilie le PnL et teste des "
                "pistes en train/validation/holdout chronologiques."
            ),
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
            "Qualite des donnees replay",
            "Mesure etiquetage, timestamps, couverture, resolution et doublons.",
            (py, str(root / "tools" / "qualite_donnees_replay.py"), str(root)),
            required_paths=(candidates, marks),
            timeout_seconds=timeout_seconds,
        ),
        # RECABLAGE (market_truth) : la chaine canonicalisation -> replay executable
        # -> ledger reconcilie etait ecrite et testee mais n'avait AUCUN appelant de
        # production. Elle tourne desormais ICI, dans le lanceur d'analyse officiel.
        # Mesure l'executabilite et les couts reels ; ne mesure aucun edge.
        AnalysisStage(
            "market_truth_replay",
            "Verite de marche : executabilite et couts",
            (
                "Rejoue des intentions ancrees sur de vrais ticks durables (deux sens) "
                "et mesure taux d'execution, spread, profondeur, latence et markout."
            ),
            (
                py,
                "-m",
                "hl_observer.ops.market_truth_replay",
                "--root",
                str(root),
                "--output-dir",
                str(output_dir),
                "--notional",
                "50",
            ),
            required_paths=(root / "runtime" / "data" / "market_ticks",),
            timeout_seconds=timeout_seconds,
        ),
        AnalysisStage(
            "ab_exact",
            "Replay A/B exact",
            "Compare le bras de reference et les flags candidats sur les marks reels locaux.",
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
                str(
                    root
                    / REPORTS_RELATIVE_PATH
                    / "_cache"
                    / "ab_replay_fixed_50_usdt.json"
                ),
            ),
            required_paths=(candidates, marks),
            timeout_seconds=timeout_seconds,
        ),
        AnalysisStage(
            "realtime_replay",
            "Replay du flux de decisions",
            "Rejoue les evenements recents des logs locaux, sans reseau ni attente artificielle.",
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
            "Replay causal du ledger ferme",
            "Rejoue les trades clotures et verifie les filtres sans lookahead.",
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
            "Tournoi train/validation/holdout",
            "Compare les familles de strategie sur des fenetres separees.",
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
            "Audit PnL",
            "Reconcilie decisions, snapshot et etat exporte de la simulation locale.",
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
            "Attribution des gains et pertes",
            "Ventile PnL, couts et causes racines a partir des logs locaux.",
            (py, "-m", "hl_observer", "loss-attribution", "--from-logs", str(logs)),
            required_paths=(logs,),
            timeout_seconds=timeout_seconds,
        ),
        AnalysisStage(
            "latency_report",
            "Rapport de latence",
            "Mesure l'age des signaux observes dans les journaux de simulation.",
            (py, "-m", "hl_observer", "realtime-latency-report", "--from-logs", str(logs)),
            required_paths=(logs,),
            timeout_seconds=timeout_seconds,
        ),
        AnalysisStage(
            "freshness_diagnostics",
            "Diagnostic de fraicheur",
            "Explique les signaux stale et les limites mesurables du flux local.",
            (py, "-m", "hl_observer", "freshness-diagnostics", "--from-logs", str(logs)),
            required_paths=(logs,),
            timeout_seconds=timeout_seconds,
        ),
    ]

    if full or deep:
        plan.extend(
            [
                AnalysisStage(
                    "walk_forward",
                    "Validation walk-forward",
                    "Valide la robustesse temporelle des configurations locales.",
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
                    "Audit anti-overfit",
                    "Verifie que les configurations ne gagnent pas uniquement sur train.",
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
        plan.append(
            AnalysisStage(
                "scenario_search",
                "Recherche exhaustive resumable",
                "Explore les scenarios existants; cette etape est volontairement opt-in.",
                (
                    py,
                    "-c",
                    (
                        "from hl_observer.backtesting.recherche_scenario import chercher_toutes;"
                        f" chercher_toutes({str(root)!r})"
                    ),
                ),
                required_paths=(candidates, marks),
                timeout_seconds=deep_timeout,
                optional=True,
            )
        )

    return tuple(plan)


def _analysis_environment(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    paths = [str(root / "src"), str(root)]
    if existing:
        paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env.setdefault(name, "2")
    env["HL_ENABLE_MAINNET_EXECUTION"] = "0"
    env["HL_ENABLE_TESTNET_EXECUTION"] = "0"
    env["HYPERSMART_ANALYSIS_LOCAL_ONLY"] = "1"
    return env


def set_below_normal_priority() -> bool:
    """Lower this process and inherited children on Windows, best effort."""

    if os.name != "nt":
        return False
    try:
        import ctypes

        below_normal_priority_class = 0x00004000
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        return bool(ctypes.windll.kernel32.SetPriorityClass(handle, below_normal_priority_class))
    except (AttributeError, OSError):
        return False


def run_stage(stage: AnalysisStage, *, root: Path, output_dir: Path) -> StageResult:
    missing = [path for path in stage.required_paths if not _path_has_data(path)]
    log_path = output_dir / f"{stage.key}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if missing:
        message = "Donnees locales absentes: " + ", ".join(str(path) for path in missing)
        log_path.write_text(message + "\n", encoding="utf-8")
        return StageResult(
            stage.key,
            stage.title,
            "SKIPPED",
            None,
            0.0,
            str(log_path),
            message,
            stage.command,
        )

    started = time.monotonic()
    timed_out = False
    interrupted = False
    return_code: int | None = None
    message = ""
    creation_flags = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)

    with log_path.open("w", encoding="utf-8", errors="replace") as log_handle:
        log_handle.write(f"stage={stage.key}\n")
        log_handle.write(f"started_at={_utc_now()}\n")
        log_handle.write("command=" + subprocess.list2cmdline(list(stage.command)) + "\n\n")
        log_handle.flush()
        try:
            process = subprocess.Popen(
                list(stage.command),
                cwd=str(root),
                env=_analysis_environment(root),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
            )
        except OSError as exc:
            message = f"Demarrage impossible: {type(exc).__name__}: {exc}"
            log_handle.write(message + "\n")
            return StageResult(
                stage.key,
                stage.title,
                "FAILED",
                None,
                round(time.monotonic() - started, 3),
                str(log_path),
                message,
                stage.command,
            )

        next_heartbeat = started
        try:
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed >= stage.timeout_seconds:
                    timed_out = True
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    break
                if time.monotonic() >= next_heartbeat:
                    print(
                        f"[ANALYSE] {stage.title}: {elapsed:.0f}s, "
                        f"log={log_path.name}",
                        flush=True,
                    )
                    next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
                time.sleep(0.25)
        except KeyboardInterrupt:
            interrupted = True
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        return_code = process.poll()

    duration = round(time.monotonic() - started, 3)
    if interrupted:
        status = "INTERRUPTED"
        message = "Interrompu proprement par Ctrl+C; les logs deja ecrits sont conserves."
    elif timed_out:
        status = "FAILED"
        message = f"Delai maximal atteint ({stage.timeout_seconds}s)."
    elif return_code == 0:
        status = "PASSED"
        message = "Etape terminee."
    else:
        status = "FAILED"
        message = f"Code retour {return_code}; voir le journal de l'etape."
    return StageResult(
        stage.key,
        stage.title,
        status,
        return_code,
        duration,
        str(log_path),
        message,
        stage.command,
    )


def _format_bytes(value: object) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024.0 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TiB"


def _read_json_object(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _analysis_findings(output_dir: Path) -> dict[str, object]:
    findings: dict[str, object] = {}
    lab = _read_json_object(output_dir / "pnl_improvement_lab.json")
    if lab:
        truth = lab.get("truth")
        temporal = lab.get("temporal_validation")
        findings["pnl_lab"] = {
            "truth": truth if isinstance(truth, dict) else {},
            "temporal_validation": temporal if isinstance(temporal, dict) else {},
            "findings": lab.get("findings") if isinstance(lab.get("findings"), dict) else {},
            "quality": lab.get("quality") if isinstance(lab.get("quality"), dict) else {},
            "groups": lab.get("groups") if isinstance(lab.get("groups"), dict) else {},
            "experiment_backlog": (
                lab.get("experiment_backlog")
                if isinstance(lab.get("experiment_backlog"), list)
                else []
            ),
            "automatic_activation": bool(lab.get("automatic_activation", False)),
        }
    ab = _read_json_object(output_dir / "ab_replay.json")
    if ab:
        arm_a = ab.get("arm_a") if isinstance(ab.get("arm_a"), dict) else {}
        arm_b = ab.get("arm_b") if isinstance(ab.get("arm_b"), dict) else {}
        validation_a = (
            ab.get("arm_a_validation")
            if isinstance(ab.get("arm_a_validation"), dict)
            else {}
        )
        validation_b = (
            ab.get("arm_b_validation")
            if isinstance(ab.get("arm_b_validation"), dict)
            else {}
        )
        findings["ab_replay"] = {
            "arm_a": {
                "trades": arm_a.get("trades"),
                "profit_factor": arm_a.get("profit_factor"),
                "net_total_usd": arm_a.get("net_total_usd"),
                "verdict": validation_a.get("verdict"),
            },
            "arm_b": {
                "trades": arm_b.get("trades"),
                "profit_factor": arm_b.get("profit_factor"),
                "net_total_usd": arm_b.get("net_total_usd"),
                "verdict": validation_b.get("verdict"),
            },
            "recommendation": ab.get("recommendation"),
            "delta_net_usd": ab.get("delta_net_usd"),
            "comparison_notional_usd": ab.get("comparison_notional_usd"),
            "raw_notional_warning": (
                "Le replay du lanceur utilise un notionnel constant pour eviter qu'un "
                "gros leader domine artificiellement la comparaison."
            ),
        }
    return findings


def _metric_text(metrics: dict[str, object]) -> str:
    trades = int(metrics.get("trades") or 0)
    net = float(metrics.get("net_pnl_actual_usdc") or 0.0)
    pf = metrics.get("profit_factor_actual")
    pf_text = "indisponible" if pf is None else f"{float(pf):.3f}"
    return f"{trades} trades, net {net:.2f} USDC, PF {pf_text}"


def _append_group_summary(
    lines: list[str],
    title: str,
    rows: object,
    *,
    minimum_trades: int = 1,
    limit: int = 8,
) -> None:
    values = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    values = [
        row for row in values if int(row.get("trades") or 0) >= minimum_trades
    ]
    values.sort(
        key=lambda row: (
            float(row.get("normalized_net_usdc") or 0.0),
            str(row.get("group") or ""),
        )
    )
    lines.extend(
        [
            f"### {title}",
            "",
            "| Groupe | Trades | Net reel | PF | Net normalise | Frais |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    if not values:
        lines.append("| Aucun groupe mesurable | 0 | 0.00 | n/a | 0.00 | 0.00 |")
    for row in values[:limit]:
        pf = row.get("profit_factor_actual")
        pf_text = "n/a" if pf is None else f"{float(pf):.3f}"
        lines.append(
            f"| {row.get('group', 'UNKNOWN')} | {int(row.get('trades') or 0)} | "
            f"{float(row.get('net_pnl_actual_usdc') or 0.0):.2f} | {pf_text} | "
            f"{float(row.get('normalized_net_usdc') or 0.0):.2f} | "
            f"{float(row.get('fees_reported_usdc') or 0.0):.2f} |"
        )
    lines.append("")


def _append_analysis_sections(lines: list[str], analysis: dict[str, object]) -> None:
    lab = analysis.get("pnl_lab")
    if isinstance(lab, dict):
        truth = lab.get("truth") if isinstance(lab.get("truth"), dict) else {}
        all_paired = (
            truth.get("all_paired") if isinstance(truth.get("all_paired"), dict) else {}
        )
        eligible = (
            truth.get("eligible_for_learning")
            if isinstance(truth.get("eligible_for_learning"), dict)
            else {}
        )
        details = lab.get("findings") if isinstance(lab.get("findings"), dict) else {}
        quality = lab.get("quality") if isinstance(lab.get("quality"), dict) else {}
        groups = lab.get("groups") if isinstance(lab.get("groups"), dict) else {}
        fee_drag = eligible.get("fee_drag_over_abs_gross")
        fee_drag_text = "indisponible" if fee_drag is None else f"{float(fee_drag):.1%}"
        lines.extend(
            [
                "## Verite PnL actuelle",
                "",
                f"- Round-trips apparies : {_metric_text(all_paired)}.",
                f"- Echantillon exploitable : {_metric_text(eligible)}.",
                "- Les comparaisons de regles sont normalisees a notionnel constant; "
                "le PnL de verite reste celui du ledger.",
                f"- Drag de frais sur le brut absolu : `{fee_drag_text}`.",
                f"- Fermetures orphelines : `{quality.get('orphan_closes', 0)}` ; "
                f"round-trips exclus : `{quality.get('excluded_round_trips', 0)}`.",
                "",
                "## Causes PnL mesurees",
                "",
            ]
        )
        _append_group_summary(
            lines,
            "Par methode de sortie",
            groups.get("by_exit_method"),
        )
        _append_group_summary(
            lines,
            "Coins recurrents les plus couteux",
            groups.get("by_coin"),
            minimum_trades=2,
        )
        labels = (
            ("Pistes robustes", "robust_opportunities"),
            ("Pistes a confirmer", "needs_confirmation"),
            ("Hypotheses rejetees", "rejected_hypotheses"),
            ("Donnees manquantes", "missing_evidence"),
            ("Prochains A/B exacts", "next_exact_ab_experiments"),
        )
        for title, key in labels:
            lines.extend([f"## {title}", ""])
            values = details.get(key) if isinstance(details.get(key), list) else []
            if values:
                lines.extend(f"- {value}" for value in values)
            else:
                fallback = (
                    "Aucune piste n'a passe les controles chronologiques."
                    if key == "robust_opportunities"
                    else "Aucun element."
                )
                lines.append(f"- {fallback}")
            lines.append("")
        backlog = (
            lab.get("experiment_backlog")
            if isinstance(lab.get("experiment_backlog"), list)
            else []
        )
        lines.extend(["## Backlog d'experiences priorise", ""])
        if backlog:
            lines.extend(
                (
                    f"- P{item.get('priority')} `{item.get('experiment_id')}` : "
                    f"{item.get('title')}."
                )
                for item in backlog
                if isinstance(item, dict)
            )
        else:
            lines.append("- Aucun experiment mesurable.")
        lines.append("")

    ab = analysis.get("ab_replay")
    if isinstance(ab, dict):
        arm_a = ab.get("arm_a") if isinstance(ab.get("arm_a"), dict) else {}
        arm_b = ab.get("arm_b") if isinstance(ab.get("arm_b"), dict) else {}
        net_a = float(arm_a.get("net_total_usd") or 0.0)
        net_b = float(arm_b.get("net_total_usd") or 0.0)
        delta_net = float(ab.get("delta_net_usd") or (net_b - net_a))
        loss_reduction = (
            delta_net / abs(net_a)
            if net_a < 0 and delta_net > 0
            else 0.0
        )
        lines.extend(
            [
                "## Replay A/B exact",
                "",
                (
                    f"- Bras A : {arm_a.get('trades', 0)} trades, "
                    f"PF `{arm_a.get('profit_factor')}`, verdict `{arm_a.get('verdict')}`."
                ),
                (
                    f"- Bras B : {arm_b.get('trades', 0)} trades, "
                    f"PF `{arm_b.get('profit_factor')}`, verdict `{arm_b.get('verdict')}`."
                ),
                (
                    f"- Delta B - A : `{delta_net:.2f}` USDT ; reduction de perte "
                    f"`{loss_reduction:.1%}`."
                ),
                f"- Recommandation du replay : `{ab.get('recommendation')}`.",
                f"- Notionnel comparatif : `{ab.get('comparison_notional_usd')}` USDT par trade.",
                f"- Prudence : {ab.get('raw_notional_warning')}",
                "",
            ]
        )


def write_reports(
    output_dir: Path,
    *,
    root: Path,
    started_at: str,
    finished_at: str,
    mode: str,
    inventory: dict[str, object],
    results: Sequence[StageResult],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    analysis = _analysis_findings(output_dir)
    payload = {
        "schema_version": 1,
        "generated_at": finished_at,
        "root": str(root),
        "mode": mode,
        "local_data_only": True,
        "network_used": False,
        "real_execution": False,
        "started_at": started_at,
        "finished_at": finished_at,
        "inputs": inventory,
        "results": [asdict(result) for result in results],
        "analysis": analysis,
        "summary": {
            status: sum(1 for result in results if result.status == status)
            for status in ("PASSED", "FAILED", "SKIPPED", "INTERRUPTED")
        },
    }
    json_path = output_dir / "report.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = payload["summary"]
    logs_info = inventory.get("logs_to_send", {})
    replay_info = inventory.get("replay", {})
    lines = [
        "# Rapport HyperSmart - backtests, replays et analyses",
        "",
        f"- Debut UTC : `{started_at}`",
        f"- Fin UTC : `{finished_at}`",
        f"- Mode : `{mode}`",
        "- Sources : donnees locales existantes uniquement",
        "- Reseau : non utilise",
        "- Execution reelle : impossible",
        (
            "- Resultats : "
            f"{summary['PASSED']} termines, {summary['FAILED']} en echec, "
            f"{summary['SKIPPED']} ignores, {summary['INTERRUPTED']} interrompus"
        ),
        "",
        "## Inventaire des donnees",
        "",
        (
            f"- Logs : `{logs_info.get('path')}` - {logs_info.get('file_count', 0)} fichiers, "
            f"{_format_bytes(logs_info.get('total_bytes', 0))}"
        ),
        (
            f"- Replay : `{replay_info.get('path')}` - {replay_info.get('file_count', 0)} fichiers, "
            f"{_format_bytes(replay_info.get('total_bytes', 0))}"
        ),
        "",
    ]
    _append_analysis_sections(lines, analysis)
    lines.extend(
        [
        "## Etapes",
        "",
        "| Etape | Statut | Duree | Message | Journal |",
        "|---|---:|---:|---|---|",
        ]
    )
    for result in results:
        lines.append(
            "| {title} | {status} | {duration:.1f}s | {message} | `{log}` |".format(
                title=result.title.replace("|", "/"),
                status=result.status,
                duration=result.duration_seconds,
                message=result.message.replace("|", "/"),
                log=result.log_path,
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Un statut PASSED prouve que l'outil a termine, pas qu'une strategie est rentable.",
            "- Une configuration ne doit etre promue qu'apres validation OOS/walk-forward et couts nets.",
            "- Les etapes SKIPPED indiquent exactement quelle donnee locale manque.",
            "- Les journaux de chaque etape conservent la sortie complete pour diagnostic.",
            "",
            "**Aucun resultat historique ne garantit un profit futur.**",
            "",
        ]
    )
    markdown_path = output_dir / "RAPPORT_BACKTEST_REPLAY.md"
    markdown_path.write_text("\n".join(lines), encoding="utf-8")

    latest_dir = output_dir.parent
    shutil.copy2(markdown_path, latest_dir / "RAPPORT_LATEST.md")
    shutil.copy2(json_path, latest_dir / "report_latest.json")
    return markdown_path, json_path


def run_suite(
    root: Path,
    *,
    full: bool = False,
    deep: bool = False,
    timeout_seconds: int = DEFAULT_STAGE_TIMEOUT_SECONDS,
    stage_runner=run_stage,
) -> tuple[int, Path, tuple[StageResult, ...]]:
    root = root.resolve()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = root / REPORTS_RELATIVE_PATH / f"run_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    set_below_normal_priority()
    started_at = _utc_now()
    mode = "deep" if deep else ("full" if full else "standard")
    plan = build_stage_plan(
        root,
        output_dir,
        full=full,
        deep=deep,
        timeout_seconds=timeout_seconds,
    )
    results: list[StageResult] = []

    print(f"[ANALYSE] HyperSmart mode={mode} etapes={len(plan)}", flush=True)
    print(f"[ANALYSE] Sortie: {output_dir}", flush=True)
    for index, stage in enumerate(plan, start=1):
        print(f"\n[{index}/{len(plan)}] {stage.title}", flush=True)
        print(f"  {stage.purpose}", flush=True)
        result = stage_runner(stage, root=root, output_dir=output_dir)
        results.append(result)
        print(f"  -> {result.status}: {result.message}", flush=True)
        if result.status == "INTERRUPTED":
            break

    inventory = build_input_inventory(root)
    finished_at = _utc_now()
    markdown_path, _ = write_reports(
        output_dir,
        root=root,
        started_at=started_at,
        finished_at=finished_at,
        mode=mode,
        inventory=inventory,
        results=results,
    )
    passed = sum(1 for result in results if result.status == "PASSED")
    failed = sum(1 for result in results if result.status == "FAILED")
    print(f"\n[ANALYSE] Rapport: {markdown_path}", flush=True)
    if passed == 0:
        return 2, markdown_path, tuple(results)
    if failed:
        return 1, markdown_path, tuple(results)
    return 0, markdown_path, tuple(results)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backtests, replays, A/B et rapport HyperSmart sur donnees locales."
    )
    parser.add_argument("--root", default=".", help="Racine du projet HyperSmart.")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Ajoute les rapports walk-forward et anti-overfit explicites.",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="Ajoute la recherche exhaustive resumable (implique --full).",
    )
    parser.add_argument(
        "--stage-timeout-seconds",
        type=int,
        default=DEFAULT_STAGE_TIMEOUT_SECONDS,
        help="Temps maximal par etape standard.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    timeout = max(60, int(args.stage_timeout_seconds))
    code, _, _ = run_suite(
        Path(args.root),
        full=bool(args.full or args.deep),
        deep=bool(args.deep),
        timeout_seconds=timeout,
    )
    return code


__all__ = [
    "AnalysisStage",
    "StageResult",
    "build_input_inventory",
    "build_stage_plan",
    "main",
    "resolve_logs_dir",
    "run_stage",
    "run_suite",
    "set_below_normal_priority",
    "write_reports",
]
