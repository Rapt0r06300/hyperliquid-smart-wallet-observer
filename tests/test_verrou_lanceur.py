"""[LANCEUR item 11] Verrou d'instance du lanceur (réutilise le verrou canonique collection.verrou_instance
avec un TTL de warmup). Deux double-clics simultanes ne lancent jamais deux recoltes. 0 reseau.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import verrou_lanceur as VL        # noqa: E402

CMD = (RACINE / "LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="ignore")


def test_premier_acquiert_second_bloque_pendant_le_warmup(tmp_path, monkeypatch):
    ok1, info1 = VL.acquerir_lanceur(tmp_path, now_ms=1000)
    assert ok1 is True and info1.get("run_id")
    # 2e double-clic (autre PID), verrou FRAIS (dans la fenetre de warmup) -> refuse.
    from hl_observer.collection import verrou_instance as VI
    monkeypatch.setattr(VI.os, "getpid", lambda: info1["pid"] + 1)
    ok2, info2 = VL.acquerir_lanceur(tmp_path, now_ms=1000 + 60_000)     # +60 s, TTL warmup 600 s
    assert ok2 is False and info2["raison"] == "INSTANCE_DEJA_ACTIVE"


def test_verrou_perime_apres_ttl_warmup(tmp_path, monkeypatch):
    ok1, info1 = VL.acquerir_lanceur(tmp_path, now_ms=1000)
    assert ok1
    from hl_observer.collection import verrou_instance as VI
    monkeypatch.setattr(VI.os, "getpid", lambda: info1["pid"] + 1)
    # bien au-dela du TTL de warmup -> repris (le controle de port cote .cmd couvre un run long).
    ok2, _ = VL.acquerir_lanceur(tmp_path, now_ms=1000 + VL.TTL_WARMUP_MS + 1)
    assert ok2 is True


def test_liberer_puis_reacquerir(tmp_path):
    ok1, info = VL.acquerir_lanceur(tmp_path, now_ms=1000)
    assert ok1
    VL.liberer_lanceur(tmp_path, info)
    ok2, _ = VL.acquerir_lanceur(tmp_path, now_ms=1100)                  # libere -> ré-acquerable
    assert ok2 is True


def test_cli(tmp_path, capsys):
    assert VL.main(["acquerir", str(tmp_path)]) == 0
    assert "VERROU_LANCEUR_ACQUIS" in capsys.readouterr().out
    assert VL.main(["liberer", str(tmp_path)]) == 0


def test_le_cmd_pose_le_verrou_avant_les_collecteurs_et_le_libere():
    i_verrou = CMD.index("verrou_lanceur acquerir")
    i_collecteurs = CMD.index("demarrer-tous harvest", i_verrou)
    assert i_verrou < i_collecteurs                      # verrou AVANT tout writer (couvre le warmup)
    assert "verrou_lanceur liberer" in CMD              # libere a l'arret
