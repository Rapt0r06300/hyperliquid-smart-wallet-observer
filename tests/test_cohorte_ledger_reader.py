import json

from hl_observer.ui.cohorte_ledger_reader import LEDGERS_COHORTES, lire_ledgers_cohortes


def test_lit_les_ledgers_de_cohortes_presents(tmp_path):
    (tmp_path / LEDGERS_COHORTES["ALPHA"]).write_text(
        json.dumps({"ev": "OPEN"}) + "\n" + json.dumps({"ev": "CLOSE"}) + "\n", encoding="utf-8")
    (tmp_path / LEDGERS_COHORTES["RAW_PROBE"]).write_text(json.dumps({"ev": "OPEN"}) + "\n", encoding="utf-8")
    r = lire_ledgers_cohortes(tmp_path)
    assert r["ALPHA"]["present"] and r["ALPHA"]["n"] == 2
    assert r["RAW_PROBE"]["present"] and r["RAW_PROBE"]["n"] == 1
    assert r["DISCOVERY_PROBE"]["present"] is False and r["DISCOVERY_PROBE"]["n"] == 0
    assert r["_cohortes_disponibles"] == ["ALPHA", "RAW_PROBE"]


def test_dossier_vide_aucune_cohorte(tmp_path):
    r = lire_ledgers_cohortes(tmp_path)
    assert r["_cohortes_disponibles"] == []
    assert all(r[c]["n"] == 0 for c in LEDGERS_COHORTES)


def test_ignore_lignes_jsonl_corrompues(tmp_path):
    (tmp_path / LEDGERS_COHORTES["ALPHA"]).write_text(
        json.dumps({"ev": "OPEN"}) + "\nPAS_DU_JSON\n" + json.dumps({"ev": "CLOSE"}) + "\n", encoding="utf-8")
    assert lire_ledgers_cohortes(tmp_path)["ALPHA"]["n"] == 2
