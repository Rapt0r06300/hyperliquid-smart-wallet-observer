"""[LANCEUR items 7-câblage & 9] Orchestration de session de récolte : relie la COLLECTE réelle au
catalogue canonique (session_catalog) et au moniteur.

Au démarrage (après READY_CORE), le lanceur ouvre UNE session ACTIVE, écrit un pointeur `COURANTE.json`
(pour que moniteur/ANALYSER retrouvent la session vivante), et DÉCLARE toutes les sources attendues du
profil HARVEST dans le catalogue — chacune avec sa santé/ses compteurs dérivés du heartbeat réel, ou sa
raison d'absence (source non implémentée / aucun heartbeat). À l'arrêt propre, il clôt la session
(session COMPLETE seulement si tout est vérifié — item 8).

CLI (appelée par LANCER_HYPERSMART.cmd) : `ouvrir` · `enregistrer` · `cloturer` · `status`.
0 réseau, 0 ordre. Aucune donnée fabriquée : une source sans preuve reste DÉCLARÉE absente.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from hl_observer.ops import session_catalog as SC
from hl_observer.ops.preuve_de_vie import (SOURCES_HARVEST, SourceAttendue, cause_source,
                                           lire_heartbeats_reels, metriques_depuis_heartbeats,
                                           preuve_source, _pid_vivant_reel)

POINTEUR = "COURANTE.json"       # runtime/data/sessions/COURANTE.json -> {run_id, ts_ms}


def _chemin_pointeur(root: str | Path) -> Path:
    return Path(root) / "runtime" / "data" / "sessions" / POINTEUR


def _ecrire_pointeur(root: str | Path, run_id: str, *, horloge=time.time) -> None:
    p = _chemin_pointeur(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(".%s.%d.tmp" % (POINTEUR, os.getpid()))
    tmp.write_text(json.dumps({"run_id": run_id, "ts_ms": int(horloge() * 1000)}, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, p)


def run_id_courant(root: str | Path) -> str | None:
    try:
        return json.loads(_chemin_pointeur(root).read_text(encoding="utf-8")).get("run_id")
    except (OSError, ValueError):
        return None


def ouvrir_session_harvest(root: str | Path, *, run_id: str | None = None, git_head: str | None = None,
                           sources: Sequence[SourceAttendue] = SOURCES_HARVEST,
                           now_ms: float | None = None, horloge=time.time) -> tuple[str, dict]:
    """Crée la session ACTIVE, écrit le pointeur COURANTE, et déclare toutes les sources attendues."""
    rid = run_id or SC.nouveau_run_id("harvest", horloge=horloge)
    cat = SC.CatalogueSession(root, rid)
    cat.demarrer(git_head=git_head, contexte={"profil": "HARVEST"}, horloge=horloge)
    _ecrire_pointeur(root, rid, horloge=horloge)
    enregistrer_sources_declarees(root, rid, sources=sources,
                                  now_ms=now_ms if now_ms is not None else horloge() * 1000.0)
    return rid, cat.lire()


def enregistrer_sources_declarees(root: str | Path, run_id: str, *,
                                  sources: Sequence[SourceAttendue] = SOURCES_HARVEST,
                                  now_ms: float, artefacts: Mapping[str, str] | None = None,
                                  pid_vivant=_pid_vivant_reel) -> dict:
    """Déclare/actualise CHAQUE source attendue dans le catalogue (item 3 : jamais omise). Les compteurs
    (événements, gaps, reconnects, stale, hors-ordre) et la santé viennent du heartbeat RÉEL ; une source
    non implémentée ou sans heartbeat est DÉCLARÉE absente avec sa raison (jamais inventée)."""
    artefacts = dict(artefacts or {})
    hbs = lire_heartbeats_reels(root, sources)
    metriques = metriques_depuis_heartbeats(hbs)
    cat = SC.CatalogueSession(root, run_id)
    resume = {"declarees": 0, "vivantes": 0, "absentes": 0}
    for s in sources:
        hb = hbs.get(s.nom) or {}
        m = metriques.get(s.nom) or {}
        entree = SC.EntreeSource(source=s.nom, venue=s.venue, canal=s.canal,
                                 chemin=artefacts.get(s.nom, ""))
        if s.non_implementee:
            entree.raison_absence = "source non implementee (aucun collecteur reel)"
            entree.sante = "GRISE"
            resume["absentes"] += 1
        elif not hb:
            entree.raison_absence = "aucun heartbeat : le collecteur n'a rien rapporte"
            entree.sante = "ROUGE"
            resume["absentes"] += 1
        else:
            p = preuve_source(s, hb, now_ms=now_ms, pid_vivant=pid_vivant,
                              gaps_critiques=int(m.get("gaps_critiques", 0)),
                              carnet_desync=bool(m.get("carnet_desync", False)),
                              sequence_invalide=bool(m.get("sequence_invalide", False)),
                              resync_en_attente=bool(m.get("resync_en_attente", False)),
                              stale=bool(m.get("stale", False)),
                              hors_ordre=int(m.get("hors_ordre", 0)),
                              reconnexions=int(m.get("reconnects", 0)))
            c = cause_source(s, p, ecrites=int(hb.get("n_ecrites_cumul") or 0),
                             ecrites_precedentes=None, reconnexions=int(m.get("reconnects", 0)),
                             heartbeat_present=True)
            entree.sante = {"VERTE": "VERTE", "ORANGE": "ORANGE", "ROUGE": "ROUGE",
                            "GRISE": "GRISE"}.get(c.get("sante", "GRISE"), "GRISE")
            entree.evenements_recus = int(hb.get("n_ecrites_cumul") or 0)
            entree.evenements_valides = int(hb.get("n_ecrites_cumul") or 0)
            entree.dernier_ts_reception = int(hb.get("ts_ms")) if hb.get("ts_ms") is not None else None
            ex = hb.get("dernier_exchange_ts")
            entree.dernier_ts_exchange = int(ex) if isinstance(ex, (int, float)) else None
            entree.gaps = int(m.get("gaps_critiques", 0))
            entree.reconnects = int(m.get("reconnects", 0))
            entree.stale = bool(m.get("stale", False))
            entree.hors_ordre = int(m.get("hors_ordre", 0))
            entree.metadata = {"cause": c.get("cause")}
            if p.sain:
                resume["vivantes"] += 1
            else:
                entree.raison_absence = p.raison
                resume["absentes"] += 1
        try:
            cat.enregistrer_source(entree)
            resume["declarees"] += 1
        except SC.SessionFigeeError:
            break                    # session déjà figée : on n'écrit plus (honnête)
    return resume


def cloturer_session_courante(root: str | Path, *, writers_arretes: bool, horloge=time.time) -> dict:
    """Clôt la session pointée par COURANTE (item 8). Sans pointeur → rien à clôturer."""
    rid = run_id_courant(root)
    if not rid:
        return {"statut": "AUCUNE_SESSION", "motifs": ["pas de session courante"]}
    verdict = SC.CatalogueSession(root, rid).cloturer(writers_arretes=writers_arretes, horloge=horloge)
    verdict["run_id"] = rid
    return verdict


def _statut_session_courante(root: str | Path) -> dict:
    rid = run_id_courant(root)
    if not rid:
        return {"run_id": None, "statut": "AUCUNE"}
    cat = SC.CatalogueSession(root, rid).lire()
    return {"run_id": rid, "statut": cat.get("statut"), "sources": len(cat.get("sources") or {})}


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Orchestration de session de recolte (catalogue canonique).")
    p.add_argument("action", choices=("ouvrir", "enregistrer", "cloturer", "status"))
    p.add_argument("racine", nargs="?", default=".")
    p.add_argument("--writers-arretes", action="store_true",
                   help="cloture : atteste que tous les writers/DB sont arretes et flush")
    args = p.parse_args(argv)
    root = Path(args.racine)
    if args.action == "ouvrir":
        rid, cat = ouvrir_session_harvest(root)
        print("SESSION_OUVERTE run_id=%s statut=%s sources=%d" %
              (rid, cat.get("statut"), len(cat.get("sources") or {})), flush=True)
        return 0
    if args.action == "enregistrer":
        rid = run_id_courant(root)
        if not rid:
            print("AUCUNE_SESSION_COURANTE", flush=True)
            return 2
        r = enregistrer_sources_declarees(root, rid, now_ms=time.time() * 1000.0)
        print("SOURCES declarees=%d vivantes=%d absentes=%d" %
              (r["declarees"], r["vivantes"], r["absentes"]), flush=True)
        return 0
    if args.action == "cloturer":
        v = cloturer_session_courante(root, writers_arretes=bool(args.writers_arretes))
        print("CLOTURE statut=%s run_id=%s motifs=%s" %
              (v.get("statut"), v.get("run_id"), ",".join(v.get("motifs", []) or [])), flush=True)
        return 0 if v.get("statut") == SC.STATUT_COMPLETE else 2
    st = _statut_session_courante(root)
    print("SESSION run_id=%s statut=%s sources=%s" %
          (st.get("run_id"), st.get("statut"), st.get("sources")), flush=True)
    return 0


__all__ = ["POINTEUR", "run_id_courant", "ouvrir_session_harvest", "enregistrer_sources_declarees",
           "cloturer_session_courante", "main"]
