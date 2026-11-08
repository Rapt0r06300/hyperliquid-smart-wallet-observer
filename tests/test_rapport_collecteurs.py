"""Tests du rapport collecteurs (classification erreurs + détection d'améliorations)."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import rapport_collecteurs as R  # noqa: E402


def test_classification_grave_vs_signal():
    assert R.MOTIF_GRAVE.search("Traceback (most recent call last):")
    assert R.MOTIF_GRAVE.search("PermissionError: [WinError 5] Acces refuse")
    assert R.MOTIF_SIGNAL.search("[poll] erreur HTTP Error 429: Too Many Requests")
    assert R.MOTIF_SIGNAL.search("reconnexion WS")
    assert not R.MOTIF_GRAVE.search("tout va bien")
    # bruit ignore
    assert R.MOTIF_IGNORER.search("[GARDE DONNEES] Modifications locales protegees")


def test_genere_rapport_avec_ameliorations(tmp_path):
    logs = tmp_path / "runtime" / "logs"
    data = tmp_path / "runtime" / "data"
    logs.mkdir(parents=True)
    data.mkdir(parents=True)
    (logs / "poll-leaders.log").write_text(
        "[poll] 0xabc erreur HTTP Error 429: Too Many Requests\n"
        "[poll] 0xdef erreur HTTP Error 429: Too Many Requests\n", encoding="utf-8")
    (logs / "supervisor.log").write_text("Traceback (most recent call last):\nValueError: boom\n", encoding="utf-8")
    (data / "vault_fills_live.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    # un log de push doit etre IGNORE
    (logs / "pousser_x.log").write_text("[ECHEC] Comparer les fichiers | code=2\n", encoding="utf-8")

    cible = R.generer(tmp_path)
    txt = cible.read_text(encoding="utf-8")
    assert "AMELIORATIONS DETECTEES" in txt
    assert "Rate-limit REST" in txt            # 429 detecte -> amelioration
    assert "ERREURS GRAVES" in txt
    assert "ValueError" in txt                 # traceback capte
    assert "pousser_x.log" not in txt          # log de push exclu
    assert "vault_fills_live.jsonl" in txt     # flux liste


def test_rapport_vide_ne_plante_pas(tmp_path):
    (tmp_path / "runtime" / "logs").mkdir(parents=True)
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    cible = R.generer(tmp_path)
    assert cible.exists()
