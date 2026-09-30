#!/usr/bin/env python3
"""Generate and rank a local semantic Discovery V3.2 candidate pool."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = REPO_ROOT / "src"
for _path in (_SRC, REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from hl_observer.research.hypothesis_ledger import FAMILIES, load_records  # noqa: E402
from hl_observer.research.process_memory import (  # noqa: E402
    combine_process_records,
    load_process_records,
)
from hl_observer.research.research_context import read_repository_head  # noqa: E402
from hl_observer.research.semantic_discovery import (  # noqa: E402
    generate_semantic_plans,
    load_catalog,
    rank_semantic_plans,
)

DEFAULT_CATALOG = (
    REPO_ROOT / ".agents/skills/alina-quant-research/references/semantic-catalog-v32.json"
)
DEFAULT_LEDGER = REPO_ROOT / "runtime/codex_research/HYPOTHESIS_LEDGER.jsonl"
DEFAULT_PROCESS_MEMORY = REPO_ROOT / "runtime/codex_research/PROCESS_MEMORY.jsonl"
DEFAULT_HISTORICAL_PROCESS_MEMORY = REPO_ROOT / "docs/quant/HISTORICAL_EXPERIMENT_MEMORY.jsonl"
DEFAULT_STATUS = REPO_ROOT / "runtime/codex_research/SEMANTIC_DISCOVERY_STATUS.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=sorted(FAMILIES), required=True)
    parser.add_argument("--pool-size", type=int, default=2000)
    parser.add_argument("--shortlist", type=int, default=12)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--process-memory", type=Path, default=DEFAULT_PROCESS_MEMORY)
    parser.add_argument(
        "--historical-process-memory",
        type=Path,
        default=DEFAULT_HISTORICAL_PROCESS_MEMORY,
        help="stable historical process-memory seed loaded before runtime memory",
    )
    parser.add_argument(
        "--retest-evidence",
        action="append",
        default=[],
        help="verified evidence satisfying a documented retest condition; repeatable",
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--status-out",
        type=Path,
        default=DEFAULT_STATUS,
        help="machine-readable search-accounting sidecar",
    )
    return parser


def _output_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / "runtime/codex_research" / path.name


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_aggregate_status(path: Path, head: str) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 2
        or payload.get("head") != head
        or not isinstance(payload.get("families"), dict)
    ):
        return {}
    output: dict[str, dict] = {}
    for family, value in payload["families"].items():
        if family in FAMILIES and isinstance(value, dict) and value.get("family") == family:
            output[family] = value
    return output


def main() -> int:
    args = _parser().parse_args()
    catalog = load_catalog(args.catalog)
    plans = generate_semantic_plans(catalog, args.family, args.pool_size, args.seed)
    if args.retest_evidence:
        plans = [{**plan, "retest_evidence": list(args.retest_evidence)} for plan in plans]
    ledger = load_records(args.ledger)
    historical = load_process_records(args.historical_process_memory)
    runtime = load_process_records(args.process_memory)
    process = combine_process_records(historical, runtime)
    ranked = rank_semantic_plans(plans, ledger, process, args.shortlist)
    filtered = max(0, len(plans) - len(ranked))
    head = read_repository_head(REPO_ROOT)
    family_status = {
        "family": args.family,
        "generated": len(plans),
        "shortlisted": len(ranked),
        "filtered_before_llm": filtered,
        "historical_memory_records": len(historical),
        "runtime_memory_records": len(runtime),
        "network_io": False,
        "certifying": False,
    }
    status_path = _output_path(args.status_out)
    families = _load_aggregate_status(status_path, head)
    families[args.family] = family_status
    _atomic_json(
        status_path,
        {
            "schema_version": 2,
            "head": head,
            "families": families,
        },
    )
    payload = {
        "schema_version": 2,
        "head": head,
        **family_status,
        "shortlist": ranked,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if args.out is None:
        print(encoded)
        return 0
    output = _output_path(args.out)
    _atomic_json(output, payload)
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
