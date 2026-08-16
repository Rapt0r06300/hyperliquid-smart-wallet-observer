from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.datasets.experiment_contract_verifier import write_contract_verification


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Vérifie le contrat courant contre le plan, les fichiers Research Lab et les schémas SQLite, "
            "sans lire les lignes économiques."
        )
    )
    parser.add_argument("--root", required=True, help="Workspace FULL/COLD reconstruit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    try:
        json_path, md_path, payload = write_contract_verification(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"DATASET_CONTRACT_VERIFY_NO_GO: {type(exc).__name__}: {exc}")
        return 2

    print(
        json.dumps(
            {
                "status": payload.get("status"),
                "contract_digest_ok": payload.get("contract_digest_ok"),
                "experiment_link_ok": payload.get("experiment_link_ok"),
                "declared_source_count": payload.get("declared_source_count", 0),
                "verified_source_count": payload.get("verified_source_count", 0),
                "errors": payload.get("errors", []),
                "warnings": payload.get("warnings", []),
                "report_json": str(json_path),
                "report_markdown": str(md_path),
                "row_data_read": False,
                "read_only": True,
                "network_used": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if payload.get("status") == "READY" else 4


if __name__ == "__main__":
    raise SystemExit(main())
