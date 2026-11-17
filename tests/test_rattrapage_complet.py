"""L'ORCHESTRATEUR DU RATTRAPAGE : un verrou, une commande juste, un univers qui ne retrecit pas.

POURQUOI CES TESTS. Le 15/11, deux rattrapages lances a la main en parallele ont ete tues par le
systeme pour manque de memoire. Et le meme soir, l'archivage de session a fait tomber l'univers
suivi de **261 a 216 coins** sans un mot : 45 coins dont on detenait des centaines de jours
cessaient d'etre tenus a jour, parce que la liste des coins etait deduite d'un ruban archive.

Aucun reseau, aucun sous-processus reel : seules les parties decidables sont testees ici.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))


def _mod(nom: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / ("%s.py" % nom))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


RC = _mod("rattrapage_complet")
BC = _mod("backfill_candles_vaults")

HEURE = 3_600_000
NOW = 1_790_000_000_000


# ─────────────── le verrou : jamais deux rattrapages ───────────────
def test_un_second_rattrapage_est_refuse_tant_que_le_premier_vit(tmp_path):
    obtenu, _ = RC.prendre_le_verrou(tmp_path)
    assert obtenu is True
    # le verrou porte NOTRE pid, qui est vivant : un second passage doit etre refuse
    encore, mot = RC.prendre_le_verrou(tmp_path)
    assert encore is False and "tourne deja" in mot, (
        "deux rattrapages a la fois, c'est la memoire qui saute et deux ecrivains sur le meme etat")
    RC.rendre_le_verrou(tmp_path)
    apres, _ = RC.prendre_le_verrou(tmp_path)
    assert apres is True, "le verrou rendu doit se reprendre"


def test_un_verrou_perime_est_recupere_et_la_recuperation_est_DITE(tmp_path):
    import time as _t

    (tmp_path / "runtime" / "data").mkdir(parents=True)
    # PID VIVANT (le notre) mais verrou plus vieux que l'expiration : cas du PID recycle apres un
    # redemarrage. Sans l'expiration, un seul verrou oublie bloquerait tous les rattrapages.
    vieux = _t.time() - RC.VERROU_PERIME_S - 60.0
    (tmp_path / RC.VERROU).write_text(json.dumps({"pid": os.getpid(), "ts": vieux}),
                                      encoding="utf-8")
    obtenu, mot = RC.prendre_le_verrou(tmp_path)
    assert obtenu is True and "PERIME" in mot, (
        "le PC coupe les runs longs : un verrou oublie ne doit pas bloquer tous les rattrapages "
        "suivants, mais la recuperation doit etre annoncee, pas silencieuse")


def test_un_horodatage_illisible_ne_fait_pas_voler_un_verrou_vivant(tmp_path):
    """`ts` absent n'est pas « tres vieux », c'est INCONNU : avec un PID vivant, on refuse."""
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / RC.VERROU).write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    obtenu, mot = RC.prendre_le_verrou(tmp_path)
    assert obtenu is False and "tourne deja" in mot


def test_un_verrou_illisible_ne_bloque_pas(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / RC.VERROU).write_text("pas du json", encoding="utf-8")
    obtenu, _ = RC.prendre_le_verrou(tmp_path)
    assert obtenu is True


# ─────────────── la commande lancee : une seule source de verite ───────────────
def test_la_commande_funding_demande_le_funding_SEUL_et_sa_profondeur():
    cmd = RC.commande_pour("funding-profond", "funding", root=Path("/r"), budget_s=1800.0,
                           profondeur_jours=1100.0)
    assert "--seulement-funding" in cmd
    assert cmd[cmd.index("--budget-funding-s") + 1] == "1800"
    assert cmd[cmd.index("--profondeur-jours") + 1] == "1100"
    assert "--intervalles" not in cmd, "le funding ne doit pas entrainer de tirage de bougies"


def test_la_commande_bougies_ne_touche_PAS_au_funding():
    cmd = RC.commande_pour("bougies-4h", "4h", root=Path("/r"), budget_s=600.0,
                           profondeur_jours=1100.0)
    assert cmd[cmd.index("--intervalles") + 1] == "4h"
    assert "--sans-funding" in cmd, (
        "sinon chaque tache de bougies relancerait le funding et le budget de la tache suivante "
        "serait depense deux fois")
    assert cmd[cmd.index("--budget-s") + 1] == "600"


def test_toutes_les_taches_du_plan_ont_une_commande_valide():
    from hl_observer.ops import rattrapage_plan as RP

    for tache in RP.TACHES:
        cmd = RC.commande_pour(tache.nom, tache.serie, root=Path("/r"), budget_s=60.0,
                               profondeur_jours=1100.0)
        assert cmd[0] == sys.executable and cmd[3].endswith("backfill_candles_vaults.py")
        if tache.serie != "funding":
            assert tache.serie in BC.INTERVALLES_MS, (
                f"{tache.serie} est demande au collecteur mais n'est pas un pas connu de lui")


# ─────────────── l'etat lu : fail-closed sur un schema etranger ───────────────
def test_un_etat_de_schema_inconnu_est_ignore_plutot_que_mal_lu(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / BC.ETAT).write_text(json.dumps({"_schema": "autre.chose", "intervalles": {"1h": {"BTC": 1}}}),
                                    encoding="utf-8")
    assert RC.charger_etat_collecteurs(tmp_path) == {}, (
        "lire un etat dont on ne connait pas le schema, c'est risquer de prendre un horodatage "
        "pour un autre — et un rattrapage mal informe redemande tout ou rien")


def test_un_etat_absent_donne_un_manque_complet_pas_une_erreur(tmp_path):
    assert RC.charger_etat_collecteurs(tmp_path) == {}


def test_l_avancement_est_ecrit_de_facon_atomique_et_relisible(tmp_path):
    RC.ecrire_avancement(tmp_path, etat="EN_COURS", coins=263, taches=[{"nom": "bougies-4h"}])
    lu = json.loads((tmp_path / RC.ETAT_SORTIE).read_text(encoding="utf-8"))
    assert lu["_schema"] == RC.SCHEMA and lu["etat"] == "EN_COURS" and lu["coins"] == 263
    assert lu["maj_ms"] > 0
    assert not list((tmp_path / RC.ETAT_SORTIE).parent.glob("*.tmp")), "aucun brouillon laisse"


# ─────────────── l'univers suivi ne doit pas retrecir apres un archivage ───────────────
def test_un_coin_dont_l_historique_est_commence_reste_suivi_meme_sans_fills(tmp_path):
    """Le defaut du 15/11 : 261 -> 216 coins apres l'archivage de la session, en silence."""
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "copy_vault_coins.json").write_text(json.dumps({"coins": ["BTC"]}),
                                                               encoding="utf-8")
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / BC.ETAT).write_text(json.dumps({
        "_schema": BC.SCHEMA_ETAT,
        "intervalles": {"1d": {"OUBLIE": NOW - HEURE}, BC.SERIE_FUNDING: {"AUTRE": NOW - HEURE}}}),
        encoding="utf-8")
    suivis = BC.coins_suivis(tmp_path)
    assert "BTC" in suivis
    assert "OUBLIE" in suivis and "AUTRE" in suivis, (
        "une serie qu'on arrete de prolonger devient un bloc mort : le livre perd sa largeur, et "
        "c'est la largeur qui fixe la diversification ET la force des queues du signal")


