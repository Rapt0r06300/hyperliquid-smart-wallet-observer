from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LogDiagnostic:
    closed_trades: int
    wins: int
    losses: int
    gross_pnl: float
    fees: float
    net_pnl: float
    winrate: float
    profit_factor: float
    by_market: list[dict[str, Any]]
    by_reason: list[dict[str, Any]]
    by_source: list[dict[str, Any]]
    no_trade_reasons: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__ | {"paper_only": True, "read_only": True}


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _f(row: dict[str, Any], key: str) -> float:
    try:
        return float(row.get(key, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _s(row: dict[str, Any], key: str) -> str:
    return str(row.get(key, "UNKNOWN") or "UNKNOWN")


def _buckets(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    d = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "net_pnl": 0.0, "fees": 0.0})
    for r in rows:
        k = _s(r, key)
        net = _f(r, "net_pnl")
        d[k]["trades"] += 1
        d[k]["wins"] += int(net > 0)
        d[k]["losses"] += int(net <= 0)
        d[k]["net_pnl"] += net
        d[k]["fees"] += _f(r, "fees")
    out = []
    for k, v in d.items():
        trades = int(v["trades"])
        out.append({
            "key": k,
            "trades": trades,
            "wins": int(v["wins"]),
            "losses": int(v["losses"]),
            "winrate": round(float(v["wins"]) / trades, 4) if trades else 0.0,
            "net_pnl": round(float(v["net_pnl"]), 6),
            "fees": round(float(v["fees"]), 6),
        })
    return sorted(out, key=lambda x: (x["net_pnl"], -x["trades"]))


def analyze_decision_rows(rows: list[dict[str, Any]]) -> LogDiagnostic:
    closed = [r for r in rows if r.get("event_type") == "PAPER_CLOSE"]
    gross = sum(_f(r, "gross_pnl") for r in closed)
    fees = sum(_f(r, "fees") for r in closed)
    net = sum(_f(r, "net_pnl") for r in closed)
    wins = sum(1 for r in closed if _f(r, "net_pnl") > 0)
    losses = len(closed) - wins
    gains = sum(max(0.0, _f(r, "net_pnl")) for r in closed)
    neg = abs(sum(min(0.0, _f(r, "net_pnl")) for r in closed))
    pf = 999.0 if neg == 0 and gains > 0 else (gains / neg if neg else 0.0)
    nt = Counter(_s(r, "reason") for r in rows if r.get("event_type") == "NO_TRADE")
    return LogDiagnostic(
        closed_trades=len(closed),
        wins=wins,
        losses=losses,
        gross_pnl=gross,
        fees=fees,
        net_pnl=net,
        winrate=wins / len(closed) if closed else 0.0,
        profit_factor=pf,
        by_market=_buckets(closed, "market_id")[:10],
        by_reason=_buckets(closed, "reason")[:10],
        by_source=_buckets(closed, "data_source")[:10],
        no_trade_reasons=dict(nt),
    )


def analyze_decision_log(path: str | Path = "logs/structured/decisions.jsonl") -> LogDiagnostic:
    return analyze_decision_rows(load_jsonl(path))


__all__ = ["LogDiagnostic", "analyze_decision_log", "analyze_decision_rows", "load_jsonl"]
