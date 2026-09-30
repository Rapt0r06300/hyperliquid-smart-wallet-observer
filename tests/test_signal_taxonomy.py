"""Q3 + Z1 -- LA ZONE MORTE EST DANS LE CODE, PAS SEULEMENT DANS UN .MD.

Un document se contredit sans bruit. Un test, non.

Ces tests figent le resultat le plus important du projet : **le fill public d'un leader ne porte
aucune information**, et la cause est mesuree (Q3, 38 388 signaux, panel strict). Ils garantissent
qu'on ne pourra pas, dans six mois, reconstruire une enieme variante du meme signal vide en
croyant innover.

Ils figent AUSSI la zone morte Z1 : **la latence n'est pas le probleme.** On ne peut pas etre
« plus rapide » a capturer un mouvement de +0,08 bps qui n'existe pas.

Aucun ordre reel.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.signals.signal_taxonomy import (
    CARRY_STRUCTUREL,
    DISCRETIONNAIRE_PUBLIC,
    FAMILLES,
    FLUX_FORCE,
    MORT_PROUVE,
    PRE_EXECUTION,
    REFUS_FAMILLE_INCONNUE,
    REFUS_ZONE_MORTE,
    REGISTRE,
    VALIDE_PARTIEL,
    est_une_zone_morte,
    famille_de,
    pistes_ouvertes,
    verdict_du_signal,
    zones_mortes,
)

COUT_ALLER_RETOUR_BPS = 12.0


# ====================================================== LA ZONE MORTE


def test_le_copy_trading_est_une_ZONE_MORTE_PROUVEE():
    """LE resultat du projet. Trois preuves independantes + une cause mesuree."""
    assert est_une_zone_morte(DISCRETIONNAIRE_PUBLIC)
    autorise, raison = verdict_du_signal(DISCRETIONNAIRE_PUBLIC)
    assert autorise is False
    assert raison == REFUS_ZONE_MORTE
    assert zones_mortes() == (DISCRETIONNAIRE_PUBLIC,)


def test_la_zone_morte_porte_sa_PREUVE_pas_une_opinion():
    """Une zone morte sans preuve chiffree n'est pas une zone morte -- c'est un abandon."""
    p = REGISTRE[DISCRETIONNAIRE_PUBLIC].preuve
    for chiffre in ("24 133", "-7,97", "23 358", "38 388", "-7,75", "+0,62"):
        assert chiffre in p, f"la preuve a perdu son chiffre : {chiffre}"


def test_une_famille_INCONNUE_est_refusee_pas_supposee_vivante():
    """Deny-by-default. « signal_genial_v2 » n'a pas droit a une exploration par defaut."""
    autorise, raison = verdict_du_signal("MON_SUPER_SIGNAL")
    assert autorise is False
    assert raison == REFUS_FAMILLE_INCONNUE
    assert famille_de("MON_SUPER_SIGNAL") == ""
    assert famille_de(None) == ""


def test_les_autres_familles_restent_OUVERTES():
    """Une zone morte ne doit PAS fermer les portes voisines. Elles ne sont pas mortes -- elles
    ne sont pas MESUREES. C'est une difference de nature."""
    for f in (PRE_EXECUTION, FLUX_FORCE, CARRY_STRUCTUREL):
        assert not est_une_zone_morte(f)
        autorise, _ = verdict_du_signal(f)
        assert autorise is True
    assert set(pistes_ouvertes()) == {PRE_EXECUTION, FLUX_FORCE, CARRY_STRUCTUREL}


def test_le_carry_est_le_SEUL_valide_et_il_est_PARTIEL():
    """Ne jamais promouvoir T2 en « ca marche ». Un marche, un mois, un risque non modelise."""
    f = REGISTRE[CARRY_STRUCTUREL]
    assert f.verdict == VALIDE_PARTIEL
    assert "HYPE" in f.preuve
    assert "liquidee" in f.preuve or "liquidée" in f.preuve, (
        "le risque de liquidation de la jambe short DOIT rester ecrit : c'est le trou du carry"
    )


def test_toutes_les_familles_sont_au_registre():
    assert set(FAMILLES) == set(REGISTRE)


# ====================================================== Z1 : LA LATENCE N'EST PAS LE PROBLEME


def test_Z1_la_courbe_MESUREE_interdit_d_esperer_de_la_latence():
    """ZONE MORTE Z1. Fige la courbe reelle : on ne peut pas etre « plus rapide » a capturer
    un mouvement qui n'existe pas.

    Si ce test echoue un jour parce que le markout a +5 s depasse le cout, ce ne sera PAS une
    regression -- ce sera une nouvelle. A re-valider avant d'y croire.
    """
    p = Path(__file__).resolve().parents[1] / "data" / "reports" / "q3_avant_apres.json"
    if not p.is_file():
        pytest.skip("Q3 non mesure (Q3-AVANT-APRES.cmd)")

    d = json.loads(p.read_text(encoding="utf-8"))
    assert d.get("panel_strict") is True, (
        "sans panel strict, la courbe compare des POPULATIONS differentes -- elle ne prouve rien"
    )
    courbe = d["courbe"]

    # APRES le signal : AUCUN horizon ne couvre les couts. Pas meme le plus court.
    for h in ("5.0", "10.0", "30.0", "60.0", "120.0", "300.0"):
        if h not in courbe:
            continue
        m = float(courbe[h]["markout_moyen_bps"])
        assert m - COUT_ALLER_RETOUR_BPS < 0.0, (
            f"a +{h}s le markout ({m:+.2f} bps) couvrirait les couts. Ce n'est pas une panne : "
            "c'est une piste. A re-valider (bootstrap, autre periode) avant d'y croire."
        )

    # Et le plus COURT horizon n'est pas meilleur que le plus long : la latence ne paie pas.
    if "5.0" in courbe and "300.0" in courbe:
        court = float(courbe["5.0"]["markout_moyen_bps"])
        assert court < COUT_ALLER_RETOUR_BPS, "etre plus rapide ne suffirait toujours pas"


def test_Q3_le_prix_court_CONTRE_le_trade_AVANT_le_fill():
    """LA CAUSE. Le leader achete la baisse et vend la hausse -- il n'est pas informe.

    C'est ce qui distingue « on arrive trop tard » de « il n'y a rien ». Les deux ferment la
    porte, mais ils n'impliquent PAS les memes suites :
      - trop tard  -> chercher le flux AVANT execution.
      - rien a voir -> chercher un flux FORCE, pas un flux qu'on espere malin.
    """
    p = Path(__file__).resolve().parents[1] / "data" / "reports" / "q3_avant_apres.json"
    if not p.is_file():
        pytest.skip("Q3 non mesure")

    d = json.loads(p.read_text(encoding="utf-8"))
    courbe = d["courbe"]
    if "-300.0" not in courbe:
        pytest.skip("horizon -300s absent")

    avant = float(courbe["-300.0"]["markout_moyen_bps"])
    borne = courbe["-300.0"].get("borne_basse_bps")
    assert avant < 0.0, (
        "le prix aurait DEJA couru dans le sens du trade avant le fill. Ce serait un tout autre "
        "diagnostic (« trop tard » et non « rien a attraper ») -- et une tout autre suite."
    )
    assert borne is not None and float(borne) < 0.0, "resultat non significatif"
