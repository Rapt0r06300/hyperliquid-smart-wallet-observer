"""Canonical collector registry and runtime profiles.

Extracted from ``superviseur_collecteurs`` so lifecycle/process supervision stays
small enough to audit. This module is pure configuration/profile selection; it
never launches a process and never performs network or trading actions.
"""
from __future__ import annotations

import os
from typing import Any

EXECUTION_CAPABILITY_NONE = "NONE"
SOURCE_STATUS_ACTIVE_OBSERVATION = "ACTIVE_OBSERVATION"
SOURCE_STATUS_SHADOW_ANALYSIS = "SHADOW_ANALYSIS"
SOURCE_STATUS_ISOLATED_EXPERIMENT = "ISOLATED_EXPERIMENT"
SOURCE_STATUS_UNCLASSIFIED = "UNCLASSIFIED"

#: 🔴 SOURCE UNIQUE — doit refléter les lignes `start ... boucle_collecteur.cmd` de
#: LANCER_HYPERSMART.cmd. Le test `test_le_REGISTRE_correspond_au_LANCEUR` compare les deux :
#: si quelqu'un ajoute un collecteur au lanceur sans l'ajouter ici, le test rougit — sinon le
#: nouveau collecteur mourrait SANS supervision, exactement la panne qu'on vient de payer.
#: limite_minutes : au-delà de ce silence du log, le collecteur est déclaré MORT.
#: (le log est écrit à CHAQUE passe ; silence sain max ≈ cadence + durée d'une passe)
#: 27/07 — REGISTRE ÉTENDU aux 19 collecteurs RÉELLEMENT démarrés par l'AUTOPILOT (avant : 7, dont
#: carry-feeder qui était COUPÉ dans le lanceur -> canari 17 vs 7 rouge). Désormais SOURCE UNIQUE
#: utilisée par : AUTOPILOT (`demarrer_tous`), `status` (status_detaille), watchdog (verifier_et_relancer),
#: arrêt ciblé (arreter_cible) et les tests. Une seule liste, plus de dérive possible.
#: `une_fois` = True si le script fait UNE passe puis rend la main (boucle_collecteur relance à l'intervalle).
REGISTRE: tuple[dict[str, Any], ...] = (
    {"nom": "marks-collector", "script": "tools/ecrire_marks_tous_coins.py",
     "intervalle_s": 60, "args": ("--une-fois",), "limite_minutes": 5.0},
    # PERSISTANT (2026-11-10) : boucle interne 4 s au lieu d'un respawn Python /15 s.
    # Capture ~7× plus de prix ET réduit le churn mémoire (1 process long-vécu). Vie =
    # HEARTBEAT (écrit à chaque passe via HB.battre), plus le log. intervalle_s = délai de
    # relance après CRASH seulement.
    {"nom": "allmids-collector", "script": "tools/collecter_allmids.py",
     "intervalle_s": 10, "args": (), "limite_minutes": 5.0,
     "heartbeat": "runtime/research_lab/heartbeats/allmids-collector.json"},
    {"nom": "liq-collector", "script": "tools/collecter_liquidations.py",
     "intervalle_s": 300, "args": ("--une-fois",), "limite_minutes": 20.0},
    {"nom": "venues-collector", "script": "tools/collecter_dispersion_venues.py",
     "intervalle_s": 60, "args": ("--une-fois",), "limite_minutes": 20.0},
    {"nom": "carnet-collector", "script": "tools/collecter_carnet.py",
     "intervalle_s": 60, "args": ("--une-fois",), "limite_minutes": 20.0},
    {"nom": "overshoot-collector", "script": "tools/collecter_overshoots.py",
     "intervalle_s": 10, "args": ("--une-fois",), "limite_minutes": 5.0},
    {"nom": "vault-collector", "script": "tools/collecter_vaults.py",
     "intervalle_s": 300, "args": ("--une-fois",), "limite_minutes": 20.0},
    {"nom": "scorer-vaults", "script": "tools/scorer_vaults.py",
     "intervalle_s": 600, "args": ("--une-fois",), "limite_minutes": 25.0},
    {"nom": "backfill-fills", "script": "tools/backfill_vault_fills.py",
     "intervalle_s": 14400, "args": ("--une-fois",), "limite_minutes": 480.0},
    {"nom": "backfill-candles-vaults", "script": "tools/backfill_candles_vaults.py",
     "intervalle_s": 14400, "args": ("--une-fois",), "limite_minutes": 480.0},
    {"nom": "pipeline-reel", "script": "tools/pipeline_copie_reel.py",
     "intervalle_s": 1800, "args": ("--une-fois",), "limite_minutes": 60.0,
     "execution_capability": EXECUTION_CAPABILITY_NONE,
     "source_status": SOURCE_STATUS_SHADOW_ANALYSIS,
     "paper_read_only": True, "real_execution": False},
    {"nom": "geler-prelim", "script": "tools/geler_prelim_copie.py",
     "intervalle_s": 3600, "args": ("--une-fois",), "limite_minutes": 120.0},
    # PERSISTANTS : écrivent la DATA en continu, pas un log par seconde -> la vie se mesure au HEARTBEAT
    # (fraîcheur du fichier), JAMAIS au log (sinon faux STALL + le watchdog dupliquerait un collecteur vivant).
    {"nom": "userfills-live", "script": "tools/collecter_userfills_vaults.py",
     "intervalle_s": 5, "args": (), "limite_minutes": 5.0,
     "heartbeat": "runtime/data/userfills_live.lock",
     "copy_vault_checkpoint_role": "UNBOUND_SOURCE",
     "execution_capability": EXECUTION_CAPABILITY_NONE,
     "source_status": SOURCE_STATUS_ACTIVE_OBSERVATION,
     "paper_read_only": True, "real_execution": False},
    {"nom": "bbo-collector", "script": "tools/collecter_bbo.py",
     "intervalle_s": 5, "args": (), "limite_minutes": 5.0,
     "heartbeat": "runtime/data/bbo_heartbeat.json"},
    {"nom": "native-venues", "script": "tools/collecter_native_venues.py",
     "intervalle_s": 5, "args": (), "limite_minutes": 5.0,
     "heartbeat": "runtime/data/native_venues_heartbeat.json"},
    {"nom": "experimental-paper", "script": "tools/experimental_paper_tick.py",
     "intervalle_s": 2, "args": ("--une-fois",), "limite_minutes": 2.0,
     "heartbeat": "runtime/research_lab/heartbeats/experimental-paper.json",
     "execution_capability": EXECUTION_CAPABILITY_NONE,
     "source_status": SOURCE_STATUS_ISOLATED_EXPERIMENT,
     "paper_read_only": True, "real_execution": False,
     "isolated_experiment": True},
    {"nom": "copy-whitelist", "script": "tools/ecrire_copy_whitelist.py",
     "intervalle_s": 21600, "args": (), "limite_minutes": 570.0},
    {"nom": "rapport-quotidien", "script": "tools/rapport_quotidien.py",
     "intervalle_s": 21600, "args": (), "limite_minutes": 570.0},
    {"nom": "research-lab", "script": "tools/lancer_research_parallel.py",
     "intervalle_s": 60, "args": ("--max-ticks", "1"), "limite_minutes": 10.0,
     "heartbeat": "runtime/research_lab/heartbeat.json"},
    # Carnets L2 + BBO CONTINUS des coins tradés par les leaders (dex HIP-3 compris). Mesuré le
    # 2026-11-11 : 89 % des signaux des leaders n'avaient aucun carnet dans les 30 s précédentes, donc
    # aucun coût d'exécution mesurable. Sessions bornées relancées par le superviseur ; la liste
    # locale est régénérée au lancement (tools/generer_coins_lanes.py), sinon la liste commitée.
    {"nom": "l2-leaders", "script": "tools/collecter_l2_lane.py",
     "intervalle_s": 5,
     "args": ("--coins-file", "runtime/data/copy_vault_coins_local.json", "--duree-s", "1500",
              "--heartbeat", "l2-leaders"),
     "limite_minutes": 5.0,
     "heartbeat": "runtime/research_lab/heartbeats/l2-leaders.json",
     "execution_capability": EXECUTION_CAPABILITY_NONE,
     "source_status": SOURCE_STATUS_ACTIVE_OBSERVATION,
     "paper_read_only": True, "real_execution": False},
    # ORDRES EN ATTENTE des leaders (leur INTENTION, avant le fill) + positions/TWAP/portefeuille.
    # Mesure du 2026-11-12 : l'etude maker (copy_vault_order_intent) voyait « 0 fill pendant le suivi
    # des carnets d'ordres ». Ce n'etait PAS un manque d'ordres : cette lane n'existait qu'en CLOUD et
    # suivait une AUTRE liste de leaders que le collecteur de fills LOCAL. D'ou `--leaders-source
    # fills` : on suit EXACTEMENT les comptes dont on capte les fills, sinon le couple ordre -> fill
    # n'existe jamais et l'etude reste vide quelle que soit la duree de collecte.
    # Pas de cle `heartbeat` (la lane n'en ecrit pas) : la vie est jugee sur la FRAICHEUR DU LOG,
    # garantie par la ligne de vie par minute de la lane — sans elle, un marche calme ferait relancer
    # un processus VIVANT (double collecte).
    {"nom": "contexte-leaders", "script": "tools/collecter_contexte_lane.py",
     "intervalle_s": 5,
     "args": ("--leaders-source", "fills", "--shard-count", "1", "--shard-index", "0",
              "--max-users", "10", "--duree-s", "900"),
     "limite_minutes": 5.0,
     "execution_capability": EXECUTION_CAPABILITY_NONE,
     "source_status": SOURCE_STATUS_ACTIVE_OBSERVATION,
     "paper_read_only": True, "real_execution": False},
    # K1 — FILLS DES LEADERS PAR REST, pour depasser le plafond WebSocket (~10 userFills/IP).
    # Mesure du 2026-11-12 : seulement 8 leaders distincts dans le ruban, dont UN SEUL a 63 % des
    # fills (439/693) : le labo mesurait un trader, pas une strategie. Cet outil existe precisement
    # pour ca (`info/userFillsByTime`, non soumis au cap WS) et il n'etait PAS dans le registre.
    # Il reserve desormais son poids dans le budget de debit PARTAGE (sinon il consommait le quota de
    # l'IP a l'insu des autres et recreait les rafales de 429).
    # Pas de cle `heartbeat` : il imprime une ligne d'etat A CHAQUE PASSE et sauvegarde son etat,
    # donc la vie se juge sur la fraicheur du log (comme 13 autres entrees).
    {"nom": "userfills-poll", "script": "tools/collecter_userfills_poll.py",
     "intervalle_s": 5,
     # CADENCE : 55 req/min etait prevu pour une IP DEDIEE (lane cloud). En local, une seule IP est
     # partagee par ~12 collecteurs et `userFillsByTime` pese 20 : 55 req/min = 1100 poids/min, soit
     # la quasi-totalite du budget de 1200 — il affamerait les autres (dont les fills causaux WS).
     # On lui alloue ~20 % du budget : 12 req/min = 240 poids/min. Avec la cadence ADAPTATIVE du
     # collecteur (un leader qui vient d'emettre est repolle plus vite), cela suffit a couvrir les
     # leaders actifs tout en passant de 8 a ~120 leaders suivis.
     "args": ("--leaders-file", "config/copy_vault_leaders.json",
              "--intervalle", "5", "--max-requests-per-min", "12",
              "--shard-count", "1", "--shard-index", "0"),
     "limite_minutes": 5.0,
     "execution_capability": EXECUTION_CAPABILITY_NONE,
     "source_status": SOURCE_STATUS_ACTIVE_OBSERVATION,
     "paper_read_only": True, "real_execution": False},
    {"nom": "lab-microstructure", "script": "tools/collecter_lab_microstructure.py",
     "intervalle_s": 30, "args": (), "limite_minutes": 5.0,
     "heartbeat": "runtime/research_lab/micro_heartbeat.json"},
    # dYdX v4 LEGACY (read-only) : trades/orderbooks/subaccounts persistés via PiloteFluxDydx.
    # Sessions bornées (290 s) relancées par le superviseur ; heartbeat canonique.
    {"nom": "dydx-live", "script": "tools/collecter_dydx_live.py",
     "intervalle_s": 300, "args": ("--duree-s", "290"), "limite_minutes": 15.0,
     "heartbeat": "runtime/research_lab/heartbeats/dydx-live.json"},
)

