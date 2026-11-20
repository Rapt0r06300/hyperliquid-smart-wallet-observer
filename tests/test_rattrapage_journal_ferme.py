"""Le journal du rattrapage doit être fermé, même quand le processus ne démarre pas.

LE FAIT OBSERVÉ (20/11/2026), pendant un vrai passage du certificateur :

    tools/rattrapage_complet.py:466: ResourceWarning: unclosed file <_io.TextIOWrapper name=5>
      bilan = executer(commande, root=root, journal=journal, ...)

``executer`` ouvre le journal, PUIS lance le processus, et ne ferme le journal que dans le
``finally`` d'un ``try`` qui commence **après** ce lancement. Si la création du processus lève —
commande absente, ou machine saturée où Windows ne parvient plus à créer un processus — le
descripteur partait à la merci du ramasse-miettes.

POURQUOI ÇA COMPTE ICI. Sous Windows, un descripteur ouvert maintient un VERROU sur le fichier :
la tâche suivante du rattrapage ne peut alors plus écrire dans son journal. Et c'est précisément
sur une machine saturée — le cas où `Popen` échoue — qu'on a le plus besoin de ses traces.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))

import rattrapage_complet as R  # noqa: E402


def _espionner_les_ouvertures(monkeypatch) -> list:
    """Remplace ``Path.open`` par un mouchard qui retient chaque fichier ouvert."""
    ouverts: list = []
    vrai_open = Path.open

    def espion(self, *args, **kwargs):
        fichier = vrai_open(self, *args, **kwargs)
        ouverts.append(fichier)
        return fichier

    monkeypatch.setattr(Path, "open", espion)
    return ouverts


def test_le_journal_est_ferme_quand_Popen_leve(tmp_path: Path, monkeypatch) -> None:
    """LE test de la fuite : sans le correctif, le fichier reste ouvert."""
    ouverts = _espionner_les_ouvertures(monkeypatch)

    def popen_qui_echoue(*_args, **_kwargs):
        raise OSError(8, "Ressources insuffisantes pour creer le processus")

    monkeypatch.setattr(R.subprocess, "Popen", popen_qui_echoue)

    with pytest.raises(OSError):
        R.executer(["commande-inexistante"], root=tmp_path,
                   journal=tmp_path / "logs" / "rattrapage.log")

    assert ouverts, "le journal doit avoir ete ouvert, sinon ce test ne prouve rien"
    non_fermes = [f for f in ouverts if not f.closed]
    assert not non_fermes, f"descripteur(s) laisse(s) ouvert(s) : {non_fermes}"


def test_l_exception_est_PROPAGEE_jamais_avalee(tmp_path: Path, monkeypatch) -> None:
    """Fermer n'est pas taire : l'appelant doit toujours apprendre que rien n'a tourné.

    C'est la moitié qui compte. Un ``except`` qui fermerait le fichier puis rendrait un bilan
    « code 0 » transformerait « le processus n'a pas pu démarrer » en « la tâche a réussi ».
    """
    _espionner_les_ouvertures(monkeypatch)
    temoin = OSError(8, "temoin")

    def popen_qui_echoue(*_args, **_kwargs):
        raise temoin

    monkeypatch.setattr(R.subprocess, "Popen", popen_qui_echoue)
    with pytest.raises(OSError) as leve:
        R.executer(["x"], root=tmp_path, journal=tmp_path / "j.log")
    assert leve.value is temoin, "l'exception d'origine doit remonter telle quelle"


def test_sans_journal_un_echec_de_demarrage_ne_casse_rien(tmp_path: Path, monkeypatch) -> None:
    """``journal=None`` est le cas courant : la garde ne doit pas y lever un ``AttributeError``."""
    monkeypatch.setattr(R.subprocess, "Popen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError(8, "x")))
    with pytest.raises(OSError):
        R.executer(["x"], root=tmp_path, journal=None)
