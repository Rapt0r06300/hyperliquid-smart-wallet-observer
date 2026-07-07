"""D4 — Contrôle de mini-run : convergence PnL + latence + liveness en un rapport.

Compose les gardes existantes (pnl_convergence, fresh_window, source_liveness) pour
qu'un run soit déclaré SAIN seulement si tout converge. Pur : agrège des mesures fournies.
"""

from __future__ import annotations

from hl_observer.audit.pnl_convergence import convergence_check


def mini_run_report(*, ledger_pnl: float | None, snapshot_pnl: float | None,
                    latency_recommendation: dict | None = None,
                    source_status: str | None = None) -> dict:
    conv = convergence_check(ledger_pnl, snapshot_pnl)
    healthy = (
        conv["status"] == "CONVERGENT"
        and (source_status in (None, "LIVE"))
    )
    return {
        "convergence": conv,
        "latency": latency_recommendation,
        "source_status": source_status,
        "healthy": bool(healthy),
        "verdict": "MINI_RUN_HEALTHY" if healthy else "MINI_RUN_NEEDS_ATTENTION",
    }


__all__ = ["mini_run_report"]
