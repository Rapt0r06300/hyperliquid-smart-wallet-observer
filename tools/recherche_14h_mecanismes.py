"""MOTEUR DE MESURE du run 14h — les 10 mécanismes HL NATIFS + mesure via execution_honnete + validation.
RÉUTILISE l'existant (ne reconstruit rien). Détecteurs PURS, deny-by-default (data absente -> aucun signal).

Consomme la data labo : micro_l2book (niveaux+tailles), micro_trades (côté agresseur), asset_ctx (OI/funding/
premium). Mesure les markouts causaux au bid/ask réel HL (execution_honnete) puis stats (validation).
0 ordre, 0 mid, aucune donnée future.
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research_parallel import execution_honnete as EH  # noqa: E402
from hl_observer.research_parallel import isolation as ISO  # noqa: E402
from hl_observer.research_parallel import validation as VAL  # noqa: E402


def _charger(root: Path, flux: str, *, t_min_ms=None, t_max_ms=None) -> list[dict]:
    p = ISO.lab_root(root) / "data" / ("%s.jsonl" % flux)
    out = []
    try:
        for l in p.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            try:
                r = json.loads(l)
            except ValueError:
                continue
            t = r.get("ts_wall_ms")
            if t is None:
                continue
            if (t_min_ms is None or t >= t_min_ms) and (t_max_ms is None or t < t_max_ms):
                out.append(r)
    except OSError:
        return []
    return out


def _serie_bbo(l2: list[dict]) -> dict:
    """{coin: [(ts, bid, ask)] trié} depuis le top-1 des snapshots l2book (bid/ask exécutables réels)."""
    s = defaultdict(list)
    for r in l2:
        b = r.get("bids") or []
        a = r.get("asks") or []
        if not b or not a:
            continue
        try:
            bid = float(b[0][0]); ask = float(a[0][0])
        except (TypeError, IndexError, ValueError):
            continue
        if ask > bid > 0:
            s[r["coin"]].append((float(r["ts_wall_ms"]), bid, ask))
    for c in s:
        s[c].sort()
    return s


# ─────────────── détecteurs (10 mécanismes HL natifs, pré-enregistrés) ───────────────
def _ofi(l2: list[dict], coin_series: dict, prof: int) -> list[dict]:
    """Order-Flow Imbalance sur top-`prof` niveaux : Δ(profondeur bid) − Δ(profondeur ask) entre 2 snapshots,
    normalisé par la profondeur totale. Signal quand |OFI| extrême -> sens = signe (pression directionnelle)."""
    par_coin = defaultdict(list)
    for r in l2:
        par_coin[r["coin"]].append(r)
    out = []
    for coin, snaps in par_coin.items():
        snaps.sort(key=lambda x: x["ts_wall_ms"])
        for i in range(1, len(snaps)):
            def dep(sn, cote):
                niv = sn.get(cote) or []
                return sum(float(x[1]) for x in niv[:prof] if len(x) >= 2)
            db = dep(snaps[i], "bids") - dep(snaps[i - 1], "bids")
            da = dep(snaps[i], "asks") - dep(snaps[i - 1], "asks")
            tot = abs(db) + abs(da)
            if tot <= 0:
                continue
            ofi = (db - da) / tot
            if abs(ofi) >= 0.6:
                out.append({"ts_ms": snaps[i]["ts_wall_ms"], "coin": coin, "sens": 1 if ofi > 0 else -1})
    return out


def _queue_microprice(l2: list[dict]) -> list[dict]:
    """Microprice = (bid·ask_sz + ask·bid_sz)/(bid_sz+ask_sz). Signal quand le microprice penche fortement
    d'un côté du mid -> sens vers le microprice (déséquilibre de file top-1)."""
    out = []
    for r in l2:
        b = r.get("bids") or []
        a = r.get("asks") or []
        if not b or not a:
            continue
        try:
            bp, bs = float(b[0][0]), float(b[0][1]); ap, as_ = float(a[0][0]), float(a[0][1])
        except (TypeError, IndexError, ValueError):
            continue
        if ap <= bp or (bs + as_) <= 0:
            continue
        mid = 0.5 * (bp + ap)
        micro = (bp * as_ + ap * bs) / (bs + as_)
        dev = (micro - mid) / mid * 1e4
        if abs(dev) >= 1.0:
            out.append({"ts_ms": r["ts_wall_ms"], "coin": r["coin"], "sens": 1 if dev > 0 else -1})
    return out


