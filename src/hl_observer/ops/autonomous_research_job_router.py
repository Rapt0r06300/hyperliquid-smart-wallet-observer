"""Pure autonomous-job router for active-family FULL/COLD economic suites."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from hl_observer.ops import autonomous_research_job as canonical_job
from hl_observer.ops.family_economic_job import (
    FAMILY_ECONOMIC_SUITES,
    execute_family_job,
    validate_family_request,
)


def allowed_economic_suites() -> frozenset[str]:
    return frozenset(canonical_job.ECONOMIC_SUITES) | FAMILY_ECONOMIC_SUITES


def validate_request(raw):
    suite = str(raw.get("suite") or "").strip()
    mode = str(raw.get("mode") or "").strip()
    if mode == "economic" and suite in FAMILY_ECONOMIC_SUITES:
        return validate_family_request(raw)
    return canonical_job.validate_request(raw)


def main(argv: Iterable[str] | None = None) -> int:
    args = canonical_job.build_parser().parse_args(list(argv) if argv is not None else None)
    request_path = Path(args.request)
    try:
        raw = canonical_job._load_request(request_path)
        suite = str(raw.get("suite") or "").strip()
        mode = str(raw.get("mode") or "").strip()
        if mode == "economic" and suite in FAMILY_ECONOMIC_SUITES:
            return execute_family_job(
                request_path,
                project_root=Path(args.project_root),
                lab_root=Path(args.lab_root),
                result_dir=Path(args.result_dir),
                force=bool(args.force),
            )
        return canonical_job.execute_job(
            request_path,
            project_root=Path(args.project_root),
            lab_root=Path(args.lab_root),
            result_dir=Path(args.result_dir),
            force=bool(args.force),
        )
    except (ValueError, RuntimeError, OSError, canonical_job.json.JSONDecodeError) as exc:
        print(f"ALINA_AUTONOMOUS_RESEARCH_ROUTER_NO_GO: {type(exc).__name__}: {exc}", flush=True)
        return 20


__all__ = ["FAMILY_ECONOMIC_SUITES", "allowed_economic_suites", "main", "validate_request"]


if __name__ == "__main__":
    raise SystemExit(main())
