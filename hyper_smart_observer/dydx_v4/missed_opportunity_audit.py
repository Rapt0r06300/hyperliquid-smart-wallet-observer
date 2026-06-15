from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_DECISION_LOG = "logs/structured/decisions.jsonl"


def _load_rows(path: str | Path) -> list[dict[str, Any]]:
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


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    p = row.get("payload") or row.get("data") or row
    return p if isinstance(p, dict) else row


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def audit_missed_opportunities(path: str | Path = DEFAULT_DECISION_LOG) -> dict[str, Any]:
    rows = _load_rows(path)
    candidates: list[dict[str, Any]] = []
    for row in rows:
        data = _payload(row)
        action = str(data.get("action") or data.get("decision") or data.get("event_type") or "")
        if action not in {"WATCH", "NO_TRADE"}:
            continue
        director = data.get("director") if isinstance(data.get("director"), dict) else {}
        tuned = data.get("tuned") if isinstance(data.get("tuned"), dict) else {}
        tremor = tuned.get("tremor") if isinstance(tuned.get("tremor"), dict) else {}
        quality = tuned.get("quality") if isinstance(tuned.get("quality"), dict) else {}
        opportunity = _num(director.get("opportunity_score"))
        risk = _num(director.get("risk_score"), 100.0)
        edge = _num(tremor.get("edge_remaining_bps"))
        quality_score = _num(quality.get("score"))
        age = _num(tremor.get("signal_age_ms"))
        wallets = max(_num(tremor.get("leading_wallets")), _num(tremor.get("consensus_wallets")))
        if opportunity >= 62.0 and risk <= 52.0 and edge >= 4.0 and quality_score >= 58.0 and age <= 90_000 and wallets >= 2:
            candidates.append({
                "action": action,
                "market_id": tremor.get("market_id"),
                "direction": tremor.get("direction"),
                "opportunity_score": round(opportunity, 4),
                "risk_score": round(risk, 4),
                "edge_bps": round(edge, 4),
                "quality_score": round(quality_score, 4),
                "signal_age_ms": round(age, 4),
                "wallets": wallets,
                "reasons": data.get("reasons", []),
                "notes": data.get("notes", []),
            })
    candidates.sort(key=lambda x: (x["opportunity_score"] - x["risk_score"], x["edge_bps"], x["quality_score"]), reverse=True)
    return {
        "rows": len(rows),
        "missed_candidate_count": len(candidates),
        "top_candidates": candidates[:50],
        "read_only": True,
        "paper_only": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit WATCH/NO_TRADE rows that may deserve paper recall")
    parser.add_argument("--path", default=DEFAULT_DECISION_LOG)
    args = parser.parse_args()
    print(json.dumps(audit_missed_opportunities(args.path), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()


__all__ = ["DEFAULT_DECISION_LOG", "audit_missed_opportunities"]