def test_coins_deja_commences_tolere_un_etat_pourri(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / BC.ETAT).write_text("{pas du json", encoding="utf-8")
    assert BC.coins_deja_commences(tmp_path) == []
    (tmp_path / BC.ETAT).write_text(json.dumps({"_schema": "inconnu", "intervalles": {"1h": {"X": 1}}}),
                                    encoding="utf-8")
    assert BC.coins_deja_commences(tmp_path) == []


# ─────────── 16/11 : le budget non consommé doit COULER vers les tâches suivantes ───────────
def test_une_tache_qui_finit_tot_REND_son_budget_aux_suivantes(tmp_path, monkeypatch):
    """Mesure du passage de 18:14 : `funding-profond` avait 26 894 s, s'est arrêté sur
    LIMITE_DEBIT après 2 400 s, et `bougies-4h`/`1h`/`5m` ont affiché « budget épuisé » alors que
    **6 h 48 de budget dormaient**. La répartition était calculée une fois pour toutes au départ.
    """
    monkeypatch.setattr(RC, "coins_du_livre", lambda root: [f"C{i}" for i in range(50)])
    monkeypatch.setattr(RC, "charger_etat_collecteurs", lambda root: {})
    monkeypatch.setattr(RC, "decider_scellement", lambda faits, **kw: (False, "test"))

    lancees = []

    def executer_instantane(commande, **kw):
        lancees.append(commande)
        return {"code": 0, "duree_s": 0.0, "lignes": 0, "arret_memoire": None}

    monkeypatch.setattr(RC, "executer", executer_instantane)
    code = RC.main(["--root", str(tmp_path), "--budget-s", "36000"])
    assert code == 0

    series = [c[c.index("--intervalles") + 1] for c in lancees if "--intervalles" in c]
    assert "--seulement-funding" in {x for c in lancees for x in c}, "le funding doit etre servi"
    assert series, (
        "aucune tache de bougies servie : le budget rendu par le funding n'a pas coule vers la "
        f"suite (commandes lancees : {len(lancees)})")
    etat = json.loads((tmp_path / RC.ETAT_SORTIE).read_text(encoding="utf-8"))
    servies = [t["nom"] for t in etat["taches"] if t.get("servie")]
    assert len(servies) >= 3, f"seules {servies} ont ete servies avec 10 h de budget"


