"""GAP VALID — Coût des refus: chiffrer le PnL manqué par chaque gate (anti-blocage).

Le souci de Flo: "trop d'interdictions risque de nous bloquer". La réponse honnête
= des DONNÉES. Pour chaque raison de refus, on agrège le PnL shadow qu'auraient fait
les trades refusés (fourni par refused_shadow_extract). Un gate qui refuse surtout
des trades PERDANTS est bon; un gate qui refuse surtout des GAGNANTS coûte cher et
doit être desserré. Pur.
"""

from __future__ import annotations

from collections import defaultdict


def refusal_cost_by_reason(refusal_shadow_rows: list[dict]) -> dict:
    """refusal_shadow_rows = [{'reason', 'shadow_net_pnl_usdc'}] (refus + PnL contrefactuel)."""
    agg: dict[str, dict] = defaultdict(lambda: {"n": 0, "would_have_won": 0, "missed_pnl_usdc": 0.0, "avoided_loss_usdc": 0.0})
    for r in refusal_shadow_rows or []:
        if not isinstance(r, dict):
            continue
        reason = str(r.get("reason") or "UNKNOWN")
        pnl = float(r.get("shadow_net_pnl_usdc") or 0.0)
        a = agg[reason]
        a["n"] += 1
        if pnl > 0:
            a["would_have_won"] += 1
            a["missed_pnl_usdc"] += pnl        # coût: on a refusé un gagnant
        else:
            a["avoided_loss_usdc"] += -pnl     # bénéfice: on a évité un perdant
    rows = []
    for reason, a in agg.items():
        net = round(a["avoided_loss_usdc"] - a["missed_pnl_usdc"], 6)  # >0 = gate rentable
        rows.append({
            "reason": reason, "refused": a["n"],
            "would_have_won": a["would_have_won"],
            "missed_pnl_usdc": round(a["missed_pnl_usdc"], 6),
            "avoided_loss_usdc": round(a["avoided_loss_usdc"], 6),
            "net_benefit_usdc": net,
            "verdict": "GATE_PAYS_OFF" if net >= 0 else "GATE_TOO_STRICT_COSTS_PNL",
        })
    rows.sort(key=lambda r: r["net_benefit_usdc"])  # les plus coûteux d'abord
    return {"rows": rows,
            "costly_gates": [r["reason"] for r in rows if r["net_benefit_usdc"] < 0],
            "honesty": "coût contrefactuel sur marks réels; un gate coûteux mérite examen, pas suppression aveugle"}


__all__ = ["refusal_cost_by_reason"]
