#!/usr/bin/env python3
"""Safe code-only reconciliation of local main with canonical GitHub main.

No force push, reset, clean, stash, deletion of Git locks, or shard downloads.
On conflicts, preserve both histories and fail closed after an automatic
checkpoint of publishable local code. Run only on the canonical main branch.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

CANONICAL = "Rapt0r06300/hyperliquid-smart-wallet-observer"
ALLOWED_ORIGINS = {
    f"https://github.com/{CANONICAL}",
    f"https://github.com/{CANONICAL}.git",
    f"git@github.com:{CANONICAL}",
    f"git@github.com:{CANONICAL}.git",
    f"ssh://git@github.com/{CANONICAL}",
    f"ssh://git@github.com/{CANONICAL}.git",
}
PROTECTED_DIRS = {
    "runtime", "logs", "data", "datasets", "catalog", "archive", "archives",
    "wheelhouse", "dist", "build", ".idea", ".vscode", ".claude",
    ".git", ".venv", "venv", "node_modules", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "__pycache__", ".tox",
}
# This root contains millions of tracked immutable data paths. A full worktree
# scan cannot complete within the launcher read budget; remote changes to one
# of these paths are still checked individually before any merge.
UNSCANNABLE_PROTECTED_ROOTS = {"datasets"}
PROTECTED_EXTENSIONS = {
    ".bundle", ".zip", ".7z", ".rar", ".tar", ".gz", ".zst", ".sqlite",
    ".sqlite3", ".db", ".parquet", ".feather", ".pkl", ".pickle",
    ".pem", ".key", ".p12", ".pfx", ".keystore", ".env",
}
SENSITIVE_PARTS = {
    "secrets", "secret", "credentials", "credential", "id_rsa",
    "id_ed25519", "private_key", "private-key", "mnemonic",
    "seed_phrase", "seed-phrase", "api_keys", "api-keys",
}
MAX_BLOB_BYTES = 95 * 1024 * 1024
MAX_RACE_RETRIES = 5
MAX_LOCAL_CHANGE_RETRIES = 3
PROTECTED_PATH_BATCH_SIZE = 128
# Data collectors may leave generated SAFE files staged while the operator is
# editing code. They stay outside code-only checkpoints, but their presence
# must not prevent an unrelated code publication. Secret-like files still
# fail closed through ``_can_defer_staged_protected`` below.
DEFERRED_STAGED_PROTECTED_ROOTS = {
    "archive", "archives", "build", "catalog", "data", "datasets", "dist",
    "logs", "wheelhouse",
}
SAFE_MAIN_PUSH_REFSPEC = (
    "push", "--progress", "origin", "HEAD:refs/heads/main",
)
# A shallow checkout only needs enough history to prove a common ancestor
# with the canonical main.  Fetching the entire repository can transfer
# millions of objects even when the two tips diverged by a handful of
# commits, so deepen progressively and stop as soon as reconciliation is
# provably possible.
# One bounded request is enough for the current main divergence and avoids a
# staircase of repeated network transfers.  If the common ancestor is older
# than this budget, fail closed and let the next run make an explicit choice.
HISTORY_DEEPEN_STEPS = (512,)
# Tree filtering is stricter than blob:none: it transfers commit ancestry
# without hydrating historical file trees or their blobs.  The worktree's
# current code remains local; any missing object required by Git can be
# fetched explicitly by Git itself, while SAFE/shard data is never bulk-read.
HISTORY_FETCH_FILTER = "--filter=tree:0"
HISTORY_FETCH_TIMEOUT_SECONDS = 300
MERGE_TREE_TIMEOUT_SECONDS = 120
# A rebase is bounded and receives a small budget per local commit.  A fixed
# five-minute wait made a double-click look hung when Git was waiting on a
# conflict, hook, or missing object.  The budget is deliberately capped: a
# slow or ambiguous replay must return a receipt and require an explicit
# retry, never keep the launcher blocked indefinitely.
REBASE_TIMEOUT_SECONDS = 60
REBASE_MIN_TIMEOUT_SECONDS = 20
REBASE_SECONDS_PER_COMMIT = 4
REBASE_ABORT_TIMEOUT_SECONDS = 8
# Git 2.54+ exposes ``git replay``.  It reconstructs a linear history while
# leaving the index and worktree untouched, so it avoids the per-commit
# checkout cost that made the classic rebase exceed the launcher budget on
# this partial clone.  The command is experimental; older Git versions fall
# back to the existing bounded rebase path.
GIT_REPLAY_TIMEOUT_SECONDS = 120
REPLAY_WORKTREE_TIMEOUT_SECONDS = 120
# Keep every network-bound Git operation bounded even when a future call site
# forgets to pass an explicit timeout.  The launcher is code-only, so a
# stalled authentication, SSH host-key prompt, or unreachable remote must
# fail closed quickly instead of leaving a double-click apparently hung.
DEFAULT_GIT_TIMEOUT_SECONDS = 300
# A checkpoint is built with the plumbing path below, which avoids Git's
# full-index refresh and hook/LFS scan on this partial clone.  Keep a generous
# bound for object creation and the atomic ref update, while still failing
# closed if either operation stops making progress.
COMMIT_TIMEOUT_SECONDS = 300
REMOTE_READ_TIMEOUT_SECONDS = 20
LOCAL_READ_TIMEOUT_SECONDS = 600
MIN_GIT_VERSION = (2, 30)
# A second double-click should wait for a short, bounded hand-off instead of
# forcing the user to rerun the launcher after a transient collision.  The
# bound remains fail-closed when the first synchronisation is slow or stuck.
MUTEX_WAIT_SECONDS = 20.0
MUTEX_POLL_SECONDS = 0.25
RECEIPT_HISTORY_LIMIT = 20
GIT_SYNC_ENGINE_BUILD = "2026-11-01-safe-main-promotion-v13"
# A single historical registry was moved out of the repository root. It is
# publishable only when both paths clean to its exact current HEAD blob.
SAFE_HISTORICAL_RELOCATIONS = {
    "CLAUDE_TASKS.jsonl": "docs/archive/root-history/CLAUDE_TASKS.jsonl",
}
AUTO_RESOLVABLE_CI_CONFLICTS = {
    ".github/workflows/alina-restore-safe-regression.yml",
    ".github/workflows/copy-vault-collector-soak.yml",
}
AUTO_RESOLVABLE_GOVERNANCE_CONFLICTS = {
    "docs/CODEX_GOAL_OBJECTIVE_V31.txt",
    "tests/test_roadmap_722_progress.py",
    "tools/roadmap_722_progress.py",
}
FORBIDDEN_HOSTED_CI_MARKERS = (
    "runs-on: self-hosted",
    'HL_ENABLE_MAINNET_EXECUTION: "1"',
    'REAL_MAINNET_TRADING: "true"',
    'HYPERSMART_ENABLE_REAL_ORDERS: "1"',
    'ENABLE_REAL_ORDERS: "1"',
)
MUTATING_GIT_COMMANDS = {
    "add", "commit", "commit-tree", "fetch", "merge", "rebase", "read-tree",
    "write-tree", "switch", "checkout", "update-ref", "push",
}


def _rebase_timeout_budget(replay_count: int) -> int:
    """Return a bounded, deterministic timeout for a local replay.

    The lower bound leaves Git enough time to start and finish a single
    commit on Windows; the upper bound prevents a stalled rebase from making
    the one-click launcher wait for minutes.  Invalid/negative counts are
    treated conservatively as one commit.
    """
    count = max(1, int(replay_count))
    return min(
        REBASE_TIMEOUT_SECONDS,
        max(REBASE_MIN_TIMEOUT_SECONDS, 12 + count * REBASE_SECONDS_PER_COMMIT),
    )


def _human_path_label(path: str) -> str:
    """Turn one publishable path into a short, truthful commit noun."""
    name = PurePosixPath(path).stem.replace("-", " ").replace("_", " ")
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    name = re.sub(r"\s+", " ", name).strip().lower()
    return name or "code changes"


def _common_filename_tokens(paths: list[str]) -> list[str]:
    """Return stable filename tokens shared by a small mixed code/test change."""
    token_lists: list[list[str]] = []
    for path in paths:
        stem = PurePosixPath(path).stem.lower()
        tokens = re.findall(r"[a-z0-9]+", stem)
        tokens = [token for token in tokens if token not in {"test", "tests", "py"}]
        if not tokens:
            return []
        token_lists.append(tokens)
    common = set(token_lists[0])
    for tokens in token_lists[1:]:
        common.intersection_update(tokens)
    return [token for token in token_lists[0] if token in common]


def _changed_diff_signal(diff_text: str) -> str:
    """Return only changed lines for semantic commit classification.

    Git headers and unchanged context are intentionally excluded so a commit
    subject cannot be chosen from a filename or an old comment alone.  The
    raw signal is retained for unit calls that provide a compact marker list
    instead of a complete unified diff.
    """
    raw = diff_text.casefold()
    changed: list[str] = []
    for line in raw.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith(("+", "-")):
            changed.append(line[1:])
    return "\n".join(changed) if changed else raw


def _semantic_subject(prefix: str, scope: str, detail: str, count: int) -> str:
    """Build a Conventional-Commit subject with a bounded truthful suffix."""
    suffix = f" ({count} paths)"
    subject = f"{prefix}({scope}): {detail}{suffix}"
    if len(subject) <= 72:
        return subject
    subject = f"{prefix}({scope}): {detail}"
    if len(subject) <= 72:
        return subject
    return f"{prefix}({scope}): update ({count} paths)"


def _mixed_batch_detail(paths: list[str], diff_signal: str) -> str | None:
    """Return a truthful summary for a large batch with several repository areas.

    A first-file fallback is misleading when a checkpoint contains tooling,
    configuration, documentation and tests together.  This helper only runs
    after the narrow path-specific rules, and it deliberately uses broad
    safeguards rather than inventing a feature name from one path.
    """
    if len(paths) < 4:
        return None
    areas = {
        "source" if any(path.startswith("src/") for path in paths) else None,
        "tests" if any(path.startswith("tests/") for path in paths) else None,
        "tooling" if any(
            path.startswith("tools/") or path.endswith((".cmd", ".ps1"))
            for path in paths
        ) else None,
        "docs" if any(path.startswith("docs/") for path in paths) else None,
        "configuration" if any(
            path in {"pyproject.toml", "requirements.txt"} for path in paths
        ) else None,
    }
    areas.discard(None)
    if len(areas) < 2:
        return None
    signal = diff_signal.casefold()
    if "sync" in signal or "github" in signal:
        if "portable" in signal or "launcher" in signal:
            return "update sync and portability safeguards"
        return "update synchronization safeguards"
    if "portable" in signal or "launcher" in signal:
        return "update portability safeguards"
    return "update repository tooling and safeguards"


def _commit_subject(paths: list[str], diff_text: str = "") -> str:
    """Build a deterministic semantic subject from the staged code paths.

    The sync helper must never invent a product claim from a diff it cannot
    understand. It uses repository areas, filenames, and a bounded staged-diff
    signal, so the subject stays useful while remaining honest for arbitrary
    local edits.
    """
    normalized = sorted(set(path.replace("\\", "/") for path in paths))
    diff_signal = _changed_diff_signal(diff_text)
    if not normalized:
        return "chore(sync): checkpoint code changes"

    if all(path.startswith(".github/workflows/") for path in normalized):
        prefix, scope = "ci", "github"
    elif all(path.startswith("tests/") for path in normalized):
        prefix, scope = "test", "validation"
    elif all(path.startswith("docs/") for path in normalized):
        prefix, scope = "docs", "project"
    elif all(path.startswith("src/") for path in normalized):
        prefix = "feat" if any(
            "/copy_vault/" in f"/{path}/" or "copy_vault" in path
            for path in normalized
        ) else "chore"
        scope = (
            "copy-vault" if any("copy_vault" in path for path in normalized)
            else "runtime"
        )
    elif all(path.startswith("tools/") for path in normalized):
        prefix, scope = "chore", "tooling"
    else:
        prefix, scope = "chore", "repository"

    sync_engine_paths = (
        2 <= len(normalized) <= 3
        and any(path.endswith("tools/alina_git_code_sync.py") for path in normalized)
        and any(path.endswith("tests/test_alina_git_code_sync.py") for path in normalized)
    )
    if sync_engine_paths and any(
        marker in diff_signal
        for marker in ("git_terminal_prompt", "gcm_interactive", "credential manager")
    ):
        return (
            "fix(sync): fail fast on Git auth prompts "
            f"({len(normalized)} paths)"
        )

    if sync_engine_paths and "reapply-cherry-picks" in diff_signal:
        return (
            "fix(sync): avoid slow upstream rebase scans "
            f"({len(normalized)} paths)"
        )

    if sync_engine_paths and any(marker in diff_signal for marker in (
        "git replay", "git_replay_index_preserving", "replay_worktree_timeout",
    )):
        return (
            "fix(sync): accelerate linear Git replay "
            f"({len(normalized)} paths)"
        )

    if sync_engine_paths and any(marker in diff_signal for marker in (
        "git_editor", "git_sequence_editor", "git_merge_autoedit",
        "rebase_timeout", "rebase timeout",
        "verified-remote-receipt-v",
    )):
        return (
            "fix(sync): prevent interactive rebase stalls "
            f"({len(normalized)} paths)"
        )

    if sync_engine_paths and any(marker in diff_signal for marker in (
        "mutex_wait_seconds", "mutex_poll_seconds", "_lock_mutex_handle",
        "transient second invocation",
    )):
        return (
            "fix(sync): wait for concurrent launcher safely "
            f"({len(normalized)} paths)"
        )

    if sync_engine_paths and any(marker in diff_signal for marker in (
        "unexpected internal sync error", "unexpected_engine_error",
        "except exception", "fail closed on unexpected",
    )):
        return (
            "fix(sync): fail closed on engine errors "
            f"({len(normalized)} paths)"
        )

    if sync_engine_paths and any(marker in diff_signal for marker in (
        "restoration_artifacts_from_train",
        "train_ledger_reference",
        "durable train outputs",
    )):
        return "fix(sync): name semantic Copy-Vault commits (2 paths)"

    if (
        any(path.endswith("src/hl_observer/backtesting/copy_vault_leader_selection_comparison.py") for path in normalized)
        and any(path.endswith("tests/test_copy_vault_leader_selection_comparison.py") for path in normalized)
        and any(marker in diff_signal for marker in (
            "replay_receipt",
            "replay_not_completed",
            "canonical replay",
        ))
    ):
        return (
            "fix(copy-vault): require canonical replay receipt "
            f"({len(normalized)} paths)"
        )

    if sync_engine_paths and (
        not diff_signal
        or any(marker in diff_signal for marker in ("remote_sha", "github sha", "pushed_head"))
    ):
        return (
            "fix(sync): verify final GitHub SHA in receipt "
            f"({len(normalized)} paths)"
        )

    # Generic rules are deliberately restricted to small coherent changes.
    # A large/mixed batch may contain several independent topics; choosing one
    # marker from one file would produce a misleading commit subject.
    semantic_rules = (
        (
            ("promote-current-to-main", "promotion fast-forward",
             "promoted_current_branch", "branch_after"),
            "promote current branch safely",
        ),
        (
            ("commit_subject", "proposed_commit_message", "semantic commit",
             "commit intent"),
            "name commits from change intent",
        ),
        (
            ("protected_local_changes", "safe data", "safe shards",
             "shard conservation"),
            "preserve SAFE data boundaries",
        ),
        (
            ("dry-run", "dry_run", "read-only", "read only"),
            "preserve read-only safeguards",
        ),
        (
            ("timeout", "retry", "poll", "bounded wait"),
            "bound synchronization waits",
        ),
        (
            ("merge-base", "fast-forward", "rebase", "git replay"),
            "reconcile Git history safely",
        ),
    )
    if len(normalized) <= 3:
        for markers, detail in semantic_rules:
            if any(marker in diff_signal for marker in markers):
                return _semantic_subject("fix", "sync", detail, len(normalized))

    if (
        len(normalized) <= 3
        and
        any(path.endswith("POUSSER-GITHUB-FORCE.cmd") for path in normalized)
        and any(path.endswith("tools/alina_git_code_sync.py") for path in normalized)
    ):
        return _semantic_subject(
            "fix", "sync", "harden safe GitHub launcher", len(normalized)
        )

    if (
        len(normalized) == 2
        and any(path.endswith("tools/restore_alina.py") for path in normalized)
        and any(path.endswith("tests/test_restore_alina.py") for path in normalized)
    ):
        return "fix(copy-vault): restore filtered SAFE registry (2 paths)"

    if (
        len(normalized) == 2
        and any(path.endswith("tools/continuous_reconcile_backlog.py") for path in normalized)
        and any(path.endswith("tests/test_continuous_reconcile_backlog.py") for path in normalized)
    ):
        return "fix(recovery): resume historical SAFE backlog (2 paths)"

    if (
        any(path.endswith("src/hl_observer/control_plane/campaign_adapters.py") for path in normalized)
        and any(path.endswith("tests/test_campaign_adapter_diagnostics.py") for path in normalized)
    ):
        return (
            "fix(recovery): preserve timed-out adapter checkpoints "
            f"({len(normalized)} paths)"
        )

    if (
        any(path.endswith("src/hl_observer/copying/consensus_leader_selector.py") for path in normalized)
        and any(path.endswith("tests/test_consensus_leader_selector.py") for path in normalized)
    ):
        return (
            "fix(copy-vault): guard non-finite consensus inputs "
            f"({len(normalized)} paths)"
        )

    if (
        len(normalized) == 2
        and any(path.endswith("src/hl_observer/backtesting/copy_vault_local_lab.py") for path in normalized)
        and any(path.endswith("tests/test_copy_vault_local_lab.py") for path in normalized)
        and any(marker in diff_signal for marker in (
            "restoration_artifacts_from_train",
            "train_ledger_reference",
            "durable train outputs",
        ))
    ):
        return "fix(copy-vault): preserve TRAIN restoration artifacts (2 paths)"

    if any(
        token in path
        for path in normalized
        for token in ("l4_capture", "order_intent", "entity_resolution")
    ):
        return (
            "fix(copy-vault): guard L4 intent and entity provenance "
            f"({len(normalized)} paths)"
        )

    if len(normalized) >= 2 and any("copy_vault" in path for path in normalized):
        common = _common_filename_tokens(normalized)
        for token in ("copy", "vault"):
            common = [item for item in common if item != token]
        if common:
            subject = f"feat(copy-vault): {' '.join(common)} ({len(normalized)} paths)"
            if len(subject) <= 72:
                return subject

    mixed_detail = _mixed_batch_detail(normalized, diff_signal)
    if mixed_detail:
        return _semantic_subject(prefix, scope, mixed_detail, len(normalized))

    labels = [_human_path_label(path) for path in normalized]
    if len(labels) == 1:
        detail = labels[0]
    elif len(labels) == 2:
        detail = f"{labels[0]} and {labels[1]}"
    else:
        detail = f"{labels[0]}, {labels[1]} and {len(labels) - 2} other files"
    subject = f"{prefix}({scope}): update {detail}"
    if len(subject) > 72:
        subject = (
            f"{prefix}({scope}): update {labels[0]} "
            f"({len(normalized)} paths)"
        )
    if len(subject) > 72:
        subject = f"{prefix}({scope}): update ({len(normalized)} paths)"
    return subject


class SyncBlocked(RuntimeError):
    """Unsafe to proceed while preserving local and remote history."""


class LocalEditsDetected(SyncBlocked):
    """Source changed while network or Git reconciliation was in flight."""


def _redact_sensitive_text(value: str) -> str:
    """Remove credentials and bearer tokens before text reaches a receipt/UI."""
    redacted = re.sub(
        r"(https?://)([^/@\s]+):([^/@\s]+)@",
        r"\1[REDACTED]@",
        value,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)\b",
        "[REDACTED]",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        r"(authorization\s*:\s*bearer\s+)\S+",
        r"\1[REDACTED]",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        r"([?&](?:access_token|api[_-]?key|password|token|secret)=)[^&\s]+",
        r"\1[REDACTED]",
        redacted,
        flags=re.IGNORECASE,
    )
    return redacted


def _classify_git_failure(
    detail: str, returncode: int,
) -> Literal[
    "retryable_race", "retryable_network", "auth", "protected",
    "configuration", "unknown",
]:
    """Classify a Git transport error without guessing that every failure is a race."""
    lowered = _redact_sensitive_text(detail).casefold()
    if any(marker in lowered for marker in (
        "non-fast-forward", "non fast-forward", "fetch first",
        "failed to push some refs", "remote rejected",
    )):
        return "retryable_race"
    if any(marker in lowered for marker in (
        "authentication failed", "terminal prompts disabled",
        "could not read username", "could not read password",
        "permission denied (publickey)", "invalid username or password",
    )):
        return "auth"
    if any(marker in lowered for marker in (
        "protected branch", "hook declined", "gh006",
        "not allowed to push", "permission denied to update",
    )):
        return "protected"
    if any(marker in lowered for marker in (
        "no such remote", "does not appear to be a git repository",
        "invalid remote", "repository not found",
    )):
        return "configuration"
    if any(marker in lowered for marker in (
        "could not resolve host", "unable to access", "connection reset",
        "connection refused", "connection timed out", "timed out",
        "network is unreachable", "temporary failure in name resolution",
    )):
        return "retryable_network"
    if returncode in {128, 129} and not lowered:
        return "unknown"
    return "unknown"


def _atomic_json_write(destination: Path, payload: object) -> None:
    """Write a JSON receipt durably, then publish it with one atomic replace."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=f".{destination.name}.", suffix=".tmp", delete=False,
        ) as out:
            temporary = Path(out.name)
            json.dump(payload, out, indent=2, sort_keys=True, ensure_ascii=False)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _verify_push_porcelain(
    output: str, expected_sha: str, expected_ref: str,
) -> None:
    """Require one successful, non-forced porcelain result for the target ref."""
    if not re.fullmatch(r"[0-9a-f]{40,64}", expected_sha):
        raise SyncBlocked("SHA locale invalide; preuve de push refusee.")
    matches: list[tuple[str, str]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split(None, 2)
        if fields and fields[0] in {"*", "=", "+", "!", "-"}:
            flag = fields[0]
            mapping = fields[1] if len(fields) > 1 else ""
        else:
            # A successful porcelain update may use a leading blank flag.
            flag = " "
            mapping = fields[0] if fields else ""
        if ":" not in mapping:
            continue
        _source, target = mapping.split(":", 1)
        if target == expected_ref:
            matches.append((flag, raw_line))
    if len(matches) != 1:
        raise SyncBlocked(
            f"Preuve push absente ou ambigue pour {expected_ref}; "
            "aucun succes distant declare."
        )
    flag, line = matches[0]
    if flag in {"!", "+", "-"}:
        raise SyncBlocked(
            f"Preuve push refusee pour {expected_ref}: statut {flag}."
        )
    ranges = re.findall(
        r"\b([0-9a-f]{7,64})\.\.([0-9a-f]{7,64})\b", line.casefold()
    )
    if ranges and not any(
        expected_sha.startswith(target_sha) for _source_sha, target_sha in ranges
    ):
        raise SyncBlocked(
            f"Preuve push incoherente pour {expected_ref}; SHA locale inattendue."
        )


def _paths(data: bytes) -> list[str]:
    if not data:
        return []
    if not data.endswith(b"\0"):
        raise SyncBlocked("Sortie Git NUL tronquee; inventaire abandonne.")
    try:
        return [name.decode("utf-8") for name in data[:-1].split(b"\0") if name]
    except UnicodeDecodeError as exc:
        raise SyncBlocked("Nom Git non UTF-8, selection automatique refusee.") from exc


def _status_records(data: bytes) -> list[tuple[bytes, list[str]]]:
    """Decode status records from `git status --porcelain=v1 -z` safely."""
    if not data:
        return []
    if not data.endswith(b"\0"):
        raise SyncBlocked("Sortie Git status NUL tronquee; inventaire abandonne.")
    records = data[:-1].split(b"\0")
    records_out: list[tuple[bytes, list[str]]] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if len(record) < 4 or record[2:3] != b" ":
            raise SyncBlocked("Enregistrement Git status invalide; inventaire abandonne.")
        status, path = record[:2], record[3:]
        try:
            paths = [path.decode("utf-8")]
            if b"R" in status or b"C" in status:
                if index >= len(records):
                    raise SyncBlocked("Ancien chemin de renommage Git absent.")
                paths.append(records[index].decode("utf-8"))
                index += 1
        except UnicodeDecodeError as exc:
            raise SyncBlocked("Nom Git status non UTF-8; inventaire abandonne.") from exc
        records_out.append((status, paths))
    return records_out


def _status_entries(data: bytes) -> tuple[list[str], list[str]]:
    """Split porcelain status paths into staged and worktree changes."""
    staged: list[str] = []
    tracked: list[str] = []
    for status, paths in _status_records(data):
        if status[:1] != b" ":
            staged.extend(paths)
        if status[1:2] != b" ":
            tracked.extend(paths)
    return staged, tracked


def _status_paths(data: bytes) -> list[str]:
    """Decode all paths from `git status --porcelain=v1 -z` safely."""
    return [path for _status, paths in _status_records(data) for path in paths]


def _protected(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if not parts or normalized.startswith("/") or ".." in parts:
        return True
    lower = tuple(part.casefold() for part in parts)
    # Root data trees are excluded; equally named Python package subfolders
    # (src/hl_observer/datasets, src/hl_observer/runtime, etc.) ARE CODE.
    if lower[0] in PROTECTED_DIRS:
        return True
    if any(part in SENSITIVE_PARTS for part in lower[:-1]):
        return True
    if any(part in {".git", ".venv", "venv", "node_modules", "__pycache__"}
           for part in lower[:-1]):
        return True
    name = lower[-1]
    if name.startswith(".env") or name.endswith(".env"):
        return True
    if any(secret in name for secret in ("id_rsa", "id_ed25519", "private_key", "private-key")):
        return True
    if normalized.casefold().startswith(("tools/git/", "tools/python/")):
        return True
    if name in SENSITIVE_PARTS or Path(name).suffix in PROTECTED_EXTENSIONS:
        return True
    if name.endswith((".bundle", ".jsonl", ".jsonl.gz")):
        return True
    return name in ("thumbs.db", "desktop.ini")


def _can_defer_staged_protected(path: str) -> bool:
    """Return whether a staged protected path is collector-owned SAFE data.

    This is intentionally narrower than ``_protected``. A staged ``.env`` or
    key-looking file must still stop the run; only known data/runtime roots
    may remain staged while an isolated code checkpoint is built.
    """
    normalized = path.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if not parts or parts[0].casefold() not in DEFERRED_STAGED_PROTECTED_ROOTS:
        return False
    lowered = tuple(part.casefold() for part in parts)
    if any(part in SENSITIVE_PARTS for part in lowered):
        return False
    name = lowered[-1]
    if name.startswith(".env") or name.endswith(".env"):
        return False
    if any(secret in name for secret in (
        "id_rsa", "id_ed25519", "private_key", "private-key",
    )):
        return False
    return Path(name).suffix not in {
        ".pem", ".key", ".p12", ".pfx", ".keystore",
    }


def _git_operation_label(args: list[str]) -> str:
    """Return a safe, user-facing description without echoing raw arguments."""
    verb = args[0] if args else ""
    if verb == "rev-parse":
        return "Verifier le depot et son HEAD"
    if verb == "branch":
        return "Verifier la branche active"
    if verb == "remote":
        return "Verifier le depot GitHub canonique"
    if verb == "status":
        return "Inventaire des modifications locales"
    if verb == "ls-files":
        return "Inventaire Git cible (sans lire les shards)"
    if verb == "diff":
        return "Comparer les fichiers suivis par Git"
    if verb == "fetch":
        return "Recevoir les objets Git de GitHub main"
    if verb == "merge-base":
        return "Comparer l'historique local et GitHub"
    if verb == "merge":
        return "Adopter GitHub main en avance rapide"
    if verb == "rebase":
        if "--abort" in args:
            return "Annuler le rebase inacheve"
        if "--continue" in args:
            return "Continuer le rebase sans choix automatique"
        if "--skip" in args:
            return "Ignorer le commit de rebase vide"
        return "Rejouer les commits locaux sans commit de fusion"
    if verb == "replay":
        return "Rejouer rapidement les commits sans toucher aux donnees"
    if verb == "read-tree":
        return "Mettre a jour le code apres le rejeu Git"
    if verb == "rev-list":
        return "Verifier les commits locaux a rejouer"
    if verb == "hash-object":
        return "Verifier le blob apres normalisation Git"
    if verb == "push":
        if "-h" in args or "--help" in args:
            return "Verifier la capacite push porcelain (sans publication)"
        return "Publier vers GitHub main sans force"
    if verb == "add":
        return "Preparer les fichiers de code admissibles"
    if verb == "commit":
        return "Creer le checkpoint local du travail"
    if verb == "write-tree":
        return "Construire l'arbre Git depuis l'index courant"
    if verb == "commit-tree":
        return "Creer le checkpoint Git sans re-scanner l'index"
    if verb == "symbolic-ref":
        return "Verifier la reference de branche"
    if verb == "update-ref":
        return "Enregistrer le checkpoint Git local"
    if verb == "show":
        return "Lire une version Git pour le diagnostic de conflit"
    return "Commande Git de controle"


def _terminate_process_tree(
    process: subprocess.Popen[bytes], root: Path | None = None,
) -> tuple[bool, list[int]]:
    """Stop a timed-out Git process and descendants without leaking pipes."""
    if process.poll() is not None:
        return True, []
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        killed = result.returncode == 0
    else:
        process.kill()
        killed = True
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1)
        killed = False
    residual = _remaining_process_ids(root or Path.cwd(), process.pid)
    return killed and not residual, residual


def _remaining_process_ids(root: Path, parent_pid: int) -> list[int]:
    """Return surviving descendants after a process-tree termination attempt."""
    if os.name != "nt":
        return []
    del root
    command = (
        "$ErrorActionPreference='Stop'; "
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId | "
        "ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
             "-Command", command],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
            check=False,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return [parent_pid]
        decoded = json.loads(completed.stdout)
        rows = decoded if isinstance(decoded, list) else [decoded]
        parents: dict[int, list[int]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            pid = row.get("ProcessId")
            ppid = row.get("ParentProcessId")
            if isinstance(pid, int) and isinstance(ppid, int):
                parents.setdefault(ppid, []).append(pid)
        pending = [parent_pid]
        descendants: set[int] = set()
        while pending:
            current = pending.pop()
            for child in parents.get(current, []):
                if child not in descendants:
                    descendants.add(child)
                    pending.append(child)
        surviving = [parent_pid, *sorted(descendants)]
        live = set()
        for pid in surviving:
            probe = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
                check=False,
            )
            if str(pid) in probe.stdout:
                live.add(pid)
        return sorted(live)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, TypeError):
        return [parent_pid]


