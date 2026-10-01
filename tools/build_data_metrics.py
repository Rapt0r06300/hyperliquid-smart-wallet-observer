#!/usr/bin/env python3
"""Exact Dataset V2 record/trade metrics from local JSONL(.gz) shards.
Counts are parsed, never estimated from bytes. Replayable counts require explicit SAFE + replay_compatible evidence.
"""
from __future__ import annotations
import argparse,gzip,hashlib,json
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path

def opener(p): return gzip.open(p,'rt',encoding='utf-8') if p.name.endswith('.gz') else p.open(encoding='utf-8')
def typ(r):
 t=str(r.get('event_type') or r.get('type') or r.get('kind') or '').lower()
 if t in {'trade','fill','aggtrade','publictrade'} or ('price' in r and any(k in r for k in ('size','qty','amount')) and 'bid' not in r): return 'trade'
 if 'liquidat' in t:return 'liquidation'
 if 'fund' in t:return 'funding'
 if 'open_interest' in t or t=='oi':return 'open_interest'
 if 'bbo' in t or ('bid' in r and 'ask' in r):return 'bbo'
 if 'book' in t or 'depth' in t or 'l2' in t:return 'l2'
 return 'other'
def dkey(r):
 native=r.get('trade_id') or r.get('id') or r.get('exec_id')
 vals=[r.get('venue') or r.get('exchange'),r.get('symbol') or r.get('coin'),native if native is not None else r.get('timestamp') or r.get('ts'),None if native is not None else r.get('side'),None if native is not None else r.get('price'),None if native is not None else r.get('size') or r.get('qty') or r.get('amount')]
 return hashlib.sha256('|'.join(map(str,vals)).encode()).hexdigest()
def main():
 a=argparse.ArgumentParser();a.add_argument('paths',nargs='+');a.add_argument('--output',default='catalog/DATA_METRICS.json');x=a.parse_args();c=Counter();bv=defaultdict(Counter);bs=defaultdict(Counter);seen=set();files=0
 for pat in x.paths:
  for p in sorted(Path().glob(pat)):
   if not p.is_file() or not (p.name.endswith('.jsonl') or p.name.endswith('.jsonl.gz')):continue
   files+=1
   with opener(p) as f:
    for line in f:
     if not line.strip():continue
     try:r=json.loads(line)
     except Exception:c['invalid_records']+=1;continue
     k=typ(r);v=str(r.get('venue') or r.get('exchange') or 'unknown').lower();s=str(r.get('symbol') or r.get('coin') or 'unknown').upper();c['records']+=1;c[k]+=1;bv[v]['records']+=1;bv[v][k]+=1;bs[s]['records']+=1;bs[s][k]+=1
     if k=='trade':
      c['raw_trades']+=1;d=dkey(r)
      if d in seen:c['duplicate_trades']+=1
      else:seen.add(d);c['unique_trades']+=1;bv[v]['unique_trades']+=1;bs[s]['unique_trades']+=1
      safe=r.get('quality_status')=='SAFE'; replay=safe and r.get('replay_compatible') is True
      if safe:c['safe_trades']+=1
      if replay:c['replayable_trades']+=1
 out={'schema_version':'alina.data_metrics.v1','generated_at':datetime.now(timezone.utc).isoformat(),'method':'exact_parse_no_byte_estimation','files_parsed':files,'totals':dict(c),'by_venue':{k:dict(v) for k,v in sorted(bv.items())},'by_symbol':{k:dict(v) for k,v in sorted(bs.items())}}
 Path(x.output).parent.mkdir(parents=True,exist_ok=True);Path(x.output).write_text(json.dumps(out,indent=2,sort_keys=True)+'\n');print(json.dumps(out['totals'],sort_keys=True))
if __name__=='__main__':main()
