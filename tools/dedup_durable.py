"""DÉDUPLICATION FORTE ET DURABLE (IDEA-9). Survit aux crashs, aux reprises et aux rotations de fichiers.

Le gate temps réel (`realtime/feed_quality.FeedQualityGate`) déduplique DANS LA MÉMOIRE d'un process : au
redémarrage, tout est oublié et un rejeu de la source peut re-compter les mêmes événements. Ici, l'ensemble
des identités vues est PERSISTÉ (journal append-only + compaction bornée), donc :

  • un événement déjà vu avant un crash reste un doublon après la reprise ;
  • la mémoire reste bornée (fenêtre glissante) pour un run 24/7 ;
  • aucune donnée n'est supprimée silencieusement : la compaction archive l'ancien journal.

0 réseau, 0 ordre, paper-only.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path


class DedupCorruptionError(RuntimeError):
    pass

FENETRE_DEFAUT = 200_000          # nombre max d'identités conservées (borne mémoire/disque 24/7)
COMPACTION_TOUS_LES = 50_000      # au-delà de N ajouts journalisés -> compaction + archive


class DedupDurable:
    """Ensemble d'identités vues, persistant. `vu(event_id)` rend True si l'événement est un DOUBLON."""

    def __init__(self, dossier: Path, *, fenetre: int = FENETRE_DEFAUT,
                 compaction_tous_les: int = COMPACTION_TOUS_LES):
        self.dir = Path(dossier)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.journal = self.dir / "dedup_journal.jsonl"
        self.snapshot = self.dir / "dedup_snapshot.json"
        self.archive = self.dir / "dedup_archive"
        self.fenetre = int(fenetre)
        self.compaction_tous_les = int(compaction_tous_les)
        self._ordre: list = []
        self._vus: set = set()
        self._depuis_compaction = 0
        self._charger()

    # ── persistance ──
    def _charger(self):
        if self.snapshot.exists():
            try:
                payload = json.loads(self.snapshot.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise DedupCorruptionError(
                    "dedup snapshot is unreadable; strict reuse is blocked"
                ) from exc
            for eid in payload.get("ids", []):
                if eid not in self._vus:
                    self._vus.add(eid); self._ordre.append(eid)
        if self.journal.exists():                       # rejeu du journal post-snapshot (reprise après crash)
            with self.journal.open("r", encoding="utf-8", errors="ignore") as f:
                for ligne in f:
                    eid = ligne.strip()
                    if eid and eid not in self._vus:
                        self._vus.add(eid); self._ordre.append(eid)
                        self._depuis_compaction += 1
        self._borner()

    def _borner(self):
        trop = len(self._ordre) - self.fenetre
        if trop > 0:
            for eid in self._ordre[:trop]:
                self._vus.discard(eid)
            del self._ordre[:trop]

    def compacter(self) -> dict:
        """Écrit un snapshot de l'état courant et ARCHIVE le journal (jamais supprimé), puis le vide."""
        tmp = self.snapshot.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump({"ids": self._ordre[-self.fenetre:]}, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.snapshot)
        if self.journal.exists() and self.journal.stat().st_size > 0:
            self.archive.mkdir(parents=True, exist_ok=True)
            os.replace(
                self.journal,
                self.archive / (
                    "dedup_%d_%s.jsonl"
                    % (time.time_ns(), uuid.uuid4().hex[:12])
                ),
            )
        with self.journal.open("w", encoding="utf-8") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        self._depuis_compaction = 0
        return {"n_ids": len(self._ordre), "snapshot": str(self.snapshot)}

    # ── API ──
    def vu(self, event_id: str) -> bool:
        """True si DÉJÀ vu (doublon). Sinon enregistre l'identité (durablement) et rend False."""
        eid = str(event_id)
        if eid in self._vus:
            return True
        self._vus.add(eid); self._ordre.append(eid)
        with self.journal.open("a", encoding="utf-8") as f:
            f.write(eid + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._depuis_compaction += 1
        self._borner()
        if self._depuis_compaction >= self.compaction_tous_les:
            self.compacter()
        return False

    def filtrer(self, evenements, *, cle: str = "event_id") -> tuple:
        """Sépare (nouveaux, doublons) en marquant `duplicate=True` sur les doublons (jamais de suppression
        silencieuse : l'appelant peut journaliser le doublon — cf. journal_operationnel)."""
        nouveaux, doublons = [], []
        for ev in evenements or []:
            eid = ev.get(cle) if isinstance(ev, dict) else ev
            if eid is None:
                nouveaux.append(ev)                     # sans identité : on ne peut pas dédupliquer honnêtement
                continue
            if self.vu(eid):
                if isinstance(ev, dict):
                    ev = {**ev, "duplicate": True}
                doublons.append(ev)
            else:
                nouveaux.append(ev)
        return nouveaux, doublons

    def compte(self) -> dict:
        return {"n_ids": len(self._ordre), "fenetre": self.fenetre,
                "depuis_compaction": self._depuis_compaction}


__all__ = [
    "DedupCorruptionError",
    "DedupDurable",
    "FENETRE_DEFAUT",
    "COMPACTION_TOUS_LES",
]
