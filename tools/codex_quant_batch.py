"""Run a planned batch of Alina quantitative experiments without model round-trips."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (SRC, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hl_observer.research.experiment_protocol import (  # noqa: E402
    ExperimentSpec,
    SpecValidationError,
    write_summary_atomic,
)
from tools.codex_quant_experiment import run_experiment  # noqa: E402

_BATCH_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
BatchRunner = Callable[..., dict[str, Any]]


def _validate_batch(payload: Mapping[str, Any]) -> tuple[str, list[ExperimentSpec]]:
    if not isinstance(payload, Mapping):
        raise SpecValidationError("batch spec must be a JSON object")
    if payload.get("schema_version") != 1:
        raise SpecValidationError("batch schema_version must be 1")
    batch_id = payload.get("batch_id")
    if not isinstance(batch_id, str) or not _BATCH_ID_RE.fullmatch(batch_id):
        raise SpecValidationError("batch_id must be a safe 1-80 character identifier")
    raw_experiments = payload.get("experiments")
    if not isinstance(raw_experiments, list) or not raw_experiments:
        raise SpecValidationError("experiments must be a non-empty list")
    if len(raw_experiments) > 10_000:
        raise SpecValidationError("one batch may contain at most 10000 experiments")
    specs = [ExperimentSpec.from_mapping(item) for item in raw_experiments]
    ids = [spec.experiment_id for spec in specs]
    if len(ids) != len(set(ids)):
        raise SpecValidationError("experiment_id values must be unique inside a batch")
    return batch_id, specs


def _compact_result(result: Mapping[str, Any]) -> dict[str, Any]:
    compute = result.get("compute_policy") if isinstance(result.get("compute_policy"), Mapping) else {}
    return {
        "experiment_id": result.get("experiment_id"),
        "signature": result.get("signature"),
        "verdict": result.get("verdict"),
        "cache_hit": result.get("cache_hit") is True,
        "duration_s": result.get("duration_s"),
        "best_candidate": result.get("best_candidate"),
        "compute_policy": dict(compute),
    }


def run_batch(
    payload: Mapping[str, Any],
    *,
    runtime_root: Path,
    runner: BatchRunner = run_experiment,
    current_sha: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Run all predeclared experiments locally before returning to the model.

    Experiments are intentionally sequential at this orchestration layer.  Each
    underlying experiment may already use all configured CPU workers; launching
    several such searches concurrently would usually oversubscribe the machine.
    Codex can split lighter jobs into multiple batches if local profiling proves
    parallel batches are beneficial.
    """

    batch_id, specs = _validate_batch(payload)
    if current_sha is not None:
        expected = current_sha.lower()
        stale = [spec.experiment_id for spec in specs if spec.base_sha != expected]
        if stale:
            raise SpecValidationError(
                "batch contains stale base_sha experiment(s): " + ", ".join(stale[:10])
            )

    runtime_root = Path(runtime_root)
    results: list[dict[str, Any]] = []
    for spec in specs:
        result = runner(
            spec,
            runtime_root=runtime_root,
            current_sha=current_sha,
            repo_root=repo_root,
        )
        if not isinstance(result, Mapping):
            raise SpecValidationError(
                f"experiment runner returned non-mapping result for {spec.experiment_id}"
            )
        results.append(_compact_result(result))

    summary = {
        "schema_version": 1,
        "batch_id": batch_id,
        "experiments_total": len(specs),
        "experiments_completed": len(results),
        "local_compute": True,
        "model_roundtrips_required_inside_batch": 0,
        "results": results,
    }
    path = runtime_root / "_batches" / batch_id / "BATCH_SUMMARY.json"
    write_summary_atomic(path, summary)
    summary["summary_path"] = str(path.resolve())
    return summary


def _load_batch(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecValidationError(f"cannot read batch spec: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise SpecValidationError("batch spec must be a JSON object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run multiple Alina quant experiments locally")
    parser.add_argument("batch", type=Path, help="Path to a JSON batch specification")
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path("runtime/codex_experiments"),
        help="Local experiment artifact root",
    )
    args = parser.parse_args(argv)
    try:
        summary = run_batch(_load_batch(args.batch), runtime_root=args.runtime_root)
    except SpecValidationError as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
