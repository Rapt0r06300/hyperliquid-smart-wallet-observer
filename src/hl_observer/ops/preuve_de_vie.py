"""[LANCEUR item 7] Preuve de vie par source — après le démarrage, on n'affiche PAS « OK » tant qu'une
source n'a pas RÉELLEMENT prouvé qu'elle reçoit des données. Pour chaque source on exige :

  process actif · heartbeat frais · ACK de souscription · ≥1 événement valide · flux qui grossit ·
  horodatage EXCHANGE **et** horodatage de RÉCEPTION présents

Le runtime ne passe READY que si TOUTES les sources OBLIGATOIRES sont saines. Sinon :
  DEGRADED         — obligatoires saines, mais une source secondaire est muette ;
  DATA_NOT_READY   — au moins une source obligatoire n'a pas prouvé sa vie → RAISON PRÉCISE
                     (quelle source, quel canal, quel contrôle a échoué).

Tout est PUR + INJECTABLE (heartbeats, PID vivants, tailles, horloge, sleep) → testable 0 réseau. La
lecture réelle s'appuie sur le heartbeat canonique (tools/heartbeat_collecteur : ts_ms, pid,
n_ecrites_cumul, dernier_exchange_ts). Aucune donnée fabriquée : une source sans heartbeat = NON prouvée.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

STATUT_READY = "READY"
STATUT_DEGRADED = "DEGRADED"
STATUT_DATA_NOT_READY = "DATA_NOT_READY"

SEUIL_HEARTBEAT_MS = 60_000.0        # un heartbeat plus vieux que 60 s = figé


@dataclass(frozen=True)
class SourceAttendue:
    nom: str                          # clé heartbeat = nom du collecteur
    venue: str                        # HYPERLIQUID / BINANCE / DYDX / MULTI / LOCAL
    canal: str                        # allMids / bbo / l2Book / userFills / marks / ...
    obligatoire: bool = True
    exige_exchange_ts: bool = True    # backfills/scoring locaux n'ont pas toujours un ts exchange live
    chemin_sortie: str | None = None  # fichier/DB de sortie (contrôle de taille en complément)


# Profil HARVEST : socle CORE = OBLIGATOIRE ; récolte dense = secondaire (DEGRADED si muette, pas bloquant).
SOURCES_HARVEST: tuple[SourceAttendue, ...] = (
    SourceAttendue("allmids-collector", "HYPERLIQUID", "allMids", True),
    SourceAttendue("bbo-collector", "HYPERLIQUID+BINANCE", "bbo", True),
    SourceAttendue("userfills-live", "HYPERLIQUID", "userFills", True),
    SourceAttendue("carnet-collector", "HYPERLIQUID", "l2Book", False),
    SourceAttendue("marks-collector", "HYPERLIQUID", "marks", False),
    SourceAttendue("liq-collector", "HYPERLIQUID", "liquidations", False),
    SourceAttendue("venues-collector", "MULTI", "dispersion", False),
    SourceAttendue("vault-collector", "HYPERLIQUID", "vaults", False, exige_exchange_ts=False),
    SourceAttendue("scorer-vaults", "LOCAL", "scoring", False, exige_exchange_ts=False),
    SourceAttendue("backfill-fills", "HYPERLIQUID", "fills-backfill", False, exige_exchange_ts=False),
    SourceAttendue("backfill-candles-vaults", "HYPERLIQUID", "candles", False, exige_exchange_ts=False),
    # dYdX v4 (secondaire) : son absence NE bloque PAS la récolte HL (obligatoire=False).
    SourceAttendue("dydx-live", "DYDX", "trades+book+subaccounts", False, exige_exchange_ts=False),
)


@dataclass(frozen=True)
class PreuveSource:
    nom: str
    venue: str
    canal: str
    obligatoire: bool
    process_actif: bool
    heartbeat_frais: bool
    souscription_ack: bool
    evenement_valide: bool
    flux_grossit: bool
    horodatages_presents: bool
    sain: bool
    raison: str


@dataclass(frozen=True)
class EtatRuntime:
    statut: str
    raison: str
    preuves: tuple[PreuveSource, ...]

    def ready(self) -> bool:
        return self.statut == STATUT_READY


def _int(x: Any) -> int | None:
    try:
        if isinstance(x, bool):
            return None
        return int(x)
    except (TypeError, ValueError):
        return None


def preuve_source(src: SourceAttendue, hb: Mapping[str, Any] | None, *, now_ms: float,
                  pid_vivant: Callable[[int], bool], seuil_hb_ms: float = SEUIL_HEARTBEAT_MS,
                  ecrites_precedentes: int | None = None,
                  taille_sortie: int | None = None) -> PreuveSource:
    """Établit la preuve de vie d'UNE source à partir de son heartbeat normalisé. Aucun heartbeat =
    aucune preuve (fail-closed honnête)."""
    hb = hb or {}
    pid = _int(hb.get("pid"))
    ts_ms = _int(hb.get("ts_ms"))
    ex_ts = hb.get("dernier_exchange_ts")
    n_ecrites = _int(hb.get("n_ecrites_cumul")) or 0

    process_actif = pid is not None and bool(pid_vivant(pid))
    heartbeat_frais = ts_ms is not None and (now_ms - ts_ms) <= seuil_hb_ms
    evenement_valide = n_ecrites > 0
    # ACK de souscription : soit explicite (le collecteur l'a écrit), soit inféré du flux réel (des
    # écritures avec un horodatage exchange PROUVENT que la souscription a été acceptée).
    ack_explicite = bool(hb.get("souscription_ack"))
    souscription_ack = ack_explicite or (evenement_valide and ex_ts is not None)
    # flux qui grossit : le compteur d'écritures progresse (vs baseline) ; en complément, si un chemin de
    # sortie est fourni, sa taille doit être non nulle.
    if ecrites_precedentes is not None:
        flux_grossit = n_ecrites > ecrites_precedentes
    else:
        flux_grossit = evenement_valide
    if src.chemin_sortie is not None and taille_sortie is not None:
        flux_grossit = flux_grossit and taille_sortie > 0
    horodatages_presents = ts_ms is not None and (ex_ts is not None or not src.exige_exchange_ts)

    controles = [
        ("process inactif", process_actif),
        ("heartbeat fige", heartbeat_frais),
        ("souscription non ACK", souscription_ack),
        ("aucun evenement valide", evenement_valide),
        ("flux ne grossit pas", flux_grossit),
        ("horodatages manquants (exchange/reception)", horodatages_presents),
    ]
    echecs = [nom for nom, ok in controles if not ok]
    sain = not echecs
    raison = "sain" if sain else echecs[0]
    return PreuveSource(src.nom, src.venue, src.canal, src.obligatoire, process_actif, heartbeat_frais,
                        souscription_ack, evenement_valide, flux_grossit, horodatages_presents, sain, raison)


def evaluer_readiness(sources: Sequence[SourceAttendue], heartbeats: Mapping[str, Mapping[str, Any]], *,
                      now_ms: float, pid_vivant: Callable[[int], bool],
                      seuil_hb_ms: float = SEUIL_HEARTBEAT_MS,
                      ecrites_precedentes: Mapping[str, int] | None = None,
                      tailles: Mapping[str, int] | None = None) -> EtatRuntime:
    """Rend l'état global : READY / DEGRADED / DATA_NOT_READY (+ raison précise)."""
    base_prec = ecrites_precedentes or {}
    base_taille = tailles or {}
    preuves = tuple(
        preuve_source(s, heartbeats.get(s.nom), now_ms=now_ms, pid_vivant=pid_vivant,
                      seuil_hb_ms=seuil_hb_ms, ecrites_precedentes=base_prec.get(s.nom),
                      taille_sortie=base_taille.get(s.nom))
        for s in sources
    )
    obligatoires_malades = [p for p in preuves if p.obligatoire and not p.sain]
    if obligatoires_malades:
        p = obligatoires_malades[0]
        raison = "source obligatoire %s (%s @ %s): %s" % (p.nom, p.canal, p.venue, p.raison)
        if len(obligatoires_malades) > 1:
            raison += " (+%d autre(s))" % (len(obligatoires_malades) - 1)
        return EtatRuntime(STATUT_DATA_NOT_READY, raison, preuves)
    secondaires_malades = [p for p in preuves if (not p.obligatoire) and not p.sain]
    if secondaires_malades:
        muettes = ", ".join("%s(%s)" % (p.nom, p.raison) for p in secondaires_malades)
        return EtatRuntime(STATUT_DEGRADED, "sources secondaires muettes: %s" % muettes, preuves)
    return EtatRuntime(STATUT_READY, "toutes les sources obligatoires sont saines", preuves)


