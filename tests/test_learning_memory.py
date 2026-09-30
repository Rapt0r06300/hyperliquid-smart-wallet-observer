from hl_observer.experimental.learning_memory import (
    deja_teste, enregistrer_apprentissage, lire_memoire)


def test_memoire_persiste_entre_runs(tmp_path):
    enregistrer_apprentissage(tmp_path, cle="cfg_A", outcome={"net": -1.0, "verdict": "KILL"})
    mem = lire_memoire(tmp_path)
    assert mem["cfg_A"]["verdict"] == "KILL"
    assert deja_teste(tmp_path, "cfg_A") is True
    assert deja_teste(tmp_path, "cfg_inconnu") is False


def test_le_plus_recent_gagne(tmp_path):
    enregistrer_apprentissage(tmp_path, cle="cfg", outcome={"v": 1})
    enregistrer_apprentissage(tmp_path, cle="cfg", outcome={"v": 2})
    assert lire_memoire(tmp_path)["cfg"]["v"] == 2


def test_memoire_vide(tmp_path):
    assert lire_memoire(tmp_path) == {}
