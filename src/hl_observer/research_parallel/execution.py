"""LOT 3 — exécution CAUSALE + décision du labo (Flo 25/07). Cœur PUR, testable sans réseau.

Règles dures : entrée = 1re cotation reçue APRÈS (ts_signal + latence) — jamais antérieure, jamais « la plus
proche » ; bid/ask RÉEL exécutable ; frais + slippage + latence ; épisodes INDÉPENDANTS ; 2 moitiés
temporelles + leave-one-out + PLACEBO (entrées aléatoires) + IC bootstrap (borne basse).

Décisions :
  KILL            : net médian ≤ 0 ou PF < 1 ;
  SHADOW          : prometteur mais < 10 épisodes causaux OU pas assez robuste ;
  ARM_MICROCOHORTE: ≥10 épisodes causaux ET net médian + dans LES DEUX moitiés ET PF > 1,2 ET positif
                    sans le meilleur épisode (5-10 $, max 1 position/plugin) ;
  SCALE           : INTERDIT avant ≥30 épisodes ET borne basse IC OOS > 0.
"""
from __future__ import annotations

import random
import statistics
from bisect import bisect_right

LATENCE_MS = 400.0
FRAICHEUR_MS = 3000.0
FEE_AR_BPS = 9.0            # 1 jambe HL taker A/R (~4,5×2)
SLIPPAGE_BPS = 1.0


def net_causal(signal: dict, prix: list, *, horizon_s: int, latence_ms=LATENCE_MS, fraicheur_ms=FRAICHEUR_MS,
               fee_ar_bps=FEE_AR_BPS, slippage_bps=SLIPPAGE_BPS):
    """Net d'UN signal au bid/ask réel. `prix` = [(ts_ms, bid, ask)] trié. Entrée = 1re cotation strictement
    APRÈS ts_signal+latence (jamais avant) ; sortie = 1re cotation à/après entrée+horizon. sens+1 long
    (achat ask -> vente bid). None si pas de cotation causale fraîche (NON_MESURABLE)."""
    temps = [p[0] for p in prix]
    seuil = signal["ts_ms"] + latence_ms
    i = bisect_right(temps, seuil)
    if i >= len(prix) or prix[i][0] - seuil > fraicheur_ms:
        return None
    te, be, ae = prix[i]
    j = bisect_right(temps, te + horizon_s * 1000 - 1)
    if j >= len(prix) or prix[j][0] - (te + horizon_s * 1000) > fraicheur_ms:
        return None
    ts2, bs, as_ = prix[j]
    if signal["sens"] > 0:
        brut = (bs - ae) / ae * 1e4
    else:
        brut = (be - as_) / be * 1e4
    return round(brut - fee_ar_bps - slippage_bps, 4)


def episodes_causaux(signaux: list, prix_par_coin: dict, *, horizon_s: int, **kw) -> list[dict]:
    """Mesure chaque signal -> épisodes {ts, coin, variante, sens, net_bps}. Ignore les NON_MESURABLE."""
    out = []
    for s in signaux:
        prix = prix_par_coin.get(s["coin"]) or []
        if len(prix) < 2:
            continue
        net = net_causal(s, prix, horizon_s=horizon_s, **kw)
        if net is None:
            continue
        out.append({"ts_ms": s["ts_ms"], "coin": s["coin"], "variante": s.get("variante"),
                    "sens": s["sens"], "net_bps": net})
    return out


def _pf(nets):
    pos = sum(x for x in nets if x > 0); neg = sum(-x for x in nets if x < 0)
    return round(pos / neg, 3) if neg > 0 else (float("inf") if pos > 0 else 0.0)


