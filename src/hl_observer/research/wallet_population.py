"""ALPHA — population de wallets À L'ÉCHELLE (P6) : ingestion STREAMING + enrichissement + classement par edge net.

Objectif : passer de 30 wallets à des milliers, en streamant `node_fills_by_block` (ou tout tape de fills),
et classer NON par PnL brut mais par **NOTRE edge net copyable** (la seule métrique qui compte pour nous).
Réutilise l'évaluateur discipliné (`wallet_copy_edge`, grappes/LCB) et ajoute les dimensions demandées :

  * **archetype** (scalper / swing / momentum / mixte) d'après fréquence et concentration ;
  * **stabilité** (part de jours/coins au markout positif) ;
  * **capacity** (depuis les tailles si présentes, sinon UNMEASURABLE) ;
  * **indépendance d'entité** : deux wallets qui tradent le même coin au même instant = probablement la même
    entité → on les marque pour ne PAS compter deux fois le même signal.

Streaming borné en mémoire : on ne garde par wallet que des markouts réduits, pas les fills bruts.
Schéma accepté : `{adresse, coin, side/sens, ts_ms, mid_at_fill, mid_forward}` (tape forward) OU
`{adresse, coin, side, ts_ms, px, sz}` (node_fills — markout alors UNMEASURABLE sans série de prix jointe).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import json
import math
import random
import statistics
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from hl_observer.research.wallet_copy_edge import FRAIS_TAKER_ROUNDTRIP_BPS, evaluer_wallet

UNMEASURABLE = "UNMEASURABLE"
JOUR_MS = 86_400_000


def flux_fills(path: str) -> Iterator[dict[str, Any]]:
    """Générateur streaming (une ligne à la fois) — borné en mémoire même pour des millions de fills."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def archetype(recs: Sequence[Mapping[str, Any]]) -> str:
    """Classe grossièrement le wallet d'après fréquence (fills/jour) et concentration par coin."""
    if not recs:
        return UNMEASURABLE
    ts = [r.get("ts_ms") for r in recs if isinstance(r.get("ts_ms"), (int, float))]
    coins = [r.get("coin") for r in recs]
    n_coins = len(set(coins))
    span_j = max(1.0, (max(ts) - min(ts)) / JOUR_MS) if len(ts) >= 2 else 1.0
    par_jour = len(recs) / span_j
    conc = max((coins.count(c) for c in set(coins)), default=0) / len(recs)
    if par_jour >= 20:
        return "scalper"
    if conc >= 0.7:
        return "momentum_mono_coin"
    if n_coins >= 5 and par_jour < 5:
        return "swing_diversifie"
    return "mixte"


def independance_entite(par_wallet: Mapping[str, Sequence[Mapping[str, Any]]], *, fenetre_ms: int = 2000) -> dict[str, list[str]]:
    """Détecte des wallets qui tradent le MÊME coin dans la même fenêtre (≈ même entité). Retourne les clusters."""
    return _clusters_cotrade(_collect_events(par_wallet), fenetre_ms=fenetre_ms)


