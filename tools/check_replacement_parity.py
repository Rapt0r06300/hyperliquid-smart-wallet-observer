"""Validate every configured replacement/parity capability matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.alerts.replacement_parity import (
    PARITY_SCHEMA,
    load_replacement_assessment,
)


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
    paths = []
    for candidate in sorted(config_root.glob("*.json")):
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("schema_version") == PARITY_SCHEMA:
            paths.append(candidate)
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
