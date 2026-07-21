"""MAPPING PERP ↔ SPOT, AVEC SA PROVENANCE (P1-4, 21/07).

LE DÉFAUT
---------
L'appariement perp↔spot reposait sur une **heuristique de nom** : un spot `U`+X est candidat
pour tout perp commençant par X (UBTC→BTC, UETH→ETH, UFART→FARTCOIN). Suivie d'un sélecteur
par prix et de plusieurs portes — donc pas dangereuse, mais **sans mémoire** : une fois le
choix fait, rien ne disait *d'où* il venait ni *sur quelle preuve*.

Preuve que ça casse : le scan produit encore des refus `base aberrante ×141` (BERA) et
`×3511` (TRUMP). Le nom correspond, l'actif non. Le sélecteur par prix les rattrape — mais
seulement parce qu'ils sont grotesques. Un faux appariement **plausible** passerait.

CE QUE CE MODULE AJOUTE
-----------------------
Il conserve, pour chaque appariement, ce qui permet de le **contester plus tard** :

    display_symbol · hypercore_token_name · spot_pair_index · base_token_index
    quote_token_index · perp_symbol · canonical_mapping · mapping_source · mapping_timestamp

`mapping_source` distingue les trois provenances, et c'est tout l'intérêt :

  * `NOM_OFFICIEL`   — le token HyperCore porte EXACTEMENT le nom du perp. Certain.
  * `PREFIXE_UNIT`   — token Unit `U`+X apparié à un perp commençant par X. **Heuristique.**
  * `INCONNU`        — aucune règle ne s'applique : on n'apparie pas.

Les métadonnées viennent de `spotMetaAndAssetCtxs`, que le feeder interroge déjà. On ne
fabrique aucun index : ce que l'API ne donne pas reste `None`.

PAPER only : nommer un actif n'est pas passer un ordre.
"""
from __future__ import annotations

import time
from typing import Any

SOURCE_NOM_OFFICIEL = "NOM_OFFICIEL"
SOURCE_PREFIXE_UNIT = "PREFIXE_UNIT"
SOURCE_INCONNU = "INCONNU"

#: longueur minimale du radical pour qu'un préfixe Unit soit crédible (UBT→BT serait du bruit).
RADICAL_MIN = 3
#: jamais appariés : un stable n'est pas le sous-jacent d'un perp (loi `couverture_meme_actif`).
STABLES = frozenset({"USDC", "USDT", "USDE", "USDHL", "FEUSD", "USOL0", "UUSDT"})


def _txt(v: Any) -> str:
    return str(v or "").strip().upper()


def indexer_metadonnees(spot_meta: dict[str, Any] | None) -> dict[str, Any]:
    """Extrait des `spotMeta` officiels : tokens par index, et paires avec LEURS index.

    Aucun champ n'est deviné. Une paire sans `tokens` exploitable est ignorée — mieux vaut
    un appariement manquant qu'un appariement inventé.
    """
    sm = spot_meta if isinstance(spot_meta, dict) else {}
    tokens: dict[int, str] = {}
    for t in sm.get("tokens") or []:
        if isinstance(t, dict) and isinstance(t.get("index"), int):
            nom = _txt(t.get("name"))
            if nom:
                tokens[int(t["index"])] = nom
    paires: dict[str, dict[str, Any]] = {}
    for i, pr in enumerate(sm.get("universe") or []):
        if not isinstance(pr, dict):
            continue
        idx = pr.get("tokens")
        nom = str(pr.get("name") or "")
        if not nom or not isinstance(idx, list) or len(idx) < 2:
            continue
        base_i, quote_i = idx[0], idx[1]
        paires[nom] = {
            "spot_pair_index": pr.get("index") if isinstance(pr.get("index"), int) else i,
            "base_token_index": base_i if isinstance(base_i, int) else None,
            "quote_token_index": quote_i if isinstance(quote_i, int) else None,
            "hypercore_token_name": tokens.get(base_i) if isinstance(base_i, int) else None,
            "quote_token_name": tokens.get(quote_i) if isinstance(quote_i, int) else None,
        }
    return {"tokens": tokens, "paires": paires}


