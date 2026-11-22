"""LA TRANCHE DE TEMPS DU LABO : l'étape 2 chargeait tout le corpus et faisait couper le rejeu.

MESURES DU 18/11/2026 sur le corpus réel :
  fills   — 8 464 251 lignes à 3 754 octets  →  31,8 Go pour tout ;  1,54 Go pour le 18/11
  carnets — 7 527 878 lignes à 2 713 octets  →  20,4 Go pour tout ;  1,27 Go pour le 18/11

`run_local_campaign` accepte désormais une tranche `(depuis_ms, jusqu_a_ms)` et la fait descendre
aux DEUX chargeurs de l'étape 2. Le labo ne boucle pas lui-même sur les tranches : il en traite une.
La combinaison appartient à un conducteur séparé, pour qu'une agrégation ne soit jamais écrite à la
hâte dans le chemin économique.
"""
from __future__ import annotations

import inspect
import pathlib
import pytest
import pathlib

from hl_observer.backtesting import copy_vault_local_lab as local_lab


def test_run_local_campaign_accepte_une_tranche_et_elle_vaut_None_par_defaut():
    parametre = inspect.signature(local_lab.run_local_campaign).parameters["tranche"]
    assert parametre.default is None, "sans tranche, le comportement doit être inchangé"
    assert parametre.kind is inspect.Parameter.KEYWORD_ONLY, "jamais positionnel par accident"


def test_la_tranche_descend_AUX_DEUX_chargeurs_de_l_etape_2():
    """Un seul des deux bornés laisserait l'autre charger tout le corpus.

    22/11/2026 — CE TEST SUIT DÉSORMAIS UNE DÉLÉGATION. Le chargement des carnets passe par
    `chargement_en_deux_temps.charger_carnets_en_deux_temps` : les instants d'abord
    (0,084 Go mesurés), le contenu seulement si la séparation temporelle peut exister. Le
    chargement complet avait atteint **24,2 Go de RSS** sur 8 jours, RAM libre tombée à
    0,6 Go, alors que la porte qui refuse ensuite ne lit qu'un `ts_ms` par carnet.

    Le littéral `load_observed_books(` a donc quitté `run_local_campaign`. La propriété
    gardée est inchangée : la tranche doit atteindre les DEUX chargeurs. On la vérifie en
    suivant le relais, ce qui est PLUS strict qu'avant — on contrôle les deux maillons au
    lieu d'un seul texte.
    """
    from hl_observer.backtesting import chargement_en_deux_temps as deux_temps

    source = inspect.getsource(local_lab.run_local_campaign)
    entrees = source.index("charger_entrees_alpha_notional_fixe_avec_audit(")
    assert "fenetre=tranche" in source[entrees:entrees + 200]

    # Maillon 1 : la campagne passe la tranche au chargeur en deux temps.
    relais = source.index("charger_carnets_en_deux_temps(")
    assert "tranche=tranche" in source[relais:relais + 300]

    # Maillon 2 : le chargeur en deux temps borne CHACUNE de ses deux lectures.
    relayee = inspect.getsource(deux_temps.charger_carnets_en_deux_temps)
    assert relayee.count("depuis_ms=tranche[0] if tranche else None") == 2, (
        "les DEUX lectures (horloges, puis carnets complets) doivent être bornées")
    assert relayee.count("as_of_ms=tranche[1] if tranche else None") == 2


def test_les_deux_chargeurs_acceptent_REELLEMENT_ces_bornes():
    """L'inspection ci-dessus ne vaut que si les signatures appelées les portent vraiment."""
    from hl_observer.backtesting.copy_vault_book_loader import load_observed_books

    carnets = inspect.signature(load_observed_books).parameters
    assert "depuis_ms" in carnets and "as_of_ms" in carnets

    import tools.pipeline_copie_reel as PR

    fills = inspect.signature(PR.charger_entrees_alpha_notional_fixe_avec_audit).parameters
    assert "fenetre" in fills and fills["fenetre"].default is None
