from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from hyper_smart_observer.copy_mode.copy_models import LeaderCandidateInput


ADDRESS_KEYS = ("wallet_address", "address", "wallet", "user")
TEMPLATE_COLUMNS = [
    "wallet_address",
    "source",
    "rank",
    "history_days",
    "closed_pnl_points",
    "total_closed_pnl",
    "max_single_trade_pnl",
    "max_drawdown_pct",
    "consistency_score",
    "per_coin_stability_score",
    "execution_quality_score",
    "sample_confidence",
    "copyability_score",
]


def load_leader_candidates_from_file(path: Path) -> list[LeaderCandidateInput]:
    """Load local leaderboard candidates from JSON, CSV or TXT.

    Missing metrics are left missing on purpose; the selector will refuse or
    mark insufficient data instead of inventing quality.
    """

    suffix = path.suffix.lower()
    if suffix == ".json":
        return _load_json(path)
    if suffix == ".csv":
        return _load_csv(path)
    if suffix in {".txt", ".list"}:
        return _load_txt(path)
    raise ValueError("Supported shortlist input formats: .json, .csv, .txt, .list")


def write_candidate_template(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(TEMPLATE_COLUMNS)
        writer.writerow(
            [
                "0x0000000000000000000000000000000000000000",
                "manual_research",
                "1",
                "30",
                "50",
                "10000",
                "1000",
                "12",
                "82",
                "75",
                "78",
                "85",
                "80",
            ]
        )
    return path


def _load_json(path: Path) -> list[LeaderCandidateInput]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = payload.get("candidates") or payload.get("wallets") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    if not isinstance(rows, list):
        raise ValueError("JSON candidates must be a list or an object with candidates/wallets list.")
    return [_candidate_from_mapping(item if isinstance(item, dict) else {"wallet_address": item}) for item in rows]


def _load_csv(path: Path) -> list[LeaderCandidateInput]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [_candidate_from_mapping(row) for row in reader]


def _load_txt(path: Path) -> list[LeaderCandidateInput]:
    candidates: list[LeaderCandidateInput] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        candidates.append(LeaderCandidateInput(wallet_address=value, source="manual_txt"))
    return candidates


def _candidate_from_mapping(raw: dict[str, Any]) -> LeaderCandidateInput:
    address = _first(raw, *ADDRESS_KEYS)
    if address is None:
        raise ValueError("Candidate row missing wallet_address/address/wallet/user.")
    return LeaderCandidateInput(
        wallet_address=str(address).strip(),
        source=str(_first(raw, "source") or "local_candidate_file"),
        rank=_optional_int(_first(raw, "rank")),
        history_days=_optional_float(_first(raw, "history_days", "historyDays")),
        closed_pnl_points=_optional_int(_first(raw, "closed_pnl_points", "closedPnlPoints", "closed_pnl_count")) or 0,
        total_closed_pnl=_optional_float(_first(raw, "total_closed_pnl", "totalClosedPnl", "closed_pnl_total")),
        max_single_trade_pnl=_optional_float(_first(raw, "max_single_trade_pnl", "maxSingleTradePnl", "largest_win")),
        max_drawdown_pct=_optional_float(_first(raw, "max_drawdown_pct", "maxDrawdownPct", "drawdown_pct")),
        consistency_score=_optional_float(_first(raw, "consistency_score", "consistencyScore")),
        per_coin_stability_score=_optional_float(_first(raw, "per_coin_stability_score", "perCoinStabilityScore")),
        execution_quality_score=_optional_float(_first(raw, "execution_quality_score", "executionQualityScore")),
        sample_confidence=_optional_float(_first(raw, "sample_confidence", "sampleConfidence")),
        copyability_score=_optional_float(_first(raw, "copyability_score", "copyabilityScore")),
    )


def _first(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
