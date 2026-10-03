#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, tempfile, time, urllib.parse
from pathlib import Path
from typing import Any, Mapping

TARGET="Rapt0r06300/hyperliquid-smart-wallet-observer"
PREFIXES=("data-v2-","copy-vault-v2-","archive-v2-","event-intelligence-v2-")
RUN="RUN_MANIFEST.json"; RECEIPT="LEGACY_MIGRATION_RECEIPT.json"

class E(RuntimeError): pass

def sh(args, ok=True):
    p=subprocess.run(args,text=True,capture_output=True,encoding="utf-8",errors="replace")
    if ok and p.returncode:
        raise E((p.stderr or p.stdout or "command failed").strip())
    return p

def gh(*args, ok=True): return sh(["gh",*args],ok=ok)
def jgh(*args):
    try: return json.loads(gh(*args).stdout)
    except json.JSONDecodeError as e: raise E(f"invalid GitHub JSON: {' '.join(args)}") from e

def rel(repo,tag):
    enc=urllib.parse.quote(tag,safe="")
    p=gh("api",f"repos/{repo}/releases/tags/{enc}",ok=False)
    if p.returncode:
        s=(p.stderr or p.stdout).lower()
        if "404" in s or "not found" in s: return None
        raise E((p.stderr or p.stdout).strip())
    return json.loads(p.stdout)

def releases(repo):
    rows=jgh("release","list","--repo",repo,"--limit","100000","--json","tagName,name,isDraft,isPrerelease,publishedAt")
    rows=[r for r in rows if not r.get("isDraft") and str(r.get("tagName") or "").startswith(PREFIXES)]
    return sorted(rows,key=lambda r:(str(r.get("publishedAt") or ""),str(r.get("tagName") or "")))

def amap(r): return {str(a["name"]):a for a in (r.get("assets") or []) if isinstance(a,dict) and a.get("name")}
def dsha(v):
    s=str(v or "")
    if s.lower().startswith("sha256:"):
        x=s.split(":",1)[1].lower(); return x if len(x)==64 else ""
    return ""