def _index_lock_path(root: Path) -> Path | None:
    """Return the ordinary repository index lock without following a worktree file."""
    git_path = root / ".git"
    if git_path.is_dir():
        return git_path / "index.lock"
    return None


def _run_git(
    root: Path,
    git: str,
    args: list[str],
    *,
    input_bytes: bytes | None = None,
    timeout: int = 300,
    live_stderr: bool = False,
    on_progress=None,
) -> subprocess.CompletedProcess[bytes]:
    env = dict(os.environ)
    env["GIT_LFS_SKIP_SMUDGE"] = "1"
    # A double-clicked launcher must never wait for a hidden terminal or
    # Credential Manager prompt.  Authentication failures stay explicit and
    # fail closed instead of looking like a hung Git synchronization.
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "Never"
    # HTTPS and SSH must both fail closed.  GIT_TERMINAL_PROMPT does not stop
    # an SSH client from waiting for a host-key/passphrase prompt.  Respect a
    # caller-provided command, but make the default non-interactive and short.
    env.setdefault(
        "GIT_SSH_COMMAND",
        "ssh -o BatchMode=yes -o ConnectTimeout=8",
    )
    env["GIT_OPTIONAL_LOCKS"] = (
        "0" if args and args[0] in {"ls-files", "status", "diff"} else "1"
    )
    # This synchronizer admits only code paths and explicitly excludes LFS or
    # shard transfers.  Repository post-commit/pre-push hooks can otherwise
    # start Git LFS scans after the checkpoint has already been created, making
    # a code-only run wait for an unrelated data plane.  The engine performs
    # its own exact SHA/protected-path proof, so hooks are isolated per process
    # and the user's repository configuration is never changed.
    # The production caller passes Git.  Keeping non-Git test doubles intact
    # makes timeout/process-tree tests exercise the requested executable
    # rather than accidentally feeding Git-only options to Python.
    is_git_executable = Path(git).stem.casefold() == "git"
    command = (
        [git, "-c", "core.hooksPath=NUL", *args]
        if is_git_executable
        else [git, *args]
    )
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=root,
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=None if live_stderr else subprocess.PIPE,
        env=env,
    )
    while True:
        elapsed = time.monotonic() - started
        remaining = timeout - elapsed
        if remaining <= 0:
            killed_process_tree, residual_process_ids = _terminate_process_tree(
                process, root,
            )
            try:
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired as communicate_timeout:
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
                timeout_error = subprocess.TimeoutExpired(
                    command,
                    timeout,
                    output=communicate_timeout.output,
                    stderr=communicate_timeout.stderr,
                )
                timeout_error.killed_process_tree = killed_process_tree
                timeout_error.residual_process_ids = residual_process_ids
                timeout_error.git_index_lock_present = bool(
                    _index_lock_path(root)
                    and _index_lock_path(root).exists()
                )
                raise timeout_error from communicate_timeout
            timeout_error = subprocess.TimeoutExpired(
                command, timeout, output=stdout, stderr=stderr,
            )
            timeout_error.killed_process_tree = killed_process_tree
            timeout_error.residual_process_ids = residual_process_ids
            timeout_error.git_index_lock_present = bool(
                _index_lock_path(root)
                and _index_lock_path(root).exists()
            )
            raise timeout_error
        try:
            stdout, stderr = process.communicate(
                input=input_bytes, timeout=min(8.0, remaining),
            )
            break
        except subprocess.TimeoutExpired:
            if on_progress is not None:
                on_progress(time.monotonic() - started)
            # communicate() can accept input only once. After its first call,
            # stdin has been closed and later calls must not send bytes again.
            input_bytes = None
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _lock_mutex_handle(handle) -> None:
    """Acquire the process mutex without touching Git's own lock files."""
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_mutex_handle(handle) -> None:
    """Release the process mutex acquired by :func:`_lock_mutex_handle`."""
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def _mutex(git_dir: Path):
    """Use an OS mutex; wait briefly for a transient second invocation."""
    with (git_dir / "alina-sync.mutex").open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + MUTEX_WAIT_SECONDS
        last_error: OSError | None = None
        while True:
            handle.seek(0)
            try:
                _lock_mutex_handle(handle)
                break
            except OSError as exc:
                last_error = exc
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SyncBlocked(
                        "Une autre synchronisation Alina est active; "
                        f"attente bornee de {MUTEX_WAIT_SECONDS:.1f}s depassee."
                    ) from last_error
                time.sleep(min(MUTEX_POLL_SECONDS, remaining))
        try:
            yield
        finally:
            handle.seek(0)
            _unlock_mutex_handle(handle)


