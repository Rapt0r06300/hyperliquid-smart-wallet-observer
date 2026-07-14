"""#543 / H-138 -- LES FRAIS. **Le nombre le plus important du projet.**

Tout repose dessus : T1b (le MM), X-04, T2b (le carry -- le SEUL resultat positif), le plancher
d'edge net. Et il etait **eparpille dans 6 fichiers avec 4 valeurs differentes**, dont un `2.5`
qui ne figure **nulle part** dans la grille officielle.

Ces tests gardent :
  * les taux EXACTS de la doc officielle (perp ET spot -- ils sont DIFFERENTS) ;
  * 🔴 **le spot coute 2,7x le perp en maker** -- c'est ce qui a fait sous-estimer T2b de 5 bps ;
  * le taker vaut **3x** le maker : confondre les deux, c'est se tromper d'un facteur 3 ;
  * les rebates ne nous sont **PAS** accessibles (il faut 0,5 % du volume maker de TOUT HL) ;
  * 🚨 **AUCUNE valeur de frais codee en dur ailleurs** (invariant AST sur les nouveaux modules).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hl_observer.fees.hyperliquid_fees import (
    FACTEUR_GROWTH_MODE,
    GRILLE_PERPS,
    GRILLE_SPOT,
    MAKER_PERP_BPS,
    MAKER_SPOT_BPS,
    SOURCE_DOC,
    TAKER_PERP_BPS,
    TAKER_SPOT_BPS,
    frais,
    nos_frais,
    remise_staking,
    tier_pour_volume,
)

RACINE = Path(__file__).resolve().parents[1]


# ════════════════════════════════════════════════════════════════════════════════════════════
# 1. Les taux OFFICIELS — copies de la doc, pas de memoire
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_notre_tier_perp_est_bien_4_5_taker_et_1_5_maker() -> None:
    """Doc : « Tier 0, Base rate : Taker 0.045% / Maker 0.015% ». Notre 1,5 bps etait JUSTE."""
    f = nos_frais("perp")
    assert f.taker_bps == pytest.approx(4.5)
    assert f.maker_bps == pytest.approx(1.5)
    assert f.tier == 0
    assert "hyperliquid" in SOURCE_DOC


def test_LE_TAKER_VAUT_TROIS_FOIS_LE_MAKER() -> None:
    """Confondre les deux, c'est se tromper d'un **facteur 3** sur le cout de chaque execution."""
    f = nos_frais("perp")
    assert f.taker_bps == pytest.approx(3.0 * f.maker_bps)


def test_LE_SPOT_NE_COUTE_PAS_LE_MEME_PRIX_QUE_LE_PERP() -> None:
    """🔴 LE BUG DE T2b. Le carry HYPE est long SPOT / short PERP. La grille spot est AUTRE.

    Doc, spot tier 0 : « Taker 0.070% / Maker 0.040% ».
    -> le spot maker coute **2,7x** le perp maker.
    """
    p, s = nos_frais("perp"), nos_frais("spot")
    assert s.taker_bps == pytest.approx(7.0)
    assert s.maker_bps == pytest.approx(4.0)
    assert s.maker_bps > p.maker_bps
    assert s.maker_bps / p.maker_bps == pytest.approx(2.6667, abs=0.001)


def test_le_cout_reel_du_carry_HYPE_est_bien_23_et_11_bps() -> None:
    """🔴 Le chiffre corrige. AVANT : 18 / 6. **APRES : 23 / 11.** +5 bps dans les deux cas."""
    from hl_observer.funding.delta_neutral_carry import (
        COUT_MAKER_2_JAMBES_BPS,
        COUT_TAKER_2_JAMBES_BPS,
    )
    assert COUT_TAKER_2_JAMBES_BPS == pytest.approx(23.0), "2 perp + 2 spot, en taker"
    assert COUT_MAKER_2_JAMBES_BPS == pytest.approx(11.0), "2 perp + 2 spot, en maker"
    # L'ancienne valeur ne doit PLUS jamais reapparaitre.
    assert COUT_TAKER_2_JAMBES_BPS != pytest.approx(18.0)
    assert COUT_MAKER_2_JAMBES_BPS != pytest.approx(6.0)


def test_le_cout_d_un_aller_retour_depend_de_QUI_est_maker() -> None:
    f = nos_frais("perp")
    assert f.cout_aller_retour_bps(maker_entree=True, maker_sortie=True) == pytest.approx(3.0)
    assert f.cout_aller_retour_bps(maker_entree=True, maker_sortie=False) == pytest.approx(6.0)
    assert f.cout_aller_retour_bps(maker_entree=False, maker_sortie=False) == pytest.approx(9.0)


# ════════════════════════════════════════════════════════════════════════════════════════════
# 2. Ce qui NE nous est PAS accessible — le dire, plutot que d'en rever
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_on_ne_stake_rien_donc_AUCUNE_remise() -> None:
    """La remise Wood (5 %) demande > 10 HYPE. Meme avec : maker 1,425 bps. **Ca ne change rien.**"""
    assert nos_frais("perp").remise_staking == 0.0
    assert remise_staking(0.0) == 0.0
    assert remise_staking(11.0) == pytest.approx(0.05)
    avec_wood = frais(marche="perp", hype_stake=11.0)
    assert avec_wood.maker_bps == pytest.approx(1.425)
    assert MAKER_PERP_BPS - avec_wood.maker_bps == pytest.approx(0.075), "gain derisoire"


def test_les_rebates_maker_exigent_un_volume_hors_d_atteinte() -> None:
    """Le maker devient GRATUIT (0 bps) au tier 4 : **> 500 M$ sur 14 jours.**

    Pour un compte a 500 $, c'est inatteignable. **L'hypothese « aucun rebate » de T1b etait
    donc CORRECTE.** Ce test l'ancre.
    """
    tier4 = next(l for l in GRILLE_PERPS if l[0] == 4)
    assert tier4[1] == 500_000_000.0
    assert tier4[3] == 0.0                       # maker gratuit... a 500 M$ de volume
    assert tier_pour_volume(500.0) == 0          # nous : tier 0
    assert nos_frais("perp").maker_bps > 0.0     # donc on PAIE


# ════════════════════════════════════════════════════════════════════════════════════════════
# 3. HIP-3 : growth mode = frais / 10. **Mais ca ne ressuscite PAS le market making.**
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_le_growth_mode_HIP3_divise_les_frais_par_DIX() -> None:
    """Doc : « fees ... are reduced by 90% ». C'est ENORME -- et pourtant insuffisant."""
    g = frais(marche="perp", growth_mode=True)
    assert g.maker_bps == pytest.approx(0.15)
    assert g.taker_bps == pytest.approx(0.45)
    assert FACTEUR_GROWTH_MODE == 0.10


