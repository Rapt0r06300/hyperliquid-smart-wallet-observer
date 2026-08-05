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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

# Câblage des protections canoniques (IDEA-79) : une panne de collecte n'est PAS un marché calme.
# Cet import branche runtime/protections dans un chemin de production (le lanceur appelle ce module).
from hl_observer.runtime.protections import etat_ingestion

STATUT_READY = "READY"
STATUT_DEGRADED = "DEGRADED"
STATUT_DATA_NOT_READY = "DATA_NOT_READY"

# Deux niveaux explicites (item 2) + trois états HARVEST honnêtes (item 4).
NIVEAU_CORE = "READY_CORE"           # allMids + BBO + userFills réellement vivants
NIVEAU_HARVEST = "READY_HARVEST"     # alias legacy (= COMPLET)
HARVEST_COMPLET = "READY_HARVEST_COMPLET"        # TOUTES les sources réellement nécessaires vivantes
HARVEST_DEGRADE = "HARVEST_DEGRADE_DOCUMENTE"    # CORE vivant, mais des sources absentes/non implémentées
# (DATA_NOT_READY réutilisé pour : CORE ou source obligatoire malade)

# Taxonomie de cause (item 2) : ne jamais confondre ces cinq états.
CAUSE_OK = "OK"
CAUSE_MARCHE_CALME = "MARCHE_CALME"
CAUSE_PANNE_TECHNIQUE = "PANNE_TECHNIQUE"
CAUSE_QUOTA = "QUOTA_ATTEINT"
CAUSE_DONNEE_ABSENTE = "DONNEE_ABSENTE"
CAUSE_NON_IMPLEMENTEE = "SOURCE_NON_IMPLEMENTEE"

# Raisons de NON-santé qui sont des pannes de QUALITÉ de flux (item 2), pas une absence de donnée ni un
# marché calme : un process vivant + heartbeat frais qui échoue sur l'une d'elles = PANNE_TECHNIQUE.
_RAISONS_QUALITE_PANNE = (
    "gap critique", "carnet desynchronise", "sequence exchange invalide",
    "resync en attente", "evenements hors ordre", "carnet stale",
)

SEUIL_HEARTBEAT_MS = 60_000.0        # un heartbeat plus vieux que 60 s = figé


@dataclass(frozen=True)
class SourceAttendue:
    nom: str                          # clé heartbeat = nom du collecteur
    venue: str                        # HYPERLIQUID / BINANCE / DYDX / MULTI / LOCAL
    canal: str                        # allMids / bbo / l2Book / userFills / marks / ...
    obligatoire: bool = True
    exige_exchange_ts: bool = True    # backfills/scoring locaux n'ont pas toujours un ts exchange live
    chemin_sortie: str | None = None  # fichier/DB de sortie (contrôle de taille en complément)
    non_implementee: bool = False     # source déclarée indisponible (pas de collecteur réel) — item 2


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
    # Sources DÉCLARÉES mais pas encore implémentées (item 3) : JAMAIS omises, statut
    # SOURCE_NON_IMPLEMENTEE — leur présence empêche READY_HARVEST_COMPLET (item 4).
    SourceAttendue("node-fills-global", "HYPERLIQUID", "node-fills", False,
                   exige_exchange_ts=False, non_implementee=True),
    SourceAttendue("twap-slices", "HYPERLIQUID", "userTwapSliceFills", False,
                   exige_exchange_ts=False, non_implementee=True),
    SourceAttendue("hf-recorder", "HYPERLIQUID+BINANCE", "hf-recorder", False,
                   exige_exchange_ts=False, non_implementee=True),
    SourceAttendue("l4-order-intent", "HYPERLIQUID", "L4", False,
                   exige_exchange_ts=False, non_implementee=True),
    SourceAttendue("bybit", "BYBIT", "trades", False, exige_exchange_ts=False, non_implementee=True),
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
    ready_core: bool = False          # allMids + BBO + userFills réellement vivants (item 2)
    ready_harvest: bool = False       # = HARVEST_COMPLET seulement (item 4) : TOUTES vivantes
    causes: tuple[dict[str, Any], ...] = field(default_factory=tuple)  # taxonomie par source (item 2)
    niveau_harvest: str = STATUT_DATA_NOT_READY  # COMPLET / DEGRADE_DOCUMENTE / DATA_NOT_READY (item 4)

    def ready(self) -> bool:
        return self.statut == STATUT_READY


