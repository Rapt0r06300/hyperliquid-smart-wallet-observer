"""Recherche MASSIVE de scenarios sur les donnees replay enregistrees (a lancer APRES les 48h).

Essaie des dizaines de milliers de reglages (scenario_grid) avec la discipline anti-overfit :
  1. eval RAPIDE et FIDELE : reutilise simulate_exit_on_path (no-lookahead) ; PnL sur NOTRE
     taille reelle (notional_usd, defaut 500 = marge $50 x levier 10) ; cout = fees+spread +
     degradation de copie REELLE enregistree par candidat ; filtre d'edge d'entree ;
  2. split TEMPOREL train/test ;
  3. classement sur train, re-eval du top-K sur le TEST (out-of-sample) ;
  4. 'robuste' = net>0 train ET test ET gate DEPLOY_CANDIDATE ET plateau (voisinage sain).
Parallelise (tous les coeurs). REPLAY-only : lit des fichiers, ecrit un rapport, ne touche
jamais au ledger live, aucun ordre. Metriques descriptives ; aucune promesse de PnL.
"""

from __future__ import annotations

import json
import math

from hl_observer.backtesting.ab_flag_replay import load_jsonl, marks_by_coin, simulate_exit_on_path
from hl_observer.backtesting.scenario_grid import generate
from hl_observer.paper_trading.sl_tp import SLTPConfig

CONTEXT = "REPLAY"
DEFAULT_NOTIONAL_USD = 500.0  # notre position reelle = marge $50 x levier 10


def _config_for(sc) -> SLTPConfig:
    trail = sc.trailing_stop_bps if sc.trailing_stop_bps > 0 else None
    act = sc.trailing_activation_bps if (trail and sc.trailing_activation_bps > 0) else None
    return SLTPConfig(
        stop_loss_bps=float(sc.sl_bps), take_profit_bps=float(sc.tp_bps),
        trailing_stop_bps=trail, trailing_activation_bps=act,
        breakeven_buffer_bps=float(sc.breakeven_bps),
    )


def eval_trades(sc, candidates, marks, notional_usd=DEFAULT_NOTIONAL_USD):
    cfg = _config_for(sc)
    hz = float(sc.horizon_min)
    min_edge = float(sc.min_edge_bps)
    base_cost = float(sc.cost_bps)
    notl = float(notional_usd)
    trades = []
    for c in candidates:
        if min_edge > 0:
            edge = c.get("edge_remaining_bps")
            if edge is None or float(edge) < min_edge:
                continue
        coin = str(c.get("coin") or "").upper()
        side = str(c.get("direction") or "").upper()
        entry = float(c.get("current_mid") or 0.0)
        ts = float(c.get("recorded_at") or 0.0)
        if not coin or side not in ("LONG", "SHORT") or entry <= 0 or ts <= 0:
            continue
        cost = base_cost + abs(float(c.get("copy_degradation_bps") or 0.0))
        pnl = simulate_exit_on_path(
            side=side, entry_price=entry, path=marks.get(coin, []), entry_ts=ts,
            config=cfg, horizon_min=hz, cost_bps=cost, notional_usd=notl,
        )
        if pnl is not None:
            trades.append(pnl)
    return trades


def report_from_trades(trades):
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = (gw / gl) if gl > 0 else (float("inf") if gw > 0 else 0.0)
    eq = peak = dd = 0.0
    for t in trades:
        eq += t
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 4) if trades else None,
        "profit_factor": round(pf, 4) if pf != float("inf") else "inf",
        "net_total_usd": round(sum(trades), 4),
        "max_drawdown_usd": round(dd, 4),
        "avg_trade_usd": round(sum(trades) / len(trades), 6) if trades else None,
    }


def temporal_split(candidates, train_frac=0.7):
    cs = sorted(candidates, key=lambda c: float(c.get("recorded_at") or 0.0))
    if len(cs) <= 1:
        return cs, []
    k = max(1, min(len(cs) - 1, int(len(cs) * float(train_frac))))
    return cs[:k], cs[k:]


_SHARED = {}


def _init_worker(train, marks, notional):
    _SHARED["train"] = train
    _SHARED["marks"] = marks
    _SHARED["notional"] = notional


def _eval_worker(sc):
    return sc, report_from_trades(eval_trades(sc, _SHARED["train"], _SHARED["marks"], _SHARED["notional"]))


def _score_all(scenarios, train, marks, min_trades, jobs, notional):
    if jobs and int(jobs) > 1:
        try:
            import concurrent.futures as cf
            with cf.ProcessPoolExecutor(max_workers=int(jobs), initializer=_init_worker,
                                        initargs=(train, marks, notional)) as ex:
                pairs = list(ex.map(_eval_worker, scenarios, chunksize=64))
            return [(sc, rep) for sc, rep in pairs if (rep["trades"] or 0) >= min_trades]
        except Exception:
            pass
    out = []
    for sc in scenarios:
        rep = report_from_trades(eval_trades(sc, train, marks, notional))
        if (rep["trades"] or 0) >= min_trades:
            out.append((sc, rep))
    return out


