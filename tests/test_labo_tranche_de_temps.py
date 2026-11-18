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

from hl_observer.backtesting import copy_vault_local_lab as local_lab


def test_run_local_campaign_accepte_une_tranche_et_elle_vaut_None_par_defaut():
    parametre = inspect.signature(local_lab.run_local_campaign).parameters["tranche"]
    assert parametre.default is None, "sans tranche, le comportement doit être inchangé"
    assert parametre.kind is inspect.Parameter.KEYWORD_ONLY, "jamais positionnel par accident"


def test_la_tranche_descend_AUX_DEUX_chargeurs_de_l_etape_2():
    """Un seul des deux bornés laisserait l'autre charger tout le corpus."""
    source = inspect.getsource(local_lab.run_local_campaign)
    entrees = source.index("charger_entrees_alpha_notional_fixe_avec_audit(")
    carnets = source.index("load_observed_books(")
    assert "fenetre=tranche" in source[entrees:entrees + 200]
    extrait = source[carnets:carnets + 300]
    assert "depuis_ms=tranche[0] if tranche else None" in extrait
    assert "as_of_ms=tranche[1] if tranche else None" in extrait


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

