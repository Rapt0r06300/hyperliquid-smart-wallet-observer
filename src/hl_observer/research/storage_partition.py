"""[AUD-301/365/367] Stockage & lineage : cle de PARTITION Parquet (venue/date/symbole), HASH de
shard/partition (adressage par contenu, immutabilite verifiable) et lineage LIGNE/EVENEMENT (chaque
ligne remonte a ses sources). stdlib pure (hashlib), 0 reseau."""
from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence


def cle_partition_parquet(record: Mapping, *, dimensions: Sequence[str] = ("venue", "date", "symbole")) -> str:
    """Cle de partition Parquet DETERMINISTE, style Hive (venue=.../date=.../symbole=...). Une bonne
    cle rend le replay et l'elagage de partitions efficaces."""
    return "/".join("%s=%s" % (d, record.get(d, "INCONNU")) for d in dimensions)


def hash_partition(lignes: Sequence[Mapping]) -> str:
    """Hash SHA-256 d'une partition/shard (adressage par contenu) : toute alteration d'une ligne change
    le hash -> immutabilite Bronze verifiable."""
    return hashlib.sha256(json.dumps(list(lignes), sort_keys=True, default=str).encode("utf-8")).hexdigest()


def lineage_ligne(valeur, sources: Sequence[str], *, transformation: str = "brut") -> dict:
    """Lineage au niveau LIGNE/EVENEMENT : la valeur remonte a ses sources + la transformation
    appliquee. Un chiffre sans lineage finit par mentir."""
    if not sources:
        raise ValueError("une ligne doit citer au moins une source (lineage obligatoire)")
    return {"valeur": valeur, "sources": list(sources), "transformation": transformation, "tracable": True}
