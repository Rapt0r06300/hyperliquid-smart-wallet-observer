"""§4.5 — équity canonique : une seule courbe, pas de double comptage, pas de faux net.

Le test décisif est `test_le_spread_deja_dans_le_prix_nest_pas_deduit_deux_fois`.

Paper/read-only : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import equity_canonique as EQ  # noqa: E402


def test_equity_complete_somme_les_briques():
    e = EQ.EquityCanonique(capital_initial_usd=1_000.0, realized_pnl_usd=50.0,
                           unrealized_liquidatable_pnl_usd=20.0,
                           couts=[EQ.Cout("exchange_fee", 9.0)])
    r = e.liquidatable_equity()
    assert r["statut"] == "COMPLETE"
    assert r["liquidatable_equity_usd"] == 1_061.0          # 1000 + 50 + 20 - 9


def test_le_spread_deja_dans_le_prix_nest_pas_deduit_deux_fois():
    inclus = EQ.EquityCanonique(capital_initial_usd=1_000.0, unrealized_liquidatable_pnl_usd=0.0,
                                couts=[EQ.Cout("spread", 12.0, included_in_price=True)])
    exclu = EQ.EquityCanonique(capital_initial_usd=1_000.0, unrealized_liquidatable_pnl_usd=0.0,
                               couts=[EQ.Cout("spread", 12.0, included_in_price=False)])
    assert inclus.liquidatable_equity()["liquidatable_equity_usd"] == 1_000.0   # spread deja dans le prix
    assert exclu.liquidatable_equity()["liquidatable_equity_usd"] == 988.0      # spread hors prix : deduit
    detail = inclus.liquidatable_equity()["couts_detail"][0]
    assert detail["deduit_usd"] == 0.0 and detail["montant_usd"] == 12.0        # rapporte mais pas deduit


def test_un_cout_non_mesure_rend_lequity_partielle():
    e = EQ.EquityCanonique(capital_initial_usd=1_000.0, unrealized_liquidatable_pnl_usd=0.0,
                           couts=[EQ.Cout("exchange_fee", None)])
    r = e.liquidatable_equity()
    assert r["statut"] == "PARTIELLE" and "INCOMPLETE" in r["note_partielle"]


def test_une_position_non_liquidable_rend_lequity_partielle():
    e = EQ.EquityCanonique(capital_initial_usd=1_000.0, realized_pnl_usd=0.0,
                           unrealized_liquidatable_pnl_usd=None, unrealized_mid_pnl_usd=30.0)
    r = e.liquidatable_equity()
    assert r["statut"] == "PARTIELLE"
    assert r["unrealized_liquidatable_pnl_usd"] is None and r["unrealized_mid_pnl_usd"] == 30.0
    # le mid ne gonfle PAS l'equity liquidable
    assert r["liquidatable_equity_usd"] == 1_000.0


def test_le_mid_est_informatif_jamais_dans_lequity():
    e = EQ.EquityCanonique(capital_initial_usd=1_000.0, unrealized_liquidatable_pnl_usd=5.0,
                           unrealized_mid_pnl_usd=50.0)
    r = e.liquidatable_equity()
    assert r["liquidatable_equity_usd"] == 1_005.0          # le liquidable, pas le mid
    assert r["unrealized_mid_pnl_usd"] == 50.0              # publie a part


def test_les_grandeurs_de_capital_sont_publiees_separement():
    e = EQ.EquityCanonique(capital_initial_usd=1_000.0, unrealized_liquidatable_pnl_usd=0.0,
                           margin_locked_usd=200.0, gross_exposure_usd=2_000.0,
                           net_exposure_usd=0.0, peak_margin_usd=350.0, free_collateral_usd=650.0,
                           venue_exposure_usd={"HL": 1_500.0, "BINANCE": 500.0})
    r = e.liquidatable_equity()
    assert r["margin_locked_usd"] == 200.0 and r["peak_margin_usd"] == 350.0
    assert r["net_exposure_usd"] == 0.0 and r["venue_exposure_usd"]["BINANCE"] == 500.0


def test_depuis_ledger_marque_le_spread_inclus_et_somme_le_realized():
    lignes = [{"kind": "OPEN", "coin": "BTC"},
              {"kind": "CLOSE", "coin": "BTC", "realized_net_pnl_usdc": 12.0, "frais_usd": 0.5},
              {"kind": "CLOSE", "coin": "ETH", "realized_net_pnl_usdc": -4.0, "frais_usd": 0.5}]
    e = EQ.depuis_ledger_lignes(lignes, capital_initial_usd=1_000.0)
    r = e.liquidatable_equity()
    assert r["realized_pnl_usd"] == 8.0                     # 12 - 4
    noms = {c["nom"]: c for c in r["couts_detail"]}
    assert noms["spread"]["included_in_price"] is True and noms["spread"]["deduit_usd"] == 0.0
    assert noms["exchange_fee"]["deduit_usd"] == 1.0        # 0,5 + 0,5


def test_un_ledger_sans_frais_donne_une_equity_partielle():
    lignes = [{"kind": "CLOSE", "coin": "BTC", "realized_net_pnl_usdc": 3.0}]
    e = EQ.depuis_ledger_lignes(lignes, capital_initial_usd=1_000.0)
    r = e.liquidatable_equity()
    assert r["statut"] == "PARTIELLE"                       # frais non vus => exchange_fee None


def test_securite_aucun_appel_reel():
    src = (RACINE / "src" / "hl_observer" / "ops" / "equity_canonique.py").read_text(encoding="utf-8")
    for interdit in ('"/exchange"', "'/exchange'", "requests.get", "requests.post", "import websocket",
                     "websockets.connect", "eth_account", "Account.from_key", "private_key"):
        assert interdit not in src, "appel interdit dans equity_canonique: %s" % interdit
