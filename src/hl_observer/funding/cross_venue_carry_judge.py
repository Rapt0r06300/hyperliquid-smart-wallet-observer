"""JUGE SIGNÉ DU CARRY CROSS-VENUE — par coin, pas la moyenne de l'univers (23/07, nouveau cap).

LE DÉFAUT CORRIGÉ. `tools/mesurer_dispersion_venues.py` jugeait le cross-venue sur la MÉDIANE de
`|dispersion|` de TOUT l'univers → noyée par ~200 majors collés au plancher → incapable de distinguer
un carry PROPRE (DASH : d stable +0,2 bph, base 2 bps, les deux jambes paient) d'un PIÈGE (GAS :
+1,5 bph brut mais base 10 bps qui DÉRIVE et FLIPPE en <72 h — le Sharpe −7,40 net du papier MDPI
2227-7390/14/2/346). Le brut élevé EST le piège.

CE QUE CE JUGE MESURE, PAR COIN (données réelles `dispersion_venues.jsonl` : hl_px/bin_px + funding
synchrones à chaque tick — donc la BASE est mesurable, contrairement à ce que disait le vieux
commentaire « carnet trop épars ») :
  * `d = hl_bps_h − bin_bps_h` SIGNÉ dans la direction stable (funding encaissé net/heure) ;
  * PERSISTANCE du signe (un carry vit de la persistance, pas de la demi-vie du bruit) ;
  * la BASE prix (hl_px − bin_px) : médiane (appariement) + écart-type (risque delta-neutre réel) ;
  * NET@hold = `|d|×hold − (cout_carnet_AR + frais)` — coûts RÉELS des deux jambes, jamais un forfait ;
  * coupe OOS : le net doit rester POSITIF sur la 2ᵉ moitié temporelle (jamais vue à la sélection).

EXCLUSIONS (deny-by-default) : jambe figée (bin à une valeur = artefact VINE/MAVIA) ; base médiane
> plafond (instrument mal jumelé, STABLE +29 bps) ; persistance sous le plancher ; coût inconnu
(pas de carnet → net NON calculable → NON promu, signalé `COUT_INCONNU`).

PAPER only : juger n'est pas passer un ordre. Aucune promesse : brut ≠ net, et la fenêtre est courte.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hl_observer.funding.cross_venue_carry_paper import VENUES_RELPATH, couts_carnet

MAX_BASE_MEDIANE_BPS = 15.0        # au-delà = appariement suspect (pas le même instrument)
MIN_PERSIST = 0.90                 # 90 % du temps du bon côté, sinon le signe n'est pas fiable
FRAIS_AR_BPS = 6.6                 # frais all-in des deux jambes (aller-retour), approx conservatrice
HOLD_DEFAUT_H = 168.0             # 7 j : l'horizon d'un carry qui amortit son entrée
MIN_OBS = 300


def charger_series(root: str | Path) -> dict[str, list[tuple[float, float, float, float, float]]]:
    """{coin: [(ts, hl_px, bin_px, hl_bps_h, bin_bps_h)]} chronologique. Ligne incomplète -> ignorée."""
    from collections import defaultdict
    p = Path(root) / VENUES_RELPATH
    if not p.exists():
        return {}
    par: dict[str, list] = defaultdict(list)
    with p.open(encoding="utf-8", errors="ignore") as f:
        for l in f:
            try:
                d = json.loads(l)
                c = str(d["coin"]).upper()
                row = (float(d["ts"]), float(d.get("hl_px") or 0.0), float(d.get("bin_px") or 0.0),
                       float(d["hl_bps_h"]), float(d["bin_bps_h"]))
            except (KeyError, TypeError, ValueError):
                continue
            par[c].append(row)
    for c in par:
        par[c].sort()
    return dict(par)


def _stats(serie: list[tuple], *, cout_ar_bps: float | None, hold_h: float) -> dict[str, Any]:
    import statistics as st
    difs = [r[3] - r[4] for r in serie]                      # d = hl_f - bin_f (bps/h)
    brut = st.mean(difs)
    signe = 1.0 if brut >= 0 else -1.0
    persist = sum(1 for x in difs if (x >= 0) == (brut >= 0)) / len(difs)
    bases = [1e4 * (r[1] - r[2]) / r[2] for r in serie if r[2] > 0]
    base_med = st.median(bases) if bases else 0.0
    base_std = st.pstdev(bases) if len(bases) > 2 else 0.0
    net = None
    if cout_ar_bps is not None:
        net = abs(brut) * hold_h - (cout_ar_bps + FRAIS_AR_BPS)
    return {"d_bps_h": round(brut * signe, 4), "persist": round(persist, 3),
            "apr_pct": round(abs(brut) * 8760 / 100.0, 1), "base_med_bps": round(base_med, 2),
            "base_std_bps": round(base_std, 2), "n": len(serie),
            "net_hold_bps": round(net, 2) if net is not None else None}


def juger_coin(serie: list[tuple], *, cout_ar_bps: float | None,
               hold_h: float = HOLD_DEFAUT_H, min_obs: int = MIN_OBS) -> dict[str, Any]:
    """Verdict d'UN coin. Coupe OOS : le net doit rester positif sur la 2ᵉ moitié temporelle."""
    if len(serie) < min_obs:
        return {"verdict": "INSUFFISANT", "n": len(serie)}
    bin_vals = {round(r[4], 6) for r in serie}
    hl_vals = {round(r[3], 6) for r in serie}
    if len(bin_vals) <= 1 or max((abs(x) for x in hl_vals), default=0.0) < 1e-9:
        return {"verdict": "JAMBE_FIGEE", "n": len(serie)}
    glob = _stats(serie, cout_ar_bps=cout_ar_bps, hold_h=hold_h)
    mid = len(serie) // 2
    h1 = _stats(serie[:mid], cout_ar_bps=cout_ar_bps, hold_h=hold_h)
    h2 = _stats(serie[mid:], cout_ar_bps=cout_ar_bps, hold_h=hold_h)
    if cout_ar_bps is None:
        verdict = "COUT_INCONNU"                             # pas de carnet -> non promu (mesuré, pas jugé)
    elif abs(glob["base_med_bps"]) > MAX_BASE_MEDIANE_BPS:
        verdict = "BASE_SUSPECTE"                            # instrument mal jumelé
    elif glob["persist"] < MIN_PERSIST:
        verdict = "SIGNE_INSTABLE"
    elif glob["net_hold_bps"] is not None and glob["net_hold_bps"] > 0 and (h2.get("net_hold_bps") or -1) > 0:
        verdict = "SURVIVANT_OOS"                            # net>0 IN ET OOS
    else:
        verdict = "NET_NEGATIF"
    return {"verdict": verdict, **glob, "oos_net_hold_bps": h2.get("net_hold_bps")}


