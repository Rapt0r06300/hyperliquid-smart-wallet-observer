"""LEAD-LAG SHADOW — Binance mène, HL suit ? Mesure NETTE, méthodo gelée (23/07, chantier ARB).

Corrections méthodo de Flo, AVANT la collecte :
  1. HL n'émet le BBO que quand il change sur un bloc -> on MESURE d'abord la distribution réelle des
     intervalles entre messages (`distribution_intervalles`) et on ne GARDE un horizon que si la
     donnée permet de l'observer (`horizons_observables` : un horizon < ~2× l'intervalle médian HL
     est illusoire, on le jette).
  2. Le CHOC se détecte sur les TRADES Binance (aggTrade), pas sur le mid BBO ; l'ENTRÉE se simule au
     bid/ask HL réellement dispo (demi-spread réel), avec la profondeur au top ; horloge MONOTONE.
  3. Coins, horizons, seuils, critère de réussite GELÉS avant le live-forward (`geler_config`) — on ne
     les réajuste pas après avoir vu le PnL.
  4. On mesure l'espérance nette, la CAPACITÉ, le DRAWDOWN et la STABILITÉ PAR PÉRIODE — pas le winrate.

Coins de CONTRÔLE gardés : si le contrôle gagne autant, c'est un artefact d'horloge, pas un edge.
PAPER/shadow only : mesurer n'est pas trader.
"""
from __future__ import annotations

import bisect
import json
import statistics as st
from pathlib import Path
from typing import Any

TAPE = Path("runtime") / "data" / "bbo_tape.jsonl"
CONFIG_GELE = Path("runtime") / "data" / "lead_lag_config_gele.json"
SEUIL_CHOC_BPS = 8.0
FRAIS_SLIPPAGE_BPS = 6.0
HORIZONS_MS = (50.0, 100.0, 250.0, 500.0, 1000.0)
MIN_CHOCS = 30
N_PERIODES = 4                     # pour juger la stabilité dans le temps


def charger_tape(root: str | Path) -> dict[str, dict[str, list]]:
    """{coin: {'HL':[(ns,mid,bid,ask)], 'BIN':[(ns,mid)], 'TRADE':[(ns,px,dir)]}} trié."""
    from collections import defaultdict
    p = Path(root) / TAPE
    if not p.exists():
        return {}
    par: dict[str, dict[str, list]] = defaultdict(lambda: {"HL": [], "BIN": [], "TRADE": []})
    for l in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            d = json.loads(l)
            coin = str(d["coin"]).upper(); r = int(d["recu_ns"])
        except (KeyError, TypeError, ValueError):
            continue
        v = d.get("venue")
        if v == "HL":
            m = _flt(d.get("mid"))
            if m:
                par[coin]["HL"].append((r, m, _flt(d.get("bid")) or m, _flt(d.get("ask")) or m))
        elif v == "BIN":
            m = _flt(d.get("mid"))
            if m:
                par[coin]["BIN"].append((r, m))
        elif v == "BIN_TRADE":
            px = _flt(d.get("px"))
            if px:
                par[coin]["TRADE"].append((r, px, 1.0 if d.get("side") == "BUY" else -1.0))
    for c in par:
        for k in par[c]:
            par[c][k].sort()
    return dict(par)


