"""#517 (HIP-3) + #556 (oracle) + #530 (liquidations) — les 3 pistes qui restent.

Ce que ces tests gardent, et POURQUOI :

  * **#517** — le growth mode divise les frais par 10 ; **le test prouve que ça ne suffit PAS**,
    parce que T1b est mort sur l'INVENTAIRE, pas sur les coûts. *Franchir la porte B ne franchit
    pas la porte C.*
  * **#556** — le funding se calcule sur la **MOYENNE horaire** du premium et se paie **à l'heure**
    -> l'angle est le funding PRÉVISIBLE, **pas une course de vitesse** (qu'on perdrait).
    Et l'unité reste **HORAIRE** (le piège 8h/1h de la même soirée).
  * **#530** — le markout se calcule sur le **MID**, jamais sur des prix de trade
    (*le bid-ask bounce a fabriqué un faux edge deux fois : ça suffit*), et un markout **négatif**
    doit **tuer** la piste, pas être arrondi vers le haut.
"""
from __future__ import annotations

import pytest

from hl_observer.backtesting.liquidation_cascade import (
    MIN_COMPTES_PAR_CLUSTER,
    MIN_EVENEMENTS,
    MOTIF_COUTEAU_QUI_TOMBE,
    MOTIF_FLUX_NON_INFORME,
    MOTIF_PAS_ASSEZ_D_EVENEMENTS,
    NiveauLiquidation,
    construire_clusters,
    juger,
    markout_absorbeur_bps,
)
from hl_observer.fees.hyperliquid_fees import frais
from hl_observer.market.hip3_markets import (
    DexHip3,
    MarcheHip3,
    est_hip3,
    parser_meta_dex,
    parser_perp_dexs,
    resume,
)
from hl_observer.market.oracle_lag import (
    MOTIF_COURSE_DE_VITESSE,
    PointOracle,
    funding_predit_bps_h,
    mesurer_retour,
    verdict_course_de_vitesse,
)


# ════════════════════════════════════════════════════════════════════════════════════════════
# #517 — HIP-3
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_un_coin_HIP3_se_reconnait_a_son_deux_points() -> None:
    """Doc : « builder-deployed perps always have name in the format `{dex}:{coin}` »."""
    assert est_hip3("xyz:CL") and est_hip3("test:ABC")
    assert not est_hip3("BTC") and not est_hip3("HYPE")
    assert not est_hip3(":CL") and not est_hip3("xyz:")      # malformes ECARTES


def test_l_index_0_de_perpDexs_est_le_marche_PRINCIPAL_pas_un_HIP3() -> None:
    """⚠️ La reponse commence par `null` : c'est HyperCore, **PAS** un dex HIP-3."""
    dexs = parser_perp_dexs([None, {"name": "test", "deployer": "0xabc"}])
    assert [d.nom for d in dexs] == ["test"]
    assert dexs[0].index == 1


def test_un_marche_sans_szDecimals_est_ECARTE_jamais_devine() -> None:
    """Sans szDecimals on ne peut RIEN arrondir -> l'ordre serait invalide. On l'ecarte."""
    ms = parser_meta_dex("xyz", {"universe": [
        {"name": "CL", "szDecimals": 2, "maxLeverage": 5},
        {"name": "BAD"},                        # pas de szDecimals
    ]})
    assert [m.coin for m in ms] == ["CL"]
    assert ms[0].nom_complet == "xyz:CL"        # ce que `l2Book` attend


def test_LE_GROWTH_MODE_DIVISE_LES_FRAIS_PAR_DIX() -> None:
    g = frais(marche="perp", growth_mode=True)
    assert g.maker_bps == pytest.approx(0.15)   # au lieu de 1,5
    assert g.taker_bps == pytest.approx(0.45)


