"""[COPY-VAULT #73] leader price-quality attribution : distinguer l'alpha du leader de son exécution chanceuse."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.leader_price_quality_attribution import attribuer   # noqa: E402


def test_prix_exceptionnel_non_replicable():
    # achat rempli bien en dessous de la référence -> avantage d'exécution, non réplicable
    r = attribuer(99.0, 100.0, "ACHAT", seuil_bps=5.0)   # ~100 bps d'avantage
    assert r["replicable"] is False and r["verdict"] == "EDGE_EXECUTION_NON_REPLICABLE"


def test_prix_normal_replicable():
    r = attribuer(100.0, 100.0, "ACHAT", seuil_bps=5.0)
    assert r["replicable"] is True


def test_prix_manquant():
    assert attribuer(None, 100.0, "ACHAT")["avantage_execution_bps"] == "UNMEASURABLE"
