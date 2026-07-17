"""LES PIERRES TOMBALES DE `runtime/` — T3e (2026-07-13). Meme doctrine que T3b/T3c.

POURQUOI CE FICHIER EXISTE
--------------------------
Les taches **P4 (hot path)** et **P5 (queues bornees / backpressure)** etaient marquees
**« completed »**. Verification par execution (grep des imports sur TOUT le depot) :

    hot_path.py            -> importe par : tests/test_hot_path_no_heavy_imports.py.  RIEN d'autre.
    event_driven_decider.py-> importe par : tests/test_event_driven_decider.py.        RIEN d'autre.
    bounded_event_queue.py -> importe par : event_driven_decider (mort) + son test.    RIEN d'autre.

**Zero import de production.** Le coeur de P4 et de P5 n'est appele par PERSONNE. Les tests sont
verts ; la production ne les voit pas. *Un test ne cable rien.*

La regle de Flo est sans ambiguite : **BRANCHER (avec un test qui prouve l'appel) ou ENTERRER.**

LA DECISION, ET SES RAISONS (pas des impressions -- des mesures deja faites)
---------------------------------------------------------------------------
**P4 (hot_path, event_driven_decider) -> ENTERRE. Motif : ZONE_MORTE_MESUREE.**
Sa promesse etait « decider a l'arrivee du fill, pas en fin de cycle de 30-50 s ». Mais la courbe
edge/horizon a ete **mesuree** (P7-1, puis 11/07) : elle est **PLATE**. Meme a **500 ms**, l'edge
est de **−3,74 bps**. Et la preuve OOS du copy-trading (24 133 signaux) donne **−7,97 bps meme a
cout ZERO**. Decider plus VITE ne peut pas rendre positif un signal qui n'a pas d'edge.
Z1 l'avait deja scelle : *« ne PAS optimiser la latence pour ameliorer le PnL »*.
-> Brancher P4, ce serait accelerer une machine qui va dans le mur. **Enterre.**

**P5 (bounded_event_queue) -> ENTERRE. Motif : PAS_DE_CONSOMMATEUR + ACCUSATION_FAUSSE.**
Sa taxonomie (JAMAIS_JETABLE / COALESCABLE / JETABLE) est **bonne**. Mais :
  1. il n'existe **aucun consommateur de flux temps reel** a alimenter : la seule queue vivante
     (`realtime/low_latency_event_queue`, dans `fusion_runtime:167`) est un **tampon de tri** cree
     et vide dans un seul appel, nourri **uniquement de PriceEvent** ;
  2. le bug qu'il pretendait corriger -- « la queue vivante jette des userFill en silence » --
     **n'existe pas** : cette queue ne voit **jamais** un userFill (verifie le 13/07).
-> Un module justifie par un bug inexistant, et sans consommateur. **Enterre**, et l'accusation
   corrigee a sa source (voir l'en-tete de `bounded_event_queue.py`).

CE QUE « ENTERRE » VEUT DIRE
---------------------------
Le fichier reste sur le disque, sous git, recuperable (CLAUDE.md : « ne rien supprimer
brutalement »). « Enterre » veut dire : **aucun chemin de production ne doit l'appeler, et c'est
desormais une regle TESTEE** (`tests/test_runtime_no_limbo.py`). Si quelqu'un le ressuscite par
accident, la suite rougit. S'il le ressuscite **exprès**, il doit retirer la tombe -- donc ecrire
pourquoi.

Aucun ordre reel.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TombeRuntime:
    module: str          # nom court, ex. "hot_path"
    motif: str           # ZONE_MORTE_MESUREE | PAS_DE_CONSOMMATEUR | ACCUSATION_FAUSSE | DOUBLON
    pourquoi: str        # la raison, en une phrase qu'on peut CONTREDIRE
    preuve: str          # ou verifier, en une ligne


TOMBES_RUNTIME: tuple[TombeRuntime, ...] = (
    TombeRuntime(
        module="hot_path",
        motif="ZONE_MORTE_MESUREE",
        pourquoi=(
            "decider plus vite ne peut pas creer un edge qui n'existe pas : la courbe edge/horizon "
            "est PLATE (−3,74 bps a 500 ms) et le copy-trading rend −7,97 bps meme a cout ZERO"
        ),
        preuve="Z1 + P7-1 (courbe edge/horizon) + preuve OOS du 2026-07-11 (24 133 signaux)",
    ),
    TombeRuntime(
        module="event_driven_decider",
        motif="ZONE_MORTE_MESUREE",
        pourquoi=(
            "meme raison que hot_path : c'est le moteur de la decision evenementielle, dont la "
            "seule promesse etait la VITESSE -- et la vitesse ne paie pas ici"
        ),
        preuve="Z1 ; et son unique import est son propre test",
    ),
    TombeRuntime(
        module="bounded_event_queue",
        motif="PAS_DE_CONSOMMATEUR",
        pourquoi=(
            "sa taxonomie est bonne, mais aucun consommateur de flux temps reel ne l'attend, et le "
            "bug qu'il pretendait corriger (userFill jetes en silence) N'EXISTE PAS : la seule "
            "queue vivante est un tampon de tri qui ne voit que des PriceEvent"
        ),
        preuve="strategies/fusion_runtime.py:167 (cree, rempli de PriceEvent, draine dans l'appel)",
    ),
    # ---- LES 3 COQUILLES DU BRIEF « PHASE 5 » : ecrites, jamais branchees, jamais testees.
    TombeRuntime(
        module="graceful_shutdown",
        motif="COQUILLE_JAMAIS_BRANCHEE",
        pourquoi=(
            "18 lignes, un dataclass a 2 champs, ZERO appelant et ZERO test dans tout le depot ; "
            "l'arret propre reellement utilise passe par le watchdog de backtesting/runtime_guards"
        ),
        preuve="grep `graceful_shutdown` sur tout le depot : seul son propre fichier repond",
    ),
    TombeRuntime(
        module="research_path",
        motif="COQUILLE_JAMAIS_BRANCHEE",
        pourquoi=(
            "resume les raisons de NO_TRADE... alors que le comptage des refus est deja fait, et "
            "affiche, par le journal de decisions (detailed_logger) : c'est un DOUBLON non branche"
        ),
        preuve="grep `research_path` : aucun appelant ; le comptage vivant est dans detailed_logger",
    ),
    TombeRuntime(
        module="safe_mode",
        motif="COQUILLE_JAMAIS_BRANCHEE",
        pourquoi=(
            "🚩 son nom rassure, mais il ne protege RIEN : une fonction de 2 lignes que PERSONNE "
            "n'appelle. Le no-real-trade est tenu par les 8 controles de `python -m hl_observer "
            "safety-audit` (dont l'absence de librairie d'execution installee) -- pas par ce "
            "fichier. *Un garde-fou que personne n'appelle ne garde rien.* L'enterrer ne retire "
            "aucune protection : il n'en apportait aucune."
        ),
        preuve="grep `is_safe_mode_enabled` : 0 appelant ; safety-audit reste a 8/8 sans lui",
    ),

    # ---- #302 / #286 : L'INFRA DE REPLAY DETERMINISTE -- batie, testee, JAMAIS appelee ----
    #
    # Trouvees dans le LIMBE par test_runtime_no_limbo (2026-07-16). Verifie a l'AST : AUCUN module
    # de production ne les importe. `research/differentiel.py` ne fait que CITER le nom
    # "replay_shadow" dans une chaine de mapping -- ce n'est pas un import. *Un nom dans une chaine
    # ne cable rien.* (Reversibles : pour rebrancher le replay, on retire la tombe et on l'APPELLE.)
    TombeRuntime(
        module="session_and_bus",
        motif="DOUBLON",
        pourquoi=(
            "sa moitie IDENTITE-DE-SESSION double `runtime/session_identity.py`, lui VIVANT (importe "
            "par mainnet_readonly_observer/observer, runtime/persistent_poll_runner et "
            "funding/carry_paper_runtime) ; sa moitie BUS ne sert qu'a replay_shadow, lui sans appelant"
        ),
        preuve="grep `session_identity` -> 3 imports de prod ; `session_and_bus` -> seul replay_shadow (mort) + tests",
    ),
    TombeRuntime(
        module="replay_shadow",
        motif="PAS_DE_CONSOMMATEUR",
        pourquoi=(
            "outil de REPLAY DETERMINISTE / shadow A-B, bati et teste, mais AUCUN chemin de production "
            "ne l'invoque : c'est une validation OFFLINE, pas un module du chemin de decision live"
        ),
        preuve="AST : zero import de production ; differentiel.py ne cite que son NOM dans une chaine",
    ),
)

MODULES_ENTERRES_RUNTIME: frozenset[str] = frozenset(t.module for t in TOMBES_RUNTIME)

__all__ = ["MODULES_ENTERRES_RUNTIME", "TOMBES_RUNTIME", "TombeRuntime"]