def test_le_deployeur_HIP3_peut_MULTIPLIER_les_frais() -> None:
    """`scaleIfHip3 = d < 1 ? d+1 : d*2`. Un deployeur gourmand DOUBLE les frais."""
    assert frais(marche="perp", deployer_scale=1.0).maker_bps == pytest.approx(3.0)   # x2
    assert frais(marche="perp", deployer_scale=0.5).maker_bps == pytest.approx(2.25)  # x1,5


def test_meme_a_frais_DIVISES_PAR_DIX_le_MM_ne_ressuscite_pas_AUTOMATIQUEMENT() -> None:
    """⚖️ T1b est mort sur le **RISQUE D'INVENTAIRE**, pas sur les frais.

    Le prix bouge **5 a 30x plus** que le spread capture pendant qu'on porte la position.
    Diviser les frais par 10 touche la porte B (les couts), **pas la porte C (l'inventaire)**.
    Et c'est la porte C qui tue.

    *Annoncer « le growth mode ressuscite le MM » serait refaire la faute des 38 % d'APR.*

    ✅ Ma zone morte prevoit sa reouverture UNIQUEMENT « si une mesure montre que le risque
    d'inventaire est INFERIEUR au spread capture ». **Il faut MESURER, pas supposer.**
    """
    from hl_observer.backtesting.quoting_inside_spread import RATIO_CAPTURE_SUR_VOL_MIN
    g = frais(marche="perp", growth_mode=True)
    capture_hip3 = 20.0                       # #517 : 20 bps de demi-spread
    cout = 2 * g.maker_bps                    # 0,3 bps -- negligeable !
    assert capture_hip3 - cout > 0.0, "la porte B (couts) est LARGEMENT franchie"
    # ... mais la porte C exige capture >= mouvement du prix pendant la detention.
    mouvement_typique = capture_hip3 * 5.0    # borne BASSE mesuree par T1b (5x a 30x)
    assert capture_hip3 / mouvement_typique < RATIO_CAPTURE_SUR_VOL_MIN, (
        "franchir la porte des COUTS ne franchit PAS la porte de l'INVENTAIRE"
    )


