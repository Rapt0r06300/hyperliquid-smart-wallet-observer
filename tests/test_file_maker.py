"""Le `queue_ratio` d'un ordre passif : ce qu'il mesure, et ce qu'il REFUSE de supposer.

L'enjeu : taker = 4,5 bps par jambe (9 bps l'aller-retour), maker = 1,5 (3 bps). **6 bps d'écart**,
soit +1,20 USD/jour dès 20 allers-retours sur 100 USD — face à −0,19 USD/jour mesuré.

Mais supposer qu'un ordre passif se remplit aux mêmes instants qu'un ordre agressif fabriquerait
exactement le PnL qu'on cherche à mesurer, et l'erreur serait invisible puisqu'elle embellit le
résultat. Ces tests gardent les deux hypothèses conservatrices et le refus de deviner.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import copy_vault_file_maker as F  # noqa: E402
from hl_observer.paper_trading.fill_outcomes import FillOutcome, resolve_fill  # noqa: E402

CARNET = {
    "bids5": [[100.0, 5.0], [99.0, 7.0], [98.0, 3.0]],
    "asks5": [[101.0, 4.0], [102.0, 6.0], [103.0, 2.0]],
}


def _t(prix, taille, agresseur):
    return {"price": prix, "size": taille, "aggressor_side": agresseur}


# --------------------------------------------------------------------------- la file devant moi


def test_j_arrive_dernier_dans_la_file() -> None:
    """Le carnet ne porte pas la priorité temporelle : tout ce qui repose à mon prix me précède."""
    assert F.taille_devant(CARNET, prix=100.0, cote=F.ACHAT) == 5.0


def test_les_meilleurs_prix_sont_servis_avant_moi() -> None:
    # Un achat à 99 : les 5 lots à 100 passent avant, plus les 7 lots à 99.
    assert F.taille_devant(CARNET, prix=99.0, cote=F.ACHAT) == 12.0
    # Côté vente, « meilleur » veut dire MOINS cher.
    assert F.taille_devant(CARNET, prix=102.0, cote=F.VENTE) == 10.0


def test_se_poser_loin_derriere_met_tout_le_carnet_devant_soi() -> None:
    """Un achat à 50 quand le marché achète à 100 : les trois niveaux passent avant moi.

    C'est la bonne réponse, et elle traduit la réalité — un ordre posé loin du marché n'est
    servi qu'après tous les autres, donc presque jamais.
    """
    assert F.taille_devant(CARNET, prix=50.0, cote=F.ACHAT) == 15.0


def test_se_poser_devant_tout_le_monde_vide_la_file() -> None:
    """Un achat à 100,5 — encore passif, sous le meilleur prix de vente (101) — passe devant."""
    assert F.taille_devant(CARNET, prix=100.5, cote=F.ACHAT) == 0.0
    # Miroir : pour VENDRE, « meilleur » veut dire MOINS cher. Une vente à 100,5 passe donc
    # devant les offres à 101/102/103, tandis qu'une vente à 103 les a toutes devant elle.
    assert F.taille_devant(CARNET, prix=100.5, cote=F.VENTE) == 0.0
    assert F.taille_devant(CARNET, prix=103.0, cote=F.VENTE) == 12.0


def test_carnet_illisible_rend_none_pas_zero() -> None:
    """Zéro dirait « la voie est libre » ; None dit « je ne sais pas »."""
    assert F.taille_devant({}, prix=100.0, cote=F.ACHAT) is None
    assert F.taille_devant({"bids5": []}, prix=100.0, cote=F.ACHAT) is None
    assert F.taille_devant({"bids5": [[None, 1.0]]}, prix=100.0, cote=F.ACHAT) is None


# --------------------------------------------------------------------------- ce qui est passé


def test_seul_le_flux_agressif_du_bon_cote_me_remplit() -> None:
    """Un achat passif n'est rempli que par un VENDEUR agressif à mon prix ou en dessous."""
    transactions = [
        _t(100.0, 2.0, F.VENTE),   # me remplit
        _t(99.0, 1.0, F.VENTE),    # me remplit (encore mieux)
        _t(101.0, 9.0, F.VENTE),   # au-dessus de mon prix : ne me concerne pas
        _t(100.0, 8.0, F.ACHAT),   # acheteur agressif : ne me remplit pas
    ]
    assert F.volume_traverse(transactions, prix=100.0, cote=F.ACHAT) == 3.0


