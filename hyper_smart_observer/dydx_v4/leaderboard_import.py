from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Iterable, Optional

from hyper_smart_observer.dydx_v4.wallet_harvester import WalletSource, is_valid_address

DEFAULT_IMPORT_PATHS = (
    "data/import/dydx_whales.csv",
    "data/import/dydx_whales.json",
    "data/import/dydx_whales.jsonl",
    "data/import/dydx_leaderboard.csv",
    "data/import/dydx_leaderboard.json",
    "data/import/dydx_leaderboard.jsonl",
)

ADDRESS_KEYS = ("address", "wallet", "user", "subaccount", "account", "owner", "ethAddress")
PNL_KEYS = ("net_pnl_usdc", "pnl", "netPnl", "realizedPnl", "realized_pnl", "totalPnl")
ROI_KEYS = ("roi_pct", "roi", "roiPct", "returnPct")
WINRATE_KEYS = ("winrate", "winRate", "win_rate")
PF_KEYS = ("profit_factor", "profitFactor", "pf")
TRADES_KEYS = ("trade_count", "trades", "numTrades", "tradeCount")
BALANCE_KEYS = ("usdc_balance", "balance", "equity", "accountEquity", "margin")
OPEN_POSITIONS_KEYS = ("open_positions", "openPositions", "positions", "position_count")
MARKET_KEYS = ("markets", "market", "coins", "symbols", "assets")


def _first(row: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _metrics(row: dict) -> dict:
    metrics = {
        "net_pnl_usdc": _first(row, PNL_KEYS),
        "roi_pct": _first(row, ROI_KEYS),
        "winrate": _first(row, WINRATE_KEYS),
        "profit_factor": _first(row, PF_KEYS),
        "trade_count": _first(row, TRADES_KEYS),
        "usdc_balance": _first(row, BALANCE_KEYS),
        "open_positions": _first(row, OPEN_POSITIONS_KEYS),
        "markets": _first(row, MARKET_KEYS),
    }
    return {key: value for key, value in metrics.items() if value not in (None, "")}


def _rows_from_json(data) -> list[dict]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        rows = data.get("leaderboard") or data.get("rows") or data.get("data") or data.get("traders") or []
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
    return []


def _read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _read_json(path: Path) -> list[dict]:
    return _rows_from_json(json.loads(path.read_text(encoding="utf-8")))


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def read_leaderboard_file(path: str | Path) -> list[tuple[str, dict]]:
    p = Path(path)
    if not p.exists() or not p.is_file():
        return []
    suffix = p.suffix.lower()
    try:
        if suffix == ".csv":
            rows = _read_csv(p)
        elif suffix == ".jsonl":
            rows = _read_jsonl(p)
        elif suffix == ".json":
            rows = _read_json(p)
        else:
            return []
    except OSError:
        return []
    out: list[tuple[str, dict]] = []
    for row in rows:
        addr = _first(row, ADDRESS_KEYS)
        if isinstance(addr, str) and is_valid_address(addr):
            out.append((addr.strip(), _metrics(row)))
    return out


def configured_import_paths() -> list[str]:
    raw = os.environ.get("DYDX_WALLET_IMPORT_PATHS", "") or os.environ.get("DYDX_WHALE_IMPORT_PATHS", "")
    if raw.strip():
        return [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]
    return list(DEFAULT_IMPORT_PATHS)


def imported_wallet_rows(paths: Optional[Iterable[str | Path]] = None) -> list[tuple[str, dict]]:
    merged: dict[str, dict] = {}
    for path in paths or configured_import_paths():
        for addr, metrics in read_leaderboard_file(path):
            current = merged.get(addr, {})
            current.update({k: v for k, v in metrics.items() if v not in (None, "")})
            merged[addr] = current
    return list(merged.items())


def leaderboard_file_source(name: str = "local_leaderboard_import", paths: Optional[Iterable[str | Path]] = None) -> WalletSource:
    selected = list(paths) if paths is not None else configured_import_paths()

    def _gen():
        yield from imported_wallet_rows(selected)

    return WalletSource(name=name, harvest_fn=_gen)


__all__ = [
    "DEFAULT_IMPORT_PATHS",
    "configured_import_paths",
    "imported_wallet_rows",
    "leaderboard_file_source",
    "read_leaderboard_file",
]
