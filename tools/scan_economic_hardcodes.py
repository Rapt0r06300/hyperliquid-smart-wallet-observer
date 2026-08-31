"""Generate a review-only report of economic numeric literals."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.economics.hardcode_scanner import (  # noqa: E402
    DEFAULT_ECONOMIC_PATHS,
    scan_economic_paths,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scanne les littéraux économiques sans modifier le code.",
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--path", action="append", dest="paths")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    root = args.root.resolve()
    report = scan_economic_paths(root, args.paths or DEFAULT_ECONOMIC_PATHS)
    payload = json.dumps(report, indent=2, ensure_ascii=True, sort_keys=True) + "\n"
    if args.output is not None:
        output = args.output
        if not output.is_absolute():
            output = root / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
        print(output)
    else:
        print(payload, end="")
    return 2 if report["parse_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
