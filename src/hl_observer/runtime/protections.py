"""Protections critiques portées du LEGACY vers le runtime canonique (pur, 0 réseau, 0 ordre).

Ces gardes vivaient dans `tools/` et n'étaient appelés que par `tools/recherche_continue.py`, moteur
désormais gelé. Une protection qui ne vit que dans le legacy ne protège rien : l'audit de câblage les avait
classées `TODO_ACTIVE`. Elles sont ici, importables par `src/hl_observer`, donc par le runtime officiel et
par la suite d'analyse.

| IDEA | Garde | Ce qu'elle empêche |
|---|---|---|
| 9 | `DedupDurable` | qu'un événement rejoué après un crash compte deux fois |
| 10 | `JournalIncidents` | qu'une panne disparaisse sans trace |
| 36 | `scanner_ledger` | qu'un ledger corrompu produise un PnL d'apparence normale |
| 71 | `sanity_cross_source` | qu'une source externe devienne un signal sans confirmation |
| 78 | `manifeste_execution` | qu'un résultat produit sur un arbre sale se dise reproductible |
| 79 | `etat_ingestion` | qu'une panne de collecte passe pour un marché calme |
| 80 | `verrou_synthetique` | qu'une donnée synthétique promeuve une stratégie |

IDEA-11 (TruthReconciler) n'est pas reportée ici : son équivalent canonique existe déjà dans
`hl_observer.market_truth.truth_chain`. Dupliquer serait créer une seconde vérité.

Un test d'équivalence compare chaque garde à son ancêtre `tools/` : si les deux divergent un jour, il tombe.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "hypersmart.runtime_protections.v1"

#: IDEA-10 — types d'incidents. `BLOQUANTS` interdit toute promotion tant qu'ils sont présents.
TYPES_INCIDENT = ("WS_GAP", "RECONNECT", "DUPLICATE", "OUTLIER", "DATA_MISSING", "LEDGER_MISMATCH",
                  "PNL_UNTRUSTED", "CLOCK_SKEW", "QUEUE_OVERFLOW", "CRASH", "PARSE_ERROR")
BLOQUANTS = ("DATA_MISSING", "LEDGER_MISMATCH", "PNL_UNTRUSTED")


# ════════════════════════ IDEA-9 — dédup durable ════════════════════════
class DedupDurable:
    """Dédup qui SURVIT au redémarrage : l'état est sur disque, pas en mémoire.

    Un `set` en mémoire oublie tout au crash ; l'événement rejoué compte alors une seconde fois et le PnL
    double sans que rien ne le signale.
    """

    def __init__(self, dossier: Path | str) -> None:
        self.dossier = Path(dossier)
        self.dossier.mkdir(parents=True, exist_ok=True)
        self.journal = self.dossier / "dedup_journal.jsonl"
        self._vus: set[str] = set()
        if self.journal.exists():
            for ligne in self.journal.read_text(encoding="utf-8", errors="replace").splitlines():
                ligne = ligne.strip()
                if ligne:
                    self._vus.add(ligne)

    def vu(self, cle: str) -> bool:
        return str(cle) in self._vus

    def marquer(self, cle: str) -> None:
        cle = str(cle)
        if cle in self._vus:
            return
        self._vus.add(cle)
        with self.journal.open("a", encoding="utf-8") as fh:
            fh.write(cle + "\n")

    def filtrer(self, evenements: Iterable[Mapping[str, Any]], *, cle: str = "event_id"):
        """Rend (nouveaux, doublons). Un doublon n'est jamais jeté en silence : il est rendu."""
        nouveaux, doublons = [], []
        for ev in evenements:
            identifiant = str((ev or {}).get(cle) or "")
            if not identifiant:
                nouveaux.append(ev)          # sans identite, on ne peut pas affirmer que c'est un doublon
                continue
            if self.vu(identifiant):
                doublons.append(ev)
            else:
                self.marquer(identifiant)
                nouveaux.append(ev)
        return nouveaux, doublons


