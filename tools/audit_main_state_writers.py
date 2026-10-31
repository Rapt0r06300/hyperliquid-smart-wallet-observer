"""Render a source inventory of GitHub Actions workflows that push commits."""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


def _sources(root: Path, ref: str | None) -> dict[str, str]:
    if ref is None:
        paths = [
            path.relative_to(root).as_posix()
            for base in (root / ".github" / "workflows", root / "tools")
            for path in base.rglob("*")
            if path.is_file() and (path.suffix in {".yml", ".yaml", ".py"})
        ]
        return {
            name: (root / name).read_text(encoding="utf-8", errors="replace")
            for name in paths
        }
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref, "--", ".github/workflows", "tools"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    paths = [
        name for name in listing.splitlines()
        if name.endswith((".yml", ".yaml", ".py"))
        and (name.startswith(".github/workflows/") or name.startswith("tools/"))
    ]
    sources: dict[str, str] = {}
    for name in paths:
        result = subprocess.run(
            ["git", "show", f"{ref}:{name}"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        sources[name] = result.stdout
    return sources


def inventory(root: Path, ref: str | None = None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    sources = _sources(root, ref)
    for name, source in sorted(sources.items()):
        if not name.startswith(".github/workflows/"):
            continue
        lines = source.splitlines()
        pushes = [f"{number}: {line.strip()}" for number, line in enumerate(lines, 1) if "git push" in line]
        if not pushes and "publish_main_commit.py" in source:
            pushes = [
                f"{number}: {line.strip()}"
                for number, line in enumerate(lines, 1)
                if "publish_main_commit.py" in line
            ]
        if not pushes:
            continue
        events: list[str] = []
        inside_on = False
        for line in lines:
            if re.match(r"^on:\s*(?:#.*)?$", line):
                inside_on = True
                continue
            if inside_on and line and not line[0].isspace() and not line.startswith("#"):
                break
            if inside_on:
                match = re.match(r"^  ([A-Za-z0-9_-]+):", line)
                if match:
                    events.append(match.group(1))
        groups = [
            line.strip().split("group:", 1)[1].strip()
            for line in lines
            if re.match(r"^\s+group:", line)
        ]
        write_lines = [
            f"{number}: {line.strip()}"
            for number, line in enumerate(lines, 1)
            if re.search(r"\bgit (add|rm)\b", line)
        ]
        if "publish_main_commit.py" in "\n".join(lines):
            strategy = "shared atomic fast-forward publisher; bounded fetch/rebase/retry"
        elif "rebase_disjoint_catalog_publication.py" in "\n".join(lines):
            strategy = "specialized disjoint-catalog rebase; bounded push retry"
        elif any("pull --rebase" in line for line in lines):
            strategy = "inline pull/rebase and push retry"
        elif any(re.search(r"for (?:ATTEMPT|attempt|i) in", line) for line in lines):
            strategy = "custom bounded push retry"
        else:
            strategy = "single push or workflow-specific fallback"
        rows.append(
            {
                "workflow": name,
                "events": events,
                "groups": groups,
                "writes": write_lines,
                "pushes": pushes,
                "strategy": strategy,
            }
        )
    for name, source in sorted(sources.items()):
        if not name.startswith("tools/"):
            continue
        source_lines = source.splitlines()
        if name.endswith("audit_main_state_writers.py"):
            continue
        push_lines = [
            f"{number}: {line.strip()}"
            for number, line in enumerate(source_lines, 1)
            if re.search(r"\bgit\s+push\b|[\"']push[\"']\s*,", line)
        ]
        is_main_writer = bool(push_lines) and (
            "publish_main_commit.py" in name
            or "refs/heads/main" in source
            or "HEAD:main" in source
            or "HEAD:{push_ref}" in source
        )
        if is_main_writer:
            if name.endswith("alina_git_code_sync.py"):
                events = ["manual local synchronization"]
                groups = ["none; bounded local process"]
                strategy = "bounded fetch/reconcile; fast-forward push only; no force; rechecks remote SHA"
                writes = ["reconciles local code/history; excludes shard payloads by existing sync policy"]
            elif name.endswith("continuous_reconcile_backlog.py"):
                events = ["called by GitHub-hosted reconciliation workflow"]
                groups = ["workflow-defined; no independent repository-wide lock"]
                strategy = "legacy data backlog writer; normal push plus verified disjoint-catalog rebase"
                writes = ["catalog/data receipts; historical compatibility path, not an economic Copy-Vault source"]
            else:
                events = ["called by main-state workflows"]
                groups = ["inherited from caller workflow"]
                strategy = "shared fast-forward publisher; bounded retry; no force update"
                writes = ["publishes already-committed state; rebase conflicts fail closed"]
            rows.append(
                {
                    "workflow": f"{name} (main writer)",
                    "events": events,
                    "groups": groups,
                    "writes": writes,
                    "pushes": push_lines,
                    "strategy": strategy,
                }
            )
    return rows


def render(root: Path, ref: str | None = None) -> str:
    rows = inventory(root, ref)
    out = [
        "# GitHub Actions main-state writer inventory",
        "",
        "Generated by `python tools/audit_main_state_writers.py`. This is a source scan, not proof that a workflow is enabled or has run.",
        "The full workflow list is retained because every accepted fast-forward can contend on the same `main` ref. Dataset V2, event-intelligence, and other out-of-scope workflows remain historical/compatibility sources; this inventory does not enable them.",
        "",
        f"Scanned {sum(not str(row['workflow']).startswith('tools/') for row in rows)} workflow files and {sum(str(row['workflow']).startswith('tools/') for row in rows)} Git writer script(s).",
        "",
    ]
    for row in rows:
        out.extend(
            [
                f"## `{row['workflow']}`",
                "",
                f"- Triggers: {', '.join(row['events']) or 'not parsed'}",
                f"- Concurrency groups: {', '.join(f'`{x}`' for x in row['groups']) or 'none'}",
                f"- Retry strategy: {row['strategy']}",
                "- Write staging commands:",
            ]
        )
        if row["writes"]:
            out.extend(f"  - `{item}`" for item in row["writes"])
        else:
            out.append("  - not statically found")
        out.append("- Main push sites:")
        out.extend(f"  - `{item}`" for item in row["pushes"])
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ref", help="scan workflow and writer sources from this Git ref instead of the working tree")
    args = parser.parse_args()
    report = render(args.root.resolve(), args.ref)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
