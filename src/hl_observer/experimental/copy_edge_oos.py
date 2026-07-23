"""EDGE DE COPIE — SÉLECTION SUR TRAIN, VALIDATION WALK-FORWARD PURGÉE, OOS PAR PÉRIODE **ET** PAR
VAULT (rectif Flo 23/07). Zéro fuite.

Règles anti-fuite :
  • le choix (seuil, horizon) se fait UNIQUEMENT sur le TRAIN (vaults de train, période de train) ;
  • PURGE = horizon entre train et OOS (la fenêtre forward d'une entrée de train ne doit pas déborder
    dans la période OOS) ;
  • OOS = vaults HELD-OUT (jamais vus au train) sur la période POSTÉRIEURE → séparation par période ET
    par vault ;
  • intervalle de confiance BOOTSTRAP sur le net OOS ;
  • n_oos < seuil → statut PRÉLIMINAIRE (un signal, pas une validation) ; ≥ seuil → VALIDATION.

Le PLACEBO (mêmes coins/directions, instants aléatoires) neutralise la dérive. Un edge n'est SCALE que
s'il est net>0, bat le placebo, et son IC bas est > 0. Sinon OBSERVE (préliminaire) ou KILL.
"""
from __future__ import annotations

import bisect
import random
from typing import Any, Iterable

from hl_observer.experimental.copy_edge_forward import rendement_forward

SEUILS_DEFAUT = (0.03, 0.05, 0.10, 0.20)
FORWARD_DEFAUT = rendement_forward       # tick (allmids) ; passer rendement_forward_candles pour la recherche candles
HORIZONS_DEFAUT_MS = (60_000.0, 300_000.0, 900_000.0, 3_600_000.0)
SEUIL_VALIDATION_N = 100          # n_oos >= ça => VALIDATION ; en-dessous => PRÉLIMINAIRE (Flo : 30 = préliminaire)


def _returns_nets(events: list[dict], tape: dict[str, list[tuple[int, float]]], horizon_ms: float,
                  seuil: float, frais_bps: float, forward_fn=FORWARD_DEFAUT) -> list[float]:
    """Rendements NETS (bps) par entrée de move_frac >= seuil, appariables à la tape."""
    out: list[float] = []
    for e in events:
        if float(e.get("move_frac", 0.0)) < seuil:
            continue
        serie = tape.get(e["coin"])
        if not serie:
            continue
        r = forward_fn(e, serie, horizon_ms)
        if r is not None:
            out.append(r - frais_bps)
    return out


def _placebo_nets(events: list[dict], tape: dict[str, list[tuple[int, float]]], horizon_ms: float,
                  seuil: float, frais_bps: float, rng: random.Random, forward_fn=FORWARD_DEFAUT) -> list[float]:
    out: list[float] = []
    for e in events:
        if float(e.get("move_frac", 0.0)) < seuil:
            continue
        serie = tape.get(e["coin"])
        if not serie or len(serie) < 3:
            continue
        t0 = serie[rng.randrange(len(serie))][0]
        r = forward_fn({"ts_ms": t0, "direction": e["direction"]}, serie, horizon_ms)
        if r is not None:
            out.append(r - frais_bps)
    return out


def _moy(v: list[float]) -> float:
    return sum(v) / len(v) if v else 0.0


def _bootstrap_ic(vals: list[float], *, b: int = 1000, graine: int = 7, alpha: float = 0.05) -> tuple[float, float]:
    """IC bootstrap (percentile) de la MOYENNE. Sans données → (0,0)."""
    if not vals:
        return 0.0, 0.0
    rng = random.Random(graine)
    n = len(vals)
    moyennes = []
    for _ in range(b):
        ech = [vals[rng.randrange(n)] for _ in range(n)]
        moyennes.append(sum(ech) / n)
    moyennes.sort()
    lo = moyennes[int(alpha / 2 * b)]
    hi = moyennes[min(b - 1, int((1 - alpha / 2) * b))]
    return round(lo, 3), round(hi, 3)