# ───────────────────────── le contrôle fonctionnel ─────────────────────────
# Les deux tests ci-dessus lisent le CODE. Celui-ci fait tourner la campagne et regarde ce que les
# chargeurs reçoivent vraiment : une inspection peut rester verte sur un appel mort.

def _workspace_minimal(tmp_path):
    import hashlib
    import json

    from tests.test_copy_vault_local_lab import _bind_fixture_safe_asset

    workspace = tmp_path / "workspace"
    data_dir = workspace / "runtime" / "data"
    data_dir.mkdir(parents=True)
    tapes = {}
    for nom in local_lab._MATERIALIZED_TAPE_NAMES:
        charge = b"{}" + bytes([10])
        (data_dir / nom).write_bytes(charge)
        tapes[nom] = {"bytes": len(charge), "sha256": hashlib.sha256(charge).hexdigest()}
    manifeste = _bind_fixture_safe_asset({
        "paper_read_only": True, "real_execution": False,
        "selection_digest": "a" * 64, "source_index_sha256": "b" * 64,
        "status": "READY", "safe_catalog_status": "SAFE_COMPLETE",
        "replay_inputs_available": True, "unique_fills": 2, "unique_books": 2,
        "data_complete": True, "materialized_tapes": tapes,
    })
    (workspace / "SAFE_INPUT_MANIFEST.json").write_text(json.dumps(manifeste), encoding="utf-8")
    return workspace


def test_la_tranche_arrive_VRAIMENT_aux_deux_chargeurs(tmp_path, monkeypatch):
    instants = [10 * 86_400_000 + 10_000, 11 * 86_400_000 + 10_000]
    metaordres = [{"signal_ts_ms": t, "action": "ADD", "coin": "BTC"} for t in instants]
    carnets = {"BTC": [{"ts_ms": t - 1_000} for t in instants]}
    recus = {}

    class Pipeline:
        @staticmethod
        def charger_entrees_alpha_notional_fixe_avec_audit(_workspace, **kw):
            recus["fills"] = kw.get("fenetre")
            return [], {}

        @staticmethod
        def charger_evenements_lifecycle_avec_audit(_workspace):
            return [], {}

    def faux_carnets(*_a, **kw):
        recus["carnets"] = (kw.get("depuis_ms"), kw.get("as_of_ms"))
        return carnets, {}

    monkeypatch.setattr(local_lab, "_load_pipeline", lambda: Pipeline())
    monkeypatch.setattr(local_lab.cv, "cluster_metaorders", lambda _e: (metaordres, {}))
    monkeypatch.setattr(local_lab.cv, "load_observed_books", faux_carnets)

    workspace = _workspace_minimal(tmp_path)
    local_lab.run_local_campaign(
        workspace, repository_root=tmp_path, campaign_root=tmp_path / "campagne",
        max_trials=1, tranche=(instants[0], instants[0] + 86_399_999),
    )
    assert recus["fills"] == (instants[0], instants[0] + 86_399_999)
    assert recus["carnets"] == (instants[0], instants[0] + 86_399_999)


def test_SANS_tranche_les_chargeurs_ne_recoivent_aucune_borne(tmp_path, monkeypatch):
    """La non-régression qui compte : un labo appelé comme avant doit lire comme avant."""
    instants = [10 * 86_400_000 + 10_000, 11 * 86_400_000 + 10_000]
    metaordres = [{"signal_ts_ms": t, "action": "ADD", "coin": "BTC"} for t in instants]
    recus = {}

    class Pipeline:
        @staticmethod
        def charger_entrees_alpha_notional_fixe_avec_audit(_workspace, **kw):
            recus["fills"] = kw.get("fenetre", "ABSENT")
            return [], {}

        @staticmethod
        def charger_evenements_lifecycle_avec_audit(_workspace):
            return [], {}

    def faux_carnets(*_a, **kw):
        recus["carnets"] = (kw.get("depuis_ms", "ABSENT"), kw.get("as_of_ms", "ABSENT"))
        return {"BTC": [{"ts_ms": t - 1_000} for t in instants]}, {}

    monkeypatch.setattr(local_lab, "_load_pipeline", lambda: Pipeline())
    monkeypatch.setattr(local_lab.cv, "cluster_metaorders", lambda _e: (metaordres, {}))
    monkeypatch.setattr(local_lab.cv, "load_observed_books", faux_carnets)

    local_lab.run_local_campaign(
        _workspace_minimal(tmp_path), repository_root=tmp_path,
        campaign_root=tmp_path / "campagne", max_trials=1,
    )
    assert recus["fills"] is None
    assert recus["carnets"] == (None, None)
