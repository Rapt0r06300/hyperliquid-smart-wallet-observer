#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,time
from hl_observer.control_plane.campaign_adapters import AdapterContext,run_one_unit

def main():
 p=argparse.ArgumentParser(); p.add_argument("--campaign-id",required=True); p.add_argument("--kind",required=True); p.add_argument("--unit-id",required=True); p.add_argument("--partition-json",required=True); p.add_argument("--soft-deadline-s",type=int,default=18000); a=p.parse_args(); ctx=AdapterContext(a.campaign_id,a.kind,a.unit_id,time.time()+min(a.soft_deadline_s,18900),json.loads(a.partition_json)); r=run_one_unit(ctx); print(json.dumps({"status":r.status,"sha256":r.sha256,"payload":r.payload,"progressed":r.progressed},sort_keys=True))
if __name__=="__main__": main()
