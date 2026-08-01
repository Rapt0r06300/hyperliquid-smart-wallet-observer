"""[COPY-VAULT #57] maximum concurrent positions : plafond propre au copy-vault."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.max_concurrent_positions import LimiteurPositions   # noqa: E402


def test_plafond():
    lim = LimiteurPositions(max_positions=2)
    assert lim.ouvrir("BTC") is True
    assert lim.ouvrir("ETH") is True
    assert lim.peut_ouvrir("SOL")["ok"] is False          # plafond atteint
    assert lim.peut_ouvrir("SOL")["raison"] == "PLAFOND_POSITIONS_ATTEINT"


def test_coin_deja_ouvert_ne_compte_pas():
    lim = LimiteurPositions(max_positions=1)
    lim.ouvrir("BTC")
    assert lim.peut_ouvrir("BTC")["ok"] is True           # déjà ouvert, pas une nouvelle position


def test_fermer_libere_une_place():
    lim = LimiteurPositions(max_positions=1)
    lim.ouvrir("BTC")
    lim.fermer("BTC")
    assert lim.peut_ouvrir("ETH")["ok"] is True
