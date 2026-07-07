"""R15 — Verificateur de convergence PnL : ledger == snapshot/dashboard.

Compare le PnL realise agrege depuis le ledger (logs jsonl, via pnl_from_logs)
au PnL rapporte par le snapshot/dashboard. Rend CONVERGENT / DIVERGENT /
INSUFFICIENT_DATA. Read-only, pur (hors lecture de fichier). Ne maquille rien :
donnee manquante -> INSUFFICIENT_DATA, jamais une fausse convergence.
"""

from __future__ import annotations

from hl_observer.backtest.experiment_runner import summarize_pnl
from hl_observer.backtest.pnl_from_logs import load_realized_pnls

DEFAULT_ABS_TOL = 1e-6
DEFAULT_REL_TOL = 1e-4


def convergence_check(
    ledger_total_pnl: float | None,
    snapshot_total_pnl: float | None,
    *,
    abs_tol: float = DEFAULT_ABS_TOL,
    rel_tol: float = DEFAULT_REL_TOL,
) -> dict:
    if ledger_total_pnl is None or snapshot_total_pnl is None:
        return {"status": "INSUFFICIENT_DATA", "gap": None,
                "ledger": ledger_total_pnl, "snapshot": snapshot_total_pnl}
    gap = float(ledger_total_pnl) - float(snapshot_total_pnl)
    scale = max(abs(float(ledger_total_pnl)), abs(float(snapshot_total_pnl)), 1.0)
    convergent = abs(gap) <= max(abs_tol, rel_tol * scale)
    return {
        "status": "CONVERGENT" if convergent else "DIVERGENT",
        "gap": round(gap, 8),
        "ledger": round(float(ledger_total_pnl), 8),
        "snapshot": round(float(snapshot_total_pnl), 8),
    }


def convergence_from_logs(
    ledger_path: str,
    snapshot_total_pnl: float | None,
    *,
    pnl_key: str = "estimated_net_pnl_usdc",
    **tol,
) -> dict:
    """Agrege le ledger depuis un log jsonl et le compare au PnL snapshot fourni."""
    pnls = load_realized_pnls(ledger_path, pnl_key=pnl_key)
    if not pnls:
        return {"status": "INSUFFICIENT_DATA", "gap": None, "ledger": None,
                "snapshot": snapshot_total_pnl, "reason": "NO_CLOSED_TRADES_IN_LEDGER"}
    ledger_total = summarize_pnl(pnls).total_pnl
    out = convergence_check(ledger_total, snapshot_total_pnl, **tol)
    out["trades"] = len(pnls)
    return out


__all__ = ["convergence_check", "convergence_from_logs", "DEFAULT_ABS_TOL", "DEFAULT_REL_TOL"]