# ───────── l'identité de campagne : deux tranches ne partagent pas leur historique ─────────
# Défaut trouvé le 18/11 AVANT d'avoir conduit la première tranche. `selection_digest` identifie
# la SOURCE et ne change pas d'une tranche à l'autre : sans la tranche dans le nom du dossier, les
# dix-neuf tranches partageaient TRIALS.jsonl, ATTEMPTS.jsonl et CHECKPOINT.json.

def test_deux_tranches_ont_des_noms_de_campagne_DIFFERENTS():
    """Sinon `seen` est commun et la tranche 2 saute les paramètres essayés sur la tranche 1."""
    a = local_lab._nom_de_campagne("d" * 64, (1_000, 1_999))
    b = local_lab._nom_de_campagne("d" * 64, (2_000, 2_999))
    assert a != b
    assert a.startswith("d" * 64) and "1000" in a and "1999" in a


def test_SANS_tranche_le_nom_de_campagne_est_EXACTEMENT_l_ancien():
    """La non-régression qui protège les reçus déjà scellés."""
    assert local_lab._nom_de_campagne("e" * 64, None) == "e" * 64


def test_la_meme_tranche_donne_TOUJOURS_le_meme_nom():
    """Sans quoi une reprise ne retrouverait pas sa propre campagne."""
    assert (local_lab._nom_de_campagne("f" * 64, (7, 9))
            == local_lab._nom_de_campagne("f" * 64, (7, 9)))


def test_le_selection_digest_n_est_PAS_modifie_par_la_tranche():
    """Il est vérifié contre le manifeste et scellé dans les reçus : y toucher les invaliderait."""
    nom = local_lab._nom_de_campagne("a" * 64, (1, 2))
    assert nom.split("-")[0] == "a" * 64, "le digest reste intact en tête du nom"


def test_la_racine_par_defaut_du_labo_passe_par_le_nom_de_campagne():
    source = inspect.getsource(local_lab.run_local_campaign)
    extrait = source[source.index("campaign_root = Path(campaign_root)"):][:400]
    assert "_nom_de_campagne(selection_digest, tranche)" in extrait


def test_le_conducteur_derive_une_racine_PAR_TRANCHE(tmp_path, monkeypatch):
    """Et il le fait vraiment : vérifié sur l'appel, pas sur le code."""
    from tools import conduire_labo_par_tranches as CD

    vues = []

    def faux_labo(_workspace, **kw):
        vues.append(kw.get("campaign_root"))
        return {"status": "MORE_DATA"}

    import hl_observer.backtesting.copy_vault_local_lab as module

    monkeypatch.setattr(module, "run_local_campaign", faux_labo)
    lancer = CD._lanceur_reel(1, tmp_path / "campagne", tmp_path)
    lancer(tmp_path, (1_000, 1_999))
    lancer(tmp_path, (2_000, 2_999))
    assert vues[0] != vues[1], "deux tranches, deux dossiers"
    assert vues[0].name == "t1000-1999" and vues[1].name == "t2000-2999"


def test_le_conducteur_laisse_le_labo_decider_quand_aucune_racine_n_est_donnee(tmp_path, monkeypatch):
    from tools import conduire_labo_par_tranches as CD

    vues = []
    import hl_observer.backtesting.copy_vault_local_lab as module

    monkeypatch.setattr(
        module, "run_local_campaign",
        lambda _w, **kw: vues.append(kw.get("campaign_root")) or {"status": "MORE_DATA"})
    CD._lanceur_reel(1, None, tmp_path)(tmp_path, (1, 2))
    assert vues == [None], "le labo appliquera `_nom_de_campagne` lui-même"