# Collecteurs strictement reserves aux campagnes de preuve. Ils ne font pas
# partie du registre du lanceur et ne peuvent donc entrer dans aucun profil
# CORE/HARVEST/RESEARCH/ALL par accident. Le demarrage borne les attache a une
# lease economique existante ou en cree une lors d'une campagne explicite.
COLLECTEURS_CAMPAGNE: tuple[dict[str, Any], ...] = (
    {
        "nom": "copy-vault-checkpoints",
        "script": "tools/collecter_copy_vault_checkpoints.py",
        "intervalle_s": 1,
        "args": (),
        "limite_minutes": 5.0,
        "heartbeat": "runtime/research_lab/heartbeats/copy-vault-checkpoints.json",
        "copy_vault_checkpoint_role": "BOUND_WRITER",
    },
)

# Le runtime principal ne doit pas devenir un laboratoire permanent. Ces profils
# gardent tous les collecteurs disponibles. Le profil essentiel demarre les
# prix/microstructure et userFills : sans ce dernier, copy-vault ne peut pas
# observer les transitions leader en temps reel.
PROFILS_VALIDES = ("core", "maintenance", "research", "harvest", "all")
COLLECTEURS_CORE = frozenset({
    "allmids-collector",
    "bbo-collector",
    "userfills-live",
})
COLLECTEURS_MAINTENANCE = frozenset({
    "copy-whitelist",
    "rapport-quotidien",
})
COLLECTEURS_RESEARCH = frozenset(
    c["nom"]
    for c in REGISTRE
    if c["nom"] not in COLLECTEURS_CORE | COLLECTEURS_MAINTENANCE
)