def cause_source(src: SourceAttendue, preuve: PreuveSource, *, ecrites: int,
                 ecrites_precedentes: int | None, reconnexions: int = 0,
                 heartbeat_present: bool = True, seuil_reconnexions_quota: int = 20) -> dict[str, Any]:
    """Distingue les CINQ états (item 2), sans jamais confondre panne et marché calme. S'appuie sur la
    protection canonique `etat_ingestion` (IDEA-79)."""
    if src.non_implementee:
        return {"source": src.nom, "cause": CAUSE_NON_IMPLEMENTEE, "sante": "GRISE",
                "motif": "aucun collecteur reel branche pour cette source"}
    if preuve.sain:
        return {"source": src.nom, "cause": CAUSE_OK, "sante": "VERTE"}
    if not heartbeat_present:
        return {"source": src.nom, "cause": CAUSE_DONNEE_ABSENTE, "sante": "ROUGE",
                "motif": "aucun heartbeat : le collecteur n'a rien rapporte"}
    if not preuve.process_actif or not preuve.heartbeat_frais:
        return {"source": src.nom, "cause": CAUSE_PANNE_TECHNIQUE, "sante": "ROUGE",
                "motif": preuve.raison}
    if int(reconnexions) >= int(seuil_reconnexions_quota):
        return {"source": src.nom, "cause": CAUSE_QUOTA, "sante": "ORANGE",
                "motif": "reconnexions repetees : quota/limite probable (%d)" % int(reconnexions)}
    if preuve.raison in _RAISONS_QUALITE_PANNE:
        # process vivant + heartbeat frais mais qualité de flux dégradée (gap/désync/séquence/resync/
        # hors-ordre/stale) : c'est une PANNE TECHNIQUE, jamais « donnée absente » ni « marché calme ».
        return {"source": src.nom, "cause": CAUSE_PANNE_TECHNIQUE, "sante": "ROUGE",
                "motif": preuve.raison}
    if ecrites <= 0 and (ecrites_precedentes is None or ecrites <= int(ecrites_precedentes)):
        # collecteur vivant mais aucune donnée : panne OU marché calme -> etat_ingestion tranche.
        ei = etat_ingestion(n_nouveaux_evenements=0)
        if ei["sante"] == "VERTE":
            return {"source": src.nom, "cause": CAUSE_MARCHE_CALME, "sante": "VERTE",
                    "motif": ei["motif"]}
        return {"source": src.nom, "cause": CAUSE_PANNE_TECHNIQUE, "sante": "ROUGE", "motif": ei["motif"]}
    return {"source": src.nom, "cause": CAUSE_DONNEE_ABSENTE, "sante": "ROUGE", "motif": preuve.raison}


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
                  taille_sortie: int | None = None,
                  gaps_critiques: int = 0, carnet_desync: bool = False,
                  sequence_invalide: bool = False, resync_en_attente: bool = False,
                  stale: bool = False, hors_ordre: int = 0,
                  reconnexions: int = 0, seuil_reconnexions: int = 20) -> PreuveSource:
    """Établit la preuve de vie d'UNE source à partir de son heartbeat normalisé. Aucun heartbeat =
    aucune preuve (fail-closed honnête). Métriques de qualité (item 2) : un heartbeat FRAIS ne masque
    JAMAIS un trou critique (`gaps_critiques`), un carnet désynchronisé (`carnet_desync`), une séquence
    exchange invalide (`sequence_invalide`, ex. U/u Binance), un resync en attente (`resync_en_attente`),
    des événements hors ordre (`hors_ordre`), un carnet stale (`stale`) ou des reconnexions excessives
    (`reconnexions` ≥ `seuil_reconnexions`)."""
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
        ("gap critique", int(gaps_critiques) <= 0),
        ("carnet desynchronise", not bool(carnet_desync)),
        ("sequence exchange invalide", not bool(sequence_invalide)),
        ("resync en attente", not bool(resync_en_attente)),
        ("evenements hors ordre", int(hors_ordre) <= 0),
        ("carnet stale", not bool(stale)),
        ("reconnexions excessives", int(reconnexions) < int(seuil_reconnexions)),
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
                      tailles: Mapping[str, int] | None = None,
                      metriques: Mapping[str, Mapping[str, Any]] | None = None) -> EtatRuntime:
    """Rend l'état global : READY / DEGRADED / DATA_NOT_READY (+ raison précise), plus les deux niveaux
    READY_CORE / READY_HARVEST et la taxonomie de cause par source (item 2). `metriques` (optionnel) :
    par source gaps_critiques / carnet_desync / reconnexions (feed_quality)."""
    base_prec = ecrites_precedentes or {}
    base_taille = tailles or {}
    base_met = metriques or {}

    def _met(nom, cle, defaut=0):
        m = base_met.get(nom) or {}
        return m.get(cle, defaut)

    def _reconnexions(nom):
        return int(_met(nom, "reconnects", _met(nom, "reconnexions", 0)))

    preuves = tuple(
        preuve_source(s, heartbeats.get(s.nom), now_ms=now_ms, pid_vivant=pid_vivant,
                      seuil_hb_ms=seuil_hb_ms, ecrites_precedentes=base_prec.get(s.nom),
                      taille_sortie=base_taille.get(s.nom),
                      gaps_critiques=int(_met(s.nom, "gaps_critiques", 0)),
                      carnet_desync=bool(_met(s.nom, "carnet_desync", False)),
                      sequence_invalide=bool(_met(s.nom, "sequence_invalide", False)),
                      resync_en_attente=bool(_met(s.nom, "resync_en_attente", False)),
                      stale=bool(_met(s.nom, "stale", False)),
                      hors_ordre=int(_met(s.nom, "hors_ordre", 0)),
                      reconnexions=_reconnexions(s.nom))
        for s in sources
    )
    causes = tuple(
        cause_source(s, p, ecrites=int((heartbeats.get(s.nom) or {}).get("n_ecrites_cumul") or 0),
                     ecrites_precedentes=base_prec.get(s.nom),
                     reconnexions=_reconnexions(s.nom),
                     heartbeat_present=bool(heartbeats.get(s.nom)))
        for s, p in zip(sources, preuves)
    )
    _tolere = {CAUSE_NON_IMPLEMENTEE, CAUSE_MARCHE_CALME}          # « clairement déclarée indispo » ou calme
    ready_core = all(p.sain for p in preuves if p.obligatoire)
    # item 4 — trois états HONNÊTES, jamais présenter une récolte incomplète comme complète :
    #  COMPLET = TOUTES les sources vivantes (aucune non_implementee, aucune muette) ;
    #  DEGRADE_DOCUMENTE = CORE vivant mais des sources absentes/non implémentées (chacune avec sa cause) ;
    #  DATA_NOT_READY = CORE ou source obligatoire malade.
    harvest_complet = ready_core and all(p.sain for p in preuves)
    if not ready_core:
        niveau_harvest = STATUT_DATA_NOT_READY
    elif harvest_complet:
        niveau_harvest = HARVEST_COMPLET
    else:
        niveau_harvest = HARVEST_DEGRADE
    ready_harvest = niveau_harvest == HARVEST_COMPLET

    obligatoires_malades = [p for p in preuves if p.obligatoire and not p.sain]
    if obligatoires_malades:
        p = obligatoires_malades[0]
        raison = "source obligatoire %s (%s @ %s): %s" % (p.nom, p.canal, p.venue, p.raison)
        if len(obligatoires_malades) > 1:
            raison += " (+%d autre(s))" % (len(obligatoires_malades) - 1)
        return EtatRuntime(STATUT_DATA_NOT_READY, raison, preuves, ready_core, ready_harvest, causes,
                           niveau_harvest)
    secondaires_malades = [p for p, c in zip(preuves, causes)
                           if (not p.obligatoire) and not p.sain and c["cause"] not in _tolere]
    if secondaires_malades:
        muettes = ", ".join("%s(%s)" % (p.nom, p.raison) for p in secondaires_malades)
        return EtatRuntime(STATUT_DEGRADED, "sources secondaires muettes: %s" % muettes,
                           preuves, ready_core, ready_harvest, causes, niveau_harvest)
    return EtatRuntime(STATUT_READY, "toutes les sources obligatoires sont saines",
                       preuves, ready_core, ready_harvest, causes, niveau_harvest)


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