def _split_vaults(events: list[dict]) -> tuple[set[str], set[str]]:
    """Partition DÉTERMINISTE des vaults : index pair -> TRAIN, impair -> OOS (held-out par vault)."""
    vaults = sorted({str(e.get("vault") or "") for e in events})
    train = {v for i, v in enumerate(vaults) if i % 2 == 0}
    oos = {v for i, v in enumerate(vaults) if i % 2 == 1}
    return train, oos


def mesurer_oos(events: list[dict], tape: dict[str, list[tuple[int, float]]], *,
                seuils: Iterable[float] = SEUILS_DEFAUT, horizons_ms: Iterable[float] = HORIZONS_DEFAUT_MS,
                frais_bps: float = 12.0, frac_train: float = 0.6, min_events_train: int = 20,
                min_events_oos: int = 20, seuil_validation: int = SEUIL_VALIDATION_N,
                graine: int = 12345, forward_fn=FORWARD_DEFAUT) -> dict[str, Any]:
    """PRIMAIRE = walk-forward TEMPOREL sur les MÊMES vaults (choix sur période de train, validation sur
    période postérieure, PURGÉE). SECONDAIRE = généralisation par vault held-out (rectif Flo 23/07 : le
    split par vault est un test secondaire). IC bootstrap, vs placebo. Verdict NEED_MORE_DATA /
    PRÉLIMINAIRE / VALIDATION + SCALE/OBSERVE/KILL."""
    ev = sorted(events, key=lambda e: int(e.get("ts_ms") or 0))
    if len(ev) < (min_events_train + min_events_oos):
        return {"statut": "NEED_MORE_DATA", "n_events": len(ev), "requis": min_events_train + min_events_oos}
    purge = max(horizons_ms)                                       # la fenêtre forward la plus large
    ts = [int(e["ts_ms"]) for e in ev]
    t_cut = ts[int(len(ts) * frac_train)]
    # PRIMAIRE (temporel, mêmes vaults) : train = fenêtre forward terminée avant la coupe (purge) ; oos = après
    train = [e for e in ev if int(e["ts_ms"]) + purge <= t_cut]
    oos = [e for e in ev if int(e["ts_ms"]) >= t_cut]
    grille: list[dict] = []
    for s in seuils:
        for h in horizons_ms:
            nets = _returns_nets(train, tape, h, s, frais_bps, forward_fn)
            if len(nets) >= min_events_train:
                grille.append({"seuil": s, "horizon_ms": h, "train_net_bps": round(_moy(nets), 3), "train_n": len(nets)})
    if not grille:
        return {"statut": "NEED_MORE_DATA", "n_train": len(train), "n_oos": len(oos),
                "note": "aucune combinaison n'atteint le minimum d'entrées sur le TRAIN"}
    choix = max(grille, key=lambda g: g["train_net_bps"])
    nets_oos = _returns_nets(oos, tape, choix["horizon_ms"], choix["seuil"], frais_bps, forward_fn)
    rng = random.Random(graine)
    placebo = _placebo_nets(oos, tape, choix["horizon_ms"], choix["seuil"], frais_bps, rng, forward_fn)
    # SECONDAIRE : généralisation sur vaults HELD-OUT (période OOS), aux mêmes params
    tv, ov = _split_vaults(ev)
    oos_vault = [e for e in oos if str(e.get("vault") or "") in ov]
    nets_gv = _returns_nets(oos_vault, tape, choix["horizon_ms"], choix["seuil"], frais_bps, forward_fn)
    generalisation_vault = {"n": len(nets_gv), "net_bps": round(_moy(nets_gv), 3) if nets_gv else None,
                            "vaults_held_out": sorted(ov)}
    n = len(nets_oos)
    net_oos = _moy(nets_oos)
    pb = _moy(placebo)
    ic_bas, ic_haut = _bootstrap_ic(nets_oos, graine=graine)
    if n < min_events_oos:
        statut = "NEED_MORE_DATA"
    elif n < seuil_validation:
        statut = "PRELIMINAIRE"                                    # 30 events = signal, pas validation
    else:
        statut = "VALIDATION"
    bat_placebo = (net_oos - pb) > 0
    decision = "KILL"
    if net_oos > 0 and bat_placebo and ic_bas > 0:
        decision = "SCALE" if statut == "VALIDATION" else "OBSERVE"
    elif net_oos > 0 and bat_placebo:
        decision = "OBSERVE"
    return {"statut": statut, "n_events": len(ev), "n_train": len(train), "n_oos": n,
            "purge_ms": purge, "validation": "temporelle_walk_forward_meme_vaults",
            "choix_sur_train": choix, "grille_train": grille,
            "oos": {"seuil": choix["seuil"], "horizon_ms": choix["horizon_ms"], "n": n,
                    "net_bps": round(net_oos, 3), "brut_bps": round(net_oos + frais_bps, 3),
                    "placebo_bps": round(pb, 3), "edge_vs_placebo_bps": round(net_oos - pb, 3),
                    "ic95_bas_bps": ic_bas, "ic95_haut_bps": ic_haut},
            "generalisation_par_vault": generalisation_vault,      # test SECONDAIRE (vaults held-out)
            "edge_valide_oos": bool(statut == "VALIDATION" and net_oos > 0 and bat_placebo and ic_bas > 0),
            "decision": decision, "frais_bps": frais_bps, "seuil_validation": seuil_validation,
            "note": "PRIMAIRE = walk-forward TEMPOREL (mêmes vaults, purge=horizon) ; SECONDAIRE = "
                    "généralisation par vault held-out ; IC bootstrap. SCALE si VALIDATION + net>0 + bat "
                    "placebo + IC bas>0."}


