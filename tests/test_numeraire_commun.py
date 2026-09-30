"""[ARB #5] numéraire commun : tout ramené à un quote canonique avant comparaison."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import numeraire_commun as NC   # noqa: E402


def test_conversion_et_passthrough():
    taux = {"USDT": 0.9995, "EUR": 1.08}
    assert NC.vers_numeraire(100.0, "USD", taux_vers_numeraire=taux) == 100.0        # déjà en numéraire
    assert NC.vers_numeraire(100.0, "USDT", taux_vers_numeraire=taux) == 99.95       # via taux exécutable
    assert NC.vers_numeraire(100.0, "XYZ", taux_vers_numeraire=taux) == "UNMEASURABLE"  # taux inconnu, jamais 1:1


def test_comparable_ramene_au_meme_numeraire():
    taux = {"USDT": 0.999, "USDC": 1.001}
    r = NC.comparable(100.0, "USDT", 100.0, "USDC", taux_vers_numeraire=taux)
    assert r["comparable"] is True and r["prix_a_num"] == 99.9 and r["prix_b_num"] == 100.1
    assert r["ecart_num"] == round(99.9 - 100.1, 10)
