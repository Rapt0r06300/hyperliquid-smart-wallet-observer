"""[ARB #29] episode idempotency : une empreinte ne peut donner qu'UN seul épisode économique."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.episode_idempotency import EpisodesIdempotents   # noqa: E402


def test_meme_empreinte_meme_episode():
    reg = EpisodesIdempotents()
    a = reg.obtenir_ou_creer("emp-abc")
    b = reg.obtenir_ou_creer("emp-abc")
    assert a["episode_id"] == b["episode_id"]
    assert a["nouveau"] is True and b["nouveau"] is False        # le 2e n'est pas un doublon


def test_empreintes_differentes_episodes_differents():
    reg = EpisodesIdempotents()
    a = reg.obtenir_ou_creer("emp-1")
    b = reg.obtenir_ou_creer("emp-2")
    assert a["episode_id"] != b["episode_id"]


def test_existe():
    reg = EpisodesIdempotents()
    assert reg.existe("emp-x") is False
    reg.obtenir_ou_creer("emp-x")
    assert reg.existe("emp-x") is True
