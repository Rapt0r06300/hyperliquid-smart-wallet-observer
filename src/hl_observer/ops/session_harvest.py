"""Orchestration canonique d'une session HARVEST.

La session n'est COMPLETE que si ses sources sont prouvées et si tous les
writers enregistrés sont réellement arrêtés. Aucun réseau ni ordre ici.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from hl_observer.ops import session_catalog as SC
from hl_observer.ops.preuve_de_vie import (
    SOURCES_HARVEST,
    SourceAttendue,
    _pid_vivant_reel,
    cause_source,
    lire_heartbeats_reels,
    metriques_depuis_heartbeats,
    preuve_source,
)

POINTEUR = "COURANTE.json"


def _chemin_pointeur(root: str | Path) -> Path:
    return Path(root) / "runtime" / "data" / "sessions" / POINTEUR


def _ecrire_pointeur(root: str | Path, run_id: str, *, horloge=time.time) -> None:
    p = _chemin_pointeur(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(".%s.%d.tmp" % (POINTEUR, os.getpid()))
    tmp.write_text(
        json.dumps({"run_id": run_id, "ts_ms": int(horloge() * 1000)}, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, p)


def run_id_courant(root: str | Path) -> str | None:
    try:
        return json.loads(_chemin_pointeur(root).read_text(encoding="utf-8")).get("run_id")
    except (OSError, ValueError):
        return None


def ouvrir_session_harvest(
    root: str | Path,
    *,
    run_id: str | None = None,
    git_head: str | None = None,
    sources: Sequence[SourceAttendue] = SOURCES_HARVEST,
    now_ms: float | None = None,
    horloge=time.time,
) -> tuple[str, dict]:
    rid = run_id or SC.nouveau_run_id("harvest", horloge=horloge)
    cat = SC.CatalogueSession(root, rid)
    cat.demarrer(
        git_head=git_head,
        contexte={"profil": "HARVEST"},
        data_origin=SC.ORIGINE_REEL,
        horloge=horloge,
    )
    _ecrire_pointeur(root, rid, horloge=horloge)
    enregistrer_sources_declarees(
        root,
        rid,
        sources=sources,
        now_ms=now_ms if now_ms is not None else horloge() * 1000.0,
    )
    return rid, cat.lire()


def enregistrer_sources_declarees(
    root: str | Path,
    run_id: str,
    *,
    sources: Sequence[SourceAttendue] = SOURCES_HARVEST,
    now_ms: float,
    artefacts: Mapping[str, str] | None = None,
    pid_vivant=_pid_vivant_reel,
) -> dict:
    artefacts = dict(artefacts or {})
    hbs = lire_heartbeats_reels(root, sources)
    metriques = metriques_depuis_heartbeats(hbs)
    cat = SC.CatalogueSession(root, run_id)
    resume = {"declarees": 0, "vivantes": 0, "absentes": 0}
    for s in sources:
        hb = hbs.get(s.nom) or {}
        m = metriques.get(s.nom) or {}
        entree = SC.EntreeSource(
            source=s.nom,
            venue=s.venue,
            canal=s.canal,
            chemin=artefacts.get(s.nom, ""),
        )
        if s.non_implementee:
            entree.raison_absence = "source non implementee (aucun collecteur reel)"
            entree.sante = "GRISE"
            resume["absentes"] += 1
        elif not hb:
            entree.raison_absence = "aucun heartbeat : le collecteur n'a rien rapporte"
            entree.sante = "ROUGE"
            resume["absentes"] += 1
        else:
            p = preuve_source(
                s,
                hb,
                now_ms=now_ms,
                pid_vivant=pid_vivant,
                gaps_critiques=int(m.get("gaps_critiques", 0)),
                carnet_desync=bool(m.get("carnet_desync", False)),
                sequence_invalide=bool(m.get("sequence_invalide", False)),
                resync_en_attente=bool(m.get("resync_en_attente", False)),
                stale=bool(m.get("stale", False)),
                hors_ordre=int(m.get("hors_ordre", 0)),
                reconnexions=int(m.get("reconnects", 0)),
            )
            c = cause_source(
                s,
                p,
                ecrites=int(hb.get("n_ecrites_cumul") or 0),
                ecrites_precedentes=None,
                reconnexions=int(m.get("reconnects", 0)),
                heartbeat_present=True,
            )
            entree.sante = {
                "VERTE": "VERTE",
                "ORANGE": "ORANGE",
                "ROUGE": "ROUGE",
                "GRISE": "GRISE",
            }.get(c.get("sante", "GRISE"), "GRISE")
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
            break
    return resume


# Noms CANONIQUES du registre_pids. Le cmd lui-même reste vivant pendant la
# clôture et n'est donc volontairement pas considéré comme writer économique.
PROCESSUS_ECRIVAINS = (
    "ui",
    "poller",
    "stream",
    "moniteur",
    "resource-policy",
    "ia-shadow",
)


def _pid_composant(meta: Any) -> int | None:
    """Accepte le schéma canonique {pid,role,...} et l'ancien entier brut."""
    if isinstance(meta, int):
        return meta
    if isinstance(meta, Mapping):
        pid = meta.get("pid")
        return int(pid) if isinstance(pid, int) else None
    return None


