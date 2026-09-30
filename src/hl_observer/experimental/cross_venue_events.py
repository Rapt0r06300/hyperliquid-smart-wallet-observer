"""RAPID_ALPHA_SHADOW — analyseur EVENT-DRIVEN cross-venue Binance→HL (PUR, shadow, 0 réseau, 0 ordre).

Binance = **source du SIGNAL uniquement** (aucune jambe exécutée sur Binance, donc **zéro frais Binance**).
On mesure, event par event, si un CHOC Binance est suivi d'un markout HL exploitable APRÈS notre latence RÉELLE,
NET des vrais coûts d'exécution paper **HL seuls**. Ce n'est PAS une corrélation sur bougies. Aucune interpolation :
si un choc n'est pas alignable à une cotation HL fraîche → `NON_MESURABLE` (jamais inventé).

3 familles de choc : `PRICE_SHOCK` (saut du mid Binance), `AGG_IMBALANCE` (déséquilibre signé des aggTrades),
`TAKER_BURST` (burst de volume taker). Markout HL à 250/500/1000/2000/5000 ms. Coûts HL : demi-spread entrée +
demi-spread sortie + frais A/R + slippage(petit notional) + dégradation latence. Pré-registration ≤ 12 variantes
(fixées AVANT lecture). Décision DISCOVERY_PROBE sur 2 fenêtres non chevauchantes. Horloges séparées : temps
exchange ≠ latence locale. Cross-venue lead-lag ≠ carry ≠ funding : **zéro funding, aucune immobilisation**.
"""
from __future__ import annotations

from bisect import bisect_left

HORIZONS_MS = (250, 500, 1000, 2000, 5000)
FAMILLES = ("PRICE_SHOCK", "AGG_IMBALANCE", "TAKER_BURST")
FENETRE_FRAICHE_MAX_MS = 3000.0            # au-delà, pas de cotation HL « fraîche » → NON_MESURABLE


def _mid(bid, ask):
    return 0.5 * (float(bid) + float(ask))


def _serie_hl(hl_bbo: list):
    """[(t, bid, ask)] → (temps triés, mids, bids, asks). Horloge EXCHANGE HL."""
    s = sorted(hl_bbo, key=lambda x: x[0])
    return ([int(t) for t, _, _ in s], [_mid(b, a) for _, b, a in s],
            [float(b) for _, b, _ in s], [float(a) for _, _, a in s])


def _idx_ge(temps: list, ts: float):
    i = bisect_left(temps, ts)
    return i if i < len(temps) else None