def placebo(prix_par_coin: dict, *, horizon_s: int, n: int = 200, graine: int = 7, **kw) -> dict:
    """Baseline : n entrées ALÉATOIRES (coin+temps+sens aléatoires) mesurées pareil. Le signal doit BATTRE
    ça (sinon il ne capture que le mouvement de fond). Rend {median_bps, n}."""
    rng = random.Random(graine)
    coins = [c for c, p in prix_par_coin.items() if len(p) > 5]
    nets = []
    for _ in range(n):
        if not coins:
            break
        c = rng.choice(coins)
        p = prix_par_coin[c]
        k = rng.randint(0, len(p) - 2)
        sig = {"ts_ms": p[k][0], "coin": c, "sens": rng.choice((1, -1))}
        v = net_causal(sig, p, horizon_s=horizon_s, **kw)
        if v is not None:
            nets.append(v)
    return {"median_bps": round(statistics.median(nets), 3) if nets else None, "n": len(nets)}


def ic_bootstrap_bas(nets: list, *, iters: int = 2000, alpha: float = 0.05, graine: int = 11):
    """Borne BASSE de l'IC (1-alpha) de la médiane par bootstrap. None si trop peu d'échantillons."""
    if len(nets) < 8:
        return None
    rng = random.Random(graine)
    meds = []
    for _ in range(iters):
        ech = [nets[rng.randrange(len(nets))] for _ in range(len(nets))]
        meds.append(statistics.median(ech))
    meds.sort()
    return round(meds[int(alpha * len(meds))], 3)


def decision(episodes: list, *, placebo_median=None, min_arm: int = 10, min_scale: int = 30,
             notional_usd: float = 10.0) -> dict:
    """Décision d'une VARIANTE à partir de ses épisodes causaux (triés par temps pour les 2 moitiés)."""
    n = len(episodes)
    nets = [e["net_bps"] for e in episodes]
    if n < min_arm:
        return {"decision": "SHADOW", "motif": "INSUFFISANT", "n": n, "requis": min_arm,
                "net_median_bps": round(statistics.median(nets), 3) if nets else None, "pf": _pf(nets)}
    tri = sorted(episodes, key=lambda e: e["ts_ms"])
    m = n // 2
    n1 = [e["net_bps"] for e in tri[:m]]
    n2 = [e["net_bps"] for e in tri[m:]]
    med = statistics.median(nets); med1 = statistics.median(n1); med2 = statistics.median(n2)
    meilleur = max(range(n), key=lambda i: nets[i])
    med_loo = statistics.median([x for i, x in enumerate(nets) if i != meilleur])
    pf = _pf(nets); ic_bas = ic_bootstrap_bas(nets)
    cum = pic = dd = 0.0
    for e in tri:
        cum += e["net_bps"] / 1e4 * notional_usd; pic = max(pic, cum); dd = min(dd, cum - pic)
    bat_placebo = placebo_median is None or med > placebo_median
    robuste = med1 > 0 and med2 > 0 and pf > 1.2 and med_loo > 0 and bat_placebo
    if med <= 0 or pf < 1.0:
        dec = "KILL"
    elif n >= min_scale and ic_bas is not None and ic_bas > 0 and robuste:
        dec = "SCALE"
    elif robuste:
        dec = "ARM_MICROCOHORTE"
    else:
        dec = "SHADOW"
    return {"decision": dec, "n": n, "net_median_bps": round(med, 3), "net_moyen_bps": round(sum(nets) / n, 3),
            "net_median_usd": round(statistics.median([e["net_bps"] / 1e4 * notional_usd for e in episodes]), 5),
            "pf": pf, "dd_usd": round(dd, 4), "ic_bas_bps": ic_bas,
            "median_moitie1_bps": round(med1, 3), "median_moitie2_bps": round(med2, 3),
            "median_sans_meilleur_bps": round(med_loo, 3),
            "placebo_median_bps": placebo_median, "bat_placebo": bat_placebo}


__all__ = ["net_causal", "episodes_causaux", "placebo", "ic_bootstrap_bas", "decision",
           "LATENCE_MS", "FEE_AR_BPS"]
