"""Tardis : un fichier abîmé, une horloge qui recule ou un carnet sans instantané initial sont refusés."""
from __future__ import annotations

import gzip
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import ingerer_tardis_jours_gratuits as T  # noqa: E402

ENTETE = "exchange,symbol,timestamp,local_timestamp,is_snapshot,side,price,amount\n"


def _ecrire(p: Path, lignes: list[str]) -> Path:
    with gzip.open(p, "wt", encoding="utf-8") as f:
        f.write(ENTETE + "".join(lignes))
    return p


def test_carnet_sain(tmp_path: Path) -> None:
    v = T.valider("incremental_book_L2", _ecrire(tmp_path / "a.csv.gz", [
        f"hyperliquid,BTC,{k},{k + 5},true,bid,100,1\n" for k in range(0, 10_000_000, 500_000)]))
    assert v["statut"] == "EXTERNAL_VALIDATED" and v["trous_de_capture_60s"] == 0


def test_horloge_qui_recule_refusee(tmp_path: Path) -> None:
    v = T.valider("incremental_book_L2", _ecrire(tmp_path / "b.csv.gz", [
        "hyperliquid,BTC,1,10,true,bid,100,1\n", "hyperliquid,BTC,2,5,false,bid,100,1\n"]))
    assert v["statut"] == "EXTERNAL_REJECTED" and "reculs" in v["motifs"][0]


def test_carnet_sans_instantane_initial_refuse(tmp_path: Path) -> None:
    v = T.valider("incremental_book_L2", _ecrire(tmp_path / "c.csv.gz", ["hyperliquid,BTC,1,10,false,bid,100,1\n"]))
    assert v["statut"] == "EXTERNAL_REJECTED"


def test_trou_de_capture_rend_le_replay_strict_non_admissible(tmp_path: Path) -> None:
    v = T.valider("incremental_book_L2", _ecrire(tmp_path / "d.csv.gz", [
        "hyperliquid,BTC,1,10,true,bid,100,1\n", f"hyperliquid,BTC,2,{10 + 120_000_000},false,bid,100,1\n"]))
    assert v["trous_de_capture_60s"] == 1 and v["replay_strict"] == "NON_ADMISSIBLE"


def test_gzip_abime_refuse(tmp_path: Path) -> None:
    p = tmp_path / "e.csv.gz"
    p.write_bytes(b"pas du gzip")
    assert T.valider("trades", p)["statut"] == "EXTERNAL_REJECTED"


def test_seuls_les_premiers_du_mois_sont_acceptes() -> None:
    assert T.main(["--jours", "2026-06-02", "--coins", "BTC"]) == 2
