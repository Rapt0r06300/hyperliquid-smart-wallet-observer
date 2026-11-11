"""Parité des frais : le labo, le moteur PAPER et les portes de risque lisent la MÊME source.

``hl_observer.fees.hyperliquid_fees`` déclare nos frais une seule fois. Un module qui recopie sa
propre valeur finit par diverger : le détecteur de signaux de copie utilisait 4,0 bps au lieu de
4,5, ce qui rendait l'avantage restant trop favorable. Une stratégie ne doit jamais paraître
rentable parce qu'un composant applique des frais plus bas qu'un autre.
"""
from __future__ import annotations

from hl_observer.backtesting.copy_vault_copiability_entrees import CopiabilityConfig
from hl_observer.backtesting.copy_vault_persistence import PersistenceConfig
from hl_observer.copying.signal_detector import CopySignalTuning
from hl_observer.fees.hyperliquid_fees import MAKER_PERP_BPS, TAKER_PERP_BPS
from hl_observer.paper_trading.exec_model import ExecModelConfig
from hl_observer.risk.trade_floor import TradeFloorConfig


def test_tous_les_composants_appliquent_les_frais_de_la_source_unique():
    assert ExecModelConfig().taker_fee_bps == TAKER_PERP_BPS        # moteur PAPER : exécution taker
    assert ExecModelConfig().maker_fee_bps == MAKER_PERP_BPS        # moteur PAPER : exécution maker
    assert TradeFloorConfig().taker_fee_bps == TAKER_PERP_BPS       # porte de risque
    assert CopySignalTuning().taker_fee_bps == TAKER_PERP_BPS       # détecteur de signaux de copie
    assert CopiabilityConfig().taker_fee_bps == TAKER_PERP_BPS      # labo : étude de copiabilité


def test_le_cout_de_replication_du_labo_ne_passe_jamais_sous_les_frais_taker():
    """Le coût par notionnel de l'étude de persistance = frais taker + demi-écart : jamais moins que les frais."""
    assert PersistenceConfig().cost_bps_per_notional >= TAKER_PERP_BPS


def test_aucun_dimensionneur_n_accepte_un_ordre_que_la_plateforme_refuserait():
    """Hyperliquid refuse tout ordre de moins de 10 USD. Les dimensionneurs acceptaient 5 USD (et le
    plancher générique 1,50 USD) : avec 350 USD de capital, c'était simuler des trades impossibles."""
    from hl_observer.fees.hyperliquid_fees import MIN_ORDER_VALUE_USD
    from hl_observer.risk.kelly_sizer import KellySizerConfig
    from hl_observer.risk.proportional_paper_sizer import (
        ProportionalSizingConfig,
        size_proportional_paper_notional,
    )
    from hl_observer.risk.trade_floor import evaluate_trade_floor, meets_floor

    assert MIN_ORDER_VALUE_USD == 10.0
    assert ProportionalSizingConfig().min_notional_usdt == KellySizerConfig().min_notional_usdt == MIN_ORDER_VALUE_USD
    # 350 USD de capital, plafond de 5 % : 17,50 USD -> accepté ; copie à 8 USD -> refusée
    grand = size_proportional_paper_notional(leader_size=10.0, leader_price=100.0, equity_usdt=350.0)
    assert grand.accepted and grand.paper_notional_usdt == 17.5
    petit = size_proportional_paper_notional(leader_size=1.6, leader_price=100.0, equity_usdt=350.0)
    assert petit.paper_notional_usdt == 8.0 and not petit.accepted
    assert petit.reason == "MIRROR_NOTIONAL_BELOW_MINIMUM"
    # un réglage plus bas que la plateforme ne peut pas abaisser le minimum
    force = size_proportional_paper_notional(
        leader_size=1.6, leader_price=100.0, equity_usdt=350.0,
        config=ProportionalSizingConfig(min_notional_usdt=1.0))
    assert not force.accepted
    assert not meets_floor(9.99) and meets_floor(10.0) and not meets_floor(5.0, min_trade_usdc=1.5)
    assert evaluate_trade_floor(9.0).passes_floor is False


def test_le_moteur_paper_ne_facture_jamais_moins_que_le_labo_pour_un_aller_retour_taker():
    aller_retour_labo = 2.0 * CopiabilityConfig().taker_fee_bps
    aller_retour_moteur = 2.0 * ExecModelConfig().taker_fee_bps
    assert aller_retour_moteur == aller_retour_labo
    assert TradeFloorConfig().taker_fee_bps * TradeFloorConfig().round_trips >= aller_retour_labo
