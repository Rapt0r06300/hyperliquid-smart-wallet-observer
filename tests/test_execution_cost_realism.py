"""Garde-fous : LE PnL PAPER NE DOIT JAMAIS ETRE FLATTE (chasse aux bugs, 2026-07-11).

Le ledger du run des 09-10 juillet montrait :
  - `entry_price == leader_price` sur **20 trades sur 20** ;
  - dans **8 cas sur 20**, l'entree se faisait a un prix MEILLEUR que le marche (impossible) ;
  - des frais d'entree de **1 bps** (contre 4,5 bps de taker fee reelle sur Hyperliquid) ;
  - la degradation de copie (~14 bps, calculee par le scorer) n'etait **jamais** soustraite du PnL.

Trois bugs de code, tous en faveur du bot :
  A. la LATENCE coutait ZERO (`latency_cost_bps_per_sec = 0.0`) alors qu'on copie avec un retard
     median MESURE de 57 secondes ;
  B. `PaperEngine` ne transmettait PAS `latency_sec` a `simulate_execution` ;
  C. le prix d'entree paper etait donc EXACTEMENT celui du leader, sans aucun cout de copie.

FAUSSE PISTE ECARTEE : j'ai d'abord cru que le demi-spread n'etait jamais paye (il n'apparait pas
explicitement dans le chemin taker). FAUX : `estimate_slippage_bps` le contient deja. L'ajouter
l'aurait compte DOUBLE. C'est un test existant qui a attrape l'erreur -- la raison d'etre des tests.

Consequence : le PnL affiche (-64,02 $) etait OPTIMISTE d'environ 19 $. La vraie perte etait plus
proche de -83 $. C'est exactement ce que la regle "le PnL paper n'est jamais maquille" interdit.

Simulation paper uniquement. Aucun ordre reel.
"""
from __future__ import annotations

import pytest

from hl_observer.paper_trading.exec_model import ExecModelConfig, simulate_execution


# ---------------------------------------------------------------- A. le spread est PAYE

def test_a_taker_order_always_pays_the_spread():
    """Un ordre au marche TRAVERSE le spread -- exactement UNE fois, jamais deux."""
    cfg = ExecModelConfig()
    assert cfg.half_spread_bps > 0, "un demi-spread nul n'existe pas sur un vrai carnet"

    r = simulate_execution(side="LONG", notional_usdc=500, mid_price=100.0,
                           top_depth_usdc=50_000, latency_sec=0.0, config=cfg)
    assert r.net_cost_bps >= cfg.taker_fee_bps + cfg.half_spread_bps, (
        f"cout {r.net_cost_bps:.2f} bps : le spread n'est PAS paye"
    )
    # ANTI-DOUBLE-COMPTAGE : le spread vit DANS estimate_slippage_bps. Le compter une 2e fois
    # gonflerait artificiellement les couts (et pessimiserait le PnL -- aussi malhonnete que
    # de le flatter). C'est l'erreur que j'ai failli commettre le 2026-07-11.
    from hl_observer.paper_trading.exec_model import estimate_slippage_bps
    attendu = estimate_slippage_bps(500, 50_000, config=cfg) + cfg.taker_fee_bps
    assert r.net_cost_bps == pytest.approx(attendu, abs=1e-6), (
        f"cout {r.net_cost_bps:.4f} != {attendu:.4f} -> le spread est compte DEUX FOIS"
    )


def test_the_fill_price_is_always_worse_than_the_mid_for_a_taker():
    """INVARIANT PHYSIQUE : un ordre au marche ne peut JAMAIS etre rempli mieux que le mid."""
    cfg = ExecModelConfig()
    for side, mid in (("LONG", 100.0), ("SHORT", 100.0), ("BUY", 3000.0), ("SELL", 3000.0)):
        r = simulate_execution(side=side, notional_usdc=500, mid_price=mid,
                               top_depth_usdc=50_000, latency_sec=0.0, config=cfg)
        if side in {"LONG", "BUY"}:
            assert r.fill_price > mid, f"{side} rempli SOUS le mid : gain impossible"
        else:
            assert r.fill_price < mid, f"{side} rempli AU-DESSUS du mid : gain impossible"


# ---------------------------------------------------------------- B. la latence coute

def test_latency_is_actually_charged():
    """Copier un leader avec 57 s de retard n'est PAS gratuit : le prix a bouge entre-temps."""
    cfg = ExecModelConfig()
    assert cfg.latency_cost_bps_per_sec > 0, "la latence coutait ZERO (bug du 2026-07-11)"

    instant = simulate_execution(side="LONG", notional_usdc=500, mid_price=100.0,
                                 top_depth_usdc=50_000, latency_sec=0.0, config=cfg)
    tardif = simulate_execution(side="LONG", notional_usdc=500, mid_price=100.0,
                                top_depth_usdc=50_000, latency_sec=57.0, config=cfg)
    assert tardif.net_cost_bps > instant.net_cost_bps, "un signal de 57 s coute autant qu'un instantane ?!"
    assert tardif.latency_bps >= 10.0, (
        f"57 s de retard ne coutent que {tardif.latency_bps:.1f} bps -- irrealiste : "
        f"le scorer, lui, mesure ~14 bps de degradation de copie."
    )


def test_latency_cost_is_capped():
    """Un signal tres vieux ne doit pas produire un cout absurde (il doit etre REFUSE en amont)."""
    cfg = ExecModelConfig()
    r = simulate_execution(side="LONG", notional_usdc=500, mid_price=100.0,
                           top_depth_usdc=50_000, latency_sec=100_000.0, config=cfg)
    assert r.latency_bps <= 30.0, "cout de latence non borne -> prix de fill absurde"


