"""LA REPRISE DE LA CONDUITE : dix-neuf tranches ne tiennent pas dans une seule exécution.

Ce n'est pas une hypothèse. Le 18/11/2026, deux tâches de fond ont été arrêtées par le harnais pour
mémoire système critique — dont une suite de tests à 98 % de son parcours. Une conduite de dix-neuf
tranches dure des heures : sans reprise, chaque interruption effacerait tout et elle ne finirait
jamais.

Ces tests verrouillent ce que la reprise reprend, et surtout ce qu'elle REFUSE de reprendre.
"""
from __future__ import annotations

import json

from tools import conduire_labo_par_tranches as CD

HEURE = 3_600_000
T1 = (1, HEURE)
T2 = (HEURE + 1, 2 * HEURE)
T3 = (2 * HEURE + 1, 3 * HEURE)


def _journal(tmp_path):
    return tmp_path / "reprise.jsonl"


def _conduire(tmp_path, tranches, lancer, **kw):
    return CD.conduire(tmp_path, tranches, lancer=lancer,
                       journal_reprise=_journal(tmp_path), **kw)


# ───────────────────────── l'empreinte d'un découpage ─────────────────────────

def test_deux_decoupages_DIFFERENTS_ont_des_empreintes_differentes():
    assert CD.empreinte_du_decoupage([T1, T2]) != CD.empreinte_du_decoupage([T1, T3])


def test_le_MEME_decoupage_donne_toujours_la_meme_empreinte():
    assert CD.empreinte_du_decoupage([T1, T2]) == CD.empreinte_du_decoupage([T1, T2])


def test_l_ORDRE_des_tranches_change_l_empreinte():
    """Un découpage est une séquence : deux ordres sont deux conduites différentes."""
    assert CD.empreinte_du_decoupage([T1, T2]) != CD.empreinte_du_decoupage([T2, T1])


# ───────────────────────── ce que la reprise reprend ─────────────────────────

def test_une_tranche_deja_faite_n_est_PAS_relancee(tmp_path):
    appels = []

    def lancer(_w, tranche):
        appels.append(tranche)
        return {"status": "MORE_DATA", "net_pnl_usd": 1.0}

    premier = _conduire(tmp_path, [T1, T2], lancer)
    assert len(appels) == 2 and premier["tranches_reprises"] == 0

    appels.clear()
    second = _conduire(tmp_path, [T1, T2], lancer)
    assert appels == [], "les deux tranches viennent du journal"
    assert second["tranches_reprises"] == 2
    assert len(second["rapports"]) == 2


def test_une_conduite_INTERROMPUE_reprend_ou_elle_s_est_arretee(tmp_path):
    """Le cas réel : la troisième tranche meurt, on relance, seules les manquantes repartent."""
    def premier_essai(_w, tranche):
        if tranche == T3:
            raise MemoryError("arrêté pour mémoire")
        return {"status": "MORE_DATA"}

    avant = _conduire(tmp_path, [T1, T2, T3], premier_essai)
    assert len(avant["rapports"]) == 2 and avant["incidents"][0]["erreur"] == "MemoryError"
    assert avant["agregat"]["exploitable"] is False

    relances = []

    def second_essai(_w, tranche):
        relances.append(tranche)
        return {"status": "MORE_DATA"}

    apres = _conduire(tmp_path, [T1, T2, T3], second_essai)
    assert relances == [T3], "seule la tranche manquante est refaite"
    assert apres["tranches_reprises"] == 2 and len(apres["rapports"]) == 3
    assert apres["agregat"]["exploitable"] is True


def test_un_rapport_repris_est_MARQUE_comme_tel(tmp_path):
    _conduire(tmp_path, [T1], lambda _w, _t: {"status": "MORE_DATA"})
    repris = _conduire(tmp_path, [T1], lambda _w, _t: {"status": "PROVEN"})
    assert repris["rapports"][0]["repris_du_journal"] is True
    assert repris["rapports"][0]["status"] == "MORE_DATA", "c'est bien l'ancien rapport"


def test_une_tranche_en_ECHEC_n_est_pas_notee_au_journal(tmp_path):
    """Sinon un échec serait repris comme un résultat."""
    _conduire(tmp_path, [T1], lambda _w, _t: (_ for _ in ()).throw(RuntimeError("raté")))
    assert not _journal(tmp_path).exists() or _journal(tmp_path).read_text(encoding="utf-8") == ""
    relances = []
    _conduire(tmp_path, [T1], lambda _w, t: relances.append(t) or {"status": "MORE_DATA"})
    assert relances == [T1], "la tranche en échec est bien retentée"


