from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


FIELD_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="([^"]*)"')


def _integer(value: str | None) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


def _records(path: Path, limit: int) -> list[dict[str, str]]:
    tail: deque[dict[str, str]] = deque(maxlen=limit)
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            parsed = dict(FIELD_RE.findall(line))
            if parsed.get("launcher") and parsed.get("event"):
                tail.append(parsed)
    return list(tail)


@dataclass
class OperationStats:
    calls: int = 0
    failures: int = 0
    slow_events: int = 0
    durations_ms: list[int] = field(default_factory=list)
    last_exit_code: str = ""
    last_failure_code: str = ""
    last_failure_mode: str = ""
    last_failure_run_id: str = ""
    last_status: str = ""
    output_logs: set[str] = field(default_factory=set)

    def add(self, record: dict[str, str]) -> None:
        self.calls += 1
        if record.get("status") == "FAILURE":
            self.failures += 1
            self.last_failure_code = record.get("exit_code", "")
            self.last_failure_mode = record.get("mode", "")
            self.last_failure_run_id = record.get("run_id", "")
        if record.get("slow") == "1":
            self.slow_events += 1
        if record.get("event") in {"RESULT", "SUMMARY", "EXIT"}:
            self.durations_ms.append(_integer(record.get("since_previous_ms")))
        if record.get("exit_code"):
            self.last_exit_code = record["exit_code"]
        if record.get("status"):
            self.last_status = record["status"]
        output_log = record.get("output_log", "")
        if output_log and output_log != "not-declared":
            self.output_logs.add(output_log)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _analyse(records: Iterable[dict[str, str]], ignored_run_ids: set[str] | None = None) -> dict[str, object]:
    all_rows = list(records)
    ignored_run_ids = ignored_run_ids or set()
    audit_rows = [row for row in all_rows if row.get("launcher") == "LOG_AUDIT"]
    current_run_rows = [row for row in all_rows if row.get("run_id", "") in ignored_run_ids]
    candidate_rows = [
        row
        for row in all_rows
        if row.get("launcher") != "LOG_AUDIT" and row.get("run_id", "") not in ignored_run_ids
    ]
    test_run_keys = {
        (row.get("launcher", ""), row.get("run_id", ""))
        for row in candidate_rows
        if "pytest-of-" in row.get("cwd", "").lower()
    }
    test_rows = [
        row
        for row in candidate_rows
        if (row.get("launcher", ""), row.get("run_id", "")) in test_run_keys
    ]
    rows = [
        row
        for row in candidate_rows
        if (row.get("launcher", ""), row.get("run_id", "")) not in test_run_keys
    ]
    operations: dict[tuple[str, str, str], OperationStats] = defaultdict(OperationStats)
    runs: dict[tuple[str, str], dict[str, object]] = {}
    launcher_scores: dict[str, dict[str, int]] = defaultdict(
        lambda: {"events": 0, "failures": 0, "slow_events": 0, "incomplete_runs": 0}
    )

    for record in rows:
        launcher = record.get("launcher", "unknown")
        phase = record.get("phase", "unknown")
        operation = record.get("operation", "unknown")
        operations[(launcher, phase, operation)].add(record)
        launcher_scores[launcher]["events"] += 1
        if record.get("status") == "FAILURE":
            launcher_scores[launcher]["failures"] += 1
        if record.get("slow") == "1":
            launcher_scores[launcher]["slow_events"] += 1

        run_id = record.get("run_id", "")
        if run_id and run_id != "unavailable":
            state = runs.setdefault(
                (launcher, run_id),
                {"launcher": launcher, "run_id": run_id, "started": False, "exited": False, "last": {}},
            )
            if record.get("event") == "START":
                state["started"] = True
            if record.get("event") == "EXIT":
                state["exited"] = True
            state["last"] = record

    incomplete = []
    for state in runs.values():
        if state["started"] and not state["exited"]:
            incomplete.append(state)
            launcher_scores[str(state["launcher"])]["incomplete_runs"] += 1

    operation_rows = []
    for (launcher, phase, operation), stats in operations.items():
        durations = stats.durations_ms
        operation_rows.append(
            {
                "launcher": launcher,
                "phase": phase,
                "operation": operation,
                "events": stats.calls,
                "failures": stats.failures,
                "slow_events": stats.slow_events,
                "average_duration_ms": round(sum(durations) / len(durations)) if durations else 0,
                "maximum_duration_ms": max(durations, default=0),
                "last_exit_code": stats.last_exit_code,
                "last_failure_code": stats.last_failure_code,
                "last_failure_mode": stats.last_failure_mode,
                "last_failure_run_id": stats.last_failure_run_id,
                "last_status": stats.last_status,
                "output_logs": sorted(stats.output_logs),
            }
        )

    failures = sorted(
        (row for row in operation_rows if row["failures"] and row["last_status"] == "FAILURE"),
        key=lambda row: (row["failures"], row["maximum_duration_ms"]),
        reverse=True,
    )
    historical_failures = sorted(
        (row for row in operation_rows if row["failures"] and row["last_status"] != "FAILURE"),
        key=lambda row: (row["failures"], row["maximum_duration_ms"]),
        reverse=True,
    )
    slowest = sorted(
        (row for row in operation_rows if row["maximum_duration_ms"] >= 5_000),
        key=lambda row: row["maximum_duration_ms"],
        reverse=True,
    )
    ranking = []
    for launcher, values in launcher_scores.items():
        open_failures = sum(1 for row in failures if row["launcher"] == launcher)
        score = open_failures * 100 + values["incomplete_runs"] * 50 + values["failures"] * 10 + values["slow_events"] * 10
        ranking.append({"launcher": launcher, "priority_score": score, "open_failures": open_failures, **values})
    ranking.sort(key=lambda row: (row["priority_score"], row["events"]), reverse=True)

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "records_analyzed": len(rows),
        "audit_records_ignored": len(audit_rows),
        "current_run_records_ignored": len(current_run_rows),
        "test_records_ignored": len(test_rows),
        "test_runs_ignored": len(test_run_keys),
        "launchers_seen": len(launcher_scores),
        "runs_seen": len(runs),
        "incomplete_runs": incomplete,
        "failure_operations": failures,
        "historical_failure_operations": historical_failures,
        "slow_operations": slowest,
        "launcher_priority": ranking,
    }


