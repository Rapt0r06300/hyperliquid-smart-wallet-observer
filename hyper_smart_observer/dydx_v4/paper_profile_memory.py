from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DECISION_LOG = "logs/structured/decisions.jsonl"
_CACHE: dict[str, Any] = {"path": None, "ts": 0.0, "profiles": {}}


@dataclass(frozen=True)
class PaperProfileBias:
    sample_count: int
    positive_rate: float
    gain_loss_ratio: float
    net_usdc: float
    opportunity_delta: float
    risk_delta: float
    size_multiplier: float
    hard_block: bool
    reasons: list[str]
    notes: list[str]
    read_only: bool = True
    paper_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_count": self.sample_count,
            "positive_rate": round(self.positive_rate, 6),
            "gain_loss_ratio": round(self.gain_loss_ratio, 6),
            "net_usdc": round(self.net_usdc, 6),
            "opportunity_delta": round(self.opportunity_delta, 6),
            "risk_delta": round(self.risk_delta, 6),
            "size_multiplier": round(self.size_multiplier, 6),
            "hard_block": self.hard_block,
            "reasons": list(self.reasons),
            "notes": list(self.notes),
            "read_only": self.read_only,
            "paper_only": self.paper_only,
        }


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    data = row.get("payload") or row.get("data") or row
    return data if isinstance(data, dict) else row


def _event(row: dict[str, Any]) -> str:
    p = _payload(row)
    return str(row.get("event_type") or row.get("type") or p.get("event_type") or p.get("type") or "")


def _key(data: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(data.get("market_id") or data.get("market") or "UNKNOWN"),
        str(data.get("side") or data.get("direction") or "UNKNOWN").upper(),
        str(data.get("data_source") or data.get("source") or "UNKNOWN").lower(),
    )


def _load_rows(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def build_profile_table(path: str | Path = DEFAULT_DECISION_LOG) -> dict[tuple[str, str, str], dict[str, float]]:
    table: dict[tuple[str, str, str], dict[str, float]] = {}
    for row in _load_rows(path):
        if _event(row) != "PAPER_CLOSE":
            continue
        data = _payload(row)
        net = _num(data.get("net_pnl_usdc") or data.get("net_pnl"))
        key = _key(data)
        item = table.setdefault(key, {"count": 0.0, "positive": 0.0, "gain": 0.0, "loss": 0.0, "net": 0.0})
        item["count"] += 1.0
        item["net"] += net
        if net > 0:
            item["positive"] += 1.0
            item["gain"] += net
        elif net < 0:
            item["loss"] += abs(net)
    return table


def cached_profile_table(path: str | Path = DEFAULT_DECISION_LOG, ttl_s: float = 30.0) -> dict[tuple[str, str, str], dict[str, float]]:
    now = time.time()
    p = str(path)
    if _CACHE.get("path") == p and now - float(_CACHE.get("ts") or 0.0) <= ttl_s:
        return dict(_CACHE.get("profiles") or {})
    table = build_profile_table(path)
    _CACHE.update({"path": p, "ts": now, "profiles": table})
    return table


def profile_bias_for(
    market_id: str,
    direction: str,
    source: str,
    *,
    path: str | Path = DEFAULT_DECISION_LOG,
    min_samples: int = 12,
) -> PaperProfileBias:
    table = cached_profile_table(path)
    item = table.get((str(market_id), str(direction).upper(), str(source).lower()))
    if not item:
        return PaperProfileBias(0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, False, [], ["profile_memory_no_sample"])
    count = int(item["count"])
    positive_rate = item["positive"] / item["count"] if item["count"] else 0.0
    ratio = item["gain"] / item["loss"] if item["loss"] > 0 else (999.0 if item["gain"] > 0 else 0.0)
    net = item["net"]
    if count < min_samples:
        return PaperProfileBias(count, positive_rate, ratio, net, 0.0, 0.0, 1.0, False, [], ["profile_memory_warming_up"])
    reasons: list[str] = []
    notes: list[str] = []
    opportunity_delta = 0.0
    risk_delta = 0.0
    size = 1.0
    hard_block = False
    if positive_rate >= 0.56 and ratio >= 1.20 and net > 0:
        opportunity_delta = 8.0
        risk_delta = -4.0
        size = 1.10
        notes.append("profile_memory_preferred")
    elif positive_rate < 0.48 or ratio < 1.0 or net < 0:
        opportunity_delta = -6.0
        risk_delta = 14.0
        size = 0.45
        reasons.append("PROFILE_MEMORY_REDUCE")
        if count >= 30 and positive_rate < 0.43 and ratio < 0.90 and net < 0:
            hard_block = True
            size = 0.0
            reasons.append("PROFILE_MEMORY_BLOCK")
    else:
        notes.append("profile_memory_neutral")
    return PaperProfileBias(count, positive_rate, ratio, net, opportunity_delta, risk_delta, size, hard_block, reasons, notes)


__all__ = ["DEFAULT_DECISION_LOG", "PaperProfileBias", "build_profile_table", "cached_profile_table", "profile_bias_for"]
