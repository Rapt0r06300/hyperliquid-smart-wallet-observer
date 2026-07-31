"""ALPHA — lead-lag HL↔Binance mesuré sur tape SYNCHRONISÉE réelle (bbo_synchro).

Question : Binance mène-t-il HL ? Et si oui, le mouvement Binance prédit-il un mouvement HL EXPLOITABLE
après coûts ? On mesure, par coin, sur des rendements pas-à-pas :

  * lead-lag : corr(bin_ret[t], hl_ret[t+k]) — un pic à k>0 = HL SUIT Binance (Binance mène) ;
  * markout conditionnel : après un choc Binance ≥ seuil, rendement HL cumulé sur l'horizon suivant,
    signé dans le sens du choc = **gross bps** ; **net = gross − coût round-trip HL**.

Discipline : split temporel DISCOVERY/OOS disjoint ; le seuil est choisi sur la DÉCOUVERTE, gelé, puis
mesuré sur l'OOS INTACT. Observations INDÉPENDANTES (fenêtres non chevauchantes). LCB par bootstrap.
Verdict : `LCB(net)<=0` → KILL ; couverture insuffisante → MORE_DATA ; net OOS>0 → à porter en forward.
Pur, 0 réseau, 0 ordre réel — lit un CSV `coin,ts_ms,hl_mid,bin_mid`.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any


def charger_series(path: str) -> dict[str, list[tuple[int, float, float]]]:
    par_coin: dict[str, list[tuple[int, float, float]]] = {}
    with open(path, encoding="utf-8") as f:
        entete = f.readline()
        for line in f:
            p = line.strip().split(",")
            if len(p) != 4:
                continue
            try:
                c, ts, hl, bn = p[0], int(p[1]), float(p[2]), float(p[3])
            except ValueError:
                continue
            if hl > 0 and bn > 0:
                par_coin.setdefault(c, []).append((ts, hl, bn))
    for c in par_coin:
        par_coin[c].sort(key=lambda r: r[0])
    return par_coin


def rendements_bps(serie: Sequence[tuple[int, float, float]]) -> list[tuple[float, float]]:
    """(hl_ret_bps, bin_ret_bps) pas-à-pas."""
    out: list[tuple[float, float]] = []
    for i in range(1, len(serie)):
        _, h0, b0 = serie[i - 1]
        _, h1, b1 = serie[i]
        if h0 > 0 and b0 > 0:
            out.append(((h1 / h0 - 1.0) * 1e4, (b1 / b0 - 1.0) * 1e4))
    return out


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


def lead_lag_crosscorr(rends: Sequence[tuple[float, float]], max_lag: int = 5) -> dict[str, Any]:
    """corr(bin_ret[t], hl_ret[t+k]). Pic à k>0 ⇒ HL suit Binance (Binance mène)."""
    hl = [r[0] for r in rends]
    bn = [r[1] for r in rends]
    n = len(hl)
    corr: dict[int, float | None] = {}
    for k in range(-max_lag, max_lag + 1):
        xs, ys = [], []
        for t in range(n):
            if 0 <= t + k < n:
                xs.append(bn[t])
                ys.append(hl[t + k])
        corr[k] = _pearson(xs, ys)
    valides = {k: v for k, v in corr.items() if v is not None}
    peak = max(valides, key=lambda k: valides[k]) if valides else None
    return {"corr_par_lag": corr, "peak_lag": peak,
            "binance_mene": (peak is not None and peak > 0),
            "hl_mene": (peak is not None and peak < 0)}


def markout_conditionnel(rends: Sequence[tuple[float, float]], *, seuil_bps: float,
                         horizon_pas: int, cout_bps: float) -> dict[str, Any]:
    """Après un choc Binance ≥ seuil, rendement HL cumulé signé sur l'horizon. Fenêtres NON chevauchantes."""
    hl = [r[0] for r in rends]
    bn = [r[1] for r in rends]
    n = len(rends)
    markouts: list[float] = []
    t = 0
    while t < n - horizon_pas - 1:
        if abs(bn[t]) >= seuil_bps:
            direction = 1.0 if bn[t] > 0 else -1.0
            hl_fwd = sum(hl[t + 1: t + 1 + horizon_pas])   # mouvement HL APRÈS le choc Binance
            markouts.append(direction * hl_fwd)
            t += horizon_pas                                # observation indépendante
        else:
            t += 1
    if not markouts:
        return {"n": 0, "gross_bps": None, "net_bps": None, "markouts": []}
    gross = sum(markouts) / len(markouts)
    return {"n": len(markouts), "gross_bps": round(gross, 4),
            "net_bps": round(gross - float(cout_bps), 4), "markouts": markouts}


