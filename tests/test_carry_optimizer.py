"""Optimiseur de carry — chaque levier fait ce qu'il promet, deny-by-default (entrée absente = neutre)."""
from __future__ import annotations

from hl_observer.funding.carry_optimizer import (
    break_even_heures, cout_entree_optimise_bps, facteur_kelly, facteur_vol, facteur_zscore,
    funding_encaisse_bps_h, sens_carry, taille_carry,
)


# Y1 — le maker coûte MOINS et rembourse PLUS VITE
def test_maker_moins_cher_que_taker():
    cm = cout_entree_optimise_bps(0.0, maker=True)
    ct = cout_entree_optimise_bps(0.0, maker=False, spread_spot_bps=6.0, spread_perp_bps=1.0)
    assert cm < ct                                   # maker évite frais taker + demi-spread
    assert cm == 3.0                                  # 2 × 1.5 bps, pas de spread


def test_base_positive_reduit_le_cout():
    assert cout_entree_optimise_bps(2.0, maker=True) < cout_entree_optimise_bps(0.0, maker=True)
    assert cout_entree_optimise_bps(999.0, maker=True) == 0.0   # jamais négatif (pas de cadeau)


def test_break_even_maker_plus_rapide():
    cm = cout_entree_optimise_bps(0.0, maker=True)
    ct = cout_entree_optimise_bps(0.0, maker=False, spread_spot_bps=6.0, spread_perp_bps=1.0)
    assert break_even_heures(cm, 0.125) < break_even_heures(ct, 0.125)
    assert break_even_heures(5.0, 0.0) is None


# Y2 — sens du carry
def test_sens_carry():
    assert sens_carry(0.125) == "NORMAL"
    assert sens_carry(-0.125) == "INVERSE"
    assert sens_carry(0.001) == "NEUTRE"
    assert sens_carry(None) == "NEUTRE"
    assert funding_encaisse_bps_h(-0.125) == 0.125    # on encaisse |funding| en inverse
    assert funding_encaisse_bps_h(0.001) == 0.0


# Y4 — z-score
def test_facteur_zscore():
    assert facteur_zscore(3.0) == 1.5                 # spike -> plus gros
    assert facteur_zscore(0.0) == 1.0                 # normal -> neutre
    assert facteur_zscore(-2.0) == 0.5                # évaporé -> plus petit
    assert facteur_zscore(None) == 1.0                # absent -> neutre


# Y15 — Kelly (facteur = fraction 0.25 × edge/variance, borné)
def test_facteur_kelly():
    assert facteur_kelly(80.0, 10.0) > 1.0            # edge élevé / variance basse -> plus gros (0.25×8=2→cap 1.5)
    assert facteur_kelly(80.0, 10.0) <= 1.5           # borné
    assert facteur_kelly(10.0, 40.0) < 1.0            # edge faible / variance haute -> plus petit
    assert facteur_kelly(None, 10.0) == 1.0           # absent -> neutre
    assert facteur_kelly(40.0, 0.0) == 1.0            # variance nulle -> neutre (pas de division)


# Y16 — vol-target
def test_facteur_vol():
    assert facteur_vol(0.5, 1.0) > 1.0                # marché calme (vol < cible) -> plus gros
    assert facteur_vol(2.0, 1.0) < 1.0                # marché agité -> plus petit
    assert facteur_vol(None, 1.0) == 1.0              # absent -> neutre


# combinaison bornée, deny-by-default
def test_taille_carry_bornee_et_neutre_si_absent():
    assert taille_carry(100.0) == 100.0               # aucune entrée -> base inchangée
    gros = taille_carry(100.0, zscore=3.0, edge_bps=40.0, variance_bps2=10.0, vol_realisee=0.5, vol_cible=1.0)
    assert 100.0 < gros <= 200.0                      # amplifié mais plafonné à 2×
    petit = taille_carry(100.0, zscore=-2.0, vol_realisee=3.0, vol_cible=1.0)
    assert 25.0 <= petit < 100.0                      # réduit mais plancher 0.25×
