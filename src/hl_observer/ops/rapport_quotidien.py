"""Q-243 — Rapport quotidien automatique frais et performance.

Génère un résumé structuré de la journée : PnL, frais, positions,
alertes et métriques clés. PAPER / READ-ONLY.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def build_daily_summary(
    *,
    pnl_usd: float = 0.0,
    fees_usd: float = 0.0,
    trades_count: int = 0,
    positions_open: int = 0,
    max_drawdown_pct: float = 0.0,
    uptime_pct: float = 0.0,
    alerts: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construit le résumé quotidien structuré."""
    report: dict[str, Any] = {
        "date": time.strftime("%Y-%m-%d"),
        "ts": time.time(),
        "pnl_usd": round(pnl_usd, 4),
        "fees_usd": round(fees_usd, 4),
        "pnl_net_usd": round(pnl_usd - fees_usd, 4),
        "trades_count": trades_count,
        "positions_open": positions_open,
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "uptime_pct": round(uptime_pct, 2),
        "alerts": alerts or [],
    }
    if extra:
        report["extra"] = extra
    return report


def save_daily_report(report: dict[str, Any]) -> Path | None:
    """Sauvegarde le rapport dans runtime/reports/."""
    root = Path(os.environ.get("HYPERSMART_RUNTIME_ROOT", "runtime"))
    out_dir = root / "reports"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        date_str = report.get("date", time.strftime("%Y-%m-%d"))
        path = out_dir / f"rapport_{date_str}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Rapport quotidien sauvegardé → %s", path)
        return path
    except OSError as exc:
        logger.warning("Impossible de sauvegarder le rapport quotidien : %s", exc)
        return None


__all__ = ["build_daily_summary", "save_daily_report"]
