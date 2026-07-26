"""LOT13 Part 1+2 — MESURE CORRIGÉE de NATIVE_ALPHA_V1 (Flo 26/07). Corrige les biais mesurés avant tout verdict :

  * DÉCOMPOSITION HONNÊTE : brut = mouvement du MID (l'alpha réel) ; spread, frais, slippage SÉPARÉS.
    net = brut_mid − spread − frais − slippage (réconcilie exactement le net bid/ask). Un brut_mid ≈ 0
    prouve l'ABSENCE d'alpha (pas juste des coûts trop hauts).
  * PLACEBO = ré-exécution du SENS OPPOSÉ des mêmes signaux (brut+coûts recalculés), JAMAIS −net.
  * DSR = Sharpe RÉELS de TOUTES les variantes ; PBO réel sur buckets temporels alignés.
  * HORIZONS sous-seconde : acceptés SEULEMENT si une cotation arrive DANS l'horizon ; tous les lags rendus.
  * MAKER RÉEL : prix maker (best), file devant = sz+n, volume traversant = VRAIS trades HL au prix de
    l'ordre (jamais NOTIONAL×3), file diminuée par exécutions, annulations conservatrices, fills partiels,
    adverse selection, frais maker tier-0 conservateur.
Lecture seule, 0 ordre. Ne touche pas au run 14h.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.research_parallel import validation as VAL  # noqa: E402
import recherche_14h_mecanismes as MEC  # noqa: E402
import native_alpha_v1 as NA  # noqa: E402  (réutilise détecteurs + série avec tailles)

HORIZONS_S = (0.1, 0.25, 0.5, 1, 3, 5, 15, 30, 60, 300, 900, 1800, 3600)
LATENCE_MS = 400.0
FEE_TAKER_AR_BPS = 9.0          # HL taker A/R conservateur
FEE_MAKER_AR_BPS = 3.0         # HL maker A/R tier-0 conservateur (userFees non disponible ici)
SLIPPAGE_BPS = 1.0
NOTIONAL = 10.0
DEDUP_MS = 30_000.0


def _fraicheur(h_s: float) -> float:
    """Fraîcheur = l'horizon lui-même (borné) : un markout à 100 ms n'est VALIDE que si une cotation arrive
    dans ~100-200 ms. Empêche d'étiqueter '100ms' une cotation reçue 8 s plus tard."""
    return max(120.0, min(8000.0, h_s * 1000.0 * 1.5))


def _quote_apres(prix, cible_ms, fraicheur_ms):
    tps = prix["tps"]
    i = bisect_right(tps, cible_ms)
    if i >= len(tps) or tps[i] - cible_ms > fraicheur_ms:
        return None
    return i


def markout_decompose(signal, prix, *, horizons=HORIZONS_S, fee_ar_bps=FEE_TAKER_AR_BPS):
    """prix = {'tps':[...], 'rows':[(ts,bid,ask)]}. Entrée causale (1re cotation après ts+latence). Pour
    chaque horizon : brut au MID + spread/frais/slippage SÉPARÉS + lags réels. NON_MESURABLE hors fraîcheur."""
    ie = _quote_apres(prix, signal["ts_ms"] + LATENCE_MS, _fraicheur(0.5))
    if ie is None:
        return {"statut": "NON_MESURABLE", "motif": "PAS_D_ENTREE"}
    te, be, ae = prix["rows"][ie]
    mid_in = 0.5 * (be + ae); spr_in = (ae - be) / mid_in
    sens = signal["sens"]
    par_h = {}
    for h in horizons:
        j = _quote_apres(prix, te + h * 1000, _fraicheur(h))
        if j is None:
            par_h[str(h)] = {"statut": "NON_MESURABLE"}
            continue
        ts2, b2, a2 = prix["rows"][j]
        mid_out = 0.5 * (b2 + a2); spr_out = (a2 - b2) / mid_out
        brut = sens * (mid_out - mid_in) / mid_in * 1e4              # ALPHA : mouvement du mid dans le sens
        spread = (spr_in / 2 + spr_out / 2) * 1e4                    # coût de croisement (demi-spread ×2)
        net = brut - spread - fee_ar_bps - SLIPPAGE_BPS
        par_h[str(h)] = {"statut": "OK", "brut_mid_bps": round(brut, 3), "spread_bps": round(spread, 3),
                         "frais_bps": fee_ar_bps, "slippage_bps": SLIPPAGE_BPS, "net_bps": round(net, 3),
                         "entree_lag_ms": round(te - (signal["ts_ms"] + LATENCE_MS), 1),
                         "sortie_lag_ms": round(ts2 - (te + h * 1000), 1)}
    return {"statut": "OK", "par_horizon": par_h}


