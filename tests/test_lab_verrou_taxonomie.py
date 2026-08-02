"""[items 13,21] Verrou d'analyse (deux ANALYSER n'ecrivent pas le meme rapport/shard) + taxonomie NETTE
du code de sortie (erreur technique -> non nul ; issue economique -> 0, verdict au rapport). 0 reseau.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import lab_alpha as LA          # noqa: E402


def test_verrou_analyse_bloque_un_second_lancement(tmp_path):
    sortie = tmp_path / "runtime" / "reports" / "backtest_replay" / "run-x"
    v = LA.acquerir_verrou_analyse(sortie, pid_vivant=lambda pid: True)
    assert v.is_file()
    # un second acquer avec le meme PID VIVANT -> bloque.
    with pytest.raises(LA.AnalyseVerrouilleeError):
        LA.acquerir_verrou_analyse(sortie, pid_vivant=lambda pid: True)


def test_verrou_perime_pid_mort_est_repris(tmp_path):
    sortie = tmp_path / "runtime" / "reports" / "backtest_replay" / "run-y"
    sortie.mkdir(parents=True)
    (sortie / ".analyse.lock").write_text(json.dumps({"pid": 999999}), encoding="utf-8")
    # PID mort -> le verrou est repris sans erreur.
    v = LA.acquerir_verrou_analyse(sortie, pid_vivant=lambda pid: False)
    assert v.is_file()


def test_taxonomie_erreur_technique_code_non_nul(tmp_path, monkeypatch):
    # une erreur TECHNIQUE dans lancer_lab -> code de sortie NON NUL (item 21).
    def _boom(**kw):
        raise RuntimeError("panne disque simulee")
    monkeypatch.setattr(LA, "lancer_lab", _boom)
    code = LA.main(["--root", str(tmp_path), "--budget", "1"])
    assert code == 1


def test_taxonomie_verrou_code_dedie(tmp_path, monkeypatch):
    def _lock(**kw):
        raise LA.AnalyseVerrouilleeError("deja en cours")
    monkeypatch.setattr(LA, "lancer_lab", _lock)
    assert LA.main(["--root", str(tmp_path)]) == 8


def test_taxonomie_issue_economique_code_zero(tmp_path, monkeypatch):
    # un run qui produit un rapport (verdict economique quelconque) -> code 0 (pas un echec technique).
    def _ok(**kw):
        return {"tableau": "T", "verdict": "NEGATIF", "rapport": {"latest": "r.md"}, "journal": "j.log",
                "duree_s": 0.1}
    monkeypatch.setattr(LA, "lancer_lab", _ok)
    assert LA.main(["--root", str(tmp_path)]) == 0


def test_verrou_analyse_est_atomique_o_excl(tmp_path, monkeypatch):
    # item 5 : le verrou utilise os.open(O_CREAT|O_EXCL), pas exists()+write_text.
    import inspect
    src = inspect.getsource(LA.acquerir_verrou_analyse)
    assert "O_EXCL" in src and "os.open" in src.replace("_os.open", "os.open")
    # comportement : 1er acquiert, 2e (PID vivant) bloque, verrou perime (PID mort) repris.
    sortie = tmp_path / "runtime" / "reports" / "backtest_replay" / "run-atom"
    LA.acquerir_verrou_analyse(sortie, pid_vivant=lambda pid: True)
    with pytest.raises(LA.AnalyseVerrouilleeError):
        LA.acquerir_verrou_analyse(sortie, pid_vivant=lambda pid: True)
    v = LA.acquerir_verrou_analyse(sortie, pid_vivant=lambda pid: False)   # PID mort -> repris
    assert v.is_file()
