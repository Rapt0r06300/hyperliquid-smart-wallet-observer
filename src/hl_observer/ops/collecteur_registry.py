"""Canonical collector registry and runtime profiles.

Extracted from ``superviseur_collecteurs`` so lifecycle/process supervision stays
small enough to audit. This module is pure configuration/profile selection; it
never launches a process and never performs network or trading actions.
"""
from __future__ import annotations

import os
from typing import Any

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
    {"nom": "allmids-collector", "script": "tools/collecter_allmids.py",
     "intervalle_s": 15, "args": ("--une-fois",), "limite_minutes": 5.0},
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
     "intervalle_s": 1800, "args": ("--une-fois",), "limite_minutes": 60.0},
    {"nom": "geler-prelim", "script": "tools/geler_prelim_copie.py",
     "intervalle_s": 3600, "args": ("--une-fois",), "limite_minutes": 120.0},
    # PERSISTANTS : écrivent la DATA en continu, pas un log par seconde -> la vie se mesure au HEARTBEAT
    # (fraîcheur du fichier), JAMAIS au log (sinon faux STALL + le watchdog dupliquerait un collecteur vivant).
    {"nom": "userfills-live", "script": "tools/collecter_userfills_vaults.py",
     "intervalle_s": 5, "args": (), "limite_minutes": 5.0,
     "heartbeat": "runtime/data/userfills_live.lock"},
    {"nom": "bbo-collector", "script": "tools/collecter_bbo.py",
     "intervalle_s": 5, "args": (), "limite_minutes": 5.0,
     "heartbeat": "runtime/data/bbo_heartbeat.json"},
    {"nom": "experimental-paper", "script": "tools/experimental_paper_tick.py",
     "intervalle_s": 2, "args": ("--une-fois",), "limite_minutes": 2.0,
     "heartbeat": "runtime/research_lab/heartbeats/experimental-paper.json"},
    {"nom": "copy-whitelist", "script": "tools/ecrire_copy_whitelist.py",
     "intervalle_s": 21600, "args": (), "limite_minutes": 570.0},
    {"nom": "rapport-quotidien", "script": "tools/rapport_quotidien.py",
     "intervalle_s": 21600, "args": (), "limite_minutes": 570.0},
    {"nom": "research-lab", "script": "tools/lancer_research_parallel.py",
     "intervalle_s": 60, "args": ("--max-ticks", "1"), "limite_minutes": 10.0,
     "heartbeat": "runtime/research_lab/heartbeat.json"},
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
# possédant un runner réel : les briques encore BLOCKED_EXTERNAL (node fills global, HF recorder standalone,
# TWAP standalone, Bybit) restent honnêtement hors profil tant qu'un vrai collecteur n'est pas branché.
# dYdX reste un connecteur legacy read-only disponible dans REGISTRE/research/all,
# mais il est dormant par défaut. Le runtime officiel HARVEST est Hyperliquid uniquement.
_NOMS_REGISTRE = frozenset(c["nom"] for c in REGISTRE)
_HARVEST_SOUHAITE = frozenset({
    "allmids-collector", "bbo-collector", "userfills-live",           # CORE (requis)
    "carnet-collector", "marks-collector", "liq-collector", "venues-collector",
    "overshoot-collector", "vault-collector", "scorer-vaults",
    "backfill-fills", "backfill-candles-vaults",
})
COLLECTEURS_HARVEST = frozenset(n for n in _HARVEST_SOUHAITE if n in _NOMS_REGISTRE)
# Sources OBLIGATOIRES : leur échec doit empêcher le passage en READY (le CLI sort non-zero).
COLLECTEURS_REQUIS = COLLECTEURS_CORE


def experimental_paper_demande() -> bool:
    """Le worker paper est opt-in, mais un flag actif implique un worker supervise."""
    return os.environ.get("HYPERSMART_EXPERIMENTAL_PAPER", "0").strip().lower() in {
        "1", "true", "yes", "oui", "on",
    }


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
    """Requis pour ce lancement; experimental-paper ne devient jamais CORE."""
    normalise = normaliser_profil(profil)
    requis = set(COLLECTEURS_REQUIS)
    if experimental_paper_demande() and normalise in {"harvest", "all"}:
        requis.add("experimental-paper")
    return frozenset(requis)