def _flt(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def distribution_intervalles(evenements: list) -> dict[str, float]:
    """Percentiles (ms) des intervalles entre messages — DIT si un horizon est observable."""
    ns = [e[0] for e in evenements]
    if len(ns) < 5:
        return {"n": len(ns), "p50_ms": None, "p90_ms": None}
    d = sorted((ns[i] - ns[i - 1]) / 1e6 for i in range(1, len(ns)))
    return {"n": len(ns), "p50_ms": round(d[len(d) // 2], 2),
            "p90_ms": round(d[int(len(d) * 0.9)], 2), "p99_ms": round(d[int(len(d) * 0.99)], 2)}


def horizons_observables(dist_hl: dict, horizons) -> list[float]:
    """On ne garde un horizon que s'il est >= 2× l'intervalle médian HL : sinon la 'réaction' à cet
    horizon n'est PAS observable (HL n'a pas encore réémis). C'est le garde-fou n°1 de Flo."""
    p50 = dist_hl.get("p50_ms")
    if not p50:
        return []
    return [h for h in horizons if h >= 2.0 * p50]


FENETRE_GROUPE_MS = 100.0          # deux chocs à moins de ça = le MÊME mouvement -> groupés (1 seul)


def detecter_chocs(trades: list, *, seuil_bps: float,
                   fenetre_groupe_ms: float = FENETRE_GROUPE_MS) -> list[tuple[int, float]]:
    """Chocs exécutables depuis les TRADES Binance : un saut de prix >= seuil entre trades consécutifs.
    Les chocs qui SE CHEVAUCHENT (< fenetre_groupe_ms) sont GROUPÉS en un seul (sinon on compte 5 fois
    le même mouvement et on gonfle l'échantillon). Retour [(recu_ns, direction)]."""
    out = []
    dernier_ns = -1e30
    for i in range(1, len(trades)):
        if trades[i - 1][1] <= 0:
            continue
        mv = (trades[i][1] - trades[i - 1][1]) / trades[i - 1][1] * 1e4
        if abs(mv) < seuil_bps:
            continue
        t = trades[i][0]
        if (t - dernier_ns) / 1e6 < fenetre_groupe_ms:        # chevauche le choc précédent -> groupé
            continue
        out.append((t, 1.0 if mv > 0 else -1.0))
        dernier_ns = t
    return out


def _hl_a(hl: list, t_ns: int) -> tuple | None:
    i = bisect.bisect_right([e[0] for e in hl], t_ns) - 1
    return hl[i] if i >= 0 else None


def net_par_horizon(hl: list, chocs: list, *, frais_slippage_bps: float,
                    horizons_ms) -> dict[float, list[tuple[float, float]]]:
    """Pour chaque choc, (net_bps, capacité_usd) forward HL par horizon. ENTRÉE au côté cher, SORTIE au
    côté défavorable (bid/ask HL RÉELS des deux côtés — le spread est payé aller ET retour, pas modélisé
    par un forfait). Cœur PUR (testable)."""
    out: dict[float, list] = {h: [] for h in horizons_ms}
    for t0, direction in chocs:
        e0 = _hl_a(hl, t0)
        if e0 is None:
            continue
        entree = e0[3] if direction > 0 else e0[2]             # long -> on paie l'ASK ; short -> le BID
        if entree <= 0:
            continue
        for h in horizons_ms:
            eh = _hl_a(hl, t0 + int(h * 1e6))
            if eh is None or eh[0] <= e0[0]:
                continue
            sortie = eh[2] if direction > 0 else eh[3]         # long -> on sort au BID ; short -> à l'ASK
            net = (sortie - entree) / entree * 1e4 * direction - frais_slippage_bps
            out[h].append((net, e0[2]))                        # capacité proxy = prix (taille au top ailleurs)
    return out


def _metriques(nets: list[float], *, n_periodes: int) -> dict[str, Any]:
    """Espérance, drawdown du cumul, et stabilité PAR PÉRIODE (pas le winrate)."""
    esper = st.mean(nets)
    cum, pic, dd = 0.0, 0.0, 0.0
    for x in nets:
        cum += x; pic = max(pic, cum); dd = min(dd, cum - pic)
    taille = max(1, len(nets) // n_periodes)
    periodes = [nets[i:i + taille] for i in range(0, len(nets), taille)]
    moys = [st.mean(p) for p in periodes if p]
    return {"esperance_nette_bps": round(esper, 3), "n": len(nets),
            "drawdown_cumule_bps": round(dd, 2),
            "periodes_positives": "%d/%d" % (sum(1 for m in moys if m > 0), len(moys)),
            "stable": all(m > 0 for m in moys)}


def backtest(root: str | Path = ".", *, seuil_choc_bps: float = SEUIL_CHOC_BPS,
             frais_slippage_bps: float = FRAIS_SLIPPAGE_BPS, horizons_ms=HORIZONS_MS,
             coins_controle: tuple = (), min_chocs: int = MIN_CHOCS) -> dict[str, Any]:
    """Verdict lead-lag NET par horizon (gaté par l'observable), par coin, test vs contrôle, avec
    espérance/capacité/drawdown/stabilité. NEED_MORE_DATA tant que trop peu de chocs."""
    tape = charger_tape(root)
    if not tape:
        return {"strategie": "lead_lag_shadow", "statut": "NEED_MORE_DATA", "detail": "tape vide"}
    controle = {c.upper() for c in coins_controle}
    # 1) cadence HL PAR COIN (jamais poolée : l'interleaving de N coins donne un p50 illusoire ~0 ms
    #    et ferait croire que 50/100 ms sont observables alors qu'HL n'emet ~qu'aux 100 ms PAR coin).
    p50s = [d["p50_ms"] for ev in tape.values() if len(ev["HL"]) >= 5
            and (d := distribution_intervalles(ev["HL"]))["p50_ms"]]
    med_p50 = st.median(p50s) if p50s else None
    dist = {"p50_ms_par_coin_median": round(med_p50, 2) if med_p50 else None, "n_coins_mesures": len(p50s)}
    horizons = [h for h in horizons_ms if med_p50 and h >= 2.0 * med_p50]
    if not horizons:
        return {"strategie": "lead_lag_shadow", "statut": "NEED_MORE_DATA",
                "intervalles_hl": dist, "detail": "aucun horizon observable (HL trop lent / peu de data)"}
    # 2) chocs sur trades -> net par horizon, séparé test/contrôle
    import random
    test: dict[float, list] = {h: [] for h in horizons}
    ctrl: dict[float, list] = {h: [] for h in horizons}
    placebo: dict[float, list] = {h: [] for h in horizons}     # directions MÉLANGÉES -> doit donner ~0
    cap: list[float] = []
    for coin, ev in tape.items():
        chocs = detecter_chocs(ev["TRADE"], seuil_bps=seuil_choc_bps)
        if not chocs or len(ev["HL"]) < 3:
            continue
        nets = net_par_horizon(ev["HL"], chocs, frais_slippage_bps=frais_slippage_bps, horizons_ms=horizons)
        cible = ctrl if coin in controle else test
        for h in horizons:
            cible[h].extend(x[0] for x in nets[h])
        if coin not in controle:
            for h in horizons:
                cap.extend(x[1] for x in nets[h])
            rng = random.Random(20260723)                      # placebo REPRODUCTIBLE : mêmes t0, sens aléatoire
            faux = [(t0, 1.0 if rng.random() > 0.5 else -1.0) for t0, _ in chocs]
            netpl = net_par_horizon(ev["HL"], faux, frais_slippage_bps=frais_slippage_bps, horizons_ms=horizons)
            for h in horizons:
                placebo[h].extend(x[0] for x in netpl[h])
    n_test = max((len(v) for v in test.values()), default=0)
    if n_test < min_chocs:
        return {"strategie": "lead_lag_shadow", "statut": "NEED_MORE_DATA", "chocs_test": n_test,
                "cible": min_chocs, "intervalles_hl": dist, "horizons_observables": horizons}
    par_h = {h: _metriques(v, n_periodes=N_PERIODES) for h, v in test.items() if v}
    ctrl_h = {h: round(st.mean(v), 3) for h, v in ctrl.items() if v}
    plac_h = {h: round(st.mean(v), 3) for h, v in placebo.items() if v}
    # KEEP seulement si : espérance>0, STABLE par période, ET bat le PLACEBO (sinon = artefact d'horloge)
    gagnants = {h: r for h, r in par_h.items()
                if r["esperance_nette_bps"] > 0 and r["stable"]
                and r["esperance_nette_bps"] > plac_h.get(h, 0.0)}
    return {"strategie": "lead_lag_shadow",
            "statut": "PROMETTEUR" if gagnants else "PAS_D_EDGE",
            "intervalles_hl": dist, "horizons_observables": horizons,
            "capacite_mediane_usd": round(st.median(cap), 2) if cap else None,
            "net_par_horizon": par_h, "controle_par_horizon": ctrl_h, "placebo_par_horizon": plac_h,
            "avertissement": "Choc sur trades Binance ; entrée demi-spread HL réel + frais/slippage ; "
                             "horizons GATÉS par l'observable ; stabilité par période. Contrôle > 0 = "
                             "artefact d'horloge. Sub-seconde souvent gagnée par des racers co-localisés."}


def geler_config(root: str | Path = ".", *, coins: list[str], coins_controle: list[str],
                 horizons_ms=HORIZONS_MS, seuil_choc_bps: float = SEUIL_CHOC_BPS,
                 frais_slippage_bps: float = FRAIS_SLIPPAGE_BPS) -> dict[str, Any]:
    """GÈLE coins/horizons/seuils/critère AVANT le live-forward. On lira CE fichier, jamais des seuils
    réajustés après avoir vu le PnL (anti-cherry-picking)."""
    import time
    cfg = {"gele_ts": time.time(), "coins": [c.upper() for c in coins],
           "coins_controle": [c.upper() for c in coins_controle], "horizons_ms": list(horizons_ms),
           "seuil_choc_bps": seuil_choc_bps, "frais_slippage_bps": frais_slippage_bps,
           "critere_reussite": "esperance_nette_bps > 0 ET stable sur toutes les périodes ET contrôle <= 0",
           "min_chocs": MIN_CHOCS}
    p = Path(root) / CONFIG_GELE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp"); tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    import os
    os.replace(tmp, p)
    return cfg


__all__ = ["SEUIL_CHOC_BPS", "FRAIS_SLIPPAGE_BPS", "HORIZONS_MS", "charger_tape",
           "distribution_intervalles", "horizons_observables", "detecter_chocs",
           "net_par_horizon", "backtest", "geler_config"]
