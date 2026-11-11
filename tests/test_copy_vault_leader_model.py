"""Modèle de sélection des leaders : il apprend un effet réel, n'invente rien sur du bruit, ne voit jamais le futur."""
from __future__ import annotations

import numpy as np

from hl_observer.backtesting import copy_vault_leader_model as M
from hl_observer.backtesting import copy_vault_persistence as P

DAY = 86_400_000
SEMAINE = 7 * DAY
W0 = (1_780_000_000_000 // SEMAINE + 1) * SEMAINE


def _courbes(n_vaults=50, semaines=110, *, effet=0.0, seed=3):
    """Courbes hebdomadaires. ``effet`` < 0 : le rendement suivant s'oppose au précédent (retour à la moyenne)."""
    rng = np.random.default_rng(seed)
    courbes = {}
    for i in range(n_vaults):
        valeur, pnl, precedent, points = 100_000.0, 0.0, 0.0, []
        for j in range(semaines + 1):
            points.append((W0 + j * SEMAINE, valeur, pnl))
            rendement = effet * precedent + rng.normal(0.0, 0.03)
            gain = valeur * rendement
            valeur, pnl, precedent = valeur + gain, pnl + gain, rendement
        courbes[f"0x{i:040x}"] = points
    return courbes


def _persistance():
    return P.PersistenceConfig(bootstrap_samples=300, permutation_samples=300)


def test_le_modele_apprend_un_retour_a_la_moyenne_sans_qu_on_lui_donne_le_signe():
    etude = M.run_leader_model_study(_courbes(effet=-0.5), turnover_per_day={}, persistence=_persistance())
    resume = etude["summary"]
    assert resume["dates"] >= 60 and resume["ic_intervalle"][0] > 0          # classement juste hors apprentissage
    assert etude["coefficients_moyens"]["rendement_1"] < 0                   # signe APPRIS : après une hausse, baisse
    assert etude["stabilite_du_signe"]["rendement_1"] > 0.95
    # rotation inconnue : le net de réplication reste inconnu, donc pas de verdict « prometteur »
    assert resume["tete_nette_bps_jour"] is None and etude["verdict"]["status"] == "MORE_DATA"
    lents = {f"0x{i:040x}": 0.01 for i in range(50)}
    avec_cout = M.run_leader_model_study(_courbes(effet=-0.5), turnover_per_day=lents, persistence=_persistance())
    assert avec_cout["verdict"]["status"] == "PROMISING" and avec_cout["economically_proven"] is False


def test_sur_du_bruit_pur_le_modele_ne_trouve_rien():
    etude = M.run_leader_model_study(_courbes(effet=0.0, seed=9), turnover_per_day={}, persistence=_persistance())
    assert etude["verdict"]["status"] in {"REJECTED", "MORE_DATA"}
    assert abs(etude["summary"]["ic_moyen"]) < 0.06


def test_les_notes_d_une_date_n_utilisent_aucune_donnee_de_cette_date_ni_d_apres():
    """Métamorphique : truquer tout ce qui se passe à partir de la date notée ne change aucune note."""
    panel = M.build_panel(_courbes(n_vaults=30, semaines=60, effet=-0.3), period_days=7)
    notes, _ = M.walk_forward_model(panel)
    cible = sorted(notes)[5]
    truque = {**panel, "ret": panel["ret"].copy(), "flux": panel["flux"].copy()}
    truque["ret"][:, cible:] = 9.0
    truque["flux"][:, cible:] = 9.0
    notes_truquees, _ = M.walk_forward_model(truque)
    np.testing.assert_array_equal(notes_truquees[cible], notes[cible])
    X, _ = M.features_at(panel, cible)
    X_truque, _ = M.features_at(truque, cible)
    np.testing.assert_array_equal(X, X_truque)
    # et la date suivante, elle, a bien appris la période truquée (le test détecte une vraie dépendance)
    assert not np.array_equal(notes_truquees[cible + 1], notes[cible + 1], equal_nan=True)


def test_pas_assez_d_historique_pas_de_note():
    court = M.run_leader_model_study(_courbes(n_vaults=30, semaines=15), turnover_per_day={})
    assert court["summary"]["dates"] == 0 and court["verdict"]["status"] == "MORE_DATA"
    assert M.run_leader_model_study({}, turnover_per_day={})["verdict"]["status"] == "MORE_DATA"


def test_un_vault_sans_ses_quatre_dernieres_periodes_n_est_pas_note():
    panel = M.build_panel(_courbes(n_vaults=12, semaines=30), period_days=7)
    panel["ret"][0, 20] = np.nan                       # un trou dans l'historique récent du vault 0
    _, notables = M.features_at(panel, 22)
    assert not notables[0] and notables[1:].all()
    _, plus_tard = M.features_at(panel, 26)            # le trou est sorti de la fenêtre des 4 dernières
    assert plus_tard[0]
