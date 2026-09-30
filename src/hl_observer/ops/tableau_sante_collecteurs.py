"""[LANCEUR item 12] Tableau de santé LIVE des collecteurs — la fenêtre principale montre, en une ZONE
DYNAMIQUE (une ligne par source, ré-affichée à chaque passe — PAS des milliers de lignes qui défilent),
plus un JOURNAL horodaté (une ligne par passe) pour l'historique.

Colonnes : source · venue · canal · PID · état · dernier heartbeat · events/s · octets écrits ·
reconnexions · gaps · doublons · stale · hors-ordre · période couverte · chemin de sortie.

L'état par source réutilise la preuve de vie (item 7). events/s se calcule entre deux passes (delta
d'écritures / delta de temps) ; sans passe précédente → EN CALIBRATION (jamais un faux débit). Les
métriques gaps/doublons/reconnexions/stale/hors-ordre viennent de feed_quality (clés canoniques :
gaps, stale_events, reconnects, out_of_order) ; absentes → 0 honnête, jamais fabriquées. 0 réseau.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from hl_observer.ops.preuve_de_vie import SOURCES_HARVEST, SourceAttendue, preuve_source


@dataclass(frozen=True)
class LigneSante:
    source: str
    venue: str
    canal: str
    pid: int | None
    etat: str                       # SAIN / MUET (secondaire) / MANQUE (obligatoire)
    heartbeat_age_s: float | None
    events_par_s: float | None      # None = EN CALIBRATION (pas encore deux passes)
    octets_ecrits: int
    reconnexions: int
    gaps: int
    doublons: int
    stale: int
    hors_ordre: int
    periode_couverte: str
    chemin_sortie: str


@dataclass(frozen=True)
class Tableau:
    lignes: tuple[LigneSante, ...] = field(default_factory=tuple)
    snapshot: dict[str, dict[str, float]] = field(default_factory=dict)  # {nom:{n,ts}} pour la passe suivante
    horodatage: str = ""

    def resume(self) -> dict[str, int]:
        sains = sum(1 for l in self.lignes if l.etat == "SAIN")
        return {"total": len(self.lignes), "sains": sains,
                "gaps": sum(l.gaps for l in self.lignes),
                "doublons": sum(l.doublons for l in self.lignes)}


def _i(x: Any, defaut: int = 0) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return defaut


def _etat(preuve, obligatoire: bool) -> str:
    if preuve.sain:
        return "SAIN"
    return "MANQUE" if obligatoire else "MUET"


def _events_par_s(nom: str, n_now: int, ts_now: float,
                  precedent: Mapping[str, Mapping[str, float]] | None) -> float | None:
    if not precedent or nom not in precedent:
        return None
    prev = precedent[nom]
    dt = (ts_now - float(prev.get("ts", 0.0))) / 1000.0
    if dt <= 0:
        return None
    delta = n_now - int(prev.get("n", 0))
    return max(0.0, delta / dt)


def _periode(hb: Mapping[str, Any], metriques: Mapping[str, Any]) -> str:
    deb = metriques.get("periode_debut_ms")
    fin = metriques.get("periode_fin_ms") or hb.get("dernier_exchange_ts")
    if deb and fin and fin >= deb:
        return "%.1f min" % ((float(fin) - float(deb)) / 60000.0)
    if fin:
        return "jusqu'a ts=%s" % _i(fin)
    return "n/a"


def construire_ligne(src: SourceAttendue, hb: Mapping[str, Any] | None, pid: int | None,
                     metriques: Mapping[str, Any], *, now_ms: float,
                     pid_vivant: Callable[[int], bool],
                     precedent: Mapping[str, Mapping[str, float]] | None) -> LigneSante:
    hb = dict(hb or {})
    m = dict(metriques or {})
    preuve = preuve_source(src, hb, now_ms=now_ms, pid_vivant=pid_vivant)
    ts = hb.get("ts_ms")
    age_s = None if ts is None else max(0.0, (now_ms - float(ts)) / 1000.0)
    n_ecrites = _i(hb.get("n_ecrites_cumul"))
    pid_effectif = pid if pid is not None else (_i(hb.get("pid")) or None)
    return LigneSante(
        source=src.nom, venue=src.venue, canal=src.canal, pid=pid_effectif, etat=_etat(preuve, src.obligatoire),
        heartbeat_age_s=age_s, events_par_s=_events_par_s(src.nom, n_ecrites, float(now_ms), precedent),
        octets_ecrits=_i(m.get("octets")), reconnexions=_i(m.get("reconnects")), gaps=_i(m.get("gaps")),
        doublons=_i(m.get("doublons")), stale=_i(m.get("stale_events")),
        hors_ordre=_i(m.get("out_of_order")), periode_couverte=_periode(hb, m),
        chemin_sortie=str(m.get("chemin") or src.chemin_sortie or ""))


def construire_tableau(sources: Sequence[SourceAttendue], heartbeats: Mapping[str, Mapping[str, Any]],
                       pids: Mapping[str, int], metriques: Mapping[str, Mapping[str, Any]], *,
                       now_ms: float, pid_vivant: Callable[[int], bool],
                       precedent: Mapping[str, Mapping[str, float]] | None = None,
                       horodatage: str = "") -> Tableau:
    lignes: list[LigneSante] = []
    snapshot: dict[str, dict[str, float]] = {}
    for s in sources:
        hb = heartbeats.get(s.nom) or {}
        lignes.append(construire_ligne(s, hb, pids.get(s.nom), metriques.get(s.nom) or {},
                                       now_ms=now_ms, pid_vivant=pid_vivant, precedent=precedent))
        snapshot[s.nom] = {"n": float(_i(hb.get("n_ecrites_cumul"))), "ts": float(now_ms)}
    return Tableau(tuple(lignes), snapshot, horodatage)


def _fmt(x: Any, largeur: int) -> str:
    return str(x).ljust(largeur)[:largeur]


def format_tableau(tableau: Tableau) -> str:
    """Zone dynamique compacte : en-tête + une ligne par source (ré-affichée en place à chaque passe)."""
    r = tableau.resume()
    entete = ("=== TABLEAU DE SANTE COLLECTEURS (%s) — %d/%d sains, gaps=%d, doublons=%d ==="
              % (tableau.horodatage or "?", r["sains"], r["total"], r["gaps"], r["doublons"]))
    cols = "%s %s %s %s %s %s %s %s %s %s %s" % (
        _fmt("SOURCE", 20), _fmt("VENUE", 11), _fmt("CANAL", 11), _fmt("PID", 7), _fmt("ETAT", 6),
        _fmt("HB(s)", 6), _fmt("EV/S", 7), _fmt("OCTETS", 9), _fmt("RECO", 4), _fmt("GAP", 4), _fmt("DUP", 4))
    lignes = [entete, cols]
    for l in tableau.lignes:
        hb = "?" if l.heartbeat_age_s is None else ("%.0f" % l.heartbeat_age_s)
        ev = "CAL" if l.events_par_s is None else ("%.1f" % l.events_par_s)
        lignes.append("%s %s %s %s %s %s %s %s %s %s %s" % (
            _fmt(l.source, 20), _fmt(l.venue, 11), _fmt(l.canal, 11), _fmt(l.pid if l.pid else "-", 7),
            _fmt(l.etat, 6), _fmt(hb, 6), _fmt(ev, 7), _fmt(l.octets_ecrits, 9),
            _fmt(l.reconnexions, 4), _fmt(l.gaps, 4), _fmt(l.doublons, 4)))
    return "\n".join(lignes)


def ligne_journal(tableau: Tableau) -> str:
    """Une ligne HORODATÉE pour le journal append-only (historique des passes)."""
    r = tableau.resume()
    fragments = []
    for l in tableau.lignes:
        ev = "cal" if l.events_par_s is None else ("%.0f" % l.events_par_s)
        fragments.append("%s=%s/ev%s/g%d/d%d" % (l.canal, l.etat[:4], ev, l.gaps, l.doublons))
    return "[%s] sains=%d/%d | %s" % (tableau.horodatage or "?", r["sains"], r["total"], " ".join(fragments))


__all__ = ["LigneSante", "Tableau", "SOURCES_HARVEST", "construire_ligne", "construire_tableau",
           "format_tableau", "ligne_journal"]
