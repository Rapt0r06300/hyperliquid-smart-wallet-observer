#!/usr/bin/env python3
"""Emit the compact local Discovery V3.2 resume pack."""
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

from hl_observer.research.hypothesis_ledger import FAMILIES  # noqa: E402
from hl_observer.research.research_context import build_research_context  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auto", action="store_true", help="select the sole active economic family")
    parser.add_argument("--family", choices=sorted(FAMILIES))
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--process-memory", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--task", help="compile a bounded code context for this task")
    parser.add_argument("--context-budget", type=int, default=24_000, help="maximum context characters")
    parser.add_argument("--repo-index", type=Path, help="optional incremental repository index path")
    parser.add_argument("--changed", action="append", default=[], help="changed repository path, repeatable")
    return parser


def main() -> int:
    args = _parser().parse_args()
    family = None if args.auto or args.family is None else args.family
    try:
        context = build_research_context(
            REPO_ROOT,
            family=family,
            ledger_path=args.ledger,
            process_memory_path=args.process_memory,
        )
    except ValueError as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    if args.task:
        from hl_observer.agent_tools.efficiency.context_bundle import ContextRequest, compile_context
        from hl_observer.agent_tools.efficiency.repo_index import build_incremental_index

        index = build_incremental_index(
            REPO_ROOT,
            index_path=args.repo_index or REPO_ROOT / "runtime" / "agent_efficiency" / "repo_index.json",
        )
        context["bounded_code_context"] = compile_context(
            REPO_ROOT,
            index,
            ContextRequest(
                task=args.task,
                changed_files=tuple(args.changed),
                max_chars=max(1_000, args.context_budget),
            ),
        ).to_dict()
    encoded = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if args.out is None:
        print(encoded)
        return 0
    output = (
        args.out
        if args.out.is_absolute()
        else REPO_ROOT / "runtime/codex_research" / args.out.name
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded + "\n", encoding="utf-8")
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
