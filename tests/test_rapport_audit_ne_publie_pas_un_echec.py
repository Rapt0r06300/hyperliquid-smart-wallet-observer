"""Un rapport d'audit qui echoue ne doit RIEN publier, ni laisser un fichier vide derriere lui.

LE DEFAUT (20/11/2026). ``tools/audit_report.py`` ecrivait ainsi :

    io.open(tmp, "w", encoding="utf-8").write(build_report())
    os.replace(tmp, REPORT)

Python evalue ``io.open(tmp, "w")`` AVANT l'argument : le temporaire etait donc **cree et
tronque avant** que ``build_report()`` soit appele. Un echec de construction laissait un
``.tmp`` de 0 octet derriere lui. Pire, le fichier n'etait ferme qu'APRES l'instruction, et une
exception levee a la FERMETURE (disque plein, quota) est **ignoree** par Python : le
``os.replace`` publiait alors un rapport TRONQUE comme s'il etait complet. Le temporaire +
remplacement atomique ne protegent pas de ca -- il faut un ``with``.

CE QUE CE TEST TIENT. L'ancien rapport survit a un echec, et aucun residu n'est laisse. Le
second test verifie la moitie qui compte : le chemin normal publie bien.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "audit_report_sous_test", RACINE / "tools" / "audit_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _echoue():
    raise RuntimeError("construction du rapport impossible")


def test_un_rapport_qui_echoue_ne_detruit_pas_le_precedent(tmp_path, monkeypatch, capsys):
    module = _module()
    cible = tmp_path / "resultat-audit.md"
    cible.write_text("RAPPORT PRECEDENT, A CONSERVER", encoding="utf-8")
    monkeypatch.setattr(module, "REPORT", cible)
    monkeypatch.setattr(module, "build_report", _echoue)

    module.write_report()

    assert cible.read_text(encoding="utf-8") == "RAPPORT PRECEDENT, A CONSERVER", (
        "le rapport precedent a ete detruit par un echec de construction")
    residus = sorted(p.name for p in tmp_path.glob("*.tmp"))
    assert residus == [], (
        f"residu(s) laisse(s) par l'echec : {residus} -- le temporaire etait cree AVANT "
        "l'evaluation du contenu")
    assert "impossible d'ecrire le rapport" in capsys.readouterr().out, (
        "l'echec doit etre DIT, jamais avale en silence")


def test_le_chemin_normal_publie_bien(tmp_path, monkeypatch):
    """La moitie qui compte : sans ceci, un write_report qui n'ecrit JAMAIS passerait."""
    module = _module()
    cible = tmp_path / "resultat-audit.md"
    monkeypatch.setattr(module, "REPORT", cible)
    monkeypatch.setattr(module, "build_report", lambda: "# Audit\n\nTout va bien.\n")

    module.write_report()

    assert cible.read_text(encoding="utf-8") == "# Audit\n\nTout va bien.\n"
    assert sorted(p.name for p in tmp_path.glob("*.tmp")) == [], "temporaire non nettoye"