def _markdown(report: dict[str, object], source: Path) -> str:
    failures = list(report["failure_operations"])
    historical_failures = list(report["historical_failure_operations"])
    slow = list(report["slow_operations"])
    incomplete = list(report["incomplete_runs"])
    ranking = list(report["launcher_priority"])
    lines = [
        "# Rapport d’amélioration des lanceurs",
        "",
        f"Source : `{source}`",
        f"Généré : `{report['generated_at_utc']}`",
        "",
        "## Résumé",
        "",
        f"- Événements analysés : **{report['records_analyzed']}**",
        f"- Événements d’autotest ignorés : **{report['audit_records_ignored']}**",
        f"- Événements du rapport en cours ignorés : **{report['current_run_records_ignored']}**",
        f"- Runs pytest ignorés : **{report['test_runs_ignored']}** ({report['test_records_ignored']} événements)",
        f"- Lanceurs observés : **{report['launchers_seen']}**",
        f"- Exécutions observées : **{report['runs_seen']}**",
        f"- Opérations actuellement en échec : **{len(failures)}**",
        f"- Incidents historiques suivis d’un succès : **{len(historical_failures)}**",
        f"- Opérations lentes (≥ 5 s) : **{len(slow)}**",
        f"- Exécutions commencées sans événement EXIT : **{len(incomplete)}**",
        "",
        "## Priorités d’amélioration",
        "",
        "| Priorité | Lanceur | Échecs actifs | Incidents | Lenteurs | Runs incomplets | Événements |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for index, row in enumerate(ranking[:20], start=1):
        lines.append(
            f"| {index} | `{row['launcher']}` | {row['open_failures']} | {row['failures']} | {row['slow_events']} | "
            f"{row['incomplete_runs']} | {row['events']} |"
        )
    if not ranking:
        lines.append("| 1 | Aucune donnée exploitable | 0 | 0 | 0 | 0 | 0 |")

    lines.extend(["", "## Échecs à corriger", ""])
    if failures:
        for row in failures[:30]:
            logs = ", ".join(f"`{item}`" for item in row["output_logs"]) or "journal du lanceur"
            lines.append(
                f"- **{row['launcher']} / {row['phase']} / {row['operation']}** : "
                f"{row['failures']} échec(s), dernier code d’échec `{row['last_failure_code'] or 'inconnu'}`. "
                f"Mode `{row['last_failure_mode'] or 'inconnu'}`, run `{row['last_failure_run_id'] or 'inconnu'}`. "
                f"Action : consulter {logs} et les événements précédents de ce `run_id`."
            )
    else:
        lines.append("- Aucun échec encore actif dans la fenêtre analysée.")

    lines.extend(["", "## Incidents historiques maintenant résolus", ""])
    if historical_failures:
        for row in historical_failures[:30]:
            lines.append(
                f"- **{row['launcher']} / {row['phase']} / {row['operation']}** : "
                f"{row['failures']} ancien(s) échec(s), puis statut `{row['last_status']}` "
                f"avec code final `{row['last_exit_code'] or 'inconnu'}`. À surveiller, sans le classer comme panne active."
            )
    else:
        lines.append("- Aucun incident historique résolu dans la fenêtre analysée.")

    lines.extend(["", "## Lenteurs à profiler", ""])
    if slow:
        for row in slow[:30]:
            lines.append(
                f"- **{row['launcher']} / {row['phase']} / {row['operation']}** : "
                f"maximum `{row['maximum_duration_ms']} ms`, moyenne `{row['average_duration_ms']} ms`."
            )
    else:
        lines.append("- Aucune étape structurée au-dessus de 5 secondes.")

    lines.extend(["", "## Exécutions incomplètes", ""])
    if incomplete:
        for run in incomplete[:30]:
            last = run["last"]
            lines.append(
                f"- `{run['launcher']}` run `{run['run_id']}` : dernier événement "
                f"`{last.get('event', '?')}` / `{last.get('phase', '?')}` / `{last.get('operation', '?')}`. "
                "Action : rechercher un arrêt brutal, une fermeture de fenêtre ou un processus encore actif."
            )
    else:
        lines.append("- Aucun run incomplet détecté.")

    lines.extend(
        [
            "",
            "## Lecture recommandée",
            "",
            "1. Corriger d’abord les opérations en échec récurrent.",
            "2. Examiner ensuite les runs sans `EXIT`, car ils signalent souvent une interruption ou un crash.",
            "3. Profiler les phases lentes avec leur `output_log`, sans réduire les contrôles SAFE.",
            "4. Comparer plusieurs runs avant de conclure à une régression de performance.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyse les journaux structurés des lanceurs racine.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--limit", type=int, default=50_000)
    parser.add_argument("--ignore-run-id", action="append", default=[])
    args = parser.parse_args()

    root = args.root.resolve()
    source = root / "runtime" / "logs" / "launchers" / "ALL_LAUNCHERS.log"
    output_dir = root / "runtime" / "reports" / "launchers"
    if not source.is_file():
        print(f"[NO_GO] Journal global absent: {source}")
        return 2

    records = _records(source, max(1, args.limit))
    if not records:
        print(f"[NO_GO] Aucun événement structuré exploitable dans {source}")
        return 3

    report = _analyse(records, set(args.ignore_run_id))
    json_path = output_dir / "IMPROVEMENT_REPORT.json"
    markdown_path = output_dir / "IMPROVEMENT_REPORT.md"
    _atomic_write(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    _atomic_write(markdown_path, _markdown(report, source))
    print(f"[OK] Rapport JSON: {json_path}")
    print(f"[OK] Rapport lisible: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
