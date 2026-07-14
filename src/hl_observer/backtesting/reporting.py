"""Reporting & attribution — pur, testé. Exécution du backlog :
export_csv (IMPROVE-41), reconcile_pnl (IMPROVE-19), cost_attribution (IMPROVE-17, où part
l'argent), refusal_stats (IMPROVE-43, pourquoi on ne trade pas), ab_compare (IMPROVE-44).
Aucun ordre, aucune promesse.
"""
from __future__ import annotations

import csv
import os
from collections import Counter


def export_csv(rows, path: str, *, columns=None) -> str:
    """Exporte des lignes (dicts) en CSV pour analyse externe (Excel, pandas...)."""
    cols = list(columns) if columns else sorted({k for r in rows for k in r})
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    return path


def reconcile_pnl(snapshot: dict) -> dict:
    """Vérifie que equity == cash + latent. Toute divergence = bug de comptabilité à corriger."""
    cash = float(snapshot.get("cash_balance_usdc", 0.0))
    unreal = float(snapshot.get("unrealized_pnl_usdc", 0.0))
    equity = float(snapshot.get("equity_usdc", 0.0))
    diff = equity - (cash + unreal)
    return {"ok": abs(diff) < 1e-6, "diff": round(diff, 8)}


def cost_attribution(trades) -> dict:
    """Décompose le PnL : brut − frais − spread − slippage − dégradation = net.
    Montre EXACTEMENT où part l'argent (et donc quel coût attaquer en priorité)."""
    keys = ("gross", "fees", "spread", "slippage", "degradation")
    agg = {k: sum(float(t.get(k, 0.0)) for t in trades) for k in keys}
    cost_total = agg["fees"] + agg["spread"] + agg["slippage"] + agg["degradation"]
    agg["cost_total"] = cost_total
    agg["net"] = agg["gross"] - cost_total
    agg["cost_share"] = {
        k: (agg[k] / cost_total if cost_total > 0 else 0.0)
        for k in ("fees", "spread", "slippage", "degradation")
    }
    return agg


def refusal_stats(refusals) -> list:
    """Comptage trié des raisons de refus (NO_TRADE) — comprendre pourquoi on ne trade pas."""
    c = Counter()
    for reasons in refusals:
        for r in reasons:
            c[r] += 1
    return c.most_common()


def ab_compare(a: dict, b: dict) -> list:
    """Comparaison A/B côte à côte de deux jeux de métriques (avec delta si numérique)."""
    out = []
    for k in sorted(set(a) | set(b)):
        va, vb = a.get(k), b.get(k)
        delta = (vb - va) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else None
        out.append({"metric": k, "A": va, "B": vb, "delta": delta})
    return out