class Synchronizer:
    def __init__(self, root: Path, git: str = "git", *, dry_run: bool = False,
                 allow_test_remote: bool = False,
                 promote_current_to_main: bool = False):
        self.root = root.resolve()
        self.git = git
        self.dry_run = dry_run
        self.allow_test_remote = allow_test_remote
        self.promote_current_to_main = promote_current_to_main
        self.changed_python_paths: list[str] = []
        self._inventory_cache: tuple[list[str], list[str], list[str]] | None = None
        self._pathspec_cache: dict[bool, tuple[str, ...]] = {}
        self._remote_snapshot_ready = False
        self._remote_snapshot_sha: str | None = None
        self._allow_protected_local_checkpoint = False
        self._deferred_local_paths: set[str] = set()
        self._deferred_staged_protected_paths: set[str] = set()
        self._command_count = 0
        self.report: dict[str, object] = {
            "schema": "alina.git_code_reconciliation.v1",
            "engine_build": GIT_SYNC_ENGINE_BUILD,
            "run_id": None,
            "mode": "DRY_RUN" if dry_run else "SYNC",
            "status": "NOT_STARTED",
            "shard_downloads": False,
            "force_push": False,
            "reset_or_clean": False,
            "shallow_repository": None,
            "history_expanded": False,
            "history_mode": None,
            "history_deepen_steps": [],
            "local_commit_created": False,
            "commit_message": None,
            "commit_backend": None,
            "proposed_commit_message": None,
            "branch_before": None,
            "branch_after": None,
            "promoted_current_branch": False,
            "promoted_from_branch": None,
            "promotion_sha": None,
            "merge_commits_created": 0,
            "rebases_performed": 0,
            "push_attempts": 0,
            "push_failure_classes": [],
            "local_syntax_check": "NOT_RUN",
            "fast_path": None,
            "remote_sha_observed": None,
            "remote_url_observed": None,
            "push_url_observed": None,
            "push_capability": "NOT_CHECKED",
            "remote_capability": "NOT_CHECKED",
            "push_ref_result": None,
            "git_version": None,
            "python_version": None,
            "hooks_isolated": True,
            "git_index_lock_detected": False,
            "mutations": [],
            "remote_snapshot_reused": False,
            "commit_timeout_recovered": False,
            "phases": {},
            "verified_historical_relocations": [],
            "git_commands": [],
        }

    def command(self, *args: str, input_bytes: bytes | None = None,
                check: bool = True, timeout: int = 300,
                expected_returncodes: tuple[int, ...] = ()
                ) -> subprocess.CompletedProcess[bytes]:
        git_args = list(args)
        if timeout == 300:
            verb = git_args[0] if git_args else ""
            timeout = (
                REMOTE_READ_TIMEOUT_SECONDS
                if verb in {"ls-remote", "remote"}
                else COMMIT_TIMEOUT_SECONDS
                if verb == "commit"
                else DEFAULT_GIT_TIMEOUT_SECONDS
                if verb in {"fetch", "push"}
                else LOCAL_READ_TIMEOUT_SECONDS
            )
        label = _git_operation_label(git_args)
        self._command_count += 1
        command_number = self._command_count
        # Capture network stderr so credentials embedded by a credential
        # helper or remote URL can be redacted before they reach the console
        # and the receipt.  Git progress is replayed after completion below.
        live_stderr = False
        self.say(f"[GIT {command_number:03d}] {label} ...")
        started = time.monotonic()

        def progress(elapsed: float) -> None:
            self.say(f"[EN COURS] {label} | {elapsed:.0f} s ecoulees")

        try:
            with self._timed_phase(f"git_{command_number:03d}", timeout):
                completed = _run_git(
                    self.root,
                    self.git,
                    git_args,
                    input_bytes=input_bytes,
                    timeout=timeout,
                    live_stderr=live_stderr,
                    on_progress=progress,
                )
        except subprocess.TimeoutExpired as timeout_error:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            self._record_git_command(
                command_number, label, -1, elapsed_ms, timed_out=True,
                killed_process_tree=bool(
                    getattr(timeout_error, "killed_process_tree", False)
                ),
                residual_process_ids=list(
                    getattr(timeout_error, "residual_process_ids", [])
                ),
                git_index_lock_present=bool(
                    getattr(timeout_error, "git_index_lock_present", False)
                ),
            )
            if git_args and git_args[0] in MUTATING_GIT_COMMANDS and not (
                git_args[0] == "push"
                and any(option in git_args for option in ("-h", "--help", "--dry-run"))
            ):
                mutations = self.report.setdefault("mutations", [])
                if isinstance(mutations, list):
                    mutations.append({
                        "operation": label,
                        "exit_code": -1,
                        "duration_ms": elapsed_ms,
                        "timed_out": True,
                    })
            self.say(
                f"[TIMEOUT] {label} apres {elapsed_ms / 1000:.1f} s; "
                "le processus Git a ete arrete."
            )
            raise

        elapsed_ms = int((time.monotonic() - started) * 1000)
        self._record_git_command(
            command_number, label, completed.returncode, elapsed_ms,
        )
        is_mutation = bool(git_args and git_args[0] in MUTATING_GIT_COMMANDS)
        if git_args and git_args[0] == "push" and any(
            option in git_args for option in ("-h", "--help", "--dry-run")
        ):
            is_mutation = False
        if is_mutation:
            mutations = self.report.setdefault("mutations", [])
            if isinstance(mutations, list):
                mutations.append({
                    "operation": label,
                    "exit_code": completed.returncode,
                    "duration_ms": elapsed_ms,
                })
        outcome = (
            "OK" if completed.returncode == 0
            else "INFO" if completed.returncode in expected_returncodes
            else "ECHEC"
        )
        self.say(
            f"[{outcome}] {label} | code={completed.returncode} | "
            f"duree={elapsed_ms / 1000:.2f} s"
        )
        captured_stderr = _redact_sensitive_text(
            (completed.stderr or b"").decode("utf-8", errors="replace").strip()
        )
        if captured_stderr and git_args and git_args[0] in {"fetch", "push"}:
            self.say("[GIT DETAIL] " + captured_stderr[:1800])
        if check and completed.returncode and completed.returncode not in expected_returncodes:
            stderr = captured_stderr
            stdout = _redact_sensitive_text((completed.stdout or b"").decode(
                "utf-8", errors="replace",
            ).strip())
            detail = stderr or stdout
            if not detail:
                detail = "aucun detail Git recupere"
            raise SyncBlocked(
                f"git {git_args[0]} a echoue (code {completed.returncode}): "
                f"{detail[:1400]}"
            )
        return completed

    def _record_git_command(
        self, number: int, label: str, exit_code: int, elapsed_ms: int,
        *, timed_out: bool = False, killed_process_tree: bool | None = None,
        residual_process_ids: list[int] | None = None,
        git_index_lock_present: bool = False,
    ) -> None:
        commands = self.report.setdefault("git_commands", [])
        if isinstance(commands, list):
            entry = {
                "number": number,
                "operation": label,
                "exit_code": exit_code,
                "duration_ms": elapsed_ms,
                "timed_out": timed_out,
            }
            if timed_out:
                entry["killed_process_tree"] = bool(killed_process_tree)
                entry["residual_process_ids"] = list(residual_process_ids or [])
                entry["git_index_lock_present"] = git_index_lock_present
            commands.append(entry)

    def text(self, *args: str) -> str:
        return self.command(*args).stdout.decode("utf-8", errors="replace").strip()

    @staticmethod
    def say(message: str) -> None:
        stamp = datetime.now().astimezone().strftime("%H:%M:%S")
        print(f"[{stamp}] {message}", flush=True)

    def _verify_git_capabilities(self) -> None:
        """Check local Git/Python features before any repository mutation."""
        version = self.text("--version")
        match = re.search(r"git version (\d+)\.(\d+)(?:\.(\d+))?", version)
        if not match:
            raise SyncBlocked("Version Git illisible; synchronisation refusee.")
        git_version = tuple(int(part or 0) for part in match.groups())
        if git_version[:2] < MIN_GIT_VERSION:
            raise SyncBlocked(
                f"Git {version} trop ancien; minimum requis "
                f"{MIN_GIT_VERSION[0]}.{MIN_GIT_VERSION[1]}."
            )
        self.report["git_version"] = _redact_sensitive_text(version)
        self.report["python_version"] = sys.version.split()[0]
        help_result = self.command(
            "push", "-h", check=False, expected_returncodes=(0, 129),
        )
        help_text = "\n".join(
            part.decode("utf-8", errors="replace")
            for part in (help_result.stdout or b"", help_result.stderr or b"")
            if part
        )
        if "porcelain" not in help_text.casefold():
            raise SyncBlocked(
                "Git local ne declare pas --porcelain; preuve de push impossible."
            )
        self.report["push_capability"] = "PORCELAIN_SUPPORTED"

    def preflight(
        self, *, allow_shallow: bool = False, allow_non_main: bool = False,
    ) -> Path:
        self.say("[MOTEUR 1/5] Controle du depot, de main et du remote autorise.")
        self._verify_git_capabilities()
        top = Path(self.text("rev-parse", "--show-toplevel")).resolve()
        if top != self.root:
            raise SyncBlocked(f"Lanceur hors racine du depot: {top}")
        branch = self.text("branch", "--show-current")
        self.report["branch_before"] = branch or None
        if not branch:
            raise SyncBlocked(
                "HEAD detache; impossible de promouvoir automatiquement vers main."
            )
        if branch != "main" and not allow_non_main:
            raise SyncBlocked(
                f"Branche active '{branch}' refusee: main est la seule branche "
                "de livraison. Le lanceur peut la promouvoir automatiquement "
                "avec --promote-current-to-main, sans force ni reset."
            )
        shallow = self.text("rev-parse", "--is-shallow-repository") == "true"
        self.report["shallow_repository"] = shallow
        if shallow and not allow_shallow:
            raise SyncBlocked("Clone shallow: historique insuffisant pour fusionner.")
        if shallow:
            self.say(
                "[PREFLIGHT] Clone shallow detecte; lecture seule/checkpoint "
                "autorise, synchronisation completee apres extension non destructive."
            )
        remote = self.text("remote", "get-url", "origin")
        push_remote = self.text("remote", "get-url", "--push", "origin")
        test_remote_allowed = (
            self.allow_test_remote
            and os.environ.get("ALINA_SYNC_TEST_REMOTE_ALLOWED") == "1"
        )
        if remote not in ALLOWED_ORIGINS and not test_remote_allowed:
            raise SyncBlocked(f"origin non canonique: {remote}. Push interdit.")
        if push_remote not in ALLOWED_ORIGINS and not test_remote_allowed:
            raise SyncBlocked(
                f"pushurl non canonique: {push_remote}. Push interdit."
            )
        if not push_remote:
            raise SyncBlocked("pushurl origin vide; capacite de publication inconnue.")
        gitdir = Path(self.text("rev-parse", "--absolute-git-dir")).resolve()
        index_lock = _index_lock_path(self.root)
        if index_lock is not None and index_lock.exists():
            self.report["git_index_lock_detected"] = True
            raise SyncBlocked(
                "Verrou Git index.lock present; aucun add, commit ou push. "
                "Fermer le processus Git proprietaire et traiter ce verrou "
                "manuellement avant de relancer."
            )
        for marker in (
            "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG",
            "rebase-apply", "rebase-merge", "sequencer",
        ):
            if (gitdir / marker).exists():
                raise SyncBlocked(
                    f"Operation Git inachevee ({marker}); intervention manuelle."
                )
        if self.command("ls-files", "-u", "-z").stdout:
            raise SyncBlocked("Conflits Git deja en cours dans l'index.")
        self.report["head_before"] = self.text("rev-parse", "HEAD")
        self.report["remote"] = remote
        self.report["remote_url_observed"] = _redact_sensitive_text(remote)
        self.report["push_url_observed"] = _redact_sensitive_text(push_remote)
        self.report["remote_capability"] = "REMOTE_CONFIGURED"
        self.say(
            f"[PREFLIGHT OK] branche={branch} | HEAD="
            f"{str(self.report['head_before'])[:12]} | remote canonique confirme."
        )
        return gitdir

    def _promote_current_branch_to_main(self, source_branch: str) -> None:
        """Fast-forward local main from a clean, linear current branch."""
        if source_branch == "main":
            self.report["branch_after"] = "main"
            return
        source_sha = self.text("rev-parse", "HEAD")
        main_sha = self.command(
            "rev-parse", "--verify", "refs/heads/main", check=False,
        )
        if main_sha.returncode:
            raise SyncBlocked("Branche locale main introuvable; promotion refusee.")
        main_sha_text = main_sha.stdout.decode("ascii", errors="replace").strip()
        ancestor = self.command(
            "merge-base", "--is-ancestor", main_sha_text, source_sha,
            check=False, expected_returncodes=(1,),
        )
        if ancestor.returncode != 0:
            raise SyncBlocked(
                f"Promotion refusee: main ({main_sha_text[:12]}) n'est pas "
                f"un ancetre de {source_branch} ({source_sha[:12]}). "
                "Aucune fusion automatique ni force-push."
            )
        dirty = self.command(
            "status", "--porcelain=v1", "-z", "--no-renames",
            "--untracked-files=no",
            "--", *self._pathspecs(include_protected=True),
        ).stdout
        if dirty:
            raise SyncBlocked(
                "Promotion refusee: des modifications suivies restent presentes "
                "apres le checkpoint; donnees conservees, aucune bascule."
            )
        self.say(
            f"[PROMOTION] Fast-forward local de main depuis {source_branch} "
            f"({source_sha[:12]}); aucun reset, clean ou merge de conflit."
        )
        switched = False
        try:
            self.command("switch", "main")
            switched = True
            self.command("merge", "--ff-only", source_branch)
        except Exception:
            if switched:
                self.command("switch", source_branch, check=False)
            raise
        promoted_sha = self.text("rev-parse", "HEAD")
        if promoted_sha != source_sha:
            raise SyncBlocked(
                "Promotion refusee: le SHA de main ne correspond pas au SHA "
                "source apres fast-forward."
            )
        self.report["branch_after"] = "main"
        self.report["promoted_current_branch"] = True
        self.report["promoted_from_branch"] = source_branch
        self.report["promotion_sha"] = promoted_sha
        self.say(
            f"[PROMOTION OK] main local={promoted_sha[:12]} | "
            "branche active finale=main."
        )

    def _ensure_full_history(self) -> None:
        """Deepen only until local and remote history have a common ancestor.

        This is intentionally bounded.  A complete unshallow fetch is both
        unnecessary for normal main reconciliation and catastrophically slow
        for this repository's large historical object graph.  If the common
        ancestor is still unavailable after the bounded steps, fail closed
        instead of silently turning a code push into a repository download.
        """
        if self.text("rev-parse", "--is-shallow-repository") != "true":
            self.report["history_mode"] = "FULL"
            return
        local_head = self.text("rev-parse", "HEAD")
        existing_remote = self.command(
            "rev-parse", "refs/remotes/origin/main", check=False,
        )
        if existing_remote.returncode == 0:
            remote_head = existing_remote.stdout.decode(
                "ascii", errors="replace"
            ).strip()
            if remote_head and self.command(
                "merge-base", local_head, remote_head, check=False,
                expected_returncodes=(1,),
            ).returncode == 0:
                self.report["history_mode"] = "EXISTING_SHALLOW_BASE"
                self.say(
                    "[HISTORIQUE] Base commune deja prouvee dans le clone "
                    "shallow; aucun fetch supplementaire."
                )
                return
        steps = self.report["history_deepen_steps"]
        if not isinstance(steps, list):
            steps = []
            self.report["history_deepen_steps"] = steps

        for deepen in HISTORY_DEEPEN_STEPS:
            self.say(
                f"[HISTORIQUE] Approfondissement borne +{deepen} commits; "
                "arret des que la base commune est prouvee..."
            )
            fetch_args = [
                "fetch", "--progress", "--no-tags", HISTORY_FETCH_FILTER,
                f"--deepen={deepen}", "origin",
                "refs/heads/main:refs/remotes/origin/main",
            ]
            filtered = self.command(
                *fetch_args, check=False, timeout=HISTORY_FETCH_TIMEOUT_SECONDS,
            )
            if filtered.returncode:
                detail = (filtered.stderr or b"").decode(
                    "utf-8", errors="replace"
                ).lower()
                if "filter" not in detail and "partial" not in detail:
                    raise SyncBlocked(
                        "Extension Git bornee echouee; aucun fallback non filtre: "
                        + detail[:900]
                    )
                self.say(
                    "[HISTORIQUE] Serveur sans filtre blob:none; fallback borne "
                    "sans blobs exclus impossible, reprise controlee."
                )
                self.command(
                    *[arg for arg in fetch_args if arg != HISTORY_FETCH_FILTER],
                    timeout=HISTORY_FETCH_TIMEOUT_SECONDS,
                )
            steps.append(deepen)
            remote_head = self.text("rev-parse", "refs/remotes/origin/main")
            common = self.command(
                "merge-base", local_head, remote_head, check=False,
                expected_returncodes=(1,),
            )
            if common.returncode == 0:
                self.report["history_expanded"] = True
                self.report["history_mode"] = "BOUNDED_DEEPEN"
                return
            if self.text("rev-parse", "--is-shallow-repository") != "true":
                raise SyncBlocked(
                    "Historique Git complet mais sans base commune avec origin/main; "
                    "fusion refusee."
                )

        raise SyncBlocked(
            "Historique Git shallow sans base commune apres approfondissement "
            "borne; aucun telechargement complet ni push."
        )

    def _predict_merge_conflicts(self, remote: str, local: str) -> list[str]:
        """Detect conflicts without touching the index or worktree.

        A real rebase can replay many local commits before it reaches the
        first unsupported conflict.  `merge-tree` computes the same three-way
        merge decision against the two tips without mutating Git state, so an
        unsupported conflict can fail closed in milliseconds instead of
        spending minutes replaying commits that will be discarded.
        """
        outcome = self.command(
            "merge-tree", "--write-tree", remote, local,
            check=False, timeout=MERGE_TREE_TIMEOUT_SECONDS,
        )
        payload = b"\n".join(
            part for part in (outcome.stdout or b"", outcome.stderr or b"")
            if part
        ).decode("utf-8", errors="replace")
        if outcome.returncode == 0:
            self.report["predicted_conflicts"] = []
            return []
        conflicts = sorted({
            match.group(1).strip()
            for match in re.finditer(
                r"^CONFLICT .*?: Merge conflict in (.+)$",
                payload,
                flags=re.MULTILINE,
            )
            if match.group(1).strip()
        })
        if not conflicts:
            raise SyncBlocked(
                "Precontrole merge-tree impossible; rebase non lance. "
                + payload[:900].strip()
            )
        self.report["predicted_conflicts"] = conflicts
        return conflicts

    @staticmethod
    def _preflight_auto_resolvable_conflict(path: str) -> bool:
        """Return whether the existing post-rebase resolver may inspect it."""
        if path in AUTO_RESOLVABLE_CI_CONFLICTS | AUTO_RESOLVABLE_GOVERNANCE_CONFLICTS:
            return True
        return (
            path.startswith(("src/", "tools/", "tests/"))
            and path.endswith(".py")
        )

    def _inventory(
        self, *, refresh: bool = False,
    ) -> tuple[list[str], list[str], list[str]]:
        if self._inventory_cache is not None and not refresh:
            self.say("[INVENTAIRE] reutilisation du cache Git local stable.")
            return self._inventory_cache
        self.say(
            "[MOTEUR 2/5] Inventaire des changements de code; les dossiers "
            "de donnees restent exclus."
        )
        # This repository tracks millions of protected dataset paths. A full
        # worktree status exceeds the local read budget even with
        # --untracked-files=no, so inspect every root except the one massive
        # protected tree. Protected paths that are scanned are still rejected
        # as checkpoint candidates; an incoming remote change to the massive
        # tree is checked individually before any merge.
        # The publishable inventory must cover every code root, but it must
        # not stat SAFE/runtime trees on every launcher invocation.  SAFE
        # worktree edits are never eligible for a code commit; staged SAFE
        # paths are read separately from the index so they can still be
        # reported and preserved without a full worktree scan.
        staged, tracked = _status_entries(
            self.command(
                "status", "--porcelain=v1", "-z", "--no-renames",
                "--untracked-files=no",
                "--", *self._pathspecs(include_protected=False),
            ).stdout
        )
        staged_protected = _paths(
            self.command(
                "diff", "--cached", "--name-only", "-z",
                "--no-renames", "--",
                *self._pathspecs(include_protected=True),
            ).stdout
        )
        staged.extend(staged_protected)
        # Worktree diff on protected paths (without --cached) requires Git to
        # lstat every matched path.  On a shallow clone whose index exceeds one
        # million entries this takes 10+ minutes and times out the launcher.
        # Protected paths are never eligible for a code commit — the --cached
        # diff above already catches anything staged — so the worktree scan is
        # skipped entirely.  If a protected file is modified on disk it will
        # still appear when the operator runs a manual ``git status``.
        tracked_protected: list[str] = []
        tracked.extend(tracked_protected)
        # Git prunes excluded directories; never descend into SAFE shards.
        args = ["ls-files", "--others", "--exclude-standard", "-z"]
        for pattern in self._excluded_untracked_patterns():
            args.extend(["-x", pattern])
        untracked = _paths(self.command(*args).stdout)
        self.say(
            f"[INVENTAIRE] deja stages={len(staged)} | suivis modifies="
            f"{len(tracked)} | nouveaux={len(untracked)}."
        )
        self._inventory_cache = (staged, tracked, untracked)
        return self._inventory_cache

    @contextlib.contextmanager
    def _timed_phase(self, name: str, budget_seconds: float):
        started = time.monotonic()
        try:
            yield
        finally:
            phases = self.report.setdefault("phases", {})
            if isinstance(phases, dict):
                duration = time.monotonic() - started
                phases[name] = {
                    "duration_ms": int(duration * 1000),
                    "budget_seconds": budget_seconds,
                    "budget_exceeded": duration > budget_seconds,
                }

    def _pathspecs(self, *, include_protected: bool) -> tuple[str, ...]:
        """Return bounded top-level worktree pathspecs.

        The repository's root ``datasets`` tree contains millions of tracked
        files. Passing ``.`` to ``git status`` makes Git stat that entire tree
        even when untracked files are disabled. A root-file glob preserves
        deleted tracked files, while explicit directory roots preserve the
        existing data-integrity checks without traversing ``datasets``.
        """
        cached = self._pathspec_cache.get(include_protected)
        if cached is not None:
            return cached
        # Do not add a root-wide glob here.  Git expands that glob into every
        # tracked path, including the multi-million-file ``datasets`` tree,
        # before it applies the explicit directory exclusions below.  Listing
        # root files and bounded top-level directories directly preserves the
        # complete code inventory without accidentally reintroducing the
        # expensive SAFE/data scan.
        paths: list[str] = []
        for child in self.root.iterdir():
            if child.name in UNSCANNABLE_PROTECTED_ROOTS:
                continue
            if not include_protected and child.name in PROTECTED_DIRS:
                continue
            paths.append(
                f"{child.name}/**"
                if child.is_dir() and not child.is_symlink()
                else child.name
            )
        result = tuple(sorted(paths))
        self._pathspec_cache[include_protected] = result
        return result

    @staticmethod
    def _excluded_untracked_patterns() -> list[str]:
        patterns = [
            pattern
            for directory in sorted(PROTECTED_DIRS)
            for pattern in (f"/{directory}/", f"/{directory}/**")
        ]
        patterns.extend(["/tools/git/", "/tools/python/"])
        return patterns

    def _fetch_remote_snapshot(self, observed_remote: str) -> str:
        """Use a current tracking ref when it already proves the remote SHA.

        A large partial clone may spend several minutes indexing a tiny fetch.
        The fresh ``ls-remote`` SHA is the authority; when the local tracking
        ref already has that exact SHA, fetching again only repeats expensive
        object/index work without changing the snapshot.
        """
        existing_remote = self.command(
            "rev-parse", "refs/remotes/origin/main", check=False,
        )
        existing_sha = existing_remote.stdout.decode(
            "ascii", errors="replace"
        ).strip() if existing_remote.returncode == 0 else ""
        if existing_sha and existing_sha == observed_remote:
            # The remote snapshot still took time (ls-remote plus index/ref
            # inspection); a user/editor may have changed code meanwhile.
            self._inventory_cache = None
            self._remote_snapshot_ready = True
            self._remote_snapshot_sha = existing_sha
            self.report["remote_snapshot_reused"] = True
            self.say(
                "[FETCH] SHA GitHub deja present dans origin/main; "
                "aucun fetch supplementaire."
            )
            return existing_sha

        self.command(
            "fetch", "--progress", "--no-tags", "origin",
            "refs/heads/main:refs/remotes/origin/main",
        )
        self._inventory_cache = None
        fetched_remote = self.text("rev-parse", "refs/remotes/origin/main")
        self._remote_snapshot_ready = True
        self._remote_snapshot_sha = fetched_remote
        self.report["remote_snapshot_reused"] = False
        return fetched_remote

    def capture_preflight(
        self, *, fetch_remote: bool, allow_protected_local: bool | None = None,
    ) -> None:
        """Persist exact local inventory before checkpointing or reconciling."""
        staged, tracked, untracked = self._inventory()
        local_head = str(self.report.get("head_before") or self.text("rev-parse", "HEAD"))
        inventory = {
            "staged": {"count": len(staged), "paths": sorted(set(staged))},
            "tracked_changes": {
                "count": len(tracked), "paths": sorted(set(tracked)),
            },
            "untracked": {"count": len(untracked), "paths": sorted(set(untracked))},
            "protected_observed_paths": sorted({
                path for path in staged + tracked + untracked if _protected(path)
            }),
            "excluded_untracked_patterns": self._excluded_untracked_patterns(),
        }
        snapshot: dict[str, object] = {
            "captured_at_utc": datetime.now(UTC).isoformat(),
            "local_head": local_head,
            "remote_head_observed": None,
            "remote_head_fetched": None,
            "ahead_commits": None,
            "behind_commits": None,
            "comparison_status": "NOT_REQUESTED",
            "inventory": inventory,
            "publishable_paths": [],
        }
        self.report["preflight"] = snapshot

        if fetch_remote:
            observed_remote = self.remote_sha()
            snapshot["remote_head_observed"] = observed_remote

        eligible = self._check_candidates(
            staged,
            tracked,
            untracked,
            allow_protected_local=(
                fetch_remote
                if allow_protected_local is None
                else allow_protected_local
            ),
        )
        snapshot["publishable_paths"] = eligible
        snapshot["inventory_status"] = "VALIDATED"

        if not fetch_remote:
            snapshot["comparison_status"] = (
                "NOT_FETCHED_DRY_RUN" if self.dry_run else "NOT_REQUESTED_LOCAL_ONLY"
            )
            self.say(
                "[PREFLIGHT RECEIPT] Inventaire local conserve; aucune mutation "
                "ni comparaison de commits distante dans ce mode."
            )
            return

        if self._remote_snapshot_ready:
            fetched_remote = self._remote_snapshot_sha or self.text(
                "rev-parse", "refs/remotes/origin/main"
            )
            self.say(
                "[FETCH] Snapshot distant deja valide reutilise; "
                "aucun second fetch identique."
            )
        else:
            # A user/editor can change source files while fetch is in flight.
            # Never reuse the pre-fetch snapshot for the publishable checkpoint.
            fetched_remote = self._fetch_remote_snapshot(observed_remote)
        counts = self.text(
            "rev-list", "--left-right", "--count",
            f"{local_head}...{fetched_remote}",
        ).split()
        if len(counts) != 2 or any(not value.isdecimal() for value in counts):
            raise SyncBlocked("Comptage ahead/behind invalide; aucun changement publié.")
        ahead, behind = (int(value) for value in counts)
        snapshot.update({
            "remote_head_fetched": fetched_remote,
            "ahead_commits": ahead,
            "behind_commits": behind,
            "comparison_status": "EXACT_FOR_FETCHED_REMOTE_HEAD",
        })
        self.report["remote_sha_observed"] = fetched_remote
        self.say(
            f"[PREFLIGHT RECEIPT] local={local_head[:12]} | "
            f"GitHub snapshot={fetched_remote[:12]} | ahead={ahead} | "
            f"behind={behind} | staged={len(staged)} | suivis={len(tracked)} | "
            f"nouveaux={len(untracked)} | chemins proteges={len(inventory['protected_observed_paths'])}."
        )

    def _fast_path_if_clean(self) -> bool:
        """Finish a provably clean run without fetching Git history.

        A clean repository whose local HEAD already equals the current
        ``ls-remote`` SHA has nothing to reconcile.  The old path still ran a
        shallow-history check and a full fetch before discovering that fact,
        which made a harmless double-click spend tens of seconds in GitHub
        traffic.  This shortcut is deliberately narrow: it first inventories
        every publishable path, checks the protected-data contract, verifies
        the remote twice around the local-change check, and returns only when
        both the code and the remote are still unchanged.

        When GitHub is ahead but local ``main`` is clean, the same proof can
        safely finish with one fetch and a fast-forward.  Keeping that lane
        here avoids the later checkpoint/syntax/reconcile loop while retaining
        the ignored-data guard and the final remote SHA verification.
        """
        staged, tracked, untracked = self._inventory()
        eligible = self._check_candidates(
            # Protected local bytes are deliberately excluded from
            # ``eligible``.  They may coexist with a code-only fast-forward;
            # _protect_ignored_files below still refuses any remote change
            # that could overwrite one of them.
            staged, tracked, untracked, allow_protected_local=True,
        )
        if eligible:
            return False

        local = str(self.report.get("head_before") or self.text("rev-parse", "HEAD"))
        observed_remote = self.remote_sha()
        protected_local = sorted({
            path for path in staged + tracked + untracked if _protected(path)
        })
        if observed_remote == local and protected_local:
            self.report["protected_local_changes"] = protected_local
            raise SyncBlocked(
                "Donnees locales protegees modifiees alors que GitHub est deja "
                "aligne; aucun raccourci silencieux. Relancer apres traitement "
                "manuel des donnees SAFE."
            )
        if observed_remote != local:
            fetched_remote = self._fetch_remote_snapshot(observed_remote)
            if fetched_remote == local:
                self._assert_no_new_code_changes()
                verified_remote = self.remote_sha()
                if verified_remote != local:
                    return False
                self.report["preflight"] = {
                    "captured_at_utc": datetime.now(UTC).isoformat(),
                    "local_head": local,
                    "remote_head_observed": observed_remote,
                    "remote_head_fetched": fetched_remote,
                    "ahead_commits": 0,
                    "behind_commits": 0,
                    "comparison_status": "EXACT_FOR_FETCHED_REMOTE_HEAD",
                    "inventory": {
                        "staged": {"count": len(staged), "paths": sorted(set(staged))},
                        "tracked_changes": {
                            "count": len(tracked), "paths": sorted(set(tracked)),
                        },
                        "untracked": {
                            "count": len(untracked), "paths": sorted(set(untracked)),
                        },
                        "protected_observed_paths": sorted({
                            path for path in staged + tracked + untracked
                            if _protected(path)
                        }),
                        "excluded_untracked_patterns": self._excluded_untracked_patterns(),
                    },
                    "publishable_paths": [],
                    "inventory_status": "VALIDATED",
                }
                self.report["remote_sha_observed"] = verified_remote
                self.report["fast_path"] = "CLEAN_REMOTE_MATCH_AFTER_FETCH"
                self.report["local_syntax_check"] = "NO_PYTHON_CHANGED"
                self.report["status"] = "SYNCHRONIZED"
                self.report["head_after"] = local
                self.report["checkpoint_sha_after_reconcile"] = local
                self.say(
                    "[RACCOURCI] Fetch distant confirme le meme SHA; "
                    "aucun checkpoint, rebase ni push necessaire."
                )
                return True
            if fetched_remote == local or self.command(
                "merge-base", "--is-ancestor", local, fetched_remote,
                check=False, expected_returncodes=(1,),
            ).returncode:
                return False

            self._protect_ignored_files(fetched_remote)
            self._assert_no_new_code_changes()
            with self._preserve_local_protected_index():
                self.command("merge", "--ff-only", fetched_remote)
            merged_local = self.text("rev-parse", "HEAD")
            verified_remote = self.remote_sha()
            if merged_local != fetched_remote or verified_remote != merged_local:
                return False

            counts = self.text(
                "rev-list", "--left-right", "--count",
                f"{local}...{verified_remote}",
            ).split()
            if len(counts) != 2 or any(not value.isdecimal() for value in counts):
                return False
            ahead, behind = (int(value) for value in counts)
            staged, tracked, untracked = self._inventory()
            self.report["preflight"] = {
                "captured_at_utc": datetime.now(UTC).isoformat(),
                "local_head": local,
                "remote_head_observed": observed_remote,
                "remote_head_fetched": fetched_remote,
                "ahead_commits": ahead,
                "behind_commits": behind,
                "comparison_status": "EXACT_FOR_FETCHED_REMOTE_HEAD",
                "inventory": {
                    "staged": {"count": len(staged), "paths": sorted(set(staged))},
                    "tracked_changes": {
                        "count": len(tracked), "paths": sorted(set(tracked)),
                    },
                    "untracked": {
                        "count": len(untracked), "paths": sorted(set(untracked)),
                    },
                    "protected_observed_paths": sorted({
                        path for path in staged + tracked + untracked if _protected(path)
                    }),
                    "excluded_untracked_patterns": self._excluded_untracked_patterns(),
                },
                "publishable_paths": [],
                "inventory_status": "VALIDATED",
            }
            self.report["remote_sha_observed"] = verified_remote
            self.report["fast_path"] = "CLEAN_REMOTE_FAST_FORWARD"
            self.report["local_syntax_check"] = "NO_PYTHON_CHANGED"
            self.report["status"] = "SYNCHRONIZED"
            self.report["head_after"] = merged_local
            self.report["checkpoint_sha_after_reconcile"] = merged_local
            self.say(
                "[RACCOURCI] Depot propre; avance rapide GitHub integree et "
                "SHA distant reverifiee, sans rebase ni push."
            )
            return True

        # The exact-match path below deliberately rechecks the remote around
        # the local-change assertion, because GitHub may advance during this
        # short read-only window.

        inventory = {
            "staged": {"count": len(staged), "paths": sorted(set(staged))},
            "tracked_changes": {
                "count": len(tracked), "paths": sorted(set(tracked)),
            },
            "untracked": {
                "count": len(untracked), "paths": sorted(set(untracked)),
            },
            "protected_observed_paths": sorted({
                path for path in staged + tracked + untracked if _protected(path)
            }),
            "excluded_untracked_patterns": self._excluded_untracked_patterns(),
        }
        self.report["preflight"] = {
            "captured_at_utc": datetime.now(UTC).isoformat(),
            "local_head": local,
            "remote_head_observed": observed_remote,
            "remote_head_fetched": None,
            "ahead_commits": 0,
            "behind_commits": 0,
            "comparison_status": "EXACT_REMOTE_SHA_EQUALS_LOCAL",
            "inventory": inventory,
            "publishable_paths": [],
            "inventory_status": "VALIDATED",
        }
        self._assert_no_new_code_changes()
        verified_remote = self.remote_sha()
        if verified_remote != local:
            return False

        self.report["remote_sha_observed"] = verified_remote
        self.report["fast_path"] = "CLEAN_REMOTE_MATCH"
        self.report["local_syntax_check"] = "NO_PYTHON_CHANGED"
        self.report["status"] = "SYNCHRONIZED"
        self.report["head_after"] = local
        self.report["checkpoint_sha_after_reconcile"] = local
        self.say(
            "[RACCOURCI] Depot propre et SHA GitHub identique; "
            "aucun fetch, commit, rebase ou push necessaire."
        )
        return True

    def _historical_head_blob(self, source: str) -> bytes:
        result = self.command("show", f"HEAD:{source}", check=False)
        if result.returncode:
            raise SyncBlocked(
                f"Blob historique absent de HEAD; deplacement refuse: {source}"
            )
        return result.stdout

    def _clean_blob_oid(self, path: str, payload: bytes) -> str:
        result = self.command(
            "hash-object", f"--path={path}", "--stdin", input_bytes=payload,
        )
        return result.stdout.decode("ascii", errors="strict").strip()

    def _verify_historical_archive_payload(
        self, source: str, destination: str, archive_path: Path,
    ) -> tuple[bytes, bytes]:
        head_blob = self._historical_head_blob(source)
        expected_oid = self.text("rev-parse", f"HEAD:{source}")
        payload = archive_path.read_bytes()
        source_oid = self._clean_blob_oid(source, payload)
        destination_oid = self._clean_blob_oid(destination, payload)
        if source_oid != expected_oid or destination_oid != expected_oid:
            raise SyncBlocked(
                f"Archive differente du blob HEAD apres normalisation Git: {destination}"
            )
        return head_blob, payload

    def _historical_archive_file(self, destination: str) -> Path:
        relative = PurePosixPath(destination)
        if relative.is_absolute() or ".." in relative.parts:
            raise SyncBlocked("Destination d'archive hors depot; deplacement refuse.")
        current = self.root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise SyncBlocked(
                    f"Lien symbolique dans le chemin d'archive: {destination}"
                )
        if not current.is_file():
            raise SyncBlocked(
                f"Copie d'archive absente ou non reguliere: {destination}"
            )
        return current

    def _record_historical_relocation(
        self, source: str, destination: str, head_blob: bytes,
        worktree_payload: bytes, proof: str,
    ) -> None:
        entry = {
            "source": source,
            "destination": destination,
            "sha256": hashlib.sha256(head_blob).hexdigest(),
            "worktree_sha256": hashlib.sha256(worktree_payload).hexdigest(),
            "proof": proof,
        }
        records = self.report["verified_historical_relocations"]
        if isinstance(records, list):
            for item in records:
                if (
                    isinstance(item, dict)
                    and item.get("source") == source
                    and item.get("destination") == destination
                ):
                    item.update(entry)
                    break
            else:
                records.append(entry)
        self.say(
            f"[ARCHIVE MOVE {proof}] {source} -> {destination} "
            f"| SHA-256={entry['sha256']}"
        )

    def _verified_unstaged_historical_moves(
        self, tracked: list[str], untracked: list[str]
    ) -> set[str]:
        allowed: set[str] = set()
        for source, destination in SAFE_HISTORICAL_RELOCATIONS.items():
            if source not in tracked or destination not in untracked:
                continue
            old_path = self.root / source
            if old_path.exists() or old_path.is_symlink():
                raise SyncBlocked(
                    f"Le fichier source existe encore; deplacement archive non prouve: {source}"
                )
            archive_path = self._historical_archive_file(destination)
            head_blob, payload = self._verify_historical_archive_payload(
                source, destination, archive_path
            )
            self._check_file_payload(destination, archive_path)
            self._record_historical_relocation(
                source, destination, head_blob, payload, "WORKTREE_BLOB_EXACT"
            )
            allowed.update((source, destination))
        return allowed

    def _verified_staged_historical_moves(self, staged: list[str]) -> set[str]:
        allowed: set[str] = set()
        staged_paths = set(staged)
        for source, destination in SAFE_HISTORICAL_RELOCATIONS.items():
            pair = {source, destination}
            if not pair.intersection(staged_paths) or not pair.issubset(staged_paths):
                continue
            old_path = self.root / source
            if old_path.exists() or old_path.is_symlink():
                raise SyncBlocked(
                    f"Le fichier source existe encore dans le depot: {source}"
                )
            archive_path = self._historical_archive_file(destination)
            head_blob, payload = self._verify_historical_archive_payload(
                source, destination, archive_path
            )
            staged_blob = self.command("show", f":{destination}", check=False)
            source_index = self.command("ls-files", "--stage", "--", source)
            if (
                staged_blob.returncode
                or staged_blob.stdout != head_blob
                or source_index.stdout
            ):
                raise SyncBlocked(
                    "Le deplacement archive ne correspond plus exactement au blob "
                    "HEAD dans l'index et le disque; synchronisation arretee."
                )
            self._check_file_payload(destination, archive_path)
            self._record_historical_relocation(
                source, destination, head_blob, payload,
                "INDEX_AND_WORKTREE_BLOB_EXACT",
            )
            allowed.update(pair)
        return allowed

    def _check_candidates(
        self, staged: list[str], tracked: list[str], untracked: list[str],
        *, allow_protected_local: bool = False,
    ) -> list[str]:
        staged_protected = [p for p in staged if _protected(p)]
        safe_moves = self._verified_unstaged_historical_moves(tracked, untracked)
        deferable_staged = {
            path for path in staged_protected
            if path not in safe_moves and _can_defer_staged_protected(path)
        }
        blocking_staged = [
            path for path in staged_protected
            if path not in deferable_staged and path not in safe_moves
        ]
        if blocking_staged:
            raise SyncBlocked(
                "Fichiers sensibles deja stages : " + ", ".join(blocking_staged[:8])
            )
        if deferable_staged:
            self._deferred_staged_protected_paths.update(deferable_staged)
            deferred_list = sorted(self._deferred_staged_protected_paths)
            self.report["deferred_staged_protected_paths"] = deferred_list[:100]
            self.report["deferred_staged_protected_count"] = len(deferred_list)
            self.say(
                "[GARDE DONNEES] "
                f"{len(deferable_staged)} fichier(s) SAFE deja stages "
                "seront exclus du commit de code et preserves dans l'index operateur."
            )
        tracked_protected = [
            p for p in tracked if _protected(p) and p not in safe_moves
        ]
        deferable_tracked = {
            path for path in tracked_protected
            if _can_defer_staged_protected(path)
        }
        blocking_tracked = [
            path for path in tracked_protected if path not in deferable_tracked
        ]
        if blocking_tracked and not allow_protected_local:
            raise SyncBlocked(
                "Donnees Git suivies mais modifiees localement : "
                + ", ".join(blocking_tracked[:8])
                + ". Les proteger avant toute fusion."
            )
        if tracked_protected:
            self.report["protected_local_changes"] = sorted(tracked_protected)
            self.say(
                "[GARDE DONNEES] Modifications locales protegees conservees hors "
                "du commit; elles seront refusees si GitHub touche ces chemins."
            )
        eligible = sorted(
            p for p in set(staged + tracked + untracked)
            if not _protected(p) or p in safe_moves
        )
        for path in eligible:
            absolute = self.root / path
            if absolute.is_symlink():
                raise SyncBlocked(f"Lien symbolique non publiable automatiquement: {path}")
            if absolute.is_file() and absolute.stat().st_size > MAX_BLOB_BYTES:
                raise SyncBlocked(f"Fichier >95 Mio interdit dans Git: {path}")
        self.say(
            f"[FILTRE] {len(eligible)} chemin(s) admissible(s); "
            "donnees, binaires et secrets exclus."
        )
        for path in eligible[:30]:
            label = "ARCHIVE SAFE" if path in safe_moves else "CODE"
            self.say(f"  [{label}] {path}")
        if len(eligible) > 30:
            self.say(f"  [CODE] ... {len(eligible) - 30} autre(s) fichier(s).")
        return eligible

    @staticmethod
    def _check_file_payload(path: str, full: Path) -> None:
        if not full.is_file():
            return
        if full.stat().st_size > MAX_BLOB_BYTES:
            raise SyncBlocked(f"Fichier trop volumineux: {path}")
        if full.stat().st_size <= 2 * 1024 * 1024:
            sample = full.read_bytes()
            if any(line in {
                b"-----BEGIN PRIVATE KEY-----",
                b"-----BEGIN RSA PRIVATE KEY-----",
                b"-----BEGIN OPENSSH PRIVATE KEY-----",
                b"-----BEGIN EC PRIVATE KEY-----",
            } for line in sample.splitlines()):
                raise SyncBlocked(f"Materiel de cle privee detecte: {path}")

    def _verify_stage(self) -> None:
        staged = _paths(
            self.command(
                "diff", "--cached", "--name-only", "--no-renames", "-z"
            ).stdout
        )
        safe_moves = self._verified_staged_historical_moves(staged)
        deferred = self._deferred_staged_protected_paths
        unexpected_protected = [
            path for path in staged
            if _protected(path) and path not in safe_moves and path not in deferred
        ]
        if unexpected_protected:
            raise SyncBlocked(
                "L'index contient une archive, des donnees ou un secret: "
                + ", ".join(unexpected_protected[:8])
            )
        for path in staged:
            self._check_file_payload(path, self.root / path)
        if self.command("diff", "--cached", "--check", check=False).returncode:
            self.say("[ATTENTION] Espaces non conformes dans un WIP, code preserve.")

    @contextlib.contextmanager
    def _temporary_checkpoint_index(self, protected_paths: set[str]):
        """Stage code in an isolated index while preserving operator staging.

        A collector can legitimately stage SAFE catalog receipts while this
        launcher is publishing code. Copying the operator index and removing
        protected deltas only in the copy means the real index is never
        unstaged, reset, or rewritten as a side effect of publishing.
        """
        git_dir = Path(self.text("rev-parse", "--absolute-git-dir"))
        source_index = git_dir / "index"
        lock_path = git_dir / "index.lock"
        fd, raw_path = tempfile.mkstemp(
            prefix=".alina-checkpoint-", suffix=".index", dir=git_dir,
        )
        os.close(fd)
        index = Path(raw_path)
        index.unlink(missing_ok=True)
        previous = os.environ.get("GIT_INDEX_FILE")
        copied = False
        try:
            # Never copy an index while another Git process is replacing it.
            # A HEAD-only temporary index is still sufficient: the checkpoint
            # stages admissible worktree paths below and excludes SAFE data.
            if source_index.is_file() and not lock_path.exists():
                shutil.copyfile(source_index, index)
                copied = True
            os.environ["GIT_INDEX_FILE"] = str(index)
            if not copied:
                self.command("read-tree", "HEAD")
            self._restore_protected_paths_from_head(protected_paths)
            yield index
        finally:
            if previous is None:
                os.environ.pop("GIT_INDEX_FILE", None)
            else:
                os.environ["GIT_INDEX_FILE"] = previous
            index.unlink(missing_ok=True)

    def _restore_protected_paths_from_head(self, paths: set[str]) -> None:
        """Remove protected staged deltas from the currently selected index."""
        if not paths:
            return
        head_entries: dict[str, bytes] = {}
        ordered = sorted(paths)
        for start in range(0, len(ordered), PROTECTED_PATH_BATCH_SIZE):
            batch = ordered[start:start + PROTECTED_PATH_BATCH_SIZE]
            output = self.command(
                "ls-tree", "-r", "-z", "HEAD", "--", *batch,
            ).stdout
            for raw in output.split(b"\0"):
                if not raw:
                    continue
                metadata, separator, raw_path = raw.partition(b"\t")
                fields = metadata.split()
                if not separator or len(fields) != 3 or fields[1] != b"blob":
                    raise SyncBlocked("Arbre HEAD protege illisible.")
                path = raw_path.decode("utf-8", errors="strict")
                head_entries[path] = (
                    fields[0] + b" " + fields[2] + b" 0\t" + raw_path
                )
        updates = [head_entries[path] for path in ordered if path in head_entries]
        removals = [path for path in ordered if path not in head_entries]
        if updates:
            self.command(
                "update-index", "-z", "--index-info",
                input_bytes=b"\0".join(updates) + b"\0",
            )
        if removals:
            self.command(
                "update-index", "--force-remove", "-z", "--stdin",
                input_bytes=b"\0".join(
                    path.encode("utf-8") for path in removals
                ) + b"\0",
            )

    def _align_operator_index(self, paths: list[str], index_info: bytes) -> None:
        """Align only published paths; never disturb protected operator stages."""
        if not paths:
            return
        entries: set[str] = set()
        if index_info:
            for raw in index_info.split(b"\0"):
                if not raw:
                    continue
                _metadata, separator, raw_path = raw.partition(b"\t")
                if not separator:
                    raise SyncBlocked("Index du checkpoint publie illisible.")
                entries.add(raw_path.decode("utf-8", errors="strict"))
            self.command(
                "update-index", "-z", "--index-info", input_bytes=index_info,
            )
        removals = [path for path in paths if path not in entries]
        if removals:
            self.command(
                "update-index", "--force-remove", "-z", "--stdin",
                input_bytes=b"\0".join(
                    path.encode("utf-8") for path in removals
                ) + b"\0",
            )

    def _commit_staged_index(self, commit_message: str) -> str:
        """Create one local checkpoint without Git's full-index commit refresh.

        ``git commit`` refreshes a large index and can then run post-commit
        hooks.  This repository carries a hundreds-of-megabytes data index,
        while this synchronizer has already validated the exact staged paths.
        The plumbing sequence below turns that verified index into a tree,
        creates one commit, and atomically advances only the current branch.
        No reset, force update, or worktree rewrite is involved.
        """
        branch_ref = self.text("symbolic-ref", "-q", "HEAD")
        if not re.fullmatch(r"refs/heads/[A-Za-z0-9._/-]+", branch_ref):
            raise SyncBlocked(
                "Reference de branche absente ou invalide; checkpoint refuse."
            )
        parent = self.text("rev-parse", "HEAD")
        if not re.fullmatch(r"[0-9a-f]{40,64}", parent):
            raise SyncBlocked("HEAD local invalide; checkpoint refuse.")

        tree = self.command(
            "write-tree", timeout=COMMIT_TIMEOUT_SECONDS,
        ).stdout.decode("utf-8", errors="replace").strip()
        if not re.fullmatch(r"[0-9a-f]{40,64}", tree):
            raise SyncBlocked("Arbre Git invalide; checkpoint refuse.")

        created = self.command(
            "commit-tree", tree, "-p", parent, "-m", commit_message,
            timeout=COMMIT_TIMEOUT_SECONDS,
        ).stdout.decode("utf-8", errors="replace").strip()
        if not re.fullmatch(r"[0-9a-f]{40,64}", created):
            raise SyncBlocked("Commit Git invalide; checkpoint refuse.")

        # The expected old SHA makes a concurrent local ref update fail closed.
        self.command(
            "update-ref", branch_ref, created, parent,
            timeout=COMMIT_TIMEOUT_SECONDS,
        )
        observed = self.text("rev-parse", "HEAD")
        if observed != created:
            raise SyncBlocked(
                "Le checkpoint Git n'est pas le HEAD observe; aucun push."
            )
        self.report["commit_backend"] = "COMMIT_TREE_INDEX_FAST_PATH"
        return created

    def checkpoint(self) -> None:
        # A retry checkpoint intentionally adopts any paths that were
        # deferred by a previous replay; they are now part of the new local
        # snapshot rather than silently ignored.
        self._deferred_local_paths.clear()
        staged, tracked, untracked = self._inventory()
        snapshot = self.report.get("preflight")
        allow_protected_local = (
            self._allow_protected_local_checkpoint
            or (
            isinstance(snapshot, dict)
            and snapshot.get("remote_head_fetched")
            and snapshot.get("local_head") != snapshot.get("remote_head_fetched")
            )
        )
        eligible = self._check_candidates(
            staged, tracked, untracked,
            allow_protected_local=bool(allow_protected_local),
        )
        self.report["publishable_paths_seen"] = len(eligible)
        self.changed_python_paths = [
            p for p in eligible
            if p.endswith(".py") and (self.root / p).is_file()
        ]
        self.say(
            f"[MOTEUR 3/5] Fichiers de code locaux admissibles: {len(eligible)}."
        )
        # Detect high-confidence private-key material BEFORE writing Git blobs.
        for path in eligible:
            self._check_file_payload(path, self.root / path)
        if self.dry_run and eligible:
            pathspec_bytes = (
                b"\0".join(p.encode("utf-8") for p in eligible) + b"\0"
            )
            proposed_diff = self.command(
                "diff", "HEAD", "--no-ext-diff", "--unified=0",
                "--pathspec-from-file=-", "--pathspec-file-nul",
                input_bytes=pathspec_bytes, check=False,
            )
            proposed_message = _commit_subject(
                eligible,
                proposed_diff.stdout.decode("utf-8", errors="replace"),
            )
            self.report["proposed_commit_message"] = proposed_message
            self.say(f"[DRY-RUN] Commit propose: {proposed_message}")
        if self.dry_run or not eligible:
            if self.dry_run:
                self.say("[DRY-RUN] Aucun fichier prepare ou committe.")
            else:
                self.say("[CHECKPOINT] Rien a sauvegarder; aucun commit vide.")
            return
        pathspec = b"\0".join(path.encode("utf-8") for path in eligible) + b"\0"
        published_index_info = b""
        with self._temporary_checkpoint_index(
            self._deferred_staged_protected_paths,
        ):
            # In a same-size edit made within Windows' coarse filesystem
            # timestamp window, a copied index can still carry a valid stat
            # cache and ``git add`` may incorrectly believe the worktree is
            # unchanged. Reset only publishable paths to their HEAD entries
            # in the temporary index; the following add must then read their
            # current bytes. The operator index remains untouched.
            self._restore_protected_paths_from_head(set(eligible))
            self.command(
                "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul",
                input_bytes=pathspec,
            )
            self._verify_stage()
            diff = self.command(
                "diff", "--cached", "--quiet", check=False,
                expected_returncodes=(1,),
            )
            if diff.returncode not in (0, 1):
                raise SyncBlocked("Verification de l'index Git impossible.")
            if diff.returncode == 1:
                staged_diff = self.command(
                    "diff", "--cached", "--no-ext-diff", "--unified=0",
                ).stdout.decode("utf-8", errors="replace")
                commit_message = _commit_subject(eligible, staged_diff)
                self.report["commit_message"] = commit_message
                self.say(f"Commit semantique du code admissible: {commit_message}")
                self.report["checkpoint_sha"] = self._commit_staged_index(
                    commit_message
                )
                _chunks = [
                    eligible[i:i + 200]
                    for i in range(0, len(eligible), 200)
                ]
                published_index_info = b"".join(
                    self.command(
                        "ls-files", "-s", "-z", "--", *chunk,
                    ).stdout
                    for chunk in _chunks
                )
                self.report["local_commit_created"] = True
        if self.report.get("local_commit_created"):
            self._align_operator_index(eligible, published_index_info)
            self.command(
                "update-ref", "refs/alina-sync/last-local-checkpoint",
                self.report["checkpoint_sha"],
            )

    def _syntax_gate(self) -> None:
        if not self.changed_python_paths:
            self.report["local_syntax_check"] = "NO_PYTHON_CHANGED"
            self.say("[ETAPE 4/6] Controle syntaxique ignore: aucun Python modifie.")
            return
        self.say(
            f"[MOTEUR 4/5] Verification syntaxique de "
            f"{len(self.changed_python_paths)} fichier(s) Python."
        )
        for index, path in enumerate(self.changed_python_paths, 1):
            self.say(
                f"[PYTHON {index}/{len(self.changed_python_paths)}] {path}"
            )
            try:
                ast.parse((self.root / path).read_bytes(), filename=path)
            except (SyntaxError, UnicodeError, ValueError) as exc:
                self.report["local_syntax_check"] = "FAILED_WIP_CHECKPOINT_PRESERVED"
                raise SyncBlocked(
                    f"Python incomplet ({path}): {exc}. "
                    "WIP sauvegarde en commit local, NON pousse."
                ) from exc
        self.report["local_syntax_check"] = "PASS_NOT_PROOF_OF_TESTS"
        self.say("[SYNTAXE OK] Tous les fichiers Python admissibles compilent.")

    def _assert_no_new_code_changes(self, *, allow_deferred: bool = False) -> None:
        staged, tracked, untracked = self._inventory(refresh=True)
        eligible = self._check_candidates(
            staged, tracked, untracked, allow_protected_local=True,
        )
        if allow_deferred and self._deferred_local_paths:
            eligible = [
                path for path in eligible
                if path not in self._deferred_local_paths
            ]
        if eligible:
            self.report["late_local_paths"] = eligible[:100]
            self.report["late_local_count"] = len(eligible)
            self.report["late_local_types"] = {
                "staged": [p for p in staged if p in eligible][:100],
                "tracked": [p for p in tracked if p in eligible][:100],
                "untracked": [p for p in untracked if p in eligible][:100],
            }
            raise LocalEditsDetected(
                f"{len(eligible)} modification(s) arrivee(s) pendant Git Sync : "
                + ", ".join(eligible[:12])
                + ". Contenu conserve sur disque."
            )

    def remote_sha(self) -> str:
        remote = self.text("ls-remote", "origin", "refs/heads/main")
        if not remote:
            raise SyncBlocked("GitHub main introuvable ou inaccessible.")
        matches = []
        for line in remote.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1] == "refs/heads/main":
                matches.append(fields[0])
        if len(matches) != 1:
            raise SyncBlocked(
                "Reponse ls-remote ambigue pour refs/heads/main; SHA distante "
                "non prouvee."
            )
        sha = matches[0]
        if not re.fullmatch(r"[0-9a-f]{40,64}", sha):
            raise SyncBlocked("SHA GitHub invalide.")
        return sha

    def _protect_ignored_files(self, remote: str) -> None:
        # Git merge can overwrite ignored files. Check upstream paths only,
        # without traversing runtime/shards or hydrating any LFS assets.
        changed = _paths(
            self.command("diff", "--name-only", "-z", "HEAD", remote).stdout
        )
        protected_changes = [path for path in changed if _protected(path)]
        self.say(
            f"[GARDE DONNEES] Inspection en lot de {len(protected_changes)} "
            f"chemin(s) protege(s) sur {len(changed)} chemin(s) distant(s)."
        )
        if not protected_changes:
            return

        # Resolve tracking state in small path batches instead of starting
        # multiple Git processes for every remote path.  The old O(n) loop
        # turned a 1,350-path remote diff into thousands of subprocesses.
        tracked_paths: set[str] = set()
        for start in range(0, len(protected_changes), PROTECTED_PATH_BATCH_SIZE):
            batch = protected_changes[start:start + PROTECTED_PATH_BATCH_SIZE]
            tracked_paths.update(_paths(
                self.command("ls-files", "-z", "--", *batch).stdout
            ))

        # `capture_preflight` and the immediately preceding late-edit gate
        # already inventory the operator's protected paths against the real
        # index.  Re-running `git diff HEAD -- <thousands of catalog paths>`
        # here rescans the large index and was the remaining multi-minute
        # bottleneck.  Reuse that exact validated set instead.
        observed_protected = self.report.get("protected_local_changes", [])
        local_changed = {
            path for path in observed_protected if isinstance(path, str)
        }
        for path in protected_changes:
            local_path = self.root / path
            if not (local_path.exists() or local_path.is_symlink()):
                continue
            if path in tracked_paths:
                if path in local_changed:
                    raise SyncBlocked(
                        f"GitHub toucherait un fichier protege modifie localement: {path}. "
                        "Fusion interdite pour proteger les donnees."
                    )
                continue
            if _can_defer_staged_protected(path):
                self.say(
                    f"[GARDE DONNEES] Fichier SAFE non suivi tolere: {path}"
                )
                continue
            raise SyncBlocked(
                f"GitHub toucherait un fichier local protege non suivi: {path}. "
                "Fusion interdite pour proteger les donnees."
            )

    @contextlib.contextmanager
    def _preserve_local_protected_index(self):
        """Let Git rebase code while preserving unrelated local SAFE bytes."""
        paths = [
            path for path in self.report.get("protected_local_changes", [])
            if isinstance(path, str)
        ]
        if not paths:
            yield
            return

        # Refresh the existing index entries in bounded batches, then toggle
        # skip-worktree for the complete set through NUL-delimited stdin.
        # The former implementation launched three Git processes per path
        # (ls-files, cacheinfo and skip-worktree).  With hundreds of SAFE
        # shards that made an otherwise code-only replay hold index locks for
        # minutes and prevented the operator from publishing concurrently.
        index_info: list[bytes] = []
        seen: set[str] = set()
        for start in range(0, len(paths), PROTECTED_PATH_BATCH_SIZE):
            batch = paths[start:start + PROTECTED_PATH_BATCH_SIZE]
            entry_bytes = self.command(
                "ls-files", "-s", "-z", "--", *batch,
            ).stdout
            for raw_entry in entry_bytes.split(b"\0"):
                if not raw_entry:
                    continue
                header, separator, raw_path = raw_entry.partition(b"\t")
                fields = header.split()
                if not separator or len(fields) != 3 or fields[2] != b"0":
                    raise SyncBlocked(
                        "Entree d'index protegee ambigue ou en conflit."
                    )
                path = raw_path.decode("utf-8", errors="strict")
                if path in seen:
                    raise SyncBlocked(
                        "Entree d'index protegee dupliquee: " + path
                    )
                seen.add(path)
                index_info.append(raw_entry)

        if seen != set(paths):
            missing = sorted(set(paths) - seen)
            raise SyncBlocked(
                "Entree(s) d'index protegee(s) introuvable(s): "
                + ", ".join(missing[:8])
            )

        index_payload = b"\0".join(index_info) + b"\0"
        path_payload = b"\0".join(
            path.encode("utf-8") for path in paths
        ) + b"\0"
        assumed: list[str] = []
        try:
            # A generated file can be byte-identical to HEAD while its
            # filesystem stat is stale.  Refresh only those exact index
            # entries with their existing blobs; this never stages or rewrites
            # the protected worktree files.
            self.command(
                "update-index", "-z", "--index-info",
                input_bytes=index_payload,
            )
            # `skip-worktree` is the index contract Git checkout/rebase honors
            # when the worktree intentionally contains a local protected file
            # that must not be replaced by code replay.  `assume-unchanged`
            # only suppresses stat checks and still lets checkout reject it.
            self.command(
                "update-index", "--skip-worktree", "-z", "--stdin",
                input_bytes=path_payload,
            )
            assumed = list(paths)
            yield
        finally:
            if assumed:
                restored = self.command(
                    "update-index", "--no-skip-worktree", "-z", "--stdin",
                    input_bytes=path_payload,
                    check=False,
                )
                if restored.returncode:
                    raise SyncBlocked(
                        "Restauration de la garde d'index impossible pour "
                        "les fichiers proteges."
                    )

    def _capture_conflicts(self, conflicted: list[str], local: str,
                           remote: str) -> None:
        """Save exact base/local/GitHub blobs before aborting reconciliation.

        Never write outside runtime/reports; never post payload to GitHub.
        The copies are resolved from immutable commit IDs, not index stages,
        whose local/GitHub roles change between merge and rebase conflicts.
        """
        root = self.root / "runtime"
        reports = root / "reports"
        sync_dir = reports / "git-sync"
        dest = sync_dir / "conflicts" / (local[:12] + "-" + remote[:12])
        parents = (root, reports, sync_dir, sync_dir / "conflicts", dest)
        if any(p.is_symlink() for p in parents):
            raise SyncBlocked("Chemin runtime du dossier de conflits non fiable.")
        dest.mkdir(parents=True, exist_ok=True)
        manifest: dict[str, object] = {
            "schema": "alina.git_conflict_kit.v1",
            "local_head": local,
            "remote_head": remote,
            "git_stage_roles": {
                "base": "merge-base(local_head, remote_head)",
                "local": "exact local checkpoint commit",
                "github": "exact GitHub main commit",
                "conflict": "Git tentative de rebase lineaire, NON resolue",
            },
            "files": [],
            "includes_shards": False,
            "no_auto_choice": True,
        }
        instructions = [
            "# Alina - conflits Git (copies locales NON publiees)",
            "",
            f"Commit local protege : `{local}`",
            f"HEAD distant observe : `{remote}`",
            "",
            "Ne supprimer ni la logique locale ni la logique GitHub.",
            "Analyser chaque triplet base/local/github, fusionner les intentions",
            "et tester les comportements avant de valider.",
            "Ces copies sont des diagnostics, jamais des fichiers a committer.",
            "",
            "## Fichiers",
        ]
        base_result = self.command("merge-base", local, remote, check=False)
        if base_result.returncode:
            raise SyncBlocked("Base commune locale/GitHub introuvable pour le kit.")
        base = base_result.stdout.decode("ascii", errors="strict").strip()
        for i, path in enumerate(conflicted):
            if _protected(path):
                raise SyncBlocked("Conflit sur chemin protege : " + path)
            entry: dict[str, object] = {"path": path, "versions": {}}
            instructions.append(f"- `{path}` : prefixe `{i:02d}-`")
            for label, spec in (
                ("base", f"{base}:{path}"),
                ("local", f"{local}:{path}"),
                ("github", f"{remote}:{path}"),
            ):
                outcome = self.command("show", spec, check=False)
                if outcome.returncode:
                    entry["versions"][label] = {"status": "ABSENT"}
                    continue
                raw = outcome.stdout
                if len(raw) > 2 * 1024 * 1024:
                    entry["versions"][label] = {"status": "TOO_LARGE"}
                    continue
                name = f"{i:02d}-{label}.txt"
                (dest / name).write_bytes(raw)
                entry["versions"][label] = {
                    "file": name,
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            conflict_path = self.root / path
            if conflict_path.is_file() and not conflict_path.is_symlink():
                raw = conflict_path.read_bytes()
                if len(raw) <= 2 * 1024 * 1024:
                    name = f"{i:02d}-conflict.txt"
                    (dest / name).write_bytes(raw)
                    entry["versions"]["conflict"] = {
                        "file": name,
                        "bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                    }
            manifest["files"].append(entry)
        instructions += [
            "",
            "## Reprise conseillee (Codex/Claude dans le clone local)",
            "",
            "1. Ouvrir le manifest.json et les 3 versions de chaque conflit.",
            "2. Comparer au HEAD local et a origin/main, jamais choisir",
            "   systematiquement --ours ou --theirs.",
            "3. Resoudre les intentions dans une serie de commits lineaire, sans",
            "   commit de fusion ni re-ecriture de main; lancer les tests locaux.",
            "4. Relancer POUSSER-GITHUB-FORCE.cmd pour verifier la reconciliation.",
            "",
            "Ce kit ne restaure rien automatiquement. Les originaux et les",
            "commits sont preserves; le rebase incomplet est annule sans force.",
        ]
        (dest / "RESOLUTION.md").write_text(
            "\n".join(instructions) + "\n", encoding="utf-8"
        )
        (dest / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self.report["conflict_kit"] = str(dest.relative_to(self.root)).replace("\\", "/")
        self.report["conflict_files"] = conflicted
        self.say("Kit de reconciliation local: " + str(self.report["conflict_kit"]))

    def _resolve_known_ci_conflicts(self, conflicted: list[str]) -> bool:
        """Resolve only validated hosted CI contract conflicts.

        Rebase names the upstream side `ours` and the replayed local commit
        `theirs`.  For these two workflows the upstream version is preferred
        because it contains the latest hosted CI contract; the safety markers
        below prevent accepting a self-hosted or real-execution path.
        Every other conflict remains fail-closed.
        """
        if not conflicted:
            return False
        if any(path not in AUTO_RESOLVABLE_CI_CONFLICTS for path in conflicted):
            return self._resolve_trivial_code_conflicts(conflicted)
        for path in conflicted:
            upstream = self.command("show", f":2:{path}", check=False)
            if upstream.returncode:
                return False
            content = upstream.stdout.decode("utf-8", errors="replace")
            lowered = content.casefold()
            if "runs-on: ubuntu-latest" not in lowered:
                return False
            if any(marker.casefold() in lowered
                   for marker in FORBIDDEN_HOSTED_CI_MARKERS):
                return False
            self.command("checkout", "--ours", "--", path)
            self.command("add", "--", path)
        resolutions = self.report.setdefault("ci_conflict_resolutions", [])
        if isinstance(resolutions, list):
            resolutions.extend({
                "path": path,
                "resolution": "UPSTREAM_HOSTED_CI_CONTRACT",
                "reason": "validated_no_self_hosted_or_real_execution_markers",
            } for path in conflicted)
        self.say(
            "Conflit CI resolu automatiquement: version hosted upstream "
            "validee, sans self-hosted ni execution reelle."
        )
        return True

    def _resolve_trivial_code_conflicts(self, conflicted: list[str]) -> bool:
        """Resolve a whitelisted code conflict only when semantics are equal."""
        if any(
            not path.endswith(".py")
            or not path.startswith(("src/", "tools/", "tests/"))
            or _protected(path)
            for path in conflicted
        ):
            return False
        for path in conflicted:
            versions = []
            for stage in (2, 3):
                result = self.command("show", f":{stage}:{path}", check=False)
                if result.returncode:
                    return False
                content = result.stdout.decode("utf-8", errors="strict")
                try:
                    compile(content, path, "exec")
                except SyntaxError:
                    return False
                versions.append(content)
            normalized = [
                [line.rstrip() for line in content.splitlines() if line.strip()]
                for content in versions
            ]
            if normalized[0] != normalized[1]:
                return False
            self.command("checkout", "--ours", "--", path)
            self.command("add", "--", path)
        resolutions = self.report.setdefault("ci_conflict_resolutions", [])
        if isinstance(resolutions, list):
            resolutions.extend({
                "path": path,
                "resolution": "TRIVIAL_WHITESPACE_ONLY",
                "reason": "both_sides_compile_and_match_after_blank_line_normalization",
            } for path in conflicted)
        self.say("Conflit code trivial resolu: versions compilees et semantiquement identiques.")
        return True

    def _continue_rebase_after_known_ci_conflicts(
        self, outcome: subprocess.CompletedProcess[bytes],
    ) -> bool:
        """Continue a rebase while only the known hosted CI conflicts occur.

        The initial failed ``git rebase`` result is part of the state machine:
        when the index has no conflicts, its stderr is the only evidence that
        the current commit is empty and may be skipped safely.
        """
        previous_editor = os.environ.get("GIT_EDITOR")
        os.environ["GIT_EDITOR"] = "true"
        try:
            for _ in range(32):
                conflicted = _paths(self.command(
                    "diff", "--name-only", "--diff-filter=U", "-z"
                ).stdout)
                if not conflicted:
                    detail = (
                        (outcome.stderr or b"") + (outcome.stdout or b"")
                    ).decode("utf-8", errors="replace").casefold()
                    if "empty" not in detail:
                        return False
                    skipped = self.command("rebase", "--skip", check=False)
                    if skipped.returncode:
                        return False
                    self.report["empty_rebase_commits_skipped"] = (
                        int(self.report.get("empty_rebase_commits_skipped", 0)) + 1
                    )
                    gitdir = Path(self.text("rev-parse", "--absolute-git-dir"))
                    if not any((gitdir / marker).exists()
                               for marker in ("rebase-merge", "rebase-apply")):
                        return True
                    continue
                if not self._resolve_known_ci_conflicts(conflicted):
                    return False
                outcome = self.command(
                    "rebase", "--continue", check=False,
                )
                if outcome.returncode == 0:
                    return True
            raise SyncBlocked("Trop de conflits CI successifs; rebase arrete.")
        finally:
            if previous_editor is None:
                os.environ.pop("GIT_EDITOR", None)
            else:
                os.environ["GIT_EDITOR"] = previous_editor

    def _abort_rebase_after_timeout(
        self, timeout: subprocess.TimeoutExpired,
    ) -> None:
        """Abort a timed-out rebase without leaving Git half-open.

        A killed ``git rebase`` can leave its state machine active.  Letting
        the outer error handler return in that state makes the next launcher
        invocation fail on a stale rebase and can hold the user in a long
        recovery loop.  The abort is itself bounded and never deletes a Git
        lock; if Git cannot prove the abort completed, fail closed.
        """
        budget = int(
            self.report.get("rebase_timeout_budget_seconds")
            or REBASE_TIMEOUT_SECONDS
        )
        self.report["rebase_timeout_seconds"] = budget
        self.report["rebase_timeout_count"] = (
            int(self.report.get("rebase_timeout_count", 0)) + 1
        )
        try:
            aborted = self.command(
                "rebase", "--abort", check=False,
                timeout=REBASE_ABORT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as abort_timeout:
            raise SyncBlocked(
                "Rebase depassee apres "
                f"{budget}s; git rebase --abort a aussi "
                f"depasse {REBASE_ABORT_TIMEOUT_SECONDS}s. Intervention "
                "manuelle requise; aucun push force."
            ) from abort_timeout

        gitdir = Path(self.text("rev-parse", "--absolute-git-dir"))
        markers = tuple(
            gitdir / marker for marker in ("rebase-merge", "rebase-apply")
        )
        if aborted.returncode or any(marker.exists() for marker in markers):
            detail = (aborted.stderr or b"").decode(
                "utf-8", errors="replace",
            ).strip()
            raise SyncBlocked(
                "Rebase depassee et abort Git non confirme; "
                "intervention manuelle requise; "
                + (detail[:600] if detail else "aucun detail Git")
            ) from timeout
        self.say(
            "[REBASE TIMEOUT] Rebase arretee et abort Git confirme; "
            "aucun push force."
        )
        raise SyncBlocked(
            "Rebase depassee apres "
            f"{budget}s; rebase annulee proprement."
        ) from timeout

    def _try_git_replay(
        self, remote: str, local: str, base: str,
    ) -> bool:
        """Use Git's index-preserving replay when the installed Git supports it.

        ``git replay`` creates the rebased commit objects without changing the
        current ref, index, or worktree.  We only publish its printed,
        old-value-guarded ref update after materialising the new tree with
        ``read-tree -u``.  If the ref update loses a race, the old tree is
        restored and the operation fails closed.  Git versions without this
        experimental command, or a replay with conflicts, return ``False`` so
        the established bounded rebase/resolver remains the compatibility
        path.
        """
        outcome = self.command(
            "replay", f"--onto={remote}", "--ref=refs/heads/main",
            "--ref-action=print", f"{base}..refs/heads/main",
            check=False,
            timeout=GIT_REPLAY_TIMEOUT_SECONDS,
            expected_returncodes=(1, 129),
        )
        detail = "\n".join(
            part.decode("utf-8", errors="replace")
            for part in (outcome.stdout or b"", outcome.stderr or b"")
            if part
        ).strip()
        if outcome.returncode:
            lowered = detail.casefold()
            if outcome.returncode == 1:
                self.report["replay_fallback"] = "GIT_REPLAY_CONFLICT"
                return False
            if outcome.returncode == 129 and any(marker in lowered for marker in (
                "is not a git command", "unknown command", "unknown subcommand",
            )):
                self.report["replay_fallback"] = "GIT_REPLAY_UNAVAILABLE"
                return False
            raise SyncBlocked(
                "git replay a echoue sans resultat exploitable: "
                + (detail[:900] or f"code {outcome.returncode}")
            )

        updates = []
        for line in detail.splitlines():
            fields = line.split()
            if (
                len(fields) == 4
                and fields[0] == "update"
                and fields[1] == "refs/heads/main"
                and re.fullmatch(r"[0-9a-f]{40,64}", fields[2])
                and re.fullmatch(r"[0-9a-f]{40,64}", fields[3])
            ):
                updates.append((fields[2], fields[3]))
        if len(updates) != 1:
            raise SyncBlocked(
                "git replay a repondu sans une mise a jour unique de main; "
                "aucun ref ni push modifie."
            )
        new_tip, expected_old = updates[0]
        if expected_old != local or new_tip == local:
            raise SyncBlocked(
                "git replay a produit une ancienne base inattendue; "
                "aucun ref ni push modifie."
            )

        # The replay itself did not touch the worktree.  Recheck the code
        # inventory immediately before applying the new tracked tree so a
        # concurrent editor cannot be overwritten silently.
        self._assert_no_new_code_changes()
        # On a shallow clone with thousands of SAFE catalog files on disk,
        # ``read-tree -u -m`` will refuse if any untracked file matches a
        # path in new_tip.  Pre-identify those conflicts and remove the SAFE
        # ones before attempting the tree update.
        incoming_paths = _paths(
            self.command(
                "diff", "--name-only", "-z", local, new_tip,
            ).stdout
        )
        existing_untracked: list[str] = []
        for path in incoming_paths:
            full = self.root / path
            if not full.is_file():
                continue
            existing_untracked.append(path)
        _tracked_here: set[str] = set()
        for start in range(0, len(existing_untracked), PROTECTED_PATH_BATCH_SIZE):
            batch = existing_untracked[start:start + PROTECTED_PATH_BATCH_SIZE]
            _tracked_here.update(_paths(
                self.command("ls-files", "-z", "--", *batch).stdout
            ))
        removed_safe: list[str] = []
        blocked_unsafe: list[str] = []
        for path in existing_untracked:
            if path in _tracked_here:
                continue
            if _can_defer_staged_protected(path):
                (self.root / path).unlink()
                removed_safe.append(path)
            else:
                blocked_unsafe.append(path)
        if blocked_unsafe:
            raise SyncBlocked(
                f"GitHub toucherait {len(blocked_unsafe)} fichier(s) local non "
                f"suivi(s) non-SAFE: {', '.join(blocked_unsafe[:5])}. "
                "Fusion interdite."
            )
        if removed_safe:
            self.say(
                f"[GARDE DONNEES] {len(removed_safe)} fichier(s) SAFE locaux "
                f"supprimes pour permettre la fusion (recrees par le remote)."
            )
        self.command(
            "read-tree", "-u", "-m", new_tip,
            timeout=REPLAY_WORKTREE_TIMEOUT_SECONDS,
        )
        updated = self.command(
            "update-ref", "refs/heads/main", new_tip, local,
            check=False,
        )
        if updated.returncode:
            restored = self.command(
                "read-tree", "-u", "-m", local,
                check=False,
                timeout=REPLAY_WORKTREE_TIMEOUT_SECONDS,
            )
            if restored.returncode:
                raise SyncBlocked(
                    "Mise a jour atomique de main refusee et restauration du "
                    "code impossible; intervention manuelle requise."
                )
            raise SyncBlocked(
                "Mise a jour atomique de main refusee; code local restaure."
            )

        if self.text("rev-parse", "HEAD") != new_tip:
            raise SyncBlocked(
                "HEAD local ne confirme pas le rejeu Git; aucun push lance."
            )
        # A full-index diff over the code pathspecs can exceed the replay
        # budget on this partial clone. The bounded status inventory already
        # excludes SAFE roots and reports any code that arrived during replay;
        # reuse it instead of holding the operator index in a long scan.
        self._assert_no_new_code_changes()
        self.report["replay_verification"] = "INVENTORY_NO_NEW_CODE_CHANGES"
        self.report["replay_engine"] = "GIT_REPLAY_INDEX_PRESERVING"
        self.report["local_rebased_onto"] = remote
        self.say(
            "[INTEGRATION RAPIDE] git replay a rejoue les commits sans "
            "rebase checkout; code local aligne."
        )
        return True

    @contextlib.contextmanager
    def _temporary_index(self):
        """Give tree-only replay an isolated index, never the operator index."""
        git_dir = self.root / ".git"
        if not git_dir.is_dir():
            raise SyncBlocked("Git directory absent; replay arbre impossible.")
        fd, raw_path = tempfile.mkstemp(
            prefix=".alina-tree-replay-", suffix=".index", dir=git_dir,
        )
        os.close(fd)
        index = Path(raw_path)
        index.unlink(missing_ok=True)
        previous = os.environ.get("GIT_INDEX_FILE")
        os.environ["GIT_INDEX_FILE"] = str(index)
        try:
            yield index
        finally:
            if previous is None:
                os.environ.pop("GIT_INDEX_FILE", None)
            else:
                os.environ["GIT_INDEX_FILE"] = previous
            index.unlink(missing_ok=True)

    def _try_tree_plumbing_replay(
        self, remote: str, local: str, base: str,
        predicted: list[str],
    ) -> bool:
        """Replay linear commits through trees for approved governance conflicts.

        Classic rebase refreshes the full 346MB index for every local commit.
        For the small, reviewed governance conflict set, Git's three-tree
        index merge is enough: keep the current GitHub stage for those paths,
        fail closed for every other conflict, create equivalent linear commit
        objects, then update the real worktree once and advance main atomically.
        The operator's real index is never used during planning.
        """
        if not predicted or any(
            path not in AUTO_RESOLVABLE_GOVERNANCE_CONFLICTS
            for path in predicted
        ):
            return False
        commits = self.text(
            "rev-list", "--reverse", "--topo-order", f"{base}..{local}"
        ).split()
        if not commits:
            return False
        current = remote
        resolved: list[dict[str, str]] = []
        skipped_empty = 0
        replay_index_info = b""
        with self._temporary_index():
            for old_commit in commits:
                parents = self.text(
                    "rev-list", "--parents", "-n", "1", old_commit
                ).split()
                if len(parents) != 2:
                    raise SyncBlocked(
                        "Commit local de fusion ou parent ambigu; replay arbre refuse."
                    )
                old_parent = parents[1]
                merged = self.command(
                    # The temporary index must not validate the operator
                    # worktree: it may still contain the local version of a
                    # code file while the three-tree merge is being planned.
                    # `-i` keeps this phase index-only and cannot overwrite
                    # SAFE bytes.
                    "read-tree", "-m", "-i", old_parent, current, old_commit,
                    check=False, expected_returncodes=(1,),
                    timeout=REPLAY_WORKTREE_TIMEOUT_SECONDS,
                )
                if merged.returncode not in (0, 1):
                    self.report["tree_replay_fallback_reason"] = {
                        "phase": "three_tree_read",
                        "commit": old_commit,
                        "parent": old_parent,
                        "current": current,
                        "exit_code": merged.returncode,
                        "stderr": _redact_sensitive_text(
                            (merged.stderr or b"").decode(
                                "utf-8", errors="replace"
                            ).strip()
                        )[:900],
                    }
                    return False
                unmerged_raw = self.command(
                    "ls-files", "-u", "-z",
                ).stdout
                stage_rows: dict[str, dict[int, tuple[str, str]]] = {}
                for raw_row in unmerged_raw.split(b"\0"):
                    if not raw_row:
                        continue
                    fields = raw_row.decode("utf-8", errors="strict").split("\t", 1)
                    if len(fields) != 2:
                        raise SyncBlocked("Index de replay arbre illisible.")
                    mode_oid_stage = fields[0].split()
                    if len(mode_oid_stage) != 3:
                        raise SyncBlocked("Stage Git de replay arbre invalide.")
                    mode, oid, stage_text = mode_oid_stage
                    stage_rows.setdefault(fields[1], {})[int(stage_text)] = (mode, oid)
                if stage_rows:
                    if any(path not in AUTO_RESOLVABLE_GOVERNANCE_CONFLICTS
                           for path in stage_rows):
                        self.report["tree_replay_fallback_reason"] = {
                            "phase": "unapproved_stage",
                            "commit": old_commit,
                            "paths": sorted(stage_rows)[:24],
                        }
                        return False
                    for path, stages in stage_rows.items():
                        upstream = stages.get(2)
                        if upstream is None:
                            self.command("update-index", "--remove", "--", path)
                        else:
                            mode, oid = upstream
                            self.command(
                                "update-index", "--add", "--cacheinfo",
                                f"{mode},{oid},{path}",
                            )
                        resolved.append({
                            "path": path,
                            "resolution": "UPSTREAM_GITHUB_HEAD",
                            "commit": old_commit,
                        })
                    if self.command("ls-files", "-u", "-z").stdout:
                        raise SyncBlocked(
                            "Conflit residuel apres resolution gouvernance; aucun push."
                        )
                tree = self.command(
                    "write-tree", timeout=COMMIT_TIMEOUT_SECONDS,
                ).stdout.decode("ascii", errors="strict").strip()
                if not re.fullmatch(r"[0-9a-f]{40,64}", tree):
                    raise SyncBlocked("Arbre de replay invalide; aucun push.")
                current_tree = self.text("rev-parse", f"{current}^{{tree}}")
                if tree == current_tree:
                    skipped_empty += 1
                    continue
                message = self.command(
                    "show", "-s", "--format=%B", old_commit,
                ).stdout
                created = self.command(
                    # `commit-tree` has no --author option; its author comes
                    # from the configured Git identity/environment.  Passing
                    # the pretty-printed author as an option made the
                    # governance replay fail with exit 129 after all its
                    # expensive index work had completed.
                    "commit-tree", tree, "-p", current,
                    input_bytes=message, timeout=COMMIT_TIMEOUT_SECONDS,
                ).stdout.decode("ascii", errors="strict").strip()
                if not re.fullmatch(r"[0-9a-f]{40,64}", created):
                    raise SyncBlocked("Commit de replay invalide; aucun push.")
                current = created

            # The temporary index contains the final replay tree.  Applying
            # it with `read-tree -u` against the operator index is unsafe
            # here: the operator index intentionally contains local SAFE-byte
            # changes and Git can reject the whole checkout (or touch a
            # protected path).  Copy only changed, non-protected files from
            # the isolated index.  This keeps shard bytes untouched and makes
            # the concurrent-push window short.
            changed_paths = _paths(
                self.command("diff", "--name-only", "-z", local, current).stdout
            )
            deleted_code_paths = [
                path for path in _paths(self.command(
                    "diff", "--name-only", "--diff-filter=D", "-z",
                    local, current,
                ).stdout)
                if not _protected(path)
            ]
            if deleted_code_paths:
                raise SyncBlocked(
                    "Replay arbre avec suppression de code refuse sans "
                    "nettoyage implicite: "
                    + ", ".join(deleted_code_paths[:8])
                )
            code_paths = [path for path in changed_paths if not _protected(path)]
            # Inspect late edits against the operator's real index, not the
            # temporary merge index.  They are deliberately deferred: the
            # checkpoint being replayed remains publishable, while the new
            # bytes stay on disk and are reported for the next run.
            previous_index = os.environ.pop("GIT_INDEX_FILE", None)
            try:
                self._inventory_cache = None
                late_staged, late_tracked, late_untracked = self._inventory(
                    refresh=True
                )
                late_candidates = self._check_candidates(
                    late_staged, late_tracked, late_untracked,
                    allow_protected_local=True,
                )
            finally:
                if previous_index is not None:
                    os.environ["GIT_INDEX_FILE"] = previous_index
            deferred = set(late_candidates)
            if code_paths:
                deferred.update(
                    self._worktree_mismatched_tree_paths(local, code_paths)
                )
            self._deferred_local_paths.update(deferred)
            if deferred:
                deferred_list = sorted(deferred)
                self.report["deferred_local_paths"] = deferred_list[:100]
                self.report["deferred_local_count"] = len(deferred_list)
                self.say(
                    "[REPLAY] Code arrive pendant le rejeu; "
                    f"{len(deferred_list)} chemin(s) conserve(s) pour le "
                    "prochain checkpoint, sans ecrasement."
                )
            apply_paths = [path for path in code_paths if path not in deferred]
            if apply_paths:
                self.command(
                    "checkout-index", "--force", "-z", "--stdin",
                    input_bytes=b"\0".join(
                        path.encode("utf-8") for path in apply_paths
                    ) + b"\0",
                    timeout=REPLAY_WORKTREE_TIMEOUT_SECONDS,
                )

            # Verify only the selected blobs while the temporary index is
            # active.  This avoids a full-index `git diff` on every replay.
            if apply_paths and not self._worktree_matches_tree_paths(
                current, apply_paths,
            ):
                raise SyncBlocked(
                    "Worktree code different du replay arbre; aucun push."
                )
            if code_paths:
                replay_index_info = self.command(
                    "ls-files", "-s", "-z", "--", *code_paths,
                ).stdout

        # Align only the code entries in the operator index.  A full
        # `read-tree` would revalidate/replace the protected SAFE entries and
        # can fail on their intentionally dirty worktree bytes.  The outer
        # guard leaves those entries and their bytes untouched.
        if replay_index_info:
            self.command(
                "update-index", "-z", "--index-info",
                input_bytes=replay_index_info,
            )
        updated = self.command(
            "update-ref", "refs/heads/main", current, local, check=False,
        )
        if updated.returncode:
            restored = self.command("read-tree", local, check=False)
            if restored.returncode:
                raise SyncBlocked(
                    "Ref Git refusee et restauration de l'index impossible; "
                    "intervention manuelle requise."
                )
            raise SyncBlocked(
                "Ref Git avancee par une autre operation; index restaure, "
                "aucun push."
            )
        if self.text("rev-parse", "HEAD") != current:
            raise SyncBlocked("HEAD apres replay arbre non prouve; aucun push.")
        self.report["replay_engine"] = "TREE_PLUMBING_REPLAY_GOVERNANCE"
        self.report["tree_replay_conflict_resolutions"] = resolved
        self.report["empty_replay_commits_skipped"] = skipped_empty
        self.report["local_rebased_onto"] = remote
        self.say(
            "[INTEGRATION RAPIDE] Replay arbre termine sans rebase classique; "
            f"{len(resolved)} conflit(s) gouvernance conserve(nt) GitHub."
        )
        return True

    def _worktree_matches_tree_paths(
        self, tree: str, paths: list[str],
    ) -> bool:
        """Compare selected worktree blobs without scanning the giant index."""
        return not self._worktree_mismatched_tree_paths(tree, paths)

    def _worktree_mismatched_tree_paths(
        self, tree: str, paths: list[str],
    ) -> set[str]:
        """Return selected paths whose worktree bytes differ from a tree."""
        if not paths:
            return set()
        rows = self.command(
            "ls-tree", "-z", tree, "--", *paths,
        ).stdout
        tree_hashes: dict[str, str] = {}
        for raw_row in rows.split(b"\0"):
            if not raw_row:
                continue
            header, separator, raw_path = raw_row.partition(b"\t")
            fields = header.split()
            if not separator or len(fields) != 3:
                raise SyncBlocked("Arbre Git de verification illisible.")
            tree_hashes[raw_path.decode("utf-8", errors="strict")] = (
                fields[2].decode("ascii", errors="strict")
            )

        existing = [
            path for path in paths
            if (self.root / path).is_file() or (self.root / path).is_symlink()
        ]
        mismatched: set[str] = set()
        for path in paths:
            if path not in tree_hashes and path in existing:
                mismatched.add(path)
            if path in tree_hashes and path not in existing:
                mismatched.add(path)
        if not existing:
            return mismatched
        worktree_hashes = self.command(
            "hash-object", "--", *existing,
        ).stdout.decode("ascii", errors="strict").splitlines()
        if len(worktree_hashes) != len(existing):
            return set(paths)
        mismatched.update({
            path for index, path in enumerate(existing)
            if tree_hashes.get(path) != worktree_hashes[index]
        })
        return mismatched

    def _run_rebase(
        self, remote: str, *, timeout_seconds: int | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        """Run the bounded rebase without ever returning an unbound outcome.

        The timeout handler normally raises ``SyncBlocked`` after confirming
        ``git rebase --abort``.  Keeping the raise here as an explicit safety
        net matters because a test double, an interrupted interpreter, or a
        future handler change must never let ``reconcile`` continue with a
        result that was never produced.
        """
        previous_editor = os.environ.get("GIT_EDITOR")
        previous_sequence_editor = os.environ.get("GIT_SEQUENCE_EDITOR")
        previous_merge_autoedit = os.environ.get("GIT_MERGE_AUTOEDIT")
        # A double-clicked launcher has no reliable interactive terminal.  A
        # rebase that reaches a commit-message step must therefore finish
        # non-interactively instead of looking hung until the timeout.  This
        # does not bypass conflict validation: unresolved conflicts still
        # return to the fail-closed resolver below.
        os.environ["GIT_EDITOR"] = "true"
        os.environ["GIT_SEQUENCE_EDITOR"] = "true"
        os.environ["GIT_MERGE_AUTOEDIT"] = "no"
        budget = int(timeout_seconds or REBASE_TIMEOUT_SECONDS)
        self.report["rebase_timeout_budget_seconds"] = budget
        self.report["rebase_strategy"] = (
            "REAPPLY_CHERRY_PICKS_NO_UPSTREAM_SCAN_NO_FORK_POINT"
        )
        try:
            return self.command(
                "rebase", "--no-autostash", "--reapply-cherry-picks",
                "--no-fork-point", remote,
                check=False,
                timeout=budget,
            )
        except subprocess.TimeoutExpired as timeout:
            self._abort_rebase_after_timeout(timeout)
            raise SyncBlocked(
                "Rebase timeout handler returned without a confirmed abort; "
                "aucun push force."
            ) from timeout
        finally:
            if previous_editor is None:
                os.environ.pop("GIT_EDITOR", None)
            else:
                os.environ["GIT_EDITOR"] = previous_editor
            if previous_sequence_editor is None:
                os.environ.pop("GIT_SEQUENCE_EDITOR", None)
            else:
                os.environ["GIT_SEQUENCE_EDITOR"] = previous_sequence_editor
            if previous_merge_autoedit is None:
                os.environ.pop("GIT_MERGE_AUTOEDIT", None)
            else:
                os.environ["GIT_MERGE_AUTOEDIT"] = previous_merge_autoedit

    def reconcile(self) -> None:
        self.say(
            "[MOTEUR 5/5] Recuperation de main depuis GitHub "
            "(objets Git seulement, aucun shard)."
        )
        if self._remote_snapshot_ready:
            self._remote_snapshot_ready = False
            self.say(
                "[FETCH] Snapshot preflight reutilise; aucun second fetch "
                "identique avant le rebase."
            )
        else:
            self.command(
                "fetch", "--progress", "--no-tags", "origin",
                "refs/heads/main:refs/remotes/origin/main",
            )
        remote = self.text("rev-parse", "refs/remotes/origin/main")
        local = self.text("rev-parse", "HEAD")
        self.say(
            f"[COMPARAISON] local={local[:12]} | GitHub={remote[:12]}"
        )
        if local == remote or self.command(
            "merge-base", "--is-ancestor", remote, local, check=False,
            expected_returncodes=(1,),
        ).returncode == 0:
            self.say("Tous les commits distants sont deja dans main local.")
            return
        self._assert_no_new_code_changes()
        self._protect_ignored_files(remote)
        if self.command(
            "merge-base", "--is-ancestor", local, remote, check=False,
            expected_returncodes=(1,),
        ).returncode == 0:
            self.say(
                "[INTEGRATION] Avance rapide possible: adoption des commits "
                "GitHub sans creer de commit de fusion."
            )
            with self._preserve_local_protected_index():
                self.command("merge", "--ff-only", remote)
            self.say("[INTEGRATION OK] HEAD local aligne sur GitHub main.")
            return
        self.command(
            "update-ref", "refs/alina-sync/last-local-checkpoint", local
        )
        local_merges = self.command(
            "rev-list", "--merges", f"{remote}..{local}", check=False
        )
        if local_merges.returncode:
            raise SyncBlocked("Verification des commits locaux impossible.")
        if local_merges.stdout.strip():
            raise SyncBlocked(
                "Des commits de fusion locaux non publies existent; "
                "rejeu automatique refuse pour preserver l'historique."
            )
        replay_count = self.command(
            "rev-list", "--count", f"{remote}..{local}", check=False
        )
        replay_count_text = replay_count.stdout.decode(
            "ascii", errors="replace"
        ).strip()
        if replay_count.returncode or not replay_count_text.isdecimal():
            raise SyncBlocked("Comptage des commits locaux a rejouer impossible.")
        replay_count_value = int(replay_count_text)
        rebase_budget = _rebase_timeout_budget(replay_count_value)
        self.say(
            "[INTEGRATION LINEAIRE] Rejeu de "
            f"{replay_count_value} commit(s) local(aux) sur GitHub main; "
            f"budget rebase={rebase_budget}s; aucun commit de fusion."
        )
        base = self.text("merge-base", local, remote)
        predicted = self._predict_merge_conflicts(remote, local)
        unsupported = [
            path for path in predicted
            if not self._preflight_auto_resolvable_conflict(path)
        ]
        if unsupported:
            raise SyncBlocked(
                "Conflits previsibles non auto-resolvables: "
                + ", ".join(unsupported[:12])
                + ". Rebase non lance; commits locaux et GitHub preserves."
            )
        rebase_resolved = False
        with self._preserve_local_protected_index():
            if predicted and all(
                path in AUTO_RESOLVABLE_GOVERNANCE_CONFLICTS
                for path in predicted
            ) and self._try_tree_plumbing_replay(
                remote, local, base, predicted,
            ):
                self.report["rebases_performed"] = (
                    int(self.report["rebases_performed"]) + 1
                )
                return
            if not predicted and self._try_git_replay(remote, local, base):
                self.report["rebases_performed"] = (
                    int(self.report["rebases_performed"]) + 1
                )
                return
            outcome = self._run_rebase(
                remote, timeout_seconds=rebase_budget,
            )
            if outcome.returncode:
                rebase_resolved = self._continue_rebase_after_known_ci_conflicts(
                    outcome,
                )
                if not rebase_resolved:
                    conflicted = _paths(self.command(
                        "diff", "--name-only", "--diff-filter=U", "-z"
                    ).stdout)
                    if conflicted:
                        try:
                            self._capture_conflicts(conflicted, local, remote)
                        except (OSError, SyncBlocked) as exc:
                            self.report["conflict_kit_error"] = str(exc)
                            self.say("Kit de conflits non ecrit: " + str(exc))
                    gitdir = Path(self.text("rev-parse", "--absolute-git-dir"))
                    rebase_markers = (
                        gitdir / "rebase-merge", gitdir / "rebase-apply"
                    )
                    if any(marker.exists() for marker in rebase_markers):
                        abort = self.command("rebase", "--abort", check=False)
                        if (
                            abort.returncode
                            or any(marker.exists() for marker in rebase_markers)
                        ):
                            raise SyncBlocked(
                                "Echec de git rebase --abort. Ne rien nettoyer; "
                                "conserver les commits et terminer la reprise "
                                "manuellement."
                            )
                    if not conflicted:
                        raise SyncBlocked(
                            "Git rebase refuse sans conflit index detecte; "
                            "aucun choix automatique: "
                            + outcome.stderr.decode(
                                "utf-8", errors="replace"
                            )[:900]
                        )
                    raise SyncBlocked(
                        "Conflit de code: " + ", ".join(conflicted[:12])
                        + ". Rejeu annule; commits locaux et GitHub preserves. "
                        "Voir le kit dans runtime/reports/git-sync/conflicts."
                    )
        if rebase_resolved:
            self.report["rebases_performed"] = (
                int(self.report["rebases_performed"]) + 1
            )
            self.report["local_rebased_onto"] = remote
            self.say(
                "[INTEGRATION OK] Commits locaux rejoues; conflits CI "
                "resolus sous contrat hosted."
            )
            return
        self.report["rebases_performed"] = (
            int(self.report["rebases_performed"]) + 1
        )
        self.report["local_rebased_onto"] = remote
        self.say("[INTEGRATION OK] Commits locaux rejoues en ligne droite.")

    def publish(self) -> None:
        local_retries = 0
        push_races = 0
        while local_retries <= MAX_LOCAL_CHANGE_RETRIES and push_races <= MAX_RACE_RETRIES:
            try:
                self.reconcile()
                self._assert_no_new_code_changes(allow_deferred=True)
            except LocalEditsDetected as exc:
                if local_retries >= MAX_LOCAL_CHANGE_RETRIES:
                    raise SyncBlocked(
                        "Le code change encore pendant la synchronisation "
                        f"apres {MAX_LOCAL_CHANGE_RETRIES} sauvegardes : {exc}. "
                        "Fermer les editeurs qui reecrivent des fichiers avant de relancer."
                    ) from exc
                local_retries += 1
                self.report["late_checkpoint_attempts"] = local_retries
                self.say(
                    f"Nouveau code detecte apres fetch. "
                    f"Sauvegarde prudente ({local_retries}/{MAX_LOCAL_CHANGE_RETRIES})..."
                )
                self.checkpoint()
                self._syntax_gate()
                # Never merge or push before rechecking the worktree and remote.
                continue

            local = self.text("rev-parse", "HEAD")
            current_remote = self.remote_sha()
            if local == current_remote:
                # ``reconcile`` may have fast-forwarded local main while
                # GitHub advanced again during the same run.  The final
                # success receipt must describe the SHA just verified here,
                # never the older preflight snapshot.
                self.report["remote_sha_observed"] = current_remote
                self.report["status"] = "SYNCHRONIZED"
                self.report["head_after"] = local
                self.report["checkpoint_sha_after_reconcile"] = local
                self.say("GitHub et main local identiques; pas de commit vide.")
                return
            # The non-force push is the authoritative ancestry check.  A
            # merge-base probe here is both redundant and expensive on this
            # shallow repository (it can take ~30 s), while GitHub may still
            # advance immediately after the probe.  Let Git reject a stale
            # ref atomically, then use the bounded reconciliation below.
            self.say(
                f"Push sans force vers main ({push_races + 1}/{MAX_RACE_RETRIES})..."
            )
            self.report["push_attempts"] = int(self.report["push_attempts"]) + 1
            pushed = self.command(
                SAFE_MAIN_PUSH_REFSPEC[0], "--porcelain",
                *SAFE_MAIN_PUSH_REFSPEC[1:],
                check=False,
            )
            if pushed.returncode == 0:
                push_output = "\n".join(
                    part.decode("utf-8", errors="replace")
                    for part in (pushed.stdout or b"", pushed.stderr or b"")
                    if part
                )
                _verify_push_porcelain(
                    push_output, local, "refs/heads/main",
                )
                self.report["push_ref_result"] = {
                    "ref": "refs/heads/main",
                    "expected_sha": local,
                    "status": "SUCCESS",
                }
                self.report["push_completed"] = True
                self.report["pushed_head"] = local
                verified_remote = self.remote_sha()
                self.report["remote_sha_observed"] = verified_remote
                if verified_remote == local:
                    self.report["status"] = "SYNCHRONIZED"
                    self.report["head_after"] = local
                    self.report["checkpoint_sha_after_reconcile"] = local
                    self.say("SHA local = SHA GitHub; synchronisation verifiee.")
                    return
                self.say("GitHub a de nouveau avance; fusion supplementaire.")
                push_races += 1
                continue
            # A rejection can race with the remote ref update: ls-remote may
            # still expose the old value while the server has already judged
            # the push against a newer ref.  Refresh the tracking ref before
            # classifying the rejection, otherwise a valid race is reported
            # as a false authentication/protection failure.
            err = _redact_sensitive_text((pushed.stderr or b"").decode(
                "utf-8", errors="replace",
            ).strip())
            failure_class = _classify_git_failure(err, pushed.returncode)
            classes = self.report.setdefault("push_failure_classes", [])
            if isinstance(classes, list):
                classes.append(failure_class)
            if failure_class not in {"retryable_race", "retryable_network"}:
                if not err:
                    err = "aucun detail Git recupere"
                raise SyncBlocked(
                    f"Push refuse ({failure_class}): {err[:1500]}"
                )
            self.command(
                "fetch", "--progress", "--no-tags", "origin",
                "refs/heads/main:refs/remotes/origin/main",
            )
            refreshed_remote = self.text(
                "rev-parse", "refs/remotes/origin/main"
            )
            if refreshed_remote != current_remote:
                self.say("Push non-fast-forward refuse; GitHub avance, reprise...")
                push_races += 1
                continue
            if failure_class == "retryable_race":
                self.say(
                    "Rejet non-fast-forward persistant sans nouveau SHA observe; "
                    "nouvelle tentative bornee."
                )
                push_races += 1
                continue
            self.say("Echec reseau Git; nouvelle tentative bornee.")
            push_races += 1
            continue
        raise SyncBlocked(
            "GitHub avance trop souvent, ou le code local change trop "
            "frequemment: limite de tentatives atteinte. Aucun push force."
        )


    def _write_report(self) -> None:
        dest = self.root / "runtime" / "reports" / "git-sync"
        history = dest / "history"
        if any(p.is_symlink() for p in (
            self.root / "runtime", self.root / "runtime" / "reports", dest,
            history,
        )):
            return
        try:
            if not self.report.get("run_id"):
                self.report["run_id"] = (
                    datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
                    + f"-{os.getpid()}"
                )
            safe_run_id = re.sub(
                r"[^0-9A-Za-z_.-]", "_", str(self.report["run_id"])
            )
            history.mkdir(parents=True, exist_ok=True)
            history_name = f"RUN-{safe_run_id}.json"
            self.report["history_receipt"] = (
                f"runtime/reports/git-sync/history/{history_name}"
            )
            _atomic_json_write(history / history_name, self.report)
            history_files = sorted(
                history.glob("RUN-*.json"), key=lambda path: path.name,
                reverse=True,
            )
            for stale in history_files[RECEIPT_HISTORY_LIMIT:]:
                try:
                    stale.unlink()
                except FileNotFoundError:
                    pass
            # Publish LAST_SYNC only after its immutable history target exists;
            # a reporting failure therefore leaves the previous pointer valid.
            _atomic_json_write(dest / "LAST_SYNC.json", self.report)
            self.say("Journal: runtime/reports/git-sync/LAST_SYNC.json")
        except OSError as exc:
            self.say(f"Journal non ecrit, sans effet sur Git: {exc}")

    def run(self, *, wip_only: bool = False) -> int:
        run_started = time.monotonic()
        self.report["started_at_utc"] = datetime.now(UTC).isoformat()
        self._allow_protected_local_checkpoint = wip_only
        self.say(
            "[DEBUT] Mode="
            + ("DRY-RUN (lecture seule)" if self.dry_run else
               "CHECKPOINT LOCAL" if wip_only else "SYNCHRONISATION")
            + " | aucun telechargement de shard | aucun push force."
        )
        result_code = 0
        try:
            # A shallow clone is safe to inspect in every mode.  The real
            # synchronisation path expands it inside the Git mutex before
            # comparing or replaying history; dry-run/checkpoint modes never
            # fetch and therefore remain read-only.
            gitdir = self.preflight(
                allow_shallow=True,
                allow_non_main=(
                    self.dry_run or wip_only or self.promote_current_to_main
                ),
            )
            with _mutex(gitdir):
                active_branch = self.text("branch", "--show-current")
                promotion_needed = (
                    self.promote_current_to_main
                    and active_branch != "main"
                )
                fast_path = False
                if not self.dry_run and not wip_only and not promotion_needed:
                    fast_path = self._fast_path_if_clean()
                if fast_path:
                    pass
                else:
                    if not self.dry_run and not wip_only:
                        self._ensure_full_history()
                    self.capture_preflight(
                        fetch_remote=not self.dry_run and not wip_only,
                        allow_protected_local=True,
                    )
                    self.checkpoint()
                    if promotion_needed:
                        self._promote_current_branch_to_main(active_branch)
                if self.dry_run:
                    remote_sha = self.remote_sha()
                    self.report["remote_sha_observed"] = remote_sha
                    snapshot = self.report.get("preflight")
                    if isinstance(snapshot, dict):
                        snapshot["remote_head_observed"] = remote_sha
                        if remote_sha == snapshot.get("local_head"):
                            snapshot["ahead_commits"] = 0
                            snapshot["behind_commits"] = 0
                            snapshot["comparison_status"] = "EXACT_REMOTE_SHA_EQUALS_LOCAL"
                        else:
                            snapshot["comparison_status"] = "NOT_COMPUTED_DRY_RUN_NO_FETCH"
                    self.report["status"] = "DRY_RUN_ONLY"
                    self.say(
                        "[DRY-RUN TERMINE] HEAD local="
                        f"{str(self.report.get('head_before', ''))[:12]} | "
                        f"HEAD GitHub={str(self.report['remote_sha_observed'])[:12]}."
                    )
                    self.say(
                        "Aucun add, commit, fetch, merge ou push n'a ete execute."
                    )
                elif wip_only:
                    self.report["status"] = "LOCAL_CHECKPOINT_ONLY"
                    self.report["head_after"] = self.text("rev-parse", "HEAD")
                    self.say(
                        "[CHECKPOINT LOCAL TERMINE] Travail conserve sur la "
                        f"branche {self.text('branch', '--show-current')}; "
                        "aucun acces GitHub ni push."
                    )
                elif not fast_path:
                    self._syntax_gate()
                    self.publish()
                    self._assert_no_new_code_changes(allow_deferred=True)
                    if self.text("rev-parse", "HEAD") != self.remote_sha():
                        raise SyncBlocked("GitHub a avance; relancer pour finaliser.")
        except (SyncBlocked, subprocess.TimeoutExpired, OSError) as exc:
            self.report["status"] = "NO_GO"
            safe_error = _redact_sensitive_text(str(exc))
            self.report["error"] = safe_error
            self.say("[NO_GO] " + safe_error)
            self.say(
                "Aucun shard telecharge; aucun push force, reset ou clean."
            )
            result_code = 2
        except Exception as exc:  # pragma: no cover - regression guard below
            # The synchronizer is a safety boundary. A future programming
            # regression must never escape as a traceback while leaving a
            # stale NOT_STARTED receipt that looks inconclusive to the CMD.
            # Do not attempt recovery, cleanup, rebase or push here: the
            # finally block only records the fail-closed outcome.
            self.report["status"] = "NO_GO"
            self.report["error_type"] = type(exc).__name__
            safe_error = _redact_sensitive_text(str(exc)) or type(exc).__name__
            self.report["error"] = safe_error
            self.say(
                "[NO_GO] Unexpected internal sync error: "
                + safe_error
            )
            self.say(
                "Aucun shard telecharge; aucun push force, reset ou clean."
            )
            result_code = 2
        finally:
            elapsed_ms = int((time.monotonic() - run_started) * 1000)
            self.report["duration_ms"] = elapsed_ms
            self.report["finished_at_utc"] = datetime.now(UTC).isoformat()
            self.report["exit_code"] = result_code
            status = str(self.report.get("status") or "UNKNOWN")
            self.say(
                f"[FIN] statut={status} | code retour={result_code} | "
                f"duree totale={elapsed_ms / 1000:.1f} s"
            )
            self._write_report()
        return result_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--git", default="git")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--wip-only", action="store_true")
    parser.add_argument(
        "--promote-current-to-main", action="store_true",
        help="promouvoir la branche active vers main par fast-forward seulement",
    )
    parser.add_argument("--test-remote", action="store_true", help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    if options.dry_run and options.wip_only:
        parser.error("Modes --dry-run et --wip-only incompatibles.")
    if options.promote_current_to_main and (options.dry_run or options.wip_only):
        parser.error(
            "La promotion automatique est incompatible avec --dry-run et --wip-only."
        )
    print(
        "ALINA CODE SYNC - main local <-> GitHub main - ZERO shard - sans force",
        flush=True,
    )
    return Synchronizer(
        options.root, options.git, dry_run=options.dry_run,
        allow_test_remote=options.test_remote,
        promote_current_to_main=options.promote_current_to_main,
    ).run(wip_only=options.wip_only)


if __name__ == "__main__":
    raise SystemExit(main())
