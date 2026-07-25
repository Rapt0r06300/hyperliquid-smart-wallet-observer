"""RESET PAPER VOLONTAIRE (Fix 1) — sans --confirm ne touche à RIEN ; avec --confirm sauvegarde AVANT.

Prouve : (1) refus sans --confirm (code 2, aucun reset) ; (2) sauvegarde horodatée créée avec MANIFEST +
copie de l'état paper ; (3) avec --confirm : la sauvegarde précède le reset (ordre non négociable).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("reset_paper", _ROOT / "tools" / "reset_paper.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def test_refuse_sans_confirm(capsys):
    appels = []
    # monkeypatch reset pour prouver qu'il n'est JAMAIS appelé sans --confirm
    orig = M.reset
    M.reset = lambda **k: appels.append("reset") or 0
    try:
        code = M.main([])
    finally:
        M.reset = orig
    assert code == 2 and appels == [], "sans --confirm : aucun reset, code 2"
    assert "REFUS" in capsys.readouterr().out


def test_sauvegarde_horodatee_copie_l_etat(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "carry_paper_ledger.jsonl").write_text('{"kind":"CLOSE"}', encoding="utf-8")
    (data / "experimental_paper_V2_positions.json").write_text("{}", encoding="utf-8")
    dst = M.sauvegarder(tmp_path, ts="20260725-000000")
    assert dst.name == "reset_20260725-000000"
    assert (dst / "carry_paper_ledger.jsonl").exists()
    assert (dst / "experimental_paper_V2_positions.json").exists()
    assert "AVANT remise a zero" in (dst / "MANIFEST.txt").read_text(encoding="utf-8")


def test_confirm_sauvegarde_AVANT_reset(tmp_path, monkeypatch):
    """L'ordre est non négociable : sauvegarde PUIS reset."""
    ordre = []
    monkeypatch.setattr(M, "sauvegarder", lambda *a, **k: ordre.append("save") or (tmp_path / "bkp"))
    monkeypatch.setattr(M, "reset", lambda **k: ordre.append("reset") or 0)
    code = M.main(["--confirm"])
    assert code == 0 and ordre == ["save", "reset"], "la sauvegarde doit PRECEDER le reset"
