#!/usr/bin/env python3
"""Generate and rank a local semantic Discovery V3.2 candidate pool."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.research.hypothesis_ledger import FAMILIES, load_records
from hl_observer.research.process_memory import load_process_records
from hl_observer.research.semantic_discovery import (
    generate_semantic_plans,
    load_catalog,
    rank_semantic_plans,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = (
    REPO_ROOT / ".agents/skills/alina-quant-research/references/semantic-catalog-v32.json"
)
DEFAULT_LEDGER = REPO_ROOT / "runtime/codex_research/HYPOTHESIS_LEDGER.jsonl"
DEFAULT_PROCESS_MEMORY = REPO_ROOT / "runtime/codex_research/PROCESS_MEMORY.jsonl"
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
    parser.add_argument("--out", type=Path)
    return parser


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    args = _parser().parse_args()
    catalog = load_catalog(args.catalog)
    plans = generate_semantic_plans(catalog, args.family, args.pool_size, args.seed)
    ledger = load_records(args.ledger)
    process = load_process_records(args.process_memory)
    ranked = rank_semantic_plans(plans, ledger, process, args.shortlist)
    filtered = max(0, len(plans) - len(ranked))
    status = {
        "schema_version": 1,
        "family": args.family,
        "generated": len(plans),
        "shortlisted": len(ranked),
        "filtered_before_llm": filtered,
        "network_io": False,
        "certifying": False,
    }
    _atomic_json(DEFAULT_STATUS, status)
    payload = {**status, "shortlist": ranked}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if args.out is None:
        print(encoded)
        return 0
    output = (
        args.out
        if args.out.is_absolute()
        else REPO_ROOT / "runtime/codex_research" / args.out.name
    )
    _atomic_json(output, payload)
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