def _liquidity_vacuum(l2: list[dict]) -> list[dict]:
    """Vidage brutal de profondeur top-5 (le carnet se creuse d'un côté) -> le prix part vers le côté vidé."""
    par_coin = defaultdict(list)
    for r in l2:
        par_coin[r["coin"]].append(r)
    out = []
    for coin, snaps in par_coin.items():
        snaps.sort(key=lambda x: x["ts_wall_ms"])
        for i in range(1, len(snaps)):
            def d5(sn, cote):
                return sum(float(x[1]) for x in (sn.get(cote) or [])[:5] if len(x) >= 2)
            bid0, ask0 = d5(snaps[i - 1], "bids"), d5(snaps[i - 1], "asks")
            bid1, ask1 = d5(snaps[i], "bids"), d5(snaps[i], "asks")
            if bid0 > 0 and bid1 / bid0 < 0.4 and bid1 < ask1:
                out.append({"ts_ms": snaps[i]["ts_wall_ms"], "coin": coin, "sens": -1})   # bid vidé -> baisse
            elif ask0 > 0 and ask1 / ask0 < 0.4 and ask1 < bid1:
                out.append({"ts_ms": snaps[i]["ts_wall_ms"], "coin": coin, "sens": 1})     # ask vidé -> hausse
    return out


def _trades_agg(trades: list[dict], *, fenetre_ms=2000.0):
    """Agrège le flux agressif HL par coin sur des fenêtres glissantes -> [(ts, coin, net, gross, dprix?)]."""
    par_coin = defaultdict(list)
    for t in trades:
        try:
            par_coin[t["coin"]].append((float(t["ts_wall_ms"]), float(t["px"]), float(t["sz"]) * float(t["px"]),
                                        int(t.get("side", 0))))
        except (TypeError, ValueError):
            continue
    return par_coin


def _absorption_native(trades: list[dict], serie: dict) -> list[dict]:
    """Gros flux agressif HL SANS déplacement du prix (absorption native) -> reversal/continuation testés en aval."""
    par_coin = _trades_agg(trades)
    out = []
    for coin, tr in par_coin.items():
        tr.sort()
        for i in range(20, len(tr)):
            fen = tr[i - 20:i]
            net = sum(n * (t[3] or 0) for t, n in [(x, x[2]) for x in fen])
            gross = sum(x[2] for x in fen)
            if gross <= 0 or abs(net) / gross < 0.7:
                continue
            dprix = (fen[-1][1] - fen[0][1]) / fen[0][1] * 1e4 if fen[0][1] else 0
            if abs(dprix) < 2.0:
                out.append({"ts_ms": fen[-1][0], "coin": coin, "sens": -1 if net > 0 else 1})   # fade par défaut
    return out


def _sweep_burst(trades: list[dict]) -> list[dict]:
    """Rafale de trades MÊME côté qui balaie le carnet (sweep) -> continuation dans le sens du sweep."""
    par_coin = _trades_agg(trades)
    out = []
    for coin, tr in par_coin.items():
        tr.sort()
        for i in range(10, len(tr)):
            fen = tr[i - 10:i]
            if fen[-1][0] - fen[0][0] > 1500:          # rafale = 10 trades en < 1,5 s
                continue
            cotes = [x[3] for x in fen]
            if all(c == 1 for c in cotes):
                out.append({"ts_ms": fen[-1][0], "coin": coin, "sens": 1})
            elif all(c == -1 for c in cotes):
                out.append({"ts_ms": fen[-1][0], "coin": coin, "sens": -1})
    return out


def _oi_vel_accel(ctx: list[dict]) -> list[dict]:
    from hl_observer.research_parallel.plugins import vague1 as V
    return V.oi_crowding({"_asset_ctx": ctx, "root": "."})


def _funding_div(ctx: list[dict]) -> list[dict]:
    from hl_observer.research_parallel.plugins import vague1 as V
    return V.funding_clock({"_asset_ctx": ctx, "root": "."})


