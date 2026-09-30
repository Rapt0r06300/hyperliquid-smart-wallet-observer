"""[COPY-VAULT #63] order-level fill aggregation : les partial fills d'un même oid forment un seul ordre."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.order_level_fill_aggregation import AgregateurOrdres   # noqa: E402


def test_agregation_vwap():
    ag = AgregateurOrdres()
    ag.ajouter_fill("oid1", 1.0, 100.0)
    ag.ajouter_fill("oid1", 3.0, 104.0)                   # même ordre
    o = ag.ordre("oid1")
    assert o["qte"] == 4.0 and o["vwap"] == 103.0         # (100+312)/4
    assert ag.nombre_ordres() == 1                        # un seul ordre malgré 2 partials


def test_oids_distincts():
    ag = AgregateurOrdres()
    ag.ajouter_fill("oid1", 1.0, 100.0)
    ag.ajouter_fill("oid2", 1.0, 200.0)
    assert ag.nombre_ordres() == 2


def test_fill_invalide_ignore():
    ag = AgregateurOrdres()
    assert ag.ajouter_fill("oid1", 0.0, 100.0)["ok"] is False
    assert ag.ordre("oid1")["qte"] is None