def test_AUCUN_double_de_test_n_est_fige_sur_l_ancienne_signature():
    """Le garde-fou contre un piège qui s'est produit TROIS fois le 18/11/2026.

    Chaque fois que la signature d'un chargeur de production gagne un paramètre, les classes et
    lambdas qui le doublent dans les tests lèvent `TypeError` — et un double figé est un test qui
    ne vérifie plus ce qu'il croit vérifier. Trois fichiers ont été touchés successivement
    (`test_copy_vault_local_lab`, `test_pipeline_copie_reel`, `test_copy_vault_campaign_lock`), et
    chacun a été découvert par une suite rouge plutôt que d'un coup.

    La règle : un double de ces fonctions accepte `**kwargs`, donc il reste indifférent aux
    paramètres qu'il n'examine pas. Ce test échouera au prochain double écrit sans.
    """
    import re

    racine = pathlib.Path(__file__).resolve().parent
    surveilles = (
        "charger_entrees_alpha_notional_fixe_avec_audit",
        "_reconstruire_episodes_canoniques",
        "load_observed_books",
        # ajoute apres un 4e cas le meme jour : les doubles de ce compteur avaient la
        # signature `(root, *, exclude_selection_digest)` et ont leve des que le
        # correctif d'essais multiples a recu `exclude_campaign_name`.
        "_prior_copy_vault_trial_count",
    )
    figes: list[str] = []
    for fichier in sorted(racine.glob("test_*.py")):
        texte = fichier.read_text(encoding="utf-8", errors="ignore")
        for nom in surveilles:
            # une définition de double : `def <nom>(...)` suivie d'une liste de paramètres sans **
            for trouve in re.finditer(rf"def {re.escape(nom)}\(([^)]*)\)", texte):
                if "**" not in trouve.group(1):
                    ligne = texte[:trouve.start()].count(chr(10)) + 1
                    figes.append(f"{fichier.name}:{ligne} def {nom}({trouve.group(1)})")
            # un lambda qui le remplace : `setattr(..., "<nom>", lambda ...)` sans **
            for trouve in re.finditer(
                rf'"{re.escape(nom)}",\s*lambda ([^:]*):', texte
            ):
                if "**" not in trouve.group(1):
                    ligne = texte[:trouve.start()].count(chr(10)) + 1
                    figes.append(f"{fichier.name}:{ligne} lambda {trouve.group(1)}")
    separateur = chr(10) + '  '
    assert not figes, (
        'double(s) de test fige(s) sur une signature : ajoutez **_kw.'
        + separateur + separateur.join(figes)
    )
# ───────── LA LIMITE DE LA CONDUITE PAR TRANCHES, prouvée et non cachée ─────────
# `_MINIMUM_SIGNAL_UTC_DAYS = 6` est une porte appliquée À CHAQUE APPEL. Une tranche dure de 4 à
# 11 heures : elle ne couvre jamais six journées UTC. Les dix-neuf tranches rendent donc toutes
# `MORE_DATA / INSUFFICIENT_DISTINCT_SIGNAL_DAYS` SANS RIEN EXPLORER.
#
# Ce test ne corrige rien : il FIXE le constat, pour qu'on ne croie pas la conduite capable de
# chercher alors qu'elle s'arrête avant. La conception juste est écrite au journal du 18/11 : une
# tranche doit PRODUIRE des trades, et c'est l'agrégat qui compte les jours et décide —
# `agregation_tranches.unir_les_jours` existe déjà pour cela.

