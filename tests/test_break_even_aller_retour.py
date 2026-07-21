"""LE BREAK-EVEN DOIT INCLURE LA SORTIE (21/07) — idée #1 des 15.

LE DÉFAUT, MESURÉ
-----------------
`evaluer_carry_neutre` cherchait combien d'heures de funding remboursent le **coût d'entrée**.
Le coût de **fermeture** (11 bps maker, 2 jambes) n'y entrait pas. Au plancher protocolaire
(0,125 bps/h) ces 11 bps valent **88 HEURES** de portage jamais comptées.

Conséquence : la porte du feeder à 235 h laissait passer des positions dont le vrai
break-even atteignait 323 h — pour un âge max de 336 h. Sur nos 12 positions vivantes,
**4 coins ne pouvaient PAS s'amortir avant leur revalidation forcée**. Pas des paris
incertains : des perdants garantis à l'ouverture.

Une position ne rembourse pas quand elle a payé son entrée. Elle rembourse quand elle peut
**SORTIR sans perte**.
"""
from __future__ import annotations

import pytest

from hl_observer.funding.delta_neutral_carry import COUT_MAKER_2_JAMBES_BPS, evaluer_carry_neutre

#: le plancher protocolaire d'Hyperliquid — le régime dans lequel on vit
PLANCHER = 0.125


def _eval(funding=PLANCHER, base=0.0, liq=400_000.0, lev=2.0, pire=0.05):
    return evaluer_carry_neutre(coin="X", funding_bps_h=funding, base_bps=base,
                                liquidite_spot_usd=liq, maker=True, levier_max=10.0,
                                marge_ratio=round(1.0 / lev, 6),
                                pire_hausse_observee=pire)


# ------------------------------------------------------------------ le cœur du correctif

def test_le_break_even_couvre_l_ALLER_RETOUR_pas_seulement_l_entree():
    """Au plancher, la sortie (11 bps) vaut 88 h. Le break-even doit les contenir."""
    v = _eval()
    assert v.heures_pour_rentabiliser is not None
    heures_entree_seule = v.cout_entree_bps / PLANCHER
    assert v.heures_pour_rentabiliser >= heures_entree_seule + 80, (
        "le break-even ne couvre pas la sortie : %.0f h pour une entrée à %.0f h"
        % (v.heures_pour_rentabiliser, heures_entree_seule))


def test_les_88_heures_manquantes_valent_bien_le_cout_de_sortie():
    attendu = COUT_MAKER_2_JAMBES_BPS / PLANCHER
    assert 85 <= attendu <= 92, "l'ordre de grandeur des 88 h a changé : %.0f" % attendu


def test_un_funding_plus_eleve_rembourse_TOUJOURS_plus_vite():
    """Monotonie. On ne teste PAS une formule linéaire : le modèle applique une décroissance
    de persistance (un funding élevé ne tient pas). C'est lui qui a raison — extrapoler
    linéairement un taux qui s'évapore serait exactement le biais du ×30 du 19/07."""
    heures = [_eval(funding=f).heures_pour_rentabiliser for f in (0.125, 0.25, 0.5, 1.0, 2.0)]
    assert all(h is not None for h in heures)
    assert heures == sorted(heures, reverse=True), heures


def test_un_coin_qui_ne_peut_PAS_s_amortir_avant_l_age_max_est_visible():
    """AVAX réel (21/07) : coût A/R 72,4 bps au plancher -> 579 h, pour un âge max de 336 h.
    Le break-even doit le DIRE, pas l'arrondir vers le bas."""
    from hl_observer.funding.carry_position_lifecycle import AGE_MAX_H_DEFAUT
    v = _eval(base=-55.0)                      # base très négative = coût d'entrée énorme
    assert v.heures_pour_rentabiliser is None or v.heures_pour_rentabiliser > AGE_MAX_H_DEFAUT / 2


def test_le_correctif_ne_condamne_pas_TOUT():
    """Contrôle positif : au plancher, un coût d'entrée normal reste amortissable dans la
    vie d'une position — sinon le correctif fermerait la stratégie, pas un défaut."""
    from hl_observer.funding.carry_position_lifecycle import AGE_MAX_H_DEFAUT
    v = _eval(base=3.0)                      # base légèrement favorable, coût d'entrée réduit
    assert v.heures_pour_rentabiliser is not None
    assert v.heures_pour_rentabiliser < AGE_MAX_H_DEFAUT


# ------------------------------------------------------------------ la porte, rendue cohérente

