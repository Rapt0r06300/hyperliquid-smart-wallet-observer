from __future__ import annotations

import gzip
import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import hl_observer.datasets.github_release_bridge as bridge


def _asset(name="asset.bin", data=b"abc", *, asset_id=1) -> bridge.ReleaseAsset:
    return bridge.ReleaseAsset(asset_id=asset_id, name=name, size=len(data), digest="sha256:" + hashlib.sha256(data).hexdigest())


def test_release_asset_and_dataset_record_parsing() -> None:
    asset = bridge.ReleaseAsset(1, "x", 3, "sha256:abc")
    assert asset.sha256 == "abc"
    assert bridge.ReleaseAsset(1, "x", 3, "md5:abc").sha256 == ""
    record = bridge.DatasetRecord.from_mapping({
        "relative_path":"a/b.json", "size":"3", "sha256":"ff", "storage":"raw_chunks",
        "chunks":[{"asset":"p2","part":2}, "bad", {"asset":"p1","part":1}],
    })
    assert record.relative_path == "a/b.json" and record.size == 3
    assert record.needed_assets() == ("p2","p1")
    zipped = bridge.DatasetRecord.from_mapping({"relative_path":"x","storage":"zip_entry","asset":"z.zip"})
    assert zipped.needed_assets() == ("z.zip",)
    assert bridge.DatasetRecord.from_mapping({"relative_path":"x","storage":"other"}).needed_assets() == ()


def test_sha256_gh_path_and_run_text(tmp_path, monkeypatch) -> None:
    p = tmp_path / "x"; p.write_bytes(b"abc")
    assert bridge._sha256(p) == hashlib.sha256(b"abc").hexdigest()
    monkeypatch.setattr(bridge.shutil, "which", lambda name: None)
    with pytest.raises(bridge.DatasetBridgeError, match="GitHub CLI"):
        bridge._gh_path()
    monkeypatch.setattr(bridge.shutil, "which", lambda name: "/bin/gh")
    assert bridge._gh_path() == "/bin/gh"
    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout='{"ok":1}', stderr=""))
    assert bridge._run_gh_text(["api","x"]) == '{"ok":1}'
    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=2, stdout="", stderr="denied"))
    with pytest.raises(bridge.DatasetBridgeError, match="denied"):
        bridge._run_gh_text(["api","x"])


def test_load_release_and_release_assets(monkeypatch) -> None:
    monkeypatch.setattr(bridge, "_run_gh_text", lambda args: json.dumps({"name":"R","assets":[]}))
    assert bridge.load_release("o/r", 1)["name"] == "R"
    monkeypatch.setattr(bridge, "_run_gh_text", lambda args: "[]")
    with pytest.raises(bridge.DatasetBridgeError, match="Réponse GitHub invalide"):
        bridge.load_release()
    result = bridge.release_assets({"assets":[None, {}, {"name":"a","id":"1","size":"2","digest":"sha256:ff"}]})
    assert list(result) == ["a"] and result["a"].asset_id == 1
    assert bridge.release_assets({}) == {}


def test_verify_asset_all_failures_and_success(tmp_path) -> None:
    a = _asset(data=b"abc")
    p = tmp_path / a.name
    with pytest.raises(bridge.DatasetBridgeError, match="Fichier absent"):
        bridge.verify_asset(p, a)
    p.write_bytes(b"ab")
    with pytest.raises(bridge.DatasetBridgeError, match="Taille incorrecte"):
        bridge.verify_asset(p, a)
    nohash = bridge.ReleaseAsset(1,"asset.bin",2,"")
    with pytest.raises(bridge.DatasetBridgeError, match="SHA-256"):
        bridge.verify_asset(p, nohash)
    wrong = bridge.ReleaseAsset(1,"asset.bin",2,"sha256:" + "0"*64)
    with pytest.raises(bridge.DatasetBridgeError, match="SHA-256 incorrect"):
        bridge.verify_asset(p, wrong)
    p.write_bytes(b"abc")
    bridge.verify_asset(p, a)


