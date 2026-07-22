"""ARBITRAGE AU MAKER — l'entrée passive sauve-t-elle l'edge ? (étape 2/3, 22/07).

La loi `arb_dislocation_cout_all_in` gardait une porte de sortie : « à 9 bps (tout maker) les
mêmes trades survivent ». Ce module la MESURE. Résultat sur données réelles : sur les spreads
vivants, la capture de convergence (~3,4 bps) reste SOUS le coût maker (9 bps). Le refuge est
fermé — par la mesure, pas par un argument.
"""
from __future__ import annotations

import pytest

from hl_observer.funding import arb_maker_study as S


def _serie(points):
    return sorted((float(t), float(e)) for t, e in points)


# ─────────────── la sélection adverse d'une entrée passive ───────────────

def test_entree_passive_LARGE_rate_un_ecart_qui_converge_vite():
    """🔴 LE PIÈGE. On poste 2 bps PLUS LARGE ; si l'écart converge sans repasser par notre
    limite, on n'est JAMAIS rempli — on rate exactement les meilleurs trades."""
    # entre a 25, converge tout droit vers 0 sans jamais remonter a 27
    serie = _serie([(0, 25.0), (60, 18.0), (120, 9.0), (300, 2.0), (1800, 1.0)])
    r = S.etudier_un_signal(serie, 0, seuil_bps=19.0, offset_bps=2.0)
    assert r is not None
    assert r["maker_rempli"] is False, "l'ecart n'est jamais remonte a 27 -> pas de fill"
    assert r["capture_taker_bps"] > 0, "le taker, lui, aurait capture la convergence"


def test_entree_passive_AU_TOUCH_remplit_si_l_ecart_reste():
    """Poster au prix courant (offset 0) : rempli si l'écart y revient dans la fenêtre."""
    serie = _serie([(0, 25.0), (60, 25.5), (120, 10.0), (900, 2.0)])
    r = S.etudier_un_signal(serie, 0, seuil_bps=19.0, offset_bps=0.0)
    assert r["maker_rempli"] is True


def test_la_sortie_est_a_la_CONVERGENCE_pas_a_l_horizon():
    """Sans sortie à la convergence, la capture mesurée serait fausse (~0). La stratégie SORT
    quand l'écart s'est refermé (<= 3 bps), pas à la fin de l'horizon."""
    # converge a 2 bps a t=300, puis REDIVERGE a 20 a t=1500. La sortie doit capturer les 2 bps.
    serie = _serie([(0, 25.0), (300, 2.0), (1500, 20.0)])
    r = S.etudier_un_signal(serie, 0, seuil_bps=19.0, offset_bps=0.0)
    assert r["ecart_sortie_bps"] == pytest.approx(2.0), "sortie a la convergence, pas a t=1500"
    assert r["capture_taker_bps"] == pytest.approx(23.0)   # 25 - 2


def test_un_ecart_fige_ne_capture_RIEN():
    """MKR : 71 bps qui ne bouge pas. Entre a 71, sort a 71 (age max) -> capture 0."""
    serie = _serie([(0, 71.0), (600, 71.0), (1800, 71.0)])
    r = S.etudier_un_signal(serie, 0, seuil_bps=19.0, offset_bps=0.0)
    assert r["capture_taker_bps"] == pytest.approx(0.0)


def test_un_signal_sous_le_seuil_est_ignore():
    serie = _serie([(0, 10.0), (600, 2.0)])
    assert S.etudier_un_signal(serie, 0, seuil_bps=19.0) is None


def test_pas_de_chemin_de_sortie_pas_de_mesure():
    serie = _serie([(0, 25.0)])                        # rien apres l'entree
    assert S.etudier_un_signal(serie, 0, seuil_bps=19.0) is None


# ─────────────── l'étude complète, verdicts ───────────────

def test_le_cout_vient_de_la_source_unique():
    """Les coûts (9 / 23 bps) viennent de `arb_cout_all_in`, pas d'une constante locale."""
    r = S.etudier({"X": _serie([(0, 25.0), (300, 2.0)])}, seuil_bps=19.0)
    from hl_observer.funding.arb_cout_all_in import decomposer
    assert r["cout_maker_bps"] == decomposer(mode="TOUT_MAKER")["cout_aller_retour_bps"]
    assert r["cout_taker_bps"] == decomposer(mode="TOUT_TAKER")["cout_aller_retour_bps"]


def test_la_POPULATION_sous_le_cout_maker_ne_FERME_PAS_la_strategie():
    """🔴 22/07 (soir) — Flo : « ne ferme aucune porte ». Ce module mesure la POPULATION de
    signaux, pas le sous-ensemble que le moteur trade. Une population négative au maker ne dit
    RIEN de la stratégie gatée (réalisé réel +0,54 $, 13/15). Le verdict doit le DIRE, jamais
    conclure « réfuté »."""
    serie = _serie([(0, 25.0), (60, 25.5), (600, 22.0), (1800, 22.0)])
    r = S.etudier({"A": serie, "B": serie, "C": serie}, seuil_bps=19.0, offset_bps=0.0)
    assert r["maker_remplis"] > 0
    assert r["capture_maker_moyenne_bps"] < 9.0
    assert r["pnl_maker_usd_sur_remplis"] < 0
    assert "POPULATION" in r["verdict"], "on parle de la population, pas de la strategie"
    assert "porte" in r["verdict"].lower() and "borne" in r["verdict"].lower()
    assert "refut" not in r["verdict"].lower(), "on ne ferme AUCUNE porte"


def test_une_convergence_forte_au_maker_est_un_signal_POSITIF():
    """Le module n'est pas biaisé au négatif : une vraie grosse convergence passe positif."""
    serie = _serie([(0, 40.0), (60, 40.5), (600, 2.0), (1800, 2.0)])   # capture ~38 bps
    r = S.etudier({"A": serie}, seuil_bps=19.0, offset_bps=0.0)
    assert r["pnl_maker_usd_sur_remplis"] > 0 and "positive" in r["verdict"].lower()


def test_aucun_signal_ne_LEVE_pas():
    r = S.etudier({}, seuil_bps=19.0)
    assert r["signaux"] == 0 and "rien a mesurer" in r["verdict"]
    assert r["real_execution"] is False


def test_les_valeurs_illisibles_sont_ignorees():
    r = S.etudier({"X": [(0.0, 25.0), ("x", 5.0), (300.0, float("nan"))]}, seuil_bps=19.0)
    assert isinstance(r["signaux"], int)
