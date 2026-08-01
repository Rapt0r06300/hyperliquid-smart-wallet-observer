"""[COPY-VAULT #62] per-coin serialization : deux fills du même vault/coin ne modifient pas l'état en parallèle."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.per_coin_serialization import VerrouParCoin   # noqa: E402


def test_verrou_exclusif():
    v = VerrouParCoin()
    assert v.acquerir("vaultA", "BTC")["ok"] is True
    r = v.acquerir("vaultA", "BTC")                       # deuxième fill du même coin
    assert r["ok"] is False and r["raison"] == "COIN_DEJA_EN_TRAITEMENT"


def test_liberation():
    v = VerrouParCoin()
    v.acquerir("vaultA", "BTC")
    v.liberer("vaultA", "BTC")
    assert v.acquerir("vaultA", "BTC")["ok"] is True


def test_coins_independants():
    v = VerrouParCoin()
    v.acquerir("vaultA", "BTC")
    assert v.acquerir("vaultA", "ETH")["ok"] is True      # autre coin, verrou indépendant
