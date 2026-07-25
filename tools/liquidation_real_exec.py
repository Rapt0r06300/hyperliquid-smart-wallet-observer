"""LIQUIDATION — recompute avec EXÉCUTION RÉELLE (bid/ask HL de la bbo_tape) + séparation de PROVENANCE.
PUR, 0 réseau, 0 ordre. Réutilise la bbo_tape (HL bid/ask) + les helpers rapid_alpha_run. AUCUN spread forfaitaire.

PROVENANCE (Flo 25/07) — strictement séparée, jamais mélangée :
  • REAL_LIQUIDATION           = confirmé par fill.liquidation / ledger liquidation. **ICI : 0** (aucun flux
    confirmé collecté ; overshoots_hl = écart mark↔oracle ; liquidation_map = carte de RISQUE, pas des fills).
  • MARK_ORACLE_OVERSHOOT_PROXY = overshoots_liquidation.jsonl (source=overshoots_hl). Mesuré ci-dessous, LABEL PROXY.

Exécution RÉELLE : SELL_OVERSHOOT → long (achat ask entrée, vente bid sortie) ; BUY_OVERSHOOT → short (vente bid,
rachat ask). Coût = spread RÉEL payé + frais A/R + latence. Jointure sur la bbo_tape HL (couverture limitée → les
events hors fenêtre bbo = NON_MESURABLE_NO_BBO, jamais inventés). Épisodes dédupliqués. 2 moitiés + leave-one-out.
"""
from __future__ import annotations

import importlib.util
import json
import statistics
import time
from bisect import bisect_left
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("rapid_alpha_run", RACINE / "tools" / "rapid_alpha_run.py")
RAR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RAR)
_specL = importlib.util.spec_from_file_location("liquidation_cascade_run", RACINE / "tools" / "liquidation_cascade_run.py")
LCR = importlib.util.module_from_spec(_specL)
_specL.loader.exec_module(LCR)

DATA = RACINE / "runtime" / "data"
SORTIE = RACINE / "runtime" / "rapports" / "liquidation_cascade"
HORIZONS_S = (15, 30, 60, 120)
FEE_AR_BPS = 9.0
DEGRAD_LAT_BPS = 1.0
TOL_JOIN_MS = 2000.0                         # cotation HL acceptée si à ≤ 2 s de l'instant visé


def charger_hl_bbo(coins: set, *, max_lignes_prev: int = 3_000_000) -> dict:
    """{coin: ([ts_wall_ms triés],[(bid,ask)])} depuis bbo_tape.jsonl (+ .prev borné). Venue HL seulement."""
    brut = {c: [] for c in coins}
    for f, cap in ((DATA / "bbo_tape.jsonl", 10_000_000), (DATA / "bbo_tape.jsonl.prev", max_lignes_prev)):
        if not f.exists():
            continue
        n = 0
        for L in f.open(encoding="utf-8", errors="ignore"):
            n += 1
            if n > cap:
                break
            if '"HL"' not in L:
                continue
            try:
                d = json.loads(L)
            except (ValueError, TypeError):
                continue
            if d.get("venue") != "HL":
                continue
            c = d.get("coin")
            t = d.get("ts_wall_ms")
            if c in brut and isinstance(t, (int, float)):
                brut[c].append((t, float(d["bid"]), float(d["ask"])))
    out = {}
    for c, v in brut.items():
        v.sort(key=lambda x: x[0])
        out[c] = ([x[0] for x in v], [(x[1], x[2]) for x in v])
    return out


def _bbo_a(serie, ts):
    temps, ba = serie
    if not temps:
        return None
    i = bisect_left(temps, ts)
    cands = [j for j in (i - 1, i) if 0 <= j < len(temps)]
    best = min(cands, key=lambda j: abs(temps[j] - ts), default=None)
    if best is None or abs(temps[best] - ts) > TOL_JOIN_MS:
        return None
    return ba[best]


