"""ALPHA P62/P63 — hard negatives (skip retest) + backlog scorer (prochaine task auto)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import research_backlog as R  # noqa: E402


def test_hard_negatives_skip_sauf_nouveaute():
    hn = R.HardNegatives()
    hn.ajouter("btc_leadlag_taker", raison="KILL", dataset_hash="d1", hypothese="lag+cost")
    assert hn.doit_retester("btc_leadlag_taker", dataset_hash="d1", hypothese="lag+cost") is False   # deja mort
    assert hn.doit_retester("btc_leadlag_taker", dataset_hash="d2") is True     # nouvelle donnee
    assert hn.doit_retester("btc_leadlag_taker", hypothese="maker") is True     # nouvelle hypothese
    assert hn.doit_retester("zone_inconnue") is True


def test_score_idee():
    fort = R.score_idee(impact=5, data_readiness=1.0, independence=1.0, cost=1.0)
    faible = R.score_idee(impact=5, data_readiness=0.1, independence=1.0, cost=5.0)
    assert fort > faible


def test_prochaine_task_par_score_puis_prio():
    tasks = [
        {"id": "A", "statut": "DONE", "prio_eco": 1},
        {"id": "B", "statut": "TODO", "prio_eco": 5, "score": 10.0},
        {"id": "C", "statut": "TODO", "prio_eco": 2, "score": 50.0},
        {"id": "D", "statut": "BLOCKED_EXTERNAL", "prio_eco": 0},
    ]
    assert R.prochaine_task(tasks)["id"] == "C"              # meilleur score parmi TODO
    # sans score -> plus petite prio_eco
    t2 = [{"id": "X", "statut": "TODO", "prio_eco": 7}, {"id": "Y", "statut": "TODO", "prio_eco": 3}]
    assert R.prochaine_task(t2)["id"] == "Y"
