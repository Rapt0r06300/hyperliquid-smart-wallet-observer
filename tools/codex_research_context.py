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
    parser.add_argument("--auto", action="store_true", help="auto-select the underworked family")
    parser.add_argument("--family", choices=sorted(FAMILIES))
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--process-memory", type=Path)
    parser.add_argument("--out", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    family = None if args.auto or args.family is None else args.family
    context = build_research_context(
        REPO_ROOT,
        family=family,
        ledger_path=args.ledger,
        process_memory_path=args.process_memory,
    )
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