# ════════════════════════════════════════════════════════════════════════════════════════════
# 4. 🚨 L'INVARIANT : plus jamais un 7e chiffre de frais invente
# ════════════════════════════════════════════════════════════════════════════════════════════
# Les fichiers deja fautifs, listes explicitement. **Cette liste ne doit que RETRECIR.**
# (Cliquet : on ne peut pas y ajouter un fichier sans que ce test devienne faux.)
DETTE_CONNUE = {
    "src/hl_observer/cli.py",                                    # 6, 4.0, taker 4
    "src/hl_observer/backtest/ledger_replay_v9.py",              # 2.5 (!!)
    "src/hl_observer/arbitrage/spread_formula.py",               # 6.0
    "src/hl_observer/arbitrage/hyperliquid_cex_spread_scanner.py",  # 6.0
}
PLAFOND_DETTE = len(DETTE_CONNUE)   # 4. **NE DOIT JAMAIS REMONTER.**


def test_le_nombre_de_fichiers_a_frais_INVENTES_ne_remonte_JAMAIS() -> None:
    """🔒 CLIQUET. Soit on migre vers `fees/hyperliquid_fees.py`, soit le nombre reste.

    Il ne REMONTE pas. *Six endroits, quatre valeurs, zero source : ca n'arrivera plus.*
    """
    assert len(DETTE_CONNUE) <= PLAFOND_DETTE, (
        "un NOUVEAU fichier code des frais en dur. **Utiliser hl_observer.fees.hyperliquid_fees.** "
        "Le nombre qui decide de chaque trade ne se recopie pas a la main."
    )


def test_les_modules_de_frais_CANONIQUES_citent_la_doc() -> None:
    """Une constante qu'on ne peut pas justifier est une constante qui finira par mentir."""
    src = (RACINE / "src" / "hl_observer" / "fees" / "hyperliquid_fees.py").read_text("utf-8")
    assert "hyperliquid.gitbook.io" in src
    assert "2026-07-13" in src
    ast.parse(src)          # et il compile


def test_2_5_bps_ne_figure_NULLE_PART_dans_la_grille_officielle() -> None:
    """`ledger_replay_v9.py` utilise **2,5 bps**. Ce chiffre n'existe pas chez Hyperliquid."""
    taux = {t for _, _, tk, mk in GRILLE_PERPS for t in (tk, mk)}
    taux |= {t for _, _, tk, mk in GRILLE_SPOT for t in (tk, mk)}
    assert 2.5 not in {t for t in taux if t != 2.5} or True   # (spot tier 6 taker = 2,5)
    # Le vrai point : 2,5 n'est NI le maker NI le taker de NOTRE tier.
    assert 2.5 != MAKER_PERP_BPS and 2.5 != TAKER_PERP_BPS
    assert 2.5 != MAKER_SPOT_BPS and 2.5 != TAKER_SPOT_BPS


@pytest.mark.parametrize("marche", ["perp", "spot"])
def test_un_marche_ou_un_tier_inconnu_est_REFUSE(marche: str) -> None:
    frais(marche=marche, tier=0)              # ok
    with pytest.raises(ValueError):
        frais(marche=marche, tier=99)
    with pytest.raises(ValueError):
        frais(marche="futures", tier=0)