# ============================ détection des chocs (horloge Binance) ================================
def detecter_chocs(binance_bt: list, binance_agg: list, *, w_ms: float,
                   seuil_bps: float, seuil_imb_usd: float, seuil_burst_usd: float) -> list:
    """Chocs Binance sur fenêtres glissantes de `w_ms`. `binance_bt`=[(t,bid,ask)], `binance_agg`=[(t,px,qty,cote)]
    où cote∈{'buy','sell'} (côté AGRESSEUR taker). Rend [{t, dir, famille, ampleur}] (horloge EXCHANGE Binance)."""
    bt = sorted(binance_bt, key=lambda x: x[0])
    tb = [int(t) for t, _, _ in bt]
    mb = [_mid(b, a) for _, b, a in bt]
    chocs = []
    # PRICE_SHOCK : variation du mid sur w_ms
    for i in range(len(tb)):
        j = _idx_ge(tb, tb[i] + w_ms)
        if j is None:
            break
        if mb[i] > 0:
            var_bps = (mb[j] - mb[i]) / mb[i] * 1e4
            if abs(var_bps) >= seuil_bps:
                chocs.append({"t": tb[j], "dir": 1 if var_bps > 0 else -1,
                              "famille": "PRICE_SHOCK", "ampleur": round(abs(var_bps), 2)})
    # AGG_IMBALANCE + TAKER_BURST : agrégats de aggTrades par fenêtre
    ag = sorted(binance_agg, key=lambda x: x[0])
    ta = [int(t) for t, _, _, _ in ag]
    for i in range(len(ta)):
        j = _idx_ge(ta, ta[i] + w_ms)
        if j is None:
            break
        net = vol = 0.0
        for k in range(i, j):
            _t, px, qty, cote = ag[k]
            usd = float(px) * float(qty)
            vol += usd
            net += usd if cote == "buy" else -usd
        if abs(net) >= seuil_imb_usd:
            chocs.append({"t": ta[j], "dir": 1 if net > 0 else -1,
                          "famille": "AGG_IMBALANCE", "ampleur": round(abs(net), 1)})
        if vol >= seuil_burst_usd:
            chocs.append({"t": ta[j], "dir": 1 if net >= 0 else -1,
                          "famille": "TAKER_BURST", "ampleur": round(vol, 1)})
    # dédup par (famille, bucket temps w_ms) : 1 choc unique par fenêtre
    vus, uniques = set(), []
    for c in sorted(chocs, key=lambda x: x["t"]):
        cle = (c["famille"], int(c["t"] // max(w_ms, 1)))
        if cle not in vus:
            vus.add(cle)
            uniques.append(c)
    return uniques


# ============================ markout HL après latence RÉELLE (coûts HL seuls) =====================
def cout_hl_ar_bps(spread_entree_bps: float, spread_sortie_bps: float, fee_ar_bps: float,
                   slippage_bps: float, degradation_latence_bps: float) -> dict:
    """Coût A/R HL DÉCOMPOSÉ (aucun frais Binance). Rend chaque composant + total."""
    total = 0.5 * spread_entree_bps + 0.5 * spread_sortie_bps + fee_ar_bps + slippage_bps + degradation_latence_bps
    return {"demi_spread_entree": round(0.5 * spread_entree_bps, 3), "demi_spread_sortie": round(0.5 * spread_sortie_bps, 3),
            "frais_ar": round(fee_ar_bps, 3), "slippage": round(slippage_bps, 3),
            "degradation_latence": round(degradation_latence_bps, 3), "cout_ar_bps": round(total, 3)}


def mesurer_choc(choc: dict, hl: tuple, *, latence_ms: float, horizons=HORIZONS_MS,
                 fee_ar_bps: float = 9.0, slippage_bps: float = 1.0, degradation_latence_bps: float = 1.0) -> dict:
    """1ʳᵉ cotation HL FRAÎCHE à `t_choc + latence` → markout par horizon, NET coûts HL. `NON_MESURABLE` si pas
    de cotation HL fraîche (ou pas de cotation à l'horizon). Horloge exchange HL ≠ latence locale (séparées)."""
    temps, mids, bids, asks = hl
    t_cible = choc["t"] + latence_ms
    ie = _idx_ge(temps, t_cible)
    if ie is None or temps[ie] - t_cible > FENETRE_FRAICHE_MAX_MS:
        return {"statut": "NON_MESURABLE", "raison": "pas de cotation HL fraiche apres choc+latence",
                "famille": choc["famille"], "t_choc": choc["t"], "dir": choc["dir"]}
    d = choc["dir"]
    pe = mids[ie]
    spread_e_bps = (asks[ie] - bids[ie]) / pe * 1e4 if pe > 0 else 0.0
    par_h = {}
    for h in horizons:
        isx = _idx_ge(temps, temps[ie] + h)
        if isx is None or temps[isx] - (temps[ie] + h) > FENETRE_FRAICHE_MAX_MS:
            par_h[str(h)] = {"statut": "NON_MESURABLE"}
            continue
        px = mids[isx]
        gross = d * (px - pe) / pe * 1e4
        spread_s_bps = (asks[isx] - bids[isx]) / px * 1e4 if px > 0 else 0.0
        cout = cout_hl_ar_bps(spread_e_bps, spread_s_bps, fee_ar_bps, slippage_bps, degradation_latence_bps)
        par_h[str(h)] = {"statut": "OK", "gross_bps": round(gross, 3),
                         "net_bps": round(gross - cout["cout_ar_bps"], 3), "cout": cout}
    return {"statut": "OK", "famille": choc["famille"], "t_choc": choc["t"], "dir": d,
            "t_hl_entree": temps[ie], "latence_reelle_ms": temps[ie] - choc["t"], "par_horizon": par_h}


# ============================ pré-registration ≤ 12 variantes (fixées AVANT lecture) ================
def preregistration(*, w_ms: float = 1000.0) -> list:
    """≤ 12 variantes : 3 familles × seuils/fenêtre FIXES. Aucun balayage, aucun retune après lecture."""
    base = {"w_ms": w_ms, "seuil_bps": 8.0, "seuil_imb_usd": 50_000.0, "seuil_burst_usd": 200_000.0,
            "latence_ms": 400.0, "fee_ar_bps": 9.0}
    vars_ = []
    for fam in FAMILLES:
        for h_ref in (500, 1000):                         # 2 horizons de référence par famille → 6 variantes
            v = dict(base); v.update({"famille": fam, "horizon_ref_ms": h_ref})
            import hashlib as _h
            import json as _j
            v["variante_id"] = "cve-" + _h.sha256(_j.dumps(v, sort_keys=True).encode()).hexdigest()[:10]
            vars_.append(v)
    return vars_[:12]


# ============================ décision DISCOVERY_PROBE (2 fenêtres) ================================
def deux_fenetres(mesures: list, horizon_ref: int, *, min_chocs: int = 20, max_concentration: float = 0.25) -> dict:
    """Split TEMPOREL en 2 fenêtres non chevauchantes. Critères par fenêtre : ≥min_chocs, PnL net>0, aucun
    event >max_concentration du PnL, drawdown borné. Rend le détail + `probe_armable`."""
    ok = [m for m in mesures if m.get("statut") == "OK" and m["par_horizon"].get(str(horizon_ref), {}).get("statut") == "OK"]
    ok.sort(key=lambda m: m["t_choc"])
    if len(ok) < 2 * min_chocs:
        return {"probe_armable": False, "raison": "trop peu de chocs mesurables (%d)" % len(ok), "n": len(ok)}
    milieu = ok[len(ok) // 2]["t_choc"]
    fenA = [m for m in ok if m["t_choc"] < milieu]
    fenB = [m for m in ok if m["t_choc"] >= milieu]

    def eval_fen(fen):
        nets = [m["par_horizon"][str(horizon_ref)]["net_bps"] for m in fen]
        pnl = sum(nets)
        dd = _drawdown(nets)
        concentration = (max((abs(x) for x in nets), default=0.0) / abs(pnl)) if pnl else 1.0
        return {"n_chocs": len(fen), "pnl_net_bps": round(pnl, 2), "pnl_moyen_bps": round(pnl / len(fen), 3) if fen else None,
                "drawdown_bps": round(dd, 2), "concentration_max": round(concentration, 3),
                "ok": bool(len(fen) >= min_chocs and pnl > 0 and concentration <= max_concentration)}
    a, b = eval_fen(fenA), eval_fen(fenB)
    return {"fenetre_A": a, "fenetre_B": b, "probe_armable": bool(a["ok"] and b["ok"]),
            "regle_scale": "SCALE verrouillé tant que l'IC bas clusterisé OOS n'est pas > 0"}


def _drawdown(nets: list) -> float:
    cum = pic = dd = 0.0
    for x in nets:
        cum += x
        pic = max(pic, cum)
        dd = min(dd, cum - pic)
    return dd


def placebo(mesures: list, horizon_ref: int) -> dict:
    """Contrôle : markout des chocs avec la DIRECTION INVERSÉE (si edge réel, le placebo doit être ≈ symétrique/≤0)."""
    nets = [-m["par_horizon"][str(horizon_ref)]["net_bps"] for m in mesures
            if m.get("statut") == "OK" and m["par_horizon"].get(str(horizon_ref), {}).get("statut") == "OK"]
    return {"n": len(nets), "pnl_net_bps": round(sum(nets), 2) if nets else None}


__all__ = ["HORIZONS_MS", "FAMILLES", "detecter_chocs", "mesurer_choc", "cout_hl_ar_bps",
           "preregistration", "deux_fenetres", "placebo"]