def _niveau_ok(etat: EtatRuntime, niveau: str) -> bool:
    """Condition de passage de la barrière (item 1) : `core` exige READY_CORE ; `harvest` exige au moins
    CORE vivant (COMPLET ou DEGRADE_DOCUMENTE), jamais DATA_NOT_READY."""
    if niveau == "core":
        return bool(etat.ready_core)
    return etat.niveau_harvest != STATUT_DATA_NOT_READY


def evaluer_avec_attente(lecteur: Callable[[], EtatRuntime], *, niveau: str, timeout_s: float,
                         intervalle_s: float, horloge: Callable[[], float],
                         dormir: Callable[[float], None]) -> EtatRuntime:
    """Attente BORNÉE de la preuve de vie au niveau demandé (item 1 : warmup après démarrage des
    collecteurs). Réévalue `lecteur()` toutes les `intervalle_s` jusqu'à ce que le niveau soit satisfait
    OU que `timeout_s` soit écoulé. Rend le DERNIER état observé (avec sa raison précise). Injectable
    (horloge/dormir) → testable sans temps réel."""
    t0 = horloge()
    etat = lecteur()
    while not _niveau_ok(etat, niveau) and (horloge() - t0) < timeout_s:
        dormir(intervalle_s)
        etat = lecteur()
    return etat


