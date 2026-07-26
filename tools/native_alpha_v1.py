"""LOT12 — NATIVE_ALPHA_V1 : mesure des 4 familles HL natives sur toute la microstructure valide.
RÉUTILISE execution_honnete (markouts causaux + VWAP L2 + queue maker) + validation (DSR/PBO/…). Aucun
framework neuf. ≤8 variantes figées. Ne rouvre aucune variante exacte déjà KILL.

Sortie : par variante — couverture, événements indépendants, net moyen/médian, PF, DD, markouts séparés
(100ms→60min), fill-rate maker, DSR/PBO, décision SCALE/SHADOW/KILL. Lecture seule, 0 ordre.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.research_parallel import execution_honnete as EH  # noqa: E402
from hl_observer.research_parallel import validation as VAL  # noqa: E402
import recherche_14h_mecanismes as MEC  # noqa: E402  (réutilise les détecteurs + chargement)

#: 8 variantes figées (2 par famille). Aucun retuning après le 1er run.
HORIZONS_S = (0.1, 0.25, 0.5, 1, 3, 5, 15, 30, 60, 300, 900, 1800, 3600)
NOTIONAL = 10.0
DEDUP_MS = 30_000.0


def _serie_avec_tailles(l2: list[dict]) -> dict:
    """{coin: [(ts, bid, ask, bid_sz, ask_sz, bid_n, ask_n)]} top-1, tolérant v1 [px,sz] et v2 [px,sz,n]."""
    s = defaultdict(list)
    for r in l2:
        b = r.get("bids") or []
        a = r.get("asks") or []
        if not b or not a:
            continue
        try:
            bp, bs = float(b[0][0]), float(b[0][1]); ap, as_ = float(a[0][0]), float(a[0][1])
            bn = int(b[0][2]) if len(b[0]) > 2 else 0
            an = int(a[0][2]) if len(a[0]) > 2 else 0
        except (TypeError, IndexError, ValueError):
            continue
        if ap > bp > 0:
            s[r["coin"]].append((float(r["ts_wall_ms"]), bp, ap, bs, as_, bn, an))
    for c in s:
        s[c].sort()
    return s


def detecter(variante: str, data: dict) -> list[dict]:
    """Signaux d'une variante. Réutilise les détecteurs natifs ; continuation/reversal = même signal, sens
    opposé. deny-by-default si data absente."""
    if variante == "MLOFI_CONTINUATION":
        return MEC._ofi(data["l2"], data["serie"], 5)
    if variante == "MLOFI_REVERSAL":
        return [{**s, "sens": -s["sens"]} for s in MEC._ofi(data["l2"], data["serie"], 5)]
    if variante in ("QUEUE_MICROPRICE_TAKER", "QUEUE_MICROPRICE_MAKER"):
        return MEC._queue_microprice(data["l2"])
    if variante == "LIQ_OI_VACUUM_CONT":
        return MEC._liquidity_vacuum(data["l2"])
    if variante == "LIQ_OI_VACUUM_FADE":
        return [{**s, "sens": -s["sens"]} for s in MEC._liquidity_vacuum(data["l2"])]
    if variante == "OI_ACCEL":
        return MEC._oi_vel_accel(data["ctx"])
    if variante == "FUNDING_DIV":
        return MEC._funding_div(data["ctx"])
    return []


VARIANTES = ("MLOFI_CONTINUATION", "MLOFI_REVERSAL", "QUEUE_MICROPRICE_TAKER", "QUEUE_MICROPRICE_MAKER",
             "LIQ_OI_VACUUM_CONT", "LIQ_OI_VACUUM_FADE", "OI_ACCEL", "FUNDING_DIV")


def _fill_rate_maker(sigs, serie_t, *, horizon_s=5) -> dict:
    """QUEUE_MICROPRICE en MAKER : on poste au meilleur prix ; rempli si le volume au touch traverse la file
    (sz+n conservateur) ; adverse selection = markout APRÈS fill (si négatif -> toxique). Conservateur."""
    remplis, adverses, n = 0, 0, 0
    tps = serie_t["tps"]; rows = serie_t["rows"]
    from bisect import bisect_right
    for s in sigs:
        i = bisect_right(tps, s["ts_ms"])
        if i >= len(rows):
            continue
        _t, bp, ap, bs, as_, bn, an = rows[i]
        # file devant (conservateur) : toute la taille au touch du côté où l'on poste + n ordres * lot symbolique
        cote_sz = bs if s["sens"] > 0 else as_
        q = EH.queue_model_maker(file_devant_usd=cote_sz * (bp if s["sens"] > 0 else ap),
                                 taille_usd=NOTIONAL, volume_traverse_usd=NOTIONAL * 3)  # proxy volume traversant
        n += 1
        if q["statut"] == "REMPLI":
            remplis += 1
            j = bisect_right(tps, s["ts_ms"] + horizon_s * 1000)
            if j < len(rows):
                mid0 = 0.5 * (bp + ap); mid1 = 0.5 * (rows[j][1] + rows[j][2])
                if s["sens"] * (mid1 - mid0) < 0:       # le prix va CONTRE le maker rempli = adverse
                    adverses += 1
    return {"n": n, "fill_rate": round(remplis / n, 3) if n else None,
            "adverse_selection": round(adverses / remplis, 3) if remplis else None}


def mesurer(variante: str, data: dict, *, horizon_ref=5) -> dict:
    sigs = detecter(variante, data)
    serie = data["serie"]
    eps = []
    markouts = defaultdict(list)
    for s in sigs:
        prix = serie.get(s["coin"]) or []
        if len(prix) < 2:
            continue
        mk = EH.markouts_causaux(s, prix, horizons_s=HORIZONS_S, fraicheur_ms=8000.0)
        if mk["statut"] != "OK":
            continue
        for h in HORIZONS_S:
            r = mk["par_horizon"][str(h)]
            if r["statut"] == "OK":
                markouts[h].append(r["net_bps"])
        rr = mk["par_horizon"][str(horizon_ref)]
        if rr["statut"] == "OK":
            eps.append({"ts_ms": s["ts_ms"], "coin": s["coin"], "variante": variante, "net_bps": rr["net_bps"]})
    eps = VAL.dedup_episodes(eps, fenetre_ms=DEDUP_MS)      # événements INDÉPENDANTS
    nets = [e["net_bps"] for e in eps]
    out = {"variante": variante, "n_signaux": len(sigs), "n_episodes_indep": len(eps),
           "couverture_coins": len({e["coin"] for e in eps}),
           "markouts_median_bps": {str(h): (round(statistics.median(v), 2) if len(v) >= 5 else None)
                                    for h, v in sorted(markouts.items())}}
    if variante == "QUEUE_MICROPRICE_MAKER":
        serie_sz = data["serie_sz"]                    # série AVEC tailles+n (pour le modèle de file maker)
        fr = {"n": 0, "remplis": 0, "adverses": 0}
        from bisect import bisect_right
        for s in sigs:
            rows = serie_sz.get(s["coin"]) or []
            if len(rows) < 2:
                continue
            tps = [r[0] for r in rows]
            i = bisect_right(tps, s["ts_ms"])
            if i >= len(rows):
                continue
            _t, bp, ap, bs, as_, bn, an = rows[i]
            cote_sz = bs if s["sens"] > 0 else as_
            q = EH.queue_model_maker(file_devant_usd=cote_sz * (bp if s["sens"] > 0 else ap),
                                     taille_usd=NOTIONAL, volume_traverse_usd=NOTIONAL * 3)
            fr["n"] += 1
            if q["statut"] == "REMPLI":
                fr["remplis"] += 1
                j = bisect_right(tps, s["ts_ms"] + 5000)
                if j < len(rows):
                    mid0 = 0.5 * (bp + ap); mid1 = 0.5 * (rows[j][1] + rows[j][2])
                    if s["sens"] * (mid1 - mid0) < 0:
                        fr["adverses"] += 1
        out["maker"] = {"fill_rate": round(fr["remplis"] / fr["n"], 3) if fr["n"] else None,
                        "adverse_selection": round(fr["adverses"] / fr["remplis"], 3) if fr["remplis"] else None}
    if len(nets) < 8:
        out["decision"] = "SHADOW"; out["motif"] = "INSUFFISANT"
        out["net_median_bps"] = round(statistics.median(nets), 3) if nets else None
        return out
    tri = sorted(eps, key=lambda e: e["ts_ms"]); m = len(nets) // 2
    med = statistics.median(nets)
    med1 = statistics.median([e["net_bps"] for e in tri[:m]])
    med2 = statistics.median([e["net_bps"] for e in tri[m:]])
    best = max(range(len(nets)), key=lambda i: nets[i])
    loo = statistics.median([x for i, x in enumerate(nets) if i != best])
    pos = sum(x for x in nets if x > 0); neg = sum(-x for x in nets if x < 0)
    pf = round(pos / neg, 3) if neg else float("inf")
    plac = VAL.placebo_direction(eps)
    d = VAL.dsr(nets, sharpes_essais=[VAL.sharpe([e["net_bps"] for e in eps]) for _ in VARIANTES])
    trn, tst = VAL.walk_forward_purge(eps)
    oos = round(statistics.median([e["net_bps"] for e in tst]), 2) if len(tst) >= 4 else None
    perf = {variante: [e["net_bps"] for e in tri]}
    robuste = med1 > 0 and med2 > 0 and pf > 1.2 and loo > 0 and med > plac and (d.get("dsr") or 0) > 0.95
    dec = "KILL" if (med <= 0 or pf < 1.0) else ("SCALE" if (len(nets) >= 30 and oos and oos > 0 and robuste)
                                                else ("ARM_MICROCOHORTE" if robuste else "SHADOW"))
    out.update({"decision": dec, "net_median_bps": round(med, 3), "net_moyen_bps": round(sum(nets) / len(nets), 3),
                "median_moitie1_bps": round(med1, 3), "median_moitie2_bps": round(med2, 3),
                "median_sans_meilleur_bps": round(loo, 3), "pf": pf, "placebo_direction_bps": round(plac, 3),
                "dsr": d.get("dsr"), "oos_median_bps": oos,
                "dd_usd": round(_dd([e["net_bps"] for e in tri]), 4)})
    return out


def _dd(nets):
    cum = pic = dd = 0.0
    for x in nets:
        cum += x / 1e4 * NOTIONAL; pic = max(pic, cum); dd = min(dd, cum - pic)
    return dd


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="NATIVE_ALPHA_V1 (mesure microstructure réelle, lecture seule).")
    ap.add_argument("--root", default=str(RACINE))
    ap.add_argument("--sortie", default=str(RACINE / "docs" / "audit" / "LOT12_native_alpha_v1.json"))
    a = ap.parse_args(argv)
    root = Path(a.root)
    l2 = MEC._charger(root, "micro_l2book")
    trades = MEC._charger(root, "micro_trades")
    ctx = MEC._charger(root, "asset_ctx")
    serie = MEC._serie_bbo(l2)
    data = {"l2": l2, "trades": trades, "ctx": ctx, "serie": serie,
            "serie_sz": _serie_avec_tailles(l2), "root": root}
    rap = {"couverture": {"l2book_lignes": len(l2), "trades_lignes": len(trades), "asset_ctx_lignes": len(ctx),
                          "coins": len(serie)}, "variantes": {}}
    for v in VARIANTES:
        rap["variantes"][v] = mesurer(v, data)
    Path(a.sortie).parent.mkdir(parents=True, exist_ok=True)
    Path(a.sortie).write_text(json.dumps(rap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rap, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