# ════════════════════════ IDEA-10 — journal des incidents ════════════════════════
class JournalIncidents:
    """Journal append-only des incidents réels. Une panne non écrite n'a jamais eu lieu."""

    def __init__(self, dossier: Path | str) -> None:
        self.dossier = Path(dossier)
        self.dossier.mkdir(parents=True, exist_ok=True)
        self.chemin = self.dossier / "incidents.jsonl"

    def enregistrer(self, type_: str, **details: Any) -> dict[str, Any]:
        ligne = {"type": str(type_).upper(), **details}
        with self.chemin.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ligne, ensure_ascii=False) + "\n")
        return ligne

    def resume(self) -> dict[str, Any]:
        par_type: dict[str, int] = {}
        if self.chemin.exists():
            for ligne in self.chemin.read_text(encoding="utf-8", errors="replace").splitlines():
                ligne = ligne.strip()
                if not ligne:
                    continue
                try:
                    t = str(json.loads(ligne).get("type") or "").upper()
                except ValueError:
                    t = "PARSE_ERROR"
                par_type[t] = par_type.get(t, 0) + 1
        bloquant = any(par_type.get(t) for t in BLOQUANTS)
        return {"n_incidents": sum(par_type.values()), "par_type": par_type,
                "promotion_interdite": bool(bloquant)}


# ════════════════════════ IDEA-36 — ledger corrompu ════════════════════════
def scanner_ledger(chemin: Path | str) -> dict[str, Any]:
    """Localise CHAQUE ligne invalide (numéro + offset). Un ledger illisible interdit toute promotion."""
    p = Path(chemin)
    if not p.exists():
        return {"statut": "ABSENT", "n_lignes": 0, "n_erreurs": 0, "erreurs": [],
                "promotion_autorisee": True}
    erreurs: list[dict[str, Any]] = []
    n = 0
    offset = 0
    for i, brute in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        taille = len(brute.encode("utf-8", errors="replace")) + 1
        if brute.strip():
            n += 1
            try:
                obj = json.loads(brute)
                if not isinstance(obj, dict):
                    raise ValueError("ligne JSON qui n'est pas un objet")
            except ValueError as exc:
                erreurs.append({"ligne": i, "offset": offset, "motif": str(exc)[:120]})
        offset += taille
    return {"statut": "CORROMPU" if erreurs else "OK", "n_lignes": n, "n_erreurs": len(erreurs),
            "erreurs": erreurs[:50], "promotion_autorisee": not erreurs}


# ════════════════════════ IDEA-71 — sanity cross-source ════════════════════════
def sanity_cross_source(valeurs: Mapping[str, Any], *, tolerance_bps: float = 50.0) -> dict[str, Any]:
    """Compare plusieurs sources d'une même grandeur. **`signal_autorise` est toujours `False`** :
    une confirmation croisée sert à détecter une anomalie, jamais à créer un signal."""
    nombres = {k: float(v) for k, v in valeurs.items()
               if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) == float(v)}
    if len(nombres) < 2:
        return {"statut": "NON_COMPARABLE", "n_sources": len(nombres), "ecart_bps": None,
                "coherent": None, "signal_autorise": False}
    ref = sum(nombres.values()) / len(nombres)
    ecart = max(abs(v - ref) for v in nombres.values()) / abs(ref) * 1e4 if ref else float("inf")
    return {"statut": "COMPARE", "n_sources": len(nombres), "ecart_bps": round(ecart, 4),
            "coherent": bool(ecart <= float(tolerance_bps)), "reference": ref,
            "signal_autorise": False}


# ════════════════════════ IDEA-78 — manifeste d'exécution ════════════════════════
def manifeste_execution(racine: Path | str, **contexte: Any) -> dict[str, Any]:
    """Provenance du run. Un `git` muet rend `None` (INCONNU), jamais « arbre propre »."""
    import platform
    import sys

    def _git(*args: str, timeout: float = 8.0) -> str | None:
        proc = None
        try:
            proc = subprocess.Popen(["git", *args], cwd=str(racine), stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True)
            sortie, _ = proc.communicate(timeout=timeout)
            return None if proc.returncode != 0 else (sortie or "").strip()
        except Exception:  # noqa: BLE001
            if proc is not None:
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            return None

    head = _git("rev-parse", "HEAD")
    statut = _git("status", "--porcelain")
    sale = None if statut is None else bool(statut.strip())
    return {"schema_version": SCHEMA_VERSION, "git_head": head or None, "git_dirty": sale,
            "python": sys.version.split()[0], "plateforme": platform.system(),
            "reproductible": bool(head) and sale is False,
            "avertissement": ("arbre git SALE : resultat non reproductible tel quel" if sale else
                              None if sale is False else
                              "etat git INCONNU : traite comme NON reproductible"),
            "contexte": dict(contexte), "real_execution": False}