def attendre_readiness(lecteur_etat: Callable[[float], EtatRuntime], *, timeout_s: float,
                       intervalle_s: float, horloge: Callable[[], float],
                       dormir: Callable[[float], None]) -> EtatRuntime:
    """Attend la preuve de vie jusqu'à READY ou timeout. `lecteur_etat(now_ms)` relit l'état à chaque
    passe. Injectable (horloge/dormir) → testable sans temps réel. Rend le DERNIER état observé (avec sa
    raison précise si toujours DATA_NOT_READY)."""
    t0 = horloge()
    dernier = lecteur_etat(t0 * 1000.0)
    while not dernier.ready() and (horloge() - t0) < timeout_s:
        dormir(intervalle_s)
        dernier = lecteur_etat(horloge() * 1000.0)
    return dernier


def format_readiness(etat: EtatRuntime) -> str:
    lignes = ["=== PREUVE DE VIE — %s ===" % etat.statut, "  %s" % etat.raison]
    for p in etat.preuves:
        marque = "OK  " if p.sain else ("MANQUE" if p.obligatoire else "muet")
        lignes.append("  [%s] %-24s %-18s %s" % (marque, p.nom, p.canal, "sain" if p.sain else p.raison))
    return "\n".join(lignes)


# ── Lecture réelle (sur la machine de Flo) ──────────────────────────────────────────────────────────
def _pid_vivant_reel(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(int(pid))
    except Exception:  # noqa: BLE001 — psutil absent -> repli os.kill
        import os
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, ValueError):
            return False


