from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from hl_observer.explorer.explorer_models import ExplorerResult, ExplorerSourceStatus
from hl_observer.explorer.explorer_parser import parse_explorer_records


def import_explorer_file(path: str | Path) -> ExplorerResult:
    file_path = Path(path)
    records = _read_records(file_path)
    transactions, truncated = parse_explorer_records(records, source_url=str(file_path))
    full_addresses = {tx.wallet_address for tx in transactions if tx.wallet_address}
    result = ExplorerResult(
        method="import",
        status=ExplorerSourceStatus.OK if full_addresses else ExplorerSourceStatus.IMPORT_REQUIRED,
        events_seen=len(records),
        transactions=transactions,
        full_addresses_found=len(full_addresses),
        truncated_addresses_rejected=truncated,
        candidates_created=len(full_addresses),
        notes=["local_import_parsed", "truncated_addresses_rejected"],
    )
    return result.finish()


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return [row for row in raw if isinstance(row, dict)]
        if isinstance(raw, dict):
            rows = raw.get("transactions") or raw.get("events") or raw.get("rows") or []
            return [row for row in rows if isinstance(row, dict)]
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value:
            rows.append({"address": value})
    return rows

