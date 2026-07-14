"""Analyse d'optimisation HONNETE (lecture seule, aucun ordre) sur les donnees replay reelles.
Repond a 3 questions concretes, sans promesse :
  1) MAKER vs TAKER : economiser le spread (avec missed-fill) fait-il basculer la meilleure tranche ?
  2) MONTE-CARLO : le quasi-breakeven est-il un edge ou du bruit (IC par bootstrap) ?
  3) FRAICHEUR : ou est l'edge selon l'age du signal (bandes cumulees) ?
"""
from __future__ import annotations
import json
from hl_observer.backtesting.ab_flag_replay import marks_by_coin
from hl_observer.backtesting import scenario_search as ss
from hl_observer.backtesting.scenario_grid import Scenario
from hl_observer.backtesting.robustness import bootstrap_pnl_ci, maker_adjust_net, profit_factor

def load_jsonl(p):
    out=[]
    with open(p) as f:
        for line in f:
            line=line.strip()
            if line:
                try: out.append(json.loads(line))
                except Exception: pass
    return out

C="runtime/replay/_archive/run_20260709_152414/candidates.jsonl"
M="runtime/replay/_archive/run_20260709_152414/marks.jsonl"
marks=marks_by_coin(load_jsonl(M))
meas=ss.prefilter_candidates(load_jsonl(C), marks)
train,test=ss.temporal_split(meas,0.7)
print(f"mesurables={len(meas)} train={len(train)} test={len(test)}\n")

def sc(**kw):
    d=dict(name="x", sl_bps=126.0, tp_bps=40.0, trailing_stop_bps=132.0, trailing_activation_bps=201.0,
           breakeven_bps=14.0, horizon_min=480.0, cost_bps=6.0, min_edge_bps=0.0, source="optim",
           max_signal_age_ms=0.0, min_liquidity_score=0.0, min_consensus_wallets=1,
           max_copy_degradation_bps=0.0, min_leader_score=0.0, side_mode="both", catastrophic_stop_bps=180.0)
    d.update(kw); return Scenario(**d)

# Meilleure tranche OOS trouvee : edge>=40 + frais<=10s (sortie #1)
BEST=dict(min_edge_bps=40.0, max_signal_age_ms=10000.0)
tr_trades=ss.eval_trades(sc(**BEST), train, marks, 500.0)
te_trades=ss.eval_trades(sc(**BEST), test, marks, 500.0)
def line(name, tl):
    return f"{name:16} n={len(tl):>4} net=${sum(tl):>8.2f} pf={profit_factor(tl):.2f}"
print("=== Tranche edge>=40 + frais<=10s (sortie #1) ===")
print(line("TRAIN taker", tr_trades)); print(line("TEST  taker", te_trades))

print("\n=== 1) MAKER vs TAKER (TEST/OOS) — economie spread $0.20 (~4bps sur $500) ===")
print(f"{'fill_rate':10} {'aleatoire':>14} {'adverse(pire)':>16}")
for fr in (1.0, 0.9, 0.7, 0.5):
    rnd=maker_adjust_net(te_trades, spread_saving_usd=0.20, fill_rate=fr, seed=7, adverse=False)
    adv=maker_adjust_net(te_trades, spread_saving_usd=0.20, fill_rate=fr, seed=7, adverse=True)
    print(f"{fr:<10} net=${sum(rnd):>8.2f}   net=${sum(adv):>8.2f}")

print("\n=== 2) MONTE-CARLO (bootstrap 3000x) — le resultat est-il reel ou du bruit ? ===")
for nm,tl in (("TEST taker", te_trades),
              ("TEST maker fill0.7 alea", maker_adjust_net(te_trades, spread_saving_usd=0.20, fill_rate=0.7, seed=7))):
    ci=bootstrap_pnl_ci(tl, n=3000, seed=7)
    print(f"{nm:24} net_obs=${ci['net_observed']:>7} median=${ci['net_median']:>7} "
          f"p5=${ci['net_p5']:>7} p95=${ci['net_p95']:>7} P(net>0)={ci['prob_net_positive']}")

print("\n=== 3) EDGE PAR FRAICHEUR (edge>=40, bandes cumulees, TRAIN+TEST) ===")
allc=train+test
for age in (3000,5000,10000,20000,30000):
    tl=ss.eval_trades(sc(min_edge_bps=40.0, max_signal_age_ms=float(age)), allc, marks, 500.0)
    print(f"  age<={age/1000:>4.0f}s  n={len(tl):>4}  net=${sum(tl):>8.2f}  pf={profit_factor(tl):.2f}")
