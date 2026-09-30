"""ETAPE 5 — le modele predictif bat-il le HASARD en hors-echantillon ? (lecture seule, aucun ordre)
Label = un signal donne-t-il un trade net-positif (sortie #1, couts reels) ? Features = scan.
On entraine sur le TRAIN, on juge sur le TEST, et on compare a une selection ALEATOIRE."""
from __future__ import annotations
import json, random
from statistics import fmean
from hl_observer.backtesting.ab_flag_replay import marks_by_coin
from hl_observer.backtesting import scenario_search as ss
from hl_observer.backtesting.scenario_grid import Scenario
from hl_observer.backtesting import edge_predictor as ep

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
train_c, test_c = ss.temporal_split(meas, 0.7)

def SC():
    return Scenario(name="lbl", sl_bps=126.0, tp_bps=40.0, trailing_stop_bps=132.0,
        trailing_activation_bps=201.0, breakeven_bps=14.0, horizon_min=480.0, cost_bps=6.0,
        min_edge_bps=0.0, source="lbl", max_signal_age_ms=0.0, min_liquidity_score=0.0,
        min_consensus_wallets=1, max_copy_degradation_bps=0.0, min_leader_score=0.0,
        side_mode="both", catastrophic_stop_bps=180.0)

def build(cands):
    X=[]; y=[]; nets=[]
    sc=SC()
    for c in cands:
        t=ss.eval_trades(sc, [c], marks, 500.0)
        if not t: continue
        net=t[0]
        X.append(ep.features_of(c)); y.append(1 if net>0 else 0); nets.append(net)
    return X,y,nets

Xtr,ytr,ntr = build(train_c)
Xte,yte,nte = build(test_c)
print(f"train trades={len(Xtr)} (positifs {100*sum(ytr)/len(ytr):.0f}%)  test trades={len(Xte)} (positifs {100*sum(yte)/len(yte):.0f}%)")
print(f"net TOTAL si on prend TOUS les trades du test : ${sum(nte):.2f}\n")

# standardisation sur TRAIN, fit sur un echantillon (vitesse), jugement sur TEST complet
mean,std = ep.fit_standardizer(Xtr)
rng=random.Random(0)
idx=list(range(len(Xtr))); rng.shuffle(idx); idx=idx[:8000]
Xtr_s=ep.apply_standardizer([Xtr[i] for i in idx], mean, std)
ytr_s=[ytr[i] for i in idx]
w,b = ep.fit_logreg(Xtr_s, ytr_s, epochs=150, lr=0.3)

Xte_s=ep.apply_standardizer(Xte, mean, std)
prob=ep.predict_proba(Xte_s, w, b)
acc=sum(1 for i in range(len(yte)) if (prob[i]>0.5)==bool(yte[i]))/len(yte)

# selection du modele : trades predits gagnants
sel=[nte[i] for i in range(len(nte)) if prob[i]>0.5]
k=len(sel)
print(f"=== JUGEMENT HORS-ECHANTILLON ===")
print(f"accuracy test = {acc:.3f}   (part reellement gagnants = {sum(yte)/len(yte):.3f})")
print(f"le modele SELECTIONNE {k}/{len(nte)} trades  ->  net = ${sum(sel):.2f}  (par trade ${fmean(sel) if sel else 0:.3f})")

# controle ALEATOIRE : selection de meme taille au hasard
if 0<k<len(nte):
    rr=[]
    for s in range(30):
        rg=random.Random(s); pick=rg.sample(range(len(nte)), k)
        rr.append(sum(nte[i] for i in pick))
    print(f"selection ALEATOIRE de meme taille ({k}) : net median ${sorted(rr)[len(rr)//2]:.2f}  (max ${max(rr):.2f})")
    print(f"\nVERDICT : le modele bat-il le hasard en OOS ? "
          f"{'OUI (a creuser!)' if sum(sel)>max(rr) and sum(sel)>0 else 'NON — indistinct du hasard / negatif'}")
else:
    print("\nVERDICT : le modele ne selectionne rien d'exploitable.")
