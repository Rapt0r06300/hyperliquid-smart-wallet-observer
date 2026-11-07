"""Arrêt immédiat et sûr de la campagne de collecte (correctif gel Ctrl+C).

Sur Ctrl+C, le watchdog invalidait seulement le bail et attendait son expiration
(jusqu'à 120 s) — la fenêtre semblait gelée. Désormais il invalide le bail ET
tue immédiatement les workers, APRÈS vérification qu'ils sont bien des python
(jamais à l'aveugle : garde-fou anti-recyclage de PID par Windows).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import tools.watch_economic_collectors as wec


def _ecrire_etat(root: Path, pids: dict[str, int]) -> Path:
    (root / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    etat = root / wec.STATE_RELPATH
    etat.write_text(json.dumps({"pids": pids}), encoding="utf-8")
    bail = root / "runtime" / "data" / "economic_collection_lease.json"
    bail.write_text("{}", encoding="utf-8")
    return bail


def test_arret_immediat_tue_les_python_et_invalide_le_bail(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(wec, "_IS_WINDOWS", True)  # force le chemin taskkill/tasklist
    bail = _ecrire_etat(tmp_path, {"allmids": 111, "bbo": 222})

    appels: list[list[str]] = []

    def runner(cmd, **_kw):
        appels.append(list(cmd))
        if cmd[0] == "tasklist":
            # cmd[2] == "PID eq <pid>" ; 111 est python, 222 ne l'est pas.
            pid = cmd[2].split()[-1]
            image = "python.exe" if pid == "111" else "notepad.exe"
            return SimpleNamespace(stdout=f'"{image}","{pid}","Console"', returncode=0)
        return SimpleNamespace(stdout="", returncode=0)

    recu = wec.arreter_campagne_immediatement(tmp_path, runner=runner, verbose=False)

    assert recu["bail_supprime"] is True
    assert not bail.exists()
    assert recu["tues"] == [111]
    assert 222 in recu["ignores"]
    kills = [c for c in appels if c[0] == "taskkill"]
    assert any("111" in c for c in kills)
    assert not any("222" in c for c in kills)


def test_arret_sans_etat_ne_plante_pas(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(wec, "_IS_WINDOWS", True)
    recu = wec.arreter_campagne_immediatement(tmp_path, runner=lambda *a, **k: SimpleNamespace(stdout="", returncode=0), verbose=False)
    assert recu["tues"] == []
    assert recu["bail_supprime"] is False


def test_pids_campagne_lit_les_entiers(tmp_path: Path) -> None:
    _ecrire_etat(tmp_path, {"a": 5, "b": 7})
    assert wec._pids_campagne(tmp_path) == {"a": 5, "b": 7}