# Profil officiel HARVEST : récolte DENSE et durable pour LANCER_HYPERSMART.cmd, distinct de research.
# Il démarre le socle prix/microstructure/userFills (CORE, REQUIS) PLUS les collecteurs de récolte qui
# tournent réellement aujourd'hui (carnet L2 batch + Binance depth REST, marks, liquidations, dispersion
# venues, découverte + scoring de vaults, backfills fills/candles). On n'inclut ici QUE des collecteurs
# possédant un runner réel. Bybit/OKX/Gate/Bitget sont maintenant branchés via le coordinateur
# natif read-only et son runner persistant; node fills global/HF recorder/TWAP standalone restent hors
# profil tant qu'un vrai collecteur n'est pas branché. dYdX reste legacy read-only et dormant par défaut.
_NOMS_REGISTRE = frozenset(c["nom"] for c in REGISTRE)
_HARVEST_SOUHAITE = frozenset({
    "allmids-collector", "bbo-collector", "userfills-live",           # CORE (requis)
    "native-venues",                                                   # Bybit/OKX/Gate/Bitget natifs
    "carnet-collector", "marks-collector", "liq-collector", "venues-collector",
    "overshoot-collector", "vault-collector", "scorer-vaults",
    "backfill-fills", "backfill-candles-vaults",
    "l2-leaders",                                                      # carnets des coins de leaders
    "contexte-leaders",                                                # ordres en attente = intention
    "userfills-poll",                                                  # fills REST : depasse le cap WS
})
COLLECTEURS_HARVEST = frozenset(n for n in _HARVEST_SOUHAITE if n in _NOMS_REGISTRE)
# Sources OBLIGATOIRES : leur échec doit empêcher le passage en READY (le CLI sort non-zero).
COLLECTEURS_REQUIS = COLLECTEURS_CORE


