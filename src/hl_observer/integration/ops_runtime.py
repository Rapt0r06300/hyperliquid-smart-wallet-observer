"""A6 — Runtime OPS: alertes, backup planifié, coût des refus pour le dashboard.

Compose operator_alerts (santé), state_backup (snapshot périodique), refusal_cost +
refusal_live (panneau refus enrichi du coût). Fournit un payload prêt pour le dashboard
v2 et une écriture d'alertes gardée. Pur/gardé. Câblage = appeler build_ops_payload()
dans /api/simulation/status et maybe_backup() sur throttle.
"""

from __future__ import annotations

import os
import time

from hl_observer.ops.operator_alerts import alerts_summary, evaluate_alerts
from hl_observer.ops.state_backup import backup_state
from hl_observer.ui.refusal_live import build_live_refusal_breakdown
from hl_observer.validation.refusal_cost import refusal_cost_by_reason


def _on(flag: str) -> bool:
    return str(os.getenv(flag, "0")).strip().lower() in {"1", "true", "yes", "on"}


def build_ops_payload(
    *, status: dict, ledger_events: list[dict], now_ms: int,
    refusal_shadow_rows: list[dict] | None = None, prev_boot_id: str | None = None,
) -> dict:
    """Payload dashboard: alertes + breakdown des refus + coût par gate."""
    alerts = evaluate_alerts(status, now_ms=now_ms, prev_boot_id=prev_boot_id)
    breakdown = build_live_refusal_breakdown(ledger_events)
    cost = refusal_cost_by_reason(refusal_shadow_rows or [])
    # fusionne le coût dans le breakdown par raison
    cost_by = {r["reason"]: r for r in cost["rows"]}
    for row in breakdown["rows"]:
        c = cost_by.get(row["reason"])
        if c:
            row["net_benefit_usdc"] = c["net_benefit_usdc"]
            row["verdict"] = c["verdict"]
    return {
        "alerts": alerts,
        "alerts_summary": alerts_summary(alerts),
        "refusal_breakdown": breakdown,
        "costly_gates": cost.get("costly_gates", []),
        "read_only": True,
    }


_LAST_BACKUP_MS = 0


def maybe_backup(state: dict, path: str, *, min_interval_ms: int = 300_000) -> dict:
    """Snapshot throttlé de l'état (flag HYPERSMART_OPS_BACKUP)."""
    global _LAST_BACKUP_MS
    if not _on("HYPERSMART_OPS_BACKUP"):
        return {"ok": False, "reason": "BACKUP_OFF"}
    now = int(time.time() * 1000)
    if now - _LAST_BACKUP_MS < min_interval_ms:
        return {"ok": False, "reason": "THROTTLED"}
    try:
        res = backup_state(state, path)
        _LAST_BACKUP_MS = now
        return res
    except Exception:
        return {"ok": False, "reason": "BACKUP_FAILED_NONBLOCKING"}


__all__ = ["build_ops_payload", "maybe_backup"]