# ───────────────────────── ce que la reprise REFUSE ─────────────────────────

def test_un_journal_d_un_AUTRE_decoupage_est_IGNORE(tmp_path):
    """Les bornes viennent de la densité du ruban : si le ruban change, le découpage change."""
    _conduire(tmp_path, [T1, T2], lambda _w, _t: {"status": "MORE_DATA"})
    appels = []
    autre = CD.conduire(tmp_path, [T1, T3], journal_reprise=_journal(tmp_path),
                        lancer=lambda _w, t: appels.append(t) or {"status": "MORE_DATA"})
    assert appels == [T1, T3], "aucune tranche reprise : le découpage n'est pas le même"
    assert autre["tranches_reprises"] == 0


def test_une_ligne_TRONQUEE_est_comptee_et_sautee_jamais_devinee(tmp_path):
    """Une interruption peut couper la dernière ligne en deux."""
    chemin = _journal(tmp_path)
    identite = CD.identite_de_tranche(T1, 10)
    with open(chemin, "w", encoding="utf-8", newline="") as flux:
        flux.write(json.dumps({"empreinte": identite, "tranche": list(T1),
                               "rapport": {"status": "MORE_DATA"}}) + "\n")
        flux.write('{"empreinte": "' + identite + '", "tranche": [3600')   # coupée
    lu = CD.lire_le_journal(chemin, {T1: identite})
    assert len(lu["rapports"]) == 1 and lu["lignes_illisibles"] == 1


def test_un_rapport_NON_LISIBLE_dans_le_journal_est_refuse(tmp_path):
    chemin = _journal(tmp_path)
    identite = CD.identite_de_tranche(T1, 10)
    with open(chemin, "w", encoding="utf-8", newline="") as flux:
        flux.write(json.dumps({"empreinte": identite, "tranche": list(T1),
                               "rapport": "tout va bien"}) + "\n")
    lu = CD.lire_le_journal(chemin, {T1: identite})
    assert lu["rapports"] == {} and lu["lignes_illisibles"] == 1


def test_un_journal_ABSENT_n_est_pas_une_erreur(tmp_path):
    lu = CD.lire_le_journal(tmp_path / "jamais.jsonl", {T1: "abc"})
    assert lu["rapports"] == {} and lu["journal"] is False
    assert lu["lignes_illisibles"] == 0


def test_SANS_journal_la_conduite_fonctionne_comme_avant(tmp_path):
    """La non-régression : la reprise est une option, pas une obligation."""
    appels = []
    resultat = CD.conduire(tmp_path, [T1],
                           lancer=lambda _w, t: appels.append(t) or {"status": "MORE_DATA"})
    assert appels == [T1] and resultat["tranches_reprises"] == 0
    assert not (tmp_path / "reprise.jsonl").exists()


def test_l_empreinte_du_decoupage_est_PUBLIEE(tmp_path):
    """Pour qu'on puisse vérifier à quoi un journal appartient sans le relire ligne à ligne."""
    resultat = _conduire(tmp_path, [T1, T2], lambda _w, _t: {"status": "MORE_DATA"})
    assert resultat["empreinte_du_decoupage"] == CD.empreinte_du_decoupage([T1, T2])


def test_les_lignes_d_un_autre_decoupage_sont_COMPTEES(tmp_path):
    """On ne les ignore pas en silence : un journal mélangé doit se voir."""
    chemin = _journal(tmp_path)
    with open(chemin, "w", encoding="utf-8", newline="") as flux:
        flux.write(json.dumps({"empreinte": "autre", "tranche": list(T1),
                               "rapport": {"status": "MORE_DATA"}}) + "\n")
    lu = CD.lire_le_journal(chemin, {T1: CD.identite_de_tranche(T1, 10)})
    assert lu["rapports"] == {} and lu["autre_decoupage"] == 1
# ───────── l'empreinte couvre AUSSI le corpus, pas seulement les bornes ─────────
# Les bornes viennent de la densité du ruban, donc un ruban différent donne presque toujours un
# découpage différent — mais « presque toujours » n'est pas « toujours ». Deux corpus de même
# densité horaire et de contenu différent donneraient les mêmes bornes.

def _manifeste(tmp_path, digest):
    (tmp_path / "SAFE_INPUT_MANIFEST.json").write_text(
        json.dumps({"selection_digest": digest}), encoding="utf-8")