def test_une_tranche_COURTE_s_arrete_avant_la_recherche(tmp_path, monkeypatch):
    """La preuve du constat : un seul jour de signaux, et le labo refuse de chercher."""
    jour = 10 * 86_400_000
    instants = [jour + 10_000, jour + 20_000]          # deux signaux, UNE journée UTC
    metaordres = [{"signal_ts_ms": t, "action": "ADD", "coin": "BTC"} for t in instants]
    carnets = {"BTC": [{"ts_ms": t - 1_000} for t in instants]}

    class Pipeline:
        @staticmethod
        def charger_entrees_alpha_notional_fixe_avec_audit(_workspace, **_kw):
            return [], {}

        @staticmethod
        def charger_evenements_lifecycle_avec_audit(_workspace):
            return [], {}

    monkeypatch.setattr(local_lab, "_load_pipeline", lambda: Pipeline())
    monkeypatch.setattr(local_lab.cv, "cluster_metaorders", lambda _e: (metaordres, {}))
    monkeypatch.setattr(local_lab.cv, "load_observed_books", lambda *_a, **_k: (carnets, {}))

    resultat = local_lab.run_local_campaign(
        _workspace_minimal(tmp_path), repository_root=tmp_path,
        campaign_root=tmp_path / "campagne", max_trials=1,
        tranche=(jour, jour + 86_399_999),
    )
    assert resultat["status"] == "MORE_DATA"
    assert resultat["reason"] == "INSUFFICIENT_DISTINCT_SIGNAL_DAYS"
    assert resultat["candidates_tested"] == 0, "aucune exploration n'a eu lieu"
    assert resultat["signal_coverage"]["distinct_utc_days"] == 1
    assert resultat["signal_coverage"]["minimum_utc_days_required"] == 6


def test_le_seuil_JUGE_L_ENSEMBLE_quand_on_lui_donne_les_journees_du_corpus():
    """Ce test constatait d'abord le defaut ; il exige maintenant sa correction.

    Avant : les trois portes comparaient `_MINIMUM_SIGNAL_UTC_DAYS` aux journees de la TRANCHE,
    donc une tranche de 4 a 11 heures etait toujours recalee sans explorer un candidat.
    Apres : elles comparent `jours_juges` / `jours_evaluables_juges`, qui valent les journees du
    CORPUS quand une tranche est en cours et que ce nombre est fourni -- le niveau juste, puisque
    le seuil dit « on ne conclut pas sur moins de six jours » et qu'une tranche ne conclut pas.
    """
    source = inspect.getsource(local_lab.run_local_campaign)
    assert local_lab._MINIMUM_SIGNAL_UTC_DAYS == 6
    # Les trois portes passent par les grandeurs JUGEES, et contre `seuil_jours` -- qui vaut la
    # constante par defaut et peut etre abaisse par le manifeste. ACTUALISE le 19/11/2026 : ces
    # deux lignes comptaient la constante, et comparer la constante en dur faisait ignorer la
    # surcharge a la porte de l'exploration overshoot (6 journees exigees contre 3 ailleurs).
    assert source.count("jours_evaluables_juges < seuil_jours") == 2
    assert source.count("jours_juges < seuil_jours") == 1
    # et aucune ne compare plus directement les journees de la tranche
    assert "distinct_utc_days\"] < _MINIMUM_SIGNAL_UTC_DAYS" not in source
    assert "evaluable_utc_days\"] < _MINIMUM_SIGNAL_UTC_DAYS" not in source
    # l'ouverture exige une tranche ET un nombre entier strictement positif
    assert "tranche is not None and type(jours_du_corpus) is int and jours_du_corpus > 0" in source

def test_l_agregat_sait_DEJA_unir_les_jours_des_tranches():
    """La brique qui rendra le seuil applicable à l'ensemble est en place, et testée ailleurs."""
    from hl_observer.backtesting import agregation_tranches as AG

    rapports = [
        {"signal_coverage": {"utc_days": [f"2026-11-{13 + index:02d}"]}} for index in range(6)
    ]
    assert AG.unir_les_jours(rapports)["distincts"] == 6
# ───────── LE MODE « PRODUIRE SANS JUGER » : la porte au bon niveau ─────────

