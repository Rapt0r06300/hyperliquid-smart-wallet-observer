from __future__ import annotations

import argparse
import math
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass

GIT_COMMAND_TIMEOUT_SECONDS = 90.0


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str


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
    "returned error: 500",
    "returned error: 502",
    "returned error: 503",
    "returned error: 504",
    "bad gateway",
    "service unavailable",
    "internal server error",
)


def _git(*args: str) -> GitResult:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "Never"
    try:
        completed = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
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
        timeout_message = f"git command timed out after {GIT_COMMAND_TIMEOUT_SECONDS:g}s"
        return GitResult(124, stdout, f"{timeout_message}: {stderr}" if stderr else timeout_message)
    return GitResult(completed.returncode, completed.stdout.strip(), completed.stderr.strip())


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    result = _git("merge-base", "--is-ancestor", ancestor, descendant)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr or result.stdout or "git merge-base failed")
    return result.returncode == 0


def _emit(result: GitResult) -> None:
    if result.stdout:
        print(result.stdout, flush=True)
    if result.stderr:
        print(result.stderr, file=sys.stderr, flush=True)


def _retryable(result: GitResult) -> bool:
    message = f"{result.stdout}\n{result.stderr}".casefold()
    return any(marker in message for marker in RETRYABLE)


def _fetch(remote: str, branch: str) -> GitResult:
    tracking_ref = f"refs/remotes/{remote}/{branch}"
    return _git("fetch", "--no-tags", remote, f"refs/heads/{branch}:{tracking_ref}")


def _validate_checkout(remote: str, branch: str) -> None:
    result = _git("check-ref-format", f"refs/heads/{branch}")
    if result.returncode:
        raise ValueError(f"invalid target branch {branch!r}")
    if _git("remote", "get-url", remote).returncode:
        raise ValueError(f"git remote {remote!r} is not configured")
    for args, name in (
        (("diff", "--quiet"), "unstaged"),
        (("diff", "--cached", "--quiet"), "staged"),
    ):
        result = _git(*args)
        if result.returncode:
            raise ValueError(f"refusing to publish with uncommitted {name} changes")


def publish(remote: str, branch: str, max_attempts: int, base_delay: float, max_delay: float) -> int:
    _validate_checkout(remote, branch)
    target_ref = f"refs/remotes/{remote}/{branch}"
    push_ref = f"refs/heads/{branch}"
    initial_head = _git("rev-parse", "HEAD^{commit}")
    if initial_head.returncode:
        raise RuntimeError(initial_head.stderr or "cannot resolve HEAD")

    rng = random.SystemRandom()
    for attempt in range(1, max_attempts + 1):
        print(f"[main-publish] attempt {attempt}/{max_attempts}: fetch latest {remote}/{branch}", flush=True)
        fetched = _fetch(remote, branch)
        if fetched.returncode:
            _emit(fetched)
            if attempt == max_attempts or not _retryable(fetched):
                return fetched.returncode or 1
        else:
            target = _git("rev-parse", f"{target_ref}^{{commit}}")
            if target.returncode:
                _emit(target)
                return target.returncode or 1

            current_head = _git("rev-parse", "HEAD^{commit}")
            if current_head.returncode:
                _emit(current_head)
                return current_head.returncode or 1
            if _is_ancestor(current_head.stdout, target.stdout):
                print("[main-publish] this commit is already present on the target branch", flush=True)
                return 0

            rebased = _git("rebase", target_ref)
            if rebased.returncode:
                _emit(rebased)
                aborted = _git("rebase", "--abort")
                if aborted.returncode and aborted.stderr:
                    print(aborted.stderr, file=sys.stderr, flush=True)
                print(
                    "[main-publish] rebase conflict; publication stopped without resolving or discarding files",
                    file=sys.stderr,
                    flush=True,
                )
                return rebased.returncode or 1
            _emit(rebased)

            rebased_head = _git("rev-parse", "HEAD^{commit}")
            if rebased_head.returncode:
                _emit(rebased_head)
                return rebased_head.returncode or 1
            if _is_ancestor(rebased_head.stdout, target.stdout):
                print("[main-publish] equivalent change is already present on the target branch", flush=True)
                return 0

            print(f"[main-publish] atomic fast-forward update {remote}/{branch}", flush=True)
            pushed = _git("push", remote, f"HEAD:{push_ref}")
            if pushed.returncode == 0:
                _emit(pushed)
                print(f"[main-publish] published {rebased_head.stdout}", flush=True)
                return 0
            _emit(pushed)
            if attempt == max_attempts or not _retryable(pushed):
                print(
                    "[main-publish] push failed for a non-retryable reason; no force update was attempted",
                    file=sys.stderr,
                    flush=True,
                )
                return pushed.returncode or 1

        if attempt < max_attempts:
            delay_cap = min(max_delay, base_delay * (2 ** min(attempt - 1, 30)))
            delay = rng.uniform(delay_cap / 2, delay_cap) if delay_cap else 0.0
            print(f"[main-publish] target moved or transport failed; retrying in {delay:.2f}s", flush=True)
            time.sleep(delay)

    local_head = _git("rev-parse", "HEAD^{commit}")
    local_sha = local_head.stdout if local_head.returncode == 0 else initial_head.stdout
    print(
        f"[main-publish] exhausted {max_attempts} attempts; local commit {local_sha} remains unpushed; no force update was attempted",
        file=sys.stderr,
        flush=True,
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish already-committed changes to a branch with bounded, non-destructive CAS retries."
    )
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--max-attempts", type=int, default=30)
    parser.add_argument("--base-delay-seconds", type=float, default=0.5)
    parser.add_argument("--max-delay-seconds", type=float, default=12.0)
    args = parser.parse_args()
    if args.max_attempts < 1:
        parser.error("--max-attempts must be positive")
    if not math.isfinite(args.base_delay_seconds) or args.base_delay_seconds < 0:
        parser.error("--base-delay-seconds must be finite and nonnegative")
    if not math.isfinite(args.max_delay_seconds) or args.max_delay_seconds < args.base_delay_seconds:
        parser.error("--max-delay-seconds must be finite and at least the base delay")
    try:
        return publish(
            args.remote,
            args.branch,
            args.max_attempts,
            args.base_delay_seconds,
            args.max_delay_seconds,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[main-publish] {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
