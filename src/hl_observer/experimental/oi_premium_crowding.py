"""OI_PREMIUM_CROWDING_V1 — cœur PUR, pré-enregistré, testable sans réseau (Flo 25/07). 0 ordre, 0 clé.

HYPOTHÈSES (littérature crowding/positionnement, écrites AVANT la donnée — les changer se voit dans un diff) :
  H1 CONTINUATION : OI en HAUSSE + premium (mark−oracle) EXTRÊME -> le mouvement CONTINUE (crowd qui pousse) ;
  H2 REVERSAL     : CHUTE brutale d'OI + COMPRESSION du premium -> REVERSAL (dé-crowding, retour à l'oracle) ;
  H3 SQUEEZE      : CHUTE d'OI + mouvement de prix VIOLENT -> squeeze/continuation (liquidations en cascade).

6 VARIANTES = ces 3 hypothèses × 2 groupes d'horizon (court 5/15 min, long 30/60 min). Figées ci-dessous.

EXÉCUTION : au bid/ask (ou VWAP top) RÉEL HL, frais + slippage inclus, JAMAIS de mid forfaitaire. Le premium
et le ΔOI sont mesurés point-in-time sur la série ctx ; le rendement forward au bid/ask sur la série de prix.
Objectif = PnL net × fréquence × capacité / drawdown (pas « multiplier les trades »). Décision SCALE/SHADOW/KILL.
"""
from __future__ import annotations

import statistics
from bisect import bisect_right

# horizons (secondes) par groupe
H_COURT = (300, 900)          # 5, 15 min
H_LONG = (1800, 3600)         # 30, 60 min

#: seuils pré-enregistrés (dérivés du bon sens crowding ; à ne pas re-tuner après avoir vu le résultat).
PREMIUM_EXTREME_BPS = 25.0    # |premium| au-delà = extrême (mark franchement décollé de l'oracle)
PREMIUM_COMPRESSE_BPS = 5.0   # |premium| en-deçà = compressé (retour vers l'oracle)
DOI_HAUSSE = 0.03             # +3 % d'OI sur la fenêtre = crowd qui entre
DOI_CHUTE = -0.03             # −3 % = dé-crowding
MOVE_VIOLENT_BPS = 40.0       # |Δprix| sur la fenêtre au-delà = mouvement violent
FENETRE_DOI_S = 300.0         # fenêtre de calcul du ΔOI et du Δprix (point-in-time, passé seulement)

FEE_AR_BPS = 9.0              # 1 jambe HL taker A/R (~4,5×2) — surchargé en sensibilité
SLIPPAGE_BPS = 1.0

VARIANTES = (
    {"id": "H1_CONTINUATION_COURT", "hypo": "H1", "sens": "continuation", "horizons": H_COURT},
    {"id": "H1_CONTINUATION_LONG", "hypo": "H1", "sens": "continuation", "horizons": H_LONG},
    {"id": "H2_REVERSAL_COURT", "hypo": "H2", "sens": "reversal", "horizons": H_COURT},
    {"id": "H2_REVERSAL_LONG", "hypo": "H2", "sens": "reversal", "horizons": H_LONG},
    {"id": "H3_SQUEEZE_COURT", "hypo": "H3", "sens": "squeeze", "horizons": H_COURT},
    {"id": "H3_SQUEEZE_LONG", "hypo": "H3", "sens": "squeeze", "horizons": H_LONG},
)


def _prev(serie, ts, fenetre_s):
    """Valeur de `serie`=[(ts, val)] la plus proche AVANT ts−fenetre (point-in-time, jamais le futur)."""
    cible = ts - fenetre_s * 1000
    temps = [x[0] for x in serie]
    i = bisect_right(temps, cible) - 1
    return serie[i][1] if i >= 0 else None


def detecter(hypo: str, serie_ctx: list[dict], *, premium_extreme=PREMIUM_EXTREME_BPS,
             premium_compresse=PREMIUM_COMPRESSE_BPS, doi_hausse=DOI_HAUSSE, doi_chute=DOI_CHUTE,
             move_violent=MOVE_VIOLENT_BPS, fenetre_s=FENETRE_DOI_S) -> list[dict]:
    """Émet les signaux d'une hypothèse sur une série ctx d'UN coin (triée). `serie_ctx` = [{ts_ms, oi,
    premium_bps, mark}]. Point-in-time : ΔOI et Δprix comparent au passé (fenêtre), jamais au futur.
    Rend [{ts_ms, sens:+1/−1}] : +1 = fade long HL (on achète), −1 = short HL."""
    oi_s = [(r["ts_ms"], r["oi"]) for r in serie_ctx if r.get("oi") is not None]
    mk_s = [(r["ts_ms"], r["mark"]) for r in serie_ctx if r.get("mark")]
    out = []
    for r in serie_ctx:
        ts = r["ts_ms"]
        prem = r.get("premium_bps")
        if prem is None:
            continue
        oi0 = _prev(oi_s, ts, fenetre_s)
        mk0 = _prev(mk_s, ts, fenetre_s)
        doi = (r["oi"] - oi0) / oi0 if (oi0 and r.get("oi") is not None and oi0 > 0) else None
        dmove = (r["mark"] - mk0) / mk0 * 1e4 if (mk0 and r.get("mark") and mk0 > 0) else None
        if hypo == "H1":     # OI hausse + premium extrême -> continuation DANS le sens du premium
            if doi is not None and doi >= doi_hausse and abs(prem) >= premium_extreme:
                out.append({"ts_ms": ts, "sens": (1 if prem > 0 else -1)})   # premium+ = mark>oracle = pression haussière
        elif hypo == "H2":   # chute OI + premium compressé -> reversal vers l'oracle (fade le premium résiduel)
            if doi is not None and doi <= doi_chute and abs(prem) <= premium_compresse:
                out.append({"ts_ms": ts, "sens": (-1 if prem > 0 else 1)})
        elif hypo == "H3":   # chute OI + move violent -> squeeze continue dans le sens du move
            if doi is not None and doi <= doi_chute and dmove is not None and abs(dmove) >= move_violent:
                out.append({"ts_ms": ts, "sens": (1 if dmove > 0 else -1)})
    return out


