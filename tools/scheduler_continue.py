"""RESEARCH SCHEDULER ADAPTATIF (LABO-CONTINU-FINAL FINAL-4/5/6/7, Flo 26/07). Le moteur ne reste JAMAIS
inactif et ne rejoue JAMAIS les mêmes 64 variantes : il génère continuellement de NOUVEAUX trials utiles,
dédupliqués par signature canonique, via une recherche à plusieurs étages, et les priorise en 7 files.
L'objectif de sélection est MULTI-CRITÈRES (jamais le plus gros PnL brut seul). 0 réseau, 0 ordre.
"""
from __future__ import annotations

import hashlib
import json
import random

#: 7 files prioritaires (1 = plus prioritaire).
FILES = ("ingestion_sante", "forward_figes", "exact_survivants", "validation_stress",
         "exploration_familles", "amelioration_locale", "analyse_rejets")

CHAMPS_SIGNATURE = ("family", "version", "features", "params", "horizon_ms", "direction", "coins",
                    "regime", "dataset", "execution_model", "latency_model", "cost_model", "code_sha")


def signature_canonique(trial: dict) -> str:
    """Signature STABLE d'un trial sur tous ses champs canoniques -> déduplication fiable (identique = même sig)."""
    canon = {k: trial.get(k) for k in CHAMPS_SIGNATURE}
    return hashlib.sha256(json.dumps(canon, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def classer_nouveaute(trial: dict, deja_vus: set, *, zones: dict | None = None) -> str:
    """identique -> ne pas rejouer ; quasi_identique (mêmes family+horizon+direction+coins, params voisins)
    -> rattacher à la même zone ; nouvelle_hypothese -> nouveau trial ; correction_code -> nouvelle version."""
    sig = signature_canonique(trial)
    if sig in deja_vus:
        return "identique"
    zone = "%s|%s|%s|%s" % (trial.get("family"), trial.get("horizon_ms"), trial.get("direction"), tuple(trial.get("coins") or ()))
    if zones is not None and zone in zones:
        return "quasi_identique"
    return "nouvelle_hypothese"


# ─────────── recherche multi-étages : génère de NOUVELLES variantes à chaque cycle ───────────
def _grille(familles, directions, horizons, regimes, coins, seuils):
    for f in familles:
        for d in directions:
            for h in horizons:
                for reg in regimes:
                    for c in coins:
                        for s in seuils:
                            yield {"family": f, "direction": d, "horizon_ms": h, "regime": reg,
                                   "coins": [c], "params": {"seuil": s}}


def generer(*, cycle: int, deja_vus: set, familles, directions, horizons, regimes, coins,
            meilleurs: list[dict] | None = None, budget: int = 48, seed: int = 0, code_sha: str = "") -> list[dict]:
    """Génère jusqu'à `budget` variantes NOUVELLES (non déjà vues) en combinant les étages :
      1) grille grossière (couverture) indexée par le cycle (des seuils différents chaque cycle) ;
      2) random search (diversité) ;
      3) recherche LOCALE autour des meilleurs plateaux connus (raffinement).
    Successive halving est appliqué en aval (on ne garde que le haut du panier après FAST_SCREEN).
    Chaque variante est estampillée `code_sha` AVANT signature -> déduplication inter-cycles cohérente
    (la signature côté appelant se calcule sur le MÊME objet, sans re-fusion divergente)."""
    rng = random.Random(seed * 1000 + cycle)
    out, vus_local = [], set()

    def _ajouter(v):
        v["version"] = v.get("version", 1)
        v["code_sha"] = code_sha
        s = signature_canonique(v)
        if s in deja_vus or s in vus_local:
            return False
        vus_local.add(s); out.append(v)
        return True

    # étage 1 : grille dont les seuils DÉPENDENT du cycle -> jamais la même grille (pas de répétition)
    seuils = [4 + (cycle * 2 + k) % 20 for k in range(3)]
    for v in _grille(familles, directions, horizons, regimes, coins, seuils):
        _ajouter(v)
        if len(out) >= budget * 2 // 3:
            break
    # étage 2 : random search (diversité) sur des seuils/horizons tirés
    for _ in range(budget * 3):
        v = {"family": rng.choice(familles), "direction": rng.choice(directions),
             "horizon_ms": rng.choice(horizons), "regime": rng.choice(regimes),
             "coins": [rng.choice(coins)], "params": {"seuil": rng.randint(3, 40)}}
        _ajouter(v)
        if len(out) >= budget:
            break
    # étage 3 : recherche locale autour des meilleurs (raffinement de plateau)
    for m in (meilleurs or [])[:5]:
        base = int((m.get("params") or {}).get("seuil", 10))
        for delta in (-2, -1, 1, 2):
            _ajouter({**{k: m.get(k) for k in ("family", "direction", "horizon_ms", "regime", "coins")},
                      "params": {"seuil": max(1, base + delta)}})
    return out[:budget]


# ─────────── objectif multi-critères (jamais le PnL brut seul) ───────────
def score_multicritere(m: dict) -> float:
    """Score composite : récompense net/ROI/PF/DSR/stabilité/capacité, pénalise DD/coûts/dépendance-1-coin/
    instabilité/PBO/turnover/concentration/sensibilité. Un gros PnL BRUT instable/mono-coin NE gagne pas."""
    def g(k, d=0.0):
        v = m.get(k)
        return float(v) if isinstance(v, (int, float)) else d
    net = g("net_median_bps")
    if net <= 0:
        return net - 100.0                    # pas d'edge net -> jamais promu, quel que soit le brut
    bonus = (net * 1.0 + g("roi_immobilise_pct") * 0.5 + g("pf") * 5.0 + g("dsr") * 20.0
             + g("stabilite_oos") * 10.0 + g("capacite_norm") * 5.0 + g("regularite") * 5.0)
    penal = (g("drawdown_bps") * 0.3 + g("cout_bps") * 0.2 + g("dependance_coin") * 15.0
             + g("instabilite_params") * 10.0 + g("pbo") * 30.0 + g("turnover") * 2.0
             + g("concentration") * 10.0 + g("sensibilite_latence") * 5.0)
    return round(bonus - penal, 4)


class ResearchScheduler:
    """7 files prioritaires. On enfile des tâches, on défile toujours la file la plus prioritaire non vide.
    Le moteur ne reste jamais inactif : s'il n'y a pas de nouvelle donnée, les files exploration/amélioration/
    analyse fournissent du travail."""

    def __init__(self):
        self.files = {f: [] for f in FILES}

    def enfiler(self, file: str, tache: dict) -> None:
        if file not in self.files:
            raise ValueError("file inconnue: %s" % file)
        self.files[file].append(tache)

    def defiler(self) -> dict | None:
        for f in FILES:                       # ordre = priorité
            if self.files[f]:
                return {"file": f, **self.files[f].pop(0)}
        return None

    def taille(self) -> dict:
        return {f: len(self.files[f]) for f in FILES}

    def vide(self) -> bool:
        return all(not v for v in self.files.values())


__all__ = ["ResearchScheduler", "FILES", "signature_canonique", "classer_nouveaute", "generer",
           "score_multicritere", "CHAMPS_SIGNATURE"]
