"""Grid/MM — épreuve de vérité : (1) fills réalistes (adverse) sur vrais prix, (2) stress-test sur
des régimes que les 6h ne contiennent pas (tendances, crash). Lecture seule, aucun ordre."""
from __future__ import annotations
import json, math
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
liquid=[c for c,s in series.items() if len(s)>=300][:15]

print("========== 1) FILLS REALISTES sur vrais prix (grid 30/30 x6 constant, 15 coins ~6h) ==========")
print(f"{'adverse/fill':>13} {'net_total':>10} {'wins':>5} {'blowups':>7}")
for adv in (0.0, 2.0, 5.0, 8.0):
    cfg=GridConfig(grid_bps=30,tp_bps=30,max_adds=6,hard_stop_bps=300,add_size_mult=1.0,adverse_bps=adv)
    net=0.0; wins=blow=0
    for c in liquid:
        r=simulate_grid(series[c], cfg); net+=r["net_usd"]; wins+=r["wins"]; blow+=r["blowups"]
    tag = "optimiste" if adv==0 else ("realiste" if adv in (2.0,5.0) else "pessimiste")
    print(f"{adv:>10.0f}b  ${net:>9.2f} {wins:>6} {blow:>7}   [{tag}]")

# ---------- 2) STRESS TEST sur régimes synthétiques (ce que les 6h de calme n'ont pas) ----------
def path_range(n=400):     # oscillation +/-0.5% (l'ami du grid)
    return [100.0*(1+0.005*math.sin(i/6.0)) for i in range(n)]
def path_downtrend(n=400): # tendance baissiere lente -0.15%/pas
    return [100.0*(1-0.0015*i) for i in range(n)]
def path_flash_crash(n=400):  # calme puis -20% rapide puis rebond partiel
    out=[100.0]*120
    for i in range(40): out.append(100.0*(1-0.005*i))   # -20%
    for i in range(60): out.append(80.0*(1+0.001*i))    # rebond mou
    out += [85.0]* (n-len(out))
    return out
def path_uptrend(n=400):   # tendance haussiere +0.15%/pas
    return [100.0*(1+0.0015*i) for i in range(n)]

regimes={"range (calme)":path_range(),"downtrend":path_downtrend(),
         "flash-crash":path_flash_crash(),"uptrend":path_uptrend()}
print("\n========== 2) STRESS-TEST par régime (fills réalistes adverse=3b) ==========")
print(f"{'régime':>16} | {'grid constant':>28} | {'MARTINGALE x2':>28}")
print(f"{'':>16} | {'net / wins / blow / DD':>28} | {'net / wins / blow / DD':>28}")
for name,px in regimes.items():
    g=simulate_grid(px, GridConfig(grid_bps=30,tp_bps=30,max_adds=6,hard_stop_bps=300,add_size_mult=1.0,adverse_bps=3.0))
    m=simulate_grid(px, GridConfig(grid_bps=30,tp_bps=30,max_adds=6,hard_stop_bps=300,add_size_mult=2.0,adverse_bps=3.0))
    def fmt(r): return f"${r['net_usd']:>7.1f}/{r['wins']:>2}/{r['blowups']}/${r['max_drawdown_usd']:>6.1f}"
    print(f"{name:>16} | {fmt(g):>28} | {fmt(m):>28}")
