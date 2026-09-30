"""Preuve de la cause racine : sensibilite a la DEGRADATION DE COPIE (=fraicheur du signal).
Sur la meilleure tranche OOS, on rejoue en supposant des signaux plus frais (degr plus faible).
Si le net bascule positif quand degr baisse => le levier est la FRAICHEUR, pas le calibrage.
Lecture seule, aucun ordre.
"""
from __future__ import annotations
import json, copy
from hl_observer.backtesting.ab_flag_replay import marks_by_coin
from hl_observer.backtesting import scenario_search as ss
from hl_observer.backtesting.scenario_grid import Scenario

def load_jsonl(path):
    out=[]
    with open(path) as f:
        for line in f:
            line=line.strip()
            if line:
                try: out.append(json.loads(line))
                except Exception: pass
    return out

cands = load_jsonl("runtime/replay/_archive/run_20260709_152414/candidates.jsonl")
marks = marks_by_coin(load_jsonl("runtime/replay/_archive/run_20260709_152414/marks.jsonl"))
meas = ss.prefilter_candidates(cands, marks)
train, test = ss.temporal_split(meas, 0.7)

def sc(name, **kw):
    d = dict(name=name, sl_bps=126.0, tp_bps=40.0, trailing_stop_bps=132.0,
             trailing_activation_bps=201.0, breakeven_bps=14.0, horizon_min=480.0,
             cost_bps=6.0, min_edge_bps=0.0, source="sens", max_signal_age_ms=0.0,
             min_liquidity_score=0.0, min_consensus_wallets=1, max_copy_degradation_bps=0.0,
             min_leader_score=0.0, side_mode="both", catastrophic_stop_bps=180.0)
    d.update(kw); return Scenario(**d)

# meilleures tranches vues en OOS
SLICES = {
 "edge>=40":            dict(min_edge_bps=40.0),
 "edge40+fresh10":      dict(min_edge_bps=40.0, max_signal_age_ms=10000.0),
 "edge50+fresh10+cons3":dict(min_edge_bps=50.0, max_signal_age_ms=10000.0, min_consensus_wallets=3),
}
# on force max_copy_degradation tres haut pour ne pas exclure, puis on CLAMP la valeur de cout
def clamp_degr(rows, cap):
    out=[]
    for c in rows:
        d=dict(c);
        cur=abs(float(d.get("copy_degradation_bps") or 0.0))
        d["copy_degradation_bps"]=min(cur, cap)
        out.append(d)
    return out

DEGR_LEVELS = [13.0, 8.0, 4.0, 2.0, 0.0]  # 13≈actuel (signaux ~57s) ; 2-4≈signaux sub-seconde
print("Sensibilite du NET OOS (TEST) a la degradation de copie (fraicheur), sortie=#1 :")
print(f"{'slice':22} " + " ".join(f"degr<={d:>4}" for d in DEGR_LEVELS))
for sname, sf in SLICES.items():
    scn = sc(sname, **sf, max_copy_degradation_bps=9999.0)
    line=f"{sname:22} "
    for cap in DEGR_LEVELS:
        rep = ss.report_from_trades(ss.eval_trades(scn, clamp_degr(test, cap), marks, 500.0))
        line += f"{rep['net_total_usd']:>9.1f}"
    print(line)
print("\n(memes trades, on ne fait varier QUE le cout de degradation = proxy de la fraicheur du signal)")
print("degr~13 bps = signaux mediane 57s (actuel). degr~2-4 bps = signaux quasi temps reel (firehose).")
