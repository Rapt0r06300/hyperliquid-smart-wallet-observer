from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path
from typing import Any

from hyper_smart_observer.dydx_v4.config import DydxNetwork, DydxV4Config
from hyper_smart_observer.dydx_v4.cosmos_client import DydxCosmosLcdClient
from hyper_smart_observer.dydx_v4.rest_client import DydxIndexerRestClient

DEFAULT_OUTPUT = "data/import/dydx_whales.csv"


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _rows_from_pnl_response(resp: dict) -> list[dict]:
    rows = resp.get("historicalPnl") or resp.get("historicalPnlRecords") or resp.get("pnlTicks") or resp.get("data") or []
    return rows if isinstance(rows, list) else []


def _pnl_value(row: dict) -> float:
    for key in ("totalPnl", "netPnl", "pnl", "realizedPnl", "realizedPnlUsdc"):
        if row.get(key) not in (None, ""):
            return _num(row.get(key), 0.0)
    return 0.0


def fetch_pnl(rest: DydxIndexerRestClient, address: str, subaccount_number: int, limit: int) -> tuple[float, int]:
    try:
        resp = rest.get_historical_pnl(address=address, subaccount_number=subaccount_number, limit=limit)
    except Exception:
        return 0.0, 0
    rows = _rows_from_pnl_response(resp)
    if not rows:
        return 0.0, 0
    values = [_pnl_value(r) for r in rows if isinstance(r, dict)]
    if not values:
        return 0.0, 0
    # Certains endpoints retournent un PnL cumulatif par tick, d'autres un delta.
    # Pour rester conservateur, on garde le meilleur estimateur disponible:
    # max absolu positif si cumulatif, sinon somme si les lignes sont des deltas.
    total = max(values) if max(values) >= abs(min(values)) else sum(values)
    return float(total), len(values)


def build_rows(max_pages: int, page_size: int, min_usdc: float, pnl_limit: int, pause_s: float) -> list[dict]:
    cfg = DydxV4Config(network=DydxNetwork.MAINNET)
    rest = DydxIndexerRestClient(base_url=cfg.indexer_rest_url, timeout_s=8.0, max_retries=1, rate_limit_rps=3.0)
    cosmos = DydxCosmosLcdClient()
    subs = cosmos.scan_subaccounts(max_pages=max_pages, page_size=page_size, min_usdc=min_usdc, only_with_positions=True)
    rows: list[dict] = []
    for sub in subs:
        pnl, ticks = fetch_pnl(rest, sub.address, sub.subaccount_number, pnl_limit)
        markets = ";".join(sorted({p.market_id for p in sub.positions}))
        sides = ";".join(sorted({p.side for p in sub.positions}))
        rows.append({
            "address": sub.address,
            "subaccount_number": sub.subaccount_number,
            "net_pnl_usdc": round(pnl, 6),
            "pnl_ticks": ticks,
            "usdc_balance": round(float(sub.usdc_balance or 0.0), 6),
            "open_positions": sub.total_position_count,
            "markets": markets,
            "sides": sides,
            "source": "cosmos_subaccounts_plus_indexer_historical_pnl",
            "fetched_at_ms": int(time.time() * 1000),
        })
        if pause_s > 0:
            time.sleep(pause_s)
    rows.sort(key=lambda r: (_num(r.get("net_pnl_usdc")), _num(r.get("usdc_balance")), _num(r.get("open_positions"))), reverse=True)
    return rows


def write_csv(rows: list[dict], output: str | Path) -> Path:
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "address",
        "subaccount_number",
        "net_pnl_usdc",
        "pnl_ticks",
        "usdc_balance",
        "open_positions",
        "markets",
        "sides",
        "source",
        "fetched_at_ms",
    ]
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})
    return out


def build_whale_file(
    output: str | Path = DEFAULT_OUTPUT,
    max_pages: int = 80,
    page_size: int = 100,
    min_usdc: float = 1000.0,
    pnl_limit: int = 100,
    pause_s: float = 0.05,
    limit_rows: int = 2000,
) -> Path:
    rows = build_rows(max_pages=max_pages, page_size=page_size, min_usdc=min_usdc, pnl_limit=pnl_limit, pause_s=pause_s)
    if limit_rows > 0:
        rows = rows[:limit_rows]
    return write_csv(rows, output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build local dYdX whales import CSV from public read-only data")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--max-pages", type=int, default=80)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--min-usdc", type=float, default=1000.0)
    parser.add_argument("--pnl-limit", type=int, default=100)
    parser.add_argument("--pause-s", type=float, default=0.05)
    parser.add_argument("--limit-rows", type=int, default=2000)
    args = parser.parse_args()
    path = build_whale_file(
        output=args.output,
        max_pages=args.max_pages,
        page_size=args.page_size,
        min_usdc=args.min_usdc,
        pnl_limit=args.pnl_limit,
        pause_s=args.pause_s,
        limit_rows=args.limit_rows,
    )
    print(str(path))


if __name__ == "__main__":
    main()


__all__ = ["DEFAULT_OUTPUT", "build_whale_file", "build_rows", "fetch_pnl", "write_csv"]
