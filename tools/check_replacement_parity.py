"""Validate every configured replacement/parity capability matrix."""

from __future__ import annotations

import argparse
from pathlib import Path

from hl_observer.alerts.replacement_parity import load_replacement_assessment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("config/alerts"),
    )
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    config_root = args.root if args.root.is_absolute() else root / args.root
    paths = sorted(config_root.glob("*.json"))
    if not paths:
        raise SystemExit("REPLACEMENT_PARITY_REFUSED no assessment files")
    for path in paths:
        assessment = load_replacement_assessment(path)
        print(
            "REPLACEMENT_PARITY_OK "
            f"subject={assessment['subject']} "
            f"verdict={assessment['verdict']} "
            f"hash={assessment['assessment_hash']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
