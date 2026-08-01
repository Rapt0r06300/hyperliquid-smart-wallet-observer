"""[COPY-VAULT lot2 #59] position-state hash : hash déterministe, détecte la divergence de replay."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.position_state_hash import hash_positions, concordent   # noqa: E402


def test_hash_deterministe_ordre_indifferent():
    a = hash_positions({"BTC": 0.5, "ETH": -2.0})
    b = hash_positions({"ETH": -2.0, "btc": 0.5})        # ordre + casse différents
    assert a == b


def test_divergence_detectee():
    a = hash_positions({"BTC": 0.5})
    b = hash_positions({"BTC": 0.6})
    assert a != b and concordent(a, b)["concordent"] is False


def test_hash_absent_failclosed():
    assert concordent(None, "x")["concordent"] is False
