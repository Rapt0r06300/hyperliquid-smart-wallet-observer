"""Gates de validation unifiées (walk-forward, OOS, régime, lookahead, Monte-Carlo).

Inspiré du cadre « 5 checks avant de passer live » (thread Minara) MAIS strictement
paper-only : aucun ordre réel, jamais. Compose nos modules EXISTANTS (walk_forward,
lookahead_analysis) en UN rapport de gates pass/fail + verdict global, pour valider
une config de flags en replay A/B après le run.

Chaque gate répond à une question honnête :
- sample_size : assez de trades pour que ce ne soit pas du bruit ?
- profit_factor : gross gains / gross pertes >= seuil (le juge de paix, pas le winrate) ?
- out_of_sample : l'edge tient-il sur les 30% derniers (pas seulement en in-sample) ?
- regime_robustness : le profit ne vient-il pas d'UNE seule tranche chanceuse ?
- lookahead : aucun signal n'a utilisé de donnée future (anti-leakage) ?
- monte_carlo_dd : le pire chemin (drawdown p95 sur ordres rebattus) est-il survivable ?

Un verdict DEPLOY_CANDIDATE est un verdict de RECHERCHE, jamais une promesse de PnL.
Pur, déterministe (seed). Réutilise l'existant, zéro duplication de logique lourde.
"""

from __future__ import annotations

import random
from typing import Any

from hl_observer.backtest.walk_forward import split_walk_forward


def _pnls(trades: Any) -> list[float]:
    """Extrait la liste des PnL nets (float | dict{net_pnl_usdc|pnl} | objet)."""
    out: list[float] = []
    for t in trades or ():
        v = None
        if isinstance(t, (int, float)):
            v = t
        elif isinstance(t, dict):
            v = t.get("net_pnl_usdc", t.get("pnl", t.get("net_pnl_usd")))
        else:
            v = getattr(t, "net_pnl_usdc", getattr(t, "pnl", None))
        if v is not None:
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                continue
    return out


def profit_factor(pnls: list[float]) -> float:
    wins = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    if losses <= 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def max_drawdown(pnls: list[float]) -> float:
    eq = peak = dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return dd


def _pf_str(pf: float):
    return "inf" if pf == float("inf") else round(pf, 3)


def sample_size_gate(pnls, *, min_trades: int = 30) -> dict:
    n = len(pnls)
    return {"gate": "sample_size", "passed": n >= int(min_trades), "n": n, "min": int(min_trades)}


def profit_factor_gate(pnls, *, min_pf: float = 1.1) -> dict:
    pf = profit_factor(pnls)
    return {"gate": "profit_factor", "passed": pf >= min_pf, "pf": _pf_str(pf), "min": min_pf}


def out_of_sample_gate(pnls, *, train_fraction: float = 0.7, min_oos_pf: float = 1.0) -> dict:
    train, test = split_walk_forward(pnls, train_fraction=train_fraction)
    pf_in, pf_out = profit_factor(train), profit_factor(test)
    passed = bool(test) and pf_out >= min_oos_pf
    return {"gate": "out_of_sample", "passed": passed, "pf_in_sample": _pf_str(pf_in),
            "pf_out_sample": _pf_str(pf_out), "n_test": len(test), "min_oos_pf": min_oos_pf}


