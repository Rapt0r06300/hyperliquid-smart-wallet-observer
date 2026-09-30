"""[Bloc 37 / DATA-118 / AUD-300,301,302] Data plane REEL : ingestion composee
producteur -> Bronze (immuable hashe) -> Silver (Parquet partitionne) -> Gold (features) -> catalogue
Data Mesh (SQLite), avec lineage. Prouve la chaine complete sur des lots reellement persistes.
Fournit aussi la construction d'une PreuveLive a partir de l'ingest, pour la gate LIVE_READY. 0 reseau.
"""
from __future__ import annotations

from typing import Mapping, Optional, Sequence

from . import data_mesh_catalog as dm
from . import live_ready as lr
from . import medallion_store as ms


def ingerer(root: str, conn, venue: str, records: Sequence[Mapping], *, ts: float) -> dict:
    """Persiste un lot canonique dans les 3 etages + le catalogue. Retourne les artefacts + lineage."""
    bronze = ms.ecrire_bronze(root, venue, records)
    silver = ms.to_silver_parquet(root, venue, records)
    gold = ms.to_gold_parquet(root, records)
    dm.enregistrer_dataset(conn, name="%s_bronze" % venue, etage="bronze", path=bronze["path"],
                           n_rows=bronze["n"], venue=venue, content_hash=bronze["hash"], ts=ts)
    dm.enregistrer_dataset(conn, name="%s_silver" % venue, etage="silver", path=silver["dir"],
                           n_rows=silver["n"], venue=venue, ts=ts)
    dm.enregistrer_dataset(conn, name="%s_gold" % venue, etage="gold", path=gold["path"],
                           n_rows=gold["n"], venue=venue, ts=ts)
    return {"venue": venue, "bronze": bronze, "silver": silver, "gold": gold,
            "catalogue": dm.lister_datasets(conn),
            "lineage": ["bronze", "silver", "gold", "catalogue"]}


def preuve_live_depuis_ingest(venue: str, ingest: Mapping, *, connexion: bool, n_messages: int,
                              last_useful_event_ts: Optional[float], sequences_ok: bool,
                              replay_parite: bool) -> lr.PreuveLive:
    """Construit la PreuveLive : le critere 'stockage' est ALIMENTE par l'ingest reel (bronze ecrit).
    Les autres criteres restent a fournir par le collecteur runtime (jamais supposes)."""
    return lr.PreuveLive(
        venue, connexion=connexion, n_messages=n_messages, last_useful_event_ts=last_useful_event_ts,
        sequences_ok=sequences_ok, bronze_lignes_ecrites=ingest["bronze"]["n"], replay_parite=replay_parite)
