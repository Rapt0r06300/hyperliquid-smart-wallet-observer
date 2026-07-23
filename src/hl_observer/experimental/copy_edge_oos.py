"""EDGE DE COPIE — SÉLECTION SUR TRAIN, VALIDATION EN WALK-FORWARD OOS (rectif Flo 23/07).

On teste PLUSIEURS seuils de taille (fraction du NAV) et PLUSIEURS horizons, on CHOISIT le couple
(seuil, horizon) UNIQUEMENT sur la période TRAIN, puis on le VALIDE sur la période OOS (postérieure,
walk-forward) contre un PLACEBO. Zéro fuite : le choix n'utilise jamais l'OOS ni un prix futur.

Entrée : ÉVÉNEMENTS d'entrée alpha (OPEN/ADD reconstruits depuis les fills, retraits exclus), chacun
portant `ts_ms, coin, direction, move_frac` ; et une tape de prix {coin: [(ts,px)]}. Un edge n'est
retenu QUE si l'OOS est net>0 ET bat le placebo. Sinon : REFUSÉ (honnête).
"""
from __future__ import annotations

from typing import Any, Iterable

from hl_observer.experimental.copy_edge_forward import rendement_forward

SEUILS_DEFAUT = (0.03, 0.05, 0.10, 0.20)
HORIZONS_DEFAUT_MS = (60_000.0, 300_000.0, 900_000.0, 3_600_000.0)


def _net_moyen(events: list[dict], tape: dict[str, list[tuple[int, float]]], horizon_ms: float,
               seuil: float, frais_bps: float) -> tuple[float, int, float]:
    """(net_moyen_bps, n, brut_moyen_bps) sur les entrées de move_frac >= seuil, appariables à la tape."""
    reels: list[float] = []
    for e in events:
        if float(e.get("move_frac", 0.0)) < seuil:
            continue
        serie = tape.get(e["coin"])
        if not serie:
            continue
        r = rendement_forward(e, serie, horizon_ms)
        if r is not None:
            reels.append(r)
    if not reels:
        return 0.0, 0, 0.0
    brut = sum(reels) / len(reels)
    return brut - frais_bps, len(reels), brut


def _placebo_moyen(events: list[dict], tape: dict[str, list[tuple[int, float]]], horizon_ms: float,
                   seuil: float, graine: int) -> float:
    import random
    rng = random.Random(graine)
    vals: list[float] = []
    for e in events:
        if float(e.get("move_frac", 0.0)) < seuil:
            continue
        serie = tape.get(e["coin"])
        if not serie or len(serie) < 3:
            continue
        t0 = serie[rng.randrange(len(serie))][0]
        r = rendement_forward({"ts_ms": t0, "direction": e["direction"]}, serie, horizon_ms)
        if r is not None:
            vals.append(r)
    return (sum(vals) / len(vals)) if vals else 0.0


