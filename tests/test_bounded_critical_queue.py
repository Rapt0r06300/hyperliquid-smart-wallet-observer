"""[pépite 272] bounded critical queue : file bornée, saturation → rejet mesuré, pas d'accumulation infinie."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.capture.bounded_critical_queue import FileBornee   # noqa: E402


def test_rejet_quand_pleine():
    f = FileBornee(2)
    assert f.enfiler("a")["ok"] is True and f.enfiler("b")["ok"] is True
    r = f.enfiler("c")
    assert r["rejete"] is True and f.occupation() == 2 and f.rejets() == 1


def test_taux_occupation_et_defiler():
    f = FileBornee(4)
    f.enfiler("a"); f.enfiler("b")
    assert f.taux_occupation() == 0.5 and f.defiler()["item"] == "a"


def test_capacite_invalide():
    try:
        FileBornee(0)
        assert False
    except ValueError:
        assert True