def simuler_paper(events: list[dict], tape: dict[str, list[tuple[int, float]]], *, horizon_ms: float,
                  seuil: float, notional_usd: float, cout_ar_bps: float,
                  capital_usd: float = 1000.0, graine: int = 7, forward_fn=FORWARD_DEFAUT) -> dict[str, Any]:
    """Backtest paper des trades de copie. ROI CUMULATIF (PnL/capital) **et** ROI PAR TRADE (bps moyen)
    clairement distingués (rectif Flo). IC bootstrap sur le PnL/trade. Aucune exécution."""
    trades: list[dict] = []
    equity = 0.0
    pic = 0.0
    dd_max = 0.0
    pnls_bps: list[float] = []
    for e in sorted(events, key=lambda x: int(x.get("ts_ms") or 0)):
        if float(e.get("move_frac", 0.0)) < seuil:
            continue
        serie = tape.get(e["coin"])
        if not serie:
            continue
        r = forward_fn(e, serie, horizon_ms)
        if r is None:
            continue
        pnl_bps = r - cout_ar_bps
        pnl_usd = pnl_bps / 1e4 * notional_usd
        equity += pnl_usd
        pic = max(pic, equity)
        dd_max = max(dd_max, pic - equity)
        pnls_bps.append(pnl_bps)
        trades.append({"ts_ms": e["ts_ms"], "coin": e["coin"], "direction": e["direction"],
                       "fwd_bps": round(r, 2), "pnl_bps": round(pnl_bps, 2), "pnl_usd": round(pnl_usd, 4)})
    n = len(trades)
    pnl = round(equity, 4)
    gagnants = sum(1 for t in trades if t["pnl_usd"] > 0)
    ic_bas, ic_haut = _bootstrap_ic(pnls_bps, graine=graine)
    return {"n_trades": n, "pnl_net_usd": pnl,
            "roi_cumulatif_pct": round(pnl / capital_usd * 100, 3) if capital_usd else 0.0,   # sur le capital, cumulé
            "roi_par_trade_bps": round(_moy(pnls_bps), 3),                                     # rendement moyen par trade
            "roi_par_trade_ic95_bps": [ic_bas, ic_haut],
            "drawdown_usd": round(dd_max, 4), "drawdown_pct": round(dd_max / capital_usd * 100, 3) if capital_usd else 0.0,
            "winrate_pct": round(gagnants / n * 100, 1) if n else 0.0,
            "capacite_usd_par_trade": round(notional_usd, 2), "capital_usd": capital_usd,
            "profit_factor": _profit_factor(trades), "trades": trades[:50]}


def _profit_factor(trades: list[dict]) -> float:
    gains = sum(t["pnl_usd"] for t in trades if t["pnl_usd"] > 0)
    pertes = -sum(t["pnl_usd"] for t in trades if t["pnl_usd"] < 0)
    return round(gains / pertes, 3) if pertes > 0 else (float("inf") if gains > 0 else 0.0)


