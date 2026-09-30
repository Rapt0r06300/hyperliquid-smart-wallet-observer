"""#296 #323 #324 #359 — l'arbitrage : **on MESURE avant de construire.**

***Construire un moteur pour capturer un edge qu'on n'a jamais mesure, c'est EXACTEMENT ce que ce
projet punit depuis deux jours.*** (25 garde-fous ecrits, 23 sans appelant. 7 anti-overfit, ZERO
appelant. La pile V26 entiere, eteinte.)

🔴 LE TEST CENTRAL : `test_LE_MID_MENT_d_un_demi_spread_PAR_JAMBE`.
"""
from __future__ import annotations

import pytest

from hl_observer.arbitrage.triangular_measure import (
    COUT_3_JAMBES_BPS,
    MOTIF_EDGE_MESURE,
    MOTIF_KILL,
    MOTIF_PAS_D_EDGE,
    MOTIF_TROP_MINCE,
    MOTIF_UNHEDGED,
    EtatArbitrage,
    Jambe,
    evaluer_cycle,
)


def test_les_couts_sont_3_EXECUTIONS_taker() -> None:
    """Etre maker sur les 3 jambes, c'est du market making -- **T1b : mort.**"""
    assert COUT_3_JAMBES_BPS == pytest.approx(13.5)      # 3 x 4,5


# ════════════════════════════════════════════════════════════════════════════════════════════
# 🔴 LE TEST CENTRAL
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_LE_MID_MENT_d_un_demi_spread_PAR_JAMBE() -> None:
    """🔴 *Sur 3 jambes, c'est **1,5 spread** de mensonge.*

    C'est la faute qui a fabrique un faux edge de **+31 bps** dans T1. **On achete a l'ASK,
    on vend au BID. Toujours.**
    """
    # 3 jambes avec un spread de 20 bps chacune, et AUCUN vrai edge
    jambes = [
        Jambe("A/B", achat=True, bid=0.999, ask=1.001, profondeur_usd=10_000),
        Jambe("B/C", achat=False, bid=0.999, ask=1.001, profondeur_usd=10_000),
        Jambe("C/A", achat=False, bid=0.999, ask=1.001, profondeur_usd=10_000),
    ]
    v = evaluer_cycle(jambes)
    assert v is not None
    assert v.edge_au_mid_bps > v.edge_executable_bps, "le mid FLATTE toujours"
    assert v.mensonge_du_mid_bps > 0
    assert not v.viable
    assert "demi-spread" in v.as_dict()["avertissement"].lower() or \
           "DEMI-SPREAD" in v.as_dict()["avertissement"]


def test_un_cycle_SANS_edge_est_refuse_et_le_mensonge_du_mid_est_CHIFFRE() -> None:
    jambes = [
        Jambe("A/B", achat=True, bid=0.995, ask=1.005, profondeur_usd=10_000),
        Jambe("B/C", achat=False, bid=0.995, ask=1.005, profondeur_usd=10_000),
        Jambe("C/A", achat=False, bid=0.995, ask=1.005, profondeur_usd=10_000),
    ]
    v = evaluer_cycle(jambes)
    assert v is not None and not v.viable and v.motif == MOTIF_PAS_D_EDGE
    assert "le mid mentait de" in v.note


# ════════════════════════════════════════════════════════════════════════════════════════════
# LA TAILLE SE PROPAGE
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_une_opportunite_sur_3_dollars_de_PROFONDEUR_N_EXISTE_PAS() -> None:
    """🔴 *Un edge calcule au meilleur prix sur 3 $ de profondeur n'existe pas.*"""
    jambes = [
        Jambe("A/B", achat=True, bid=0.90, ask=0.91, profondeur_usd=3.0),   # <- la plus MINCE
        Jambe("B/C", achat=False, bid=1.20, ask=1.21, profondeur_usd=100_000),
        Jambe("C/A", achat=False, bid=1.10, ask=1.11, profondeur_usd=100_000),
    ]
    v = evaluer_cycle(jambes)
    assert v is not None and not v.viable and v.motif == MOTIF_TROP_MINCE
    assert v.taille_max_usd == pytest.approx(3.0), "la jambe la plus MINCE decide"
    assert "n'existe pas" in v.note


def test_un_VRAI_edge_est_reconnu_mais_avec_sa_RESERVE() -> None:
    jambes = [
        Jambe("A/B", achat=True, bid=0.90, ask=0.905, profondeur_usd=50_000),
        Jambe("B/C", achat=False, bid=1.15, ask=1.155, profondeur_usd=50_000),
        Jambe("C/A", achat=False, bid=1.00, ask=1.005, profondeur_usd=50_000),
    ]
    v = evaluer_cycle(jambes)
    assert v is not None
    if v.viable:
        assert v.motif == MOTIF_EDGE_MESURE
        assert "CENTAINES de cycles" in v.note, "un seul essai chanceux ne prouve rien"


def test_un_carnet_ABSURDE_est_ECARTE() -> None:
    assert evaluer_cycle([Jambe("A/B", True, 0.0, 1.0, 100.0)] * 3) is None
    assert evaluer_cycle([Jambe("A/B", True, 1.1, 1.0, 100.0)] * 3) is None   # bid > ask
    assert evaluer_cycle([Jambe("A/B", True, 1.0, 1.0, 100.0)]) is None       # 1 seule jambe


# ════════════════════════════════════════════════════════════════════════════════════════════
# #323 — LE KILL-SWITCH : l'etat UNHEDGED
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_un_cycle_reste_A_MOITIE_INTERDIT_tout_nouveau_cycle() -> None:
    """🔴 ***L'etat UNHEDGED est le seul etat vraiment dangereux d'un arbitrage.***

    Jambe 1 passee, jambe 2 rejetee -> **on est directionnel sans l'avoir voulu.**
    """
    e = EtatArbitrage(jambes_ouvertes=["A/B"], jambes_attendues=3)
    assert e.unhedged
    ok, m = e.peut_ouvrir_un_cycle()
    assert not ok and MOTIF_UNHEDGED in m
    assert "doubler un risque qu'on ne voulait pas" in m


def test_un_cycle_COMPLET_ne_bloque_pas() -> None:
    e = EtatArbitrage(jambes_ouvertes=["A/B", "B/C", "C/A"], jambes_attendues=3)
    assert not e.unhedged
    assert e.peut_ouvrir_un_cycle()[0]


def test_aucun_cycle_ouvert_ne_bloque_pas() -> None:
    assert EtatArbitrage(jambes_attendues=3).peut_ouvrir_un_cycle()[0]


def test_le_KILL_SWITCH_bloque_TOUT() -> None:
    e = EtatArbitrage(jambes_attendues=3)
    e.armer_le_kill()
    ok, m = e.peut_ouvrir_un_cycle()
    assert not ok and m == MOTIF_KILL
