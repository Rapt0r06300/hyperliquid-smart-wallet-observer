"""Écran de suivi coffre : rendu pur de l'avancement/ETA (lecture seule)."""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

_MOD = Path(__file__).resolve().parents[1] / "tools" / "suivi_coffre.py"
_spec = importlib.util.spec_from_file_location("suivi_coffre", _MOD)
sc = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(sc)


def test_barre():
    assert sc.barre(0, 10) == "[----------]"
    assert sc.barre(50, 10) == "[#####-----]"
    assert sc.barre(100, 10) == "[##########]"
    # bornage : valeurs hors [0,100]
    assert sc.barre(-5, 10) == "[----------]"
    assert sc.barre(999, 10) == "[##########]"


def test_fmt_duree():
    assert sc._fmt_duree(0) == "0s"
    assert sc._fmt_duree(90) == "1m30s"
    assert sc._fmt_duree(3660) == "1h01m"


def test_rendu_en_cours():
    now = time.time() * 1000
    st = {
        "stage": "CERTIFICATION", "pct": 42.0, "i": 12, "n": 50,
        "fichier": "vault_fills.jsonl", "octets_faits": 5_000_000,
        "octets_total": 12_000_000, "debit_mo_s": 3.2, "eta_s": 140,
        "termine": False, "updated_ms": now,
    }
    out = "\n".join(sc.rendre(st, maintenant_ms=now))
    assert "EN COURS" in out
    assert "42.0%" in out
    assert "12/50" in out
    assert "reste ~2m20s" in out
    assert "vault_fills.jsonl" in out


def test_rendu_inactif_si_perime():
    now = time.time() * 1000
    st = {"stage": "CERTIFICATION", "pct": 10.0, "termine": False,
          "updated_ms": now - (sc.PERIME_S + 30) * 1000}
    out = "\n".join(sc.rendre(st, maintenant_ms=now))
    assert "INACTIF" in out


def test_rendu_termine_avec_bilan():
    now = time.time() * 1000
    st = {"stage": "TERMINE", "pct": 100.0, "termine": True, "code": 0,
          "resume": {"deposes": 1234, "quarantaine": 5, "doublons": 2},
          "updated_ms": now}
    out = "\n".join(sc.rendre(st, maintenant_ms=now))
    assert "TERMINE" in out
    assert "1234" in out


def test_rendu_sans_statut():
    out = "\n".join(sc.rendre(None, maintenant_ms=time.time() * 1000))
    assert "En attente" in out