def format_readiness(etat: EtatRuntime) -> str:
    lignes = ["=== PREUVE DE VIE — %s ===" % etat.statut,
              "  READY_CORE=%s   HARVEST=%s" % (etat.ready_core, etat.niveau_harvest),
              "  %s" % etat.raison]
    causes = {c["source"]: c["cause"] for c in etat.causes}
    for p in etat.preuves:
        marque = "OK  " if p.sain else ("MANQUE" if p.obligatoire else "muet")
        cause = causes.get(p.nom, "")
        lignes.append("  [%s] %-24s %-18s %-22s %s" % (
            marque, p.nom, p.canal, cause, "sain" if p.sain else p.raison))
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


def metriques_depuis_heartbeats(heartbeats: Mapping[str, Mapping[str, Any]]) -> dict[str, dict]:
    """Extrait, pour chaque source, les VRAIES métriques de qualité écrites par le collecteur (item 2) :
    sous-dict `metriques` du heartbeat, avec repli sur d'éventuelles clés à plat. C'est ce qui empêche un
    heartbeat frais de masquer un gap/désync/séquence invalide/resync/stale/hors-ordre/reconnexions."""
    from tools.heartbeat_collecteur import CLES_METRIQUES
    out: dict[str, dict] = {}
    for nom, hb in (heartbeats or {}).items():
        hb = hb or {}
        m = dict(hb.get("metriques") or {})
        for cle in CLES_METRIQUES:                       # repli : métrique éventuellement écrite à plat
            if cle not in m and cle in hb:
                m[cle] = hb[cle]
        if m:
            out[nom] = m
    return out


