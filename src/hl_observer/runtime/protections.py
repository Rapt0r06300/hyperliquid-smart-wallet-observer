"""Protections critiques portées du LEGACY vers le runtime canonique (pur, 0 réseau, 0 ordre).

Ces gardes vivaient dans ``tools/`` et n'étaient appelées que par l'ancien moteur de
recherche continue. Elles sont maintenant importables par le runtime officiel.

Le contrat de ce module est volontairement fail-closed :
- une déduplication survit au crash sans charger un fichier entier en RAM ;
- un incident réel reste journalisé et relisible en streaming ;
- un lecteur d'incidents peut être strictement non-mutant ;
- un ledger corrompu est localisé par offset sans ``read_text`` massif ;
- une source externe ne crée jamais un signal ;
- provenance inconnue, ingestion inconnue et données synthétiques ne deviennent
  jamais des preuves fortes par défaut.

IDEA-11 (TruthReconciler) n'est pas dupliquée ici : la vérité canonique vit dans
``hl_observer.market_truth.truth_chain``.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections import deque
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "hypersmart.runtime_protections.v2"
DEFAULT_DEDUP_MAX_IDS = 200_000
DEFAULT_DEDUP_COMPACT_EVERY = 50_000

TYPES_INCIDENT = (
    "WS_GAP",
    "RECONNECT",
    "DUPLICATE",
    "OUTLIER",
    "DATA_MISSING",
    "LEDGER_MISMATCH",
    "PNL_UNTRUSTED",
    "CLOCK_SKEW",
    "QUEUE_OVERFLOW",
    "CRASH",
    "PARSE_ERROR",
)
BLOQUANTS = ("DATA_MISSING", "LEDGER_MISMATCH", "PNL_UNTRUSTED")


class DedupDurable:
    """Dédup durable et bornée.

    Le journal est relu ligne par ligne au démarrage. Seule une fenêtre bornée est
    gardée en mémoire et le fichier est périodiquement compacté de façon atomique.
    """

    def __init__(
        self,
        dossier: Path | str,
        *,
        max_ids: int = DEFAULT_DEDUP_MAX_IDS,
        compact_every: int = DEFAULT_DEDUP_COMPACT_EVERY,
    ) -> None:
        if int(max_ids) <= 0:
            raise ValueError("max_ids must be > 0")
        if int(compact_every) <= 0:
            raise ValueError("compact_every must be > 0")
        self.dossier = Path(dossier)
        self.dossier.mkdir(parents=True, exist_ok=True)
        self.journal = self.dossier / "dedup_journal.jsonl"
        self.max_ids = int(max_ids)
        self.compact_every = int(compact_every)
        self._ordre: deque[str] = deque()
        self._vus: set[str] = set()
        self._ajouts_depuis_compaction = 0
        self._charger_streaming()

    def _ajouter_memoire(self, cle: str) -> None:
        if cle in self._vus:
            return
        self._vus.add(cle)
        self._ordre.append(cle)
        while len(self._ordre) > self.max_ids:
            retire = self._ordre.popleft()
            self._vus.discard(retire)

    def _charger_streaming(self) -> None:
        if not self.journal.exists():
            return
        with self.journal.open("r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                cle = raw.strip()
                if cle:
                    self._ajouter_memoire(cle)

    def _compacter(self) -> None:
        tmp = self.journal.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            for cle in self._ordre:
                handle.write(cle + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.journal)
        self._ajouts_depuis_compaction = 0

    def vu(self, cle: str) -> bool:
        return str(cle) in self._vus

    def marquer(self, cle: str) -> None:
        cle = str(cle)
        if cle in self._vus:
            return
        self._ajouter_memoire(cle)
        with self.journal.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(cle + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._ajouts_depuis_compaction += 1
        if self._ajouts_depuis_compaction >= self.compact_every:
            self._compacter()

    def filtrer(self, evenements: Iterable[Mapping[str, Any]], *, cle: str = "event_id"):
        """Rend ``(nouveaux, doublons)`` ; un doublon n'est jamais jeté en silence."""
        nouveaux, doublons = [], []
        for ev in evenements:
            identifiant = str((ev or {}).get(cle) or "")
            if not identifiant:
                nouveaux.append(ev)
                continue
            if self.vu(identifiant):
                doublons.append(ev)
            else:
                self.marquer(identifiant)
                nouveaux.append(ev)
        return nouveaux, doublons

    def stats(self) -> dict[str, int]:
        return {
            "n_ids_en_memoire": len(self._vus),
            "max_ids": self.max_ids,
            "ajouts_depuis_compaction": self._ajouts_depuis_compaction,
        }


