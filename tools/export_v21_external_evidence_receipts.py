"""Export deterministic V21 reference-architecture and recirculation receipts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.research.external_evidence_governance import (  # noqa: E402
    audit_reference_architecture_receipt,
    audit_social_novelty_receipt,
    v21_reference_and_recirculation_receipts,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("runtime/reports/v21_external_evidence_receipts.json"),
    )
    args = parser.parse_args(argv)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    receipts = v21_reference_and_recirculation_receipts()
    audits = {
        "reference_architecture": audit_reference_architecture_receipt(
            receipts["reference_architecture"]
        ),
        "social_novelty": audit_social_novelty_receipt(receipts["social_novelty"]),
    }
    payload = {"receipts": receipts, "audits": audits}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0 if all(audit["ready"] for audit in audits.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