# ---------------------------------------------------------------- C. le PaperEngine transmet la latence

def test_paper_engine_passes_the_signal_age_to_the_execution_model():
    """Le PaperEngine recevait l'age du signal... et ne le transmettait pas au prix de fill."""
    from pathlib import Path

    src = Path("src/hl_observer/paper_trading/paper_engine.py").read_text(encoding="utf-8")
    bloc = src[src.index("exec_result = simulate_execution(") :][:600]
    assert "latency_sec=" in bloc, (
        "PaperEngine n'envoie pas `latency_sec` a simulate_execution : le retard de copie est "
        "factures ZERO et le paper trade entre au prix du leader."
    )


# ---------------------------------------------------------------- le cout total reste plausible

def test_the_total_round_trip_cost_is_realistic():
    """Aller-retour taker sur un signal de 57 s : entre 15 et 45 bps. Ni gratuit, ni absurde."""
    cfg = ExecModelConfig()
    entree = simulate_execution(side="SHORT", notional_usdc=500, mid_price=100.0,
                                top_depth_usdc=50_000, latency_sec=57.0, config=cfg)
    sortie = simulate_execution(side="BUY", notional_usdc=500, mid_price=100.0,
                                top_depth_usdc=50_000, latency_sec=0.0, config=cfg)
    total = entree.net_cost_bps + sortie.net_cost_bps
    assert 15.0 <= total <= 45.0, (
        f"cout aller-retour de {total:.1f} bps. Le scorer facture ~21 bps pour DECIDER : si le PnL "
        f"en facture beaucoup moins, il est FLATTE (et les gates deviennent incoherents avec lui)."
    )


def test_maker_fill_is_not_a_free_lunch():
    """En maker on ne paie pas le spread -- mais on subit la selection adverse.

    Un fill passif n'a lieu que quand le marche vient VERS vous, c'est-a-dire quand il va CONTRE
    vous. Sans penalite de selection adverse, le mode maker donne un cout NEGATIF (on serait paye
    pour entrer, au meilleur prix que le marche) : c'est un mirage.
    """
    import os

    cfg = ExecModelConfig()
    r = simulate_execution(side="LONG", notional_usdc=500, mid_price=100.0,
                           top_depth_usdc=50_000, is_maker=True, config=cfg)
    assert r.filled_notional_usdc == 0.0
    assert r.net_cost_bps is None
    assert r.reason == "NO_FILL_NO_QUEUE_EVIDENCE"
    assert os.environ.get("HYPERSMART_MAKER_ADVERSE_SELECTION_BPS") is None


# ======================================================================================
#  TARIF REEL HYPERLIQUID (2026-07-11) — LE MAKER **COUTE**, IL NE RAPPORTE PAS
#
#  `maker_rebate_bps = 1.0` traitait un fill passif comme un REBATE : cout NET NEGATIF,
#  c'est-a-dire que le bot etait *paye* pour entrer, et rempli a un prix MEILLEUR que le
#  marche. Or au tarif de base Hyperliquid : taker 0,045 % (4,5 bps), maker 0,015 % (1,5 bps).
#  Erreur de 2,5 bps par execution, dans le sens FAVORABLE -- exactement ce qui aurait fait
#  "valider" une strategie maker-first qui perd en reel.
# ======================================================================================

def test_a_maker_fill_costs_money_it_does_not_earn_it():
    cfg = ExecModelConfig()
    assert cfg.maker_fee_bps > 0, "un fill maker COUTE 0,015 % sur Hyperliquid"
    assert cfg.maker_rebate_bps == 0.0, (
        "le rebate n'existe qu'aux paliers de volume eleves : 0 par defaut, jamais par accident"
    )
    r = simulate_execution(side="LONG", notional_usdc=500, mid_price=100.0,
                           top_depth_usdc=50_000, is_maker=True,
                           queue_depletion_usdc=500.0,
                           adverse_selection_bps=0.0, config=cfg)
    assert r.net_cost_bps is not None
    assert r.net_cost_bps > 0, (
        f"cout maker {r.net_cost_bps:+.2f} bps : le bot serait PAYE pour entrer -- mirage."
    )
    assert r.fill_price > 100.0, "un achat maker ne peut pas etre rempli SOUS le mid"


def test_the_official_hyperliquid_tariff_is_respected():
    """taker 4,5 bps / maker 1,5 bps -> aller-retour taker = 9 bps de frais."""
    cfg = ExecModelConfig()
    assert cfg.taker_fee_bps == pytest.approx(4.5)
    assert cfg.maker_fee_bps == pytest.approx(1.5)
    assert cfg.taker_fee_bps * 2 == pytest.approx(9.0)   # aller-retour, hors spread/slippage


def test_maker_is_cheaper_than_taker_but_not_free():
    cfg = ExecModelConfig()
    maker = simulate_execution(side="LONG", notional_usdc=500, mid_price=100.0,
                               top_depth_usdc=50_000, is_maker=True,
                               queue_depletion_usdc=500.0,
                               adverse_selection_bps=0.0, config=cfg)
    taker = simulate_execution(side="LONG", notional_usdc=500, mid_price=100.0,
                               top_depth_usdc=50_000, is_maker=False, config=cfg)
    assert maker.net_cost_bps is not None
    assert taker.net_cost_bps is not None
    assert 0 < maker.net_cost_bps < taker.net_cost_bps, (
        "le maker doit etre MOINS CHER que le taker (pas de spread paye), mais jamais GRATUIT"
    )