def experimental_paper_demande() -> bool:
    """Le worker paper est opt-in, mais un flag actif implique un worker supervise."""
    return os.environ.get("HYPERSMART_EXPERIMENTAL_PAPER", "0").strip().lower() in {
        "1", "true", "yes", "oui", "on",
    }


def contrat_collecteur(nom: str) -> dict[str, Any] | None:
    """Return the explicit safety contract for one registered collector.

    A name such as ``pipeline-reel`` never grants execution authority.  The
    contract is metadata on the registry entry, and missing metadata remains
    unclassified instead of being inferred from a name.
    """
    entry = next((c for c in REGISTRE + COLLECTEURS_CAMPAGNE if c["nom"] == nom), None)
    if entry is None:
        return None
    return {
        "nom": nom,
        "execution_capability": entry.get("execution_capability", EXECUTION_CAPABILITY_NONE),
        "source_status": entry.get("source_status", SOURCE_STATUS_UNCLASSIFIED),
        "paper_read_only": entry.get("paper_read_only") is True,
        "real_execution": entry.get("real_execution") is False,
        "isolated_experiment": entry.get("isolated_experiment") is True,
    }


def contrat_collecteur_valide(nom: str) -> bool:
    """Validate a collector contract without deriving authority from its name."""
    contract = contrat_collecteur(nom)
    if contract is None:
        return False
    if contract["execution_capability"] != EXECUTION_CAPABILITY_NONE:
        return False
    if contract["real_execution"] is not True:
        return False
    if contract["source_status"] == SOURCE_STATUS_UNCLASSIFIED:
        return False
    return contract["paper_read_only"] is True


