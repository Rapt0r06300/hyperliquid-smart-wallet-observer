"""[LANCEUR item 11] Stockage brut BORNÉ — quota + rétention explicite (archive, jamais de suppression
silencieuse) + backpressure. Opt-in par ENV. Prouvé sans réseau.
"""
from __future__ import annotations

from pathlib import Path

from hl_observer.collection import stockage_brut_borne as SB


def _event(n=0):
    return {"i": n, "blob": "x" * 400, "endpoint": "/info", "type": "l2Book"}


def test_depuis_env_desactive_par_defaut(tmp_path):
    assert SB.depuis_env(tmp_path, env={}) is None                       # défaut sûr : désactivé
    w = SB.depuis_env(tmp_path, env={"HYPERSMART_RAW_STORAGE_QUOTA_GO": "2"})
    assert isinstance(w, SB.EcrivainBrutBorne) and w.garde.quota_octets == 2 * 1024**3


def test_ecriture_sous_quota_ok(tmp_path):
    w = SB.EcrivainBrutBorne(tmp_path, quota_octets=5_000_000, rotate_bytes=2000)
    r = w.ecrire(_event(1), source_id="hl", channel="l2Book", instrument="BTC")
    assert r["ecrit"] is True and w.dossier.is_dir()
    assert w.etat()["usage"] > 0


def test_retention_archive_les_vieux_shards_sans_suppression_silencieuse(tmp_path):
    # quota petit + shards petits -> la rétention DOIT archiver les vieux shards pour tenir la borne
    w = SB.EcrivainBrutBorne(tmp_path, quota_octets=6_000, rotate_bytes=2000, ligne_basse=0.5)
    for i in range(60):
        w.ecrire(_event(i))
    archives = list(w.archive.glob("*.jsonl.gz")) if w.archive.exists() else []
    assert archives, "des shards doivent avoir ete ARCHIVES (deplaces, pas supprimes)"
    # la zone hot reste bornee (usage <= quota + une marge)
    assert SB.mesurer_usage([w.dossier]).octets <= 6_000 + 4_000


def test_abandon_logge_si_pas_de_place_meme_apres_retention(tmp_path):
    w = SB.EcrivainBrutBorne(tmp_path, quota_octets=100, rotate_bytes=2000)   # trop petit pour 1 event
    r = w.ecrire(_event(1))
    assert r["ecrit"] is False and r["raison"] == "QUOTA_PLEIN_APRES_RETENTION"   # jamais un drop muet
    assert w.abandons == 1


def test_capturer_si_active_hook_global(tmp_path, monkeypatch):
    SB.reinitialiser()
    monkeypatch.delenv("HYPERSMART_RAW_STORAGE_QUOTA_GO", raising=False)
    assert SB.capturer_si_active(source="hl", endpoint="/info", request_type="l2Book",
                                 request={}, response={"a": 1}, racine=tmp_path) is False   # désactivé
    SB.reinitialiser()
    monkeypatch.setenv("HYPERSMART_RAW_STORAGE_QUOTA_GO", "1")
    assert SB.capturer_si_active(source="hl", endpoint="/info", request_type="l2Book",
                                 request={}, response={"a": 1}, racine=tmp_path) is True    # capturé
    assert (Path(tmp_path) / "runtime" / "data" / "raw_bounded").is_dir()
    SB.reinitialiser()
