from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from hl_observer.datasets.sqlite_research_source import (
    SAFE_RESEARCH_COLUMNS,
    build_sqlite_research_catalog,
    stream_table_to_jsonl,
)

CATALOG_JSON = Path("runtime") / "reports" / "datasets" / "SQLITE_RESEARCH_CATALOG.json"
CATALOG_MD = Path("runtime") / "reports" / "datasets" / "SQLITE_RESEARCH_CATALOG.md"


def _render_markdown(catalog: Mapping[str, Any]) -> str:
    lines = [
        "# Catalogue de recherche SQLite FULL/COLD",
        "",
        "- Sources SQLite ouvertes exclusivement en lecture seule.",
        "- Les colonnes JSON/payload brutes ne sont pas exposées par l'adaptateur de recherche.",
        "- `max_rowid_upper_bound` est une borne/indication de volume, pas un COUNT exact.",
        f"- Bases lisibles : **{catalog.get('readable_database_count', 0)}** / {catalog.get('database_count', 0)}.",
        "",
        "| Base | Table | Colonnes sûres | Max rowid indicatif |",
        "|---|---|---:|---:|",
    ]
    databases = catalog.get("databases")
    if isinstance(databases, list):
        for database in databases:
            if not isinstance(database, Mapping):
                continue
            tables = database.get("tables")
            if not isinstance(tables, list) or not tables:
                lines.append(
                    f"| `{database.get('path')}` | - | 0 | - |"
                )
                continue
            for table in tables:
                if not isinstance(table, Mapping):
                    continue
                lines.append(
                    f"| `{database.get('path')}` | `{table.get('name')}` | "
                    f"{table.get('safe_column_count', 0)} | {table.get('max_rowid_upper_bound')} |"
                )
    lines.extend(
        [
            "",
            "## Tables autorisées",
            "",
            ", ".join(f"`{name}`" for name in sorted(SAFE_RESEARCH_COLUMNS)),
            "",
            "> Une table disponible devient une source historique exploitable, mais son contenu doit encore passer les contrôles causaux, les coûts et la validation OOS propres à chaque moteur.",
            "",
        ]
    )
    return "\n".join(lines)


def write_catalog(root: str | Path) -> tuple[Path, Path, dict[str, Any]]:
    resolved = Path(root).resolve()
    catalog = build_sqlite_research_catalog(resolved)
    json_path = resolved / CATALOG_JSON
    md_path = resolved / CATALOG_MD
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(_render_markdown(catalog), encoding="utf-8")
    return json_path, md_path, catalog


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Catalogue et exporte des vues historiques sûres depuis les SQLite FULL/COLD."
    )
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--export-table",
        choices=tuple(sorted(SAFE_RESEARCH_COLUMNS)),
        default=None,
        help="Exporte une vue JSONL dérivée d'une table autorisée.",
    )
    parser.add_argument("--limit", type=int, default=0, help="0 = toutes les lignes de la vue.")
    parser.add_argument("--output", default=None, help="Chemin de sortie JSONL optionnel.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"SQLITE_RESEARCH_NO_GO: workspace absent: {root}")
        return 2
    try:
        json_path, md_path, catalog = write_catalog(root)
        export = None
        if args.export_table:
            output = (
                Path(args.output).resolve()
                if args.output
                else root
                / "runtime"
                / "reports"
                / "datasets"
                / "sqlite_views"
                / f"{args.export_table}.jsonl"
            )
            export = stream_table_to_jsonl(
                root,
                str(args.export_table),
                output,
                limit=max(0, int(args.limit)),
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"SQLITE_RESEARCH_NO_GO: {type(exc).__name__}: {exc}")
        return 2
    print(
        json.dumps(
            {
                "catalog_json": str(json_path),
                "catalog_markdown": str(md_path),
                "readable_database_count": catalog.get("readable_database_count", 0),
                "table_sources": catalog.get("table_sources", {}),
                "export": export,
                "read_only_sources": True,
                "safe_columns_only": True,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
