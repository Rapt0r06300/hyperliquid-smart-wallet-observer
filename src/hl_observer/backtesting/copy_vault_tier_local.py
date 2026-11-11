"""Chargement du tier LOCAL du coffre-fort certifié pour la recherche exploratoire du labo.

Lecture seule, SHA-256 revérifié (fail-closed). Les rangées sont étiquetées
``provenance_tier=LOCAL`` : elles nourrissent la recherche, jamais une preuve.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from hl_observer.collection.forward_poll_fills import is_causal_live_source


#: familles du coffre LOCAL qui alimentent les fills de replay.
_COFFRE_FAMILLES_FILLS = {"fills_forward", "fills_backfill", "snapshot"}
#: familles LOCAL de SIGNAUX de contexte (PAS le replay PnL) : nouvelles observations
#: certifiées (liquidations, overshoots, OI/funding, prix, cross-venue, bougies). Elles
#: sont mises à DISPOSITION de la recherche exploratoire, séparées du calcul PnL SAFE.
_COFFRE_FAMILLES_SIGNAUX = {
    "liquidation", "overshoot", "asset_ctx", "allmids",
    "venue_book", "venue_dispersion", "trades_marche", "candle", "position",
}


def _cotation_collecteur_vers_labo(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Cotation Hyperliquid du collecteur BBO (``bid``/``ask``/``ts_ex``) -> forme BBO du labo.

    Memes grandeurs observees, autres noms : rien n'est invente. ``None`` pour toute ligne
    qui n'est pas une cotation Hyperliquid complete (autre venue, transaction, taille
    absente, carnet croise, horloge incoherente) : fail-closed.
    """
    if row.get("venue") != "HL" or row.get("type_ligne") != "QUOTE" or not row.get("coin"):
        return None
    recu, bourse = row.get("recv_wall_ts_ms"), row.get("ts_ex")
    if isinstance(recu, bool) or not isinstance(recu, int):
        return None
    if isinstance(bourse, bool) or not isinstance(bourse, (int, float)) or not math.isfinite(bourse):
        return None
    bourse = int(bourse)
    valeurs = [row.get(nom) for nom in ("bid", "bid_sz", "ask", "ask_sz")]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in valeurs):
        return None
    bid, bid_sz, ask, ask_sz = (float(v) for v in valeurs)
    if not (0 < bid < ask and bid_sz > 0 and ask_sz > 0 and 0 < bourse <= recu):
        return None
    return {
        "schema_version": "hypersmart.copy_vault_bbo.v1", "coin": row["coin"],
        "received_at_ms": recu, "exchange_ts_ms": bourse,
        "bid_px": bid, "bid_sz": bid_sz, "ask_px": ask, "ask_sz": ask_sz,
        "source": "HYPERLIQUID_BBO_WS", "data_origin": "REAL_OBSERVED", "causal_observation": True,
        "provenance_tier": "LOCAL", "adapte_depuis": "bbo_tape",
    }