def test_le_cote_vente_est_le_miroir() -> None:
    transactions = [_t(102.0, 2.0, F.ACHAT), _t(101.0, 5.0, F.ACHAT), _t(103.0, 1.0, F.ACHAT)]
    assert F.volume_traverse(transactions, prix=102.0, cote=F.VENTE) == 3.0


def test_aucune_transaction_lisible_rend_none() -> None:
    """« Rien n'est passé » et « je n'ai pas su lire » ne doivent jamais se confondre."""
    assert F.volume_traverse([], prix=100.0, cote=F.ACHAT) is None
    assert F.volume_traverse([{"price": None}], prix=100.0, cote=F.ACHAT) is None
    assert F.volume_traverse([_t(100.0, 1.0, "???")], prix=100.0, cote=F.ACHAT) is None


def test_des_transactions_lisibles_mais_du_mauvais_cote_rendent_zero() -> None:
    """Là, on SAIT : rien n'a traversé. Zéro est la bonne réponse, pas None."""
    assert F.volume_traverse([_t(100.0, 8.0, F.ACHAT)], prix=100.0, cote=F.ACHAT) == 0.0


# --------------------------------------------------------------------------- le ratio


def test_le_marche_consomme_la_file_je_suis_servi() -> None:
    ratio = F.ratio_de_file(CARNET, [_t(100.0, 20.0, F.VENTE)], prix=100.0, cote=F.ACHAT)
    assert ratio == 0.25
    assert resolve_fill(notional_usdc=100.0, is_maker=True,
                        queue_ratio=ratio).outcome is FillOutcome.FILLED


def test_le_marche_effleure_la_file_je_suis_servi_a_moitie() -> None:
    ratio = F.ratio_de_file(CARNET, [_t(100.0, 6.25, F.VENTE)], prix=100.0, cote=F.ACHAT)
    assert ratio == 0.8
    resultat = resolve_fill(notional_usdc=100.0, is_maker=True, queue_ratio=ratio)
    assert resultat.outcome is FillOutcome.PARTIAL
    assert round(resultat.fill_fraction, 6) == 0.2


def test_rien_ne_passe_je_ne_suis_pas_servi() -> None:
    ratio = F.ratio_de_file(CARNET, [_t(100.0, 3.0, F.ACHAT)], prix=100.0, cote=F.ACHAT)
    assert ratio == float("inf")
    assert resolve_fill(notional_usdc=100.0, is_maker=True,
                        queue_ratio=ratio).outcome is FillOutcome.MISSED


def test_une_mesure_manquante_vaut_refus_jamais_remplissage() -> None:
    """LA règle : ne pas savoir, c'est ne pas être rempli. Un 0.0 par défaut déclarerait
    un remplissage CERTAIN sur une ignorance — et gonflerait le PnL."""
    assert F.ratio_de_file({}, [_t(100.0, 5.0, F.VENTE)], prix=100.0, cote=F.ACHAT) is None
    assert F.ratio_de_file(CARNET, [], prix=100.0, cote=F.ACHAT) is None
    resultat = resolve_fill(notional_usdc=100.0, is_maker=True, queue_ratio=None)
    assert resultat.outcome is FillOutcome.MISSED
    assert resultat.filled_notional_usdc == 0.0


def test_le_taker_reste_rempli_immediatement() -> None:
    """Le mode agressif ne change pas : c'est le défaut du moteur gelé."""
    resultat = resolve_fill(notional_usdc=100.0, is_maker=False, queue_ratio=None)
    assert resultat.outcome is FillOutcome.FILLED and resultat.fill_fraction == 1.0


def test_cote_invalide_refuse() -> None:
    assert F.taille_devant(CARNET, prix=100.0, cote="PEUT_ETRE") is None
    assert F.volume_traverse([_t(100.0, 1.0, F.VENTE)], prix=100.0, cote="PEUT_ETRE") is None
