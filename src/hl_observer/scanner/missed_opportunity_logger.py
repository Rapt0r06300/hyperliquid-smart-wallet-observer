from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from hl_observer.scanner.scanner_models import MissedOpportunity


def write_missed_opportunity_reports(
    opportunities: list[MissedOpportunity],
    *,
    output_dir: Path,
    stem: str = "missed_opportunity_report",
) -> dict[str, Path]:
    """Write JSON, CSV and Markdown reports for refused/missed opportunities."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    csv_path = output_dir / f"{stem}.csv"
    md_path = output_dir / f"{stem}.md"
    payload = [asdict(item) for item in opportunities]
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "reason",
                "wallet_address",
                "coin",
                "action_type",
                "observed_at_ms",
                "detected_at_ms",
                "component",
                "severity",
                "message",
                "next_action",
            ],
        )
        writer.writeheader()
        for item in opportunities:
            row = asdict(item)
            row.pop("details", None)
            writer.writerow(row)
    md_path.write_text(format_missed_opportunity_markdown(opportunities), encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "markdown": md_path}


def format_missed_opportunity_markdown(opportunities: list[MissedOpportunity]) -> str:
    lines = [
        "# HyperSmart Missed Opportunity Report",
        "",
        "Research-only report. A missed opportunity is not a trading signal.",
        "",
        f"Total: {len(opportunities)}",
        "",
        "| Reason | Wallet | Coin | Action | Severity | Message | Next action |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in opportunities:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(item.reason),
                    _cell(item.wallet_address or "-"),
                    _cell(item.coin or "-"),
                    _cell(item.action_type or "-"),
                    _cell(item.severity),
                    _cell(item.message),
                    _cell(item.next_action),
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def _cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")