def test_deux_CORPUS_differents_aux_memes_bornes_ont_des_empreintes_differentes():
    a = CD.empreinte_du_decoupage([T1, T2], corpus="a" * 64)
    b = CD.empreinte_du_decoupage([T1, T2], corpus="b" * 64)
    assert a != b


def test_le_digest_du_corpus_est_LU_dans_le_manifeste(tmp_path):
    _manifeste(tmp_path, "c" * 64)
    assert CD.digest_du_corpus(tmp_path) == "c" * 64


def test_un_manifeste_ABSENT_donne_un_corpus_inconnu_sans_lever(tmp_path):
    """La conduite ne doit pas échouer pour ça : mais l'inconnu ne se confond avec aucun digest."""
    assert CD.digest_du_corpus(tmp_path) == CD.CORPUS_INCONNU
    assert CD.empreinte_du_decoupage([T1], corpus=CD.CORPUS_INCONNU) != CD.empreinte_du_decoupage(
        [T1], corpus="d" * 64)


def test_un_manifeste_ILLISIBLE_donne_aussi_un_corpus_inconnu(tmp_path):
    (tmp_path / "SAFE_INPUT_MANIFEST.json").write_text("{ pas du json", encoding="utf-8")
    assert CD.digest_du_corpus(tmp_path) == CD.CORPUS_INCONNU


def test_un_digest_VIDE_est_traite_comme_inconnu(tmp_path):
    _manifeste(tmp_path, "")
    assert CD.digest_du_corpus(tmp_path) == CD.CORPUS_INCONNU


def test_un_journal_ecrit_pour_un_AUTRE_corpus_n_est_pas_repris(tmp_path):
    """Le scénario que la correction ferme : mêmes bornes, corpus remplacé."""
    _manifeste(tmp_path, "e" * 64)
    _conduire(tmp_path, [T1], lambda _w, _t: {"status": "MORE_DATA"})

    _manifeste(tmp_path, "f" * 64)           # le workspace a été re-matérialisé
    appels = []
    apres = _conduire(tmp_path, [T1], lambda _w, t: appels.append(t) or {"status": "PROVEN"})
    assert appels == [T1], "la tranche est refaite : le corpus n'est plus le même"
    assert apres["tranches_reprises"] == 0
    assert apres["digest_du_corpus"] == "f" * 64


def test_le_MEME_corpus_est_bien_repris(tmp_path):
    """La non-régression : lier l'empreinte au corpus ne doit pas casser la reprise normale."""
    _manifeste(tmp_path, "e" * 64)
    _conduire(tmp_path, [T1], lambda _w, _t: {"status": "MORE_DATA"})
    appels = []
    apres = _conduire(tmp_path, [T1], lambda _w, t: appels.append(t) or {"status": "PROVEN"})
    assert appels == [] and apres["tranches_reprises"] == 1
# ───────── ET QUAND DE NOUVELLES DONNÉES ARRIVENT ? ─────────
# La question, posée le 18/11/2026, a révélé un défaut. Mesure d'abord : un corpus de six heures
# donne six tranches ; trois heures de plus en donnent neuf, dont les SIX PREMIÈRES sont identiques
# à la borne près — le découpage parcourt les seaux dans l'ordre et accumule, donc une collecte
# chronologique n'ajoute des tranches qu'à la fin.
#
# Mais l'empreinte de reprise portait sur le découpage ENTIER : elle changeait, le journal était
# ignoré, et les six tranches déjà calculées étaient refaites pour rien. Une tranche s'identifie
# désormais par ce qu'elle CONTIENT : ses bornes et son nombre de fills.

def test_de_NOUVELLES_donnees_ajoutent_des_tranches_sans_bouger_les_anciennes():
    """Le fondement de tout le reste : le découpage est stable par la gauche."""
    avant = {h * HEURE: 300 for h in range(1, 7)}
    apres = {h * HEURE: 300 for h in range(1, 10)}
    ta = CD.decouper(avant, budget=500, pas_ms=HEURE)
    tb = CD.decouper(apres, budget=500, pas_ms=HEURE)
    assert len(ta) == 6 and len(tb) == 9
    assert tb[:6] == ta, "les tranches déjà formées ne bougent pas"


