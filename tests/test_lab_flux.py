"""[LAB α item 11/5] Ingestion en STREAMING à mémoire bornée : plus de plafond arbitraire 200k, spill
disque, checkpoint/reprise, fenêtre RAM bornée. 0 réseau.
"""
from __future__ import annotations

import json
import types
from pathlib import Path

from hl_observer.ops import lab_flux as F


def _fichier_events(tmp_path, n, nom="data.jsonl"):
    p = Path(tmp_path) / nom
    with p.open("w", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(json.dumps({"coin": "BTC", "ts_ms": 1000 + i, "signe": 1, "mid": 100.0 + i}) + "\n")
    return p


def test_flux_est_un_generateur_paresseux_et_borne(tmp_path):
    f = _fichier_events(tmp_path, 100)
    flux = F.flux_evenements_stream([f], max_events=5)
    assert isinstance(flux, types.GeneratorType)             # paresseux : ne matérialise rien
    evs = list(flux)
    assert len(evs) == 5                                     # max_events borne réellement (pas 100)


def test_max_events_zero_lit_tout(tmp_path):
    f = _fichier_events(tmp_path, 40)
    evs = list(F.flux_evenements_stream([f], max_events=0))
    assert len(evs) == 40                                    # 0 = pas de plafond arbitraire


def test_materialiser_shard_spill_disque_et_checkpoint(tmp_path):
    f = _fichier_events(tmp_path, 30)
    shard = tmp_path / "shard.jsonl"
    cp = tmp_path / "cp.json"
    info = F.materialiser_shard([f], shard, checkpoint_path=cp)
    assert info["n"] == 30 and info["repris"] is False and shard.is_file()
    assert F.compter_shard(shard) == 30
    assert json.loads(cp.read_text())["complet"] is True


def test_reprise_ne_recalcule_pas_un_shard_complet(tmp_path):
    f = _fichier_events(tmp_path, 20)
    shard = tmp_path / "shard.jsonl"
    cp = tmp_path / "cp.json"
    F.materialiser_shard([f], shard, checkpoint_path=cp)
    mtime1 = shard.stat().st_mtime_ns
    info2 = F.materialiser_shard([f], shard, checkpoint_path=cp)      # 2e passe : reprise
    assert info2["repris"] is True and info2["n"] == 20
    assert shard.stat().st_mtime_ns == mtime1                        # le shard n'a PAS été réécrit


def test_charger_borne_fenetre_memoire(tmp_path):
    f = _fichier_events(tmp_path, 50)
    shard = tmp_path / "shard.jsonl"
    F.materialiser_shard([f], shard)
    assert len(F.charger_borne(shard, max_ram=10)) == 10             # fenêtre RAM bornée explicite
    assert len(F.charger_borne(shard, max_ram=0)) == 50              # 0 = tout


def test_plusieurs_fichiers_streames_ensemble(tmp_path):
    f1 = _fichier_events(tmp_path, 12, "a.jsonl")
    f2 = _fichier_events(tmp_path, 8, "b.jsonl")
    assert sum(1 for _ in F.flux_evenements_stream([f1, f2])) == 20
