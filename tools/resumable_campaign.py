#!/usr/bin/env python3
"""Atomic CLI for Dataset V2 campaign manifests."""
from __future__ import annotations
import argparse,json,os,tempfile
from pathlib import Path
from hl_observer.control_plane.resumable_campaign import CampaignManifest,acquire_lease,complete_work_unit,mark_continuation,mark_terminal,select_due_campaigns,sha256_json,validate_manifest

def load(p:Path): return CampaignManifest.from_dict(json.loads(p.read_text()))
def save(p:Path,m:CampaignManifest,expected:str|None=None):
    if p.exists() and expected and sha256_json(json.loads(p.read_text()))!=expected: raise SystemExit("manifest changed")
    p.parent.mkdir(parents=True,exist_ok=True); data=json.dumps(m.to_dict(),sort_keys=True,indent=2)+"\n"
    fd,tmp=tempfile.mkstemp(dir=p.parent,prefix=p.name+"."); os.write(fd,data.encode()); os.close(fd); os.replace(tmp,p)
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("command",choices=["validate","list-due","acquire-lease","record-unit","continue","finish","fail"]); ap.add_argument("path"); ap.add_argument("--token"); ap.add_argument("--owner"); ap.add_argument("--unit-id"); ap.add_argument("--sha256"); ap.add_argument("--expected-digest"); ap.add_argument("--reason",default="cli"); a=ap.parse_args(); p=Path(a.path)
    if a.command=="list-due":
        ms=[load(x) for x in sorted(p.glob("*.json"))]; print("\n".join(m.campaign_id for m in select_due_campaigns(ms))); return
    m=load(p)
    if a.command=="validate": validate_manifest(m); print(sha256_json(m.to_dict())); return
    if a.command=="acquire-lease":
        token=acquire_lease(m,a.owner or "manual",3600); save(p,m,a.expected_digest); print(f"::add-mask::{token}"); print(f"lease_token={token}"); return
    if a.command=="record-unit": complete_work_unit(m,a.unit_id or "",a.sha256 or "",{}); save(p,m,a.expected_digest); return
    if a.command=="continue": mark_continuation(m,a.reason,progressed=True); save(p,m,a.expected_digest); return
    if a.command=="finish": mark_terminal(m,"COMPLETE",a.reason); save(p,m,a.expected_digest); return
    if a.command=="fail": mark_terminal(m,"FAILED",a.reason); save(p,m,a.expected_digest)
if __name__=="__main__": main()
