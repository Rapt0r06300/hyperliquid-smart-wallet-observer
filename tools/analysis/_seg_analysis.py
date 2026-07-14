"""Analyse par segments (LECTURE SEULE) : où l'edge net survit-il aux coûts, sur train ET test ?
Réutilise le vrai moteur eval_trades (no-lookahead, coûts réels, notional $500). Aucun ordre.
Guidé par la data (edge médian négatif, degr ~13 bps, signaux ~57s) : on chasse la tranche du
haut de distribution. Chaque config = filtres d'entrée + sortie ; jugée sur le HORS-ÉCHANTILLON.
"""
from __future__ import annotations
import json, glob
from hl_observer.backtesting.ab_flag_replay import marks_by_coin
from hl_observer.backtesting import scenario_search as ss
from hl_observer.backtesting.scenario_grid import Scenario

CAND_GLOB = "runtime/replay/_archive/run_20260709_152414/candidates.jsonl"
MARK_GLOB = "runtime/replay/_archive/run_20260709_152414/marks.jsonl"

def load_jsonl(path):
    out=[]
    with open(path) as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try: out.append(json.loads(line))
            except Exception: pass
    return out

cands = load_jsonl(CAND_GLOB)
mark_rows = load_jsonl(MARK_GLOB)
marks = marks_by_coin(mark_rows)
meas = ss.prefilter_candidates(cands, marks)
train, test = ss.temporal_split(meas, 0.7)
print(f"candidats bruts={len(cands)}  mesurables={len(meas)}  train={len(train)} test={len(test)}")
print(f"marks coins={len(marks)}  ex: {list(marks)[:8]}")

def sc(name, **kw):
    d = dict(name=name, sl_bps=60.0, tp_bps=120.0, trailing_stop_bps=0.0,
             trailing_activation_bps=0.0, breakeven_bps=0.0, horizon_min=120.0,
             cost_bps=6.0, min_edge_bps=0.0, source="seg",
             max_signal_age_ms=0.0, min_liquidity_score=0.0, min_consensus_wallets=1,
             max_copy_degradation_bps=0.0, min_leader_score=0.0, side_mode="both",
             catastrophic_stop_bps=0.0)
    d.update(kw); return Scenario(**d)

# --- Sorties candidates ---
EXITS = {
 "E_live(#1)":   dict(sl_bps=126.0, tp_bps=40.0, trailing_stop_bps=132.0, trailing_activation_bps=201.0, breakeven_bps=14.0, catastrophic_stop_bps=180.0, horizon_min=480.0),
 "E_prev":       dict(sl_bps=60.0,  tp_bps=120.0, trailing_stop_bps=30.0, trailing_activation_bps=45.0, breakeven_bps=0.0, horizon_min=240.0),
 "E_tpwide":     dict(sl_bps=180.0, tp_bps=70.0,  trailing_stop_bps=0.0, horizon_min=120.0),
 "E_tight":      dict(sl_bps=45.0,  tp_bps=45.0,  trailing_stop_bps=0.0, horizon_min=60.0),
}
# --- Filtres d'entrée (tranches) guidés par la distribution ---
ENTRIES = {
 "ALL":                 dict(),
 "edge>=19":            dict(min_edge_bps=19.0),
 "edge>=25":            dict(min_edge_bps=25.0),
 "edge>=30":            dict(min_edge_bps=30.0),
 "edge>=40":            dict(min_edge_bps=40.0),
 "edge>=50":            dict(min_edge_bps=50.0),
 "fresh<=10s":          dict(max_signal_age_ms=10000.0),
 "fresh<=5s":           dict(max_signal_age_ms=5000.0),
 "liq>=0.85":           dict(min_liquidity_score=0.85),
 "cons>=3":             dict(min_consensus_wallets=3),
 "cons>=4":             dict(min_consensus_wallets=4),
 "ls>=78":              dict(min_leader_score=78.0),
 "degr<=12.5":          dict(max_copy_degradation_bps=12.5),
 "edge30+fresh10+liq85": dict(min_edge_bps=30.0, max_signal_age_ms=10000.0, min_liquidity_score=0.85),
 "edge40+fresh10":       dict(min_edge_bps=40.0, max_signal_age_ms=10000.0),
 "edge30+cons3+liq85":   dict(min_edge_bps=30.0, min_consensus_wallets=3, min_liquidity_score=0.85),
 "edge50+fresh10+cons3": dict(min_edge_bps=50.0, max_signal_age_ms=10000.0, min_consensus_wallets=3),
 "edge25+fresh5+liq85+cons3": dict(min_edge_bps=25.0, max_signal_age_ms=5000.0, min_liquidity_score=0.85, min_consensus_wallets=3),
}

def ev(scn, pool):
    return ss.report_from_trades(ss.eval_trades(scn, pool, marks, 500.0))

rows=[]
# 1) Chaque tranche d'entrée sous la sortie LIVE (#1)
for ename, ef in ENTRIES.items():
    scn = sc("live/"+ename, **EXITS["E_live(#1)"], **ef)
    rtr, rte = ev(scn, train), ev(scn, test)
    rows.append(("E_live", ename, rtr, rte))
# 2) Les meilleures tranches croisées avec les autres sorties
best_entries = ["edge>=40","edge30+fresh10+liq85","edge40+fresh10","edge50+fresh10+cons3","edge25+fresh5+liq85+cons3"]
for xk in ["E_prev","E_tpwide","E_tight"]:
    for ename in best_entries:
        scn = sc(xk+"/"+ename, **EXITS[xk], **ENTRIES[ename])
        rtr, rte = ev(scn, train), ev(scn, test)
        rows.append((xk, ename, rtr, rte))

def f(r):
    return f"n={r['trades']:>4} net={r['net_total_usd']:>9.2f} pf={str(r['profit_factor']):>6} wr={r['win_rate']} dd={r['max_drawdown_usd']:>7.2f}"

print("\n================ SEGMENTS — TRAIN vs TEST(OOS) ================")
print(f"{'EXIT':7} {'ENTRY':26} | TRAIN                                    | TEST (OOS)")
for xk, ename, rtr, rte in rows:
    print(f"{xk:7} {ename:26} | {f(rtr):42} | {f(rte)}")

# Verdict : tranches positives sur train ET test (OOS), avec assez de trades
print("\n================ ROBUSTES (net>0 train ET test, test n>=15) ================")
robust=[]
for xk, ename, rtr, rte in rows:
    if rtr['net_total_usd']>0 and rte['net_total_usd']>0 and (rte['trades'] or 0)>=15:
        robust.append((xk,ename,rtr,rte))
if not robust:
    print("AUCUNE. => Pas de tranche à edge net positif qui survit au hors-échantillon.")
else:
    for xk,ename,rtr,rte in sorted(robust, key=lambda z: -z[3]['net_total_usd']):
        print(f"{xk:7} {ename:26} | TRAIN {f(rtr)} | TEST {f(rte)}")

out={"measurable":len(meas),"train":len(train),"test":len(test),
     "rows":[{"exit":x,"entry":e,"train":a,"test":b} for x,e,a,b in rows],
     "robust":[{"exit":x,"entry":e,"train":a,"test":b} for x,e,a,b in robust]}
open("runtime/scenarios/segment_analysis.json","w").write(json.dumps(out,indent=2))
print("\n-> runtime/scenarios/segment_analysis.json")