def evaluer_depuis_disque(root: str | Path, sources: Sequence[SourceAttendue] = SOURCES_HARVEST, *,
                          now_ms: float) -> EtatRuntime:
    """Chemin RÉEL (0 réseau, sur la machine de Flo) : lit les heartbeats canoniques ET leurs métriques de
    qualité, puis évalue. Item 2 : les gaps/désync/reconnexions RÉELS sont chargés et transmis à
    `evaluer_readiness` — un heartbeat frais ne peut plus masquer une panne de flux."""
    hbs = lire_heartbeats_reels(root, sources)
    metriques = metriques_depuis_heartbeats(hbs)
    return evaluer_readiness(sources, hbs, now_ms=now_ms, pid_vivant=_pid_vivant_reel,
                             metriques=metriques)


def main(argv: list[str] | None = None) -> int:
    """CLI BLOQUANT (item 1) : `python -m hl_observer.ops.preuve_de_vie [racine] [--niveau core|harvest]`.
    `--niveau core` (défaut) : exit 0 SEULEMENT si READY_CORE (allMids+BBO+userFills prouvés vivants),
    sinon 2 (DATA_NOT_READY) → le lanceur ne démarre pas le moteur. `--niveau harvest` : 0 si CORE vivant
    (COMPLET ou DEGRADE_DOCUMENTE), 2 sinon ; le niveau HARVEST exact est affiché et va au catalogue."""
    import argparse
    import time
    p = argparse.ArgumentParser(description="Preuve de vie bloquante des sources.")
    p.add_argument("racine", nargs="?", default=".")
    p.add_argument("--niveau", choices=("core", "harvest"), default="core")
    p.add_argument("--attendre", type=float, default=0.0,
                   help="fenetre de warmup BORNEE en secondes (0 = evaluation unique)")
    p.add_argument("--intervalle", type=float, default=2.0, help="periode de re-evaluation (s)")
    args = p.parse_args(argv)

    def _lecteur() -> EtatRuntime:
        return evaluer_depuis_disque(Path(args.racine), now_ms=time.time() * 1000.0)

    if args.attendre and args.attendre > 0:
        etat = evaluer_avec_attente(_lecteur, niveau=args.niveau, timeout_s=args.attendre,
                                    intervalle_s=max(0.1, args.intervalle),
                                    horloge=time.monotonic, dormir=time.sleep)
    else:
        etat = _lecteur()
    print(format_readiness(etat), flush=True)
    # exit 0 SEULEMENT si le niveau demandé est réellement atteint ; sinon 2 (DATA_NOT_READY) → le
    # lanceur NE démarre pas le moteur/UI/poller (item 1).
    return 0 if _niveau_ok(etat, args.niveau) else 2


__all__ = ["STATUT_READY", "STATUT_DEGRADED", "STATUT_DATA_NOT_READY", "SEUIL_HEARTBEAT_MS",
           "NIVEAU_CORE", "NIVEAU_HARVEST", "HARVEST_COMPLET", "HARVEST_DEGRADE", "CAUSE_OK", "CAUSE_MARCHE_CALME", "CAUSE_PANNE_TECHNIQUE",
           "CAUSE_QUOTA", "CAUSE_DONNEE_ABSENTE", "CAUSE_NON_IMPLEMENTEE",
           "SourceAttendue", "PreuveSource", "EtatRuntime", "SOURCES_HARVEST", "preuve_source",
           "cause_source", "evaluer_readiness", "attendre_readiness", "evaluer_avec_attente",
           "format_readiness", "evaluer_depuis_disque", "lire_heartbeats_reels",
           "metriques_depuis_heartbeats", "main"]


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
