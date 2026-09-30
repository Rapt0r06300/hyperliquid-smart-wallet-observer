from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.datasets.connection_audit import write_connection_audit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audite le raccordement d'un workspace FULL/COLD au projet principal. "
            "Distingue le câblage technique des preuves produites par de vrais runs locaux."
        )
    )
    parser.add_argument("--root", required=True, help="Workspace FULL/COLD à auditer.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"DATASET_CONNECTION_NO_GO: workspace absent: {root}")
        return 2
    try:
        json_path, md_path, payload = write_connection_audit(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"DATASET_CONNECTION_NO_GO: {type(exc).__name__}: {exc}")
        return 2
    print(
        json.dumps(
            {
                "wiring_status": payload.get("wiring_status"),
                "run_evidence_status": payload.get("run_evidence_status"),
                "available_groups": payload.get("available_groups", []),
                "unhandled_groups": payload.get("unhandled_groups", []),
                "pending_run_evidence_groups": payload.get("pending_run_evidence_groups", []),
                "report_json": str(json_path),
                "report_markdown": str(md_path),
                "paper_read_only": True,
                "real_execution": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    if payload.get("wiring_status") == "NO_PROVENANCE":
        return 2
    if payload.get("unhandled_groups"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
