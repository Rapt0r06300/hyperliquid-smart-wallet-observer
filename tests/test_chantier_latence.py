"""L'outil chantier-latence trouve le dernier espace de travail du labo et refuse proprement s'il n'y en a pas."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("chantier_latence", RACINE / "tools" / "chantier_latence.py")
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(RACINE))
    sys.path.insert(0, str(RACINE / "src"))
    spec.loader.exec_module(m)
    return m


L = _mod()


def test_prend_le_workspace_le_plus_recent(tmp_path):
    base = tmp_path / "runtime" / "reports" / "copy_vault_quant_lab"
    for nom in ("20261111T000000000000Z", "20261112T120000000000Z"):
        ws = base / nom / "workspace" / "runtime" / "data"
        ws.mkdir(parents=True)
        (base / nom / "workspace" / "SAFE_INPUT_MANIFEST.json").write_text("{}", encoding="utf-8")
    choisi = L._dernier_workspace(tmp_path)
    assert choisi is not None and choisi.parent.name == "20261112T120000000000Z"


def test_ignore_un_run_sans_workspace(tmp_path):
    base = tmp_path / "runtime" / "reports" / "copy_vault_quant_lab"
    (base / "20261112T120000000000Z").mkdir(parents=True)        # run sans workspace
    ok = base / "20261111T000000000000Z" / "workspace" / "runtime" / "data"
    ok.mkdir(parents=True)
    assert L._dernier_workspace(tmp_path).parent.name == "20261111T000000000000Z"


def test_main_sans_workspace(tmp_path, capsys):
    assert L.main(["--root", str(tmp_path)]) == 2
    assert "aucun espace de travail" in capsys.readouterr().out


def _resume_de_test():
    def ms(value):
        return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)

    return {
        "fill_start_ms": ms("2026-11-01T00:00:00"),
        "fill_end_ms": ms("2026-11-18T17:00:00"),
        "book_start_ms": ms("2026-11-01T00:00:00"),
        "book_end_ms": ms("2026-11-18T17:00:00"),
    }


def test_derniere_journee_utc_complete_reserve_horizon_et_delai_l2():
    resume = _resume_de_test()
    debut, fin = L.derniere_journee_utc_complete(resume, horizon_ms=300_000)
    assert datetime.fromtimestamp(debut / 1000, timezone.utc).isoformat() == "2026-11-17T00:00:00+00:00"
    assert datetime.fromtimestamp((fin + 1) / 1000, timezone.utc).isoformat() == "2026-11-18T00:00:00+00:00"
    assert fin + 300_000 + 120_000 <= resume["book_end_ms"]


def test_bornes_carnets_incluent_reference_et_sortie_du_replay():
    debut = 1_800_000_000_000
    fin = debut + 3_600_000 - 1
    assert L.bornes_carnets_pour_fenetre((debut, fin), horizon_ms=300_000) == (
        debut - 120_000,
        fin + 300_000 + 120_000,
    )


def test_fenetre_explicite_refuse_tout_debordement_de_couverture():
    resume = _resume_de_test()
    with pytest.raises(ValueError, match="horizon"):
        L._bornes_validees(resume, (resume["fill_start_ms"], resume["fill_start_ms"]), horizon_ms=0)
    with pytest.raises(ValueError, match="24 heures"):
        L._bornes_validees(resume, (resume["fill_start_ms"], resume["fill_start_ms"] + 86_400_000), horizon_ms=1)
    with pytest.raises(ValueError, match="L2 ne couvre pas"):
        L._bornes_validees(resume, (resume["fill_end_ms"] - 3_600_000, resume["fill_end_ms"]), horizon_ms=300_000)


def test_manifest_safe_est_classe_exploratoire_si_incomplet(tmp_path):
    workspace = tmp_path / "workspace"
    data = workspace / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "vault_fills_live.jsonl").write_text("{}\n", encoding="utf-8")
    (data / "copy_vault_l2_tape.jsonl").write_text("{}\n", encoding="utf-8")
    manifest = {
        "status": "MORE_DATA", "reason": "CONTINUITY_UNPROVEN", "data_complete": False,
        "continuity_evidence_status": "UNPROVEN", "payload_rejected_records": 2,
        "safe_catalog_status": "SAFE_COMPLETE", "safe_replay_inputs_available": True,
        "replay_inputs_available": True, "paper_read_only": True, "real_execution": False,
        "expected_safe_shards": 10, "verified_safe_shards": 10,
        "source_asset_inventory_count": 10, "source_asset_inventory_complete": True,
        "missing_count": 0, "rejected_count": 0, "unique_fills": 4, "unique_books": 5,
        **_resume_de_test(),
    }
    (workspace / "SAFE_INPUT_MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    audit = L._resume_manifest_safe(workspace)

    assert audit["corpus_readiness"] == "PARTIAL_EXPLORATORY_INPUTS"
    assert audit["economic_evidence_status"] == "EXPLORATORY_NON_OOS"
    assert audit["promotion_allowed"] is False
    assert audit["verified_safe_shards"] == 10


def test_manifest_refuse_execution_active_or_inventaire_incomplet(tmp_path):
    workspace = tmp_path / "workspace"
    data = workspace / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "vault_fills_live.jsonl").write_text("{}\n", encoding="utf-8")
    (data / "copy_vault_l2_tape.jsonl").write_text("{}\n", encoding="utf-8")
    manifest = {
        "safe_catalog_status": "SAFE_COMPLETE", "safe_replay_inputs_available": True,
        "replay_inputs_available": True, "paper_read_only": True, "real_execution": True,
        "expected_safe_shards": 10, "verified_safe_shards": 9,
        "source_asset_inventory_count": 10, "source_asset_inventory_complete": True,
        "missing_count": 0, "rejected_count": 0, "unique_fills": 4, "unique_books": 5,
        **_resume_de_test(),
    }
    (workspace / "SAFE_INPUT_MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="real_execution_disabled|safe_shards_match"):
        L._resume_manifest_safe(workspace)


def _simuler_chargement_latence(monkeypatch, *, metaorders):
    import importlib.machinery
    import importlib.util

    from hl_observer.backtesting import copy_vault_executable as cv

    class FauxLoader:
        def create_module(self, spec):
            return None

        def exec_module(self, module):
            module.charger_entrees_alpha_notional_fixe_avec_audit = (
                lambda workspace, *, fenetre: ([], {
                    "decoupe_sure": True,
                    "episode_source": "vault_fills_deduped_reconstructed",
                    "fenetre_fills": list(fenetre),
                })
            )

    monkeypatch.setattr(
        importlib.util,
        "spec_from_file_location",
        lambda *args, **kwargs: importlib.machinery.ModuleSpec(
            "pipeline_latence", FauxLoader()
        ),
    )
    monkeypatch.setattr(cv, "cluster_metaorders", lambda entries: (metaorders, {}))
    return cv


def test_chargeur_transmet_fenetre_de_fills_et_bornes_l2(monkeypatch, tmp_path):
    debut = 1_800_000_000_000
    fin = debut + 3_600_000 - 1
    cv = _simuler_chargement_latence(monkeypatch, metaorders=[{"coin": "BTC"}])
    appels = []

    def faux_loader(workspace, **kwargs):
        appels.append((workspace, kwargs))
        return {"BTC": []}, {"rows_read": 3, "valid_rows": 0}

    monkeypatch.setattr(cv, "load_observed_books", faux_loader)

    metaorders, books, audit = L.charger_metaordres_et_carnets(
        tmp_path, fenetre_ms=(debut, fin), horizon_ms=300_000
    )

    assert metaorders == [{"coin": "BTC"}]
    assert books == {"BTC": []}
    assert audit["entries"]["fenetre_fills"] == [debut, fin]
    assert appels[0][1]["depuis_ms"] == debut - 120_000
    assert appels[0][1]["as_of_ms"] == fin + 300_000 + 120_000


def test_chargeur_ne_scannera_pas_l2_sans_metaordre(monkeypatch, tmp_path):
    debut = 1_800_000_000_000
    fin = debut + 60_000
    cv = _simuler_chargement_latence(monkeypatch, metaorders=[])
    monkeypatch.setattr(
        cv,
        "load_observed_books",
        lambda *args, **kwargs: pytest.fail("aucun signal : ne pas parcourir le ruban L2"),
    )

    metaorders, books, audit = L.charger_metaordres_et_carnets(
        tmp_path, fenetre_ms=(debut, fin), horizon_ms=300_000
    )

    assert metaorders == []
    assert books == {}
    assert audit["books"]["skipped"] is True
    assert audit["books"]["skip_reason"] == "NO_METAORDERS_IN_WINDOW"