def lire_heartbeats_reels(root: str | Path, sources: Sequence[SourceAttendue]) -> dict[str, dict]:
    """Lit le heartbeat canonique de chaque source (0 réseau). Source sans heartbeat → absente du dict."""
    try:
        from tools.heartbeat_collecteur import lire as _lire
    except Exception:  # noqa: BLE001 — chemin d'import indisponible
        return {}
    out: dict[str, dict] = {}
    for s in sources:
        try:
            hb = _lire(Path(root), s.nom)
        except Exception:  # noqa: BLE001
            hb = {}
        if hb:
            out[s.nom] = hb
    return out


def evaluer_depuis_disque(root: str | Path, sources: Sequence[SourceAttendue] = SOURCES_HARVEST, *,
                          now_ms: float) -> EtatRuntime:
    hbs = lire_heartbeats_reels(root, sources)
    return evaluer_readiness(sources, hbs, now_ms=now_ms, pid_vivant=_pid_vivant_reel)


def main(argv: list[str] | None = None) -> int:
    """CLI : `python -m hl_observer.ops.preuve_de_vie [racine]`. Exit 0=READY, 1=DEGRADED, 2=DATA_NOT_READY."""
    import time
    racine = Path(argv[0]) if argv else Path.cwd()
    etat = evaluer_depuis_disque(racine, now_ms=time.time() * 1000.0)
    print(format_readiness(etat), flush=True)
    return {STATUT_READY: 0, STATUT_DEGRADED: 1, STATUT_DATA_NOT_READY: 2}[etat.statut]


__all__ = ["STATUT_READY", "STATUT_DEGRADED", "STATUT_DATA_NOT_READY", "SEUIL_HEARTBEAT_MS",
           "SourceAttendue", "PreuveSource", "EtatRuntime", "SOURCES_HARVEST", "preuve_source",
           "evaluer_readiness", "attendre_readiness", "format_readiness", "evaluer_depuis_disque",
           "lire_heartbeats_reels", "main"]


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