def fsha(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def compatible(a,size,sha): return isinstance(a,Mapping) and int(a.get("size") or 0)==size and dsha(a.get("digest"))==sha

def download(a,p):
    u=str(a.get("browser_download_url") or "")
    if not u: raise E(f"missing download URL: {a.get('name')}")
    p.parent.mkdir(parents=True,exist_ok=True)
    sh(["curl","--fail","--location","--silent","--show-error","--retry","5","--retry-all-errors","--connect-timeout","30","--max-time","7200","-o",str(p),u])
    size=p.stat().st_size; exp=int(a.get("size") or 0); sha=fsha(p); src=dsha(a.get("digest"))
    if exp and size!=exp: raise E(f"size mismatch: {a.get('name')}")
    if src and sha!=src: raise E(f"sha mismatch: {a.get('name')}")
    return size,sha

def upload(repo,tag,p,clobber=False):
    args=["release","upload",tag,str(p),"--repo",repo]+(["--clobber"] if clobber else [])
    for n in range(1,7):
        x=gh(*args,ok=False)
        if not x.returncode:return
        s=(x.stderr or x.stdout).lower()
        if n==6 or not any(k in s for k in ("rate limit","timeout","502","503","connection reset","404")): raise E((x.stderr or x.stdout).strip())
        time.sleep(min(60,2**n))

def ensure(source,target):
    tag=str(source.get("tag_name") or ""); r=rel(target,tag)
    if r:return r
    args=["release","create",tag,"--repo",target,"--target","main","--title",str(source.get("name") or tag),"--notes","Historical immutable Alina data migrated into the canonical repository after byte verification."]
    if source.get("prerelease") is True: args.append("--prerelease")
    gh(*args); r=rel(target,tag)
    if not r: raise E(f"target release not visible: {tag}")
    return r

def writej(p,o):
    p.parent.mkdir(parents=True,exist_ok=True); q=p.with_suffix(p.suffix+".tmp")
    q.write_text(json.dumps(o,indent=2,sort_keys=True)+"\n",encoding="utf-8"); os.replace(q,p)

def native_manifest(src,target,tag,tr,ta,src_sha):
    o=json.loads(json.dumps(src))
    if o.get("schema")!="alina.dataset_run_manifest.v2": raise E(f"unexpected manifest schema: {tag}")
    rid=int(tr.get("id") or 0); o.update(repository=target,release_id=rid,release_tag=tag)
    o["migration_receipt"]={"schema":"alina.target_native_release_migration.v1","source_manifest_sha256":src_sha,"target_repository":target,"all_data_assets_verified":True}
    ms=o.get("manifests")
    if not isinstance(ms,list): raise E(f"no manifests array: {tag}")
    for m in ms:
        if not isinstance(m,dict): continue
        rr=m.get("release") if isinstance(m.get("release"),dict) else {}
        name=str(m.get("release_asset") or rr.get("asset_name") or ""); a=ta.get(name)
        size=int(m.get("bytes") or 0); sha=str(m.get("sha256") or "").lower()
        if not name or not a or size<=0 or len(sha)!=64 or not compatible(a,size,sha): raise E(f"target asset not verified: {tag}/{name}")
        aid=int(a.get("id") or 0); dig=str(a.get("digest") or "")
        m["asset_verified"]=True
        m["release"]={"repository":target,"tag":tag,"release_id":rid,"asset_id":aid,"asset_name":name,"remote_size":size,"remote_digest":dig}
        m.update(release_repository=target,release_tag=tag,release_id=rid,release_asset_id=aid,release_remote_size=size,release_remote_digest=dig)
    return o

def copy_one(source,target,tag):
    sr=rel(source,tag)
    if not sr: raise E(f"source release disappeared: {tag}")
    tr=ensure(sr,target); sa=amap(sr); ma=sa.pop(RUN,None); sa.pop(RECEIPT,None)
    copied=bytes_=0; expected={}
    with tempfile.TemporaryDirectory(prefix="alina-migrate-") as td:
        td=Path(td); ta=amap(tr)
        for name,a in sa.items():
            size=int(a.get("size") or 0); sha=dsha(a.get("digest")); dst=ta.get(name)
            if sha and compatible(dst,size,sha): expected[name]=(size,sha); continue
            p=td/name; size,sha=download(a,p); expected[name]=(size,sha)
            if dst:
                if not compatible(dst,size,sha): raise E(f"target collision: {tag}/{name}")
            else:
                upload(target,tag,p); copied+=1; bytes_+=size
            p.unlink(missing_ok=True)
        tr=rel(target,tag)
        if not tr: raise E(f"target release disappeared: {tag}")
        ta=amap(tr)
        for n,(z,h) in expected.items():
            if not compatible(ta.get(n),z,h): raise E(f"post-upload verify failed: {tag}/{n}")
        native=False
        if ma:
            mp=td/RUN; _,srcsha=download(ma,mp); src=json.loads(mp.read_text(encoding="utf-8"))
            out=native_manifest(src,target,tag,tr,ta,srcsha); writej(mp,out); z=mp.stat().st_size; h=fsha(mp); cur=ta.get(RUN)
            if cur and not compatible(cur,z,h):
                ep=td/"existing.json"; download(cur,ep); ex=json.loads(ep.read_text(encoding="utf-8"))
                if isinstance(ex,dict) and ex.get("repository")==target: raise E(f"target-native manifest conflict: {tag}")
                upload(target,tag,mp,True)
            elif not cur: upload(target,tag,mp)
            final=amap(rel(target,tag) or {})
            if not compatible(final.get(RUN),z,h): raise E(f"native manifest verify failed: {tag}")
            native=True
        else:
            rec={"schema":"alina.legacy_release_quarantine_receipt.v1","release_tag":tag,"target_repository":target,"source_had_run_manifest":False,"assets":[{"name":n,"bytes":z,"sha256":h} for n,(z,h) in sorted(expected.items())],"validation_allowed":False,"reason":"SOURCE_RELEASE_WITHOUT_RUN_MANIFEST_PRESERVED_AS_QUARANTINE"}
            p=td/RECEIPT; writej(p,rec); z=p.stat().st_size; h=fsha(p); cur=amap(rel(target,tag) or {}).get(RECEIPT)
            if cur is None: upload(target,tag,p)
            elif not compatible(cur,z,h): raise E(f"quarantine receipt conflict: {tag}")
    return {"copied_assets":copied,"copied_bytes":bytes_,"native":native,"quarantine":ma is None}

def inv(rows): return hashlib.sha256("\n".join(f"{r.get('publishedAt') or ''}\t{r.get('tagName') or ''}\t{bool(r.get('isPrerelease'))}" for r in rows).encode()).hexdigest()
def load(p):
    try:o=json.loads(p.read_text(encoding="utf-8")); return o if isinstance(o,dict) else {}
    except Exception:return {}
def mark(unified,target,done):
    o=json.loads(unified.read_text(encoding="utf-8")); o.pop("source_repository",None)
    o.update(target_repository=target,mode="single-active-repository",heavy_data_storage="github_releases_same_repository",collection_storage_repository=target,external_dataset_repository_required=False,legacy_release_mirror_required=False,historical_release_migration_status="COMPLETE" if done else "IN_PROGRESS")
    if done:o.update(fresh_dataset_state=False,legacy_collection_state_imported=True)
    writej(unified,o)

def migrate(source,target,state,unified,max_releases,budget):
    if target!=TARGET or source==target: raise E("invalid migration repository binding")
    u=load(unified)
    if u.get("legacy_collection_state_imported") is True:
        mark(unified,target,True)
        s=load(state); s.update(schema="alina.legacy_release_migration.v1",status="COMPLETE",target_repository=target,pending_releases=0); writej(state,s); return s
    mark(unified,target,False)
    rs=releases(source); digest=inv(rs); s=load(state); old=str(s.get("inventory_sha256") or "")
    if old and old!=digest: raise E("historical release inventory changed during migration")
    i=int(s.get("next_index") or 0)
    if not 0<=i<=len(rs): raise E("invalid migration cursor")
    s.update(schema="alina.legacy_release_migration.v1",status="IN_PROGRESS",target_repository=target,inventory_sha256=digest,total_source_production_releases=len(rs),next_index=i,pending_releases=len(rs)-i,historical_trade_baseline=s.get("historical_trade_baseline") or {"raw_trades":27855717,"global_unique_trades":21973554,"evidence":"canonical epoch-5 closure receipt already committed on main"},copied_assets=int(s.get("copied_assets") or 0),copied_bytes=int(s.get("copied_bytes") or 0),migrated_releases=int(s.get("migrated_releases") or 0),native_manifest_releases=int(s.get("native_manifest_releases") or 0),quarantined_releases=int(s.get("quarantined_releases") or 0),quarantined_tags=list(s.get("quarantined_tags") or []),fail_closed=True,paper_only=True,read_only=True,real_execution=False); writej(state,s)
    start=time.monotonic(); n=0
    while i<len(rs) and n<max_releases:
        if n and time.monotonic()-start>=budget: break
        tag=str(rs[i].get("tagName") or ""); r=copy_one(source,target,tag); i+=1; n+=1
        s["next_index"]=i; s["pending_releases"]=len(rs)-i; s["migrated_releases"]+=1; s["copied_assets"]+=r["copied_assets"]; s["copied_bytes"]+=r["copied_bytes"]
        if r["native"]:s["native_manifest_releases"]+=1
        if r["quarantine"]:
            s["quarantined_releases"]+=1
            if tag not in s["quarantined_tags"]:s["quarantined_tags"].append(tag)
        s["last_completed_tag"]=tag; writej(state,s)
    if i==len(rs):
        s.update(status="COMPLETE",pending_releases=0,all_source_assets_preserved=True,all_manifest_bearing_releases_target_native=True); mark(unified,target,True)
    writej(state,s); return s

def main():
    p=argparse.ArgumentParser(); p.add_argument("--source-repository",required=True); p.add_argument("--target-repository",default=os.getenv("GITHUB_REPOSITORY") or TARGET); p.add_argument("--state",type=Path,default=Path("control/legacy-release-migration.json")); p.add_argument("--unified",type=Path,default=Path("control/unified-repository.json")); p.add_argument("--max-releases",type=int,default=8); p.add_argument("--time-budget-seconds",type=int,default=16200); a=p.parse_args()
    try:r=migrate(a.source_repository,a.target_repository,a.state,a.unified,a.max_releases,a.time_budget_seconds)
    except Exception as e: print(f"LEGACY_RELEASE_MIGRATION_NO_GO: {e}"); return 2
    print(json.dumps(r,indent=2,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
