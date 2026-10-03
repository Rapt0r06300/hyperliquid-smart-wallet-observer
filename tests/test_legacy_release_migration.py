from __future__ import annotations
import importlib.util, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def mod():
    s=importlib.util.spec_from_file_location("m",ROOT/"tools"/"migrate_legacy_releases_to_main.py")
    assert s and s.loader
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

def test_native_manifest_rebinds_repository():
    m=mod(); h="a"*64
    src={"schema":"alina.dataset_run_manifest.v2","repository":"old/x","manifests":[{"dataset_id":"d","release_asset":"d.gz","bytes":12,"sha256":h,"release_repository":"old/x","release":{"repository":"old/x","asset_name":"d.gz"}}]}
    out=m.native_manifest(src,m.TARGET,"data-v2-x",{"id":9},{"d.gz":{"id":10,"size":12,"digest":f"sha256:{h}"}},"b"*64)
    r=out["manifests"][0]
    assert out["repository"]==m.TARGET
    assert r["release_repository"]==m.TARGET
    assert r["release"]["repository"]==m.TARGET
    assert r["asset_verified"] is True

def test_mark_complete_removes_external_dependency(tmp_path:Path):
    m=mod(); p=tmp_path/"u.json"
    p.write_text(json.dumps({"source_repository":"old/x","legacy_collection_state_imported":False,"fresh_dataset_state":True}),encoding="utf-8")
    m.mark(p,m.TARGET,True); o=json.loads(p.read_text())
    assert "source_repository" not in o
    assert o["collection_storage_repository"]==m.TARGET
    assert o["external_dataset_repository_required"] is False
    assert o["legacy_collection_state_imported"] is True
    assert o["fresh_dataset_state"] is False

def test_inventory_digest_deterministic():
    m=mod(); rows=[{"publishedAt":"1","tagName":"a","isPrerelease":False},{"publishedAt":"2","tagName":"b","isPrerelease":False}]
    assert m.inv(rows)==m.inv(list(rows))
    assert m.inv(rows)!=m.inv(list(reversed(rows)))