def juger_tous(root: str | Path = ".", *, hold_h: float = HOLD_DEFAUT_H) -> dict[str, Any]:
    """Table par coin + survivants OOS. Le juge qui remplace la médiane-poolée noyée par les majors."""
    series = charger_series(root)
    couts = couts_carnet(Path(root))
    lignes: list[dict] = []
    for coin, serie in series.items():
        r = juger_coin(serie, cout_ar_bps=couts.get(coin), hold_h=hold_h)
        if r.get("verdict") in ("INSUFFISANT", "JAMBE_FIGEE"):
            continue
        lignes.append({"coin": coin, **r})
    lignes.sort(key=lambda d: -(d.get("net_hold_bps") or -1e9))
    survivants = [d for d in lignes if d["verdict"] == "SURVIVANT_OOS"]
    incostables = sorted((d for d in lignes if d["verdict"] == "COUT_INCONNU" and d["persist"] >= MIN_PERSIST
                          and abs(d["base_med_bps"]) < 5.0), key=lambda d: -d["apr_pct"])
    return {"strategie": "cross_venue_carry", "hold_h": hold_h,
            "survivants_costables": survivants,
            "propres_mais_sans_carnet": [d["coin"] for d in incostables[:10]],
            "table": lignes,
            "avertissement": "net@hold EXTRAPOLE si la fenêtre < hold (données courtes) ; brut ≠ net ; "
                             "OOS = 2ᵉ moitié in-sample, pas une preuve live. Capacité mid-cap limitée."}


__all__ = ["MAX_BASE_MEDIANE_BPS", "MIN_PERSIST", "FRAIS_AR_BPS", "HOLD_DEFAUT_H",
           "charger_series", "juger_coin", "juger_tous"]
