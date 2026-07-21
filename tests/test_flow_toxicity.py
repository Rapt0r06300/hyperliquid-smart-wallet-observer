"""#389 #507 #516 #521 #529 #535 #558 -- la toxicite du flux. **Sept taches, une seule entree.**

🔑 LE TEST CENTRAL : `test_le_VPIN_utilise_une_HORLOGE_DE_VOLUME_pas_de_TEMPS`.
*L'information n'arrive pas a un rythme regulier : elle arrive quand ca trade.*
Decouper en temps, c'est melanger une minute calme et une minute de panique.

🚩 ET LA RESERVE, DITE D'AVANCE : le VPIN ne peut PAS ressusciter un signal sans information
(-7,97 bps a cout ZERO). **Sa seule valeur : dire QUAND NE PAS TRADER.**
"""
from __future__ import annotations

import pytest

from hl_observer.market.flow_toxicity import (
    ACHAT,
    MOTIF_FLUX_TOXIQUE,
    MOTIF_PAS_ASSEZ,
    MOTIF_SQUEEZE,
    MOTIF_TRADE_ENCOMBRE,
    SEUIL_VPIN_TOXIQUE,
    VENTE,
    Trade,
    buckets_de_volume,
    faut_il_s_abstenir,
    lire_open_interest,
    ofi,
    toxicite_par_cote,
    vpin,
)


def _t(i: int, cote: str, taille: float = 1.0, prix: float = 100.0) -> Trade:
    return Trade(time_ms=1000 * i, prix=prix, taille=taille, cote_agresseur=cote)


# ════════════════════════════════════════════════════════════════════════════════════════════
# #389 / #507 — OFI
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_l_OFI_mesure_le_desequilibre_du_FLUX() -> None:
    assert ofi([_t(0, ACHAT), _t(1, ACHAT), _t(2, ACHAT), _t(3, VENTE)]) == pytest.approx(0.5)
    assert ofi([_t(0, ACHAT), _t(1, VENTE)]) == pytest.approx(0.0)
    assert ofi([_t(0, VENTE)]) == pytest.approx(-1.0)


def test_l_OFI_rend_None_plutot_qu_un_ZERO_FABRIQUE() -> None:
    """🔴 Un 0 invente dirait « flux parfaitement equilibre ». **C'est un mensonge, pas une absence.**"""
    assert ofi([]) is None
    assert ofi([Trade(0, 100.0, 0.0, ACHAT)]) is None          # taille nulle -> ECARTE
    assert ofi([Trade(0, 100.0, 1.0, "PEUT-ETRE")]) is None    # cote inconnue -> ECARTE


# ════════════════════════════════════════════════════════════════════════════════════════════
# #521 — 🔑 LE VPIN SUR HORLOGE DE VOLUME
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_le_VPIN_utilise_une_HORLOGE_DE_VOLUME_pas_de_TEMPS() -> None:
    """🔑 **LE CŒUR DE LA METHODE, et ce que tout le monde rate.**

    Ici : 1 trade ENORME, puis 99 trades minuscules. Sur une horloge de TEMPS, le gros trade
    serait noye dans un bucket parmi d'autres. Sur une horloge de VOLUME, **il occupe a lui seul
    plusieurs buckets** -- ce qui est correct : c'est la ou l'information est passee.
    """
    trades = [Trade(0, 100.0, 1000.0, ACHAT)] + [_t(i, VENTE, 0.01) for i in range(1, 100)]
    bs = buckets_de_volume(trades, n_buckets=10)

    assert len(bs) == 10, (
        "🔴 **UN TRADE DOIT POUVOIR ÊTRE FRACTIONNÉ.** Ma 1re version ne fractionnait pas : "
        "le trade géant (99,9 % du volume) occupait UN bucket au lieu de dix, et la moyenne "
        "se faisait sur 2 buckets au lieu de 10. *Un bucket de VOLUME, pas un bucket de TRADES.*"
    )
    # le trade geant (99,9 % du volume) remplit A LUI SEUL les 9 premiers buckets
    for b in bs[:9]:
        assert all(c == ACHAT for c, _ in b), "le geant occupe les 9 premiers buckets"
    # ... et le dernier bucket contient la queue des petites ventes
    assert any(c == VENTE for c, _ in bs[-1])
    # chaque bucket a (a peu pres) le MEME volume : c'est la definition
    vols = [sum(n for _, n in b) for b in bs]
    assert max(vols) / min(vols) < 1.05


def test_un_flux_EQUILIBRE_a_un_VPIN_bas() -> None:
    trades = [_t(i, ACHAT if i % 2 else VENTE) for i in range(400)]
    v = vpin(trades)
    assert v is not None and v < 0.20


