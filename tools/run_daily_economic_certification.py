"""Run the strict +4 USD/day per-family paper certification."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.ops.daily_economic_certification import certify_daily_workspace  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Certify Alina SmartFlow at +4 USD net/day/family")
    parser.add_argument("workspace", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    result = certify_daily_workspace(args.workspace)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result.get("all_families_certified") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