def test_une_nouvelle_collecte_ne_fait_PAS_refaire_les_tranches_deja_calculees(tmp_path):
    """Sans cela, chaque collecte jetterait des heures de travail."""
    lignes = {T1: 300, T2: 300, T3: 300}
    faits = []

    def lancer(_w, tranche):
        faits.append(tranche)
        return {"status": "MORE_DATA"}

    # première conduite : deux tranches
    CD.conduire(tmp_path, [T1, T2], lancer=lancer, journal_reprise=_journal(tmp_path),
                lignes_par_tranche=lignes.get)
    assert faits == [T1, T2]

    # la collecte a avancé : une tranche de plus, les deux premières inchangées
    faits.clear()
    resultat = CD.conduire(tmp_path, [T1, T2, T3], lancer=lancer,
                           journal_reprise=_journal(tmp_path), lignes_par_tranche=lignes.get)
    assert faits == [T3], "seule la nouvelle tranche est calculée"
    assert resultat["tranches_reprises"] == 2
    assert len(resultat["rapports"]) == 3


def test_une_tranche_dont_les_DONNEES_ont_change_est_refaite(tmp_path):
    """La contrepartie : la stabilité ne doit pas devenir de l'aveuglement."""
    faits = []

    def lancer(_w, tranche):
        faits.append(tranche)
        return {"status": "MORE_DATA"}

    CD.conduire(tmp_path, [T1, T2], lancer=lancer, journal_reprise=_journal(tmp_path),
                lignes_par_tranche={T1: 300, T2: 300}.get)
    faits.clear()
    # T1 a reçu des fills de plus (rattrapage, re-matérialisation) : son identité change
    resultat = CD.conduire(tmp_path, [T1, T2], lancer=lancer, journal_reprise=_journal(tmp_path),
                           lignes_par_tranche={T1: 450, T2: 300}.get)
    assert faits == [T1], "T1 est refaite, T2 est reprise"
    assert resultat["tranches_reprises"] == 1


def test_l_identite_d_une_tranche_ne_depend_PAS_de_ses_voisines():
    """C'est ce qui rend la reprise stable quand le découpage s'allonge."""
    a = CD.identite_de_tranche(T1, 300)
    b = CD.identite_de_tranche(T1, 300)
    assert a == b
    assert CD.identite_de_tranche(T1, 301) != a, "le nombre de lignes compte"
    assert CD.identite_de_tranche(T2, 300) != a, "les bornes comptent"


def test_SANS_compteur_de_lignes_on_retombe_sur_le_decoupage_entier(tmp_path):
    """Plus prudent, mais sans reprise au-delà d'une nouvelle collecte : le dire plutôt que deviner."""
    faits = []

    def lancer(_w, tranche):
        faits.append(tranche)
        return {"status": "MORE_DATA"}

    CD.conduire(tmp_path, [T1, T2], lancer=lancer, journal_reprise=_journal(tmp_path))
    faits.clear()
    CD.conduire(tmp_path, [T1, T2, T3], lancer=lancer, journal_reprise=_journal(tmp_path))
    assert faits == [T1, T2, T3], "le découpage a changé : tout est refait, faute d'identité stable"


def test_le_journal_PUBLIE_le_corpus_sans_s_en_servir_pour_comparer(tmp_path):
    """Une reprise qui traverse deux corpus reste acceptée, mais elle doit se VOIR."""
    import json as _json

    (tmp_path / "SAFE_INPUT_MANIFEST.json").write_text(
        _json.dumps({"selection_digest": "a" * 64}), encoding="utf-8")
    CD.conduire(tmp_path, [T1], lancer=lambda _w, _t: {"status": "MORE_DATA"},
                journal_reprise=_journal(tmp_path), lignes_par_tranche={T1: 300}.get)
    ligne = _json.loads(_journal(tmp_path).read_text(encoding="utf-8").splitlines()[0])
    assert ligne["corpus"] == "a" * 64

    # corpus remplacé : la tranche est quand même reprise, car ses données n'ont pas changé
    (tmp_path / "SAFE_INPUT_MANIFEST.json").write_text(
        _json.dumps({"selection_digest": "b" * 64}), encoding="utf-8")
    faits = []
    resultat = CD.conduire(tmp_path, [T1],
                           lancer=lambda _w, t: faits.append(t) or {"status": "MORE_DATA"},
                           journal_reprise=_journal(tmp_path), lignes_par_tranche={T1: 300}.get)
    assert faits == [] and resultat["tranches_reprises"] == 1
    assert resultat["digest_du_corpus"] == "b" * 64, "le corpus courant reste publié"