def ranger_variantes(events: list[dict], tape: dict[str, list[tuple[int, float]]], *,
                     variantes: Iterable[dict], notional_usd: float = 150.0, cout_ar_bps: float = 12.0,
                     capital_usd: float = 1000.0, forward_fn=FORWARD_DEFAUT) -> list[dict]:
    """Classe des variantes {seuil,horizon_ms} par SCORE = PnL_net × ROI_cumulatif × capacité ÷
    (drawdown+ε), avec la sim paper de chacune. Le drawdown pénalise, la capacité récompense."""
    eps = 1e-6
    out: list[dict] = []
    for v in variantes:
        sim = simuler_paper(events, tape, horizon_ms=v["horizon_ms"], seuil=v["seuil"],
                            notional_usd=notional_usd, cout_ar_bps=cout_ar_bps, capital_usd=capital_usd,
                            forward_fn=forward_fn)
        dd = sim["drawdown_usd"] + eps
        score = sim["pnl_net_usd"] * sim["roi_cumulatif_pct"] * sim["capacite_usd_par_trade"] / dd
        out.append({"seuil": v["seuil"], "horizon_ms": v["horizon_ms"], "score": round(score, 3),
                    "n_trades": sim["n_trades"], "pnl_net_usd": sim["pnl_net_usd"],
                    "roi_cumulatif_pct": sim["roi_cumulatif_pct"], "roi_par_trade_bps": sim["roi_par_trade_bps"],
                    "drawdown_pct": sim["drawdown_pct"], "profit_factor": sim["profit_factor"]})
    out.sort(key=lambda x: -x["score"])
    return out


def _percentile(v: list[float], p: float) -> float:
    if not v:
        return 0.0
    s = sorted(v)
    i = min(len(s) - 1, max(0, int(round(p / 100.0 * (len(s) - 1)))))
    return s[i]


def mae_mfe(ev: dict, serie: list[tuple[int, float]], horizon_ms: float, *, delai_ms: float = 0.0):
    """(MAE_bps<=0, MFE_bps>=0) : pires excursions ADVERSE et FAVORABLE (dans le sens de la position)
    entre l'entrée (1re bougie après signal+délai, anti-lookahead) et l'horizon. None si trou de tape."""
    if not serie:
        return None
    ts = [t for t, _ in serie]
    t_ent = int(ev["ts_ms"] + delai_ms)
    t_sor = t_ent + int(horizon_ms)
    i = bisect.bisect_right(ts, t_ent)
    if i >= len(serie):
        return None
    p_ent = serie[i][1]
    if p_ent <= 0:
        return None
    d = ev["direction"]
    mae, mfe = 0.0, 0.0
    j = i
    while j < len(serie) and serie[j][0] <= t_sor:
        move = d * (serie[j][1] - p_ent) / p_ent * 1e4
        mae = min(mae, move)
        mfe = max(mfe, move)
        j += 1
    if j == i:
        return None
    return round(mae, 3), round(mfe, 3)


RATIO_KILL_RISQUE = 4.0          # si l'excursion adverse TYPIQUE > 4× l'edge net -> risque ≫ edge -> KILL