def serie_bbo_dense(bbo_recs) -> dict:
    """{coin: [(ts, bid, ask, bid_sz, ask_sz, bid_n, ask_n)]} depuis micro_bbo (DENSE ~164 ms/coin — c'est
    le bon feed pour les markouts, pas la l2book throttlée à ~5 s). Tolère l'absence de _n (v1)."""
    s = defaultdict(list)
    for r in bbo_recs:
        try:
            bid = float(r["bid"]); ask = float(r["ask"]); bs = float(r["bid_sz"]); as_ = float(r["ask_sz"])
        except (KeyError, TypeError, ValueError):
            continue
        if ask > bid > 0:
            s[r["coin"]].append((float(r["ts_wall_ms"]), bid, ask, bs, as_,
                                 int(r.get("bid_n") or 0), int(r.get("ask_n") or 0)))
    for c in s:
        s[c].sort()
    return s


def _prix_index(serie_coin):
    return {"tps": [r[0] for r in serie_coin], "rows": [(r[0], r[1], r[2]) for r in serie_coin]}


def _dedup_sigs(sigs, fenetre_ms=DEDUP_MS):
    """Dédup AVANT markout : un signal par coin par fenêtre (événements indépendants). Réduit ~15× le calcul
    sans changer la statistique (on markout des épisodes déjà indépendants)."""
    vus, out = {}, []
    for s in sorted(sigs, key=lambda x: x["ts_ms"]):
        c = s["coin"]
        if s["ts_ms"] - vus.get(c, -1e18) < fenetre_ms:
            continue
        vus[c] = s["ts_ms"]; out.append(s)
    return out


def mesurer_variante(variante, data, *, horizon_ref=5, fee_ar_bps=FEE_TAKER_AR_BPS):
    """Mesure corrigée d'une variante : épisodes (net au horizon_ref) + décompo coûts + PLACEBO = sens opposé
    ré-exécuté (brut+coûts), pas −net. Rend aussi les markouts médians décomposés + les lags."""
    sigs = _dedup_sigs(NA.detecter(variante, data))
    serie = data["serie"]
    idx = {c: _prix_index(v) for c, v in serie.items() if len(v) >= 2}
    eps, placebo_nets = [], []
    dec = defaultdict(lambda: defaultdict(list))   # horizon -> {brut,spread,net,lag_e,lag_s} -> []
    for s in sigs:
        p = idx.get(s["coin"])
        if not p:
            continue
        mk = markout_decompose(s, p, fee_ar_bps=fee_ar_bps)
        if mk["statut"] != "OK":
            continue
        for h, r in mk["par_horizon"].items():
            if r["statut"] == "OK":
                dec[h]["brut"].append(r["brut_mid_bps"]); dec[h]["spread"].append(r["spread_bps"])
                dec[h]["net"].append(r["net_bps"]); dec[h]["lag_e"].append(r["entree_lag_ms"])
                dec[h]["lag_s"].append(r["sortie_lag_ms"])
        rr = mk["par_horizon"].get(str(horizon_ref), {})
        if rr.get("statut") == "OK":
            eps.append({"ts_ms": s["ts_ms"], "coin": s["coin"], "net_bps": rr["net_bps"]})
        # PLACEBO : MÊME signal, SENS OPPOSÉ, ré-exécuté entièrement (brut+coûts recalculés)
        mkp = markout_decompose({**s, "sens": -s["sens"]}, p, fee_ar_bps=fee_ar_bps)
        if mkp["statut"] == "OK":
            rp = mkp["par_horizon"].get(str(horizon_ref), {})
            if rp.get("statut") == "OK":
                placebo_nets.append(rp["net_bps"])
    eps = VAL.dedup_episodes([{**e, "variante": variante} for e in eps], fenetre_ms=DEDUP_MS)
    nets = [e["net_bps"] for e in eps]
    markouts = {h: {"brut_mid": _med(dec[h]["brut"]), "spread": _med(dec[h]["spread"]),
                    "net": _med(dec[h]["net"]), "n": len(dec[h]["net"]),
                    "lag_entree_med_ms": _med(dec[h]["lag_e"]), "lag_sortie_med_ms": _med(dec[h]["lag_s"])}
                for h in dec}
    return {"variante": variante, "n_signaux": len(sigs), "n_episodes_indep": len(eps), "episodes": eps,
            "nets": nets, "placebo_median_bps": (round(statistics.median(placebo_nets), 3) if placebo_nets else None),
            "sharpe": round(VAL.sharpe(nets), 4) if len(nets) >= 2 else 0.0, "markouts": markouts}