def _lancer_une_tranche(tmp_path, monkeypatch, **kw):
    """Une tranche d'UNE journée UTC, avec des doubles minimaux."""
    jour = 10 * 86_400_000
    instants = [jour + 10_000, jour + 20_000]
    metaordres = [{"signal_ts_ms": t, "action": "ADD", "coin": "BTC"} for t in instants]
    carnets = {"BTC": [{"ts_ms": t - 1_000} for t in instants]}

    class Pipeline:
        @staticmethod
        def charger_entrees_alpha_notional_fixe_avec_audit(_workspace, **_kw):
            return [], {}

        @staticmethod
        def charger_evenements_lifecycle_avec_audit(_workspace):
            return [], {}

    monkeypatch.setattr(local_lab, "_load_pipeline", lambda: Pipeline())
    monkeypatch.setattr(local_lab.cv, "cluster_metaorders", lambda _e: (metaordres, {}))
    monkeypatch.setattr(local_lab.cv, "load_observed_books", lambda *_a, **_k: (carnets, {}))
    return local_lab.run_local_campaign(
        _workspace_minimal(tmp_path), repository_root=tmp_path,
        campaign_root=tmp_path / "campagne", max_trials=1, **kw)


def test_avec_les_journees_du_CORPUS_la_porte_des_six_jours_s_ouvre(tmp_path, monkeypatch):
    """Le point de la correction : la tranche n'est plus recalée pour un seuil qui vise l'ensemble."""
    jour = 10 * 86_400_000
    resultat = _lancer_une_tranche(
        tmp_path, monkeypatch, tranche=(jour, jour + 86_399_999), jours_du_corpus=6)
    assert resultat["reason"] != "INSUFFICIENT_DISTINCT_SIGNAL_DAYS"
    assert resultat["reason"] != "INSUFFICIENT_EVALUABLE_SIGNAL_DAYS"
    assert resultat["signal_coverage"]["distinct_utc_days"] == 1, "la tranche reste honnête sur CE qu'elle couvre"
    assert resultat["jours_du_corpus"] == 6


def test_un_rapport_de_tranche_se_declare_PARTIEL(tmp_path, monkeypatch):
    """Sans cette marque, une mesure de quatre heures se lirait comme une conclusion."""
    jour = 10 * 86_400_000
    resultat = _lancer_une_tranche(
        tmp_path, monkeypatch, tranche=(jour, jour + 86_399_999), jours_du_corpus=6)
    assert resultat["verdict_partiel"] is True
    assert resultat["tranche"] == [jour, jour + 86_399_999]
    assert resultat["economically_proven"] is False


def test_SANS_tranche_le_rapport_n_est_PAS_partiel(tmp_path, monkeypatch):
    resultat = _lancer_une_tranche(tmp_path, monkeypatch)
    assert resultat["verdict_partiel"] is False and resultat["tranche"] is None


def test_les_journees_du_corpus_SANS_tranche_n_ouvrent_PAS_la_porte(tmp_path, monkeypatch):
    """Garde-fou : on ne peut pas desserrer le seuil d'une campagne entière en l'annonçant."""
    resultat = _lancer_une_tranche(tmp_path, monkeypatch, jours_du_corpus=6)
    assert resultat["reason"] == "INSUFFICIENT_DISTINCT_SIGNAL_DAYS"
    assert resultat["candidates_tested"] == 0


def test_des_journees_du_corpus_INSUFFISANTES_laissent_la_porte_fermee(tmp_path, monkeypatch):
    """Le seuil n'est pas contourné : il est appliqué au corpus, et le corpus doit le franchir."""
    jour = 10 * 86_400_000
    resultat = _lancer_une_tranche(
        tmp_path, monkeypatch, tranche=(jour, jour + 86_399_999), jours_du_corpus=5)
    assert resultat["reason"] == "INSUFFICIENT_DISTINCT_SIGNAL_DAYS"


@pytest.mark.parametrize("mauvais", (0, -1, 6.0, "6", True, None))
def test_une_valeur_de_journees_INVALIDE_laisse_la_porte_fermee(tmp_path, monkeypatch, mauvais):
    """Un `True` vaudrait 1 en arithmétique : il ne doit pas passer pour un nombre de jours."""
    jour = 10 * 86_400_000
    resultat = _lancer_une_tranche(
        tmp_path, monkeypatch, tranche=(jour, jour + 86_399_999), jours_du_corpus=mauvais)
    assert resultat["reason"] == "INSUFFICIENT_DISTINCT_SIGNAL_DAYS"


