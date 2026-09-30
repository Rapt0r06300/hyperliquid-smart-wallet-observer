"""[COPY-VAULT lot2 #47] queue-cap par vault : un vault hyperactif ne fait pas patienter les autres."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.per_vault_queue_cap import LimiteurQueueVault   # noqa: E402


def test_plafond_par_vault():
    lim = LimiteurQueueVault(cap_par_vault=2)
    assert lim.ajouter("vaultA") is True
    assert lim.ajouter("vaultA") is True
    assert lim.peut_ajouter("vaultA")["ok"] is False and lim.peut_ajouter("vaultA")["raison"] == "QUEUE_VAULT_PLEINE"


def test_vaults_independants():
    lim = LimiteurQueueVault(cap_par_vault=1)
    lim.ajouter("vaultA")
    assert lim.ajouter("vaultB") is True                 # autre vault non bloqué


def test_retrait_libere():
    lim = LimiteurQueueVault(cap_par_vault=1)
    lim.ajouter("vaultA")
    lim.retirer("vaultA")
    assert lim.peut_ajouter("vaultA")["ok"] is True