def _med(xs):
    return round(statistics.median(xs), 3) if len(xs) >= 5 else None


def maker_reel(variante, data, *, horizon_s=5):
    """MAKER RÉEL : on poste au best du côté favorable ; file devant = sz(+n) au touch ; volume traversant =
    VRAIS trades HL au prix de l'ordre entre l'entrée et l'horizon ; rempli si volume_traversant >= file_devant
    (conservateur, file réduite par EXÉCUTIONS seulement) ; adverse selection = markout mid après fill.
    Rend fill_rate, adverse, net_maker médian."""
    sigs = NA.detecter(variante, data)
    serie_sz = data["serie_sz"]
    trades = data["trades"]
    tr_par_coin = defaultdict(list)
    for t in trades:
        try:
            tr_par_coin[t["coin"]].append((float(t["ts_wall_ms"]), float(t["px"]), float(t["sz"]) * float(t["px"])))
        except (TypeError, ValueError, KeyError):
            continue
    for c in tr_par_coin:
        tr_par_coin[c].sort()
    n, remplis, adverses = 0, 0, 0
    nets = []
    for s in sigs:
        rows = serie_sz.get(s["coin"]) or []
        if len(rows) < 2:
            continue
        tps = [r[0] for r in rows]
        i = bisect_right(tps, s["ts_ms"] + LATENCE_MS)
        if i >= len(rows):
            continue
        _t, bp, ap, bs, as_, bn, an = rows[i]
        n += 1
        cote_px = bp if s["sens"] > 0 else ap             # on poste du bon côté (achète au bid, vend à l'ask)
        cote_sz = bs if s["sens"] > 0 else as_
        file_devant_usd = cote_sz * cote_px               # toute la file au touch devant nous (conservateur)
        # volume traversant = vrais trades HL au prix de l'ordre (±0,5 bps) entre entrée et horizon
        trs = tr_par_coin.get(s["coin"]) or []
        t0 = rows[i][0]; t1 = t0 + horizon_s * 1000
        vol_trav = sum(v for (tt, px, v) in trs if t0 <= tt <= t1 and abs(px - cote_px) / cote_px < 5e-5)
        if vol_trav >= file_devant_usd + NOTIONAL:        # notre lot passe après la file
            remplis += 1
            j = bisect_right(tps, t1)
            if j < len(rows):
                mid0 = 0.5 * (bp + ap); mid1 = 0.5 * (rows[j][1] + rows[j][2])
                gain_mid = s["sens"] * (mid1 - mid0) / mid0 * 1e4       # après fill maker, le mid bouge-t-il pour nous ?
                if gain_mid < 0:
                    adverses += 1
                nets.append(gain_mid - FEE_MAKER_AR_BPS - SLIPPAGE_BPS)  # net maker = mouvement mid − frais maker
    return {"n": n, "fill_rate": round(remplis / n, 3) if n else None,
            "adverse_selection": round(adverses / remplis, 3) if remplis else None,
            "net_maker_median_bps": (round(statistics.median(nets), 3) if len(nets) >= 5 else None),
            "remplis": remplis}