def _collect_events(par_wallet: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[tuple[Any, float, str]]:
    out: list[tuple[Any, float, str]] = []
    for w, recs in par_wallet.items():
        for r in recs:
            t = r.get("ts_ms")
            if isinstance(t, (int, float)):
                out.append((r.get("coin"), float(t), w))
    out.sort(key=lambda e: (str(e[0]), e[1]))
    return out


def _clusters_cotrade(events: list[tuple[Any, float, str]], *, fenetre_ms: int) -> dict[str, list[str]]:
    """Union-find léger : deux wallets tradant le même coin à < fenetre_ms sont liés."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(1, len(events)):
        c0, t0, w0 = events[i - 1]
        c1, t1, w1 = events[i]
        if c0 == c1 and w0 != w1 and (t1 - t0) <= fenetre_ms:
            union(w0, w1)
    clusters: dict[str, list[str]] = {}
    for w in list(parent):
        clusters.setdefault(find(w), []).append(w)
    return {k: sorted(v) for k, v in clusters.items() if len(v) > 1}


def fingerprint_wallet(recs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """FIX-15 — empreinte comportementale d'un wallet : coins tradés, taille médiane, cadence (fills/jour).
    Deux wallets qui partagent la même empreinte ne sont PROBABLEMENT pas deux preuves indépendantes."""
    coins = frozenset(r.get("coin") for r in recs if r.get("coin"))
    sizes = [float(r["sz"]) for r in recs if isinstance(r.get("sz"), (int, float)) and not isinstance(r.get("sz"), bool)]
    ts = [float(r["ts_ms"]) for r in recs if isinstance(r.get("ts_ms"), (int, float)) and not isinstance(r.get("ts_ms"), bool)]
    span_j = max(1.0, (max(ts) - min(ts)) / JOUR_MS) if len(ts) >= 2 else 1.0
    return {"coins": coins, "med_size": (statistics.median(sizes) if sizes else None),
            "cadence": round(len(recs) / span_j, 4), "n": len(recs)}


def fingerprints_similaires(fa: Mapping[str, Any], fb: Mapping[str, Any], *, jaccard_min: float = 0.8,
                            size_ratio_max: float = 1.25, cadence_ratio_max: float = 1.5) -> bool:
    """FIX-15 — vrai si deux empreintes « se ressemblent » assez pour être une même entité : mêmes coins
    (Jaccard ≥ seuil) ET tailles médianes proches (ratio borné) ET cadences proches. Toutes conditions requises
    (haute précision : on ne fusionne pas deux wallets distincts sur un seul indice)."""
    ca_set, cb_set = fa.get("coins") or frozenset(), fb.get("coins") or frozenset()
    union = len(ca_set | cb_set)
    if not union or len(ca_set & cb_set) / union < jaccard_min:
        return False
    a, b = fa.get("med_size"), fb.get("med_size")
    if a and b and max(a, b) / min(a, b) > size_ratio_max:
        return False
    ca, cb = fa.get("cadence"), fb.get("cadence")
    if ca and cb and max(ca, cb) / min(ca, cb) > cadence_ratio_max:
        return False
    return True


def clusters_entite(par_wallet: Mapping[str, Sequence[Mapping[str, Any]]], *, fenetre_ms: int = 2000,
                    **kw: Any) -> dict[str, list[str]]:
    """FIX-15 — clusters d'entité par DEUX critères unis : (1) co-trade (même coin, < fenetre_ms) OU (2) empreinte
    comportementale très proche (coins/taille/cadence). Étend `_clusters_cotrade` (timing seul). Deux wallets liés
    par l'un OU l'autre = UNE entité (conservateur pour l'indépendance). O(n²) sur les empreintes (population bornée)."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    events = _collect_events(par_wallet)                       # co-trade timing (comme _clusters_cotrade)
    for i in range(1, len(events)):
        c0, t0, w0 = events[i - 1]
        c1, t1, w1 = events[i]
        if c0 == c1 and w0 != w1 and (t1 - t0) <= fenetre_ms:
            union(w0, w1)
    fps = {w: fingerprint_wallet(recs) for w, recs in par_wallet.items()}
    wallets = list(par_wallet)
    for i in range(len(wallets)):
        for j in range(i + 1, len(wallets)):
            wa, wb = wallets[i], wallets[j]
            if find(wa) != find(wb) and fingerprints_similaires(fps[wa], fps[wb], **kw):
                union(wa, wb)
    clusters: dict[str, list[str]] = {}
    for w in par_wallet:
        clusters.setdefault(find(w), []).append(w)
    return {k: sorted(v) for k, v in clusters.items() if len(v) > 1}


def classer_population(path: str, *, cout_bps: float = FRAIS_TAKER_ROUNDTRIP_BPS, min_fills: int = 8) -> dict[str, Any]:
    """Streame le tape, groupe par wallet, évalue l'edge net copyable + enrichit, classe les candidats d'abord."""
    par_wallet: dict[str, list[dict[str, Any]]] = {}
    n_lignes = 0
    for r in flux_fills(path):
        n_lignes += 1
        adr = r.get("adresse") or r.get("wallet")
        if adr is None:
            continue
        par_wallet.setdefault(str(adr), []).append(r)

    clusters = _clusters_cotrade(_collect_events(par_wallet), fenetre_ms=2000)
    w_lie = {w for grp in clusters.values() for w in grp}

    lignes: list[dict[str, Any]] = []
    for adr, recs in par_wallet.items():
        if len(recs) < min_fills:
            continue
        row = evaluer_wallet(recs, adresse=adr, cout_bps=cout_bps)
        row["archetype"] = archetype(recs)
        row["entite_potentiellement_liee"] = adr in w_lie
        lignes.append(row)

    rang = {"CANDIDAT": 0, "FORWARD_REQUIS": 1, "KILL_CONCENTRE": 2, "KILL": 3, "MORE_DATA": 4}
    lignes.sort(key=lambda l: (rang.get(l.get("verdict"), 9), -(l.get("lcb_net_bps") or -1e9)))
    return {"n_lignes_streamees": n_lignes, "n_wallets": len(par_wallet), "n_evalues": len(lignes),
            "n_clusters_entite": len(clusters), "classement": lignes}


def bootstrap_population_by_vault_regime(
    rows: Sequence[Mapping[str, Any]],
    *,
    vault_field: str = "vault_id",
    regime_field: str = "regime_id",
    value_field: str = "net_usd",
    confidence: float = 0.95,
    n_bootstrap: int = 1000,
    seed: int = 7,
    min_vaults: int = 3,
    min_regimes: int = 2,
) -> dict[str, Any]:
    """Bootstrap observed vaults and regimes without over-counting fragments.

    Each vault is one population unit in a draw; a regime cell is first
    reduced to its observed mean, so repeated rows in one vault/regime cannot
    make that vault look like a larger independent population. Bootstrap
    draws sample vaults with replacement and then one observed regime cell
    within each selected vault. The result is a structural uncertainty
    interval only; it never certifies an economic edge or real execution.
    """
    result: dict[str, Any] = {
        "status": "UNMEASURABLE",
        "verdict": "INSUFFICIENT_DATA",
        "reason": None,
        "real_execution": False,
        "n_vaults": 0,
        "n_regimes": 0,
        "n_vault_regime_cells": 0,
        "n_observations": 0,
        "observed_mean": None,
        "bootstrap_ci_low": None,
        "bootstrap_ci_high": None,
        "vault_means": {},
        "regime_counts": {},
    }
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        result["reason"] = "confidence_invalide"
        return result
    confidence = float(confidence)
    if not 0.0 < confidence < 1.0:
        result["reason"] = "confidence_invalide"
        return result
    if isinstance(n_bootstrap, bool) or not isinstance(n_bootstrap, int) or n_bootstrap < 1:
        result["reason"] = "n_bootstrap_invalide"
        return result
    if isinstance(seed, bool) or not isinstance(seed, int):
        result["reason"] = "seed_invalide"
        return result
    if isinstance(min_vaults, bool) or not isinstance(min_vaults, int) or min_vaults < 2:
        result["reason"] = "min_vaults_invalide"
        return result
    if isinstance(min_regimes, bool) or not isinstance(min_regimes, int) or min_regimes < 1:
        result["reason"] = "min_regimes_invalide"
        return result

    cells: dict[str, dict[str, list[float]]] = {}
    for row in list(rows or []):
        if not isinstance(row, Mapping):
            result["reason"] = "ligne_invalide"
            return result
        vault = str(row.get(vault_field) or "").strip()
        regime = str(row.get(regime_field) or "").strip()
        value = row.get(value_field)
        if not vault or not regime or isinstance(value, bool):
            result["reason"] = "champ_manquant"
            return result
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError):
            result["reason"] = "valeur_invalide"
            return result
        if not math.isfinite(numeric):
            result["reason"] = "valeur_non_finie"
            return result
        cells.setdefault(vault, {}).setdefault(regime, []).append(numeric)

    if len(cells) < min_vaults:
        result["reason"] = "vaults_insuffisants"
        return result
    all_regimes = {regime for regimes in cells.values() for regime in regimes}
    if len(all_regimes) < min_regimes:
        result["reason"] = "regimes_insuffisants"
        return result
    if any(not regimes for regimes in cells.values()):
        result["reason"] = "regime_manquant"
        return result

    cell_means = {
        vault: {regime: statistics.fmean(values) for regime, values in regimes.items()}
        for vault, regimes in cells.items()
    }
    vault_ids = sorted(cell_means)
    vault_means = {
        vault: statistics.fmean(regimes.values())
        for vault, regimes in cell_means.items()
    }
    observed = statistics.fmean(vault_means.values())
    rng = random.Random(seed)
    bootstrap_means: list[float] = []
    for _ in range(n_bootstrap):
        sampled_values: list[float] = []
        for _ in vault_ids:
            vault = rng.choice(vault_ids)
            regime_ids = sorted(cell_means[vault])
            sampled_values.append(cell_means[vault][rng.choice(regime_ids)])
        bootstrap_means.append(statistics.fmean(sampled_values))

    ordered = sorted(bootstrap_means)
    alpha = (1.0 - confidence) / 2.0

    def quantile(q: float) -> float:
        position = (len(ordered) - 1) * q
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return ordered[lower]
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    regime_counts = {
        regime: sum(regime in regimes for regimes in cell_means.values())
        for regime in sorted(all_regimes)
    }
    result.update(
        status="PROVEN",
        verdict="POPULATION_REGIME_BOOTSTRAP_MEASURED",
        n_vaults=len(vault_ids),
        n_regimes=len(regime_counts),
        n_vault_regime_cells=sum(len(regimes) for regimes in cell_means.values()),
        n_observations=sum(len(values) for regimes in cells.values() for values in regimes.values()),
        observed_mean=observed,
        bootstrap_ci_low=quantile(alpha),
        bootstrap_ci_high=quantile(1.0 - alpha),
        vault_means=vault_means,
        regime_counts=regime_counts,
    )
    return result


__all__ = ["flux_fills", "archetype", "independance_entite", "fingerprint_wallet",
           "fingerprints_similaires", "clusters_entite", "classer_population",
           "bootstrap_population_by_vault_regime"]
