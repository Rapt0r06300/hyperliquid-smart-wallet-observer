"""Les journaux de la recherche parallele doivent etre fermes, meme si un lancement echoue.

LE FAIT. ``remplir_en_parallele`` ouvre un journal par module, le confie a ``Popen``, et retient
le descripteur dans ``lances``. L'ouverture etait AVANT le lancement et hors de tout ``try`` :
si la creation d'un processus echoue -- commande absente, ou machine saturee ou Windows ne peut
plus creer de processus -- la fonction sort en levant, et **plus aucun** des journaux
precedemment ouverts n'est ferme. La fuite est donc MULTIPLIEE par la boucle.

POURQUOI CA COMPTE ICI. Sous Windows, un descripteur ouvert maintient un VERROU sur le fichier :
la passe suivante ne pourrait plus ecrire dans ces journaux. Et c'est precisement sur une machine
saturee -- le cas ou ``Popen`` echoue -- qu'on a le plus besoin de leurs traces.

C'est la MEME famille que ``tools/rattrapage_complet.py``, corrigee le meme jour : un descripteur
confie a un sous-processus, ouvert hors du ``try`` qui le fermera.
"""
from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from hl_observer.backtesting import recherche_parallele as RP


def _espionner_les_ouvertures(monkeypatch) -> list:
    """Mouchard sur ``open`` : retient chaque fichier ouvert par le module sous test."""
    ouverts: list = []
    vrai_open = builtins.open

    def espion(*args, **kwargs):
        fichier = vrai_open(*args, **kwargs)
        ouverts.append(fichier)
        return fichier

    monkeypatch.setattr(builtins, "open", espion)
    return ouverts


def test_aucun_journal_ne_reste_ouvert_quand_un_lancement_echoue(tmp_path, monkeypatch) -> None:
    appels = {"n": 0}

    def popen_qui_echoue_au_second(*_a, **_kw):
        appels["n"] += 1
        if appels["n"] >= 2:
            raise OSError("creation de processus impossible (machine saturee)")

        class _Faux:
            def wait(self, timeout=None):
                return 0

            def kill(self):
                return None
        return _Faux()

    monkeypatch.setattr(RP._sp, "Popen", popen_qui_echoue_au_second)
    ouverts = _espionner_les_ouvertures(monkeypatch)

    with pytest.raises(OSError):
        RP.remplir_en_parallele(tmp_path, 1.0, 1, ["module_a", "module_b"], {})

    restants = [getattr(f, "name", "?") for f in ouverts if not f.closed]
    assert appels["n"] == 2, (
        f"{appels['n']} lancement(s) : le scenario ne met plus la boucle a l'epreuve")
    assert restants == [], (
        f"journal(aux) laisse(s) ouvert(s) apres l'echec : {restants} -- sous Windows chacun "
        "maintient un verrou sur son fichier")


def test_les_journaux_sont_ouverts_en_ecriture(tmp_path, monkeypatch) -> None:
    """La moitie qui compte : sans ceci, un module qui n'ouvre RIEN passerait le test ci-dessus."""
    def popen_qui_echoue(*_a, **_kw):
        raise OSError("echec immediat")

    monkeypatch.setattr(RP._sp, "Popen", popen_qui_echoue)
    ouverts = _espionner_les_ouvertures(monkeypatch)
    with pytest.raises(OSError):
        RP.remplir_en_parallele(tmp_path, 1.0, 1, ["module_a"], {})
    assert ouverts, "aucun journal ouvert : le mouchard ne voit rien, donc il ne prouve rien"
