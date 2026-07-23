"""Verrou d'instance unique (rectif Flo 23/07) : une 2ᵉ copie refuse de démarrer tant qu'une instance
FRAÎCHE tient le verrou ; un verrou périmé (process mort) est repris. Aucun réseau."""
from __future__ import annotations

from hl_observer.collection import verrou_instance as VI


def test_acquisition_puis_refus_2e_instance(tmp_path, monkeypatch):
    ok, info = VI.acquerir(tmp_path, "userfills_live", now_ms=1000)
    assert ok and info["pid"] and info["run_id"]
    # une 2ᵉ copie (autre pid) est REFUSÉE tant que le verrou est frais
    monkeypatch.setattr(VI.os, "getpid", lambda: info["pid"] + 1)
    ok2, info2 = VI.acquerir(tmp_path, "userfills_live", now_ms=2000)
    assert ok2 is False and info2["raison"] == "INSTANCE_DEJA_ACTIVE"


def test_verrou_perime_est_repris(tmp_path, monkeypatch):
    ok, info = VI.acquerir(tmp_path, "userfills_live", now_ms=1000)
    assert ok
    monkeypatch.setattr(VI.os, "getpid", lambda: info["pid"] + 1)
    # bien après le TTL -> le verrou est périmé -> une nouvelle instance peut le reprendre
    ok2, info2 = VI.acquerir(tmp_path, "userfills_live", now_ms=1000 + VI.TTL_MS + 1)
    assert ok2 is True and info2["pid"] == info["pid"] + 1


def test_liberer(tmp_path):
    ok, info = VI.acquerir(tmp_path, "userfills_live", now_ms=1000)
    VI.liberer(tmp_path, "userfills_live", info)
    ok2, _ = VI.acquerir(tmp_path, "userfills_live", now_ms=1100)   # libéré -> ré-acquérable de suite
    assert ok2 is True
