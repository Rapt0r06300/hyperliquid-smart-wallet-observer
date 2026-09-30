"""[ARB lot2 #4] batch-cancel : toutes les quotes d'un spread invalide annulées d'un coup."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.batch_cancel_invalid_spread import RegistreQuotes   # noqa: E402


def test_batch_cancel_du_spread():
    rq = RegistreQuotes()
    rq.enregistrer("spr1", "q1")
    rq.enregistrer("spr1", "q2")
    rq.enregistrer("spr2", "q3")
    r = rq.invalider_spread("spr1")
    assert r["batch"] is True and set(r["a_annuler"]) == {"q1", "q2"} and r["n"] == 2


def test_spread_retire_apres_invalidation():
    rq = RegistreQuotes()
    rq.enregistrer("spr1", "q1")
    rq.invalider_spread("spr1")
    assert rq.invalider_spread("spr1")["n"] == 0          # déjà vidé


def test_spread_inconnu():
    assert RegistreQuotes().invalider_spread("zzz")["a_annuler"] == []