def preuve_writers_arretes(
    root: str | Path,
    *,
    pid_vivant=_pid_vivant_reel,
) -> tuple[bool, list[str]]:
    """Preuve fail-closed que tous les writers enregistrés sont arrêtés.

    Le registre canonique range les composants sous ``composants``. Les vieux
    registres de test/runtime qui ne contiennent que ``collecteurs`` restent
    lisibles, mais une structure illisible/corrompue ne vaut jamais preuve.
    """
    try:
        from hl_observer.ops.registre_pids import lire_registre

        reg = lire_registre(root)
    except Exception:  # noqa: BLE001
        return False, ["REGISTRE_ILLISIBLE"]
    if not isinstance(reg, dict) or not reg:
        return False, ["REGISTRE_ABSENT"]
    if "collecteurs" not in reg:
        return False, ["REGISTRE_INCOMPLET"]
    collecteurs = reg.get("collecteurs")
    if not isinstance(collecteurs, dict):
        return False, ["REGISTRE_CORROMPU"]
    composants = reg.get("composants", {})
    if composants is None:
        composants = {}
    if not isinstance(composants, dict):
        return False, ["REGISTRE_COMPOSANTS_CORROMPU"]

    tous: dict[str, int] = {
        str(nom): int(pid)
        for nom, pid in collecteurs.items()
        if isinstance(pid, int)
    }
    for cle in PROCESSUS_ECRIVAINS:
        pid = _pid_composant(composants.get(cle))
        if isinstance(pid, int):
            tous[cle] = pid

    # Compatibilité fail-safe avec un éventuel registre historique ayant des
    # writers à la racine : on les contrôle au lieu de les ignorer.
    for cle in PROCESSUS_ECRIVAINS:
        if cle not in tous:
            pid = _pid_composant(reg.get(cle))
            if isinstance(pid, int):
                tous[cle] = pid

    vivants: list[str] = []
    for nom, pid in tous.items():
        try:
            if pid_vivant(int(pid)):
                vivants.append(str(nom))
        except Exception:  # noqa: BLE001
            vivants.append("%s?" % nom)
    return (not vivants), vivants


def cloturer_session_courante(
    root: str | Path,
    *,
    writers_arretes: bool | None = None,
    horloge=time.time,
    pid_vivant=_pid_vivant_reel,
) -> dict:
    rid = run_id_courant(root)
    if not rid:
        return {"statut": "AUCUNE_SESSION", "motifs": ["pas de session courante"]}
    arretes, vivants = preuve_writers_arretes(root, pid_vivant=pid_vivant)
    effectif = bool(arretes) if writers_arretes is None else (bool(writers_arretes) and bool(arretes))
    verdict = SC.CatalogueSession(root, rid).cloturer(writers_arretes=effectif, horloge=horloge)
    verdict.update(
        {
            "run_id": rid,
            "writers_vivants": vivants,
            "preuve_writers_arretes": arretes,
        }
    )
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
    p.add_argument(
        "--writers-arretes",
        action="store_true",
        help="cloture : attestation supplementaire ; la preuve PID independante prime",
    )
    args = p.parse_args(argv)
    root = Path(args.racine)
    if args.action == "ouvrir":
        rid, cat = ouvrir_session_harvest(root)
        print(
            "SESSION_OUVERTE run_id=%s statut=%s sources=%d"
            % (rid, cat.get("statut"), len(cat.get("sources") or {})),
            flush=True,
        )
        return 0
    if args.action == "enregistrer":
        rid = run_id_courant(root)
        if not rid:
            print("AUCUNE_SESSION_COURANTE", flush=True)
            return 2
        r = enregistrer_sources_declarees(root, rid, now_ms=time.time() * 1000.0)
        print(
            "SOURCES declarees=%d vivantes=%d absentes=%d"
            % (r["declarees"], r["vivantes"], r["absentes"]),
            flush=True,
        )
        return 0
    if args.action == "cloturer":
        atteste = True if args.writers_arretes else None
        v = cloturer_session_courante(root, writers_arretes=atteste)
        print(
            "CLOTURE statut=%s run_id=%s writers_vivants=%s motifs=%s"
            % (
                v.get("statut"),
                v.get("run_id"),
                ",".join(v.get("writers_vivants", []) or []) or "aucun",
                ",".join(v.get("motifs", []) or []),
            ),
            flush=True,
        )
        return 0 if v.get("statut") == SC.STATUT_COMPLETE else 2
    st = _statut_session_courante(root)
    print(
        "SESSION run_id=%s statut=%s sources=%s"
        % (st.get("run_id"), st.get("statut"), st.get("sources")),
        flush=True,
    )
    return 0


__all__ = [
    "POINTEUR",
    "PROCESSUS_ECRIVAINS",
    "run_id_courant",
    "ouvrir_session_harvest",
    "enregistrer_sources_declarees",
    "preuve_writers_arretes",
    "cloturer_session_courante",
    "main",
]
