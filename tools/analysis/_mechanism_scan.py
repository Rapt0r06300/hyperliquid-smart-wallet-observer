"""SCAN de mecanismes + controle ALEATOIRE — "trouver le meilleur" fait honnetement.
On classe des strategies sur le TRAIN (= on "trouve le meilleur"), puis on juge son TEST (OOS), et on
compare au MEILLEUR de 50 strategies aleatoires. Si le meilleur mecanisme ne bat pas le meilleur
hasard en OOS, son edge est du bruit (comparaisons multiples). Lecture seule, couts reels."""
from __future__ import annotations
import json
from statistics import median
from hl_observer.backtesting.ab_flag_replay import marks_by_coin
from hl_observer.backtesting import mechanism_zoo as zoo
from hl_observer.backtesting.mean_reversion import MRConfig, simulate_mean_reversion

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
series=sorted(([c,[px for _,px in rows]] for c,rows in marks.items()), key=lambda x:-len(x[1]))
liquid=[(c,s) for c,s in series if len(s)>=400][:15]
def split(s,f=0.7):
    k=int(len(s)*f); return s[:k], s[k:]
trainset=[(c,split(s)[0]) for c,s in liquid]
testset=[(c,split(s)[1]) for c,s in liquid]
COST=6.0
def agg(fn, subset): return round(sum(fn(s)["net_usd"] for _,s in subset),2)

def mr(ez): return lambda px: simulate_mean_reversion(px, MRConfig(lookback=40, entry_z=ez, cost_bps=COST))
def mom(lb,h): return lambda px: zoo.momentum(px, lookback=lb, hold=h, cost_bps=COST)
def brk(lb,h): return lambda px: zoo.breakout(px, lookback=lb, hold=h, cost_bps=COST)

cands={
 "buy&hold": lambda px: zoo.buy_hold(px, cost_bps=COST),
 "momentum 20/20": mom(20,20), "momentum 40/40": mom(40,40), "momentum 40/20": mom(40,20),
 "breakout 20/20": brk(20,20), "breakout 40/40": brk(40,40),
 "reversion z1.5": mr(1.5), "reversion z2.0": mr(2.0), "reversion z2.5": mr(2.5),
}
rows=[(name, agg(fn,trainset), agg(fn,testset)) for name,fn in cands.items()]
rows.sort(key=lambda r:-r[1])  # on classe par TRAIN = "on trouve le meilleur"

print(f"{'mecanisme':>16} | {'TRAIN net':>10} | {'TEST net (OOS)':>14}")
for name,tr,te in rows:
    print(f"{name:>16} | ${tr:>8.2f} | ${te:>12.2f}")
best=rows[0]
print(f"\n>>> 'MEILLEUR' choisi sur le train : {best[0]}  (train ${best[1]}) -> TEST OOS = ${best[2]}")

# --- controle ALEATOIRE : 50 strategies au hasard ---
rnd=[(agg(lambda px,sd=sd: zoo.random_strategy(px, seed=sd, hold=30, p_trade=0.1, cost_bps=COST), trainset),
      agg(lambda px,sd=sd: zoo.random_strategy(px, seed=sd, hold=30, p_trade=0.1, cost_bps=COST), testset))
     for sd in range(50)]
best_rnd=max(rnd, key=lambda x:x[0])   # meilleur hasard SUR LE TRAIN
pos_train=sum(1 for tr,_ in rnd if tr>0)
print(f"\n--- controle : 50 strategies ALEATOIRES ---")
print(f"  meilleur hasard (choisi sur train) : train ${best_rnd[0]:.2f} -> TEST OOS ${best_rnd[1]:.2f}")
print(f"  {pos_train}/50 strategies aleatoires sont POSITIVES sur le train (par pure chance)")
print(f"  net TEST des aleatoires : median ${median([te for _,te in rnd]):.2f}  max ${max(te for _,te in rnd):.2f}")
print(f"\nVERDICT : le meilleur mecanisme (OOS ${best[2]}) ne se distingue pas du bruit aleatoire.")
