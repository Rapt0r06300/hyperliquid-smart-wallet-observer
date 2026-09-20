"""Command line entry point for the Alina local read-only observer."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from tools.local_readonly_observer_core import (
    compare_tracked_paths,
    inventory_tree,
    protected_source_signature,
    resolved,
    tracked_and_untracked,
    utc_iso,
    validate_paths,
    write_inventory_csv,
    write_json,
)
from tools.local_readonly_observer_git import (
    git_state,
    write_changed_text_snapshot,
)
from tools.local_readonly_observer_static import static_scan

SCHEMA_VERSION = "alina.local_readonly_observer.v1"
RESULT_TOKENS = (
    "backtest", "replay", "scoreboard", "metric", "result", "rapport",
    "report", "equity", "pnl", "oos", "forward", "verdict",
)


def summarize_inventory(rows: list[dict[str, Any]]) -> dict[str, Any]:
    datasets = [row for row in rows if row.get("category") == "dataset"]
    logs = [
        row for row in rows
        if Path(str(row.get("path") or "")).suffix.casefold() == ".log"
        or str(row.get("path") or "").casefold().startswith("runtime/logs/")
    ]
    results = [
        row for row in rows
        if any(
            token in Path(str(row.get("path") or "")).name.casefold()
            for token in RESULT_TOKENS
        )
    ]
    large = sorted(
        rows,
        key=lambda row: int(row.get("size") or 0),
        reverse=True,
    )[:500]
    fresh = sorted(
        rows,
        key=lambda row: int(row.get("mtime_ns") or 0),
        reverse=True,
    )[:500]
    return {
        "datasets": {
            "files": len(datasets),
            "bytes": sum(int(row.get("size") or 0) for row in datasets),
            "largest_500": sorted(
                datasets,
                key=lambda row: int(row.get("size") or 0),
                reverse=True,
            )[:500],
            "freshest_500": sorted(
                datasets,
                key=lambda row: int(row.get("mtime_ns") or 0),
                reverse=True,
            )[:500],
        },
        "logs": {
            "files": len(logs),
            "recent_500": sorted(
                logs,
                key=lambda row: int(row.get("mtime_ns") or 0),
                reverse=True,
            )[:500],
            "content_copied": False,
        },
        "existing_results": {
            "files": len(results),
            "recent_1000": sorted(
                results,
                key=lambda row: int(row.get("mtime_ns") or 0),
                reverse=True,
            )[:1000],
            "executed": False,
        },
        "largest_files_500": large,
        "freshest_files_500": fresh,
    }


def environment_inventory(target: Path) -> dict[str, Any]:
    candidates = [
        target / "tools" / "python" / "python.exe",
        target / ".venv" / "Scripts" / "python.exe",
        target / "venv" / "Scripts" / "python.exe",
        target / "env" / "Scripts" / "python.exe",
    ]
    interpreters = []
    for path in candidates:
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        interpreters.append({
            "path": str(path.relative_to(target)).replace("\\", "/"),
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        })

    dependency_files = []
    for path in sorted(target.glob("requirements*.txt")):
        if path.is_file():
            dependency_files.append(path.name)
    if (target / "pyproject.toml").is_file():
        dependency_files.append("pyproject.toml")

    return {
        "interpreters": interpreters,
        "dependency_files": dependency_files,
        "local_python_executed": False,
    }


def render_report(
    *,
    target: Path,
    github_root: Path,
    inventory_summary: dict[str, Any],
    comparison: list[dict[str, Any]],
    untracked: list[str],
    git: dict[str, Any],
    static: dict[str, Any],
    derived: dict[str, Any],
    environment: dict[str, Any],
    changed_snapshot: dict[str, Any],
    protected_unchanged: bool,
) -> str:
    counts = Counter(str(row.get("status") or "unknown") for row in comparison)
    lines = [
        "# Alina SmartFlow - audit local READ-ONLY",
        "",
        f"Schema: {SCHEMA_VERSION}",
        f"Generated UTC: {utc_iso()}",
        f"Observed folder: {target}",
        f"Separate GitHub reference: {github_root}",
        "Mode: read-only. No Git write command is used in the observed repository.",
        f"Protected source tree unchanged after audit: {protected_unchanged}",
        "",
        "## Local versus GitHub main",
        "",
        f"Tracked files compared: {len(comparison)}",
        f"Modified locally: {counts.get('modified_local', 0)}",
        f"Deleted locally: {counts.get('deleted_local', 0)}",
        f"Tracked locally but absent from GitHub main: {counts.get('tracked_local_not_in_github_main', 0)}",
        f"Untracked local files: {len(untracked)}",
        f"Changed local text files copied with redaction: {changed_snapshot.get('files_included', 0)}",
        "",
        "## Local Git",
        "",
        f"Branch: {git.get('branch')}",
        f"HEAD: {git.get('head')}",
        f"Local commits versus local origin/main ref: {len(git.get('local_commits_not_in_local_origin_main_ref') or [])}",
        "",
        "## Inventory",
        "",
        f"Files inventoried: {inventory_summary.get('files', 0)}",
        f"Bytes inventoried: {inventory_summary.get('bytes', 0)}",
        f"Stopped reason: {inventory_summary.get('stopped_reason')}",
        f"Dataset-like files: {derived['datasets'].get('files', 0)}",
        f"Log files: {derived['logs'].get('files', 0)}",
        f"Existing replay/backtest/report files: {derived['existing_results'].get('files', 0)}",
        "",
        "## Static source audit",
        "",
        f"Active text files scanned: {static.get('files_scanned', 0)}",
        f"Findings: {len(static.get('findings') or [])}",
        f"Finding counts: {json.dumps(static.get('finding_counts') or {}, ensure_ascii=False)}",
        "",
        "## Local Python metadata",
        "",
        f"Interpreter executables found: {len(environment.get('interpreters') or [])}",
        "The local Python interpreter is not executed by this audit.",
        "",
        "## Evidence files",
        "",
        "REPORT.md - this summary",
        "report.json - machine-readable summary",
        "inventory.csv - paths, sizes, dates and categories",
        "inventory_details.json - datasets, logs, result-file metadata and largest files",
        "git.json - HEAD, branches, status and commit presence",
        "tracked_comparison.json - SHA-256 local versus GitHub main",
        "untracked.json - local untracked paths",
        "local_vs_github_main.patch - redacted text diff",
        "changed_text/ - redacted copies of changed or untracked source text",
        "static_findings.json - TODO markers, pass nodes, hardcoded user paths and duplicate heuristics",
        "environment.json - detected local interpreter paths and dependency files",
        "protected_before.json / protected_after.json - anti-modification proof",
        "",
        "Raw log and dataset bodies are not copied automatically.",
        "A future explicitly authorized action can inspect a specific selected file if needed.",
        "",
        "True OS-enforced NTFS deny-write hardening is intentionally not changed by this workflow.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Observe an Alina SmartFlow local folder without modifying it."
    )
    parser.add_argument("--target", required=True)
    parser.add_argument("--github-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-files", type=int, default=500000)
    parser.add_argument("--max-seconds", type=float, default=90.0)
    parser.add_argument("--hash-max-mb", type=int, default=256)
    args = parser.parse_args(argv)

    target = resolved(args.target)
    github_root = resolved(args.github_root)
    output = resolved(args.output)
    validate_paths(target, github_root, output)
    output.mkdir(parents=True, exist_ok=True)

    protected_before = protected_source_signature(target)
    write_json(output / "protected_before.json", protected_before)

    inventory, inventory_summary = inventory_tree(
        target,
        max_files=max(1, int(args.max_files)),
        max_seconds=max(1.0, float(args.max_seconds)),
    )
    write_inventory_csv(output / "inventory.csv", inventory)
    write_json(output / "inventory_summary.json", inventory_summary)

    git = git_state(target, github_root)
    write_json(output / "git.json", git)

    tracked, untracked = tracked_and_untracked(target)
    comparison = compare_tracked_paths(
        target,
        github_root,
        tracked,
        hash_max_bytes=max(1, int(args.hash_max_mb)) * 1024 * 1024,
    )
    write_json(output / "tracked_comparison.json", comparison)
    write_json(output / "untracked.json", sorted(untracked))

    changed_snapshot = write_changed_text_snapshot(
        target,
        github_root,
        output,
        comparison,
        untracked,
    )

    static = static_scan(target)
    write_json(output / "static_findings.json", static)

    derived = summarize_inventory(inventory)
    write_json(output / "inventory_details.json", derived)

    environment = environment_inventory(target)
    write_json(output / "environment.json", environment)

    protected_after = protected_source_signature(target)
    write_json(output / "protected_after.json", protected_after)
    protected_unchanged = protected_before == protected_after

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_iso(),
        "target": str(target),
        "github_root": str(github_root),
        "output": str(output),
        "read_only": True,
        "target_write_operations_requested": 0,
        "protected_source_unchanged": protected_unchanged,
        "inventory_summary": inventory_summary,
        "comparison_counts": dict(
            Counter(str(row.get("status") or "unknown") for row in comparison)
        ),
        "tracked_files": len(tracked),
        "untracked_files": len(untracked),
        "changed_text_snapshot": changed_snapshot,
        "git_head": git.get("head"),
        "git_branch": git.get("branch"),
        "static_finding_counts": static.get("finding_counts"),
        "dataset_files": derived["datasets"].get("files"),
        "dataset_bytes": derived["datasets"].get("bytes"),
        "log_files": derived["logs"].get("files"),
        "existing_result_files": derived["existing_results"].get("files"),
        "local_interpreters_found": len(environment.get("interpreters") or []),
        "raw_log_or_dataset_content_copied": False,
    }
    write_json(output / "report.json", report)
    (output / "REPORT.md").write_text(
        render_report(
            target=target,
            github_root=github_root,
            inventory_summary=inventory_summary,
            comparison=comparison,
            untracked=untracked,
            git=git,
            static=static,
            derived=derived,
            environment=environment,
            changed_snapshot=changed_snapshot,
            protected_unchanged=protected_unchanged,
        ),
        encoding="utf-8",
    )

    if not protected_unchanged:
        print(
            "READ_ONLY_POSTCONDITION_FAILED: protected source tree changed during observation",
            file=sys.stderr,
        )
        return 3

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
