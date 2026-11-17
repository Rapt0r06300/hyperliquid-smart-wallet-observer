"""LE COFFRE EST LE MAGASIN PRINCIPAL : ce qui n'y entre pas n'existe pas pour le labo.

D'OU VIENNENT CES TESTS (16/11/2026). Le rattrapage ecrivait des milliers de jours-coins dans
``runtime/history``, et c'est la campagne qui les scellait — toutes les 30 minutes, via le
collecteur « coffre-certificateur ». Donc : rattrapage lance collecteurs fermes, ou fenetre fermee
en cours de route (15/11, 21 h 32), et la donnee restait DEHORS. Le labo ne lit que le coffre : une
donnee non scellee est invisible, quelle que soit sa taille.

Corollaire immediat : si le rattrapage scelle lui-meme, DEUX scelleurs peuvent tourner ensemble
(le sien et le periodique). Ils ecrivent le meme ``SOURCES_TRAITEES.json`` et le dernier efface les
decalages d'octets de l'autre. D'ou un verrou partage, et les tests qui vont avec.

Pur : aucun reseau, aucun scellage reel.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
for chemin in (str(RACINE), str(RACINE / "src"), str(RACINE / "tools")):
    if chemin not in sys.path:
        sys.path.insert(0, chemin)

import rattrapage_complet as RC                      # noqa: E402
import sceller_coffre_local as SC                    # noqa: E402
from hl_observer.ops import verrou_pid as VP         # noqa: E402


# ─────────────── le verrou partage : un seul ecrivain sur un registre ───────────────
def test_un_verrou_vivant_refuse_le_second_ecrivain(tmp_path):
    chemin = tmp_path / "x.lock"
    assert VP.prendre(chemin)[0] is True
    encore, mot = VP.prendre(chemin, quoi="un scellage")
    assert encore is False and "un scellage tourne deja" in mot, (
        "deux scelleurs ecrivent le meme SOURCES_TRAITEES.json : le dernier efface les "
        "decalages d'octets de l'autre, et le labo ne sait plus ce qui est scelle")
    VP.rendre(chemin)
    assert VP.prendre(chemin)[0] is True, "un verrou rendu doit se reprendre"


def test_un_verrou_perime_est_recupere_et_la_recuperation_est_DITE(tmp_path):
    chemin = tmp_path / "x.lock"
    chemin.write_text(json.dumps({"pid": os.getpid(), "ts": time.time() - 7 * 3600}),
                      encoding="utf-8")
    obtenu, mot = VP.prendre(chemin, perime_s=6 * 3600.0)
    assert obtenu is True and "PERIME" in mot, (
        "le PC coupe les runs longs : un verrou oublie ne doit pas bloquer tous les scellages "
        "suivants, mais la recuperation doit etre annoncee")


def test_un_horodatage_inconnu_ne_fait_pas_voler_un_verrou_vivant(tmp_path):
    chemin = tmp_path / "x.lock"
    chemin.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")   # pas de ts
    assert VP.prendre(chemin)[0] is False, "`ts` absent n'est pas « tres vieux », c'est INCONNU"


def test_le_verrou_du_rattrapage_et_celui_du_coffre_sont_DEUX_fichiers():
    assert RC.VERROU != SC.VERROU_RELPATH, (
        "le rattrapage et le scellage s'enchainent dans le meme passage : un verrou commun "
        "ferait refuser le scellage par le rattrapage qui vient de l'appeler")


# ─────────────── le scelleur refuse de doubler, sans rougir ───────────────
def test_un_scellage_deja_en_cours_fait_RIEN_A_FAIRE_et_non_une_erreur(tmp_path, capsys, monkeypatch):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / SC.VERROU_RELPATH).write_text(json.dumps({"pid": os.getpid(), "ts": time.time()}),
                                              encoding="utf-8")
    appels = []
    monkeypatch.setattr(SC, "main", lambda argv: appels.append(argv) or 0)
    code = SC._point_d_entree(["--root", str(tmp_path)])
    sortie = capsys.readouterr().out
    assert appels == [], "refuser le verrou doit empecher la passe, pas seulement l'annoncer"
    assert code == 0, (
        "la campagne relance ce scelleur toutes les 30 min : rougir sur un passage superpose "
        "ferait croire a une panne du coffre alors que rien n'a echoue")
    assert "RIEN A SCELLER MAINTENANT" in sortie and "tourne deja" in sortie


def test_le_scelleur_pose_son_verrou_a_la_racine_DEMANDEE():
    assert SC._racine_des_args(["--root", "/un/ailleurs"]) == Path("/un/ailleurs")
    assert SC._racine_des_args(["--root=/un/ailleurs"]) == Path("/un/ailleurs")
    assert SC._racine_des_args(["--tout"]) == SC.ROOT, "sans --root, la racine du projet"


def test_le_verrou_du_scelleur_est_rendu_meme_si_la_passe_echoue(tmp_path, monkeypatch):
    def plante(_argv):
        raise RuntimeError("disque plein")
    monkeypatch.setattr(SC, "main", plante)
    with pytest.raises(RuntimeError):
        SC._point_d_entree(["--root", str(tmp_path)])
    assert not (tmp_path / SC.VERROU_RELPATH).exists(), (
        "un verrou laisse apres une passe en echec bloquerait la certification pendant 6 h, "
        "et le labo ne verrait plus rien arriver")


# ─────────────── le rattrapage scelle ce qu'il vient d'ecrire ───────────────
def test_la_commande_de_scellement_est_bien_le_scelleur_du_coffre(tmp_path, monkeypatch):
    vues = {}
    monkeypatch.setattr(RC, "executer",
                        lambda commande, **kw: vues.update(commande=commande, kw=kw) or
                        {"code": 0, "duree_s": 1.0, "lignes": 0, "arret_memoire": None})
    RC.sceller_le_coffre(tmp_path, journal=None, surveiller_memoire=False)
    assert vues["commande"][-2:] == ["--root", str(tmp_path)]
    assert vues["commande"][3].endswith("sceller_coffre_local.py"), (
        f"commande {vues['commande']} : le rattrapage doit appeler LE scelleur du coffre, "
        "pas une copie de sa logique")
    assert vues["kw"]["surveiller_memoire"] is False


def test_on_scelle_des_qu_une_tache_a_ete_SERVIE():
    on, pourquoi = RC.decider_scellement([{"nom": "funding-profond", "servie": True}],
                                         sans_scellement=False)
    assert on is True and pourquoi == ""


def test_on_NE_scelle_PAS_quand_le_certificateur_scelle_juste_apres():
    on, pourquoi = RC.decider_scellement([{"servie": True}], sans_scellement=True)
    assert on is False and "certificateur scelle juste apres" in pourquoi, (
        "« Certificateur Coffre Fort.cmd » enchaine rattrapage puis scellage : sceller deux fois "
        "de suite les memes octets ne casse rien mais ne sert a rien")


def test_un_passage_qui_n_a_rien_servi_ne_declenche_pas_un_scellage_pour_rien():
    on, pourquoi = RC.decider_scellement([{"servie": False, "note": "budget epuise"}],
                                         sans_scellement=False)
    assert on is False and "rien de neuf" in pourquoi


def test_le_certificateur_passe_bien_sans_scellement_au_rattrapage():
    """Le drapeau doit etre DANS le lanceur : un commentaire ne desactive rien."""
    texte = (RACINE / "Certificateur Coffre Fort.cmd").read_text(encoding="utf-8")
    ligne = [l for l in texte.splitlines() if "rattrapage_complet.py" in l and "--budget-s" in l]
    assert len(ligne) == 1 and "--sans-scellement" in ligne[0], (
        f"ligne de l'etape 1 : {ligne}")


def test_le_verrou_est_pris_PAR_DEFAUT_et_n_est_saute_que_si_on_le_DEMANDE(tmp_path, monkeypatch):
    """`verrouiller=False` est reserve aux tests d'aiguillage, jamais au chemin de production.

    16/11 — sans racine explicite, le verrou se pose dans l'arbre REEL du projet. Un test
    d'aiguillage interrompu y laissait un verrou qui aurait bloque la certification de la campagne
    pendant 6 h. D'ou l'option — et d'ou ce test, pour qu'elle reste une exception.
    """
    pris: list[Path] = []
    monkeypatch.setattr(SC.verrou_pid, "prendre",
                        lambda chemin, **kw: (pris.append(Path(chemin)), (True, ""))[1])
    monkeypatch.setattr(SC.verrou_pid, "rendre", lambda chemin: None)
    monkeypatch.setattr(SC, "main", lambda argv: 0)
    SC._point_d_entree(["--root", str(tmp_path)])
    assert pris == [tmp_path / SC.VERROU_RELPATH], "par defaut, le verrou DOIT etre pris"
    pris.clear()
    SC._point_d_entree(["--root", str(tmp_path)], verrouiller=False)
    assert pris == [], "verrouiller=False ne doit rien poser dans l'arbre"


def test_aucun_test_d_aiguillage_ne_verrouille_l_arbre_reel():
    """Garde-fou : un appel a `--root .` sans `verrouiller=False` ecrirait dans le vrai projet."""
    texte = (RACINE / "tests" / "test_certification_en_continu.py").read_text(encoding="utf-8")
    appels = [l for l in texte.splitlines() if "_point_d_entree(" in l and "--root" in l]
    assert appels, "le fichier d'aiguillage a change de forme : revoir ce garde-fou"
    manquants = [l.strip() for l in appels if "verrouiller=False" not in l]
    assert not manquants, f"ces appels verrouilleraient le vrai projet : {manquants}"


# ─────────────── Ctrl+C : « sans perdre aucune donnee » (exigence du 16/11) ───────────────
def test_ctrl_c_pendant_une_tache_laisse_un_etat_VRAI_et_rend_le_verrou(tmp_path, monkeypatch):
    """Sans gestion du Ctrl+C, l'avancement restait sur « EN_COURS » : un etat qui MENT.

    Les donnees, elles, etaient deja sauves — chaque page est ecrite en lignes entieres et l'etat
    du backfill est remplace atomiquement apres chacune. Ce qui manquait, c'etait de le dire et de
    laisser derriere soi un etat relisible, sans verrou coince pour 6 h.
    """
    monkeypatch.setattr(RC, "coins_du_livre", lambda root: ["BTC", "ETH"])
    monkeypatch.setattr(RC, "charger_etat_collecteurs", lambda root: {})

    def interrompu(commande, **kw):
        raise KeyboardInterrupt
    monkeypatch.setattr(RC, "executer", interrompu)

    code = RC.main(["--root", str(tmp_path), "--budget-s", "120"])
    assert code == 130, "un Ctrl+C n'est pas un succes : le lanceur doit pouvoir le distinguer"
    etat = json.loads((tmp_path / RC.ETAT_SORTIE).read_text(encoding="utf-8"))
    assert etat["etat"] == "CTRL_C", f"etat ecrit : {etat['etat']} — « EN_COURS » serait un mensonge"
    assert not (tmp_path / RC.VERROU).exists(), (
        "un verrou laisse apres un Ctrl+C bloquerait tout rattrapage pendant 6 h")
    assert etat["scellement"]["fait"] is False and "Ctrl+C" in etat["scellement"]["note"]


def test_on_ne_fait_pas_attendre_un_scellage_a_qui_vient_d_interrompre():
    on, pourquoi = RC.decider_scellement([{"servie": True}], sans_scellement=False, interrompu=True)
    assert on is False and "Certificateur Coffre Fort" in pourquoi, (
        "le scellage dure des minutes : le lancer apres un Ctrl+C serait exactement ce que "
        "l'utilisateur vient de refuser — mais il faut DIRE ou en sont les donnees")


def test_un_ruban_interrompu_se_termine_sur_une_LIGNE_ENTIERE(tmp_path):
    """La garantie « aucune donnee perdue » repose sur ca : jamais de ligne coupee en deux."""
    import backfill_candles_vaults as BC

    ruban = tmp_path / "funding.jsonl"
    lignes = [{"coin": "BTC", "ts_ms": 1 + i, "funding": 0.0001, "premium": 0.5} for i in range(50)]
    BC._ecrire_funding(ruban, lignes, now_ms=42)
    brut = ruban.read_text(encoding="utf-8")
    assert brut.endswith("\n"), "un ruban qui ne finit pas par un saut de ligne coupe le dernier point"
    assert len(brut.splitlines()) == 50
    for l in brut.splitlines():
        json.loads(l)        # chaque ligne relisible seule : c'est ce que le scelleur exige


def test_le_lanceur_explique_le_ctrl_c_a_l_ecran():
    texte = (RACINE / "RATTRAPAGE.cmd").read_text(encoding="utf-8")
    assert '"%RC%"=="130"' in texte and "AUCUNE DONNEE PERDUE" in texte, (
        "le code 130 doit etre reconnu par le lanceur, sinon un Ctrl+C s'affiche comme une panne")


def test_un_ctrl_c_pendant_un_scellage_ne_dumpe_plus_de_pile(tmp_path, monkeypatch, capsys):
    """Vu dans `coffre_session.log` du 12/11 : un Ctrl+C laissait une pile d'erreur, que le
    rapport remontait ensuite en « ERREUR GRAVE — A CORRIGER EN PRIORITE ». Ce n'etait pas une
    panne : c'etait quelqu'un qui avait interrompu. Le scellage est incremental, rien n'est perdu.
    """
    def interrompu(_argv):
        raise KeyboardInterrupt
    monkeypatch.setattr(SC, "main", interrompu)
    code = SC._point_d_entree(["--root", str(tmp_path)])
    sortie = capsys.readouterr().out
    assert code == 130, "un Ctrl+C n'est ni un succes ni une panne : 130"
    assert "arret propre" in sortie and "RESTE" in sortie
    assert not (tmp_path / SC.VERROU_RELPATH).exists(), "le verrou doit etre rendu meme la"