def _scenario_row(sc):
    return {
        "name": sc.name, "source": sc.source, "sl_bps": sc.sl_bps, "tp_bps": sc.tp_bps,
        "trailing_stop_bps": sc.trailing_stop_bps, "trailing_activation_bps": sc.trailing_activation_bps,
        "breakeven_bps": sc.breakeven_bps, "horizon_min": sc.horizon_min,
        "cost_bps": sc.cost_bps, "min_edge_bps": sc.min_edge_bps,
    }


def _norm_vec(sc):
    return (sc.sl_bps / 130.0, sc.tp_bps / 420.0, sc.trailing_stop_bps / 220.0,
            sc.horizon_min / 480.0, sc.min_edge_bps / 60.0)


def _plateau_flag(sc, scored_map, k=12):
    v = _norm_vec(sc)
    dists = [(math.dist(v, _norm_vec(other)), net) for other, net in scored_map]
    dists.sort(key=lambda x: x[0])
    nets = [net for _, net in dists[1:k + 1]]
    if not nets:
        return False
    nets.sort()
    return nets[len(nets) // 2] > 0.0


def search(candidates, mark_rows, scenarios, *, train_frac=0.7, top_k=40, min_trades=25,
           jobs=1, notional_usd=DEFAULT_NOTIONAL_USD):
    from hl_observer.backtesting.validation_gates import run_validation_gates

    marks = marks_by_coin(mark_rows)
    train, test = temporal_split(candidates, train_frac)

    scored = _score_all(scenarios, train, marks, min_trades, jobs, notional_usd)
    scored.sort(key=lambda r: (r[1]["net_total_usd"] or 0.0), reverse=True)
    scored_map = [(sc, (rep["net_total_usd"] or 0.0)) for sc, rep in scored]

    finalists = []
    for sc, train_rep in scored[:max(1, int(top_k))]:
        test_trades = eval_trades(sc, test, marks, notional_usd)
        test_rep = report_from_trades(test_trades)
        gate = run_validation_gates(test_trades)
        plateau = _plateau_flag(sc, scored_map)
        robust = bool(
            (train_rep["net_total_usd"] or 0.0) > 0.0
            and (test_rep["net_total_usd"] or 0.0) > 0.0
            and gate.get("verdict") == "DEPLOY_CANDIDATE"
            and plateau
        )
        finalists.append({
            "scenario": _scenario_row(sc),
            "train": {kk: train_rep.get(kk) for kk in ("trades", "win_rate", "profit_factor", "net_total_usd", "max_drawdown_usd")},
            "test": {kk: test_rep.get(kk) for kk in ("trades", "win_rate", "profit_factor", "net_total_usd", "max_drawdown_usd")},
            "gate_verdict": gate.get("verdict"),
            "plateau": plateau,
            "robust": robust,
        })

    finalists.sort(key=lambda f: (f["test"]["net_total_usd"] or 0.0), reverse=True)
    robust = [f for f in finalists if f["robust"]]
    return {
        "context": CONTEXT,
        "honesty": "metriques descriptives ; no-lookahead + notre notional + couts reels + train/test + voisinage ; aucune promesse de PnL",
        "notional_usd": notional_usd,
        "candidates_total": len(candidates),
        "train_size": len(train), "test_size": len(test), "train_frac": train_frac,
        "scenarios_evaluated": len(scenarios),
        "scenarios_with_min_trades": len(scored),
        "robust_count": len(robust),
        "best_robust": robust[0] if robust else None,
        "finalists": finalists,
        "note": "Fiable seulement si 'robust': net>0 train ET test ET gate ET plateau.",
    }


def main(argv=None):  # pragma: no cover
    import argparse
    import os

    ap = argparse.ArgumentParser(description="Recherche massive de scenarios replay (REPLAY, paper-only)")
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--marks", required=True)
    ap.add_argument("--max-scenarios", type=int, default=30000)
    ap.add_argument("--train-frac", type=float, default=0.7)
    ap.add_argument("--top-k", type=int, default=40)
    ap.add_argument("--min-trades", type=int, default=25)
    ap.add_argument("--jobs", type=int, default=0)
    ap.add_argument("--notional-usd", type=float, default=DEFAULT_NOTIONAL_USD)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)

    jobs = args.jobs if args.jobs > 0 else (os.cpu_count() or 1)
    candidates = load_jsonl(args.candidates)
    marks = load_jsonl(args.marks)
    scenarios = generate(max_scenarios=args.max_scenarios, seed=args.seed)
    report = search(candidates, marks, scenarios, train_frac=args.train_frac,
                    top_k=args.top_k, min_trades=args.min_trades, jobs=jobs,
                    notional_usd=args.notional_usd)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"scenario_search: {report['scenarios_evaluated']} scenarios ({jobs} coeurs), "
              f"{report['robust_count']} robustes -> {args.out}")
    else:
        print(text)
    print("mode: REPLAY read-only ; aucun ordre, aucune signature, aucune promesse de PnL")
    return 0


__all__ = ["eval_trades", "report_from_trades", "temporal_split", "search", "main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
