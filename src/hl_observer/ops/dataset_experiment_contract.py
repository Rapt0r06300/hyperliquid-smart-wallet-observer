from __future__ import annotations

import json
from pathlib import Path

from hl_observer.datasets.experiment_contract import write_replay_input_contract


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Transforme CURRENT_EXPERIMENT_PLAN en contrat d'entrée de replay local, "
            "sans lire ni copier les données brutes."
        )
    )
    parser.add_argument("--root", required=True, help="Workspace FULL/COLD reconstruit.")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        json_path, md_path, contract = write_replay_input_contract(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"DATASET_CONTRACT_NO_GO: {type(exc).__name__}: {exc}")
        return 2
    print(
        json.dumps(
            {
                "contract_digest": contract.get("contract_digest"),
                "experiment_digest": contract.get("experiment_digest"),
                "source_count": contract.get("source_count", 0),
                "research_source_count": contract.get("research_source_count", 0),
                "sqlite_source_count": contract.get("sqlite_source_count", 0),
                "report_json": str(json_path),
                "report_markdown": str(md_path),
                "read_only": True,
                "network_used": False,
                "raw_data_embedded": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