# ════════════════════════ IDEA-79 — panne ≠ marché calme ════════════════════════
def etat_ingestion(*, n_nouveaux_evenements: int | None, erreur_scanner: str | None = None) -> dict[str, Any]:
    """Une panne de collecte n'est pas un marché calme. Confondre les deux, c'est trader à l'aveugle."""
    if erreur_scanner:
        return {"statut": "DATA_INGESTION_FAILED", "sante": "ROUGE", "promotion_autorisee": False,
                "erreur": str(erreur_scanner)[:200],
                "motif": "panne de collecte — surtout pas interpretee comme un marche calme"}
    if n_nouveaux_evenements is None:
        return {"statut": "INGESTION_INCONNUE", "sante": "ROUGE", "promotion_autorisee": False,
                "motif": "nombre d'evenements inconnu : on ne suppose pas que tout va bien"}
    if int(n_nouveaux_evenements) == 0:
        return {"statut": "ZERO_NEW_EVENTS", "sante": "VERTE", "promotion_autorisee": True,
                "motif": "aucun evenement, mais la collecte fonctionne : marche calme"}
    return {"statut": "OK", "sante": "VERTE", "promotion_autorisee": True,
            "n_evenements": int(n_nouveaux_evenements)}


# ════════════════════════ IDEA-80 — verrou synthétique ════════════════════════
def verrou_synthetique(verdict: Mapping[str, Any]) -> dict[str, Any]:
    """Une donnée synthétique est de la plomberie. Elle ne promeut jamais une stratégie."""
    origine = str(verdict.get("data_origin") or "").upper()
    rendu = str(verdict.get("verdict") or "").upper()
    promouvant = rendu.startswith("PASS") or rendu in {"PROMOTED", "SCALE"}
    violation = bool(origine in {"SYNTHETIC", "SYNTHETIQUE", "FAKE", "MOCK"} and promouvant)
    return {"violation": violation, "data_origin": origine or None, "verdict_original": rendu or None,
            "verdict_corrige": "SHADOW_SYNTHETIQUE" if violation else (rendu or None),
            "motif": ("une donnee synthetique ne promeut jamais" if violation else None)}


# ════════════════════════ couture ════════════════════════
def controler_avant_promotion(rundir: Path | str, *, verdicts: Sequence[Mapping[str, Any]] = (),
                              ledger_relpath: str = "ledger.jsonl") -> dict[str, Any]:
    """Verrou unique appelé avant toute promotion : ledger lisible, incidents non bloquants, aucun
    verdict adossé à du synthétique."""
    base = Path(rundir)
    raisons: list[str] = []
    led = scanner_ledger(base / ledger_relpath)
    if not led["promotion_autorisee"]:
        raisons.append("LEDGER_CORROMPU")
    incidents = JournalIncidents(base / "operational").resume()
    if incidents["promotion_interdite"]:
        raisons.append("INCIDENT_BLOQUANT")
    synthetiques = [verrou_synthetique(v) for v in verdicts]
    if any(s["violation"] for s in synthetiques):
        raisons.append("PROMOTION_SUR_DONNEE_SYNTHETIQUE")
    return {"promotion_autorisee": not raisons, "raisons": raisons, "ledger": led,
            "incidents": incidents, "synthetiques": [s for s in synthetiques if s["violation"]],
            "real_execution": False}


def empreinte(valeur: Any) -> str:
    return hashlib.sha256(json.dumps(valeur, sort_keys=True, ensure_ascii=False, default=str)
                          .encode("utf-8")).hexdigest()[:16]


__all__ = ["SCHEMA_VERSION", "TYPES_INCIDENT", "BLOQUANTS", "DedupDurable", "JournalIncidents",
           "scanner_ledger", "sanity_cross_source", "manifeste_execution", "etat_ingestion",
           "verrou_synthetique", "controler_avant_promotion", "empreinte"]
