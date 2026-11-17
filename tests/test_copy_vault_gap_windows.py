"""UN SEUL TROU NE DOIT PAS FERMER UNE ÉPOQUE ENTIÈRE — mais un trou INCONNU doit tout fermer.

D'OÙ VIENNENT CES TESTS (bloqueur P0 confirmé le 16/11/2026). `copy_vault_book_loader` n'acceptait
une époque propre que si `input_rotations + checkpoints_expired + pending_overflow_rejected == 0`.
Ces compteurs sont CUMULATIFS sur tout le run : la campagne active comptait 43 expirations et une
rotation, donc 100 % des checkpoints du run étaient non certifiables — y compris les milliers de
lignes écrites dans des minutes sans aucun incident. Zéro trade exécutable, donc zéro preuve.

La spec autorise des trous globaux à condition de les mettre en quarantaine et de ne certifier que
des intervalles `EXECUTION_REPLAY_SAFE`. Ces tests verrouillent les deux moitiés de ce contrat :
on segmente, ET on ferme dès que la preuve d'un trou manque.

Pur : aucun fichier, aucun réseau, aucune horloge.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import copy_vault_gap_windows as G  # noqa: E402


def _etat(**kw):
    """Un état d'écrivain COHÉRENT par défaut : le journal explique exactement les compteurs."""
    base = {
        "gap_windows_schema": G.SCHEMA_FENETRES,
        "gap_windows_dropped": 0,
        "clean_epoch_ms": 1_000_000,
        "gap_windows": [],
        "counters": {"input_rotations": 0, "checkpoints_expired": 0, "pending_overflow_rejected": 0},
    }
    base.update(kw)
    return base


# ─────────────── la segmentation ───────────────
def test_un_trou_isole_laisse_DEUX_intervalles_surs():
    trous = [G.fenetre(G.TROU_EXPIRATION, debut_ms=10_000, fin_ms=12_000)]
    surs = G.intervalles_surs(debut_ms=0, fin_ms=30_000, fenetres=trous)
    assert surs == [(0, 10_000 - G.MARGE_MS), (12_000 + G.MARGE_MS, 30_000)], (
        "une expiration de 2 s ne doit pas invalider les 28 autres secondes")


def test_des_trous_qui_se_recouvrent_sont_FUSIONNES_pas_additionnes():
    trous = [G.fenetre(G.TROU_EXPIRATION, debut_ms=1_000, fin_ms=5_000),
             G.fenetre(G.TROU_ROTATION, debut_ms=4_000, fin_ms=9_000)]
    assert G.fusionner(trous) == [(1_000 - G.MARGE_MS, 9_000 + G.MARGE_MS)]


def test_un_trou_qui_couvre_tout_ne_laisse_RIEN():
    trous = [G.fenetre(G.TROU_ROTATION, debut_ms=0, fin_ms=60_000)]
    assert G.intervalles_surs(debut_ms=1_000, fin_ms=50_000, fenetres=trous) == []


def test_la_marge_de_garde_exclut_une_ligne_qui_touchait_le_bord_du_trou():
    """Horloge de réception et horloge d'écriture ne sont pas la même : on ne certifie pas le bord."""
    trous = [G.fenetre(G.TROU_EXPIRATION, debut_ms=10_000, fin_ms=10_000)]
    surs = G.intervalles_surs(debut_ms=0, fin_ms=20_000, fenetres=trous)
    assert G.est_sur(10_000 - G.MARGE_MS - 1, surs) is True
    assert G.est_sur(10_000 - 1, surs) is False, "le bord du trou n'est pas sûr"
    assert G.est_sur(10_000, surs) is False


def test_une_fenetre_a_l_envers_garde_son_ENVELOPPE_au_lieu_d_etre_ignoree():
    f = G.fenetre(G.TROU_ROTATION, debut_ms=9_000, fin_ms=3_000)
    assert (f["debut_ms"], f["fin_ms"]) == (3_000, 9_000), (
        "un incident n'a pas d'ordre ; perdre la fenetre serait perdre la preuve du trou")


def test_la_couverture_est_publiable_comme_denominateur():
    trous = [G.fenetre(G.TROU_EXPIRATION, debut_ms=10_000, fin_ms=12_000)]
    surs = G.intervalles_surs(debut_ms=0, fin_ms=30_000, fenetres=trous)
    assert G.couverture_ms(surs) == 30_000 - 2_000 - 2 * G.MARGE_MS