def test_un_budget_REELLEMENT_epuise_ne_sert_plus_rien(tmp_path, monkeypatch):
    """Le reflux ne doit pas devenir un budget infini : une tâche qui consomme tout ferme la suite."""
    monkeypatch.setattr(RC, "coins_du_livre", lambda root: [f"C{i}" for i in range(50)])
    monkeypatch.setattr(RC, "charger_etat_collecteurs", lambda root: {})
    monkeypatch.setattr(RC, "decider_scellement", lambda faits, **kw: (False, "test"))

    lancees = []

    def executer_lent(commande, **kw):
        lancees.append(commande)
        RC.time.sleep(0.05)           # consomme tout le budget de 0,01 s
        return {"code": 0, "duree_s": 0.05, "lignes": 0, "arret_memoire": None}

    monkeypatch.setattr(RC, "executer", executer_lent)
    RC.main(["--root", str(tmp_path), "--budget-s", "0.01"])
    etat = json.loads((tmp_path / RC.ETAT_SORTIE).read_text(encoding="utf-8"))
    non_servies = [t for t in etat["taches"] if not t.get("servie")]
    assert non_servies, "avec 0,01 s de budget, tout ne peut pas etre servi"
    assert all(str(t.get("note") or "").strip() for t in non_servies), (
        f"une tache non servie doit DIRE pourquoi : {[t.get('note') for t in non_servies]}")
    assert len(lancees) <= 1, (
        f"le reflux ne doit pas devenir un budget infini : {len(lancees)} taches lancees "
        "avec 0,01 s de budget")


# ───────── 16/11 : NE PAS TUER SA PROPRE TACHE QUAND LA PRESSION VIENT D'AILLEURS ─────────
#
# MESURE DU 16/11 A 20:20. Le rattrapage a vu « RAM critique (2,96 Go libres, 9 %) », attendu 30 s,
# puis tue sa passe `funding-profond` — qui avait deja consomme 4 485 s et laissait 17 458
# jours-coins a creuser. Or cette passe ecrit CHAQUE page sur le disque et ne garde qu'une page en
# memoire : l'arbre de processus d'Alina tenait **0,02 Go sur 24,04 Go utilises**. On a detruit du
# travail pour liberer un millieme du probleme, et le `break` a en plus prive les trois taches
# suivantes de leur passage, alors que `bougies-1d` ne prend qu'UNE seconde.
#
# Regle de l'operateur : « on adapte la puissance a la RAM, mais JAMAIS de crash, et SANS degrader
# les donnees. » Respirer coute du temps ; tuer coute des donnees.
_ARBRE_SAGE = 20 * 10**6          # 0,02 Go : la passe funding, qui vide sa page a chaque tour
_ARBRE_GLOUTON = 20 * 10**9       # 20 Go : la, c'est bien nous
_ROUGE = {"dispo_octets": 2 * 10**9, "total_octets": 34 * 10**9}


def test_sous_pression_EXTERIEURE_on_continue_au_lieu_de_tuer_son_travail():
    verdict = RC.decider_sous_pression(niveau="ROUGE", arbre_octets=_ARBRE_SAGE,
                                       respirations_faites=len(RC.PATIENCE_MEMOIRE_S), **_ROUGE)
    assert verdict["action"] == RC.CONTINUER
    assert verdict["coupable"] == "EXTERIEUR"
    assert "liberer" in verdict["raison"] or "libererait" in verdict["raison"]