def _charger_tier_local(
    repository_root: Path, *, progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Charge le tier LOCAL du coffre-fort (certifie) EN MEMOIRE pour la recherche.

    Lit ``runtime/coffre_certifie/LOCAL_INDEX.json`` + ses shards gzip, re-verifie leur
    SHA-256 (fail-closed : un shard altere est IGNORE), et renvoie les rangees par type
    (``_fills`` / ``_books`` / ``_bbo``), chacune etiquetee ``provenance_tier=LOCAL`` et
    SANS ``quality=SAFE`` : elles nourrissent la recherche EXPLORATOIRE (signaux causaux)
    mais NE PEUVENT JAMAIS etre « prouvees » economiquement (la preuve exige SAFE).
    """
    import gzip as _gzip

    vide = {"statut": "ABSENT", "_fills": [], "_books": [], "_bbo": [], "_signaux": {},
            "fills_causaux": 0, "fills_backfill": 0, "carnets": 0, "bbo": 0,
            "bbo_adaptees": 0, "bbo_denses_non_retenues": 0,
            "signaux_par_famille": {}, "signaux_total": 0,
            "shards_injectes": 0, "shards_rejetes": 0}
    index_path = repository_root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    if index_path.is_symlink() or not index_path.is_file():
        return vide
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {**vide, "statut": "INDEX_ILLISIBLE"}
    shards = index.get("shards") if isinstance(index, dict) else None
    if not isinstance(shards, list) or not shards:
        return {**vide, "statut": "VIDE"}

    _fills: list[dict[str, Any]] = []
    _books: list[dict[str, Any]] = []
    _bbo: list[dict[str, Any]] = []
    _signaux: dict[str, list[dict[str, Any]]] = {}
    # cotations du collecteur BBO : flux tres dense -> une par coin et par seconde (la premiere
    # observee), largement assez pour dater un prix d'execution, sans saturer la memoire.
    _bbo_secondes: set[tuple[str, int]] = set()
    bbo_adaptees = 0
    bbo_denses_non_retenues = 0
    shards_ok = 0
    shards_rejetes = 0
    for entree in shards:
        if not isinstance(entree, dict):
            continue
        famille = str(entree.get("famille") or "")
        est_signal = famille in _COFFRE_FAMILLES_SIGNAUX
        if (famille not in _COFFRE_FAMILLES_FILLS
                and famille not in ("book_l2", "bbo") and not est_signal):
            continue
        rel = entree.get("shard")
        if not isinstance(rel, str):
            continue
        sha_attendu = str(entree.get("sha256") or "").lower()
        shard_path = repository_root / rel
        if shard_path.is_symlink() or not shard_path.is_file():
            shards_rejetes += 1
            continue
        # fail-closed : le SHA du shard doit correspondre a l'index certifie.
        if sha_attendu:
            h = hashlib.sha256()
            try:
                with shard_path.open("rb") as fb:
                    for bloc in iter(lambda: fb.read(1 << 20), b""):
                        h.update(bloc)
            except OSError:
                shards_rejetes += 1
                continue
            if h.hexdigest() != sha_attendu:
                shards_rejetes += 1
                continue
        try:
            with _gzip.open(shard_path, "rt", encoding="utf-8") as src:
                for ligne in src:
                    ligne = ligne.strip()
                    if not ligne:
                        continue
                    try:
                        row = json.loads(ligne)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(row, dict):
                        continue
                    row["provenance_tier"] = "LOCAL"
                    if famille in _COFFRE_FAMILLES_FILLS:
                        if isinstance(row.get("ts_ms"), int) and row.get("vault") and row.get("coin"):
                            _fills.append(row)
                    elif famille == "book_l2":
                        if (isinstance(row.get("received_at_ms"), int)
                                and isinstance(row.get("exchange_ts_ms"), int)
                                and row.get("coin") and row.get("bids5") and row.get("asks5")):
                            _books.append(row)
                    elif famille == "bbo":
                        if (isinstance(row.get("received_at_ms"), int)
                                and isinstance(row.get("exchange_ts_ms"), int)
                                and row.get("coin") and row.get("bid_px") is not None
                                and row.get("ask_px") is not None):
                            _bbo.append(row)
                        else:
                            adaptee = _cotation_collecteur_vers_labo(row)
                            if adaptee is not None:
                                seconde = (adaptee["coin"], adaptee["received_at_ms"] // 1000)
                                if seconde in _bbo_secondes:
                                    bbo_denses_non_retenues += 1
                                else:
                                    _bbo_secondes.add(seconde)
                                    _bbo.append(adaptee)
                                    bbo_adaptees += 1
                    elif est_signal:
                        # Signal de contexte LOCAL : tout enregistrement certifié avec
                        # un horodatage (ts_ms ou snapshot_ts_ms) est mis à disposition.
                        if row.get("ts_ms") is not None or row.get("snapshot_ts_ms") is not None:
                            _signaux.setdefault(famille, []).append(row)
        except OSError:
            shards_rejetes += 1
            continue
        shards_ok += 1
        if progress is not None and shards_ok % 5 == 0:
            progress(f"Coffre LOCAL · {shards_ok} shards · {len(_fills):,} fills")

    fills_causaux = sum(
        1 for r in _fills
        if r.get("isSnapshot") is False and is_causal_live_source(r.get("source"))
    )
    return {
        "statut": "OK", "shards_injectes": shards_ok, "shards_rejetes": shards_rejetes,
        "_fills": _fills, "_books": _books, "_bbo": _bbo, "_signaux": _signaux,
        "fills_causaux": fills_causaux, "fills_backfill": len(_fills) - fills_causaux,
        "carnets": len(_books), "bbo": len(_bbo),
        "bbo_adaptees": bbo_adaptees, "bbo_denses_non_retenues": bbo_denses_non_retenues,
        "signaux_par_famille": {f: len(r) for f, r in sorted(_signaux.items())},
        "signaux_total": sum(len(r) for r in _signaux.values()),
    }