def test_le_plafond_de_break_even_est_lie_a_l_AGE_MAX_pas_libre():
    """Une position vit 336 h. Un break-even de 235 h ne laisse que 101 h (30 %) à GAGNER :
    on immobilise 14 jours pour 4 jours de rendement. Le plafond doit être la MOITIÉ."""
    import importlib.util as _u
    from pathlib import Path as _P

    racine = _P(__file__).resolve().parents[1]
    spec = _u.spec_from_file_location("feeder", racine / "tools" / "ecrire_carry_spot_inputs.py")
    m = _u.module_from_spec(spec)
    spec.loader.exec_module(m)

    from hl_observer.funding.carry_position_lifecycle import AGE_MAX_H_DEFAUT
    # le plafond est DÉRIVÉ : le funding sur la vie entière doit couvrir k× l'aller-retour.
    assert m.PLAFOND_COHERENT_H == pytest.approx(
        m._plafond_break_even(AGE_MAX_H_DEFAUT), abs=1.0)
    assert 0 < m.PLAFOND_COHERENT_H < AGE_MAX_H_DEFAUT, (
        "un plafond nul tue la stratégie ; un plafond = la vie entière n'exige aucune marge")
    assert m.MAX_BREAK_EVEN_H <= m.PLAFOND_COHERENT_H, (
        "une variable d'environnement ne doit pas pouvoir rendre la porte incohérente")


def test_la_marge_de_securite_est_SUPERIEURE_a_1_et_declaree():
    """k > 1 parce que le COÛT est certain et payé d'avance, le REVENU est incertain.
    Exiger l'égalité (k=1) reviendrait à parier que le funding tient exactement jusqu'au bout."""
    import importlib.util as _u
    from pathlib import Path as _P
    racine = _P(__file__).resolve().parents[1]
    spec = _u.spec_from_file_location("feeder5", racine / "tools" / "ecrire_carry_spot_inputs.py")
    m = _u.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.MARGE_SECURITE_REVENU > 1.0


def test_une_marge_PLUS_EXIGEANTE_donne_un_plafond_PLUS_BAS():
    """Monotonie : le plafond doit répondre à la marge, sinon il ne la respecte pas."""
    import importlib.util as _u
    from pathlib import Path as _P
    racine = _P(__file__).resolve().parents[1]
    spec = _u.spec_from_file_location("feeder6", racine / "tools" / "ecrire_carry_spot_inputs.py")
    m = _u.module_from_spec(spec)
    spec.loader.exec_module(m)
    plafonds = [m._plafond_break_even(336.0, k=k) for k in (1.25, 1.5, 2.0)]
    assert plafonds == sorted(plafonds, reverse=True), plafonds


def test_un_funding_qui_ne_couvre_JAMAIS_le_cout_donne_un_plafond_NUL():
    """Si même la vie entière ne rembourse pas k× l'aller-retour, aucun break-even n'est
    acceptable. Le plafond doit valoir 0, pas une valeur de repli complaisante."""
    import importlib.util as _u
    from pathlib import Path as _P
    racine = _P(__file__).resolve().parents[1]
    spec = _u.spec_from_file_location("feeder7", racine / "tools" / "ecrire_carry_spot_inputs.py")
    m = _u.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m._plafond_break_even(336.0, funding_bps_h=0.001) == 0.0


def test_une_env_trop_permissive_est_ECRETEE(monkeypatch):
    """Le 235 h du launcher valait en réalité 323 h une fois la sortie comptée. Une valeur
    d'environnement ne peut plus ouvrir la porte au-delà du cohérent."""
    import importlib.util as _u
    from pathlib import Path as _P

    monkeypatch.setenv("HYPERSMART_CARRY_MAX_BREAK_EVEN_H", "999")
    racine = _P(__file__).resolve().parents[1]
    spec = _u.spec_from_file_location("feeder2", racine / "tools" / "ecrire_carry_spot_inputs.py")
    m = _u.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.MAX_BREAK_EVEN_H == m.PLAFOND_COHERENT_H


# ------------------------------------------------------------------ idée #3 : le tri

def test_a_net_QUASI_EGAL_le_classement_prefere_qui_rembourse_VITE():
    """Le net est un gain MOYEN sur 30 j : il dilue un coût d'entrée one-shot. Mesuré le
    21/07 : XPL 148 h contre AVAX 567 h, pour des nets voisins."""
    import importlib.util as _u
    from pathlib import Path as _P

    racine = _P(__file__).resolve().parents[1]
    spec = _u.spec_from_file_location("feeder3", racine / "tools" / "ecrire_carry_spot_inputs.py")
    m = _u.module_from_spec(spec)
    spec.loader.exec_module(m)

    lent = ("AVAX", {}, 567.0, 1.164, 0.0)
    rapide = ("XPL", {}, 148.0, 1.161, 0.0)          # net QUASI identique, 4× plus rapide
    assert [x[0] for x in m.classer_viables([lent, rapide])] == ["XPL", "AVAX"]


def test_un_net_FRANCHEMENT_superieur_reste_prioritaire():
    """Le break-even départage à net voisin — il ne renverse pas un vrai écart de rendement."""
    import importlib.util as _u
    from pathlib import Path as _P

    racine = _P(__file__).resolve().parents[1]
    spec = _u.spec_from_file_location("feeder4", racine / "tools" / "ecrire_carry_spot_inputs.py")
    m = _u.module_from_spec(spec)
    spec.loader.exec_module(m)

    riche_lent = ("BTC", {}, 300.0, 2.22, 0.0)
    pauvre_rapide = ("XPL", {}, 100.0, 1.16, 0.0)
    assert [x[0] for x in m.classer_viables([pauvre_rapide, riche_lent])] == ["BTC", "XPL"]