def test_un_flux_TOUT_D_UN_COTE_a_un_VPIN_MAXIMAL() -> None:
    """**Flux totalement desequilibre = flux INFORME.** Servir ces agresseurs, c'est etre le pigeon."""
    v = vpin([_t(i, ACHAT) for i in range(400)])
    assert v == pytest.approx(1.0)


def test_moins_de_200_trades_ne_donne_AUCUN_chiffre() -> None:
    assert vpin([_t(i, ACHAT) for i in range(199)]) is None


# ════════════════════════════════════════════════════════════════════════════════════════════
# 🎯 LA SEULE VALEUR DU VPIN : DIRE QUAND NE PAS TRADER
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_un_VPIN_NON_MESURABLE_fait_S_ABSTENIR() -> None:
    """🔴 DENY-BY-DEFAULT. ***Ne pas savoir si le flux est toxique n'est pas une permission.***"""
    stop, m = faut_il_s_abstenir(None)
    assert stop
    assert MOTIF_PAS_ASSEZ in m
    assert "n'est pas une permission" in m


def test_un_flux_TOXIQUE_fait_S_ABSTENIR() -> None:
    stop, m = faut_il_s_abstenir(0.85)
    assert stop and MOTIF_FLUX_TOXIQUE in m
    assert "pigeon" in m


def test_un_flux_SAIN_laisse_passer() -> None:
    stop, _ = faut_il_s_abstenir(0.10)
    assert not stop
    assert SEUIL_VPIN_TOXIQUE == 0.40


# ════════════════════════════════════════════════════════════════════════════════════════════
# #516 / #529 / #535 — LA TOXICITE PAR COTE
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_le_markout_par_cote_se_calcule_SUR_LE_MID() -> None:
    """🔴 Un markout sur des prix de TRADE oscille bid<->ask et **fabrique un edge**.
    *Ca m'est arrive DEUX fois (T1 puis T1b). Pas une troisieme.*"""
    mids = [(0, 100.0), (30_000, 101.0), (60_000, 101.0)]
    # un ACHAT agressif a t=0 : le prix MONTE de 100 bps -> l'agresseur avait RAISON
    tox = toxicite_par_cote([Trade(0, 100.0, 1.0, ACHAT)], mids, horizon_ms=30_000)
    assert tox.markout_achat_bps == pytest.approx(100.0)
    assert tox.n_achat == 1 and tox.n_vente == 0


def test_le_bid_et_l_ask_n_ont_PAS_la_meme_toxicite() -> None:
    """🔴 Le cœur de #516. Si les acheteurs sont informes et les vendeurs non : **asymetrie**."""
    mids = [(0, 100.0), (30_000, 101.0)]
    tox = toxicite_par_cote(
        [Trade(0, 100.0, 1.0, ACHAT), Trade(0, 100.0, 1.0, VENTE)], mids, horizon_ms=30_000)
    assert tox.markout_achat_bps == pytest.approx(100.0)     # l'acheteur avait raison
    assert tox.markout_vente_bps == pytest.approx(-100.0)    # le vendeur avait tort
    assert tox.asymetrique
    assert "PAS la même toxicité" in tox.note
    assert "dangereux de les servir" in tox.note


def test_aucun_mid_rend_un_etat_VIDE_HONNETE() -> None:
    tox = toxicite_par_cote([_t(0, ACHAT)], [])
    assert tox.markout_achat_bps is None and "vide honnête" in tox.note


# ════════════════════════════════════════════════════════════════════════════════════════════
# #558 — L'OPEN INTEREST : le trade ENCOMBRE
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_OI_qui_MONTE_avec_le_prix_signale_un_trade_ENCOMBRE() -> None:
    """***Un trade encombre est un trade ou l'on est la sortie de secours de quelqu'un d'autre.***"""
    v = lire_open_interest(1000.0, 1100.0, 100.0, 105.0)
    assert v is not None and v.motif == MOTIF_TRADE_ENCOMBRE
    assert "sortie de secours" in v.note


def test_OI_qui_BAISSE_avec_le_prix_qui_monte_est_un_SQUEEZE() -> None:
    v = lire_open_interest(1000.0, 900.0, 100.0, 105.0)
    assert v is not None and v.motif == MOTIF_SQUEEZE
    assert "couverture" in v.note


def test_des_entrees_absurdes_rendent_None_pas_un_verdict_invente() -> None:
    assert lire_open_interest(0.0, 100.0, 100.0, 105.0) is None
    assert lire_open_interest(1000.0, 1100.0, 0.0, 105.0) is None