def test_un_horodatage_non_entier_n_est_JAMAIS_sur():
    surs = [(0, 10_000)]
    for mauvais in (None, "5000", 5000.0, True, -1, {}):
        assert G.est_sur(mauvais, surs) is False, f"{mauvais!r} ne doit pas passer pour un instant"


# ─────────────── le fail-closed : un trou inconnu ferme TOUT ───────────────
def test_un_etat_SANS_journal_de_fenetres_ne_certifie_RIEN():
    """C'est l'état de tout écrivain démarré avant ce code : aucune réparation rétroactive."""
    etat = {"clean_epoch_ms": 1_000, "counters": {"checkpoints_expired": 43, "input_rotations": 1,
                                                  "pending_overflow_rejected": 0}}
    intervalles, raison = G.intervalles_depuis_etat(etat, fin_ms=9_999_999)
    assert intervalles == [] and raison == "JOURNAL_DE_FENETRES_ABSENT"


def test_un_journal_INCOMPLET_ferme_la_porte_en_le_DISANT():
    """43 expirations comptées, 1 fenêtre publiée : les 42 autres sont des trous dont on ignore
    la position. Certifier ici serait certifier sur une preuve absente."""
    etat = _etat(
        gap_windows=[G.fenetre(G.TROU_EXPIRATION, debut_ms=2_000, fin_ms=3_000)],
        counters={"input_rotations": 0, "checkpoints_expired": 43, "pending_overflow_rejected": 0})
    intervalles, raison = G.intervalles_depuis_etat(etat, fin_ms=9_999_999)
    assert intervalles == []
    assert raison.startswith("FENETRES_INCOMPLETES:checkpoints_expired=43")


def test_une_fenetre_PERDUE_par_debordement_du_journal_ferme_tout():
    etat = _etat(gap_windows_dropped=3)
    intervalles, raison = G.intervalles_depuis_etat(etat, fin_ms=9_999_999)
    assert intervalles == [] and raison == "FENETRES_PERDUES:3"


def test_le_journal_borne_COMPTE_ses_pertes_au_lieu_de_tronquer_en_silence():
    etat = _etat()
    for i in range(G.MAX_FENETRES + 5):
        # des incidents DISJOINTS : ceux qui se touchent sont desormais un seul intervalle
        G.ajouter_fenetre(etat, G.fenetre(G.TROU_EXPIRATION, debut_ms=i * 10, fin_ms=i * 10 + 1))
    assert len(etat["gap_windows"]) == G.MAX_FENETRES
    assert etat["gap_windows_dropped"] == 5, (
        "tronquer sans le dire ferait croire a une epoque plus propre qu'elle ne l'est")


def test_un_batch_de_debordement_justifie_PLUSIEURS_unites_de_compteur():
    """`pending_overflow_rejected` s'incrémente de `len(additions)` : une fenêtre porte son `n`."""
    etat = _etat(
        gap_windows=[G.fenetre(G.TROU_DEBORDEMENT, debut_ms=5_000, fin_ms=6_000, n=7)],
        counters={"input_rotations": 0, "checkpoints_expired": 0, "pending_overflow_rejected": 7})
    coherent, raison = G.journal_coherent(etat)
    assert coherent is True and raison == "OK"


def test_un_compteur_invalide_ou_flottant_ferme_la_porte():
    for mauvais in (None, "3", 3.0, -1, True):
        etat = _etat(counters={"input_rotations": mauvais, "checkpoints_expired": 0,
                               "pending_overflow_rejected": 0})
        coherent, raison = G.journal_coherent(etat)
        assert coherent is False, f"compteur {mauvais!r} accepte"
        assert "COMPTEUR_INVALIDE" in raison or "FENETRES_INCOMPLETES" in raison


def test_une_epoque_propre_absente_ferme_la_porte():
    etat = _etat(clean_epoch_ms=0)
    intervalles, raison = G.intervalles_depuis_etat(etat, fin_ms=9_999)
    assert intervalles == [] and raison == "EPOQUE_PROPRE_ABSENTE"


def test_un_run_SANS_aucun_trou_est_sur_de_bout_en_bout():
    etat = _etat()
    intervalles, raison = G.intervalles_depuis_etat(etat, fin_ms=2_000_000)
    assert raison == "OK" and intervalles == [(1_000_000, 2_000_000)]


def test_une_nature_de_trou_inconnue_est_REFUSEE_a_l_ecriture():
    with pytest.raises(ValueError):
        G.fenetre("mystere", debut_ms=1, fin_ms=2)


def test_toutes_les_natures_ont_un_compteur_declare():
    assert set(G.COMPTEUR_PAR_NATURE) == set(G.NATURES), (
        "une nature sans compteur rendrait la reconciliation impossible")


