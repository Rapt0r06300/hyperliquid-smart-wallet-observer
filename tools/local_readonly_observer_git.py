"""Read-only Git comparison helpers for the local observer."""

from __future__ import annotations

import difflib
import json
from pathlib import Path
from typing import Any, Iterable

from tools.local_readonly_observer_core import (
    SOURCE_SUFFIXES,
    read_text_limited,
    redact_text,
    run_git,
    secret_like_path,
)


def git_state(local_root: Path, github_root: Path) -> dict[str, Any]:
    inside = run_git(local_root, ["rev-parse", "--is-inside-work-tree"])
    if not inside["ok"] or inside["stdout"].strip().lower() != "true":
        return {"is_git_repo": False, "error": inside.get("stderr") or "not a Git work tree"}

    def out(args: list[str], timeout: float = 30.0) -> str:
        result = run_git(local_root, args, timeout=timeout)
        return result["stdout"].strip() if result["ok"] else ""

    head = out(["rev-parse", "HEAD"])
    branch = out(["branch", "--show-current"])
    origin_main = out(["rev-parse", "--verify", "origin/main"])
    status = out(
        ["status", "--porcelain=v2", "--branch", "--untracked-files=all"],
        timeout=60.0,
    )
    branches = out([
        "for-each-ref",
        "--format=%(refname:short)|%(objectname)|%(upstream:short)|%(upstream:track)",
        "refs/heads",
    ])
    remotes = out(["remote", "-v"])
    local_vs_origin = (
        out(["log", "--format=%H|%h|%ad|%s", "--date=iso-strict", "origin/main..HEAD"])
        if origin_main else ""
    )

    recent = out(["rev-list", "--max-count=200", "HEAD"]).splitlines() if head else []
    github_presence = []
    for sha in recent:
        exists = run_git(github_root, ["cat-file", "-e", f"{sha}^{{commit}}"])
        containing_branches: list[str] = []
        if exists["ok"]:
            containing = run_git(
                github_root,
                [
                    "for-each-ref", "--contains", sha,
                    "--format=%(refname:short)", "refs/remotes/origin",
                ],
            )
            if containing["ok"]:
                containing_branches = [
                    line for line in containing["stdout"].splitlines() if line
                ]
        github_presence.append({
            "sha": sha,
            "present_in_github_checkout_objects": bool(exists["ok"]),
            "remote_branches_containing": containing_branches,
        })

    return {
        "is_git_repo": True,
        "head": head or None,
        "branch": branch or None,
        "origin_main_local_ref": origin_main or None,
        "status_porcelain_v2": status.splitlines(),
        "branches": [line for line in branches.splitlines() if line],
        "remotes": [line for line in remotes.splitlines() if line],
        "local_commits_not_in_local_origin_main_ref": [
            line for line in local_vs_origin.splitlines() if line
        ],
        "recent_commit_github_presence": github_presence,
        "note": (
            "The local origin/main ref can be stale. Recent commits are also checked "
            "against the separate GitHub checkout."
        ),
    }


def write_changed_text_snapshot(
    local_root: Path,
    github_root: Path,
    output: Path,
    comparison: list[dict[str, Any]],
    untracked: Iterable[str],
) -> dict[str, Any]:
    changed = {
        str(row["path"])
        for row in comparison
        if row.get("status") in {"modified_local", "tracked_local_not_in_github_main"}
    }
    changed.update(
        rel.replace("\\", "/")
        for rel in untracked
        if Path(rel).suffix.casefold() in SOURCE_SUFFIXES
    )

    snapshot_root = output / "changed_text"
    diff_path = output / "local_vs_github_main.patch"
    manifest = []
    diff_chunks: list[str] = []

    for rel in sorted(changed):
        if Path(rel).suffix.casefold() not in SOURCE_SUFFIXES or secret_like_path(rel):
            manifest.append({"path": rel, "included": False, "reason": "secret_or_unsupported"})
            continue

        local_path = local_root / Path(rel)
        github_path = github_root / Path(rel)
        local_text = read_text_limited(local_path)
        if local_text is None:
            manifest.append({"path": rel, "included": False, "reason": "missing_or_too_large"})
            continue

        local_redacted, local_redactions = redact_text(local_text)
        destination = snapshot_root / Path(rel)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(local_redacted, encoding="utf-8")

        github_text = read_text_limited(github_path) if github_path.is_file() else ""
        github_redacted, github_redactions = redact_text(github_text or "")
        diff_chunks.extend(
            difflib.unified_diff(
                github_redacted.splitlines(keepends=True),
                local_redacted.splitlines(keepends=True),
                fromfile=f"github-main/{rel}",
                tofile=f"local/{rel}",
                n=3,
            )
        )
        manifest.append({
            "path": rel,
            "included": True,
            "local_redactions": local_redactions,
            "github_redactions": github_redactions,
            "bytes": len(local_redacted.encode("utf-8")),
        })

    diff_path.write_text("".join(diff_chunks), encoding="utf-8")
    (output / "changed_text_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "files_considered": len(changed),
        "files_included": sum(1 for row in manifest if row.get("included")),
        "diff_bytes": diff_path.stat().st_size if diff_path.exists() else 0,
    }
