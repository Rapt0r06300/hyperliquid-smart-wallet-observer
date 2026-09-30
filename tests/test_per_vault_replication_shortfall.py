"""[COPY-VAULT #74] per-vault replication shortfall : leader_return - notre_return_apres_couts."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.per_vault_replication_shortfall import shortfall   # noqa: E402


def test_shortfall_positif():
    r = shortfall(50.0, 35.0)                             # on capte 15 bps de moins
    assert r["shortfall_bps"] == 15.0 and r["capte_moins"] is True


def test_shortfall_negatif_on_fait_mieux():
    r = shortfall(30.0, 32.0)
    assert r["shortfall_bps"] == -2.0 and r["capte_moins"] is False


def test_manquant_non_mesurable():
    assert shortfall(50.0, None)["shortfall_bps"] == "UNMEASURABLE"