def test_les_TROIS_portes_utilisent_les_journees_jugees():
    """Dont celle qui garde l'exploration overshoot, qui LÈVE au lieu de rendre.

    ACTUALISÉ le 19/11/2026, et il avait raison de rougir. Les trois portes comparaient la
    constante `_MINIMUM_SIGNAL_UTC_DAYS`, jusqu'à ce que le seuil devienne surchargeable par le
    manifeste (`seuil_jours`). Deux portes ont suivi, **la troisième non** : celle qui garde
    l'exploration overshoot exigeait donc 6 journées là où les deux autres en demandaient 3, et
    sautait silencieusement l'exploration sur un corpus que le reste du labo acceptait.

    Ce test ne compte donc plus une constante, il verrouille ce qui compte vraiment : les TROIS
    portes jugent sur les journées JUGÉES et contre LE MÊME seuil. Compter un nom de variable
    aurait de nouveau rougi au prochain renommage sans rien protéger de plus.
    """
    source = inspect.getsource(local_lab.run_local_campaign)
    assert source.count("jours_evaluables_juges < seuil_jours") == 2
    assert source.count("jours_juges < seuil_jours") == 1
    # Le seuil reste ANCRÉ sur la constante : surchargeable, jamais inventé.
    assert "seuil_jours = int(input_manifest.get(\"minimum_signal_utc_days\")" in source
    assert "or _MINIMUM_SIGNAL_UTC_DAYS)" in source
    # Et aucune porte ne juge sur le compte BRUT, qui ignore les journées réellement évaluables.
    assert "alignment[\"summary\"][\"evaluable_utc_days\"] < _MINIMUM" not in source
    assert "jours_evaluables_juges < _MINIMUM_SIGNAL_UTC_DAYS" not in source, (
        "une porte qui compare la constante ignore la surcharge du manifeste"
    )
# ───────── une tranche n'écrit pas le champion déployé ─────────
# `runtime/champion_deploye.json` est un chemin UNIQUE et le cliquet labo → moteur. Dix-neuf
# tranches s'y écraseraient l'une l'autre, et le fichier final porterait un candidat choisi sur
# quatre à onze heures, présenté comme déployable. L'écriture étant atomique, l'écrasement serait
# proprement irréversible — et rien dans le fichier ne dirait sur quelle fenêtre il a été choisi.

def test_une_tranche_REFUSE_d_ecrire_le_champion_deploye():
    source = inspect.getsource(local_lab.run_local_campaign)
    assert "if best is not None and tranche is not None:" in source
    debut = source.index("if best is not None and tranche is not None:")
    bloc = source[debut:debut + 900]
    assert 'champion_deploye_refuse = "VERDICT_PARTIEL_TRANCHE"' in bloc
    assert "_ecrire_champion_deploye" not in bloc.split("elif best is not None:")[0], (
        "aucune écriture ne doit avoir lieu dans la branche de la tranche")


def test_SANS_tranche_le_champion_est_toujours_ecrit():
    """La non-régression : une campagne complète garde son cliquet."""
    source = inspect.getsource(local_lab.run_local_campaign)
    apres = source[source.index("elif best is not None:"):]
    assert "_ecrire_champion_deploye(" in apres[:400]


def test_le_refus_est_PUBLIE_dans_le_rapport():
    """Un refus silencieux se lirait comme « aucun candidat trouvé »."""
    source = inspect.getsource(local_lab.run_local_campaign)
    assert '"champion_deploye_refuse": champion_deploye_refuse' in source


def test_le_cliquet_vit_dans_son_module_et_reste_importable_du_labo():
    from hl_observer.backtesting import copy_vault_champion_deploye as CH

    assert local_lab._ecrire_champion_deploye is CH._ecrire_champion_deploye
    assert local_lab.charger_champion_deploye is CH.charger_champion_deploye
    assert local_lab.CHEMIN_CHAMPION_DEPLOYE == CH.CHEMIN_CHAMPION_DEPLOYE
    assert "CHEMIN_CHAMPION_DEPLOYE" in local_lab.__all__