def experimental_paper_isole() -> bool:
    """Return whether the opt-in experimental collector is explicitly isolated."""
    contract = contrat_collecteur("experimental-paper")
    return bool(
        experimental_paper_demande()
        and contract
        and contract["isolated_experiment"]
        and contract["paper_read_only"]
        and contract["real_execution"]
        and contract["execution_capability"] == EXECUTION_CAPABILITY_NONE
    )


def normaliser_profil(profil: str | None, *, defaut: str = "core") -> str:
    aliases = {
        "analyse": "research",
        "analysis": "research",
        "recherche": "research",
        "tous": "all",
    }
    valeur = aliases.get(str(profil or defaut).strip().lower(), str(profil or defaut).strip().lower())
    if valeur not in PROFILS_VALIDES:
        raise ValueError("profil collecteurs invalide: %s" % valeur)
    return valeur


def profil_collecteur(nom: str) -> str:
    if nom in COLLECTEURS_CORE:
        return "core"
    if nom in COLLECTEURS_MAINTENANCE:
        return "maintenance"
    return "research"


def collecteurs_pour_profil(profil: str | None = "core") -> tuple[dict[str, Any], ...]:
    profil_normalise = normaliser_profil(profil)
    if profil_normalise == "all":
        return REGISTRE
    if profil_normalise == "harvest":
        # union explicite (les noms CORE appartiennent à CORE via profil_collecteur ; on les ré-inclut ici).
        noms = set(COLLECTEURS_HARVEST)
        if experimental_paper_demande():
            noms.add("experimental-paper")
        return tuple(c for c in REGISTRE if c["nom"] in noms)
    return tuple(c for c in REGISTRE if profil_collecteur(c["nom"]) == profil_normalise)


def collecteurs_requis_pour_run(profil: str | None) -> frozenset[str]:
    """Return collectors whose absence must fail the requested runtime profile.

    CORE remains the minimal runtime contract. HARVEST additionally requires the
    native multi-venue collector because Bybit/OKX are first-class market sources
    for Cross-Venue and Lead-Lag; silently running harvest without them would
    produce an incomplete dataset while appearing healthy.
    """
    normalise = normaliser_profil(profil)
    requis = set(COLLECTEURS_REQUIS)
    if normalise in {"harvest", "all"}:
        requis.add("native-venues")
    if experimental_paper_demande() and normalise in {"harvest", "all"}:
        requis.add("experimental-paper")
    return frozenset(requis)