# ─────────────── l'écrivain publie-t-il vraiment la fenêtre de chaque trou ? ───────────────
def _ecrivain(tmp_path, horloge):
    """Un compagnon réel, sur un dossier temporaire, sans réseau (fetch_book neutralisé)."""
    from hl_observer.collection.copy_vault_checkpoint_tail import CopyVaultCheckpointTail

    (tmp_path / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runtime" / "data" / "vault_fills_live.jsonl").write_text("", encoding="utf-8")
    return CopyVaultCheckpointTail(root=tmp_path, clock_ms=horloge, fetch_book=lambda coin: None)


def test_une_EXPIRATION_publie_sa_fenetre_de_la_cible_a_maintenant(tmp_path):
    horloge = {"t": 1_000_000}
    tail = _ecrivain(tmp_path, lambda: horloge["t"])
    tail.state["pending"] = [{"checkpoint_id": "cp-1", "target_wall_ms": 1_000_000,
                              "coin": "BTC", "stage": "REFERENCE", "metaorder_id": "m1"}]
    horloge["t"] = 1_000_000 + 60_000          # bien au-dela de MAX_TARGET_LAG_MS
    tail._capture_due(now_ms=horloge["t"])
    fenetres = tail.state["gap_windows"]
    assert len(fenetres) == 1 and fenetres[0]["nature"] == G.TROU_EXPIRATION
    assert (fenetres[0]["debut_ms"], fenetres[0]["fin_ms"]) == (1_000_000, 1_060_000)
    assert tail.state["counters"]["checkpoints_expired"] == 1
    coherent, raison = G.journal_coherent(tail.state)
    assert coherent is True, f"le journal doit expliquer le compteur : {raison}"


def test_un_DEBORDEMENT_publie_une_fenetre_qui_porte_tout_le_lot(tmp_path):
    from hl_observer.collection import copy_vault_checkpoint_tail as T

    horloge = {"t": 2_000_000}
    tail = _ecrivain(tmp_path, lambda: horloge["t"])
    tail.state["pending"] = [{"checkpoint_id": f"x{i}"} for i in range(T.MAX_PENDING)]
    lot = [{"checkpoint_id": "a", "target_wall_ms": 1_900_000},
           {"checkpoint_id": "b", "target_wall_ms": 1_950_000}]
    assert tail._enqueue_checkpoints(lot) is False
    fenetres = tail.state["gap_windows"]
    assert len(fenetres) == 1 and fenetres[0]["n"] == 2, (
        "le compteur monte de len(additions) : la fenetre doit porter le meme nombre")
    assert (fenetres[0]["debut_ms"], fenetres[0]["fin_ms"]) == (1_900_000, 1_950_000)
    assert G.journal_coherent(tail.state)[0] is True


def test_un_etat_ANCIEN_avec_des_trous_n_ouvre_PAS_le_journal(tmp_path):
    """Le cas réel du 16/11 : 43 expirations et 1 rotation déjà écrites, positions perdues."""
    import json

    from hl_observer.collection import copy_vault_checkpoint_tail as T

    horloge = {"t": 3_000_000}
    tail = _ecrivain(tmp_path, lambda: horloge["t"])
    ancien = dict(tail.state)
    ancien.pop("gap_windows_schema", None)
    ancien.pop("gap_windows", None)
    ancien["counters"] = {**ancien["counters"], "checkpoints_expired": 43, "input_rotations": 1}
    tail.state_path.write_text(json.dumps(ancien), encoding="utf-8")
    recharge = T.CopyVaultCheckpointTail(
        root=tmp_path, clock_ms=lambda: horloge["t"], fetch_book=lambda coin: None).state
    assert recharge.get("gap_windows_schema") != G.SCHEMA_FENETRES, (
        "ouvrir un journal vide ici ferait passer 44 trous de position inconnue pour une epoque propre")
    assert "TROUS_ANTERIEURS_SANS_FENETRE" in recharge.get("gap_windows_unavailable_reason", "")
    assert G.journal_coherent(recharge)[0] is False


def test_un_etat_ancien_SANS_aucun_trou_peut_ouvrir_le_journal(tmp_path):
    """Compteurs à zéro : il n'y a rien à expliquer, donc rien à fermer."""
    import json

    from hl_observer.collection import copy_vault_checkpoint_tail as T

    horloge = {"t": 4_000_000}
    tail = _ecrivain(tmp_path, lambda: horloge["t"])
    ancien = dict(tail.state)
    ancien.pop("gap_windows_schema", None)
    ancien.pop("gap_windows", None)
    tail.state_path.write_text(json.dumps(ancien), encoding="utf-8")
    recharge = T.CopyVaultCheckpointTail(
        root=tmp_path, clock_ms=lambda: horloge["t"], fetch_book=lambda coin: None).state
    assert recharge.get("gap_windows_schema") == G.SCHEMA_FENETRES
    assert G.journal_coherent(recharge)[0] is True


# ─────────── chantier 3 : les 10 slots WS vont aux signaux COPIABLES, pas au volume ───────────
def test_un_leader_tres_bavard_mais_JAMAIS_copiable_ne_prend_plus_de_slot_WS():
    """`docs/LOIS_MESUREES.md` : 61,8 % des fills collectés venaient d'opérateurs HFT NON
    copiables, et 47,2 % des épisodes étaient déjà clos quand leur ouverture devenait observable.
    Classer les 10 slots `userFills` par volume brut, c'est payer pour ce bruit."""
    from hl_observer.collection.subscription_universe import score_activite_leader

    now = 1_000_000_000
    bavard = {"fills_par_min": 40.0, "dernier_fill_ms": now - 1_000,
              "signaux_copiables_par_jour": 0, "fills_observes_pour_copiabilite": 500}
    assert score_activite_leader(bavard, now_ms=now) == float("-inf"), (
        "zero copiable MESURE sur 500 fills : son volume ne doit pas pouvoir acheter un slot rare")


def test_une_copiabilite_MESUREE_devance_un_volume_PRESUME():
    from hl_observer.collection.subscription_universe import score_activite_leader

    now = 1_000_000_000
    mesure_copiable = {"fills_par_min": 0.5, "dernier_fill_ms": now - 1_000,
                       "signaux_copiables_par_jour": 30,
                       "fills_observes_pour_copiabilite": 200}
    jamais_mesure = {"fills_par_min": 40.0, "dernier_fill_ms": now - 1_000}
    assert score_activite_leader(mesure_copiable, now_ms=now) > score_activite_leader(
        jamais_mesure, now_ms=now), (
        "on prefere le MESURE au PRESUME pour les slots CORE ; l'inconnu s'explore via les "
        "slots CHALLENGERS")


def test_un_echantillon_TROP_PETIT_ne_condamne_personne():
    """« pas encore mesuré » n'est pas « mesuré à zéro » : l'inconnu ne ferme pas la porte ici,
    il retombe sur l'activité brute."""
    from hl_observer.collection.subscription_universe import (
        MIN_FILLS_POUR_JUGER_COPIABILITE, score_activite_leader,
    )

    now = 1_000_000_000
    peu = {"fills_par_min": 5.0, "dernier_fill_ms": now - 1_000,
           "signaux_copiables_par_jour": 0,
           "fills_observes_pour_copiabilite": MIN_FILLS_POUR_JUGER_COPIABILITE - 1}
    score = score_activite_leader(peu, now_ms=now)
    assert score > 0.0, f"score {score} : un echantillon de 29 fills ne prouve pas la non-copiabilite"


def test_un_snapshot_only_reste_exclu():
    from hl_observer.collection.subscription_universe import score_activite_leader

    assert score_activite_leader(
        {"snapshot_only": True, "fills_par_min": 99.0, "signaux_copiables_par_jour": 99,
         "fills_observes_pour_copiabilite": 999}, now_ms=1) == float("-inf")


# ───────── 17/11/2026 : un incident = un intervalle, et l'arret de l'ecrivain est un trou ─────────

def _sommes(fenetres):
    cumul = dict.fromkeys(G.NATURES, 0)
    for f in fenetres:
        cumul[f["nature"]] += f["n"]
    return cumul


def test_la_veille_de_42_min_tient_dans_UNE_fenetre_au_lieu_de_302():
    """Le cas reel : 302 checkpoints expires par une seule coupure, tous dans le meme intervalle."""
    etat = _etat()
    for i in range(302):
        G.ajouter_fenetre(etat, G.fenetre(G.TROU_EXPIRATION, debut_ms=1_000 + i * 8_000,
                                          fin_ms=2_600_000))
    assert len(etat["gap_windows"]) == 1
    assert etat["gap_windows"][0] == {"nature": G.TROU_EXPIRATION, "debut_ms": 1_000,
                                      "fin_ms": 2_600_000, "n": 302}
    assert etat["gap_windows_dropped"] == 0


def test_une_longue_coupure_ne_ferme_plus_l_epoque_par_debordement():
    """Avant : au-dela de 512 expirations d'une meme coupure, FENETRES_PERDUES pour toujours."""
    etat = _etat()
    etat["counters"]["checkpoints_expired"] = 2_000
    for i in range(2_000):
        G.ajouter_fenetre(etat, G.fenetre(G.TROU_EXPIRATION, debut_ms=1_000_500 + i,
                                          fin_ms=1_009_000))
    assert etat["gap_windows_dropped"] == 0 and len(etat["gap_windows"]) == 1
    intervalles, raison = G.intervalles_depuis_etat(etat, fin_ms=1_020_000)
    assert raison == "OK" and intervalles, "l'epoque reste certifiable hors de la coupure"
    assert not G.est_sur(1_005_000, intervalles) and G.est_sur(1_015_000, intervalles)


def test_compacter_conserve_EXACTEMENT_l_union_et_les_sommes():
    import random

    alea = random.Random(20261117)
    for _ in range(200):
        fenetres = []
        for _ in range(alea.randint(1, 40)):
            debut = alea.randint(0, 5_000)
            fenetres.append(G.fenetre(alea.choice(G.NATURES), debut_ms=debut,
                                      fin_ms=debut + alea.randint(0, 400), n=alea.randint(1, 5)))
        compactes = G.compacter(fenetres)
        assert _sommes(compactes) == _sommes(fenetres)
        assert G.fusionner(compactes) == G.fusionner(fenetres)
        assert len(compactes) <= len(fenetres)
        assert G.compacter(compactes) == compactes, "compacter deux fois ne change plus rien"


def test_compacter_ne_melange_pas_les_natures():
    a = G.fenetre(G.TROU_EXPIRATION, debut_ms=10, fin_ms=50)
    b = G.fenetre(G.TROU_ROTATION, debut_ms=20, fin_ms=40)
    assert sorted(f["nature"] for f in G.compacter([a, b])) == sorted([G.TROU_EXPIRATION, G.TROU_ROTATION])


def test_compacter_fusionne_ce_qui_se_touche_pas_ce_qui_est_disjoint():
    touche = G.compacter([G.fenetre(G.TROU_EXPIRATION, debut_ms=0, fin_ms=10),
                          G.fenetre(G.TROU_EXPIRATION, debut_ms=10, fin_ms=20)])
    assert touche == [{"nature": G.TROU_EXPIRATION, "debut_ms": 0, "fin_ms": 20, "n": 2}]
    disjoint = G.compacter([G.fenetre(G.TROU_EXPIRATION, debut_ms=0, fin_ms=10),
                            G.fenetre(G.TROU_EXPIRATION, debut_ms=11, fin_ms=20)])
    assert len(disjoint) == 2


def test_compacter_ne_fait_pas_disparaitre_une_fenetre_invalide():
    """Sinon un journal corrompu redeviendrait coherent en passant par la compaction."""
    invalide = {"nature": "inconnue", "debut_ms": 1, "fin_ms": 2, "n": 1}
    etat = _etat(gap_windows=G.compacter([G.fenetre(G.TROU_EXPIRATION, debut_ms=0, fin_ms=5), invalide]))
    etat["counters"]["checkpoints_expired"] = 1
    assert invalide in etat["gap_windows"]
    assert G.journal_coherent(etat) == (False, "FENETRE_INVALIDE")


def test_un_etat_ANTERIEUR_sans_compteur_d_arret_reste_lisible():
    """Le compteur est ne le 17/11 : son absence vaut zero, pas « compteur invalide »."""
    etat = _etat()
    assert "writer_outages" not in etat["counters"]
    assert G.journal_coherent(etat) == (True, "OK")


def test_un_arret_DECLARE_doit_etre_explique_par_une_fenetre():
    etat = _etat()
    etat["counters"]["writer_outages"] = 1
    assert G.journal_coherent(etat) == (False, "FENETRES_INCOMPLETES:writer_outages=1,fenetres=0")
    G.ajouter_fenetre(etat, G.fenetre(G.TROU_ARRET, debut_ms=100, fin_ms=900))
    assert G.journal_coherent(etat) == (True, "OK")
    intervalles, _ = G.intervalles_depuis_etat(etat, fin_ms=5_000)
    assert not G.est_sur(500, intervalles), "l'arret est hors des intervalles surs"


def test_un_compteur_d_arret_PRESENT_mais_invalide_ferme():
    etat = _etat()
    etat["counters"]["writer_outages"] = "1"
    assert G.journal_coherent(etat) == (False, "COMPTEUR_INVALIDE:writer_outages")
