"""Grid/MM 'grinder' sur les VRAIS prix Hyperliquid enregistres (lecture seule, aucun ordre).
On mesure le grind ET le tail (blow-ups, drawdown, inventaire coince). Honnete, sans promesse."""
from __future__ import annotations
import json
from hl_observer.backtesting.ab_flag_replay import marks_by_coin
from hl_observer.backtesting.grid_market_maker import GridConfig, simulate_grid

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
series={c:[px for _,px in rows] for c,rows in marks.items()}
liquid=sorted([(c,len(s)) for c,s in series.items() if len(s)>=300], key=lambda x:-x[1])[:15]
print(f"coins liquides (>=300 pts) retenus: {len(liquid)}  ->", [c for c,_ in liquid])
print("(fenetre ~6h ; capital nominal $50/palier)\n")

configs={
 "grid 30/30 x6 (constant)": GridConfig(grid_bps=30,tp_bps=30,max_adds=6,hard_stop_bps=300,add_size_mult=1.0),
 "grid 15/15 x8 (constant)": GridConfig(grid_bps=15,tp_bps=15,max_adds=8,hard_stop_bps=300,add_size_mult=1.0),
 "MARTINGALE 30/30 x6 (x2)": GridConfig(grid_bps=30,tp_bps=30,max_adds=6,hard_stop_bps=300,add_size_mult=2.0),
}
for name,cfg in configs.items():
    net=dd=0.0; wins=blow=0
    worst=None
    for c,_ in liquid:
        r=simulate_grid(series[c], cfg)
        net+=r["net_usd"]; dd+=r["max_drawdown_usd"]; wins+=r["wins"]; blow+=r["blowups"]
        if worst is None or r["net_usd"]<worst[1]: worst=(c,r["net_usd"],r["blowups"],r["max_drawdown_usd"])
    print(f"{name:26} net=${net:>9.2f}  wins={wins:>4}  blowups={blow:>3}  DD_cumule=${dd:>9.2f}")
    print(f"     pire coin: {worst[0]} net=${worst[1]:.2f} blowups={worst[2]} DD=${worst[3]:.2f}")

print("\n=== detail par coin (grid 30/30 x6 constant) ===")
cfg=configs["grid 30/30 x6 (constant)"]
for c,_ in liquid:
    r=simulate_grid(series[c], cfg)
    flag="  <-- BLOWUP" if r["blowups"]>0 else ""
    print(f"  {c:12} net=${r['net_usd']:>8.2f}  wins={r['wins']:>3}  blowups={r['blowups']}  DD=${r['max_drawdown_usd']:>7.2f}{flag}")