def executer(events: list[dict], prix_hl: list[tuple], *, horizon_s: int, fee_ar_bps=FEE_AR_BPS,
             slippage_bps=SLIPPAGE_BPS, fraicheur_ms=3000.0) -> list[dict]:
    """Rendement forward au bid/ask HL RÉEL. `prix_hl` = [(ts_ms, bid, ask)] trié. Entrée = 1re cotation
    à/après le signal ; sortie = 1re cotation à/après entrée+horizon. sens+1 (long) : achat ask -> vente bid.
    NON_MESURABLE si pas de cotation fraîche. Frais + slippage réels, jamais de mid."""
    temps = [p[0] for p in prix_hl]
    trades = []
    for ev in events:
        i = bisect_right(temps, ev["ts_ms"] - 1)
        if i >= len(prix_hl) or prix_hl[i][0] - ev["ts_ms"] > fraicheur_ms:
            continue
        te, be, ae = prix_hl[i]
        j = bisect_right(temps, te + horizon_s * 1000 - 1)
        if j >= len(prix_hl) or prix_hl[j][0] - (te + horizon_s * 1000) > fraicheur_ms:
            continue
        ts2, bs, as_ = prix_hl[j]
        if ev["sens"] > 0:
            brut = (bs - ae) / ae * 1e4          # long : achat ask, vente bid
        else:
            brut = (be - as_) / be * 1e4         # short : vente bid, rachat ask
        net = brut - fee_ar_bps - slippage_bps
        trades.append({"ts_ms": ev["ts_ms"], "sens": ev["sens"], "net_bps": round(net, 3),
                       "brut_bps": round(brut, 3), "horizon_s": horizon_s})
    return trades


def _pf(nets):
    pos = sum(x for x in nets if x > 0); neg = sum(-x for x in nets if x < 0)
    return round(pos / neg, 3) if neg > 0 else (float("inf") if pos > 0 else 0.0)


def decision(trades: list[dict], *, min_trades: int = 20, notional_usd: float = 15.0) -> dict:
    """SCALE / SHADOW / KILL. SCALE = net+ 2 moitiés ET pf>1,2 ET positif sans le meilleur (robuste, exécutable).
    KILL = pf<1 ou net médian négatif. SHADOW = prometteur mais pas assez de trades ou pas assez robuste."""
    n = len(trades)
    nets = [t["net_bps"] for t in trades]
    if n < min_trades:
        return {"decision": "SHADOW", "motif": "INSUFFISANT", "n": n, "requis": min_trades,
                "net_median_bps": round(statistics.median(nets), 3) if nets else None, "pf": _pf(nets)}
    tri = sorted(trades, key=lambda t: t["ts_ms"])
    m = n // 2
    n1 = [t["net_bps"] for t in tri[:m]]
    n2 = [t["net_bps"] for t in tri[m:]]
    meilleur = max(range(n), key=lambda i: nets[i])
    sans = [x for i, x in enumerate(nets) if i != meilleur]
    med = statistics.median(nets); med1 = statistics.median(n1); med2 = statistics.median(n2)
    med_loo = statistics.median(sans); pf = _pf(nets)
    cum = pic = dd = 0.0
    for t in tri:
        cum += t["net_bps"] / 1e4 * notional_usd; pic = max(pic, cum); dd = min(dd, cum - pic)
    if med <= 0 or pf < 1.0:
        dec = "KILL"
    elif med1 > 0 and med2 > 0 and pf > 1.2 and med_loo > 0:
        dec = "SCALE"
    else:
        dec = "SHADOW"
    return {"decision": dec, "n": n, "net_median_bps": round(med, 3), "net_moyen_bps": round(sum(nets) / n, 3),
            "pf": pf, "dd_usd": round(dd, 4), "median_moitie1_bps": round(med1, 3),
            "median_moitie2_bps": round(med2, 3), "median_sans_meilleur_bps": round(med_loo, 3),
            "objectif": "PnL net × fréquence × capacité / drawdown"}


__all__ = ["VARIANTES", "detecter", "executer", "decision", "H_COURT", "H_LONG", "FEE_AR_BPS"]
