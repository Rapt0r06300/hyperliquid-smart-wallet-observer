"""L'audit des données vérifie, type par type, collecté → certifié → utilisé par le labo."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "src"))


def _mod():
    spec = importlib.util.spec_from_file_location("auditer_donnees", RACINE / "tools" / "auditer_donnees_collectees.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


A = _mod()


def test_inventaire_couvre_toutes_les_familles_connues_du_certificateur():
    """Aucune famille certifiable ne doit manquer à l'inventaire d'audit (sinon on l'oublierait)."""
    from hl_observer.datasets import coffre_certifie as C

    certifiables = {fam for fam, _mode in C._FICHIERS_CONNUS.values()}
    audites = {fam for fam, _f, _u in A.INVENTAIRE}
    manquants = certifiables - audites
    assert not manquants, f"familles certifiables absentes de l'audit : {manquants}"


def test_signale_un_flux_certifie_mais_non_utilise(tmp_path, monkeypatch):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    # un flux collecté, certifié, et chargé par le labo (asset_ctx)
    (data / "asset_ctx_tape.jsonl").write_text('{"coin":"ETH"}\n{"coin":"BTC"}\n', encoding="utf-8")
    # un flux collecté, certifié, mais que le labo N'utilise pas (on simule explorer_tx non chargé)
    (data / "explorer_tx_tape.jsonl").write_text('{"x":1}\n', encoding="utf-8")
    coffre = tmp_path / "runtime" / "coffre_certifie"
    coffre.mkdir(parents=True)
    (coffre / "LOCAL_INDEX.json").write_text(json.dumps({"shards": [
        {"famille": "asset_ctx", "shard": "a"}, {"famille": "explorer_tx", "shard": "b"}]}), encoding="utf-8")
    monkeypatch.setattr(A, "_charge_labo", lambda: {"asset_ctx"})          # labo ne charge pas explorer_tx
    rapport = {r["famille"]: r for r in A.auditer(tmp_path, maintenant=10**9)}
    assert rapport["asset_ctx"]["etat"].startswith("FRAIS") or "UTILISÉ" in rapport["asset_ctx"]["etat"]
    assert rapport["asset_ctx"]["lignes_collectees"] == 2
    assert rapport["explorer_tx"]["etat"] == "CERTIFIÉ · NON UTILISÉ PAR LE LABO"
    texte = "\n".join(A.rendre(list(rapport.values())))
    assert "explorer_tx" in texte and "certifiés mais NON utilisés" in texte


def test_distingue_collecte_non_certifie_et_jamais_collecte(tmp_path, monkeypatch):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "copy_vault_orders_lane.jsonl").write_text('{"user":"0x"}\n', encoding="utf-8")   # collecté
    (tmp_path / "runtime" / "coffre_certifie").mkdir(parents=True)
    (tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").write_text('{"shards": []}', encoding="utf-8")
    monkeypatch.setattr(A, "_charge_labo", lambda: {"leader_orders"})
    rapport = {r["famille"]: r for r in A.auditer(tmp_path, maintenant=10**9)}
    assert rapport["leader_orders"]["etat"] == "COLLECTÉ · NON CERTIFIÉ"     # fichier présent, 0 shard
    assert rapport["micro_l2"]["etat"] == "JAMAIS COLLECTÉ"                   # aucun fichier


def test_les_sept_flux_rebranches_sont_bien_charges_par_le_labo():
    """Garde-fou : leader_orders, funding_history, vault_ledger, vault_portfolio, micro_* sont utilisés."""
    charge = A._charge_labo()
    for famille in ("leader_orders", "funding_history", "vault_ledger", "vault_portfolio",
                    "micro_bbo", "micro_l2", "micro_trades"):
        assert famille in charge, famille


def test_main_json(tmp_path, capsys):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "coffre_certifie").mkdir(parents=True)
    (tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").write_text('{"shards": []}', encoding="utf-8")
    assert A.main(["--root", str(tmp_path), "--json"]) == 0
    sortie = json.loads(capsys.readouterr().out)
    assert isinstance(sortie, list) and len(sortie) == len(A.INVENTAIRE)