def test_MAIS_CA_NE_SUFFIT_PAS_la_porte_qui_TUE_est_l_INVENTAIRE() -> None:
    """🔴 LE TEST QUI COMPTE. *Franchir la porte des COÛTS ne franchit pas celle de l'INVENTAIRE.*

    #517 : 20 bps de demi-spread sur HIP-3. Avec le growth mode, les frais sont **négligeables**.
    Mais T1b a mesuré que **le prix bouge 5 à 30× plus** que le spread capturé pendant qu'on
    porte la position. **C'est ça qui tue, et le growth mode n'y touche pas.**
    """
    from hl_observer.backtesting.quoting_inside_spread import RATIO_CAPTURE_SUR_VOL_MIN

    capture = 20.0                                   # le demi-spread annonce par #517
    cout = 2 * frais(marche="perp", growth_mode=True).maker_bps      # 0,30 bps
    assert capture - cout > 19.0, "porte B (couts) : LARGEMENT franchie"

    # porte C : le mouvement du prix pendant la detention, borne BASSE mesuree par T1b (x5)
    mouvement = capture * 5.0
    assert capture / mouvement < RATIO_CAPTURE_SUR_VOL_MIN, (
        "**La porte C reste FERMEE.** Diviser les frais par 10 ne change RIEN au risque "
        "d'inventaire. Annoncer « HIP-3 ressuscite le MM » serait refaire la faute des 38 % d'APR."
    )


def test_le_module_DECLARE_son_attente_AVANT_de_mesurer() -> None:
    """*Annoncer son attente d'avance empeche de se raconter une histoire apres coup.*"""
    r = resume([DexHip3(1, "xyz")], [MarcheHip3("xyz", "CL", 2)])
    assert "ECHEC" in r["attente_declaree_AVANT_la_mesure"]
    assert "INVENTAIRE" in r["attente_declaree_AVANT_la_mesure"]
    assert any("ORACLE" in x.upper() for x in r["risques_specifiques_HIP3"]), (
        "sur HIP-3 l'oracle est fixe par le DEPLOYEUR (doc) -- un risque que HyperCore n'a pas"
    )


# ════════════════════════════════════════════════════════════════════════════════════════════
# #556 — L'ORACLE
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_la_forme_NAIVE_est_refusee_AVANT_toute_mesure() -> None:
    """« Lire Binance, devancer HL » = **course de vitesse**. On la perd par construction."""
    v = verdict_course_de_vitesse()
    assert v["motif"] == MOTIF_COURSE_DE_VITESSE
    assert "pigeon" in v["explication"]
    assert "PLATE" in v["explication"], "la courbe edge/horizon est plate : la vitesse n'est pas le sujet"
    assert "heure pour agir" in v["angle_retenu"]


def test_le_premium_est_l_ecart_mark_oracle_en_bps() -> None:
    p = PointOracle("BTC", 0, mark=100.10, oracle=100.0)
    assert p.premium_bps == pytest.approx(10.0)


def test_le_funding_predit_est_HORAIRE_pas_sur_8h() -> None:
    """🔴 Le piège d'unité de la même soirée. HL paie **à l'heure** = 1/8 du taux 8 h."""
    pts = [PointOracle("X", i, mark=100.0 + 0.20, oracle=100.0) for i in range(10)]  # +20 bps
    f = funding_predit_bps_h(pts)
    assert f is not None
    # premium 20 bps, clamp(1 - 20) borne a -5 -> funding 8h = 15 bps -> /8 = 1,875 bps/h
    assert f == pytest.approx(15.0 / 8.0, abs=1e-6)
    assert f < 20.0, "le taux HORAIRE doit etre bien plus petit que le premium 8 h"


def test_aucun_point_rend_None_pas_un_zero_fabrique() -> None:
    assert funding_predit_bps_h([]) is None


def test_un_echantillon_court_est_DIT_court() -> None:
    r = mesurer_retour("BTC", [PointOracle("BTC", i, 100.0, 100.0) for i in range(10)])
    assert not r.suffisant and "PAS_ASSEZ" in r.motif


