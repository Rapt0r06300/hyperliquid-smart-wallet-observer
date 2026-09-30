"""ORACLE EXIT — teste l'hypothese "c'est le SL/TP mal calibre". On calcule, pour chaque signal, la
MEILLEURE sortie POSSIBLE (au sommet favorable du chemin, avec hindsight = triche) = le PLAFOND
absolu d'un SL/TP parfait. Si meme ce plafond est bas apres couts, aucun reglage de sortie ne peut
sauver la strategie -> le probleme est l'ENTREE, pas la sortie. Lecture seule, aucun ordre."""
from __future__ import annotations
import json
from statistics import median, fmean
from hl_observer.backtesting.ab_flag_replay import marks_by_coin
from hl_observer.backtesting import scenario_search as ss

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
cands=ss.prefilter_candidates(load_jsonl(base+"/candidates.jsonl"), marks)
HORIZON_MS=60*60*1000  # 60 min de detention max
COST_BASE=6.0

def excursions(c):
    coin=str(c.get("coin") or "").upper(); side=str(c.get("direction") or "").upper()
    entry=float(c.get("current_mid") or 0.0); ts=float(c.get("recorded_at") or 0.0)
    path=marks.get(coin, [])
    fav=adv=0.0
    for pts,pmid in path:
        if pts<=ts: continue
        if pts>ts+HORIZON_MS: break
        move=(pmid-entry)/entry*10000.0  # bps signe (LONG-relatif)
        if side=="SHORT": move=-move
        fav=max(fav,move); adv=min(adv,move)
    return fav, adv

rows=[]
for c in cands:
    fav,adv=excursions(c)
    deg=abs(float(c.get("copy_degradation_bps") or 0.0))
    cost=COST_BASE+deg
    oracle_net_bps=fav-cost           # sortie PARFAITE (au sommet) moins couts
    rows.append((c, fav, adv, cost, oracle_net_bps))

favs=[r[1] for r in rows]; advs=[r[2] for r in rows]; onet=[r[4] for r in rows]
print(f"signaux mesurables: {len(rows)} | horizon 60min | notional $500")
print(f"\nExcursion FAVORABLE (meilleur mouvement possible)  : median {median(favs):.1f} bps")
print(f"Excursion ADVERSE  (pire mouvement, risque de SL)   : median {median(advs):.1f} bps")
print(f"Cout moyen (frais+spread+degradation copie)         : {fmean([r[3] for r in rows]):.1f} bps")
print(f"\n=== PLAFOND SL/TP PARFAIT (oracle: sortie au sommet - couts) ===")
pos=sum(1 for x in onet if x>0)
print(f"  net oracle median : {median(onet):.1f} bps  |  moyen : {fmean(onet):.1f} bps")
print(f"  % de trades net-positifs MEME avec sortie parfaite : {100*pos/len(onet):.0f}%")
print(f"  PnL total si sortie PARFAITE partout : ${sum(500*x/10000 for x in onet):.0f} (plafond irrealisable)")

# --- l'entree est-elle le probleme ? plafond oracle par bande d'EDGE (qualite du scan) ---
print(f"\n=== Le scan aide-t-il ? plafond oracle par bande d'edge d'entree ===")
def band(lo,hi):
    sel=[r for r in rows if lo<=float(r[0].get('edge_remaining_bps') or -999)<hi]
    if not sel: return
    on=[r[4] for r in sel]
    print(f"  edge [{lo:>4},{hi:>4}) bps : n={len(sel):>5}  net oracle median {median(on):>6.1f} bps  %pos {100*sum(1 for x in on if x>0)/len(on):>3.0f}%")
for lo,hi in [(-999,0),(0,20),(20,40),(40,60),(60,999)]:
    band(lo,hi)
