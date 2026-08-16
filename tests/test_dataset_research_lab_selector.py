from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.datasets.research_lab_selector import (
    load_research_profile,
    select_research_files,
    write_research_selection,
)
from hl_observer.datasets.research_lab_stream import REPORT_JSON


def _profile() -> dict:
    return {
        "schema": "hypersmart.research_lab_stream_profile.v1",
        "root": "X",
        "files": [
            {
                "relative_path": "runtime/research_lab/a/episodes.jsonl",
                "source_size": 10 * 1024**3,
                "timestamp_min_ms": 1_000,
                "timestamp_max_ms": 2_000,
                "complete": True,
                "checkpoint": "a.json",
                "family_counts": {"copy_vault": 100},
                "coin_counts": {"BTC": 80},
                "metrics": {"net_pnl_usd": {"count": 50}},
            },
            {
                "relative_path": "runtime/research_lab/b/working_set.jsonl",
                "source_size": 5 * 1024**3,
                "timestamp_min_ms": 3_000,
                "timestamp_max_ms": 4_000,
                "complete": False,
                "checkpoint": "b.json",
                "family_counts": {"lead_lag": 200},
                "coin_counts": {"ETH": 150},
                "metrics": {"edge_remaining_bps": {"count": 90}},
            },
            {
                "relative_path": "runtime/research_lab/c/legacy.jsonl",
                "source_size": 2 * 1024**3,
                "timestamp_min_ms": None,
                "timestamp_max_ms": None,
                "complete": True,
                "checkpoint": "c.json",
                "family_counts": {},
                "coin_counts": {},
                "metrics": {},
            },
        ],
    }


def test_selector_cible_periode_famille_coin_et_metrique() -> None:
    selection = select_research_files(
        _profile(),
        start_ms=900,
        end_ms=2_100,
        family="copy_vault",
        coin="btc",
        metric="net_pnl_usd",
        include_unknown_time=False,
    )

    assert selection["selected_file_count"] == 1
    assert selection["files"][0]["relative_path"].endswith("a/episodes.jsonl")
    assert selection["files"][0]["selection_uncertain"] is False
    assert selection["raw_events_copied"] is False


def test_selector_inclut_les_dates_inconnues_par_defaut_sans_les_faire_passer_pour_certaines() -> None:
    selection = select_research_files(
        _profile(),
        start_ms=900,
        end_ms=2_100,
        family="copy_vault",
    )

    assert selection["selected_file_count"] == 2
    uncertain = [item for item in selection["files"] if item["selection_uncertain"]]
    assert len(uncertain) == 1
    assert uncertain[0]["relative_path"].endswith("c/legacy.jsonl")
    assert selection["uncertain_selected_file_count"] == 1


def test_selector_require_complete_exclut_les_checkpoints_partiels() -> None:
    selection = select_research_files(
        _profile(),
        family="lead_lag",
        require_complete=True,
    )

    # b contient lead_lag mais est partiel; c reste inclus par prudence car son compteur est inconnu.
    assert selection["rejected_counts"]["incomplete"] == 1
    assert all(not item["relative_path"].endswith("b/working_set.jsonl") for item in selection["files"])


def test_selector_refuse_une_periode_inversee() -> None:
    with pytest.raises(ValueError):
        select_research_files(_profile(), start_ms=2_000, end_ms=1_000)


def test_selection_ecrite_est_reproductible_et_ne_copie_pas_les_evenements(tmp_path: Path) -> None:
    report = tmp_path / REPORT_JSON
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(_profile()), encoding="utf-8")

    # La période explicite rend le rejet du fichier legacy sans horodatage déterministe.
    # Sans filtre temporel, l'inconnu est volontairement conservé plutôt qu'assimilé à absent.
    kwargs = {
        "start_ms": 900,
        "end_ms": 2_100,
        "family": "copy_vault",
        "coin": "BTC",
        "metric": "net_pnl_usd",
        "include_unknown_time": False,
    }
    first_path, current, first = write_research_selection(tmp_path, **kwargs)
    second_path, _, second = write_research_selection(tmp_path, **kwargs)

    assert first["selection_digest"] == second["selection_digest"]
    assert first_path == second_path
    assert current.is_file()
    assert first["selected_file_count"] == 1
    assert first["uncertain_selected_file_count"] == 0
    assert "family_counts" not in json.dumps(first["files"])


def test_loader_explique_si_le_profil_n_existe_pas(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="dataset_research_inventory"):
        load_research_profile(tmp_path)
