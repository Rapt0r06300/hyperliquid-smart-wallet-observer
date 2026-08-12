"""Honest, separate economic scoreboards for the three active paper families.

This module only summarizes evidence already written by the read-only/paper
runtime.  Missing measurements stay ``None`` and therefore can never produce a
PROMOTE verdict.  It does not create signals, fills, positions, or PnL.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "hypersmart.economic_family_scoreboards.v1"
ACTIVE_FAMILIES = ("copy_vault", "lead_lag", "cross_venue_dislocation_v2")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _integer(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number >= 0 else None


def _empty_row(family: str) -> dict[str, Any]:
    return {
        "family": family,
        "signal_count": None,
        "no_trade_count": None,
        "top_no_trade_reasons": [],
        "closed_positions": None,
        "gross_pnl_usd": None,
        "fees_usd": None,
        "spread_cost_usd": None,
        "slippage_cost_usd": None,
        "latency_cost_usd": None,
        "net_pnl_usd": None,
        "roi_pct": None,
        "max_drawdown_usd": None,
        "hit_rate": None,
        "profit_factor": None,
        "in_sample": None,
        "oos": None,
        "forward": None,
        "placebos": None,
        "liquidatable_net": None,
        "verdict": "MORE_DATA",
        "verdict_reasons": [],
        "evidence_paths": [],
        "real_execution": False,
    }


def promotion_verdict(row: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Apply the deny-by-default promotion contract to one family row."""
    if str(row.get("source_verdict") or "").upper() == "KILL":
        return "KILL", ["SOURCE_EVIDENCE_KILL"]

    required_numeric = (
        "closed_positions",
        "net_pnl_usd",
        "roi_pct",
        "max_drawdown_usd",
        "hit_rate",
        "profit_factor",
    )
    missing = [key for key in required_numeric if _number(row.get(key)) is None]
    for segment in ("oos", "forward", "placebos"):
        if not isinstance(row.get(segment), Mapping):
            missing.append(segment)
    if row.get("liquidatable_net") is not True:
        missing.append("liquidatable_net")
    if missing:
        return "MORE_DATA", [f"UNMEASURED:{key}" for key in missing]

    closed = int(float(row["closed_positions"]))
    oos_net = _number((row["oos"] or {}).get("net_pnl_usd"))
    forward_net = _number((row["forward"] or {}).get("net_pnl_usd"))
    placebo_beaten = (row["placebos"] or {}).get("beaten") is True
    if closed < 30:
        return "MORE_DATA", ["INSUFFICIENT_CLOSED_SAMPLE"]
    if (
        float(row["net_pnl_usd"]) <= 0
        or oos_net is None
        or oos_net <= 0
        or forward_net is None
        or forward_net <= 0
        or not placebo_beaten
    ):
        return "KILL", ["ROBUST_NET_EDGE_NOT_PROVEN"]
    return "PROMOTE", []


def _copy_vault(root: Path) -> dict[str, Any]:
    row = _empty_row("copy_vault")
    path = root / "runtime" / "data" / "copy_edge_rapport_reel.json"
    report = _load_json(path)
    measure = report.get("mesure") if isinstance(report.get("mesure"), dict) else {}
    if report:
        row["evidence_paths"].append(path.relative_to(root).as_posix())
        row["signal_count"] = _integer(report.get("n_entrees_alpha"))
        row["in_sample"] = {"sample_count": _integer(measure.get("n_train"))}
        row["oos"] = {"sample_count": _integer(measure.get("n_oos")), "net_pnl_usd": None}
        row["forward"] = None
        row["source_status"] = str(measure.get("statut") or "MORE_DATA")
        row["source_note"] = str(measure.get("note") or "")
    row["verdict"], row["verdict_reasons"] = promotion_verdict(row)
    return row


def _lead_lag(root: Path) -> dict[str, Any]:
    row = _empty_row("lead_lag")
    evidence_path = root / "runtime" / "audit" / "v2_lead_lag" / "lead_lag_shadow_frozen.json"
    status_path = root / "runtime" / "data" / "lead_lag_event_runtime_status.json"
    evidence = _load_json(evidence_path)
    status = _load_json(status_path)
    if evidence:
        row["evidence_paths"].append(evidence_path.relative_to(root).as_posix())
        frozen = evidence.get("frozen_evidence") if isinstance(evidence.get("frozen_evidence"), dict) else {}
        samples = frozen.get("sample_n_by_horizon") if isinstance(frozen.get("sample_n_by_horizon"), dict) else {}
        row["signal_count"] = sum(_integer(value) or 0 for value in samples.values())
        row["in_sample"] = {"sample_count": row["signal_count"]}
        row["source_status"] = str(frozen.get("source_status") or "MORE_DATA")
    if status:
        row["evidence_paths"].append(status_path.relative_to(root).as_posix())
        row["runtime_enabled"] = bool(status.get("enabled"))
        row["runtime_code"] = str(status.get("code") or "")
        row["no_trade_count"] = (_integer(status.get("rejected")) or 0)
    row["verdict"], row["verdict_reasons"] = promotion_verdict(row)
    return row


def _cross_venue(root: Path) -> dict[str, Any]:
    row = _empty_row("cross_venue_dislocation_v2")
    path = root / "docs" / "audit" / "CROSS_VENUE_DISLOCATION_FINAL_verdict.json"
    report = _load_json(path)
    realistic = report.get("verdict_realiste_16bps") if isinstance(report.get("verdict_realiste_16bps"), dict) else {}
    if report:
        row["evidence_paths"].append(path.relative_to(root).as_posix())
        row["signal_count"] = _integer(report.get("n_trades"))
        row["closed_positions"] = _integer(realistic.get("n_trades"))
        row["net_pnl_usd"] = _number(realistic.get("net_total_usd"))
        drawdown = _number(realistic.get("dd_usd"))
        row["max_drawdown_usd"] = abs(drawdown) if drawdown is not None else None
        row["profit_factor"] = _number(realistic.get("pf"))
        row["source_verdict"] = str(realistic.get("verdict") or "")
        row["in_sample"] = {
            "median_first_half_bps": _number(realistic.get("median_moitie1_bps")),
            "median_second_half_bps": _number(realistic.get("median_moitie2_bps")),
        }
        # Depth/capacity was absent in the cited evidence, so liquidation remains unproven.
        row["liquidatable_net"] = False
    row["verdict"], row["verdict_reasons"] = promotion_verdict(row)
    return row


def build_scoreboards(root: str | Path = ".") -> dict[str, Any]:
    project_root = Path(root).resolve()
    rows = [_copy_vault(project_root), _lead_lag(project_root), _cross_venue(project_root)]
    return {
        "schema_version": SCHEMA_VERSION,
        "families": {row["family"]: row for row in rows},
        "active_families": list(ACTIVE_FAMILIES),
        "disabled_families": ["cross_venue_dislocation_v1", "carry"],
        "starting_capital_usd": 1000.0,
        "paper_read_only": True,
        "real_execution": False,
    }


def export_scoreboards(root: str | Path = ".", output: str | Path | None = None) -> Path:
    project_root = Path(root).resolve()
    target = Path(output) if output is not None else project_root / "runtime" / "reports" / "economic_family_scoreboards.json"
    if not target.is_absolute():
        target = project_root / target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(build_scoreboards(project_root), indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(target)
    return target


__all__ = [
    "ACTIVE_FAMILIES",
    "SCHEMA_VERSION",
    "build_scoreboards",
    "export_scoreboards",
    "promotion_verdict",
]
