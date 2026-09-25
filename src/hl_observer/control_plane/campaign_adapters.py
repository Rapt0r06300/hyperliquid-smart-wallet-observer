"""Deterministic bounded adapters for resumable campaigns."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib, json, subprocess, time
from typing import Any, Callable

@dataclass(frozen=True)
class AdapterContext:
    campaign_id: str
    kind: str
    unit_id: str
    soft_deadline_epoch: float
    partition: dict[str, Any]

@dataclass(frozen=True)
class AdapterResult:
    status: str
    sha256: str
    payload: dict[str, Any]
    progressed: bool = True

COMMANDS = {
 "market_collection":"tools/collect_cloud_window.py",
 "copy_vault_collection":"tools/collect_cloud_copy_vault.py",
 "official_archive_collection":"tools/collect_official_archives.py",
 "event_intelligence_collection":"tools/collect_event_intelligence_v2.py",
 "replay":"tools/replay_dataset_v2.py",
 "backtest":"tools/run_economic_objective_campaigns.py",
 "module_pnl_proof":"tools/run_economic_objective_campaigns.py",
}

def _digest(payload: dict[str, Any]) -> str:
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()

def run_one_unit(ctx: AdapterContext, runner: Callable[...,Any]=subprocess.run) -> AdapterResult:
    if time.time() >= ctx.soft_deadline_epoch: return AdapterResult("CONTINUATION_REQUIRED",_digest({"reason":"soft_deadline"}),{"reason":"soft_deadline"},False)
    script=COMMANDS.get(ctx.kind)
    if not script: raise ValueError(f"unsupported campaign kind: {ctx.kind}")
    timeout=max(1,int(ctx.soft_deadline_epoch-time.time()-5))
    cmd=["python",script,"--campaign-unit-json",json.dumps(ctx.partition,sort_keys=True,separators=(",",":"))]
    try:
        cp=runner(cmd,capture_output=True,text=True,timeout=timeout,check=False)
    except subprocess.TimeoutExpired:
        payload={"status":"CONTINUATION_REQUIRED","reason":"adapter_timeout"}; return AdapterResult(payload["status"],_digest(payload),payload,False)
    payload={"status":"COMPLETE" if cp.returncode==0 else "FAILED","returncode":cp.returncode,"stdout":cp.stdout[-8000:],"stderr":cp.stderr[-8000:]}
    return AdapterResult(payload["status"],_digest(payload),payload,cp.returncode==0)