def mesurer_reel_bbo(ev: dict, serie) -> dict:
    """Exécution RÉELLE bid/ask HL. NON_MESURABLE_NO_BBO si pas de cotation à l'entrée ou à la sortie."""
    dir_ = 1 if "SELL" in ev["sens"] else -1
    e = _bbo_a(serie, ev["t"])
    if e is None:
        return {"statut": "NON_MESURABLE_NO_BBO", "coin": ev["coin"], "t": ev["t"]}
    e_bid, e_ask = e
    par_h = {}
    for h in HORIZONS_S:
        s = _bbo_a(serie, ev["t"] + h * 1000)
        if s is None:
            par_h[str(h)] = {"statut": "NON_MESURABLE"}
            continue
        s_bid, s_ask = s
        if dir_ > 0:                                     # long : achat ask entrée, vente bid sortie
            net = (s_bid - e_ask) / e_ask * 1e4 - FEE_AR_BPS - DEGRAD_LAT_BPS
        else:                                            # short : vente bid entrée, rachat ask sortie
            net = (e_bid - s_ask) / e_bid * 1e4 - FEE_AR_BPS - DEGRAD_LAT_BPS
        spread_bps = (e_ask - e_bid) / (0.5 * (e_ask + e_bid)) * 1e4
        par_h[str(h)] = {"statut": "OK", "net_bps": round(net, 3), "spread_reel_bps": round(spread_bps, 3)}
    return {"statut": "OK", "coin": ev["coin"], "t": ev["t"], "heure": int((ev["t"] // 3_600_000) % 24),
            "dir": dir_, "par_horizon": par_h}


def _resume(mes, h):
    nets = [m["par_horizon"][str(h)]["net_bps"] for m in mes if m["par_horizon"].get(str(h), {}).get("statut") == "OK"]
    if not nets:
        return {"n": 0}
    n0 = len(nets)
    return {"n": n0, "net_somme": round(sum(nets), 2), "net_moyen": round(sum(nets) / n0, 3),
            "net_median": round(statistics.median(nets), 3), "pf": LCR._pf(nets),
            "drawdown_bps": round(RAR.CVE._drawdown(nets), 2)}


def executer(*, min_overshoot=30.0, horizon_ref=30) -> dict:
    SORTIE.mkdir(parents=True, exist_ok=True)
    ev = LCR.charger(DATA / "overshoots_liquidation.jsonl", min_overshoot_bps=min_overshoot)  # PROXY filtré liquide
    ev = LCR.episodes_liq(ev)                                                                 # 1 obs = 1 épisode
    serie = charger_hl_bbo(LCR.COINS_LIQUIDES)
    mes = [mesurer_reel_bbo(e, serie.get(e["coin"], ([], []))) for e in ev]
    ok = [m for m in mes if m["statut"] == "OK"]
    no_bbo = sum(1 for m in mes if m["statut"] == "NON_MESURABLE_NO_BBO")
    rap = {"ts_ms": int(time.time() * 1000),
           "PROVENANCE": {"REAL_LIQUIDATION": {"n_confirmes": 0,
                          "note": "aucun flux fill.liquidation confirme collecte ; overshoots_hl=proxy mark-oracle ; liquidation_map=carte de RISQUE"},
                          "MARK_ORACLE_OVERSHOOT_PROXY": {"n_episodes_filtres": len(ev),
                          "n_avec_bbo_reel": len(ok), "n_sans_bbo": no_bbo}},
           "cout": "spread RÉEL bbo + 9 bps frais A/R + 1 bps latence (aucun forfait)",
           "PROXY_par_horizon": {str(h): _resume(ok, h) for h in HORIZONS_S},
           "PROXY_2_moities@ref": RAR.deux_fenetres_ep(ok, horizon_ref),
           "PROXY_leave_one_out@ref": RAR.leave_one_out(ok, horizon_ref)}
    r = rap["PROXY_par_horizon"][str(horizon_ref)]
    d2 = rap["PROXY_2_moities@ref"]
    loo = rap["PROXY_leave_one_out@ref"]
    proxy_ok = bool(r.get("n") and r.get("net_moyen", -1) > 0 and d2.get("probe_armable")
                    and all(v is not None and v > 0 for v in loo.values()))
    rap["decision"] = {
        "REAL_LIQUIDATION": "REFUS_COHORTE — 0 evenement confirme (provenance non securisee)",
        "MARK_ORACLE_OVERSHOOT_PROXY": ("ARME_EXPLORATOIRE_PROXY" if proxy_ok else "SHADOW_ONLY"),
        "motif_proxy": ("2 moities + leave-one-out positifs apres cout reel" if proxy_ok else
                        "echoue le gate cout-reel/2-moities/leave-one-out — voir PROXY_par_horizon")}
    (SORTIE / "liquidation_real_exec.json").write_text(json.dumps(rap, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return rap


if __name__ == "__main__":
    r = executer()
    p = r["PROVENANCE"]
    print("PROVENANCE: REAL_LIQUIDATION n=%d · PROXY episodes=%d (avec bbo reel=%d, sans bbo=%d)" % (
        p["REAL_LIQUIDATION"]["n_confirmes"], p["MARK_ORACLE_OVERSHOOT_PROXY"]["n_episodes_filtres"],
        p["MARK_ORACLE_OVERSHOOT_PROXY"]["n_avec_bbo_reel"], p["MARK_ORACLE_OVERSHOOT_PROXY"]["n_sans_bbo"]))
    for h in HORIZONS_S:
        print("  PROXY @%3ds:" % h, r["PROXY_par_horizon"][str(h)])
    print("DECISION:", json.dumps(r["decision"], ensure_ascii=False))