def _cascade(root: Path, serie: dict) -> list[dict]:
    """Liquidations confirmées (journal du main, lecture seule) × baisse d'OI -> continuation dans le sens forcé."""
    liq = []
    try:
        for l in (Path(root) / "runtime" / "data" / "liquidations_confirmees.jsonl").read_text(
                encoding="utf-8").splitlines()[-500:]:
            try:
                liq.append(json.loads(l))
            except ValueError:
                continue
    except OSError:
        return []
    out = []
    for r in liq:
        coin = r.get("coin"); ts = r.get("recv_wall_ms") or r.get("recu_ms")
        d = str(r.get("dir") or "")
        if not coin or not ts or coin not in serie:
            continue
        sens = 1 if "Long" in d else (-1 if "Short" in d else 0)   # forced sell -> continuation baissière = -1? fade=+1
        if sens:
            out.append({"ts_ms": ts, "coin": coin, "sens": sens})
    return out


DETECTEURS = {
    "OFI_TOP1": lambda d: _ofi(d["l2"], d["serie"], 1),
    "OFI_TOP5": lambda d: _ofi(d["l2"], d["serie"], 5),
    "OFI_TOP20": lambda d: _ofi(d["l2"], d["serie"], 20),
    "QUEUE_MICROPRICE": lambda d: _queue_microprice(d["l2"]),
    "LIQUIDITY_VACUUM": lambda d: _liquidity_vacuum(d["l2"]),
    "HL_ABSORPTION_NATIVE": lambda d: _absorption_native(d["trades"], d["serie"]),
    "TRADE_SWEEP_BURST": lambda d: _sweep_burst(d["trades"]),
    "OI_VEL_ACCEL_PRICE_FUNDING": lambda d: _oi_vel_accel(d["ctx"]),
    "FUNDING_CLOCK_DIVERGENCE": lambda d: _funding_div(d["ctx"]),
    "LIQUIDATION_CASCADE_DEPTH": lambda d: _cascade(d["root"], d["serie"]),
}


def mesurer_phase(root: Path, *, t_min_ms=None, t_max_ms=None, horizon_ref_s: int = 30) -> dict:
    """Mesure les 10 mécanismes sur la fenêtre [t_min;t_max[. Rend {meca: {n, net_median_bps, pf, sharpe}}.
    Markouts causaux au bid/ask HL (execution_honnete). deny-by-default : mécanisme sans data -> n=0."""
    l2 = _charger(root, "micro_l2book", t_min_ms=t_min_ms, t_max_ms=t_max_ms)
    trades = _charger(root, "micro_trades", t_min_ms=t_min_ms, t_max_ms=t_max_ms)
    ctx = _charger(root, "asset_ctx", t_min_ms=t_min_ms, t_max_ms=t_max_ms)
    serie = _serie_bbo(l2)
    data = {"l2": l2, "trades": trades, "ctx": ctx, "serie": serie, "root": Path(root)}
    res = {}
    for meca, fn in DETECTEURS.items():
        try:
            sigs = fn(data) or []
        except Exception as e:  # noqa: BLE001 (un détecteur ne casse jamais le run)
            res[meca] = {"n": 0, "erreur": str(e)[:80]}
            continue
        nets = []
        for s in sigs:
            prix = serie.get(s["coin"]) or []
            if len(prix) < 2:
                continue
            mk = EH.markouts_causaux(s, prix, horizons_s=(horizon_ref_s,), fraicheur_ms=6000.0)
            if mk["statut"] == "OK" and mk["par_horizon"][str(horizon_ref_s)]["statut"] == "OK":
                nets.append(mk["par_horizon"][str(horizon_ref_s)]["net_bps"])
        if len(nets) >= 3:
            pos = sum(x for x in nets if x > 0); neg = sum(-x for x in nets if x < 0)
            res[meca] = {"n": len(nets), "net_median_bps": round(statistics.median(nets), 3),
                         "pf": round(pos / neg, 3) if neg else float("inf"), "sharpe": round(VAL.sharpe(nets), 3)}
        else:
            res[meca] = {"n": len(nets)}
    return res


__all__ = ["mesurer_phase", "DETECTEURS", "_serie_bbo"]