def test_quand_c_est_NOTRE_arbre_qui_sature_on_rend_la_main():
    """L'arret doit rester possible : sinon la machine finirait par nous tuer, et un processus tue
    ne ferme pas son etat proprement — c'est ce qui est arrive aux deux passes du 15/11."""
    verdict = RC.decider_sous_pression(niveau="ROUGE", arbre_octets=_ARBRE_GLOUTON,
                                       respirations_faites=len(RC.PATIENCE_MEMOIRE_S), **_ROUGE)
    assert verdict["action"] == RC.RENDRE_LA_MAIN
    assert verdict["coupable"] == "NOUS"


def test_la_patience_ESCALADE_avant_toute_decision():
    """Cinq respirations de 30 s a 8 min : 15,5 min de patience avant de renoncer, contre 30 s."""
    attentes = []
    for n in range(len(RC.PATIENCE_MEMOIRE_S)):
        verdict = RC.decider_sous_pression(niveau="ROUGE", arbre_octets=_ARBRE_GLOUTON,
                                           respirations_faites=n, **_ROUGE)
        assert verdict["action"] == RC.RESPIRER, "meme gloutons, on respire AVANT de renoncer"
        attentes.append(verdict["attente_s"])
    assert attentes == sorted(attentes), "les attentes doivent croitre, pas stagner"
    assert attentes[0] == 30.0
    assert sum(attentes) >= 900.0, "au moins 15 min de patience au total"


def test_une_memoire_SAINE_ne_declenche_aucune_attente():
    for niveau in ("VERT", "ORANGE"):
        verdict = RC.decider_sous_pression(niveau=niveau, arbre_octets=_ARBRE_GLOUTON,
                                           respirations_faites=0, **_ROUGE)
        assert verdict["action"] == RC.CONTINUER
        assert verdict["attente_s"] == 0.0


def test_un_arbre_IMMESURABLE_ne_fait_jamais_accuser_notre_travail():
    """psutil absent ou droits refuses => 0 octet mesure. Conclure « c'est nous » detruirait du
    travail sur une mesure MANQUANTE ; on conclut donc EXTERIEUR, qui ne detruit rien."""
    verdict = RC.decider_sous_pression(niveau="ROUGE", arbre_octets=0,
                                       respirations_faites=len(RC.PATIENCE_MEMOIRE_S), **_ROUGE)
    assert verdict["coupable"] == "EXTERIEUR"
    assert verdict["action"] == RC.CONTINUER


def test_l_attribution_de_la_pression_compte_la_memoire_UTILISEE():
    from hl_observer.ops import budget_ram as BR

    # 32 Go utilises sur 34, dont 20 a nous => c'est nous
    faute = BR.coupable_de_la_pression(arbre_octets=20 * 10**9, dispo_octets=2 * 10**9,
                                       total_octets=34 * 10**9)
    assert faute["coupable"] == "NOUS"
    assert faute["part_arbre"] > 0.6
    # la meme RAM libre, mais 0,02 Go a nous => ce n'est pas nous
    faute = BR.coupable_de_la_pression(arbre_octets=20 * 10**6, dispo_octets=2 * 10**9,
                                       total_octets=34 * 10**9)
    assert faute["coupable"] == "EXTERIEUR"
    assert faute["part_arbre"] < 0.01


def test_une_tache_rendue_ne_doit_pas_emporter_les_suivantes():
    """Le `break` du 16/11 privait trois taches de leur passage pour UNE tache lourde."""
    assert RC.ARRETS_MEMOIRE_AVANT_ABANDON >= 2


def test_lister_les_gros_consommateurs_n_agit_sur_AUCUN_processus():
    """Salad, le navigateur et WSL ne sont pas les sujets d'Alina : elle les nomme, point."""
    import inspect

    from hl_observer.ops import budget_ram as BR

    source = inspect.getsource(BR.plus_gros_consommateurs)
    # on cherche l'APPEL, pas le mot : le docstring dit justement « ne tue, ne suspend, ni ne
    # depriorise », et un test qui confond la prose et le code n'atteste rien.
    for appel in (".terminate(", ".kill(", ".suspend(", ".nice(", ".send_signal("):
        assert appel not in source, f"la liste des consommateurs ne doit JAMAIS appeler {appel}"
