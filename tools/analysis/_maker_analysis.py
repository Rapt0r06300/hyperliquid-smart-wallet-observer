"""Mesure MAKER vs TAKER sur les VRAIS chemins de prix du replay (lecture seule, aucun ordre).
Le fill est determine par les marks reels -> taux de remplissage et selection adverse MESURES."""
from __future__ import annotations
import json
from statistics import mean
from hl_observer.backtesting.ab_flag_replay import marks_by_coin
from hl_observer.backtesting import scenario_search as ss
from hl_observer.backtesting.scenario_grid import Scenario
from hl_observer.backtesting.maker_fill import eval_maker_trades
from hl_observer.backtesting.robustness import profit_factor

def load_jsonl(p):
    out=[]
    with open(p) as f:
        for line in f:
            line=line.strip()
            if line:
                try: out.append(json.loads(line))
                except Exception: pass
    return out

base="runtime/replay/_archive/run_20260709_152414"
marks=marks_by_coin(load_jsonl(base+"/marks.jsonl"))
meas=ss.prefilter_candidates(load_jsonl(base+"/candidates.jsonl"), marks)
train,test=ss.temporal_split(meas,0.7)

def sc(**kw):
    d=dict(name="x", sl_bps=126.0, tp_bps=40.0, trailing_stop_bps=132.0, trailing_activation_bps=201.0,
           breakeven_bps=14.0, horizon_min=480.0, cost_bps=6.0, min_edge_bps=40.0, source="mk",
           max_signal_age_ms=10000.0, min_liquidity_score=0.0, min_consensus_wallets=1,
           max_copy_degradation_bps=0.0, min_leader_score=0.0, side_mode="both", catastrophic_stop_bps=180.0)
    d.update(kw); return Scenario(**d)

S=sc()
for label,pool in (("TRAIN",train),("TEST (OOS)",test)):
    tk=ss.eval_trades(S, pool, marks, 500.0)
    print(f"\n===== {label} — tranche edge>=40 + frais<=10s =====")
    print(f"  TAKER  : n={len(tk):>4}  net=${sum(tk):>8.2f}  pf={profit_factor(tk):.2f}")
    print(f"  {'offset':>6} {'fenetre':>7} {'fill%':>6} {'n_fill':>6} {'maker_net':>10} {'pf':>5} {'rate_manques':>12}")
    for off in (2.0,5.0,8.0):
        for win in (30000.0,60000.0):
            r=eval_maker_trades(S, pool, marks, 500.0, offset_bps=off, window_ms=win, maker_cost_bps=2.0)
            f,m=r["filled"],r["missed_taker"]
            fr=len(f)/max(1,r["n_eligible"])
            avgf=mean(f) if f else 0.0
            avgm=mean(m) if m else 0.0
            # selection adverse: les manques sont-ils meilleurs que les remplis ?
            adverse = "ADVERSE" if (m and f and avgm>avgf) else "ok"
            print(f"  {off:>5.0f}b {win/1000:>6.0f}s {fr*100:>5.0f}% {len(f):>6} ${sum(f):>8.2f} {profit_factor(f):>5.2f}  avgFill=${avgf:>5.2f} avgManq=${avgm:>5.2f} [{adverse}]")