def mesurer_oos(events: list[dict], tape: dict[str, list[tuple[int, float]]], *,
                seuils: Iterable[float] = SEUILS_DEFAUT, horizons_ms: Iterable[float] = HORIZONS_DEFAUT_MS,
                frais_bps: float = 12.0, frac_train: float = 0.6, min_events_train: int = 20,
                min_events_oos: int = 20, graine: int = 12345) -> dict[str, Any]:
    """Choisit (seuil, horizon) sur TRAIN, valide en OOS walk-forward vs placebo. Rend un verdict honnête."""
    ev = sorted(events, key=lambda e: int(e.get("ts_ms") or 0))
    if len(ev) < (min_events_train + min_events_oos):
        return {"statut": "NEED_MORE_DATA", "n_events": len(ev),
                "requis": min_events_train + min_events_oos, "note": "pas assez d'entrées alpha pour un split train/OOS"}
    coupe = int(len(ev) * frac_train)
    train, oos = ev[:coupe], ev[coupe:]
    # 1) SÉLECTION sur TRAIN uniquement
    grille: list[dict] = []
    for s in seuils:
        for h in horizons_ms:
            net, n, brut = _net_moyen(train, tape, h, s, frais_bps)
            if n >= min_events_train:
                grille.append({"seuil": s, "horizon_ms": h, "train_net_bps": round(net, 3),
                               "train_brut_bps": round(brut, 3), "train_n": n})
    if not grille:
        return {"statut": "NEED_MORE_DATA", "n_events": len(ev), "n_train": len(train),
                "note": "aucune combinaison (seuil,horizon) n'atteint le minimum d'entrées sur le train"}
    choix = max(grille, key=lambda g: g["train_net_bps"])
    # 2) VALIDATION en OOS (jamais touché pendant le choix) + placebo
    oos_net, oos_n, oos_brut = _net_moyen(oos, tape, choix["horizon_ms"], choix["seuil"], frais_bps)
    placebo = _placebo_moyen(oos, tape, choix["horizon_ms"], choix["seuil"], graine)
    valide = bool(oos_n >= min_events_oos and oos_net > 0 and (oos_brut - placebo) > 0)
    return {"statut": "MESURE", "n_events": len(ev), "n_train": len(train), "n_oos": len(oos),
            "choix_sur_train": choix, "grille_train": grille,
            "oos": {"seuil": choix["seuil"], "horizon_ms": choix["horizon_ms"], "n": oos_n,
                    "brut_bps": round(oos_brut, 3), "net_bps": round(oos_net, 3),
                    "placebo_bps": round(placebo, 3), "edge_vs_placebo_bps": round(oos_brut - placebo, 3)},
            "edge_valide_oos": valide, "frais_bps": frais_bps,
            "note": "Choix (seuil,horizon) sur TRAIN ; validation OOS walk-forward vs placebo. "
                    "edge_valide_oos=True seulement si OOS net>0 ET bat le placebo. Aucune fuite."}


def simuler_paper(events: list[dict], tape: dict[str, list[tuple[int, float]]], *, horizon_ms: float,
                  seuil: float, notional_usd: float, cout_ar_bps: float,
                  capital_usd: float = 1000.0) -> dict[str, Any]:
    """Simule les trades paper de copie sur des entrées (période OOS) : entre au signal, sort après
    `horizon_ms`, PnL = rendement forward − coût A/R. Rend PnL net, ROI, drawdown, capacité, trades.
    C'est un BACKTEST honnête (aucune exécution) : chaque trade est appariable à la tape ou ignoré."""
    trades: list[dict] = []
    equity = 0.0
    pic = 0.0
    dd_max = 0.0
    for e in sorted(events, key=lambda x: int(x.get("ts_ms") or 0)):
        if float(e.get("move_frac", 0.0)) < seuil:
            continue
        serie = tape.get(e["coin"])
        if not serie:
            continue
        r = rendement_forward(e, serie, horizon_ms)
        if r is None:
            continue
        pnl_bps = r - cout_ar_bps
        pnl_usd = pnl_bps / 1e4 * notional_usd
        equity += pnl_usd
        pic = max(pic, equity)
        dd_max = max(dd_max, pic - equity)
        trades.append({"ts_ms": e["ts_ms"], "coin": e["coin"], "direction": e["direction"],
                       "fwd_bps": round(r, 2), "pnl_bps": round(pnl_bps, 2), "pnl_usd": round(pnl_usd, 4)})
    n = len(trades)
    pnl = round(equity, 4)
    gagnants = sum(1 for t in trades if t["pnl_usd"] > 0)
    return {"n_trades": n, "pnl_net_usd": pnl, "roi_pct": round(pnl / capital_usd * 100, 3) if capital_usd else 0.0,
            "drawdown_usd": round(dd_max, 4), "drawdown_pct": round(dd_max / capital_usd * 100, 3) if capital_usd else 0.0,
            "winrate_pct": round(gagnants / n * 100, 1) if n else 0.0,
            "capacite_usd_par_trade": round(notional_usd, 2), "capital_usd": capital_usd,
            "profit_factor": _profit_factor(trades), "trades": trades[:50]}


def _profit_factor(trades: list[dict]) -> float:
    gains = sum(t["pnl_usd"] for t in trades if t["pnl_usd"] > 0)
    pertes = -sum(t["pnl_usd"] for t in trades if t["pnl_usd"] < 0)
    return round(gains / pertes, 3) if pertes > 0 else (float("inf") if gains > 0 else 0.0)


__all__ = ["mesurer_oos", "simuler_paper", "SEUILS_DEFAUT", "HORIZONS_DEFAUT_MS"]