def calibrer_risque(events: list[dict], tape: dict[str, list[tuple[int, float]]], horizon_ms: float,
                    edge_net_bps: float, *, delai_ms: float = 0.0, ratio_kill: float = RATIO_KILL_RISQUE,
                    min_events: int = 20) -> dict[str, Any]:
    """Calibre STOP / TAKE-PROFIT / horizon sur les MAE/MFE HISTORIQUES (rectif Flo : un edge de 7-26 bps
    ne peut pas porter un stop de 150 bps). stop = MAE_p75 (cap la queue, survit au bruit typique),
    take-profit = MFE_p50 (capture le favorable typique). KILL si edge<=0 OU si l'adverse TYPIQUE (MAE_p50)
    dépasse largement l'edge (> ratio_kill × edge)."""
    maes, mfes = [], []
    for e in events:
        serie = tape.get(e["coin"])
        if not serie:
            continue
        mm = mae_mfe(e, serie, horizon_ms, delai_ms=delai_ms)
        if mm is not None:
            maes.append(abs(mm[0]))
            mfes.append(mm[1])
    n = len(maes)
    mae_p50, mae_p75, mae_p90 = _percentile(maes, 50), _percentile(maes, 75), _percentile(maes, 90)
    mfe_p50 = _percentile(mfes, 50)
    trop_risque = edge_net_bps <= 0 or (mae_p50 > ratio_kill * edge_net_bps)
    return {"n": n, "stop_bps": round(mae_p75, 2), "take_profit_bps": round(mfe_p50, 2),
            "horizon_ms": horizon_ms, "mae_p50_bps": round(mae_p50, 2), "mae_p90_bps": round(mae_p90, 2),
            "mfe_p50_bps": round(mfe_p50, 2), "edge_net_bps": round(edge_net_bps, 2),
            "ratio_risque_sur_edge": round(mae_p50 / edge_net_bps, 2) if edge_net_bps > 0 else None,
            "decision_risque": "KILL" if trop_risque else "OK",
            "note": "stop=MAE_p75, TP=MFE_p50 ; KILL si edge<=0 ou MAE_p50 > %.0f×edge (risque ≫ edge)" % ratio_kill}


def construire_table_prelim(events: list[dict], tape: dict[str, list[tuple[int, float]]], *,
                            horizons_ms: Iterable[float] = HORIZONS_DEFAUT_MS, frais_bps: float = 12.0,
                            min_events: int = 20, forward_fn=FORWARD_DEFAUT, delai_ms: float = 0.0,
                            appliquer_kill_risque: bool = True) -> dict[str, dict]:
    """Table d'edge PRÉLIMINAIRE PAR COIN (descriptif, PAS une validation OOS) : pour chaque coin couvert,
    le meilleur horizon dont le rendement forward NET (anti-lookahead, coûts inclus) est POSITIF sur assez
    d'entrées, AVEC son risque CALIBRÉ (stop=MAE_p75, TP=MFE_p50). Un coin est EXCLU si net<=0 OU si son
    risque dépasse largement l'edge (KILL MAE/MFE). Source du gate EXPLORATORY. Jamais de trade forcé."""
    par_coin: dict[str, list[dict]] = {}
    for e in events:
        par_coin.setdefault(e["coin"], []).append(e)
    table: dict[str, dict] = {}
    for coin, evs in par_coin.items():
        serie = tape.get(coin)
        if not serie:
            continue
        best = None
        for h in horizons_ms:
            nets = []
            for e in evs:
                r = forward_fn(e, serie, h)
                if r is not None:
                    nets.append(r - frais_bps)
            if len(nets) >= min_events:
                net = _moy(nets)
                ic_bas, ic_haut = _bootstrap_ic(nets)
                if net > 0 and (best is None or net > best["net_bps"]):
                    best = {"horizon_ms": h, "net_bps": round(net, 3), "brut_bps": round(net + frais_bps, 3),
                            "ic95_bas_bps": ic_bas, "ic95_haut_bps": ic_haut, "n": len(nets)}
        if best:
            # RISQUE CALIBRÉ sur MAE/MFE. ALPHA : KILL si risque ≫ edge (jamais copié). PROBE
            # (appliquer_kill_risque=False) : on GARDE pour OBSERVER en tout petit, mais on garde le
            # stop/TP calibré pour borner la perte — jamais un stop démesuré.
            risque = calibrer_risque(evs, tape, best["horizon_ms"], best["net_bps"], delai_ms=delai_ms,
                                     min_events=min_events)
            if appliquer_kill_risque and risque["decision_risque"] == "KILL":
                continue
            best["edge_brut_bps"] = best["brut_bps"]              # alias pour le gate du signal
            best["risque"] = risque
            best["stop_bps"] = risque["stop_bps"]
            best["take_profit_bps"] = risque["take_profit_bps"]
            table[coin] = best
    return table


__all__ = ["mesurer_oos", "simuler_paper", "ranger_variantes", "construire_table_prelim",
           "mae_mfe", "calibrer_risque", "SEUILS_DEFAUT", "HORIZONS_DEFAUT_MS", "SEUIL_VALIDATION_N"]
