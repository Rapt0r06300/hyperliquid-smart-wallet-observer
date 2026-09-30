"""LOT 7 — campagne ABSORPTION sur données RÉELLES (Flo 25/07). Détecteur PUR + markouts honnêtes + DSR/PBO.

Détection PRÉ-ENREGISTRÉE (aucun retuning) : sur des buckets 5 s {ts,bid,ask,net_flux,gross_flux}, un
événement d'absorption = flux agressif TRÈS one-sided (|net|/gross > 0,7) ET actif (gross > 2× médiane du
coin) ET prix quasi immobile sur 15 s (|Δmid| < 3 bps). On émet REVERSAL (fade) + CONTINUATION (suit), on
mesure les markouts causaux séparés au bid/ask HL, puis validation dédup/2 moitiés/LOO/placebo/DSR/PBO.
Lecture seule. 0 ordre.
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

from hl_observer.research_parallel import execution_honnete as EH  # noqa: E402
from hl_observer.research_parallel import validation as VAL  # noqa: E402

HORIZONS = (1, 3, 5, 15, 30, 60, 300)
IMBALANCE_MIN = 0.7
GROSS_MULT = 2.0
MOVE_MAX_BPS = 3.0


def detecter_absorption(rows: list[tuple], *, imbalance_min=IMBALANCE_MIN, gross_mult=GROSS_MULT,
                        move_max_bps=MOVE_MAX_BPS) -> list[dict]:
    """rows = [(ts,bid,ask,net_flux,gross_flux)] triés d'UN coin. Rend les événements {ts, signe} (signe du
    flux agressif). PUR, pré-enregistré : le seuil gross est relatif à la MÉDIANE du coin (pas un absolu à tuner)."""
    if len(rows) < 10:
        return []
    med_g = statistics.median([g for *_x, g in rows]) or 1.0
    out = []
    for i in range(3, len(rows)):
        ts, b, a, net, gross = rows[i]
        if gross < gross_mult * med_g or gross <= 0 or abs(net) / gross < imbalance_min:
            continue
        mid = 0.5 * (b + a); mid0 = 0.5 * (rows[i - 3][1] + rows[i - 3][2])
        if abs(mid - mid0) / mid * 1e4 >= move_max_bps:
            continue
        out.append({"ts": ts, "signe": 1 if net > 0 else -1})
    return out


def charger(fichier: Path) -> dict:
    S = defaultdict(list)
    for l in Path(fichier).read_text(encoding="utf-8").splitlines():
        p = l.split("\t")
        if len(p) != 6:
            continue
        c, ts, b, a, net, gross = p
        S[c].append((float(ts), float(b), float(a), float(net), float(gross)))
    for c in S:
        S[c].sort()
    return S


def campagne(S: dict, *, horizon_ref: int = 30) -> dict:
    bbo = {c: [(ts, b, a) for ts, b, a, _n, _g in rows] for c, rows in S.items()}
    par_h = defaultdict(list)          # (variante,h)->[net]
    ref = defaultdict(list)            # variante->episodes @horizon_ref
    n_ev = 0
    for c, rows in S.items():
        for ev in detecter_absorption(rows):
            n_ev += 1
            for var, sens in (("ABSORPTION_REVERSAL", -ev["signe"]), ("ABSORPTION_CONTINUATION", ev["signe"])):
                mk = EH.markouts_causaux({"ts_ms": ev["ts"], "coin": c, "sens": sens}, bbo[c],
                                         horizons_s=HORIZONS, fraicheur_ms=6000.0)
                if mk["statut"] != "OK":
                    continue
                for h in HORIZONS:
                    r = mk["par_horizon"][str(h)]
                    if r["statut"] == "OK":
                        par_h[(var, h)].append(r["net_bps"])
                rr = mk["par_horizon"][str(horizon_ref)]
                if rr["statut"] == "OK":
                    ref[var].append({"ts_ms": ev["ts"], "coin": c, "variante": var, "net_bps": rr["net_bps"]})
    sharpes = [VAL.sharpe(v) for v in par_h.values() if len(v) >= 8]
    perf = {}
    for var in ref:
        eps = VAL.dedup_episodes(ref[var])
        if eps:
            m = len(eps); nb = 12
            arr = [0.0] * nb
            for k, e in enumerate(sorted(eps, key=lambda x: x["ts_ms"])):
                arr[min(nb - 1, k * nb // m)] += e["net_bps"]
            perf[var] = arr
    pbo = VAL.pbo_cscv(perf, s=8)
    rap = {"n_evenements": n_ev, "markouts_median_bps": {}, "variantes": {}}
    for (var, h), v in sorted(par_h.items()):
        rap["markouts_median_bps"].setdefault(var, {})[str(h)] = {
            "median": round(statistics.median(v), 2), "n": len(v)} if v else None
    for var in ("ABSORPTION_REVERSAL", "ABSORPTION_CONTINUATION"):
        eps = VAL.dedup_episodes(ref[var]); nets = [e["net_bps"] for e in eps]; n = len(nets)
        if n < 8:
            rap["variantes"][var] = {"decision": "SHADOW", "n": n, "motif": "INSUFFISANT"}
            continue
        tri = sorted(eps, key=lambda e: e["ts_ms"]); half = n // 2
        med = statistics.median(nets)
        med1 = statistics.median([e["net_bps"] for e in tri[:half]])
        med2 = statistics.median([e["net_bps"] for e in tri[half:]])
        best = max(range(n), key=lambda i: nets[i])
        loo = statistics.median([x for i, x in enumerate(nets) if i != best])
        pos = sum(x for x in nets if x > 0); neg = sum(-x for x in nets if x < 0)
        pf = round(pos / neg, 3) if neg else float("inf")
        plac = VAL.placebo_direction(eps)
        d = VAL.dsr(nets, sharpes_essais=sharpes)
        tr, te = VAL.walk_forward_purge(eps)
        oos = round(statistics.median([e["net_bps"] for e in te]), 2) if len(te) >= 4 else None
        robuste = med1 > 0 and med2 > 0 and pf > 1.2 and loo > 0 and med > plac and (d.get("dsr") or 0) > 0.95
        dec = "KILL" if (med <= 0 or pf < 1.0) else ("SCALE" if (n >= 30 and oos is not None and oos > 0 and robuste)
                                                     else ("ARM_MICROCOHORTE" if robuste else "SHADOW"))
        rap["variantes"][var] = {"decision": dec, "n": n, "net_median_bps": round(med, 2),
                                 "median_moitie1_bps": round(med1, 2), "median_moitie2_bps": round(med2, 2),
                                 "median_sans_meilleur_bps": round(loo, 2), "pf": pf,
                                 "placebo_direction_bps": round(plac, 2), "dsr": d.get("dsr"),
                                 "pbo": pbo.get("pbo"), "oos_median_bps": oos}
    return rap


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Campagne ABSORPTION (données réelles, lecture seule).")
    ap.add_argument("--serie", required=True)
    ap.add_argument("--sortie", default=str(RACINE / "docs" / "audit" / "LAB_campagne_absorption.json"))
    a = ap.parse_args(argv)
    rap = campagne(charger(Path(a.serie)))
    Path(a.sortie).parent.mkdir(parents=True, exist_ok=True)
    Path(a.sortie).write_text(json.dumps(rap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rap, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