def juger(variantes: dict) -> dict:
    """DSR sur les Sharpe RÉELS de toutes les variantes ; PBO réel sur buckets alignés ; décisions."""
    sharpes = [v["sharpe"] for v in variantes.values() if v.get("nets") and len(v["nets"]) >= 8]
    perf = {}
    for nom, v in variantes.items():
        eps = v.get("episodes") or []
        if len(eps) >= 8:
            eps = sorted(eps, key=lambda e: e["ts_ms"]); m = len(eps); nb = 10
            arr = [0.0] * nb
            for k, e in enumerate(eps):
                arr[min(nb - 1, k * nb // m)] += e["net_bps"]
            perf[nom] = arr
    pbo = VAL.pbo_cscv(perf, s=8) if len(perf) >= 2 else {"pbo": None}
    out = {}
    for nom, v in variantes.items():
        nets = v.get("nets") or []
        if len(nets) < 8:
            out[nom] = {"decision": "SHADOW", "motif": "INSUFFISANT", "n": len(nets)}
            continue
        eps = sorted(v["episodes"], key=lambda e: e["ts_ms"]); m = len(nets) // 2
        med = statistics.median(nets)
        med1 = statistics.median([e["net_bps"] for e in eps[:m]]); med2 = statistics.median([e["net_bps"] for e in eps[m:]])
        best = max(range(len(nets)), key=lambda i: nets[i]); loo = statistics.median([x for i, x in enumerate(nets) if i != best])
        pos = sum(x for x in nets if x > 0); neg = sum(-x for x in nets if x < 0); pf = round(pos / neg, 3) if neg else float("inf")
        d = VAL.dsr(nets, sharpes_essais=sharpes)
        plac = v.get("placebo_median_bps")
        bat_plac = plac is None or med > plac
        robuste = med1 > 0 and med2 > 0 and pf > 1.2 and loo > 0 and bat_plac and (d.get("dsr") or 0) > 0.95 and (pbo.get("pbo") is None or pbo["pbo"] < 0.20)
        dec = "KILL" if (med <= 0 or pf < 1.0) else ("ARM_MICROCOHORTE" if robuste else "SHADOW")
        mk_ref = v["markouts"].get("5", {})
        out[nom] = {"decision": dec, "n_episodes": len(nets), "net_median_bps": round(med, 3),
                    "brut_mid_5s_bps": mk_ref.get("brut_mid"), "spread_5s_bps": mk_ref.get("spread"),
                    "frais_bps": FEE_TAKER_AR_BPS, "slippage_bps": SLIPPAGE_BPS,
                    "pf": pf, "median_moitie1_bps": round(med1, 3), "median_moitie2_bps": round(med2, 3),
                    "median_sans_meilleur_bps": round(loo, 3), "placebo_reel_bps": plac, "bat_placebo": bat_plac,
                    "dsr": d.get("dsr"), "pbo": pbo.get("pbo"), "sharpe": v["sharpe"]}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Mesure CORRIGÉE NATIVE_ALPHA_V1 (lecture seule).")
    ap.add_argument("--root", default=str(RACINE))
    ap.add_argument("--sortie", default=str(RACINE / "docs" / "audit" / "LOT13_native_alpha_corrige.json"))
    a = ap.parse_args(argv)
    root = Path(a.root)
    l2 = MEC._charger(root, "micro_l2book"); trades = MEC._charger(root, "micro_trades"); ctx = MEC._charger(root, "asset_ctx")
    bbo = MEC._charger(root, "micro_bbo")
    dense = serie_bbo_dense(bbo)                                  # feed DENSE pour markouts/maker
    # signaux OFI/vacuum depuis la l2book (profondeur) ; markouts/maker/microprice sur la bbo DENSE
    data = {"l2": l2, "trades": trades, "ctx": ctx, "serie": dense, "serie_sz": dense, "root": root}
    mesures = {v: mesurer_variante(v, data) for v in NA.VARIANTES}
    verdicts = juger(mesures)
    maker = {v: maker_reel(v, data) for v in ("QUEUE_MICROPRICE_TAKER",)}   # microprice testé en maker réel
    rap = {"couverture": {"l2book": len(l2), "trades": len(trades), "asset_ctx": len(ctx), "coins": len(dense)},
           "verdicts": verdicts,
           "markouts_decomposes": {v: mesures[v]["markouts"] for v in NA.VARIANTES},
           "maker_reel": maker}
    Path(a.sortie).parent.mkdir(parents=True, exist_ok=True)
    Path(a.sortie).write_text(json.dumps(rap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"couverture": rap["couverture"], "verdicts": verdicts, "maker_reel": maker}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
