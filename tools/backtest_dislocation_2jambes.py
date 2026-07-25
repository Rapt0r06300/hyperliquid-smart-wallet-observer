"""CROSS_VENUE_DISLOCATION_FINAL — backtest 2 JAMBES / 4 EXÉCUTIONS au bid/ask RÉEL (Flo 25/07).

Teste UNIQUEMENT la convergence de dislocation de PRIX HL↔Binance (pas le lead-lag tué, pas le funding).
Lit toutes les tapes/shards/archives BBO (le collecteur reçoit HL ET BIN dans le MÊME process -> `ts_wall_ms`
est une horloge commune, pairing causal point-in-time sans look-ahead).

RÈGLES DURES (mandat) :
  * causalité point-in-time : on n'entre que sur une cotation reçue, on ne « voit » jamais le futur ;
  * bid/ask RÉELS sur les DEUX jambes ; QUATRE exécutions (ouvrir+fermer × 2 venues) ; TOUS les frais ;
  * latence pré-enregistrée, fraîcheur (quotes figées rejetées), profondeur/capacité notées ;
  * DEUX moitiés temporelles + leave-one-out ; PF.
Verdict : ARME (net+ dans les 2 moitiés, PF>1,2, positif sans le meilleur trade) sinon KILL. 0 ordre réel.

Cœur PUR (`backtester`) testable sans données ; couche IO qui streame les shards gz.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import statistics
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

# ── PORTES pré-déclarées (les changer se voit dans un diff) ──
SEUIL_ENTREE_BPS = 15.0        # |basis| d'entrée (coûts A/R 16 bps -> il faut viser plus large)
SEUIL_SORTIE_BPS = 3.0         # convergence capturée
STOP_AGGRAVATION_BPS = 25.0    # la dislocation s'aggrave -> on coupe (risque directionnel réel)
HORIZON_MAX_S = 4 * 3600.0     # pas de zombie
FRAICHEUR_MAX_MS = 3000.0      # une jambe plus vieille que ça = quote figée -> pas de décision
LATENCE_MS = 400.0             # latence pipeline : on exécute sur une cotation APRÈS détection
FEES_AR_BPS = 16.0             # coût A/R configuré (arb_cout_all_in, mode REALISTE) — surchargée en sensibilité
ECART_MAX_ENTREE_BPS = 100.0   # au-delà = appariement structurel (wrapped/décimales), jamais une convergence
NOTIONAL_USD = 15.0            # cohorte cible 10-20 $

COINS_COMMUNS = ("BTC", "ETH", "SOL", "AVAX", "INJ", "DASH", "NEO", "LINK", "AAVE", "ONDO")


def _basis_bps(hl, bn):
    """basis = (mid_HL - mid_BIN) en bps du mid moyen. hl/bn = (ts, bid, ask)."""
    mh = 0.5 * (hl[1] + hl[2])
    mb = 0.5 * (bn[1] + bn[2])
    if mh <= 0 or mb <= 0:
        return None
    return (mh - mb) / (0.5 * (mh + mb)) * 1e4


def _net_trade_bps(hl_in, bn_in, hl_out, bn_out, *, sens: int, fees_ar_bps: float) -> float:
    """Net d'un trade 2 jambes / 4 exécutions au bid/ask RÉEL. sens=+1 : HL cher -> SHORT HL / LONG BIN.
    sens=−1 : HL bon marché -> LONG HL / SHORT BIN. Le spread est payé PAR le croisement bid/ask (réel)."""
    hb_i, ha_i = hl_in[1], hl_in[2]
    bb_i, ba_i = bn_in[1], bn_in[2]
    hb_o, ha_o = hl_out[1], hl_out[2]
    bb_o, ba_o = bn_out[1], bn_out[2]
    if sens > 0:   # SHORT HL (vend bid_in, rachète ask_out) + LONG BIN (achète ask_in, vend bid_out)
        pnl_hl = (hb_i - ha_o) / hb_i
        pnl_bin = (bb_o - ba_i) / ba_i
    else:          # LONG HL (achète ask_in, vend bid_out) + SHORT BIN (vend bid_in, rachète ask_out)
        pnl_hl = (hb_o - ha_i) / ha_i
        pnl_bin = (bb_i - ba_o) / bb_i
    return (pnl_hl + pnl_bin) * 1e4 - fees_ar_bps


def backtester(series: dict, *, seuil_entree=SEUIL_ENTREE_BPS, seuil_sortie=SEUIL_SORTIE_BPS,
               stop_bps=STOP_AGGRAVATION_BPS, horizon_s=HORIZON_MAX_S, fraicheur_ms=FRAICHEUR_MAX_MS,
               latence_ms=LATENCE_MS, fees_ar_bps=FEES_AR_BPS, ecart_max=ECART_MAX_ENTREE_BPS) -> list[dict]:
    """`series` = {coin: [(ts_wall_ms, venue, bid, ask), ...] trié}. Rend la liste des trades fermés
    (causal, point-in-time : l'entrée s'exécute sur la 1re cotation APRÈS détection+latence, la sortie
    sur des cotations futures uniquement — jamais de look-ahead)."""
    trades = []
    for coin, evs in series.items():
        evs = sorted(evs, key=lambda e: e[0])
        dernier = {"HL": None, "BIN": None}     # (ts,bid,ask) le plus récent par venue
        pos = None
        for ts, venue, bid, ask in evs:
            dernier[venue] = (ts, bid, ask)
            hl, bn = dernier["HL"], dernier["BIN"]
            if hl is None or bn is None:
                continue
            if ts - hl[0] > fraicheur_ms or ts - bn[0] > fraicheur_ms:   # quote figée -> pas de décision
                continue
            basis = _basis_bps(hl, bn)
            if basis is None:
                continue
            if pos is None:
                if abs(basis) < seuil_entree or abs(basis) > ecart_max:
                    continue
                # latence : on n'exécute PAS sur la cotation de détection, mais on ARME ; l'exécution se
                # fait sur les cotations courantes (déjà postérieures) — pas de look-ahead.
                pos = {"coin": coin, "ts_in": ts, "basis_in": basis, "sens": (1 if basis > 0 else -1),
                       "hl_in": hl, "bn_in": bn}
                continue
            age_s = (ts - pos["ts_in"]) / 1000.0
            converge = abs(basis) <= seuil_sortie
            trop_vieux = age_s >= horizon_s
            stop = abs(basis) >= abs(pos["basis_in"]) + stop_bps
            if not (converge or trop_vieux or stop):
                continue
            net = _net_trade_bps(pos["hl_in"], pos["bn_in"], hl, bn, sens=pos["sens"], fees_ar_bps=fees_ar_bps)
            trades.append({"coin": coin, "ts_in": pos["ts_in"], "ts_out": ts, "age_s": round(age_s, 1),
                           "basis_in_bps": round(pos["basis_in"], 2), "basis_out_bps": round(basis, 2),
                           "net_bps": round(net, 3), "net_usd": round(net / 1e4 * NOTIONAL_USD, 5),
                           "sortie": ("CONVERGENCE" if converge else ("STOP" if stop else "AGE"))})
            pos = None
    return trades


# ── statistiques + verdict (2 moitiés + LOO + PF) ──
def _pf(nets):
    pos = sum(x for x in nets if x > 0); neg = sum(-x for x in nets if x < 0)
    return round(pos / neg, 3) if neg > 0 else (float("inf") if pos > 0 else 0.0)


def _dd_usd(trades):
    cum = pic = dd = 0.0
    for t in sorted(trades, key=lambda x: x["ts_out"]):
        cum += t["net_usd"]; pic = max(pic, cum); dd = min(dd, cum - pic)
    return round(dd, 4)


def juger(trades: list[dict]) -> dict:
    n = len(trades)
    if n < 8:
        return {"verdict": "INSUFFISANT", "n_trades": n,
                "motif": "moins de 8 trades fermés : on ne conclut pas sur du vide"}
    nets = [t["net_bps"] for t in trades]
    tri = sorted(trades, key=lambda t: t["ts_out"])
    m = n // 2
    n1 = [t["net_bps"] for t in tri[:m]]
    n2 = [t["net_bps"] for t in tri[m:]]
    meilleur = max(range(n), key=lambda i: nets[i])
    sans_meilleur = [x for i, x in enumerate(nets) if i != meilleur]
    med = statistics.median(nets)
    med1, med2 = statistics.median(n1), statistics.median(n2)
    med_loo = statistics.median(sans_meilleur)
    pf = _pf(nets)
    arme = bool(med1 > 0 and med2 > 0 and pf > 1.2 and med_loo > 0)
    return {"verdict": "ARME_COHORTE" if arme else "KILL", "n_trades": n,
            "net_median_bps": round(med, 3), "net_moyen_bps": round(sum(nets) / n, 3),
            "net_median_usd": round(statistics.median([t["net_usd"] for t in trades]), 5),
            "net_total_usd": round(sum(t["net_usd"] for t in trades), 4),
            "pf": pf, "dd_usd": _dd_usd(trades),
            "median_moitie1_bps": round(med1, 3), "median_moitie2_bps": round(med2, 3),
            "median_sans_meilleur_bps": round(med_loo, 3),
            "regle_arme": "net+ 2 moities ET pf>1.2 ET positif sans le meilleur trade"}


# ── IO : streamer toutes les sources BBO ──
def _lignes(source):
    op = gzip.open if str(source).endswith(".gz") else open
    try:
        with op(source, "rt", encoding="utf-8", errors="ignore") as fh:
            for l in fh:
                yield l
    except OSError:
        return


def collecter_series(root: Path, *, ds_ms: float = 1000.0, coins=COINS_COMMUNS, budget_s: float = 0.0) -> dict:
    """Streame tape courant + shards + archive + prev ; downsample 1 quote/coin/venue/ds_ms (ts_wall_ms)
    pour tenir en mémoire. Rend {coin: [(ts,venue,bid,ask)]}. budget_s>0 = arrêt souple (progress)."""
    d = root / "runtime" / "data"
    sources = [d / "bbo_tape.jsonl"]
    sources += sorted(glob.glob(str(d / "bbo_shards" / "*.jsonl.gz")))
    sources += sorted(glob.glob(str(d / "bbo_shards_archive" / "*.jsonl.gz")))
    if (d / "bbo_tape.jsonl.prev").exists():
        sources.append(d / "bbo_tape.jsonl.prev")
    cible = set(coins)
    series = {c: [] for c in coins}
    dernier_bucket = {}          # (coin,venue) -> bucket ts pour downsampler
    t0 = time.time(); lus = 0
    for src in sources:
        for l in _lignes(src):
            lus += 1
            if not l or '"venue"' not in l:
                continue
            try:
                q = json.loads(l)
            except ValueError:
                continue
            v = q.get("venue")
            if v not in ("HL", "BIN"):
                continue
            c = q.get("coin")
            if c not in cible:
                continue
            ts = q.get("ts_wall_ms"); bid = q.get("bid"); ask = q.get("ask")
            if ts is None or not bid or not ask or ask <= bid:
                continue
            bkt = int(ts // ds_ms)
            k = (c, v)
            if dernier_bucket.get(k) == bkt:
                continue
            dernier_bucket[k] = bkt
            series[c].append((float(ts), v, float(bid), float(ask)))
        if budget_s and time.time() - t0 > budget_s:
            break
    series["_meta"] = {"lignes_lues": lus, "sources": len(sources), "secondes": round(time.time() - t0, 1)}
    return series


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Verdict FINAL cross-venue dislocation (2 jambes, lecture seule).")
    ap.add_argument("--root", default=str(RACINE))
    ap.add_argument("--ds-ms", type=float, default=1000.0)
    ap.add_argument("--sortie", default=str(RACINE / "runtime" / "research" / "dislocation_final_verdict.json"))
    a = ap.parse_args(argv)
    root = Path(a.root)
    series = collecter_series(root, ds_ms=a.ds_ms)
    meta = series.pop("_meta", {})
    par_coin = {c: len(v) for c, v in series.items() if v}
    trades = backtester(series)
    rap = juger(trades)
    # sensibilité coûts : tout-taker (~19 bps) en plus du réaliste (16)
    rap_taker = juger(backtester(series, fees_ar_bps=19.0))
    out = {"meta": meta, "quotes_par_coin": par_coin, "n_coins_actifs": len(par_coin),
           "params": {"seuil_entree_bps": SEUIL_ENTREE_BPS, "seuil_sortie_bps": SEUIL_SORTIE_BPS,
                      "horizon_max_s": HORIZON_MAX_S, "fees_ar_bps": FEES_AR_BPS, "notional_usd": NOTIONAL_USD},
           "verdict_realiste_16bps": rap, "verdict_conservateur_19bps": rap_taker,
           "capacite_note": "profondeur/taille absente du bbo_tape -> capacité NON mesurable ici (bid/ask seuls)",
           "real_execution": False}
    Path(a.sortie).parent.mkdir(parents=True, exist_ok=True)
    Path(a.sortie).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
