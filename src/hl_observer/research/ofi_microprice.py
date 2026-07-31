"""ALPHA — OFI + microprice + déséquilibre de carnet, mesurés sur le CARNET L2 RÉEL Hyperliquid.

Idées portées depuis la littérature microstructure (bien citées, implémentées proprement, PAS copiées) :

  * **OFI (Order Flow Imbalance)** — Cont, Kukanov & Stoikov (2014), *The price impact of order book
    events*. Le flux net au sommet du carnet (améliorations/retraits de bid et d'ask, pondérés par les
    tailles) explique et — à horizon court — précède le mouvement de mid. On l'implémente au niveau L1
    entre deux snapshots consécutifs.
  * **Microprice** — Stoikov (2018), *The micro-price: a high-frequency estimator of future prices*.
    Un mid pondéré par le déséquilibre, estimateur du mid futur. On teste `micro − mid` comme prédicteur.
  * **Déséquilibre de carnet** (queue L1 et profondeur en USD) — prédicteur directionnel court terme
    classique (Lipton/Pesavento/… ; Gould & Bonart). `imb = (bid − ask)/(bid + ask)`.

Ce module NE prétend PAS que ces effets sont tradables : il **mesure** s'ils prédisent le rendement de mid
HL sur l'horizon suivant, **net des coûts exécutables réels** (frais taker + spread courant du coin), avec
la discipline dure de la maison : split temporel DISCOVERY→FREEZE→OOS INTACT, votes rendus indépendants par
**bucket temporel** (la corrélation série à ~18 s est réelle), borne basse par bootstrap
(`following.scoring_robuste.borne_basse_confiance`). Verdict : `LCB(net)<=0` → KILL ; couverture
insuffisante → MORE_DATA ; net OOS>0 & LCB>0 → à porter en FORWARD.

Causalité stricte : toute feature au temps t n'utilise que l'état du carnet jusqu'à t ; le markout mesure
mid(t)→mid(t+h) STRICTEMENT futur, et refuse toute fenêtre qui enjambe un trou de collecte (dt > dt_max).
Pur, 0 réseau, 0 ordre réel — lit un CSV `coin,ts,bid,ask,mid,micro,bid_size,ask_size,bid_depth_usd,
ask_depth_usd,imbalance` (extrait de `runtime/replay/l2_book.*.jsonl`).
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

try:  # LCB de la maison (bootstrap) — on réutilise l'existant, on ne le réinvente pas.
    from hl_observer.following.scoring_robuste import borne_basse_confiance as _lcb_maison
except Exception:  # pragma: no cover - fallback autonome si import indisponible
    _lcb_maison = None

# Colonnes attendues du CSV extrait du carnet L2.
_COLS = ("coin", "ts", "bid", "ask", "mid", "micro", "bid_size", "ask_size",
         "bid_depth_usd", "ask_depth_usd", "imbalance")

FEATURES = ("ofi_l1", "imb_l1", "imb_depth", "micro_tilt_bps")


# ════════════════════════ chargement ════════════════════════
def charger_book_csv(path: str) -> dict[str, list[dict[str, float]]]:
    """Lit le CSV L2 → {coin: [snapshots triés par ts, dédupliqués]}. Ignore les lignes incomplètes."""
    par_coin: dict[str, list[dict[str, float]]] = {}
    with open(path, encoding="utf-8") as f:
        entete = f.readline().strip().split(",")
        idx = {c: entete.index(c) for c in _COLS if c in entete}
        if "coin" not in idx or "mid" not in idx:
            return {}
        for line in f:
            p = line.rstrip("\n").split(",")
            if len(p) < len(entete):
                continue
            try:
                coin = p[idx["coin"]]
                snap = {
                    "ts": float(p[idx["ts"]]), "bid": float(p[idx["bid"]]), "ask": float(p[idx["ask"]]),
                    "mid": float(p[idx["mid"]]),
                    "micro": float(p[idx["micro"]]) if idx.get("micro") is not None and p[idx["micro"]] else float("nan"),
                    "bid_size": float(p[idx["bid_size"]]) if idx.get("bid_size") is not None and p[idx["bid_size"]] else float("nan"),
                    "ask_size": float(p[idx["ask_size"]]) if idx.get("ask_size") is not None and p[idx["ask_size"]] else float("nan"),
                    "bid_depth": float(p[idx["bid_depth_usd"]]) if idx.get("bid_depth_usd") is not None and p[idx["bid_depth_usd"]] else float("nan"),
                    "ask_depth": float(p[idx["ask_depth_usd"]]) if idx.get("ask_depth_usd") is not None and p[idx["ask_depth_usd"]] else float("nan"),
                }
            except (ValueError, IndexError):
                continue
            if snap["mid"] > 0 and snap["bid"] > 0 and snap["ask"] >= snap["bid"]:
                par_coin.setdefault(coin, []).append(snap)
    for coin, serie in par_coin.items():
        serie.sort(key=lambda s: s["ts"])
        # dédup des snapshots au même ts (même état de carnet) : on garde le premier.
        dedup: list[dict[str, float]] = []
        vu = -1.0
        for s in serie:
            if s["ts"] != vu:
                dedup.append(s)
                vu = s["ts"]
        par_coin[coin] = dedup
    return par_coin


# ════════════════════════ features causales ════════════════════════
def ofi_l1(prev: Mapping[str, float], cur: Mapping[str, float]) -> float:
    """Incrément OFI L1 de Cont-Kukanov-Stoikov entre deux snapshots consécutifs.

    e_b = q_b·1{P_b≥P_b⁻} − q_b⁻·1{P_b≤P_b⁻} ;  e_a = q_a·1{P_a≤P_a⁻} − q_a⁻·1{P_a≥P_a⁻} ;  OFI = e_b − e_a.
    OFI>0 ⇒ pression acheteuse (bid renforcé / ask retiré-haut). Tailles en unités de base du coin.
    """
    pb, pa = prev["bid"], prev["ask"]
    cb, ca = cur["bid"], cur["ask"]
    qb0, qa0 = prev.get("bid_size", float("nan")), prev.get("ask_size", float("nan"))
    qb1, qa1 = cur.get("bid_size", float("nan")), cur.get("ask_size", float("nan"))
    if any(math.isnan(x) for x in (qb0, qa0, qb1, qa1)):
        return float("nan")
    e_b = (qb1 if cb >= pb else 0.0) - (qb0 if cb <= pb else 0.0)
    e_a = (qa1 if ca <= pa else 0.0) - (qa0 if ca >= pa else 0.0)
    return e_b - e_a


def _imb(a: float, b: float) -> float:
    s = a + b
    return (a - b) / s if s > 0 else float("nan")


def features_causaux(serie: Sequence[Mapping[str, float]], *, dt_max_feat: float = 60.0) -> list[dict[str, Any]]:
    """Pour chaque snapshot i≥1, features n'utilisant QUE l'état ≤ t : OFI L1, déséquilibres, tilt microprix.

    `dt_max_feat` : si le pas précédent enjambe un trou (> dt_max_feat s), l'OFI (qui est un flux ENTRE
    deux snapshots) est mis à NaN — on ne fabrique pas de flux à travers une coupure de collecte.
    """
    feats: list[dict[str, Any]] = []
    for i in range(1, len(serie)):
        prev, cur = serie[i - 1], serie[i]
        dt_prev = cur["ts"] - prev["ts"]
        mid = cur["mid"]
        spread_bps = (cur["ask"] - cur["bid"]) / mid * 1e4 if mid > 0 else float("nan")
        ofi = ofi_l1(prev, cur) if 0 < dt_prev <= dt_max_feat else float("nan")
        micro = cur.get("micro", float("nan"))
        micro_tilt = (micro - mid) / mid * 1e4 if (mid > 0 and not math.isnan(micro)) else float("nan")
        feats.append({
            "i": i, "ts": cur["ts"], "mid": mid, "spread_bps": spread_bps, "dt_prev": dt_prev,
            "ofi_l1": ofi,
            "imb_l1": _imb(cur.get("bid_size", float("nan")), cur.get("ask_size", float("nan"))),
            "imb_depth": _imb(cur.get("bid_depth", float("nan")), cur.get("ask_depth", float("nan"))),
            "micro_tilt_bps": micro_tilt,
        })
    return feats


# ════════════════════════ markout net (causal, non chevauchant, anti-trou) ════════════════════════
def markout_signal(feats: Sequence[Mapping[str, Any]], *, feature_key: str, seuil: float,
                   horizon_pas: int, fee_bps: float, sens: int = 1, dt_max: float = 60.0,
                   inclure_spread: bool = True) -> dict[str, Any]:
    """Markout net des évènements où |feature| ≥ seuil.

    Entrée mid(t), sortie mid(t+h) STRICTEMENT future ; direction = sens·signe(feature). Coût exécutable
    taker = `fee_bps` (+ spread courant du coin si `inclure_spread`). Fenêtres NON chevauchantes (on saute
    de h). On REFUSE toute fenêtre qui enjambe un trou (un dt interne > dt_max) — pas de rendement fabriqué.
    """
    n = len(feats)
    events: list[dict[str, Any]] = []
    t = 0
    while t < n - horizon_pas:
        f = feats[t]
        val = f.get(feature_key, float("nan"))
        if val is None or (isinstance(val, float) and math.isnan(val)) or abs(val) < seuil:
            t += 1
            continue
        # la fenêtre [t, t+h] ne doit pas enjamber de trou de collecte
        fenetre_ok = all(0 < feats[t + k]["dt_prev"] <= dt_max for k in range(1, horizon_pas + 1))
        if not fenetre_ok:
            t += 1
            continue
        mid0 = f["mid"]
        mid1 = feats[t + horizon_pas]["mid"]
        direction = float(sens) * (1.0 if val > 0 else -1.0)
        gross = direction * (mid1 / mid0 - 1.0) * 1e4
        cout = float(fee_bps) + (f["spread_bps"] if (inclure_spread and not math.isnan(f["spread_bps"])) else 0.0)
        events.append({"ts": f["ts"], "gross_bps": gross, "net_bps": gross - cout, "cout_bps": cout})
        t += horizon_pas  # observation indépendante (non chevauchante)
    if not events:
        return {"n": 0, "gross_bps": None, "net_bps": None, "events": []}
    gross = sum(e["gross_bps"] for e in events) / len(events)
    net = sum(e["net_bps"] for e in events) / len(events)
    cout = sum(e["cout_bps"] for e in events) / len(events)
    return {"n": len(events), "gross_bps": round(gross, 4), "net_bps": round(net, 4),
            "cout_moyen_bps": round(cout, 4), "events": events}


def _votes_par_bucket(events: Sequence[Mapping[str, Any]], *, bucket_s: float, cle: str = "net_bps") -> list[float]:
    """Réduit des markouts corrélés en votes INDÉPENDANTS : moyenne par bucket temporel de `bucket_s` s.

    À ~18 s d'espacement, deux markouts proches partagent le régime : on les agrège en un vote par bucket
    (même esprit qu'`agreger_en_grappes` de la maison, mais la grappe naturelle ici est le temps)."""
    par_bucket: dict[int, list[float]] = {}
    for e in events:
        b = int(float(e["ts"]) // bucket_s)
        par_bucket.setdefault(b, []).append(float(e[cle]))
    return [sum(v) / len(v) for v in par_bucket.values() if v]


def _lcb(votes: Sequence[float]) -> float | None:
    if _lcb_maison is not None:
        return _lcb_maison(votes)
    # fallback autonome : bootstrap IID de la moyenne (LCG déterministe).
    vals = [float(v) for v in votes]
    if len(vals) < 8:
        return None
    s = 1
    n = len(vals)
    moyennes = []
    for _ in range(2000):
        acc = 0.0
        for _ in range(n):
            s = (1103515245 * s + 12345) & 0x7FFFFFFF
            acc += vals[s % n]
        moyennes.append(acc / n)
    moyennes.sort()
    return round(moyennes[max(0, int(0.05 * len(moyennes)))], 6)


# ════════════════════════ diagnostic contemporain (NON tradable) ════════════════════════
def diagnostic_contemporain_ofi(feats: Sequence[Mapping[str, Any]], *, dt_max: float = 60.0) -> dict[str, Any]:
    """R² de la régression Δmid_bps[t] ~ OFI[t] (MÊME pas). Mesure que l'effet OFI→prix est RÉEL, mais
    c'est CONTEMPORAIN donc **non tradable** — sert de contrôle de cohérence, pas d'edge."""
    xs, ys = [], []
    for t in range(1, len(feats)):
        ofi = feats[t].get("ofi_l1", float("nan"))
        if ofi is None or math.isnan(ofi) or feats[t]["dt_prev"] > dt_max:
            continue
        dmid = (feats[t]["mid"] / feats[t - 1]["mid"] - 1.0) * 1e4
        xs.append(ofi)
        ys.append(dmid)
    n = len(xs)
    if n < 30:
        return {"n": n, "r2": None, "beta": None, "note": "insuffisant"}
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return {"n": n, "r2": None, "beta": None, "note": "variance nulle"}
    beta = sxy / sxx
    r = sxy / math.sqrt(sxx * syy)
    return {"n": n, "r2": round(r * r, 4), "beta": round(beta, 8),
            "note": "CONTEMPORAIN — non tradable, contrôle de cohérence seulement"}


# ════════════════════════ expérience disciplinée par feature ════════════════════════
def experience_feature(feats: Sequence[Mapping[str, Any]], *, feature_key: str, horizon_pas: int = 1,
                       fee_bps: float = 9.0, sens: int = 1, seuils: Sequence[float] | None = None,
                       fraction_decouverte: float = 0.5, bucket_s: float = 600.0,
                       dt_max: float = 60.0, n_min_oos: int = 20, inclure_spread: bool = True) -> dict[str, Any]:
    """DISCOVERY→FREEZE→OOS pour UNE feature : seuil choisi in-sample (max net), gelé, mesuré sur OOS INTACT.

    LCB calculée sur les votes indépendants (bucket temporel) de l'OOS. Aucun retune du holdout.
    """
    valides = [f for f in feats if not (isinstance(f.get(feature_key), float) and math.isnan(f.get(feature_key)))]
    if len(valides) < 200:
        return {"feature": feature_key, "verdict": "MORE_DATA", "raison": "trop peu de features valides",
                "n_valides": len(valides)}
    # bornes de seuils dérivées des quantiles absolus (data-driven mais choisies EN DÉCOUVERTE seulement).
    coupe = int(len(feats) * fraction_decouverte)
    dec, oos = feats[:coupe], feats[coupe:]
    if seuils is None:
        absv = sorted(abs(f[feature_key]) for f in dec
                      if not (isinstance(f.get(feature_key), float) and math.isnan(f.get(feature_key))))
        if len(absv) < 50:
            return {"feature": feature_key, "verdict": "MORE_DATA", "raison": "decouverte trop courte"}
        seuils = [absv[int(q * len(absv))] for q in (0.0, 0.5, 0.75, 0.9, 0.95)]
        seuils = sorted(set(round(s, 8) for s in seuils))

    # DISCOVERY : seuil qui maximise le net in-sample (avec un minimum d'obs).
    best = None
    for s in seuils:
        m = markout_signal(dec, feature_key=feature_key, seuil=s, horizon_pas=horizon_pas,
                           fee_bps=fee_bps, sens=sens, dt_max=dt_max, inclure_spread=inclure_spread)
        if m["n"] >= 15 and m["net_bps"] is not None:
            if best is None or m["net_bps"] > best[1]:
                best = (s, m["net_bps"])
    if best is None:
        return {"feature": feature_key, "verdict": "MORE_DATA", "raison": "aucun seuil exploitable en decouverte"}
    seuil_gele = best[0]

    # OOS INTACT au seuil gelé.
    mo = markout_signal(oos, feature_key=feature_key, seuil=seuil_gele, horizon_pas=horizon_pas,
                        fee_bps=fee_bps, sens=sens, dt_max=dt_max, inclure_spread=inclure_spread)
    votes = _votes_par_bucket(mo["events"], bucket_s=bucket_s) if mo["n"] else []
    lcb_net = _lcb(votes)

    if mo["n"] < n_min_oos or len(votes) < 8 or lcb_net is None:
        verdict = "MORE_DATA"
    elif lcb_net <= 0:
        verdict = "KILL"
    elif (mo["net_bps"] or 0) > 0:
        verdict = "OOS_POSITIF_A_FORWARD"
    else:
        verdict = "KILL"

    return {
        "feature": feature_key, "sens": sens, "horizon_pas": horizon_pas, "fee_bps": fee_bps,
        "seuil_gele": round(seuil_gele, 8), "seuils_testes": list(seuils),
        "n_independent_oos": mo["n"], "n_votes_independants": len(votes),
        "votes_net_oos": [round(float(v), 4) for v in votes],   # FIX-34 : distribution pour pf/es
        "gross_bps_oos": mo["gross_bps"], "net_bps_oos": mo["net_bps"],
        "cout_moyen_bps": mo.get("cout_moyen_bps"), "lcb_net_bps": lcb_net,
        "verdict": verdict, "real_execution": False,
    }


def experience_complete(serie: Sequence[Mapping[str, float]], *, coin: str = "?", horizon_pas: int = 1,
                        fee_bps: float = 9.0, dt_max: float = 60.0, bucket_s: float = 600.0,
                        fraction_decouverte: float = 0.5, inclure_spread: bool = True) -> dict[str, Any]:
    """Lance l'hypothèse de CONTINUATION (sens=+1) sur toutes les features + le diagnostic contemporain."""
    feats = features_causaux(serie, dt_max_feat=dt_max)
    res = {
        "coin": coin, "n_snapshots": len(serie), "n_features": len(feats), "horizon_pas": horizon_pas,
        "fee_bps": fee_bps, "diagnostic_ofi_contemporain": diagnostic_contemporain_ofi(feats, dt_max=dt_max),
        "par_feature": {},
    }
    for fk in FEATURES:
        res["par_feature"][fk] = experience_feature(
            feats, feature_key=fk, horizon_pas=horizon_pas, fee_bps=fee_bps, sens=1,
            fraction_decouverte=fraction_decouverte, bucket_s=bucket_s, dt_max=dt_max,
            inclure_spread=inclure_spread)
    return res


__all__ = ["charger_book_csv", "ofi_l1", "features_causaux", "markout_signal",
           "diagnostic_contemporain_ofi", "experience_feature", "experience_complete", "FEATURES"]