def _bootstrap_lcb(vals: Sequence[float], *, alpha: float = 0.05, n_boot: int = 1000, seed: int = 1) -> float | None:
    vals = list(vals)
    if len(vals) < 8:
        return None
    s = (int(seed) & 0xFFFFFFFF) or 1
    n = len(vals)
    moyennes = []
    for _ in range(n_boot):
        acc = 0.0
        for _ in range(n):
            s = (1103515245 * s + 12345) & 0x7FFFFFFF
            acc += vals[s % n]
        moyennes.append(acc / n)
    moyennes.sort()
    return round(moyennes[max(0, int(alpha * len(moyennes)))], 4)


def experience(serie: Sequence[tuple[int, float, float]], *, cout_bps: float = 9.0,
               seuils_bps: Sequence[float] = (2.0, 3.0, 5.0, 8.0, 12.0), horizon_pas: int = 3,
               fraction_decouverte: float = 0.5) -> dict[str, Any]:
    """DISCOVERY→FREEZE→OOS : choisit le seuil sur la découverte, mesure sur l'OOS INTACT. Verdict après coûts."""
    rends = rendements_bps(serie)
    n = len(rends)
    if n < 200:
        return {"verdict": "MORE_DATA", "raison": "serie trop courte", "n_rends": n}
    coupe = int(n * fraction_decouverte)
    dec, oos = rends[:coupe], rends[coupe:]

    # DISCOVERY : seuil qui maximise le net (in-sample).
    best = None
    for s in seuils_bps:
        m = markout_conditionnel(dec, seuil_bps=s, horizon_pas=horizon_pas, cout_bps=cout_bps)
        if m["net_bps"] is not None and m["n"] >= 10:
            if best is None or m["net_bps"] > best[1]:
                best = (s, m["net_bps"])
    if best is None:
        return {"verdict": "MORE_DATA", "raison": "aucun seuil avec assez d'obs en decouverte", "n_rends": n}
    seuil_gele = best[0]

    # OOS INTACT au seuil gelé.
    mo = markout_conditionnel(oos, seuil_bps=seuil_gele, horizon_pas=horizon_pas, cout_bps=cout_bps)
    ll = lead_lag_crosscorr(rends, max_lag=5)
    lcb = _bootstrap_lcb(mo["markouts"]) if mo["n"] else None
    lcb_net = (round(lcb - cout_bps, 4) if lcb is not None else None)

    if mo["n"] < 20 or lcb_net is None:
        verdict = "MORE_DATA"
    elif lcb_net <= 0:
        verdict = "KILL"
    elif (mo["net_bps"] or 0) > 0:
        verdict = "OOS_POSITIF_A_FORWARD"
    else:
        verdict = "KILL"

    return {
        "peak_lag": ll["peak_lag"], "binance_mene": ll["binance_mene"], "hl_mene": ll["hl_mene"],
        "seuil_gele_bps": seuil_gele, "horizon_pas": horizon_pas, "cout_bps": cout_bps,
        "n_independent_oos": mo["n"], "gross_bps_oos": mo["gross_bps"], "net_bps_oos": mo["net_bps"],
        "lcb_gross_bps": lcb, "lcb_net_bps": lcb_net, "verdict": verdict,
        "n_rends": n, "real_execution": False,
    }


__all__ = ["charger_series", "rendements_bps", "lead_lag_crosscorr", "markout_conditionnel", "experience"]
