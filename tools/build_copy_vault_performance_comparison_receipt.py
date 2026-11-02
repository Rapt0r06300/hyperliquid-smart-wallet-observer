#!/usr/bin/env python3
"""Build a fail-closed H-T102 performance comparison receipt.

The benchmark compares an exact historical version with the current HEAD on
the repository's real catalog.  It never invents a gain: a receipt is
``NOT_PROVEN`` unless every run completes, both versions produce the same
policy result, the input catalog hashes match, and the challenger is at least
five percent faster at the median.  The benchmark is read-only apart from the
explicit output receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "hypersmart.copy_vault_performance_comparison_receipt.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ROOT_ASSIGNMENT = "root = Path(__file__).resolve().parents[1]"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _head_sha(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    value = result.stdout.strip().lower()
    if result.returncode != 0 or not _SHA_RE.fullmatch(value):
        raise RuntimeError("EXACT_HEAD_UNAVAILABLE")
    return value


def _git_file_at_ref(repo_root: Path, ref: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{ref}:{relative_path}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"BASELINE_SOURCE_UNAVAILABLE:{detail}")
    return result.stdout


def _write_baseline_script(source: bytes, repo_root: Path) -> tuple[Path, str]:
    """Write an isolated baseline copy while binding it to the same repo.

    The historical script resolves its root from ``__file__``.  Replacing only
    that path expression lets it run against the current immutable catalog
    without changing its behavior or writing into the repository.
    """

    text = source.decode("utf-8")
    replacement = f"root = Path({str(repo_root)!r})"
    if text.count(_ROOT_ASSIGNMENT) != 1:
        raise RuntimeError("BASELINE_ROOT_BINDING_UNEXPECTED")
    bound = text.replace(_ROOT_ASSIGNMENT, replacement, 1)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".py", prefix="copy-vault-baseline-", delete=False
    )
    try:
        handle.write(bound)
        handle.flush()
    finally:
        handle.close()
    return Path(handle.name), _sha256_bytes(source)


def _run_trials(
    script: Path,
    *,
    repo_root: Path,
    arguments: list[str],
    trials: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(repo_root), existing_pythonpath) if value
    )
    for index in range(trials):
        started = time.perf_counter_ns()
        try:
            result = subprocess.run(
                [sys.executable, str(script), *arguments],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=environment,
            )
            elapsed_ns = time.perf_counter_ns() - started
            runs.append({
                "trial": index + 1,
                "returncode": result.returncode,
                "timed_out": False,
                "elapsed_ns": elapsed_ns,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "stdout_sha256": _sha256_bytes(result.stdout.encode("utf-8")),
                "stderr_sha256": _sha256_bytes(result.stderr.encode("utf-8")),
            })
        except subprocess.TimeoutExpired as exc:
            elapsed_ns = time.perf_counter_ns() - started
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            runs.append({
                "trial": index + 1,
                "returncode": None,
                "timed_out": True,
                "elapsed_ns": elapsed_ns,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_sha256": _sha256_bytes(stdout.encode("utf-8")),
                "stderr_sha256": _sha256_bytes(stderr.encode("utf-8")),
            })
            break
    return {
        "runs": runs,
        "median_elapsed_ns": int(statistics.median(run["elapsed_ns"] for run in runs)),
        "completed": all(run["returncode"] == 0 for run in runs),
        "stdout_values": [run["stdout"] for run in runs],
        "stderr_values": [run["stderr"] for run in runs],
    }


def build_receipt(
    benchmark: Mapping[str, Any],
    *,
    head_sha: str,
    baseline_ref: str,
    baseline_source_sha256: str,
    dataset_hashes: Mapping[str, str],
    source_path: str,
    trials: int,
) -> dict[str, Any]:
    """Convert measured benchmark output into a conservative evidence receipt."""

    if not _SHA_RE.fullmatch(head_sha):
        raise ValueError("head_sha must be a full lowercase commit SHA")
    if not _SHA256_RE.fullmatch(baseline_source_sha256):
        raise ValueError("baseline_source_sha256 must be a SHA-256 digest")
    if not baseline_ref.strip():
        raise ValueError("baseline_ref must be non-empty")
    if trials < 2:
        raise ValueError("at least two trials are required")
    if not dataset_hashes or any(not _SHA256_RE.fullmatch(value) for value in dataset_hashes.values()):
        raise ValueError("dataset hashes must be explicit SHA-256 digests")

    baseline = benchmark.get("baseline")
    challenger = benchmark.get("challenger")
    if not isinstance(baseline, Mapping) or not isinstance(challenger, Mapping):
        raise ValueError("benchmark arms must be objects")
    same_dataset = benchmark.get("same_dataset") is True
    same_args = benchmark.get("same_args") is True
    baseline_completed = baseline.get("completed") is True
    challenger_completed = challenger.get("completed") is True
    baseline_outputs = baseline.get("stdout_values")
    challenger_outputs = challenger.get("stdout_values")
    deterministic = (
        isinstance(baseline_outputs, list)
        and isinstance(challenger_outputs, list)
        and len(set(baseline_outputs)) == 1
        and len(set(challenger_outputs)) == 1
    )
    semantic_equivalence = (
        deterministic
        and baseline_outputs[0] == challenger_outputs[0]
        and baseline.get("stderr_values") == challenger.get("stderr_values")
    )
    baseline_median = baseline.get("median_elapsed_ns")
    challenger_median = challenger.get("median_elapsed_ns")
    medians_valid = all(
        isinstance(value, int) and value > 0
        for value in (baseline_median, challenger_median)
    )
    gain_reproducible = bool(
        medians_valid
        and challenger_median <= baseline_median * 0.95
    )
    all_completed = baseline_completed and challenger_completed
    claims = {
        "gain_reproducible": gain_reproducible,
        "semantic_equivalence": semantic_equivalence,
        "same_dataset": same_dataset,
        "same_trials": (
            len(baseline.get("runs", [])) == trials
            and len(challenger.get("runs", [])) == trials
            and same_args
        ),
        "determinism_preserved": deterministic,
        "coverage_preserved": semantic_equivalence,
        "data_count_preserved": semantic_equivalence,
        "trial_count_preserved": (
            len(baseline.get("runs", [])) == len(challenger.get("runs", [])) == trials
        ),
        "costs_preserved": same_args,
    }
    proven = all_completed and all(claims.values())
    delta_ns = (
        baseline_median - challenger_median
        if medians_valid else None
    )
    context = {
        "baseline_ref": baseline_ref,
        "baseline_source_sha256": baseline_source_sha256,
        "dataset_hashes": dict(dataset_hashes),
        "source_path": source_path,
        "trials": trials,
        "arguments": list(benchmark.get("arguments", [])),
    }
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": "performance_comparison",
        "status": "COMPLETED" if all_completed else "NOT_PROVEN",
        "evidence_status": "VERIFIED" if proven else "NOT_PROVEN",
        "head_sha": head_sha,
        "paper_read_only": True,
        "real_execution": False,
        "full_dataset_certified": False,
        "comparison_context_sha256": _canonical_sha256(context),
        "delta_usd_per_active_day": "NOT_MEASURED: performance-only comparison",
        "delta_runtime_ns_per_run": delta_ns,
        "threshold": "challenger median <= 95% of baseline median",
        "claims": claims,
        "dataset_hashes": dict(dataset_hashes),
        "baseline": {
            "receipt_sha256": _canonical_sha256(dict(baseline)),
            "median_elapsed_ns": baseline_median,
            "runs": baseline.get("runs", []),
        },
        "challenger": {
            "receipt_sha256": _canonical_sha256(dict(challenger)),
            "median_elapsed_ns": challenger_median,
            "runs": challenger.get("runs", []),
        },
        "source": {
            "path": source_path,
            "baseline_ref": baseline_ref,
            "baseline_source_sha256": baseline_source_sha256,
        },
        "missing_evidence": sorted(key for key, value in claims.items() if value is not True),
        "next_safe_action": (
            "Attach this receipt to H-T102 only when evidence_status=VERIFIED; "
            "otherwise keep Testing and investigate the explicit missing claims."
        ),
    }
    payload["receipt_sha256"] = _canonical_sha256(payload)
    return payload


def _dataset_hashes(repo_root: Path) -> dict[str, str]:
    paths = {
        "index": repo_root / "catalog" / "DATA_INDEX.json",
        "catalog": repo_root / "catalog" / "DATA_CATALOG.json",
        "registry": repo_root / "catalog" / "DATA_QUALITY_REGISTRY.json",
    }
    return {name: _sha256_file(path) for name, path in paths.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--script", default="tools/check_dataset_quality.py")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--catalog-only", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    script_relative = Path(args.script)
    current_script = repo_root / script_relative
    if not current_script.is_file():
        parser.error(f"current script not found: {current_script}")
    if args.trials < 2:
        parser.error("--trials must be at least 2")
    try:
        head_sha = _head_sha(repo_root)
        current_source = current_script.read_bytes()
        expected_current_source = _git_file_at_ref(repo_root, "HEAD", script_relative.as_posix())
        if current_source != expected_current_source:
            raise RuntimeError("CURRENT_SCRIPT_DIRTY_OR_NOT_HEAD")
        baseline_source = _git_file_at_ref(repo_root, args.baseline_ref, script_relative.as_posix())
        baseline_script, baseline_source_sha256 = _write_baseline_script(baseline_source, repo_root)
        arguments = ["--catalog-only"] if args.catalog_only else []
        try:
            baseline = _run_trials(
                baseline_script,
                repo_root=repo_root,
                arguments=arguments,
                trials=args.trials,
                timeout_seconds=args.timeout_seconds,
            )
        finally:
            baseline_script.unlink(missing_ok=True)
        challenger = _run_trials(
            current_script,
            repo_root=repo_root,
            arguments=arguments,
            trials=args.trials,
            timeout_seconds=args.timeout_seconds,
        )
        benchmark = {
            "baseline": baseline,
            "challenger": challenger,
            "same_dataset": True,
            "same_args": True,
            "arguments": arguments,
        }
        receipt = build_receipt(
            benchmark,
            head_sha=head_sha,
            baseline_ref=args.baseline_ref,
            baseline_source_sha256=baseline_source_sha256,
            dataset_hashes=_dataset_hashes(repo_root),
            source_path=str(script_relative),
            trials=args.trials,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (OSError, RuntimeError, TypeError, ValueError, subprocess.TimeoutExpired) as exc:
        parser.error(str(exc))
        return 1
    print(json.dumps({
        "output": str(args.output),
        "evidence_status": receipt["evidence_status"],
        "head_sha": receipt["head_sha"],
        "baseline_ref": args.baseline_ref,
        "delta_runtime_ns_per_run": receipt["delta_runtime_ns_per_run"],
    }, sort_keys=True))
    return 0 if receipt["evidence_status"] == "VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
