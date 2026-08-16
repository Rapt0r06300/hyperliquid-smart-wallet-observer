from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.datasets.experiment_plan import write_experiment_plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prépare un plan d'expérience FULL/COLD reproductible à partir des profils "
            "Research Lab, des schémas SQLite et de la provenance du workspace."
        )
    )
    parser.add_argument("--root", required=True, help="Workspace FULL/COLD reconstruit.")
    parser.add_argument("--start-ms", type=int, default=None)
    parser.add_argument("--end-ms", type=int, default=None)
    parser.add_argument("--family", default=None)
    parser.add_argument("--coin", default=None)
    parser.add_argument("--wallet", default=None)
    parser.add_argument("--metric", default=None)
    parser.add_argument(
        "--require-complete-research",
        action="store_true",
        help="Ne retient que les fichiers Research Lab profilés jusqu'à EOF.",
    )
    parser.add_argument(
        "--include-unknown-time",
        action="store_true",
        help="Autorise les fichiers Research Lab dont la période est inconnue.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    try:
        json_path, md_path, plan = write_experiment_plan(
            root,
            start_ms=args.start_ms,
            end_ms=args.end_ms,
            family=args.family,
            coin=args.coin,
            wallet=args.wallet,
            metric=args.metric,
            require_complete_research=bool(args.require_complete_research),
            include_unknown_time=bool(args.include_unknown_time),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"DATASET_EXPERIMENT_NO_GO: {type(exc).__name__}: {exc}")
        return 2

    print(
        json.dumps(
            {
                "status": plan.get("status"),
                "experiment_digest": plan.get("experiment_digest"),
                "ready_source_count": plan.get("ready_source_count", 0),
                "research_selected_file_count": plan.get("research_lab", {}).get("selected_file_count", 0),
                "sqlite_selected_source_count": plan.get("sqlite", {}).get("selected_source_count", 0),
                "warnings": plan.get("warnings", []),
                "report_json": str(json_path),
                "report_markdown": str(md_path),
                "read_only": True,
                "network_used": False,
                "raw_data_copied": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if plan.get("status") == "READY" else 3


if __name__ == "__main__":
    raise SystemExit(main())
