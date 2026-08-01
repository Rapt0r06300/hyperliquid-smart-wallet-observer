"""[ARB #47] persistent unfinished episodes : après restart, reprendre l'arb incomplet depuis son état réel."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.persistent_unfinished_episodes import JournalEpisodes   # noqa: E402


def test_inacheves_listes():
    j = JournalEpisodes()
    j.enregistrer("ep1", etat="HEDGED")
    j.enregistrer("ep2", etat="RESIDUAL_UNHEDGED", coin="BTC", residu=0.4)
    inacheves = j.episodes_inacheves()
    assert len(inacheves) == 1 and inacheves[0]["episode_id"] == "ep2"


def test_reprendre_depuis_etat_reel():
    j = JournalEpisodes()
    j.enregistrer("ep2", etat="RESIDUAL_UNHEDGED", coin="BTC", residu=0.4)
    r = j.reprendre("ep2")
    assert r["reprenable"] is True and r["contexte"]["residu"] == 0.4


def test_termine_ou_inconnu_non_reprenable():
    j = JournalEpisodes()
    j.enregistrer("ep1", etat="HEDGED")
    assert j.reprendre("ep1")["reprenable"] is False
    assert j.reprendre("zzz")["reprenable"] is False                 # inconnu, jamais supposé terminé
