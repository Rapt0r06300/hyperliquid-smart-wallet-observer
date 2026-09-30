"""[ARB #20] liquidity ownership : réserver pour un owner réduit immédiatement le dispo des AUTRES."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.liquidity_ownership import ProprieteLiquidite   # noqa: E402


def test_reserve_dun_owner_reduit_les_autres():
    pl = ProprieteLiquidite()
    pl.reserver("simA", "HL", "ETH", 3000.0, 4000.0, affiche_usd=5000.0)
    # simA voit encore sa propre part ; simB ne voit que 1000 restants
    assert pl.disponible_pour("simB", "HL", "ETH", 3000.0, affiche_usd=5000.0) == 1000.0
    assert pl.disponible_pour("simA", "HL", "ETH", 3000.0, affiche_usd=5000.0) == 5000.0


def test_liberation_rend_aux_autres():
    pl = ProprieteLiquidite()
    pl.reserver("simA", "HL", "ETH", 3000.0, 4000.0, affiche_usd=5000.0)
    assert pl.liberer("simA") is True
    assert pl.disponible_pour("simB", "HL", "ETH", 3000.0, affiche_usd=5000.0) == 5000.0


def test_seconde_reserve_bornee_par_les_autres():
    pl = ProprieteLiquidite()
    pl.reserver("simA", "HL", "ETH", 3000.0, 4000.0, affiche_usd=5000.0)
    r = pl.reserver("simB", "HL", "ETH", 3000.0, 3000.0, affiche_usd=5000.0)
    assert r["pris_usd"] == 1000.0 and r["refuse_usd"] == 2000.0