class JournalIncidents:
    """Journal append-only des incidents réels, relu en streaming.

    ``create=False`` garantit qu'une lecture de diagnostic ne crée ni dossier ni
    fichier. Toute écriture avec ce mode est refusée explicitement.
    """

    def __init__(self, dossier: Path | str, *, create: bool = True) -> None:
        self.dossier = Path(dossier)
        self.create = bool(create)
        if self.create:
            self.dossier.mkdir(parents=True, exist_ok=True)
        self.chemin = self.dossier / "incidents.jsonl"

    def enregistrer(self, type_: str, **details: Any) -> dict[str, Any]:
        if not self.create:
            raise RuntimeError("JournalIncidents(create=False) est strictement read-only")
        type_normalise = str(type_).upper()
        if type_normalise not in TYPES_INCIDENT:
            raise ValueError(f"type incident inconnu: {type_normalise}")
        ligne = {"type": type_normalise, **details}
        with self.chemin.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(ligne, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return ligne

    def resume(self) -> dict[str, Any]:
        par_type: dict[str, int] = {}
        if self.chemin.exists():
            with self.chemin.open("r", encoding="utf-8", errors="replace") as handle:
                for raw in handle:
                    ligne = raw.strip()
                    if not ligne:
                        continue
                    try:
                        type_normalise = str(json.loads(ligne).get("type") or "").upper()
                    except ValueError:
                        type_normalise = "PARSE_ERROR"
                    if type_normalise not in TYPES_INCIDENT:
                        type_normalise = "PARSE_ERROR"
                    par_type[type_normalise] = par_type.get(type_normalise, 0) + 1
        bloquant = any(par_type.get(type_) for type_ in BLOQUANTS)
        return {
            "n_incidents": sum(par_type.values()),
            "par_type": par_type,
            "promotion_interdite": bool(bloquant),
        }


def scanner_ledger(chemin: Path | str) -> dict[str, Any]:
    """Scanne un JSONL en mémoire bornée et localise les lignes invalides par byte offset."""
    path = Path(chemin)
    if not path.exists():
        return {
            "statut": "ABSENT",
            "n_lignes": 0,
            "n_erreurs": 0,
            "erreurs": [],
            "promotion_autorisee": True,
        }

    erreurs: list[dict[str, Any]] = []
    n_lignes = 0
    offset = 0
    with path.open("rb") as handle:
        for numero, raw in enumerate(handle, start=1):
            courant = offset
            offset += len(raw)
            if not raw.strip():
                continue
            n_lignes += 1
            try:
                texte = raw.decode("utf-8", errors="strict")
                objet = json.loads(texte)
                if not isinstance(objet, dict):
                    raise ValueError("ligne JSON qui n'est pas un objet")
            except (UnicodeDecodeError, ValueError) as exc:
                erreurs.append(
                    {
                        "ligne": numero,
                        "offset": courant,
                        "motif": str(exc)[:120],
                    }
                )

    return {
        "statut": "CORROMPU" if erreurs else "OK",
        "n_lignes": n_lignes,
        "n_erreurs": len(erreurs),
        "erreurs": erreurs[:50],
        "promotion_autorisee": not erreurs,
    }


def sanity_cross_source(valeurs: Mapping[str, Any], *, tolerance_bps: float = 50.0) -> dict[str, Any]:
    """Une confirmation cross-source est un contrôle qualité, jamais un signal."""
    nombres = {
        key: float(value)
        for key, value in valeurs.items()
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float(value) == float(value)
    }
    if len(nombres) < 2:
        return {
            "statut": "NON_COMPARABLE",
            "n_sources": len(nombres),
            "ecart_bps": None,
            "coherent": None,
            "signal_autorise": False,
        }
    reference = sum(nombres.values()) / len(nombres)
    ecart = (
        max(abs(value - reference) for value in nombres.values()) / abs(reference) * 1e4
        if reference
        else float("inf")
    )
    return {
        "statut": "COMPARE",
        "n_sources": len(nombres),
        "ecart_bps": round(ecart, 4),
        "coherent": bool(ecart <= float(tolerance_bps)),
        "reference": reference,
        "signal_autorise": False,
    }


def manifeste_execution(racine: Path | str, **contexte: Any) -> dict[str, Any]:
    """Provenance du run. Git muet = INCONNU = non reproductible."""
    import platform
    import sys

    def _git(*args: str, timeout: float = 8.0) -> str | None:
        proc = None
        try:
            proc = subprocess.Popen(
                ["git", *args],
                cwd=str(racine),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            sortie, _ = proc.communicate(timeout=timeout)
            return None if proc.returncode != 0 else (sortie or "").strip()
        except Exception:  # noqa: BLE001
            if proc is not None:
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    import logging as _lg
                    _lg.getLogger(__name__).debug("kill git impossible", exc_info=True)
            return None

    head = _git("rev-parse", "HEAD")
    statut = _git("status", "--porcelain")
    sale = None if statut is None else bool(statut.strip())
    return {
        "schema_version": SCHEMA_VERSION,
        "git_head": head or None,
        "git_dirty": sale,
        "python": sys.version.split()[0],
        "plateforme": platform.system(),
        "reproductible": bool(head) and sale is False,
        "avertissement": (
            "arbre git SALE : resultat non reproductible tel quel"
            if sale
            else None
            if sale is False
            else "etat git INCONNU : traite comme NON reproductible"
        ),
        "contexte": dict(contexte),
        "real_execution": False,
    }


def etat_ingestion(*, n_nouveaux_evenements: int | None, erreur_scanner: str | None = None) -> dict[str, Any]:
    """Une panne de collecte n'est jamais assimilée à un marché calme."""
    if erreur_scanner:
        return {
            "statut": "DATA_INGESTION_FAILED",
            "sante": "ROUGE",
            "promotion_autorisee": False,
            "erreur": str(erreur_scanner)[:200],
            "motif": "panne de collecte — surtout pas interpretee comme un marche calme",
        }
    if n_nouveaux_evenements is None:
        return {
            "statut": "INGESTION_INCONNUE",
            "sante": "ROUGE",
            "promotion_autorisee": False,
            "motif": "nombre d'evenements inconnu : on ne suppose pas que tout va bien",
        }
    if int(n_nouveaux_evenements) == 0:
        return {
            "statut": "ZERO_NEW_EVENTS",
            "sante": "VERTE",
            "promotion_autorisee": True,
            "motif": "aucun evenement, mais la collecte fonctionne : marche calme",
        }
    return {
        "statut": "OK",
        "sante": "VERTE",
        "promotion_autorisee": True,
        "n_evenements": int(n_nouveaux_evenements),
    }


def verrou_synthetique(verdict: Mapping[str, Any]) -> dict[str, Any]:
    """Une donnée synthétique peut tester la plomberie, jamais promouvoir une stratégie."""
    origine = str(verdict.get("data_origin") or "").upper()
    rendu = str(verdict.get("verdict") or "").upper()
    promouvant = rendu.startswith("PASS") or rendu in {"PROMOTED", "SCALE"}
    violation = bool(origine in {"SYNTHETIC", "SYNTHETIQUE", "FAKE", "MOCK"} and promouvant)
    return {
        "violation": violation,
        "data_origin": origine or None,
        "verdict_original": rendu or None,
        "verdict_corrige": "SHADOW_SYNTHETIQUE" if violation else (rendu or None),
        "motif": "une donnee synthetique ne promeut jamais" if violation else None,
    }


def controler_avant_promotion(
    rundir: Path | str,
    *,
    verdicts: Sequence[Mapping[str, Any]] = (),
    ledger_relpath: str = "ledger.jsonl",
) -> dict[str, Any]:
    """Verrou unique avant promotion : ledger, incidents, synthétique."""
    base = Path(rundir)
    raisons: list[str] = []
    ledger = scanner_ledger(base / ledger_relpath)
    if not ledger["promotion_autorisee"]:
        raisons.append("LEDGER_CORROMPU")
    incidents = JournalIncidents(base / "operational", create=False).resume()
    if incidents["promotion_interdite"]:
        raisons.append("INCIDENT_BLOQUANT")
    synthetiques = [verrou_synthetique(verdict) for verdict in verdicts]
    if any(item["violation"] for item in synthetiques):
        raisons.append("PROMOTION_SUR_DONNEE_SYNTHETIQUE")
    return {
        "promotion_autorisee": not raisons,
        "raisons": raisons,
        "ledger": ledger,
        "incidents": incidents,
        "synthetiques": [item for item in synthetiques if item["violation"]],
        "real_execution": False,
    }


def empreinte(valeur: Any) -> str:
    return hashlib.sha256(
        json.dumps(valeur, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()[:16]


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_DEDUP_MAX_IDS",
    "DEFAULT_DEDUP_COMPACT_EVERY",
    "TYPES_INCIDENT",
    "BLOQUANTS",
    "DedupDurable",
    "JournalIncidents",
    "scanner_ledger",
    "sanity_cross_source",
    "manifeste_execution",
    "etat_ingestion",
    "verrou_synthetique",
    "controler_avant_promotion",
    "empreinte",
]
