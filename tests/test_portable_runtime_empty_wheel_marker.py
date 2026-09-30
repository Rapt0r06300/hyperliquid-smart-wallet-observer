from __future__ import annotations

from pathlib import Path

from hl_observer.ops import inventaire_release as IR


def _neutraliser_autres_gates(monkeypatch, requis: set[str]) -> None:
    monkeypatch.setattr(IR, "fichiers_requis", lambda _root: set(requis))
    monkeypatch.setattr(IR, "cloture_imports", lambda _root: {"requis": set(), "casses": []})
    monkeypatch.setattr(IR, "references_cmd", lambda _root: {"requis": set(), "manquants": []})
    monkeypatch.setattr(
        IR,
        "references_dynamiques",
        lambda _root: {"requis": set(), "manquants": []},
    )


def test_marqueur_wheel_vide_du_runtime_installe_est_tolere(tmp_path: Path, monkeypatch) -> None:
    rel = "tools/python/Lib/site-packages/scipy-1.18.0-cp314-cp314-win_amd64.whl"
    marker = tmp_path / rel
    marker.parent.mkdir(parents=True)
    marker.write_bytes(b"")
    _neutraliser_autres_gates(monkeypatch, {rel})

    verdict = IR.controle_completude(tmp_path, {rel})

    assert verdict["complet"] is True
    assert verdict["vides"] == []


def test_wheel_source_vide_reste_bloquant(tmp_path: Path, monkeypatch) -> None:
    rel = "tools/wheelhouse/scipy-1.18.0-cp314-cp314-win_amd64.whl"
    wheel = tmp_path / rel
    wheel.parent.mkdir(parents=True)
    wheel.write_bytes(b"")
    _neutraliser_autres_gates(monkeypatch, {rel})

    verdict = IR.controle_completude(tmp_path, {rel})

    assert verdict["complet"] is False
    assert verdict["vides"] == [rel]
