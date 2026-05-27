from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from hl_observer.storage.repositories import stable_payload_hash
from hl_observer.wallets.leaderboard_models import LeaderboardRowRecord
from hl_observer.wallets.leaderboard_validation import validate_leaderboard_wallet_address


ADDRESS_KEY_CANDIDATES = (
    "address",
    "ethAddress",
    "eth_address",
    "wallet",
    "trader",
    "user",
    "account",
)


def parse_leaderboard_records(
    records: list[dict[str, Any]],
    *,
    period: str = "30D",
    source_method: str = "import",
    extraction_method: str = "import",
    source_confidence_score: float = 85.0,
) -> list[LeaderboardRowRecord]:
    rows: list[LeaderboardRowRecord] = []
    for index, record in enumerate(records, start=1):
        raw_address = _first_present(record, *ADDRESS_KEY_CANDIDATES)
        validation = validate_leaderboard_wallet_address(str(raw_address or ""), source_method=source_method)
        rows.append(
            LeaderboardRowRecord(
                rank=_safe_int(_first_present(record, "rank", "Rank")) or index,
                address=validation.normalized_value if validation.is_full_address else None,
                address_short=str(raw_address) if validation.is_truncated else None,
                account_value_usdc=_safe_float(_first_present(record, "account_value_usdc", "accountValue", "Account Value")),
                pnl_usdc=_safe_float(_first_present(record, "pnl_usdc", "pnl", "PnL")),
                roi_pct=_safe_float(_first_present(record, "roi_pct", "roi", "ROI")),
                volume_usdc=_safe_float(_first_present(record, "volume_usdc", "volume", "Volume")),
                period=period,
                source_method=source_method,
                extraction_method=extraction_method,
                source_payload_hash=stable_payload_hash(record),
                validation=validation,
                source_confidence_score=source_confidence_score,
                raw=record,
            )
        )
    return rows


def parse_leaderboard_file(path: Path, *, period: str = "30D") -> list[LeaderboardRowRecord]:
    if not path.exists():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            records = raw.get("rows") or raw.get("leaderboard") or raw.get("data") or []
        else:
            records = raw
        if not isinstance(records, list):
            raise ValueError("JSON leaderboard import must contain a list of rows")
        return parse_leaderboard_records([_coerce_record(item) for item in records], period=period)
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return parse_leaderboard_records(list(csv.DictReader(fh)), period=period)
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    records = [{"address": line} for line in lines]
    return parse_leaderboard_records(records, period=period)


def extract_display_addresses(text: str) -> list[str]:
    full = re.findall(r"0x[a-fA-F0-9]{40}", text)
    truncated = re.findall(r"0x[a-fA-F0-9]{2,12}\.\.\.[a-fA-F0-9]{2,12}", text)
    return full + truncated


def _first_present(payload: dict[str, Any], *keys: str) -> Any:
    lower_map = {key.lower(): value for key, value in payload.items()}
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
        if key.lower() in lower_map and lower_map[key.lower()] not in (None, ""):
            return lower_map[key.lower()]
    return None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _coerce_record(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    return {"address": str(item)}
