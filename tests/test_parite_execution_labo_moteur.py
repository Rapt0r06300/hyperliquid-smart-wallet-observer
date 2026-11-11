"""Parité d'exécution taker entre le laboratoire et le moteur PAPER, sur le MÊME carnet observé.

Une stratégie ne doit pas être rentable au labo parce que celui-ci remplit les ordres plus
facilement, ou à meilleur prix, que le moteur. Les deux parcourent la profondeur visible :

* labo  : ``copy_vault_execution_math._walk_quote_notional`` (tout ou rien) ;
* moteur : ``paper_trading.exec_model.simulate_depth_execution`` (remplissage partiel explicite).

Contrat vérifié ici : à profondeur suffisante, même prix moyen et même quantité ; à profondeur
insuffisante, le labo REFUSE le trade et le moteur ne remplit jamais plus que le visible. Les frais
viennent de la même source dans les deux.
"""
from __future__ import annotations

import pytest

from hl_observer.backtesting.copy_vault_execution_math import _walk_quote_notional
from hl_observer.economics.families import build_copy_vault_contract
from hl_observer.economics.proof_binding import EconomicRunMode
from hl_observer.fees.hyperliquid_fees import TAKER_PERP_BPS
from hl_observer.paper_trading.exec_model import ExecModelConfig, simulate_depth_execution

# Carnet réel observé le 2026-11-11 sur un marché HIP-3 (xyz:COIN), 5 niveaux par côté.
ASKS = [(134.72, 1.765), (134.73, 3.189), (134.74, 6.705), (134.75, 8.42), (134.76, 15.304)]
BIDS = [(134.69, 7.13), (134.68, 3.356), (134.67, 109.081), (134.66, 12.257), (134.65, 91.16)]
MID = (ASKS[0][0] + BIDS[0][0]) / 2.0
VISIBLE_ASK_USD = sum(px * sz for px, sz in ASKS)
TOLERANCE = 1e-9          # relative : le labo calcule en décimal exact, le moteur en flottant arrondi à 1e-10


@pytest.mark.parametrize("notional", [10.0, 50.0, 150.0, 237.7, 350.0, 1_000.0, 3_000.0])
@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_meme_carnet_meme_prix_moyen_et_meme_quantite(side: str, notional: float) -> None:
    niveaux = ASKS if side == "BUY" else BIDS
    labo = _walk_quote_notional(niveaux, notional)
    moteur = simulate_depth_execution(side=side, notional_usdc=notional, mid_price=MID, asks=ASKS, bids=BIDS)

    assert labo is not None and moteur.reason == "FILLED" and moteur.fill_ratio == 1.0
    vwap_labo, quantite_labo = labo
    assert moteur.average_fill_price == pytest.approx(vwap_labo, rel=TOLERANCE)
    assert moteur.filled_quantity == pytest.approx(quantite_labo, rel=TOLERANCE)
    assert moteur.filled_notional_usdc == pytest.approx(notional, rel=TOLERANCE)
    # un taker ne traite jamais mieux que le meilleur prix affiché
    assert (vwap_labo >= ASKS[0][0]) if side == "BUY" else (vwap_labo <= BIDS[0][0])


def test_profondeur_insuffisante_le_labo_refuse_et_le_moteur_n_invente_aucune_liquidite() -> None:
    demande = VISIBLE_ASK_USD * 1.5
    assert _walk_quote_notional(ASKS, demande) is None                 # labo : pas de trade, jamais un prix supposé
    moteur = simulate_depth_execution(side="BUY", notional_usdc=demande, mid_price=MID, asks=ASKS, bids=BIDS)
    assert moteur.filled_notional_usdc == pytest.approx(VISIBLE_ASK_USD, rel=1e-8)   # exactement le visible
    assert moteur.partial is True and moteur.missed is True and moteur.reason == "MISSED_FILL"
    assert moteur.missed_notional_usdc == pytest.approx(demande - VISIBLE_ASK_USD, rel=1e-6)
    # juste sous la profondeur visible mais au-dessus du seuil de remplissage : partiel déclaré, pas un plein
    presque = simulate_depth_execution(side="BUY", notional_usdc=VISIBLE_ASK_USD * 1.1, mid_price=MID, asks=ASKS)
    assert presque.partial is True and presque.missed is False and presque.fill_ratio < 1.0
    # carnet vide : aucun remplissage, aucun prix
    vide = simulate_depth_execution(side="BUY", notional_usdc=50.0, mid_price=MID, asks=[])
    assert vide.average_fill_price is None and vide.filled_quantity == 0.0 and vide.reason == "NO_DEPTH"
    assert _walk_quote_notional([], 50.0) is None


def test_plus_l_ordre_est_gros_plus_le_prix_moyen_est_defavorable() -> None:
    """Métamorphique : sur un carnet fixe, le coût d'exécution ne baisse jamais quand la taille augmente."""
    tailles = [10.0, 100.0, 237.0, 500.0, 1_500.0, 3_000.0]
    achats = [_walk_quote_notional(ASKS, t)[0] for t in tailles]
    ventes = [_walk_quote_notional(BIDS, t)[0] for t in tailles]
    assert achats == sorted(achats) and ventes == sorted(ventes, reverse=True)
    glissements = [simulate_depth_execution(side="BUY", notional_usdc=t, mid_price=MID, asks=ASKS).slippage_bps
                   for t in tailles]
    assert glissements == sorted(glissements) and glissements[0] > 0.0   # le demi-écart se paie dès le premier dollar


def test_les_frais_du_labo_et_du_moteur_viennent_de_la_meme_source() -> None:
    contrat = build_copy_vault_contract(
        mode=EconomicRunMode.EXPLORATORY, notional_usd=150.0, copy_delay_ms=60_000.0,
        max_reference_lag_ms=30_000.0, max_target_lag_ms=30_000.0)
    frais_labo = float(contrat.registry.get("fee.taker.hyperliquid.bps").value)
    assert frais_labo == TAKER_PERP_BPS == ExecModelConfig().taker_fee_bps


def test_aller_retour_sur_350_usd_coute_au_moins_frais_plus_ecart() -> None:
    """Ordre de grandeur de référence : un aller-retour taker de 350 USD sur ce carnet réel."""
    achat = simulate_depth_execution(side="BUY", notional_usdc=350.0, mid_price=MID, asks=ASKS, bids=BIDS)
    vente = simulate_depth_execution(side="SELL", notional_usdc=350.0, mid_price=MID, asks=ASKS, bids=BIDS)
    cout_bps = achat.slippage_bps + vente.slippage_bps + 2.0 * TAKER_PERP_BPS
    ecart_bps = (ASKS[0][0] - BIDS[0][0]) / MID * 1e4
    assert cout_bps >= ecart_bps + 2.0 * TAKER_PERP_BPS - 1e-6
    assert 350.0 * cout_bps / 1e4 > 0.0
