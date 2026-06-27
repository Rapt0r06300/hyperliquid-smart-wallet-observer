from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

DEFAULT_DECISION_LOG = "logs/structured/decisions.jsonl"


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _load(path: str | Path) -> list[dict[str, Any]]:
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


def signal_latency_report(path: str | Path = DEFAULT_DECISION_LOG) -> dict[str, Any]:
    rows = _load(path)
    stale_refusals = 0
    recovered = 0
    raw_ages: list[float] = []
    effective_ages: list[float] = []
    reasons: Counter[str] = Counter()
    for row in rows:
        event = str(row.get("event_type") or row.get("type") or "")
        payload = row.get("payload") or row.get("data") or row
        if not isinstance(payload, dict):
            payload = row
        reason = str(payload.get("reason") or payload.get("message") or payload.get("code") or "")
        if "STALE" in reason:
            stale_refusals += 1
            reasons[reason] += 1
        if payload.get("freshness_recovered") is True:
            recovered += 1
        raw = payload.get("raw_signal_age_ms")
        eff = payload.get("effective_signal_age_ms") or payload.get("signal_age_ms")
        if raw is not None:
            raw_ages.append(_num(raw))
        if eff is not None:
            effective_ages.append(_num(eff))
        if event == "DECISION_V2":
            for note in payload.get("notes", []) or []:
                if isinstance(note, str) and "age" in note.lower():
                    reasons[note] += 1
    avg_raw = sum(raw_ages) / len(raw_ages) if raw_ages else 0.0
    avg_eff = sum(effective_ages) / len(effective_ages) if effective_ages else 0.0
    return {
        "rows": len(rows),
        "stale_refusals": stale_refusals,
        "freshness_recovered": recovered,
        "avg_raw_signal_age_ms": round(avg_raw, 3),
        "avg_effective_signal_age_ms": round(avg_eff, 3),
        "top_latency_reasons": dict(reasons.most_common(20)),
        "read_only": True,
        "paper_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize stale/recovered dYdX paper signal latency")
    parser.add_argument("--path", default=DEFAULT_DECISION_LOG)
    args = parser.parse_args()
    print(json.dumps(signal_latency_report(args.path), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = ["DEFAULT_DECISION_LOG", "signal_latency_report"]