def regime_robustness_gate(trades, pnls, *, buckets: int = 4, max_slice_share: float = 0.7) -> dict:
    """Découpe par régime (champ 'regime' si présent) sinon en tranches temporelles
    égales. PASS si profit net positif, ≥2 tranches, ≥2 tranches profitables, et
    aucune tranche ne fournit > max_slice_share du profit total (anti « un mois chanceux »).

    🚩 CORRIGÉ le 13/07 (#127) — CE GATE SE DÉGRADAIT EN SILENCE.

    Il cherchait un champ `regime` que **personne n'écrivait jamais** (`eval_trades` renvoie des
    floats, pas des dicts : la branche « régime » était structurellement inatteignable). Il
    retombait donc TOUJOURS sur des tranches de temps — et s'appelait quand même
    « regime_robustness ». Le nom promettait un contrôle par régime de marché ; le code faisait
    un découpage chronologique.

    Le comportement (pass/fail) est INCHANGÉ. Ce qui change : le gate **DÉCLARE** son mode.
    Une dégradation qu'on voit est une dégradation qu'on peut corriger ; une dégradation
    silencieuse est un mensonge qui dure des mois.

    Pour obtenir le vrai mode `regime`, étiqueter les trades avec
    `backtesting.regime_label.trades_etiquetes` (labels CAUSAUX, seuil calculé sur le TRAIN seul).
    """
    slices: dict[str, list[float]] = {}
    has_regime = any(isinstance(t, dict) and t.get("regime") for t in (trades or ()))
    mode = "regime" if has_regime else "tranches_temporelles_FAUTE_DE_LABEL"
    if has_regime:
        for t in trades:
            if not isinstance(t, dict):
                continue
            r = str(t.get("regime") or "?")
            v = t.get("net_pnl_usdc", t.get("pnl", 0)) or 0
            slices.setdefault(r, []).append(float(v))
    else:
        n = len(pnls)
        k = max(1, n // max(1, int(buckets)))
        for i in range(0, n, k):
            slices[f"chunk_{i // k}"] = pnls[i:i + k]
    net = sum(pnls)
    slice_net = {kk: sum(vv) for kk, vv in slices.items()}
    profitable = sum(1 for v in slice_net.values() if v > 0)
    top = max(slice_net.values()) if slice_net else 0.0
    share = (top / net) if net > 0 else 0.0
    passed = net > 0 and len(slices) >= 2 and share <= max_slice_share and profitable >= 2
    return {"gate": "regime_robustness", "passed": passed, "slices": len(slices),
            "profitable_slices": profitable, "top_slice_share": round(share, 3) if net > 0 else None,
            "max_share": max_slice_share,
            # 🚩 Le gate DIT desormais ce qu'il a fait. Tant que `mode` vaut
            # "tranches_temporelles_FAUTE_DE_LABEL", ce gate ne teste PAS la robustesse au regime :
            # il teste la robustesse dans le TEMPS. Les deux sont utiles, mais ce ne sont pas les memes.
            "mode": mode,
            "regime_labels_presents": has_regime}


def lookahead_gate(events, *, min_gap_ms: int = 0) -> dict:
    if not events:
        return {"gate": "lookahead", "passed": True, "skipped": True, "reason": "no_events"}
    try:
        from hl_observer.backtesting.lookahead_analysis import lookahead_analysis_report
        rep = lookahead_analysis_report(events, min_gap_ms=min_gap_ms)
        return {"gate": "lookahead", "passed": bool(rep.get("ok")),
                "violation_count": rep.get("violation_count", 0)}
    except Exception as exc:  # noqa: BLE001
        return {"gate": "lookahead", "passed": True, "skipped": True, "reason": str(exc)[:50]}


def monte_carlo_drawdown_gate(pnls, *, runs: int = 1000, seed: int = 7, max_p95_dd_over_net: float = 2.0) -> dict:
    """Rebat l'ordre des trades `runs` fois → distribution du pire drawdown. PASS si le
    drawdown p95 reste <= max_p95_dd_over_net × le profit net (le pire chemin est tenable)."""
    if len(pnls) < 5:
        return {"gate": "monte_carlo_dd", "passed": True, "skipped": True, "reason": "too_few_trades"}
    rng = random.Random(int(seed))
    dds = []
    for _ in range(int(runs)):
        shuffled = pnls[:]
        rng.shuffle(shuffled)
        dds.append(max_drawdown(shuffled))
    dds.sort()
    p95 = dds[int(0.95 * (len(dds) - 1))]
    net = sum(pnls)
    ratio = (p95 / net) if net > 0 else float("inf")
    passed = net > 0 and ratio <= max_p95_dd_over_net
    return {"gate": "monte_carlo_dd", "passed": passed, "p95_drawdown": round(p95, 3),
            "net": round(net, 3), "p95_dd_over_net": _pf_str(ratio), "max": max_p95_dd_over_net}


def run_validation_gates(
    trades, *, events=None, min_trades: int = 30, min_pf: float = 1.1,
    min_oos_pf: float = 1.0, seed: int = 7,
) -> dict:
    """Rapport unifié : lance tous les gates, verdict global. DEPLOY_CANDIDATE seulement
    si tous les gates critiques (non skippés) passent. Verdict de recherche, paper-only."""
    pnls = _pnls(trades)
    gates = [
        sample_size_gate(pnls, min_trades=min_trades),
        profit_factor_gate(pnls, min_pf=min_pf),
        out_of_sample_gate(pnls, min_oos_pf=min_oos_pf),
        regime_robustness_gate(trades, pnls),
        lookahead_gate(events),
        monte_carlo_drawdown_gate(pnls, seed=seed),
    ]
    critical = [g for g in gates if not g.get("skipped")]
    passed_all = bool(critical) and all(g["passed"] for g in critical)
    return {
        "verdict": "DEPLOY_CANDIDATE" if passed_all else "REJECT",
        "note": "verdict de recherche, jamais une promesse de PnL ; paper-only",
        "gates_passed": sum(1 for g in gates if g["passed"]),
        "gates_total": len(gates),
        "gates": gates,
        "real_execution": False,
    }


__all__ = [
    "run_validation_gates", "profit_factor", "max_drawdown", "sample_size_gate",
    "profit_factor_gate", "out_of_sample_gate", "regime_robustness_gate",
    "lookahead_gate", "monte_carlo_drawdown_gate",
]