def test_download_asset_cache_redownload_fail_and_success(tmp_path, monkeypatch) -> None:
    data=b"abc"; a=_asset(data=data)
    dest=tmp_path/a.name; dest.write_bytes(data)
    assert bridge.download_asset(a,tmp_path)==dest
    bad=bridge.ReleaseAsset(0,"bad.bin",1,"sha256:aa")
    with pytest.raises(bridge.DatasetBridgeError, match="Identifiant GitHub invalide"):
        bridge.download_asset(bad,tmp_path)

    dest.write_bytes(b"bad")
    monkeypatch.setattr(bridge, "_gh_path", lambda: "gh")
    def good_run(command, stdout, stderr):
        stdout.write(data); return SimpleNamespace(returncode=0, stderr=b"")
    monkeypatch.setattr(bridge.subprocess, "run", good_run)
    assert bridge.download_asset(a,tmp_path,force=False).read_bytes()==data

    failing=_asset(name="fail.bin",data=b"x",asset_id=2)
    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=3, stderr=b"denied"))
    with pytest.raises(bridge.DatasetBridgeError, match="denied"):
        bridge.download_asset(failing,tmp_path)
    assert not (tmp_path/"fail.bin.part").exists()


def test_ensure_metadata_required_optional(tmp_path, monkeypatch) -> None:
    release={"name":"R"}
    names=list(bridge.CORE_METADATA_ASSETS)+list(bridge.OPTIONAL_METADATA_ASSETS)
    assets={name:bridge.ReleaseAsset(i+1,name,0,"sha256:"+hashlib.sha256(b"").hexdigest()) for i,name in enumerate(names)}
    monkeypatch.setattr(bridge,"load_release",lambda *a,**k:release)
    monkeypatch.setattr(bridge,"release_assets",lambda r:assets)
    downloaded=[]
    monkeypatch.setattr(bridge,"download_asset",lambda a,destination_dir,**k:(downloaded.append(a.name) or destination_dir/a.name))
    r,a,d=bridge.ensure_metadata(tmp_path,repository="o/r",release_id=1,force=True)
    assert r is release and a is assets and d.is_dir() and downloaded==names
    monkeypatch.setattr(bridge,"release_assets",lambda r:{})
    with pytest.raises(bridge.DatasetBridgeError, match="fichiers de contrôle"):
        bridge.ensure_metadata(tmp_path)


def test_manifest_iteration_select_and_assets(tmp_path) -> None:
    manifest=tmp_path/"m.jsonl.gz"
    lines=["", json.dumps([1,2]), json.dumps({"relative_path":"a.json","size":1,"storage":"zip_entry","asset":"z.zip"}), json.dumps({"relative_path":"b.csv","size":2,"storage":"raw_chunks","chunks":[{"asset":"p1"},{"asset":"p2"}]})]
    with gzip.open(manifest,"wt",encoding="utf-8") as f:
        f.write("\n".join(lines))
    records=list(bridge.iter_manifest_records(manifest))
    assert [r.relative_path for r in records]==["a.json","b.csv"]
    assert [r.relative_path for r in bridge.select_records(records,contains=["a."],suffixes=["json"])]==["a.json"]
    assert len(bridge.select_records(records,limit=1))==1
    assert bridge.assets_for_records(records)==("p1","p2","z.zip")
    with gzip.open(manifest,"wt",encoding="utf-8") as f:f.write("bad\n")
    with pytest.raises(bridge.DatasetBridgeError, match="ligne 1"):
        list(bridge.iter_manifest_records(manifest))


