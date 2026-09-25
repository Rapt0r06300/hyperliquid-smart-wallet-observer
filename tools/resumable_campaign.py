#!/usr/bin/env python3
"""Atomic CLI for Dataset V2 campaign manifests."""
from __future__ import annotations
import argparse,json,os,tempfile
from datetime import datetime,timezone,timedelta
from pathlib import Path
from hl_observer.control_plane.resumable_campaign import CampaignManifest,acquire_lease,complete_work_unit,mark_continuation,mark_terminal,select_due_campaigns,sha256_json,validate_manifest

def load(p): return CampaignManifest.from_dict(json.loads(Path(p).read_text()))
def save(p,m,expected=None):
 p=Path(p)
 if p.exists() and expected and sha256_json(json.loads(p.read_text()))!=expected: raise SystemExit("manifest changed")
 p.parent.mkdir(parents=True,exist_ok=True);data=json.dumps(m.to_dict(),sort_keys=True,indent=2)+'\n';fd,tmp=tempfile.mkstemp(dir=p.parent,prefix=p.name+'.');os.write(fd,data.encode());os.close(fd);os.replace(tmp,p)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('command',choices=['create','validate','list-due','acquire-lease','record-unit','continue','finish','fail']);ap.add_argument('path');ap.add_argument('--campaign-id');ap.add_argument('--kind');ap.add_argument('--code-sha');ap.add_argument('--dataset-generation',default='V2_FRESH');ap.add_argument('--config-sha256',default='schedule');ap.add_argument('--work-plan-sha256',default='schedule');ap.add_argument('--token');ap.add_argument('--owner');ap.add_argument('--unit-id');ap.add_argument('--sha256');ap.add_argument('--expected-digest');ap.add_argument('--reason',default='cli');a=ap.parse_args();p=Path(a.path)
 if a.command=='create':
  if p.exists(): print(sha256_json(json.loads(p.read_text()))); return
  exp=(datetime.now(timezone.utc)+timedelta(days=7)).isoformat();m=CampaignManifest(a.campaign_id or p.stem,a.kind or '', 'Rapt0r06300/hyperliquid-smart-wallet-observer',a.code_sha or '', 'Rapt0r06300/alina-smartflow-datasets-v2',a.dataset_generation,a.config_sha256,a.work_plan_sha256,exp);save(p,m);print(sha256_json(m.to_dict()));return
 if a.command=='list-due': print('\n'.join(m.campaign_id for m in select_due_campaigns([load(x) for x in sorted(p.glob('*.json'))])));return
 m=load(p)
 if a.command=='validate':validate_manifest(m);print(sha256_json(m.to_dict()));return
 if a.command=='acquire-lease':
  token=acquire_lease(m,a.owner or 'manual',3600);save(p,m,a.expected_digest);print(f'::add-mask::{token}');print(f'lease_token={token}');return
 if a.command=='record-unit':complete_work_unit(m,a.unit_id or '',a.sha256 or '',{});save(p,m,a.expected_digest);return
 if a.command=='continue':mark_continuation(m,a.reason,progressed=True);save(p,m,a.expected_digest);return
 if a.command=='finish':mark_terminal(m,'COMPLETE',a.reason);save(p,m,a.expected_digest);return
 if a.command=='fail':mark_terminal(m,'FAILED',a.reason);save(p,m,a.expected_digest)
if __name__=='__main__':main()
