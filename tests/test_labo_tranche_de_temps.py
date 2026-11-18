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

