#!/usr/bin/env python3
"""Publish an already committed state update to main without rewriting history.

Concurrent GitHub-hosted campaign workers may all update different durable
campaign files. A normal fast-forward push is the transaction boundary: GitHub
accepts one ref update atomically, and every losing writer must fetch/rebase
and retry. This helper centralizes that protocol and refuses merge conflicts,
dirty tracked files, and non-contention failures.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import subprocess
import sys
import time
from collections.abc import Sequence

GIT_COMMAND_TIMEOUT_SECONDS = 90.0
RETRYABLE = (
    "non-fast-forward",
    "fetch first",
    "failed to update ref",
    "cannot lock ref",
    "remote end hung up unexpectedly",
    "the remote end hung up unexpectedly",
    "connection reset",
    "connection timed out",
    "timed out",
    "could not resolve host",
    "temporary failure",
    "unexpected disconnect",
    "rpc failed",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
    "bad gateway",
    "service unavailable",
    "internal server error",
)


def _git(args: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["git", *args]
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "Never"
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_COMMAND_TIMEOUT_SECONDS,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        def decode(value: str | bytes | None) -> str:
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="replace").strip()
            return (value or "").strip()

        stdout = decode(exc.stdout or exc.output)
        stderr = decode(exc.stderr)
        message = f"git command timed out after {GIT_COMMAND_TIMEOUT_SECONDS:g}s"
        return subprocess.CompletedProcess(
            command,
            124,
            stdout,
            f"{message}: {stderr}" if stderr else message,
        )
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"git {' '.join(args)} failed ({result.returncode}): {detail}")
    return result


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    result = _git(["merge-base", "--is-ancestor", ancestor, descendant], check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError((result.stderr or result.stdout).strip() or "merge-base failed")
    return result.returncode == 0


def _retryable(result: subprocess.CompletedProcess[str]) -> bool:
    message = f"{result.stdout}\n{result.stderr}".casefold()
    return any(marker in message for marker in RETRYABLE)


def _backoff(attempt: int, base_delay_s: float, max_delay_s: float) -> None:
    delay_cap = min(max_delay_s, base_delay_s * (2 ** min(attempt - 1, 30)))
    if delay_cap:
        time.sleep(random.SystemRandom().uniform(delay_cap / 2, delay_cap))


def _emit(payload: dict[str, object], *, stream=sys.stdout) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), file=stream)


def publish(
    *,
    remote: str = "origin",
    branch: str = "main",
    max_attempts: int = 20,
    base_delay_s: float = 0.5,
    max_delay_s: float = 12.0,
) -> dict[str, object]:
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", remote) or remote.startswith("-"):
        raise ValueError("invalid remote name")
    if not branch or branch.startswith("-") or ".." in branch:
        raise ValueError("invalid branch name")
    _git(["check-ref-format", f"refs/heads/{branch}"])
    if max_attempts < 1 or not math.isfinite(base_delay_s) or not math.isfinite(max_delay_s):
        raise ValueError("invalid retry bounds")
    if base_delay_s < 0 or max_delay_s < base_delay_s:
        raise ValueError("maximum retry delay must be finite and at least the base delay")
    if _git(["remote", "get-url", remote], check=False).returncode:
        raise ValueError(f"git remote {remote!r} is not configured")

    dirty = _git(["status", "--porcelain", "--untracked-files=no"]).stdout
    if dirty.strip():
        raise RuntimeError("refusing to publish with tracked staged or unstaged changes")

    tracking = f"refs/remotes/{remote}/{branch}"
    head = _git(["rev-parse", "HEAD"]).stdout.strip()
    event: dict[str, object] = {
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "job_id": os.environ.get("GITHUB_JOB"),
        "event_sha": os.environ.get("GITHUB_SHA"),
    }

    initial_remote: str | None = None
    last_push_error = ""
    for attempt in range(1, max_attempts + 1):
        fetched = _git(["fetch", "--no-tags", remote, f"+refs/heads/{branch}:{tracking}"], check=False)
        if fetched.returncode:
            detail = (fetched.stderr or fetched.stdout).strip()
            if attempt == max_attempts or not _retryable(fetched):
                raise RuntimeError(f"cannot fetch {remote}/{branch}: {detail}")
            last_push_error = detail
            _backoff(attempt, base_delay_s, max_delay_s)
            continue
        remote_tip = _git(["rev-parse", tracking]).stdout.strip()
        current_head = _git(["rev-parse", "HEAD"]).stdout.strip()

        if initial_remote is None:
            initial_remote = remote_tip
            local_ahead = _git(["rev-list", "--count", f"{tracking}..HEAD"]).stdout.strip()
            if local_ahead == "0":
                if _is_ancestor(head, remote_tip):
                    payload = {
                        **event,
                        "status": "already_published",
                        "attempts": 0,
                        "initial_head": head,
                        "remote_before": remote_tip,
                        "remote_after": remote_tip,
                    }
                    _emit(payload)
                    return payload
                raise RuntimeError("no unpublished commit exists to publish")
            merges = _git(["rev-list", "--merges", f"{tracking}..HEAD"]).stdout.strip()
            if merges:
                raise RuntimeError("refusing to publish merge commits to canonical main")

        if _is_ancestor(current_head, remote_tip):
            payload = {
                **event,
                "status": "already_published",
                "attempts": attempt - 1,
                "initial_head": head,
                "remote_before": initial_remote,
                "remote_after": remote_tip,
            }
            _emit(payload)
            return payload

        if not _is_ancestor(remote_tip, current_head):
            rebase = _git(["rebase", remote_tip], check=False)
            if rebase.returncode:
                _git(["rebase", "--abort"], check=False)
                detail = (rebase.stderr or rebase.stdout).strip()
                raise RuntimeError(f"state conflict; no commit was published: {detail}")

        pushed = _git(["push", remote, f"HEAD:refs/heads/{branch}"], check=False)
        if pushed.returncode == 0:
            final_head = _git(["rev-parse", "HEAD"]).stdout.strip()
            payload = {
                **event,
                "status": "published",
                "attempts": attempt,
                "initial_head": head,
                "remote_before": initial_remote,
                "remote_after": final_head,
            }
            _emit(payload)
            return payload

        last_push_error = (pushed.stderr or pushed.stdout).strip()
        refreshed = _git(
            ["fetch", "--no-tags", remote, f"+refs/heads/{branch}:{tracking}"],
            check=False,
        )
        if refreshed.returncode:
            detail = (refreshed.stderr or refreshed.stdout).strip()
            if attempt == max_attempts or not _retryable(refreshed):
                raise RuntimeError(f"fetch after push rejection failed: {detail}")
            last_push_error = detail
            _backoff(attempt, base_delay_s, max_delay_s)
            continue
        new_tip = _git(["rev-parse", tracking]).stdout.strip()
        current_head = _git(["rev-parse", "HEAD"]).stdout.strip()
        if _is_ancestor(current_head, new_tip):
            payload = {
                **event,
                "status": "already_published",
                "attempts": attempt,
                "initial_head": head,
                "remote_before": initial_remote,
                "remote_after": new_tip,
            }
            _emit(payload)
            return payload
        if new_tip == remote_tip and (attempt == max_attempts or not _retryable(pushed)):
            raise RuntimeError(f"push failed without a concurrent main update: {last_push_error}")

        _backoff(attempt, base_delay_s, max_delay_s)

    raise RuntimeError(
        f"contention retry budget exhausted after {max_attempts} attempts; "
        f"local commit retained; last push error: {last_push_error}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--max-attempts", type=int, default=20)
    parser.add_argument("--base-delay-seconds", "--base-delay-s", dest="base_delay_s", type=float, default=0.5)
    parser.add_argument("--max-delay-seconds", "--max-delay-s", dest="max_delay_s", type=float, default=12.0)
    args = parser.parse_args()
    try:
        publish(
            remote=args.remote,
            branch=args.branch,
            max_attempts=args.max_attempts,
            base_delay_s=args.base_delay_s,
            max_delay_s=args.max_delay_s,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit({"status": "failed", "error": str(exc)}, stream=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
