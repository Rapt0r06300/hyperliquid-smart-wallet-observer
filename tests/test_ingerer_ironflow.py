"""Ingestion Ironflow : contrôles avant admission, exclusions nommées, jamais de fichier faux sous le nom final."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import ingerer_ironflow as I  # noqa: E402

UTC = dt.timezone.utc


def _bougies(chemin: Path, n: int = 50, *, doublon: bool = False, high_faux: bool = False) -> None:
    ts = [dt.datetime(2026, 1, 1, tzinfo=UTC) + dt.timedelta(hours=k) for k in range(n)]
    if doublon:
        ts[-1] = ts[0]
    high = [11.0] * n
    if high_faux:
        high[3] = 9.0
    pq.write_table(pa.table({"timestamp": pa.array(ts, pa.timestamp("us", tz="UTC")), "market": ["BTC-PERP"] * n,
                             "open": [10.0] * n, "high": high, "low": [9.5] * n, "close": [10.5] * n,
                             "volume": [1.0] * n}), chemin)


def test_bougies_saines_validees(tmp_path: Path) -> None:
    _bougies(tmp_path / "a.parquet")
    assert I.valider("candles-1h", tmp_path / "a.parquet")["statut"] == "EXTERNAL_VALIDATED"


def test_doublon_de_cle_et_bougie_incoherente_refuses(tmp_path: Path) -> None:
    _bougies(tmp_path / "d.parquet", doublon=True)
    _bougies(tmp_path / "h.parquet", high_faux=True)
    assert "doublons" in " ".join(I.valider("candles-1h", tmp_path / "d.parquet")["motifs"])
    assert "high < max" in " ".join(I.valider("candles-1h", tmp_path / "h.parquet")["motifs"])


def test_colonne_manquante_refusee(tmp_path: Path) -> None:
    pq.write_table(pa.table({"timestamp": pa.array([dt.datetime(2026, 1, 1, tzinfo=UTC)], pa.timestamp("ms", tz="UTC"))}),
                   tmp_path / "f.parquet")
    v = I.valider("funding", tmp_path / "f.parquet")
    assert v["statut"] == "EXTERNAL_REJECTED" and "colonnes manquantes" in v["motifs"][0]


def _oi(chemin: Path, n: int, negatifs: int) -> None:
    ts = [dt.datetime(2026, 6, 1, tzinfo=UTC) + dt.timedelta(minutes=k) for k in range(n)]
    oi = [-5.0 if k < negatifs else 100.0 for k in range(n)]
    pq.write_table(pa.table({"timestamp": pa.array(ts, pa.timestamp("us", tz="UTC")), "market": ["X-PERP"] * n,
                             "mark_price": [1.0] * n, "oracle_price": [1.0] * n, "open_interest": oi}), chemin)


def test_quelques_lignes_impossibles_sont_exclues_et_nommees(tmp_path: Path) -> None:
    _oi(tmp_path / "o.parquet", 30_000, 2)
    v = I.valider("open-interest", tmp_path / "o.parquet")
    assert v["statut"] == "EXTERNAL_VALIDATED" and v["lignes_exclues_a_la_lecture"]["open_interest"]["n"] == 2


def test_trop_de_lignes_impossibles_refusent_le_fichier(tmp_path: Path) -> None:
    _oi(tmp_path / "o.parquet", 1000, 50)
    assert I.valider("open-interest", tmp_path / "o.parquet")["statut"] == "EXTERNAL_REJECTED"


def test_la_table_fills_des_liquidations_a_son_propre_schema() -> None:
    assert "side" in I.spec_de("liquidations", "data/fills/2026-10.parquet")["colonnes"]
    assert "position_side" in I.spec_de("liquidations", "data/events/2026-10.parquet")["colonnes"]


def test_empreinte_fausse_jamais_sous_le_nom_final(tmp_path: Path) -> None:
    class Reponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self, n):
            yield b"contenu altere"

    class Client:
        def stream(self, *a, **k):
            return Reponse()

    cible = tmp_path / "x.parquet"
    with pytest.raises(ValueError):
        I.telecharger("funding", {"path": "data/x.parquet", "size": 14, "lfs": {"oid": "0" * 64}}, cible, Client())
    assert not cible.exists() and (tmp_path / "x.parquet.empreinte_fausse").exists()
