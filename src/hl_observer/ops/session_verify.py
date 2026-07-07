"""OPS-2 — Vérité complète: verdict GO/NO-GO agrégé avant chaque session.

Agrège les résultats des vérifications (pytest, safety-audit, doctor, audit ledger)
en un verdict unique horodaté. Pur: reçoit les résultats, décide. Empêche les
régressions silencieuses (ex: un modèle jamais sauvegardé, un flag mort).
"""

from __future__ import annotations


def go_no_go(checks: dict) -> dict:
    """checks = {'pytest': bool, 'safety_audit': bool, 'doctor': bool, 'ledger_ok': bool, ...}"""
    blocking = ("pytest", "safety_audit", "no_real_trade")
    results = {k: bool(v) for k, v in (checks or {}).items()}
    failed_blocking = [k for k in blocking if k in results and not results[k]]
    failed_other = [k for k, v in results.items() if not v and k not in blocking]
    verdict = "GO" if not failed_blocking else "NO_GO"
    return {
        "verdict": verdict,
        "blocking_failures": failed_blocking,
        "non_blocking_warnings": failed_other,
        "all_checks": results,
        "safe_to_run": verdict == "GO",
        "note": "NO_GO si une vérif bloquante échoue (tests, safety, no-real-trade)",
    }


__all__ = ["go_no_go"]
