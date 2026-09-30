"""LES PANNES DE COLLECTE ONT TOUJOURS ETE SILENCIEUSES (2026-07-12).

L'historique du projet est sans appel :
  * le poller de carnet L2 n'a JAMAIS demarre -- une liste vide, aucun log ;
  * le recording des marks s'est arrete a 02h32 sans un mot ;
  * le runner WS mourait au 1er drop... et rendait quand meme un verdict.

Ces tests defendent l'outil qui cherche la panne AVANT qu'elle ne coute la nuit.

Aucun ordre reel.
"""
from __future__ import annotations

from hl_observer.backtesting.market_making_flow import MIN_TRADES_POUR_CONCLURE
from hl_observer.collection.trades_recorder import MAX_OCTETS
from tools.verifier_ecoute import eta_fills, projection_taille, trous_du_flux


# ------------------------------------------------------------- la borne des 200 Mo

def test_la_borne_de_200_Mo_est_ANNONCEE_avant_d_etre_atteinte():
    """`ecrire()` s'arrete EN SILENCE au-dela de 200 Mo. Le savoir a 3 h 50 ne sert a rien."""
    # 50 Mo en 30 min -> 400 Mo sur 4 h : depassement certain
    p = projection_taille(50e6, 30 * 60)
    assert p["depassera"] is True
    assert p["projection_octets"] > MAX_OCTETS


def test_un_debit_raisonnable_ne_declenche_pas_de_fausse_alerte():
    p = projection_taille(2e6, 30 * 60)          # 2 Mo/30 min -> 16 Mo sur 4 h
    assert p["depassera"] is False
    assert p["marge_pct"] > 80.0


def test_sans_temps_ecoule_on_ne_projette_RIEN():
    """Extrapoler depuis zero seconde, c'est inventer un nombre."""
    assert projection_taille(1e6, 0.0)["depassera"] is False


# ------------------------------------------------------------- les trous = deconnexions

def test_un_silence_de_plusieurs_minutes_est_un_TROU_pas_un_marche_calme():
    """Sur 49 marches actifs, une minute sans le moindre trade n'est pas du calme :
    c'est une socket morte."""
    ts = [float(i) for i in range(0, 100)] + [float(i) for i in range(400, 500)]
    trous = trous_du_flux(ts)
    assert len(trous) == 1
    assert trous[0][1] > 60.0


def test_un_flux_continu_ne_signale_aucun_trou():
    assert trous_du_flux([float(i) for i in range(0, 600)]) == []


# ------------------------------------------------------------- l'ETA des fills

def test_l_ETA_dit_NON_quand_la_fenetre_ne_suffira_pas():
    """La reponse honnete a 'KAITO paiera-t-il ?' peut etre 'on ne le saura pas ce soir'."""
    # 10 fills en 30 min = 0,33/min -> il en manque 290 -> ~14,5 h. Il reste 3 h.
    e = eta_fills(10, 30 * 60, restant_s=3 * 3600)
    assert e["atteignable"] is False
    assert e["eta_s"] > 3 * 3600


def test_l_ETA_dit_OUI_quand_le_debit_suffit():
    e = eta_fills(280, 30 * 60, restant_s=3 * 3600)
    assert e["atteignable"] is True


def test_sans_aucun_fill_l_ETA_est_INCONNU_pas_zero():
    e = eta_fills(0, 30 * 60, restant_s=3 * 3600)
    assert e["eta_s"] is None
    assert e["atteignable"] is None


def test_la_cible_atteinte_est_reconnue():
    e = eta_fills(MIN_TRADES_POUR_CONCLURE, 30 * 60, restant_s=60.0)
    assert e["eta_s"] == 0.0
    assert e["atteignable"] is True
