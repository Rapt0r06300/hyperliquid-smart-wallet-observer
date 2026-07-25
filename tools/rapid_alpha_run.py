"""RAPID_ALPHA_SHADOW — RUN sur DONNÉES RÉELLES locales (bbo_tape : BIN + BIN_TRADE + HL). PUR, 0 réseau, 0 ordre.

La bbo_tape collecte DÉJÀ, en live, les 3 flux cross-venue avec horloges : `recu_ns` (MONOTONE local = causalité),
`ts_wall_ms` (wall), `ts_ex` (exchange = skew), `update_id` (séquence). On mesure donc du FORWARD avec horloges
locales — éligible PROBE (pas seulement descriptif).

Corrections moteur (Flo 25/07) : causalité en `recu_ns` UNIQUEMENT (jamais comparer les ts_ex Binance↔HL) ;
exécution HL RÉELLE (long = ask entrée / bid sortie ; short = bid entrée / ask sortie) — pas de mid ; coûts HL
SEULS (spread réel baked-in + frais A/R + dégradation latence ; ZÉRO frais Binance) ; `NON_MESURABLE` si pas de
cotation HL fraîche ; placebo directionnel = −gross − mêmes coûts ; placebo temporel (mêmes coin/heure sans choc) ;
`shock_episode_id` (1 obs = 1 épisode) ; embargo A/B ≥ horizon max + latence ; drawdown = gate ; leave-one-out
(event/coin/heure) ; fenêtres glissantes bornées (pas d'O(n²)). Un tape = une base recu_ns (ne pas mélanger les runs).
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from bisect import bisect_left
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
from hl_observer.experimental import cross_venue_events as CVE   # noqa: E402
from hl_observer.experimental import metaorder_shadow as MS       # noqa: E402

TAPE = RACINE / "runtime" / "data" / "bbo_tape.jsonl"
SORTIE = RACINE / "runtime" / "rapports" / "rapid_alpha"
HORIZONS = CVE.HORIZONS_MS
FEE_AR_BPS = 9.0
DEGRAD_LAT_BPS = 1.0
EPISODE_GAP_MS = max(HORIZONS) + 1500.0          # regroupe les chocs proches (même coin) en 1 épisode


def charger(tape: Path, *, max_lignes: int = 4_000_000) -> dict:
    """Par coin : {'BIN':[(recu_ms,bid,ask)], 'AGG':[(recu_ms,px,sz,cote)], 'HL':[(recu_ms,bid,ask,mid)]} + skew."""
    par = {}
    skew = {"BIN": [], "BIN_TRADE": [], "HL": []}
    n = 0
    for L in tape.open(encoding="utf-8", errors="ignore"):
        L = L.strip()
        if not L:
            continue
        n += 1
        if n > max_lignes:
            break
        try:
            d = json.loads(L)
        except (ValueError, TypeError):
            continue
        v, c = d.get("venue"), d.get("coin")
        rns, tex, tw = d.get("recu_ns"), d.get("ts_ex"), d.get("ts_wall_ms")
        if not c or not isinstance(rns, (int, float)):
            continue
        rms = rns / 1e6
        if isinstance(tex, (int, float)) and isinstance(tw, (int, float)) and v in skew:
            skew[v].append(tw - tex)                                 # wall local − exchange (proxy skew+transport)
        b = par.setdefault(c, {"BIN": [], "AGG": [], "HL": []})
        if v == "BIN":
            b["BIN"].append((rms, float(d["bid"]), float(d["ask"])))
        elif v == "BIN_TRADE":
            b["AGG"].append((rms, float(d["px"]), float(d["sz"]), "buy" if d.get("side") == "BUY" else "sell"))
        elif v == "HL":
            b["HL"].append((rms, float(d["bid"]), float(d["ask"]), float(d.get("mid") or 0.5 * (d["bid"] + d["ask"]))))
    for c in par:
        for k in par[c]:
            par[c][k].sort(key=lambda x: x[0])
    return {"par_coin": par, "skew": skew, "n_lignes": n}


def _idx_ge(temps, ts):
    i = bisect_left(temps, ts)
    return i if i < len(temps) else None


def mesurer_reel(choc: dict, hl: list, *, fee_ar_bps=FEE_AR_BPS) -> dict:
    """1ʳᵉ cotation HL fraîche à recu_ms ≥ choc (causalité LOCALE), exécution RÉELLE ask/bid, coûts HL seuls."""
    temps = [e[0] for e in hl]
    ie = _idx_ge(temps, choc["t"])
    if ie is None or temps[ie] - choc["t"] > CVE.FENETRE_FRAICHE_MAX_MS:
        return {"statut": "NON_MESURABLE", "raison": "pas de cotation HL fraiche", "t": choc["t"], "famille": choc["famille"], "coin": choc.get("coin")}
    d = choc["dir"]
    _, e_bid, e_ask, e_mid = hl[ie]
    spread_bps = (e_ask - e_bid) / e_mid * 1e4 if e_mid > 0 else 0.0
    par_h = {}
    for h in HORIZONS:
        isx = _idx_ge(temps, temps[ie] + h)
        if isx is None or temps[isx] - (temps[ie] + h) > CVE.FENETRE_FRAICHE_MAX_MS:
            par_h[str(h)] = {"statut": "NON_MESURABLE"}
            continue
        _, s_bid, s_ask, s_mid = hl[isx]
        if d > 0:                                                    # long : achat ask, revente bid
            net = (s_bid - e_ask) / e_ask * 1e4 - fee_ar_bps - DEGRAD_LAT_BPS
        else:                                                        # short : vente bid, rachat ask
            net = (e_bid - s_ask) / e_bid * 1e4 - fee_ar_bps - DEGRAD_LAT_BPS
        gross = d * (s_mid - e_mid) / e_mid * 1e4                    # mid→mid (pour placebo directionnel)
        par_h[str(h)] = {"statut": "OK", "gross_bps": round(gross, 3), "net_bps": round(net, 3),
                         "spread_bps": round(spread_bps, 3), "frais_ar": fee_ar_bps, "degrad_lat": DEGRAD_LAT_BPS}
    return {"statut": "OK", "famille": choc["famille"], "coin": choc.get("coin"), "t": choc["t"],
            "heure": int((choc["t"] // 3_600_000) % 24), "dir": d, "par_horizon": par_h}


def episodes(mesures: list) -> list:
    """1 obs = 1 épisode : regroupe les chocs OK du même coin espacés de < EPISODE_GAP_MS ; garde le 1er."""
    ok = sorted([m for m in mesures if m["statut"] == "OK"], key=lambda m: (m["coin"], m["t"]))
    out, dernier = [], {}
    for m in ok:
        d = dernier.get(m["coin"])
        if d is None or m["t"] - d >= EPISODE_GAP_MS:
            out.append(m)
            dernier[m["coin"]] = m["t"]
    return out


def _stats_h(eps, h, cle="net_bps"):
    return [m["par_horizon"][str(h)][cle] for m in eps
            if m["par_horizon"].get(str(h), {}).get("statut") == "OK"]


def leave_one_out(eps, h):
    """PnL reste-t-il > 0 en retirant le meilleur ÉVÉNEMENT, le meilleur COIN et la meilleure HEURE ?"""
    nets = [(m, m["par_horizon"][str(h)]["net_bps"]) for m in eps if m["par_horizon"].get(str(h), {}).get("statut") == "OK"]
    tot = sum(v for _, v in nets)
    if not nets:
        return {"sans_meilleur_event": None, "sans_meilleur_coin": None, "sans_meilleure_heure": None}
    sans_ev = tot - max(v for _, v in nets)
    from collections import defaultdict
    pc, ph = defaultdict(float), defaultdict(float)
    for m, v in nets:
        pc[m["coin"]] += v
        ph[m["heure"]] += v
    return {"sans_meilleur_event": round(sans_ev, 2),
            "sans_meilleur_coin": round(tot - max(pc.values()), 2),
            "sans_meilleure_heure": round(tot - max(ph.values()), 2)}


def deux_fenetres_ep(eps, h, *, min_ep=20, max_conc=0.25):
    eps = sorted(eps, key=lambda m: m["t"])
    nets_all = _stats_h(eps, h)
    if len(nets_all) < 2 * min_ep:
        return {"probe_armable": False, "raison": "trop peu d'épisodes mesurables (%d, requis %d)" % (len(nets_all), 2 * min_ep), "n_episodes": len(nets_all)}
    mid = eps[len(eps) // 2]["t"] + EPISODE_GAP_MS                   # embargo ≥ horizon max + gap
    A = [m for m in eps if m["t"] < eps[len(eps) // 2]["t"]]
    B = [m for m in eps if m["t"] >= mid]

    def ev(fen):
        nets = _stats_h(fen, h)
        pnl = sum(nets)
        conc = (max((abs(x) for x in nets), default=0) / abs(pnl)) if pnl else 1.0
        loo = leave_one_out(fen, h)
        ok = bool(len(nets) >= min_ep and pnl > 0 and conc <= max_conc
                  and all(v is not None and v > 0 for v in loo.values()))
        return {"n_episodes": len(nets), "pnl_net_bps": round(pnl, 2), "drawdown_bps": round(CVE._drawdown(nets), 2),
                "concentration_max": round(conc, 3), "leave_one_out": loo, "ok": ok}
    a, b = ev(A), ev(B)
    return {"fenetre_A": a, "fenetre_B": b, "probe_armable": bool(a["ok"] and b["ok"])}


def executer(tape=TAPE, *, w_ms=1000.0, seuil_bps=8.0, seuil_imb=50_000.0, seuil_burst=200_000.0,
             horizon_ref=1000) -> dict:
    SORTIE.mkdir(parents=True, exist_ok=True)
    data = charger(tape)
    par = data["par_coin"]
    communs = sorted(c for c in par if par[c]["BIN"] and par[c]["HL"])
    par_famille = {f: [] for f in CVE.FAMILLES}
    n_bin = n_agg = n_hl = 0
    for c in communs:
        b = par[c]
        n_bin += len(b["BIN"]); n_agg += len(b["AGG"]); n_hl += len(b["HL"])
        chocs = CVE.detecter_chocs(b["BIN"], b["AGG"], w_ms=w_ms, seuil_bps=seuil_bps,
                                   seuil_imb_usd=seuil_imb, seuil_burst_usd=seuil_burst)
        for ch in chocs:
            ch["coin"] = c
            m = mesurer_reel(ch, b["HL"])
            if m["statut"] == "OK" or m["statut"] == "NON_MESURABLE":
                par_famille[m["famille"]].append(m) if m["statut"] == "OK" else None
    rap = {"ts_ms": int(time.time() * 1000), "tape": str(tape.name), "n_lignes": data["n_lignes"],
           "coins_communs": communs, "messages": {"BIN": n_bin, "AGG_BINANCE": n_agg, "HL": n_hl},
           "skew_ms_par_venue": {v: (round(statistics.median(s), 1) if s else None) for v, s in data["skew"].items()},
           "familles": {}}
    for fam, mes in par_famille.items():
        eps = episodes(mes)
        placebo_dir = [-m["par_horizon"][str(horizon_ref)]["gross_bps"] - FEE_AR_BPS - DEGRAD_LAT_BPS
                       for m in eps if m["par_horizon"].get(str(horizon_ref), {}).get("statut") == "OK"]
        fam_rap = {"n_chocs_OK": len(mes), "n_episodes": len(eps),
                   "pnl_net_bps_par_horizon": {str(h): round(sum(_stats_h(eps, h)), 2) for h in HORIZONS},
                   "gross_bps_par_horizon": {str(h): round(sum(_stats_h(eps, h, "gross_bps")), 2) for h in HORIZONS},
                   "placebo_directionnel_net_bps": round(sum(placebo_dir), 2) if placebo_dir else None,
                   "decision_2_fenetres": deux_fenetres_ep(eps, horizon_ref)}
        rap["familles"][fam] = fam_rap
    armables = [f for f, r in rap["familles"].items() if r["decision_2_fenetres"].get("probe_armable")]
    rap["verdict"] = ("PROBE_ARMABLE:" + ",".join(armables)) if armables else "PAS_ENCORE_PROBE"
    rap["regle"] = "SCALE verrouillé tant que l'IC bas clusterisé OOS n'est pas > 0 ; KILL variante par variante."
    (SORTIE / "rapid_alpha_go_nogo.json").write_text(json.dumps(rap, indent=2, ensure_ascii=False), encoding="utf-8")
    return rap


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tape", default=str(TAPE))
    ap.add_argument("--horizon", type=int, default=1000)
    a = ap.parse_args()
    r = executer(Path(a.tape), horizon_ref=a.horizon)
    print("VERDICT:", r["verdict"], "· coins:", r["coins_communs"], "· msgs:", r["messages"])
    for f, x in r["familles"].items():
        print("  [%s] episodes=%d net@%dms=%s placebo_dir=%s probe=%s" % (
            f, x["n_episodes"], a.horizon, x["pnl_net_bps_par_horizon"][str(a.horizon)],
            x["placebo_directionnel_net_bps"], x["decision_2_fenetres"].get("probe_armable")))
