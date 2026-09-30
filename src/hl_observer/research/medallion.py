"""[DATA-115/116/117] Architecture medaillon Bronze->Silver->Gold : BRONZE (raw IMMUABLE + hash de
contenu), SILVER (schema CANONIQUE normalise cross-venue), GOLD (features derivees). Chaque etage porte
son lineage ; un champ/feature dont l'entree manque reste None (jamais invente). stdlib pure, 0 reseau."""
from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence

CHAMPS_SILVER = ("ts", "venue", "symbole", "type", "prix", "taille", "side")


def bronze_immuable(lignes: Sequence[Mapping]) -> dict:
    """BRONZE : capture RAW immuable + hash de contenu (toute alteration change le hash)."""
    h = hashlib.sha256(json.dumps(list(lignes), sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return {"n": len(lignes), "hash": h, "immutable": True}


def to_silver(ligne_brute: Mapping, mapping: Mapping[str, str], *, venue: str) -> dict:
    """SILVER : normalise une ligne brute (champs specifiques venue) vers le schema CANONIQUE via un
    mapping {champ_canonique: champ_source}. Un champ canonique absent -> None (jamais invente)."""
    out = {"venue": venue}
    for canon in CHAMPS_SILVER:
        if canon == "venue":
            continue
        src = mapping.get(canon)
        out[canon] = ligne_brute.get(src) if src else None
    out["_lineage"] = {"venue": venue, "etage": "silver"}
    return out


def to_gold(silver: Sequence[Mapping]) -> dict:
    """GOLD : features derivees du silver (ex: notionnel = prix*taille). Une feature dont l'entree
    manque reste None (pas de faux 0)."""
    feats = []
    for s in silver:
        px, sz = s.get("prix"), s.get("taille")
        notionnel = (px * sz) if (px is not None and sz is not None) else None
        feats.append({"ts": s.get("ts"), "symbole": s.get("symbole"), "notionnel": notionnel,
                      "_lineage": {"etage": "gold", "depuis": "silver"}})
    return {"n": len(feats), "features": feats}
