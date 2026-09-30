"""Produit un rapport déterministe des lignes non couvertes à partir de coverage.json."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("files"), dict):
        raise ValueError("coverage.json invalide: mapping files absent")
    return raw


def build_gap_report(report: dict[str, Any]) -> dict[str, Any]:
    totals = report.get("totals") if isinstance(report.get("totals"), dict) else {}
    rows: list[dict[str, Any]] = []
    for filename, payload in report["files"].items():
        if not isinstance(payload, dict):
            continue
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        missing_lines = payload.get("missing_lines") if isinstance(payload.get("missing_lines"), list) else []
        missing = sorted({int(line) for line in missing_lines})
        statements = int(summary.get("num_statements") or 0)
        covered = int(summary.get("covered_lines") or 0)
        pct = float(summary.get("percent_covered") or (100.0 if statements == 0 else 0.0))
        if missing:
            rows.append(
                {
                    "file": str(filename),
                    "statements": statements,
                    "covered_lines": covered,
                    "missing_count": len(missing),
                    "percent_covered": pct,
                    "missing_lines": missing,
                }
            )
    rows.sort(key=lambda row: (-row["missing_count"], row["percent_covered"], row["file"]))
    total_missing = int(totals.get("missing_lines") or sum(row["missing_count"] for row in rows))
    return {
        "schema": "hypersmart.coverage_gaps.v1",
        "percent_covered": float(totals.get("percent_covered") or 0.0),
        "num_statements": int(totals.get("num_statements") or 0),
        "covered_lines": int(totals.get("covered_lines") or 0),
        "missing_lines": total_missing,
        "files_with_gaps": len(rows),
        "target_percent": 100.0,
        "complete": total_missing == 0,
        "files": rows,
    }


def render_markdown(gaps: dict[str, Any]) -> str:
    lines = [
        "# HyperSmart — écarts de couverture vers 100 %",
        "",
        f"- Couverture : **{float(gaps['percent_covered']):.4f} %**",
        f"- Lignes mesurées : **{int(gaps['num_statements'])}**",
        f"- Lignes manquantes : **{int(gaps['missing_lines'])}**",
        f"- Fichiers avec écarts : **{int(gaps['files_with_gaps'])}**",
        f"- Objectif : **100,0000 % / 0 ligne manquante**",
        "",
        "| Fichier | Couverture | Manquantes | Lignes |",
        "|---|---:|---:|---|",
    ]
    files = gaps.get("files") if isinstance(gaps.get("files"), list) else []
    if not files:
        lines.append("| — | 100,0000 % | 0 | — |")
    for row in files:
        missing = ", ".join(str(value) for value in row["missing_lines"])
        lines.append(
            f"| `{row['file']}` | {float(row['percent_covered']):.4f} % | "
            f"{int(row['missing_count'])} | {missing} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", default="coverage.json")
    parser.add_argument("--json-output", default="coverage-gaps.json")
    parser.add_argument("--markdown-output", default="coverage-gaps.md")
    args = parser.parse_args(argv)

    gaps = build_gap_report(_load(Path(args.coverage)))
    Path(args.json_output).write_text(
        json.dumps(gaps, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    Path(args.markdown_output).write_text(render_markdown(gaps), encoding="utf-8")
    print(
        "COVERAGE_GAPS "
        f"pct={gaps['percent_covered']:.4f} missing={gaps['missing_lines']} "
        f"files={gaps['files_with_gaps']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
