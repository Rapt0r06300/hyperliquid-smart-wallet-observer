"""Pure autonomous-job router for active-family FULL/COLD economic suites."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping

from hl_observer.ops import autonomous_research_job as canonical_job
from hl_observer.ops.family_economic_job import (
    FAMILY_ECONOMIC_SUITES,
    execute_family_job,
    validate_family_request,
)
from hl_observer.ops.lead_lag_causal_gap_diagnostic import (
    write_lead_lag_causal_gap_diagnostic,
)


def allowed_economic_suites() -> frozenset[str]:
    return frozenset(canonical_job.ECONOMIC_SUITES) | FAMILY_ECONOMIC_SUITES


def validate_request(raw):
    suite = str(raw.get("suite") or "").strip()
    mode = str(raw.get("mode") or "").strip()
    if mode == "economic" and suite in FAMILY_ECONOMIC_SUITES:
        return validate_family_request(raw)
    return canonical_job.validate_request(raw)


def _print_lead_lag_diagnostic(payload: Mapping[str, object]) -> None:
    availability = payload.get("causal_book_availability")
    if not isinstance(availability, Mapping):
        availability = {}
    counts = availability.get("classification_counts")
    print(
        "LEAD_LAG_CAUSAL_GAP_DIAGNOSTIC "
        f"diagnostic_bps={payload.get('diagnostic_threshold_bps')} "
        f"economic_bps={payload.get('economic_threshold_bps')} "
        f"economic_parameters_modified={payload.get('economic_parameters_modified')} "
        f"events={availability.get('event_count')} "
        f"root_cause={availability.get('root_cause')} "
        f"counts={canonical_job.json.dumps(counts, sort_keys=True)}",
        flush=True,
    )
    events = availability.get("events")
    if not isinstance(events, list):
        return
    for index, row in enumerate(events, start=1):
        if not isinstance(row, Mapping):
            continue
        print(
            "LEAD_LAG_CAUSAL_GAP_EVENT "
            f"index={index} ts_ms={row.get('event_ts_ms')} "
            f"class={row.get('classification')} "
            f"next_delay_ms={row.get('next_book_delay_ms')} "
            f"gap_delta={row.get('gap_count_delta')} "
            f"reconnect_delta={row.get('reconnect_count_delta')} "
            f"explicit_gap={row.get('explicit_collector_gap')}",
            flush=True,
        )


def _run_family_postprocessing(*, suite: str, result_dir: Path) -> None:
    """Add family-specific evidence without changing the economic strategy.

    Lead-Lag's 8 bps pass is deliberately a data-quality diagnostic executed
    after the economic family pipeline.  The economic replay remains frozen at
    its own 20 bps threshold; this post-processing can only explain missing
    causal books and can never create an eligible trade.
    """

    if suite != "lead-lag-full":
        return
    result_path = result_dir / "JOB_RESULT.json"
    if not result_path.is_file():
        raise RuntimeError("Lead-Lag family result missing before causal-gap diagnostic")
    payload = canonical_job.json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("status") != "SUCCESS":
        raise RuntimeError("Lead-Lag causal-gap diagnostic requires successful family pipeline")
    workspace_raw = payload.get("workspace")
    if not workspace_raw:
        raise RuntimeError("Lead-Lag family result has no workspace for causal-gap diagnostic")
    workspace = Path(str(workspace_raw)).resolve()
    if not workspace.is_dir():
        raise RuntimeError(f"Lead-Lag diagnostic workspace missing: {workspace}")
    json_path, markdown_path, diagnostic = write_lead_lag_causal_gap_diagnostic(
        workspace,
        output_dir=result_dir,
    )
    _print_lead_lag_diagnostic(diagnostic)
    print(
        "LEAD_LAG_CAUSAL_GAP_FILES "
        f"json={json_path.name} markdown={markdown_path.name} raw_data_uploaded=False",
        flush=True,
    )


def main(argv: Iterable[str] | None = None) -> int:
    args = canonical_job.build_parser().parse_args(list(argv) if argv is not None else None)
    request_path = Path(args.request)
    try:
        raw = canonical_job._load_request(request_path)
        suite = str(raw.get("suite") or "").strip()
        mode = str(raw.get("mode") or "").strip()
        if mode == "economic" and suite in FAMILY_ECONOMIC_SUITES:
            result_dir = Path(args.result_dir)
            rc = execute_family_job(
                request_path,
                project_root=Path(args.project_root),
                lab_root=Path(args.lab_root),
                result_dir=result_dir,
                force=bool(args.force),
            )
            if rc == 0:
                _run_family_postprocessing(suite=suite, result_dir=result_dir.resolve())
            return rc
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


__all__ = [
    "FAMILY_ECONOMIC_SUITES",
    "_print_lead_lag_diagnostic",
    "_run_family_postprocessing",
    "allowed_economic_suites",
    "main",
    "validate_request",
]


if __name__ == "__main__":
    raise SystemExit(main())
