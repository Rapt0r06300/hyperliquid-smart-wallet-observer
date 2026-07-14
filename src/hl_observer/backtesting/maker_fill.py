"""Simulation d'entree MAKER (ordre limite passif) sur les VRAIS chemins de prix du replay.

Taker (actuel) = on traverse le spread, fill immediat au mid. Maker = on place une limite passive
et on NE remplit QUE si le prix vient la toucher dans une fenetre. Les fills sont determines par les
MARKS reels enregistres -> capture HONNETEMENT la selection adverse : un gagnant qui file en ta
faveur ne remplit pas (la limite n'est jamais touchee), tu ne captures que ce qui revient a ton prix.

Approximation assumee : on ne voit que les snapshots (marks) -> sous-estime legerement les fills.
Lecture seule, aucun ordre reel, aucune promesse de PnL.
"""
from __future__ import annotations

from hl_observer.backtesting.ab_flag_replay import simulate_exit_on_path
from hl_observer.backtesting.scenario_search import _config_for


def maker_limit_price(side: str, mid: float, offset_bps: float) -> float:
    """Prix de la limite passive. LONG => achat SOUS le mid ; SHORT => vente AU-DESSUS."""
    o = float(offset_bps) / 10000.0
    mid = float(mid)
    return mid * (1.0 - o) if side == "LONG" else mid * (1.0 + o)


def find_maker_fill(side: str, limit_price: float, path, entry_ts: float, window_ms: float):
    """(fill_ts, fill_price) si un mark touche la limite dans la fenetre, sinon None."""
    end = float(entry_ts) + float(window_ms)
    for ts, mid in path:
        ts = float(ts)
        if ts < entry_ts:
            continue
        if ts > end:
            break
        px = float(mid)
        if side == "LONG" and px <= limit_price:
            return (ts, limit_price)
        if side == "SHORT" and px >= limit_price:
            return (ts, limit_price)
    return None


def _passes_entry_filters(c, sc):
    """Memes filtres d'entree que scenario_search.eval_trades (parite stricte)."""
    min_edge = float(sc.min_edge_bps)
    if min_edge > 0:
        edge = c.get("edge_remaining_bps")
        if edge is None or float(edge) < min_edge:
            return False
    side = str(c.get("direction") or "").upper()
    if side not in ("LONG", "SHORT"):
        return False
    sm = str(getattr(sc, "side_mode", "both") or "both")
    if sm == "long_only" and side != "LONG":
        return False
    if sm == "short_only" and side != "SHORT":
        return False
    max_age = float(getattr(sc, "max_signal_age_ms", 0.0) or 0.0)
    if max_age > 0:
        age = c.get("signal_age_ms")
        if age is None or float(age) > max_age:
            return False
    min_liq = float(getattr(sc, "min_liquidity_score", 0.0) or 0.0)
    if min_liq > 1.0:
        min_liq /= 100.0
    if min_liq > 0:
        liq = c.get("liquidity_score")
        if liq is None or float(liq) < min_liq:
            return False
    min_cons = int(getattr(sc, "min_consensus_wallets", 1) or 1)
    if min_cons > 1:
        cons = c.get("consensus_wallets")
        if cons is None or int(cons) < min_cons:
            return False
    min_ls = float(getattr(sc, "min_leader_score", 0.0) or 0.0)
    if min_ls > 0:
        ls = c.get("leader_score")
        if ls is None or float(ls) < min_ls:
            return False
    max_deg = float(getattr(sc, "max_copy_degradation_bps", 0.0) or 0.0)
    deg = abs(float(c.get("copy_degradation_bps") or 0.0))
    if max_deg > 0 and deg > max_deg:
        return False
    return True


def eval_maker_trades(sc, candidates, marks, notional_usd=500.0, *,
                      offset_bps=5.0, window_ms=60000.0, maker_cost_bps=2.0):
    """Retourne un dict:
      filled     : list[float]  PnL net des entrees maker REMPLIES (entree au prix limite, cout maker),
      missed_taker : list[float] PnL taker CONTREFACTUEL des entrees NON remplies (mesure la selection
                     adverse : si fortement positif => on rate les gagnants),
      n_eligible : int          nb de candidats passant les filtres (= fills + misses mesurables).
    """
    cfg = _config_for(sc)
    hz = float(sc.horizon_min)
    notl = float(notional_usd)
    filled, missed_taker = [], []
    for c in candidates:
        if not _passes_entry_filters(c, sc):
            continue
        coin = str(c.get("coin") or "").upper()
        side = str(c.get("direction") or "").upper()
        mid = float(c.get("current_mid") or 0.0)
        ts = float(c.get("recorded_at") or 0.0)
        if not coin or mid <= 0 or ts <= 0:
            continue
        path = marks.get(coin, [])
        if not path:
            continue
        deg = abs(float(c.get("copy_degradation_bps") or 0.0))
        limit = maker_limit_price(side, mid, offset_bps)
        fill = find_maker_fill(side, limit, path, ts, window_ms)
        if fill is None:
            # non rempli : on mesure ce que le taker aurait fait (contrefactuel adverse-selection)
            tk = simulate_exit_on_path(side=side, entry_price=mid, path=path, entry_ts=ts,
                                       config=cfg, horizon_min=hz, cost_bps=6.0 + deg, notional_usd=notl)
            if tk is not None:
                missed_taker.append(tk)
            continue
        fill_ts, fill_px = fill
        pnl = simulate_exit_on_path(side=side, entry_price=fill_px, path=path, entry_ts=fill_ts,
                                    config=cfg, horizon_min=hz, cost_bps=float(maker_cost_bps) + deg,
                                    notional_usd=notl)
        if pnl is not None:
            filled.append(pnl)
    return {"filled": filled, "missed_taker": missed_taker,
            "n_eligible": len(filled) + len(missed_taker)}
