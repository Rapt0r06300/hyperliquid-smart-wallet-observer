"""[CROSS-VENUE #10] fee-token normalization : commissions en autre token ramenées au numéraire du PnL."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import fee_token_normalization as FT   # noqa: E402


def test_frais_en_bnb_converti():
    taux = {"BNB": 600.0}
    assert FT.frais_vers_numeraire(0.01, "BNB", taux_vers_numeraire=taux) == 6.0        # 0.01 BNB = $6
    assert FT.frais_vers_numeraire(0.01, "XYZ", taux_vers_numeraire=taux) == "UNMEASURABLE"  # jamais 'gratuit'


def test_total_incomplet_si_token_inconnu():
    taux = {"BNB": 600.0}
    ok = FT.frais_total_numeraire([{"montant": 5.0, "token": "USD"}, {"montant": 0.01, "token": "BNB"}],
                                  taux_vers_numeraire=taux)
    assert ok["total_numeraire"] == 11.0 and ok["incomplet"] is False
    ko = FT.frais_total_numeraire([{"montant": 5.0, "token": "USD"}, {"montant": 1.0, "token": "HYPE"}],
                                  taux_vers_numeraire=taux)
    assert ko["total_numeraire"] == "UNMEASURABLE" and ko["incomplet"] is True         # coût jamais sous-estimé