def test_download_needed_assets_and_safe_destination(tmp_path, monkeypatch) -> None:
    assets={"a":_asset(name="a",data=b"x")}
    monkeypatch.setattr(bridge,"download_asset",lambda asset,dest,**k:dest/asset.name)
    result=bridge.download_needed_assets(tmp_path,assets,["a"])
    assert result["a"].name=="a"
    with pytest.raises(bridge.DatasetBridgeError, match="absent de la Release"):
        bridge.download_needed_assets(tmp_path,assets,["missing"])
    safe=bridge._safe_destination(tmp_path,"sub/x")
    assert safe==tmp_path.resolve()/"sub/x"
    with pytest.raises(bridge.DatasetBridgeError, match="Chemin dangereux"):
        bridge._safe_destination(tmp_path,"../escape")


def test_materialize_zip_and_raw_and_failures(tmp_path) -> None:
    out=tmp_path/"out"
    zip_path=tmp_path/"z.zip"
    zip_data=b"hello"
    with zipfile.ZipFile(zip_path,"w") as z:z.writestr("nested/a.txt",zip_data)
    rzip=bridge.DatasetRecord("nested/a.txt",len(zip_data),hashlib.sha256(zip_data).hexdigest(),"zip_entry","z.zip")
    created=bridge.materialize_records([rzip],{"z.zip":zip_path},out)
    assert created[0].read_bytes()==zip_data

    p1=tmp_path/"p1"; p2=tmp_path/"p2"; p1.write_bytes(b"ab"); p2.write_bytes(b"cd")
    raw_data=b"abcd"
    rraw=bridge.DatasetRecord("raw.bin",4,hashlib.sha256(raw_data).hexdigest(),"raw_chunks",chunks=({"asset":"p2","part":2},{"asset":"p1","part":1}))
    assert bridge.materialize_records([rraw],{"p1":p1,"p2":p2},out)[0].read_bytes()==raw_data

    with pytest.raises(bridge.DatasetBridgeError, match="Stockage inconnu"):
        bridge.materialize_records([bridge.DatasetRecord("x",0,"","bad")],{},out)
    with pytest.raises(bridge.DatasetBridgeError, match="Archive non téléchargée"):
        bridge.materialize_records([rzip],{},out)
    missing=bridge.DatasetRecord("missing.txt",1,"","zip_entry","z.zip")
    with pytest.raises(bridge.DatasetBridgeError, match="absent de z.zip"):
        bridge.materialize_records([missing],{"z.zip":zip_path},out)
    no_chunks=bridge.DatasetRecord("x",0,"","raw_chunks",chunks=())
    with pytest.raises(bridge.DatasetBridgeError, match="Aucun morceau"):
        bridge.materialize_records([no_chunks],{},out)
    missing_chunk=bridge.DatasetRecord("x",1,"","raw_chunks",chunks=({"asset":"m","part":1},))
    with pytest.raises(bridge.DatasetBridgeError, match="Morceau non téléchargé"):
        bridge.materialize_records([missing_chunk],{},out)


def test_verify_reconstructed_and_build_status(tmp_path, monkeypatch) -> None:
    p=tmp_path/"x"; p.write_bytes(b"abc")
    rec=bridge.DatasetRecord("x",3,hashlib.sha256(b"abc").hexdigest(),"raw_chunks")
    bridge._verify_reconstructed(p,rec)
    with pytest.raises(bridge.DatasetBridgeError, match="Taille reconstruite"):
        bridge._verify_reconstructed(p,bridge.DatasetRecord("x",2,"","raw_chunks"))
    with pytest.raises(bridge.DatasetBridgeError, match="SHA-256 reconstruit"):
        bridge._verify_reconstructed(p,bridge.DatasetRecord("x",3,"0"*64,"raw_chunks"))
    monkeypatch.setattr(bridge,"load_release",lambda *a,**k:{"name":"R","tag_name":"v1","draft":1,"published_at":"now","assets":[]})
    monkeypatch.setattr(bridge,"release_assets",lambda r:{"a":bridge.ReleaseAsset(1,"a",10,"sha256:ff")})
    row=bridge.build_status(tmp_path,repository="o/r",release_id=7)
    assert row["repository"]=="o/r" and row["release_id"]==7 and row["asset_count"]==1 and row["asset_bytes"]==10
    assert row["draft"] is True and row["release_name"]=="R"
