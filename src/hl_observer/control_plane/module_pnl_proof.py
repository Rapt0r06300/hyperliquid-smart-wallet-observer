"""SAFE-only independent module paper-PnL proof."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Iterable, Mapping, Any
MODULES=("copy_vault","lead_lag","cross_venue_dislocation_v2","arbitrage")
@dataclass(frozen=True)
class ModulePnl:
    module:str; gross_pnl:float; fees:float; slippage:float; funding_financing:float; net_pnl:float; sample_size:int; threshold_usd:float; threshold_met:bool; proof_of_pnl:bool

def prove_module(module:str, rows:Iterable[Mapping[str,Any]], threshold_usd:float=4.0)->dict[str,Any]:
    if module not in MODULES: raise ValueError("unknown module")
    rows=list(rows)
    if not rows: raise ValueError("no evidence")
    if any(r.get("quality_status")!="SAFE" or not r.get("replay_compatible",False) for r in rows): raise ValueError("PnL proof requires SAFE replay-compatible inputs")
    gross=sum(float(r.get("gross_pnl",0)) for r in rows); fees=sum(float(r.get("fees",0)) for r in rows); slip=sum(float(r.get("slippage",0)) for r in rows); funding=sum(float(r.get("funding_financing",0)) for r in rows); net=gross-fees-slip-funding
    return asdict(ModulePnl(module,gross,fees,slip,funding,net,len(rows),threshold_usd,net>=threshold_usd,True))

def prove_all(evidence:Mapping[str,Iterable[Mapping[str,Any]]],threshold_usd:float=4.0)->dict[str,Any]:
    out={m:prove_module(m,evidence[m],threshold_usd) for m in MODULES}
    # Canonical attribution stays independent; never aggregate aliases into a pass verdict.
    return {"threshold_is_evaluation_only":True,"modules":out,"all_modules_independently_met":all(v["threshold_met"] for v in out.values())}