def source_appariement(perp_symbol: str, token_name: str) -> str:
    """D'où vient cet appariement ? `NOM_OFFICIEL` (certain), `PREFIXE_UNIT` (heuristique)
    ou `INCONNU` (on n'apparie pas)."""
    p, t = _txt(perp_symbol), _txt(token_name)
    if not p or not t or t in STABLES:
        return SOURCE_INCONNU
    if p == t:
        return SOURCE_NOM_OFFICIEL
    if t.startswith("U") and len(t) >= RADICAL_MIN + 1:
        radical = t[1:]
        if len(radical) >= RADICAL_MIN and p.startswith(radical):
            return SOURCE_PREFIXE_UNIT
    return SOURCE_INCONNU


def apparier(perp_symbol: str, pair_name: str, index: dict[str, Any],
             *, now_ms: int | None = None) -> dict[str, Any] | None:
    """Un appariement COMPLET avec sa provenance, ou None si aucune règle ne s'applique.

    `canonical_mapping` est la clé stable `PERP<-PAIRE` : c'est elle qu'on compare d'une
    passe à l'autre pour détecter qu'un appariement a **changé** sans qu'on l'ait décidé.
    """
    infos = (index.get("paires") or {}).get(str(pair_name))
    if not infos:
        return None
    token = infos.get("hypercore_token_name")
    src = source_appariement(perp_symbol, token or "")
    if src == SOURCE_INCONNU:
        return None
    return {
        "display_symbol": _txt(perp_symbol),
        "perp_symbol": _txt(perp_symbol),
        "hypercore_token_name": token,
        "spot_pair_name": str(pair_name),
        "spot_pair_index": infos.get("spot_pair_index"),
        "base_token_index": infos.get("base_token_index"),
        "quote_token_index": infos.get("quote_token_index"),
        "quote_token_name": infos.get("quote_token_name"),
        "canonical_mapping": "%s<-%s" % (_txt(perp_symbol), pair_name),
        "mapping_source": src,
        "mapping_timestamp": int(now_ms if now_ms is not None else time.time() * 1000),
        "certain": src == SOURCE_NOM_OFFICIEL,
    }


def detecter_changement(avant: dict[str, Any] | None,
                        apres: dict[str, Any] | None) -> dict[str, Any] | None:
    """Un appariement qui CHANGE sans décision est un incident, pas une mise à jour.

    C'est ce qui a produit `base aberrante ×3511` sur TRUMP : la paire choisie n'était plus
    la même, et rien ne l'avait signalé. Retourne None si rien n'a bougé.
    """
    a = (avant or {}).get("canonical_mapping")
    b = (apres or {}).get("canonical_mapping")
    if not a or not b or a == b:
        return None
    return {"coin": (apres or {}).get("perp_symbol"), "avant": a, "apres": b,
            "source_avant": (avant or {}).get("mapping_source"),
            "source_apres": (apres or {}).get("mapping_source"),
            "note": "l'appariement perp<->spot a CHANGE sans decision : a verifier avant "
                    "d'ouvrir quoi que ce soit sur ce coin"}


def resume(mappings: Any) -> dict[str, Any]:
    """Combien d'appariements sont CERTAINS, combien reposent sur l'heuristique.
    Un projet qui ne sait pas cette proportion ne sait pas ce qu'il trade."""
    liste = [m for m in (mappings.values() if isinstance(mappings, dict) else (mappings or ()))
             if isinstance(m, dict)]
    if not liste:
        return {"total": 0, "certains": 0, "heuristiques": 0, "part_certaine_pct": None}
    certains = sum(1 for m in liste if m.get("mapping_source") == SOURCE_NOM_OFFICIEL)
    return {"total": len(liste), "certains": certains,
            "heuristiques": len(liste) - certains,
            "part_certaine_pct": round(100.0 * certains / len(liste), 1),
            "coins_heuristiques": sorted(m.get("perp_symbol") for m in liste
                                         if m.get("mapping_source") != SOURCE_NOM_OFFICIEL)}


__all__ = ["SOURCE_NOM_OFFICIEL", "SOURCE_PREFIXE_UNIT", "SOURCE_INCONNU", "RADICAL_MIN",
           "STABLES", "indexer_metadonnees", "source_appariement", "apparier",
           "detecter_changement", "resume"]