def test_le_retour_vers_l_oracle_est_MESURE_et_avertit() -> None:
    pts = [PointOracle("BTC", i, mark=100.0 + (0.5 if i % 2 else 0.01), oracle=100.0)
           for i in range(100)]
    r = mesurer_retour("BTC", pts)
    assert r.suffisant and r.n == 100
    assert "trade de TOUT LE MONDE" in r.as_dict()["avertissement"]


# ════════════════════════════════════════════════════════════════════════════════════════════
# #530 — LES LIQUIDATIONS
# ════════════════════════════════════════════════════════════════════════════════════════════
def _niv(px: float, n: float = 1000.0, long: bool = True) -> NiveauLiquidation:
    return NiveauLiquidation("BTC", "0x%f" % px, px, n, long)


def test_un_compte_isole_n_est_PAS_une_cascade() -> None:
    assert construire_clusters([_niv(100.0), _niv(100.1)]) == []
    assert MIN_COMPTES_PAR_CLUSTER == 3


def test_des_niveaux_SERRES_forment_un_cluster() -> None:
    cs = construire_clusters([_niv(100.0), _niv(100.1), _niv(100.2)])
    assert len(cs) == 1 and cs[0].n_comptes == 3
    assert cs[0].notionnel_total_usd == pytest.approx(3000.0)
    assert cs[0].as_dict()["cote_force"] == "VENTE"      # des LONGS liquides -> vente forcee


def test_des_niveaux_ELOIGNES_ne_se_melangent_PAS() -> None:
    cs = construire_clusters([_niv(100.0), _niv(100.1), _niv(100.2),
                              _niv(200.0), _niv(200.1), _niv(200.2)])
    assert len(cs) == 2


def test_une_donnee_absurde_est_ECARTEE() -> None:
    assert construire_clusters([_niv(-1.0), _niv(0.0), _niv(100.0, n=-5.0)]) == []


def test_le_markout_de_l_ABSORBEUR_est_du_cote_OPPOSE() -> None:
    """Les liquides VENDENT de force -> l'absorbeur ACHETE -> il gagne si le prix MONTE."""
    mids = [(0.0, 100.0), (300.0, 101.0)]
    assert markout_absorbeur_bps(mids, t_evenement=0.0, horizon_s=300.0,
                                 cote_force_vend=True) == pytest.approx(100.0)
    # cote force ACHAT -> l'absorbeur VEND -> le meme +1 % devient une PERTE
    assert markout_absorbeur_bps(mids, t_evenement=0.0, horizon_s=300.0,
                                 cote_force_vend=False) == pytest.approx(-100.0)


def test_le_markout_rend_None_si_l_horizon_n_est_pas_couvert() -> None:
    assert markout_absorbeur_bps([(0.0, 100.0)], t_evenement=0.0, horizon_s=300.0,
                                 cote_force_vend=True) is None


def test_un_markout_NEGATIF_TUE_la_piste_il_n_est_PAS_arrondi_vers_le_haut() -> None:
    """🔴 **LE COUTEAU QUI TOMBE.** Si le prix continue de s'effondrer, absorber PERD."""
    v = juger("BTC", {30.0: [-5.0] * 25, 300.0: [-8.0] * 25})
    assert not v.viable and v.motif == MOTIF_COUTEAU_QUI_TOMBE
    assert "CONTINUE de tomber" in v.note


def test_un_markout_POSITIF_est_reconnu_MAIS_avec_ses_reserves() -> None:
    v = juger("BTC", {30.0: [2.0] * 25, 300.0: [12.0] * 25})
    assert v.viable and v.motif == MOTIF_FLUX_NON_INFORME
    assert "n'est pas un edge net" in v.note, "un markout BRUT n'est pas un edge NET"
    # même viable, le verdict DOIT rappeler que notre carte ne voit qu'une PARTIE des comptes
    c = v.as_dict()["carte_borgne"]
    assert "borne basse" in c and "backstop" in c.lower()


def test_moins_de_20_evenements_ne_donne_AUCUN_verdict() -> None:
    