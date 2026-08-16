from __future__ import annotations

import argparse
import json
from pathlib import Path

from hl_observer.datasets.sqlite_profiler import write_sqlite_inventory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inventorie les bases SQLite d'un workspace FULL/COLD en lecture seule. "
            "Aucune valeur de ligne n'est exportée et les noms marqués corrompus sont quarantainés."
        )
    )
    parser.add_argument("--root", required=True, help="Workspace FULL/COLD reconstruit.")
    parser.add_argument(
        "--quick-check",
        action="store_true",
        help=(
            "Demande PRAGMA quick_check(1) sur les bases lisibles. Peut être long sur des dizaines de Gio; "
            "désactivé par défaut."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"SQLITE_INVENTORY_NO_GO: workspace absent: {root}")
        return 2
    try:
        json_path, md_path, profile = write_sqlite_inventory(
            root,
            quick_check=bool(args.quick_check),
            include_quarantined=False,
        )
    except (OSError, ValueError) as exc:
        print(f"SQLITE_INVENTORY_NO_GO: {type(exc).__name__}: {exc}")
        return 2

    primary_failures = [
        item
        for item in profile.get("databases", [])
        if isinstance(item, dict)
        and item.get("role") == "PRIMARY"
        and item.get("status") not in {"READABLE_READ_ONLY", "QUARANTINED_NAME"}
    ]
    payload = {
        "database_count": profile.get("database_count", 0),
        "database_gib": profile.get("database_gib", 0),
        "readable_database_count": profile.get("readable_database_count", 0),
        "readable_database_gib": profile.get("readable_database_gib", 0),
        "quarantined_database_count": profile.get("quarantined_database_count", 0),
        "economic_research_candidate_count": profile.get("economic_research_candidate_count", 0),
        "primary_failures": [item.get("path") for item in primary_failures],
        "report_json": str(json_path),
        "report_markdown": str(md_path),
        "read_only": True,
        "row_values_exported": False,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if primary_failures:
        print("SQLITE_INVENTORY_PARTIAL: une base principale présente est illisible en lecture seule.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
