"""Outil de scoring des vaults (rectif Flo 23/07) : il applique le score 8-facteurs aux vaults
snapshotés, récupère age/tvl depuis la provenance, calcule les coins exécutables (carnet ∪ BBO),
et publie retenus + classement. On prouve qu'un vault à gros drawdown est REJETÉ (piège APR)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod(nom: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / ("%s.py" % nom))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SV = _mod("scorer_vaults")


def _ecrire(root, snaps, provenance=None, carnet=None):
    (root / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "data" / "vault_snapshots.jsonl").write_text(
        "\n".join(json.dumps(s) for s in snaps), encoding="utf-8")
    if provenance is not None:
        (root / "runtime" / "data" / "vaults_suivis.json").write_text(
            json.dumps({"_provenance": {"vaults": provenance}, "vaults": [v["address"] for v in provenance]}))
    if carnet is not None:
        (root / "runtime" / "data" / "carnet_venues.jsonl").write_text(
            "\n".join(json.dumps(c) for c in carnet), encoding="utf-8")


def test_coins_executables_carnet_union_bbo(tmp_path):
    _ecrire(tmp_path, [], carnet=[{"coin": "HYPE"}, {"coin": "FARTCOIN"}])
    exe = SV.coins_executables(tmp_path)
    assert "BTC" in exe and "HYPE" in exe and "FARTCOIN" in exe        # BBO ∪ carnet


def test_construire_retient_le_bon_rejette_le_drawdown(tmp_path):
    bon = [{"vault": "0xBON", "ts_ms": 1000 * i, "nav_usd": nav, "drawdown_pct": 5.0,
            "positions": [{"coin": "BTC", "szi": 1.0, "entryPx": 50_000}]}
           for i, nav in enumerate([100_000, 101_000, 102_000])]
    # même rendement mais drawdown catastrophique (piège APR) -> doit être rejeté
    piege = [{"vault": "0xPIEGE", "ts_ms": 1000 * i, "nav_usd": nav, "drawdown_pct": 80.0,
              "positions": [{"coin": "BTC", "szi": 1.0, "entryPx": 50_000}]}
             for i, nav in enumerate([100_000, 101_000, 102_000])]
    prov = [{"address": "0xBON", "age_j": 300, "tvl_usd": 3_000_000},
            {"address": "0xPIEGE", "age_j": 400, "tvl_usd": 5_000_000}]
    _ecrire(tmp_path, bon + piege, provenance=prov, carnet=[{"coin": "BTC"}])
    p = SV.construire(tmp_path)
    assert "0xBON" in p["retenus"] and "0xPIEGE" not in p["retenus"]
    piege_row = next(c for c in p["classement"] if c["vault"] == "0xPIEGE")
    assert piege_row["raison"] == "DRAWDOWN_EXCESSIF"
    assert SV.ecrire(tmp_path, p) == p["n_retenus"] and (tmp_path / SV.SORTIE).exists()


def test_l_historique_survit_a_l_archivage_des_sessions(tmp_path):
    """Cas réel du 2026-11-11 : après certification + archivage, le score voyait 0 vault et ne retenait rien."""
    import datetime

    maintenant = datetime.datetime(2026, 11, 12, 2, 0, 0)
    now = maintenant.timestamp()

    def session(quand, snaps, carnet=None):
        dossier = tmp_path / "runtime" / "archive" / ("session_" + quand.strftime("%Y%m%d_%H%M%S"))
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / "vault_snapshots.jsonl").write_text("\n".join(json.dumps(x) for x in snaps), encoding="utf-8")
        if carnet is not None:
            (dossier / "carnet_venues.jsonl").write_text("\n".join(json.dumps(x) for x in carnet), encoding="utf-8")

    def snap(i, nav):
        return {"vault": "0xBON", "ts_ms": 1000 * i, "nav_usd": nav, "drawdown_pct": 5.0,
                "positions": [{"coin": "HYPE", "szi": 1.0, "entryPx": 50.0}]}

    session(maintenant - datetime.timedelta(days=40), [snap(0, 1)])                    # trop ancienne : ignorée
    session(maintenant - datetime.timedelta(days=2), [snap(1, 100_000), snap(2, 101_000)], carnet=[{"coin": "OLD"}])
    session(maintenant - datetime.timedelta(hours=3), [snap(2, 101_000), snap(3, 102_000)], carnet=[{"coin": "HYPE"}])
    (tmp_path / "runtime" / "archive" / "session_illisible").mkdir()
    _ecrire(tmp_path, [snap(4, 103_000)], provenance=[{"address": "0xBON", "age_j": 300, "tvl_usd": 3_000_000}],
            carnet=[])
    serie = SV._snaps_par_vault(tmp_path, now=now)["0xBON"]
    assert [x["ts_ms"] for x in serie] == [1000, 2000, 3000, 4000]                      # ordre, sans doublon ni vieille session
    assert SV._rubans(tmp_path, "vault_snapshots.jsonl", now=now)[-1] == tmp_path / SV.SNAP
    assert "HYPE" in SV.coins_executables(tmp_path, now=now)                           # carnet vide en cours : celui d'avant sert
    assert "OLD" in SV.coins_executables(tmp_path, now=now) and "OLD" not in SV.coins_executables(
        tmp_path, now=now + 3 * 86_400)                                                # au-delà de 2 jours : oublié
    # session en cours VIDE (juste après l'archivage) : le vault reste noté sur son historique
    (tmp_path / SV.SNAP).write_text("", encoding="utf-8")
    serie = SV._snaps_par_vault(tmp_path, now=now)["0xBON"]
    assert [x["ts_ms"] for x in serie] == [1000, 2000, 3000]
