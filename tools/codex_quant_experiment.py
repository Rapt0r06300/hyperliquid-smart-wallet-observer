"""Run one bounded Alina SmartFlow quant experiment locally and emit a compact summary."""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
_TOOLS = _REPO_ROOT / "tools"
for _path in (_SRC, _REPO_ROOT, _TOOLS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from hl_observer.research.experiment_protocol import (  # noqa: E402
    ExperimentSpec,
    SpecValidationError,
    VERDICTS,
    load_cached_summary,
    load_spec,
    result_dir,
    write_goal_state_atomic,
    write_summary_atomic,
)

Optimizer = Callable[..., dict[str, Any]]
Evaluator = Callable[..., Mapping[str, Any]]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _git_sha(repo_root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SpecValidationError(f"cannot verify current Git SHA: {exc}") from exc
    sha = proc.stdout.strip().lower()
    if len(sha) != 40:
        raise SpecValidationError("git rev-parse did not return an exact 40-character SHA")
    return sha


def resolve_evaluator(spec: ExperimentSpec) -> Evaluator:
    module_name, callable_name = spec.evaluator.split(":", 1)
    allowed_module = (
        module_name == "hl_observer"
        or module_name.startswith("hl_observer.")
        or module_name == "tools"
        or module_name.startswith("tools.")
    )
    if not allowed_module:
        raise SpecValidationError("evaluator module is outside the project allowlist")
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise SpecValidationError(f"cannot import evaluator module {module_name}: {exc}") from exc
    evaluator = getattr(module, callable_name, None)
    if not callable(evaluator):
        raise SpecValidationError(f"evaluator callable not found: {spec.evaluator}")
    return evaluator


def _default_optimizer() -> Optimizer:
    try:
        module = importlib.import_module("tools.outils_recherche")
    except Exception as exc:
        raise SpecValidationError(f"cannot import existing research optimizer: {exc}") from exc
    optimizer = getattr(module, "optimiser", None)
    if not callable(optimizer):
        raise SpecValidationError("tools.outils_recherche.optimiser is unavailable")
    return optimizer


def _evaluator_wrapper(evaluator: Evaluator, spec: ExperimentSpec) -> Callable[..., dict[str, Any]]:
    try:
        signature = inspect.signature(evaluator)
        params = signature.parameters
        accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    except (TypeError, ValueError):
        params = {}
        accepts_kwargs = True

    context = {
        "experiment_id": spec.experiment_id,
        "signature": spec.signature(),
        "family": spec.family,
        "hypothesis_id": spec.hypothesis_id,
        "phase": spec.phase,
        "base_sha": spec.base_sha,
        "data_fingerprint": spec.data_fingerprint,
        "data_cutoff_utc": spec.data_cutoff_utc,
        "cost_model": spec.cost_model,
        "split_config": spec.split_config,
    }

    def wrapped(candidate_params: dict[str, Any], *, budget: float = 1.0) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if accepts_kwargs or "budget" in params:
            kwargs["budget"] = budget
        if accepts_kwargs or "context" in params:
            kwargs["context"] = context
        result = evaluator(candidate_params, **kwargs)
        if not isinstance(result, Mapping):
            raise TypeError("experiment evaluator must return a mapping of metrics")
        return dict(result)

    return wrapped


def _compact(value: Any, *, depth: int = 0) -> Any:
    if depth >= 5:
        return "<truncated-depth>"
    if isinstance(value, Mapping):
        items = list(value.items())
        out = {str(k): _compact(v, depth=depth + 1) for k, v in items[:30]}
        if len(items) > 30:
            out["_truncated_keys"] = len(items) - 30
        return out
    if isinstance(value, (list, tuple)):
        out = [_compact(v, depth=depth + 1) for v in value[:30]]
        if len(value) > 30:
            out.append({"_truncated_items": len(value) - 30})
        return out
    if isinstance(value, str) and len(value) > 500:
        return value[:497] + "..."
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _extract_best(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    best = raw.get("meilleur")
    if not isinstance(best, Mapping):
        return None
    params = best.get("params") if isinstance(best.get("params"), Mapping) else {}
    metrics = best.get("metriques") if isinstance(best.get("metriques"), Mapping) else {}
    extra = {k: v for k, v in best.items() if k not in {"params", "metriques"}}
    return {
        "score": raw.get("meilleur_score"),
        "params": _compact(params),
        "metrics": _compact(metrics),
        **({"extra": _compact(extra)} if extra else {}),
    }


def _suggested_verdict(
    raw: Mapping[str, Any], best: Mapping[str, Any] | None
) -> tuple[str, list[str]]:
    if not raw.get("disponible", True):
        return "BLOCKED", [str(raw.get("raison") or "optimizer unavailable")]
    if not raw.get("lance", False):
        return "BLOCKED", [str(raw.get("raison") or "optimizer did not run")]
    metrics = best.get("metrics") if isinstance(best, Mapping) else None
    if isinstance(metrics, Mapping):
        requested = metrics.get("candidate_verdict")
        if isinstance(requested, str) and requested in VERDICTS:
            reasons = metrics.get("candidate_reasons")
            if isinstance(reasons, list):
                return requested, [str(item)[:500] for item in reasons[:10]]
            return requested, ["evaluator supplied candidate_verdict"]
    completed = int(raw.get("trials_termines") or 0)
    if completed <= 0:
        return "BLOCKED", ["no completed local trials"]
    if best is None:
        return "REJECT", ["completed trials produced no candidate"]
    return "ITERATE", ["candidate exists; independent validation decision still required"]


def _forced_run_id(experiment_id: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{experiment_id}__forced_{stamp}"


def run_experiment(
    spec: ExperimentSpec,
    *,
    runtime_root: Path,
    force: bool = False,
    force_reason: str | None = None,
    optimizer: Optimizer | None = None,
    current_sha: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Execute a bounded local search and return a compact machine-readable summary."""
    runtime_root = Path(runtime_root)
    repo_root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    if force and not (force_reason and force_reason.strip()):
        raise SpecValidationError("force reason is required for a forced rerun")

    actual_sha = (current_sha or _git_sha(repo_root)).lower()
    if actual_sha != spec.base_sha:
        raise SpecValidationError(
            f"base_sha mismatch: spec={spec.base_sha} current={actual_sha}; refuse stale experiment"
        )

    signature = spec.signature()
    if not force:
        cached = load_cached_summary(runtime_root, signature)
        if cached is not None:
            returned = dict(cached)
            returned["cache_hit"] = True
            return returned

    evaluator = resolve_evaluator(spec)
    run_optimizer = optimizer or _default_optimizer()
    run_id = _forced_run_id(spec.experiment_id) if force else spec.experiment_id
    run_dir = result_dir(runtime_root, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    spec_path = run_dir / "EXPERIMENT_SPEC.json"
    detail_path = run_dir / "OPTIMIZER_RESULT.json"
    summary_path = run_dir / "RESULT_SUMMARY.json"
    storage_dir = run_dir / "optimizer_state"

    write_summary_atomic(spec_path, spec.as_mapping())
    started_iso = _utc_now()
    t0 = time.monotonic()
    wrapped = _evaluator_wrapper(evaluator, spec)
    raw = run_optimizer(
        wrapped,
        spec.search_space,
        outil=spec.engine,
        n_trials=int(spec.budget["max_trials"]),
        storage_dir=storage_dir,
        seed=spec.seed,
    )
    duration_s = round(time.monotonic() - t0, 6)
    if not isinstance(raw, Mapping):
        raise SpecValidationError("optimizer returned a non-mapping result")
    raw_dict = dict(raw)
    write_summary_atomic(detail_path, raw_dict)

    best = _extract_best(raw_dict)
    verdict, reasons = _suggested_verdict(raw_dict, best)
    trials = {
        "proposed": int(raw_dict.get("trials_proposes") or 0),
        "completed": int(raw_dict.get("trials_termines") or 0),
        "pruned": int(raw_dict.get("trials_prunes") or 0),
        "failed": int(raw_dict.get("trials_echoues") or 0),
    }
    summary: dict[str, Any] = {
        "schema_version": 1,
        "experiment_id": spec.experiment_id,
        "run_id": run_id,
        "signature": signature,
        "family": spec.family,
        "hypothesis_id": spec.hypothesis_id,
        "phase": spec.phase,
        "base_sha": spec.base_sha,
        "data_fingerprint": spec.data_fingerprint,
        "data_cutoff_utc": spec.data_cutoff_utc,
        "engine": spec.engine,
        "seed": spec.seed,
        "started_at_utc": started_iso,
        "completed_at_utc": _utc_now(),
        "duration_s": duration_s,
        "budget": _compact(spec.budget),
        "wall_budget_enforced": False,
        "trials": trials,
        "best_candidate": best,
        "verdict": verdict,
        "reasons": reasons,
        "cache_hit": False,
        "forced": bool(force),
        "force_reason": force_reason.strip() if force_reason else None,
        "fresh_evidence_claim": False,
        "artifacts": {
            "spec": str(spec_path.resolve()),
            "optimizer_result": str(detail_path.resolve()),
            "summary": str(summary_path.resolve()),
            "optimizer_state": str(storage_dir.resolve()),
        },
    }
    write_summary_atomic(summary_path, summary)
    cache_path = runtime_root / "_cache" / f"{signature}.json"
    if not force:
        write_summary_atomic(cache_path, summary)

    goal_state = {
        "schema_version": 1,
        "base_sha": spec.base_sha,
        "family": spec.family,
        "hypothesis_id": spec.hypothesis_id,
        "phase": spec.phase,
        "data_cutoff_utc": spec.data_cutoff_utc,
        "last_result_signature": signature,
        "last_verdict": verdict,
        "last_summary": str(summary_path.resolve()),
        "next_action": "review_result_summary",
        "updated_at_utc": summary["completed_at_utc"],
    }
    write_goal_state_atomic(runtime_root.parent / "codex_goal_state.json", goal_state)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a bounded local Alina quant experiment")
    parser.add_argument("spec", type=Path, help="Path to EXPERIMENT_SPEC.json")
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path("runtime/codex_experiments"),
        help="Local artifact root",
    )
    parser.add_argument(
        "--force", action="store_true", help="Rerun an already cached scientific signature"
    )
    parser.add_argument("--reason", help="Required justification when --force is used")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        spec = load_spec(args.spec)
        summary = run_experiment(
            spec,
            runtime_root=args.runtime_root,
            force=args.force,
            force_reason=args.reason,
        )
    except SpecValidationError as exc:
        print(
            json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
