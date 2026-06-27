from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

DEFAULT_DECISION_LOG = "logs/structured/decisions.jsonl"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_decision_rows(path: str | Path = DEFAULT_DECISION_LOG) -> list[dict[str, Any]]:
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


def _event(row: dict[str, Any]) -> str:
    return str(row.get("event_type") or row.get("type") or "")


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload") or row.get("data") or row
    return payload if isinstance(payload, dict) else row


def summarize_truth(rows: list[dict[str, Any]]) -> dict[str, Any]:
    events = Counter(_event(r) for r in rows)
    source_counter: Counter[str] = Counter()
    no_trade_counter: Counter[str] = Counter()
    v2_counter: Counter[str] = Counter()
    open_notional = 0.0
    close_net = 0.0
    close_gross = 0.0
    close_fees = 0.0
    by_source_pnl: dict[str, float] = defaultdict(float)

    for row in rows:
        event = _event(row)
        data = _payload(row)
        if event == "PAPER_OPEN":
            source = str(data.get("data_source") or data.get("source") or "UNKNOWN")
            source_counter[source] += 1
            open_notional += _num(data.get("size") or data.get("notional_usdc") or data.get("paper_notional_usdc"), 0.0)
        elif event == "PAPER_CLOSE":
            source = str(data.get("data_source") or data.get("source") or "UNKNOWN")
            net = _num(data.get("net_pnl_usdc") or data.get("net_pnl"), 0.0)
            gross = _num(data.get("gross_pnl_usdc") or data.get("gross_pnl"), 0.0)
            fees = _num(data.get("fees_usdc") or data.get("fees"), 0.0)
            close_net += net
            close_gross += gross
            close_fees += fees
            by_source_pnl[source] += net
        elif event == "NO_TRADE":
            reason = str(data.get("reason") or data.get("code") or data.get("message") or "UNKNOWN")
            no_trade_counter[reason] += 1
        elif event == "DECISION_V2":
            action = str(data.get("action") or data.get("decision") or "UNKNOWN")
            v2_counter[action] += 1

    fallback_opens = sum(v for k, v in source_counter.items() if "fallback" in k.lower() or "demo" in k.lower())
    real_opens = sum(v for k, v in source_counter.items() if "real" in k.lower() or "orderbook" in k.lower() or k in {"rest", "stream", "wallet_cluster"})
    total_opens = events.get("PAPER_OPEN", 0)

    return {
        "events": dict(events),
        "paper_open_count": total_opens,
        "paper_close_count": events.get("PAPER_CLOSE", 0),
        "open_notional_usdc": round(open_notional, 6),
        "gross_pnl_usdc": round(close_gross, 6),
        "fees_usdc": round(close_fees, 6),
        "net_pnl_usdc": round(close_net, 6),
        "source_counts": dict(source_counter),
        "source_pnl_usdc": {k: round(v, 6) for k, v in sorted(by_source_pnl.items())},
        "fallback_or_demo_open_share": round(fallback_opens / total_opens, 6) if total_opens else 0.0,
        "real_like_open_share": round(real_opens / total_opens, 6) if total_opens else 0.0,
        "decision_v2_actions": dict(v2_counter),
        "top_no_trade_reasons": dict(no_trade_counter.most_common(20)),
        "read_only": True,
        "paper_only": True,
    }


def truth_report(path: str | Path = DEFAULT_DECISION_LOG) -> dict[str, Any]:
    return summarize_truth(load_decision_rows(path))


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize dYdX paper simulation truth from JSONL decisions")
    parser.add_argument("--path", default=DEFAULT_DECISION_LOG)
    args = parser.parse_args()
    print(json.dumps(truth_report(args.path), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = ["DEFAULT_DECISION_LOG", "load_decision_rows", "summarize_truth", "truth_report"]
