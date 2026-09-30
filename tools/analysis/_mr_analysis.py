"""Reversion a la moyenne sur vrais prix HL, HORS-ECHANTILLON + couts reels (lecture seule)."""
from __future__ import annotations
import json
from hl_observer.backtesting.ab_flag_replay import marks_by_coin
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
print(f"coins: {[c for c,_ in liquid]}\n(split 70/30 par coin ; cout aller-retour 6 bps ; $500/trade)\n")

def split(s,f=0.7):
    k=int(len(s)*f); return s[:k], s[k:]

for label,cost in (("cout REALISTE 6 bps",6.0),("cout 0 (theorique, sans frais)",0.0)):
    print(f"===== {label} =====")
    for ez in (1.5, 2.0, 2.5):
        cfg=MRConfig(lookback=40, entry_z=ez, exit_z=0.3, hard_stop_z=4.0, hold_max=60, cost_bps=cost)
        tr_net=te_net=0.0; tr_tr=te_tr=0
        for c,s in liquid:
            tr,te=split(s)
            a=simulate_mean_reversion(tr,cfg); b=simulate_mean_reversion(te,cfg)
            tr_net+=a["net_usd"]; te_net+=b["net_usd"]; tr_tr+=a["trades"]; te_tr+=b["trades"]
        print(f"  entry_z={ez}:  TRAIN net=${tr_net:>8.2f} ({tr_tr} trades)   TEST(OOS) net=${te_net:>8.2f} ({te_tr} trades)")
    print()

print("=== detail par coin (entry_z=2.0, cout 6 bps, TEST/OOS) ===")
cfg=MRConfig(lookback=40, entry_z=2.0, cost_bps=6.0)
for c,s in liquid:
    _,te=split(s)
    r=simulate_mean_reversion(te,cfg)
    print(f"  {c:12} net=${r['net_usd']:>8.2f}  trades={r['trades']:>3}  wr={r['win_rate']}  pf={r['profit_factor']}  DD=${r['max_drawdown_usd']:>7.2f}")
