r"""LE DOSSIER — *pour chaque trouvaille : ce qu'on garde, POURQUOI, et COMMENT s'en servir.*

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUE CE MODULE RÉPARE
═══════════════════════════════════════════════════════════════════════════════════════════════

Le moissonneur produisait un **classement**. Un classement ne dit pas :

    * **pourquoi** ce repo est là (quelle preuve exacte ?)
    * **quel trou DE NOTRE BOT** il comble
    * si on a le **droit** d'en copier une ligne (licence !)
    * **comment** l'installer et par où entrer
    * et surtout : **ce qu'on ne peut PAS en dire**

    ***Un repo bien classé n'est pas une idée qui marche.***
    C'est un repo dont on peut PROUVER qu'il mérite vingt minutes de lecture.

═══════════════════════════════════════════════════════════════════════════════════════════════
LA CLASSIFICATION — celle que CLAUDE.md impose déjà
═══════════════════════════════════════════════════════════════════════════════════════════════

    COPY_DIRECT          licence permissive + code exécutable + il comble un trou mesuré
    COPY_ADAPTED         licence permissive, mais il faut réécrire pour NOTRE architecture
    PORT_BEHAVIOR        on ne copie pas le code : on reproduit le COMPORTEMENT (+ un test)
    INSPIRE_ONLY         licence copyleft (GPL) ou absente -> **on LIT, on ne copie JAMAIS**
    SKIP_WITH_REASON     il ne comble aucun trou, ou il ment
    DEFERRED_WITH_PLAN   bon, mais bloqué par un prérequis qu'on n'a pas

🔴 **49 % des repos moissonnés n'ont AUCUNE licence.** Pas de licence = **tous droits réservés**.
   *Lisibles pour comprendre. Jamais copiables. Et ça n'est pas négociable.*

═══════════════════════════════════════════════════════════════════════════════════════════════
🚩 CE QUE LE DOSSIER DIRA TOUJOURS
═══════════════════════════════════════════════════════════════════════════════════════════════

    ***Aucun repo externe ne bypasse le RiskEngine, le ledger, ou le no-real-trade.***
    (Règle CLAUDE.md. Toute idée retenue repasse par le noyau -> PaperIntent ou NO_TRADE.)

Et chaque fiche porte une section **« ce que je ne peux PAS prouver »** — parce qu'un dossier qui
n'a que des certitudes est un dossier qui ment.

PUR : aucun réseau. Aucun code exécuté. Lecture seule.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🔑 NOS TROUS — *le seul critère qui compte : est-ce que ça répare quelque chose CHEZ NOUS ?*
#
# Chaque entrée vient d'un échec **MESURÉ** de notre bot, pas d'un mot à la mode.
# C'est ce qui transforme « repo intéressant » en « repo qui nous sert ».
# ═══════════════════════════════════════════════════════════════════════════════════════════════
NOS_TROUS: dict[str, tuple[str, str]] = {
    # concept -> (le trou MESURÉ chez nous, ce qu'on en ferait)
    "kappa_intensite_de_fill": (
        "Notre simulateur suppose un fill maker à **« 10 % du flux »** — **un chiffre INVENTÉ**, "
        "jamais mesuré. Toute conclusion sur le market making en dépend.",
        "Estimer κ par coin depuis NOS données L2+trades → probabilité de fill RÉELLE → "
        "le spread optimal se compare enfin au coût aller-retour de 9 bps.",
    ),
    "position_dans_la_file": (
        "On ne modélise **aucune** position dans la file. Or T1b a mesuré le MM à **100 % de "
        "fill** (borne haute) : 0/29 viable. Un vrai modèle de file ne peut qu'**abaisser** ce "
        "fill — donc **confirmer** la mort du MM, jamais la réfuter.",
        "PORT_BEHAVIOR : reproduire `qty_ahead` depuis les deltas L2 (aucun L3 requis) et "
        "**verrouiller par un test** que le fill modélisé ≤ le fill à 100 %.",
    ),
    "gueant_lehalle_glft": (
        "L'intuition « grinder » de Flo **a un cadre mathématique** (GLFT : le grid trading est "
        "une simplification du MM optimal). Ce qui la tue, c'est **l'absence de terme "
        "d'inventaire**.",
        "INSPIRE_ONLY le plus souvent : comprendre POURQUOI le terme d'inventaire est ce qui "
        "manque. *Le grinder est mort avec T1b ; ceci explique pourquoi.*",
    ),
    "impact_racine_carree": (
        "L'hypothèse qui pourrait expliquer nos **−7,97 bps** de copy-trading : on paie l'impact "
        "du leader **après** lui.",
        "Mesurer l'impact sur NOS fills, puis le soustraire de l'edge brut — comme on vient de "
        "le faire pour les frais et le slippage.",
    ),
    "cout_chiffre_en_bps": (
        "Le nombre qui décide de CHAQUE trade vivait dans **6 fichiers, 4 valeurs différentes**, "
        "dont un **2,5 bps qui n'existe nulle part chez Hyperliquid**.",
        "Comparer leurs grilles de frais à la nôtre (`fees/hyperliquid_fees.py`, source unique).",
    ),
    "controle_stochastique": (
        "On n'a **aucun** cadre d'optimisation : nos seuils sont posés à la main puis "
        "rétro-ajustés. *C'est la définition de l'overfit.*",
        "INSPIRE_ONLY : voir à quoi ressemble une politique dérivée d'un objectif, plutôt que "
        "d'un tâtonnement.",
    ),
    "microprix": (
        "Notre VPIN/OFI vient d'être branché **hier**. Aucune validation externe.",
        "Confronter notre implémentation à la leur. *Suspecter son propre outil avant le code "
        "d'autrui.*",
    ),
}

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 🗺️ NOTRE ARCHITECTURE — *le moissonneur doit savoir OÙ ça se branche, sinon il ne sert à rien.*
#
# Flo : *« le cmd doit connaître l'architecture de notre bot afin de chercher mieux »*.
#
#     ***Une idée sans point d'ancrage n'est pas une idée : c'est une distraction.***
#
# Chaque concept pointe sur : (le module CIBLE, comment le brancher, le test OBLIGATOIRE).
# La règle CLAUDE.md est dure : **pas de module isolé sans test ET plan de câblage.**
# ═══════════════════════════════════════════════════════════════════════════════════════════════
OU_CA_SE_BRANCHE: dict[str, tuple[str, str, str]] = {
    "kappa_intensite_de_fill": (
        "`src/hl_observer/market/flow_toxicity.py` (à côté de VPIN/OFI) — nouveau "
        "`market/fill_intensity.py`",
        "Estimer κ par coin depuis nos L2+trades, puis l'exposer au **noyau** : "
        "`noyau_unique.Contexte` reçoit `kappa`, et la **porte 6** (déjà là pour le VPIN) "
        "s'abstient si κ est non mesurable. *Ne pas savoir n'est pas une permission.*",
        "`tests/test_fill_intensity.py` — un κ **non mesurable** doit faire **REFUSER**, "
        "pas passer.",
    ),
    "position_dans_la_file": (
        "`src/hl_observer/backtesting/` — nouveau `queue_model.py`",
        "Il ne se branche **PAS** sur le chemin live : il sert à **re-mesurer T1b**. "
        "🔒 Et l'argument de domination tient : T1b a mesuré le MM à **100 % de fill** "
        "(borne haute), 0/29 viable. Un vrai modèle de file ne peut qu'**abaisser** ce fill.",
        "`tests/test_queue_model.py` — **verrouiller** que `fill_modelisé ≤ fill_100%`. "
        "*Si un modèle de file rend le MM rentable, c'est le MODÈLE qui est faux.*",
    ),
    "gueant_lehalle_glft": (
        "**nulle part** — INSPIRE_ONLY.",
        "Le MM est **fermé** (T1b : 0/29 à 100 % de fill · HLP, le MM **payé**, rend −0,01 %). "
        "Ça sert à **comprendre pourquoi le grinder est mort** (absence de terme d'inventaire), "
        "pas à le ressusciter.",
        "aucun — *on ne branche pas une stratégie morte.*",
    ),
    "impact_racine_carree": (
        "`src/hl_observer/edge/edge_calculator.py` → `compute_net_edge()`",
        "L'impact est un **COÛT**. Il se soustrait de l'edge brut, **exactement comme** les "
        "frais (9 bps) et le slippage qu'on vient de brancher. Puis le résultat repasse le "
        "**plancher de 30 bps** dans `noyau_unique`.",
        "`tests/test_impact.py` — *un coût qu'on mesure mais qu'on ne soustrait pas est un coût "
        "qu'on CACHE.* **C'est arrivé 17 fois.** Le test doit prouver la soustraction.",
    ),
    "cout_chiffre_en_bps": (
        "`src/hl_observer/fees/hyperliquid_fees.py` — **la source unique**",
        "Comparer leur grille à la nôtre. **Ne JAMAIS créer une 2ᵉ table de frais** : "
        "le nombre qui décide de chaque trade a déjà vécu dans **6 fichiers, 4 valeurs**.",
        "`tests/test_hyperliquid_fees.py` — déjà là. L'étendre, pas le doubler.",
    ),
    "controle_stochastique": (
        "**nulle part pour l'instant** — DEFERRED.",
        "On n'a aucun cadre d'optimisation. Avant d'en importer un, il faut un **objectif** — "
        "et notre objectif actuel est *« battre un dépôt passif dans HLP »*, mesuré.",
        "aucun tant que ce n'est pas branché. *Un module sans appelant est un module mort.*",
    ),
    "microprix": (
        "`src/hl_observer/market/flow_toxicity.py` (OFI/VPIN, branché le 14/07)",
        "Confronter **leur** implémentation à la nôtre. Notre VPIN vient d'être branché : "
        "il n'a **aucune validation externe**.",
        "`tests/test_flow_toxicity.py` — déjà là. *Suspecter son propre outil avant le code "
        "d'autrui.*",
    ),
}

# La carte de notre bot, telle qu'elle est VRAIMENT (pour orienter la recherche ET le dossier).
NOTRE_BOT: dict[str, str] = {
    "decision_engine/noyau_unique.py": "🔑 **LA PORTE UNIQUE** — 8 gates. Tout passe par `decider()`.",
    "edge/edge_calculator.py": "`compute_net_edge()` — l'edge APRÈS coûts. Plancher 30 bps.",
    "edge/carry_edge_source.py": "l'edge du carry — **OBSERVÉ** (funding lu), pas prédit.",
    "fees/hyperliquid_fees.py": "**la source unique des frais** (perp 4,5/1,5 · spot 7,0/4,0 bps).",
    "market/flow_toxicity.py": "VPIN · OFI · toxicité — *ne pas savoir n'est pas une permission*.",
    "market/spot_depth.py": "profondeur du carnet — *un edge sur un carnet de 3 $ n'existe pas*.",
    "market/execution_constraints.py": "l'exchange accepterait-il l'ordre ? (MinTradeNtl, BadAloPx)",
    "risk/side_lock.py": "`only_per_side` — 19/21 SHORT = 1 chance sur 4 520.",
    "risk/session_gate.py": "les 11 disjoncteurs V19.",
    "strategies/carry_runtime.py": "le moteur carry — **la seule stratégie mesurée positive**.",
    "strategies/carry_scanner.py": "le scanner carry — 4 portes (spot · signe · stabilité · éco).",
    "paper_trading/": "le **ledger** — la vérité du PnL. Tout converge dessus.",
    "backtesting/": "replay, métriques honnêtes, détection de lookahead.",
    "hyperliquid/rest_info_client.py": "**allowlist /info** — read-only, aucun endpoint d'exécution.",
}

# Ce qu'un concept de la phase 2 (grep README) veut dire pour nous.
TROUS_CONCEPTS: dict[str, str] = {
    "file_attente": "notre fill maker est un **chiffre inventé** (« 10 % du flux »)",
    "selection_adverse": "le maker est rempli **quand il a tort** — jamais modélisé chez nous",
    "avellaneda": "coter autour d'un **prix de réservation**, pas du mid",
    "latence_modele": "latence du **FLUX** vs latence des **ORDRES** — on confondait les deux",
    "carnet_rejeu": "on lit des snapshots, **on ne REJOUE rien**",
    "impact_marche": "l'hypothèse qui expliquerait nos **−7,97 bps**",
    "funding_carry": "**la seule piste à structure réelle** (PURR +7,09 % · HYPE +4,47 %)",
    "mempool": "🔴 **MESURÉ ET MORT** : le prix court CONTRE le leader **AVANT** son fill (−7,75 bps)",
    "liquidation": "🎯 **la dernière piste non mesurée** — *le liquidé ne choisit pas de vendre*",
    "biais_backtest": "notre coupe train/test **FUYAIT** (ni purge ni embargo) — 68 % de fuite",
    "validation_oos": "**7 garde-fous anti-overfit avaient ZÉRO appelant**",
    "protections": "global_stop / stop_per_pair : **on n'avait RIEN**",
    "kappa": "proba de fill selon la distance au mid : **jamais mesuré**",
}

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LA LICENCE — *49 % des repos n'en ont AUCUNE. Pas de licence = tous droits réservés.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
PERMISSIVES = ("mit", "apache", "bsd", "isc", "unlicense", "mpl", "cc0", "zlib")
COPYLEFT = ("gpl", "agpl", "lgpl", "sspl", "osl", "eupl")

VERDICTS = ("COPY_DIRECT", "COPY_ADAPTED", "PORT_BEHAVIOR",
            "INSPIRE_ONLY", "SKIP_WITH_REASON", "DEFERRED_WITH_PLAN")


def statut_licence(licence: str | None) -> tuple[str, str]:
    """`(statut, ce que ça nous autorise)`. **Deny-by-default : inconnu = INTOUCHABLE.**"""
    l = (licence or "").strip().lower()
    if not l or l in ("none", "null", "other", "noassertion"):
        return "AUCUNE", ("🔴 **Aucune licence = TOUS DROITS RÉSERVÉS.** On peut LIRE pour "
                          "comprendre. **On ne copie pas une ligne.** Ce n'est pas négociable.")
    if any(x in l for x in COPYLEFT):
        return "COPYLEFT", ("🔴 **Copyleft (%s)** : copier contaminerait tout notre code. "
                            "-> **INSPIRE_ONLY**, jamais de copie." % licence)
    if any(x in l for x in PERMISSIVES):
        return "PERMISSIVE", ("✅ **%s** : on peut adapter, en conservant l'attribution."
                              % licence)
    return "INCONNUE", ("⚠️ Licence **%s** non reconnue -> on la traite comme **INTOUCHABLE** "
                        "jusqu'à vérification humaine. *Deny-by-default.*" % licence)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# L'INSTALLATION — *déduite de l'ARBRE du repo, jamais inventée.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class Installation:
    gestionnaire: str
    commande: str
    langage: str
    point_d_entree: str
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"gestionnaire": self.gestionnaire, "commande": self.commande,
                "langage": self.langage, "point_d_entree": self.point_d_entree,
                "note": self.note}


_MARQUEURS: tuple[tuple[str, str, str, str], ...] = (
    # (fichier, gestionnaire, commande, langage)
    ("pyproject.toml", "pip", "pip install -e .", "Python"),
    ("setup.py", "pip", "pip install -e .", "Python"),
    ("requirements.txt", "pip", "pip install -r requirements.txt", "Python"),
    ("Cargo.toml", "cargo", "cargo build --release", "Rust"),
    ("package.json", "npm", "npm install", "Node/TS"),
    ("go.mod", "go", "go build ./...", "Go"),
    ("CMakeLists.txt", "cmake", "cmake -B build && cmake --build build", "C++"),
    ("environment.yml", "conda", "conda env create -f environment.yml", "Python"),
)


def installation(chemins: Sequence[str]) -> Installation:
    """Comment on l'installe. **Déduit de l'arbre. Si on ne sait pas, ON LE DIT.**"""
    bas = {str(c).lower(): str(c) for c in chemins}

    trouves: list[tuple[str, str, str]] = []
    for fichier, gest, cmd, lang in _MARQUEURS:
        if fichier.lower() in bas or any(k.endswith("/" + fichier.lower()) for k in bas):
            trouves.append((gest, cmd, lang))

    # le point d'entrée : un notebook, un __main__, un exemple...
    entree = ""
    for c in chemins:
        b = str(c).lower()
        if b.endswith("__main__.py") or b.endswith("/main.py") or b == "main.py":
            entree = str(c)
            break
    if not entree:
        for c in chemins:
            if str(c).lower().endswith(".ipynb"):
                entree = "%s  *(notebook — souvent le meilleur point d'entrée)*" % c
                break

    if not trouves:
        return Installation(
            "INCONNU", "—", "—", entree or "—",
            "⚠️ **Aucun manifeste d'installation trouvé** (ni `pyproject`, ni `Cargo.toml`, "
            "ni `package.json`...). *Je ne devine pas une commande d'installation : je dis "
            "que je ne sais pas.*",
        )

    gest, cmd, lang = trouves[0]
    note = ""
    if len(trouves) > 1:
        note = "Plusieurs écosystèmes détectés : %s." % ", ".join(sorted({t[2] for t in trouves}))
    return Installation(gest, cmd, lang, entree or "—", note)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LE VERDICT — *la classification que CLAUDE.md impose.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class Fiche:
    repo: str
    verdict: str
    pourquoi: str
    trous_combles: list[str] = field(default_factory=list)
    reserves: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"repo": self.repo, "verdict": self.verdict, "pourquoi": self.pourquoi,
                "trous_combles": self.trous_combles, "reserves": self.reserves}


def classer(repo: str, *, licence: str | None, signaux: Mapping[str, Any],
            n_lignes_de_code: int = 0) -> Fiche:
    """**Le verdict.** Chaque branche s'explique. *Un refus muet est un refus inauditable.*"""
    statut, _ = statut_licence(licence)
    formules = list((signaux.get("formules") or {}).keys())
    aveux = list(signaux.get("aveux_de_limite") or [])
    creuses = list(signaux.get("promesses_creuses") or [])

    trous = [f for f in formules if f in NOS_TROUS]
    reserves: list[str] = []

    # 🚩 Le menteur, d'abord. *Promettre sans jamais douter est une signature d'arnaque.*
    if creuses and not aveux:
        return Fiche(repo, "SKIP_WITH_REASON",
                     "🚩 Il **promet sans jamais douter** (%s) et **n'avoue aucune limite**. "
                     "*Dans ce corpus, l'absence d'aveu est le signal d'alarme.*"
                     % creuses[0][:60], trous, reserves)

    # Il ne comble aucun trou MESURÉ chez nous.
    if not trous:
        return Fiche(repo, "SKIP_WITH_REASON",
                     "Il ne pose **aucune formule qui comble un trou MESURÉ de notre bot**. "
                     "*Intéressant n'est pas utile.*", trous, reserves)

    if aveux:
        reserves.append("Il **avoue lui-même** une limite : « %s ». *C'est ce qui le rend "
                        "crédible — et c'est aussi une limite qu'on héritera.*" % aveux[0][:90])

    if statut in ("AUCUNE", "COPYLEFT", "INCONNUE"):
        return Fiche(repo, "INSPIRE_ONLY",
                     "Licence **%s** -> on **LIT**, on ne copie **aucune ligne**. "
                     "Le comportement peut être **reproduit** de zéro, avec un test qui le "
                     "prouve." % statut, trous, reserves)

    if n_lignes_de_code == 0:
        reserves.append("⚠️ **Aucune ligne de code n'a été lue** (arbre illisible ou fichiers "
                        "hors sujet). *Le README seul ne suffit pas à juger.*")
        return Fiche(repo, "DEFERRED_WITH_PLAN",
                     "Licence permissive et formules pertinentes, **mais on n'a pas encore "
                     "ouvert son code**. -> plan : lire les fichiers listés ci-dessous.",
                     trous, reserves)

    # Permissive + code lu + comble un trou.
    if len(trous) >= 2:
        return Fiche(repo, "COPY_ADAPTED",
                     "Licence permissive, **%d formules** qui comblent des trous mesurés, et son "
                     "code a été lu. -> on **adapte** à notre architecture (`src/hl_observer/`), "
                     "on ne colle pas." % len(trous), trous, reserves)

    return Fiche(repo, "PORT_BEHAVIOR",
                 "Licence permissive et une formule utile. -> on **reproduit le comportement** "
                 "chez nous, **avec un test qui le prouve**. *Pas de copier-coller : un "
                 "comportement porté sans test n'est pas porté.*", trous, reserves)


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# 📋 LE PLAN D'ACTION — *le .md n'est pas un résumé : c'est un ORDRE DE MISSION.*
#
# Flo : *« il faut que le moisson-fini.md soit ultra détaillé pour que TOI tu puisses comprendre
#         absolument tout : quoi faire, quoi brancher, où brancher. »*
#
# -> chaque fiche porte une **suite d'étapes numérotées, exécutables**, avec la **commande** et
#    le **critère d'acceptation**. *Un plan sans critère d'acceptation n'est pas un plan :
#    c'est un souhait.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class Tache:
    """**Une tâche.** Elle porte son ID, son POURQUOI, son APPORT et son CRITÈRE.

    *Une tâche sans critère d'acceptation n'est pas une tâche : c'est un souhait.*
    *Une tâche sans « pourquoi » sera abandonnée à la première difficulté.*
    """
    id: str
    titre: str
    pourquoi: str          # pourquoi on le fait — la CAUSE, pas la description
    apport: str            # ce que ça nous apporte, concrètement
    comment: str           # les gestes exacts
    critere: str           # 🔒 comment on sait que c'est FINI

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "titre": self.titre, "pourquoi": self.pourquoi,
                "apport": self.apport, "comment": self.comment, "critere": self.critere}

    def md(self) -> list[str]:
        return [
            "#### `%s` — %s" % (self.id, self.titre),
            "",
            "| | |",
            "|---|---|",
            "| **Pourquoi on le fait** | %s |" % self.pourquoi,
            "| **Ce que ça nous apporte** | %s |" % self.apport,
            "| **Comment** | %s |" % self.comment,
            "| 🔒 **Critère — c'est FINI quand…** | %s |" % self.critere,
            "",
        ]


def plan_d_action(repo: str, verdict: str, trous: Sequence[str],
                  lectures: Sequence[Mapping[str, Any]], *, prefixe: str = "T") -> list[Tache]:
    """Les tâches, **identifiées**, dans l'ordre. *Aucune ne doit pouvoir se perdre.*

    Flo : *« aucune tâche laissée de côté, aucun détail oublié »*.
    -> chaque tâche a un **ID**. La checklist finale les reprend **toutes**. Si une tâche
    n'apparaît pas dans la checklist, c'est un **bug du générateur**, pas un oubli humain.
    """
    if verdict == "SKIP_WITH_REASON":
        return []

    t: list[Tache] = []
    n = 0

    def _id() -> str:
        nonlocal n
        n += 1
        return "%s-%d" % (prefixe, n)

    # ── TÂCHE 1 — LIRE. Toujours en premier. *Trier ne remplace jamais lire.* ──────────────────
    if lectures:
        lignes = "<br>".join(
            "`%s:%s` → %s" % (x.get("fichier"), x.get("ligne"), x.get("pourquoi"))
            for x in list(lectures)[:8]
        )
        t.append(Tache(
            _id(), "LIRE le code — ces lignes exactes",
            "Parce que **trier ne remplace jamais lire**. Le chiffre est brutal : "
            "**8 passes de tri sur 5 617 repos → 3 idées**, alors que **20 minutes à lire le "
            "code d'UN seul repo (hftbacktest) → 5 bugs trouvés dans notre simu**. "
            "Le README est une **page de vente** ; le code est la **vérité**.",
            "Comprendre **ce que leur code fait que le nôtre ne fait pas**. C'est la seule "
            "étape qui ait jamais produit quelque chose dans ce projet.",
            "Ouvrir ces lignes sur GitHub (**aucun clone nécessaire**) :<br>%s" % lignes,
            "Tu sais dire **en une phrase** ce que leur code fait que le nôtre ne fait pas. "
            "**Si tu ne peux pas, tu n'as pas lu** — et tu n'as pas le droit de porter.",
        ))
    else:
        t.append(Tache(
            _id(), "LIRE le code — ⚠️ aucune ligne extraite automatiquement",
            "Le grep n'a rien trouvé, **ce qui ne veut pas dire qu'il n'y a rien** : ça veut "
            "dire que **mon filtre est peut-être trop étroit**. *Un filtre trop étroit rate en "
            "silence — c'est la pathologie de ce projet.*",
            "Soit on trouve la substance à la main, soit on **écarte honnêtement**.",
            "Ouvrir le repo, chercher les fichiers dont le **nom** annonce le sujet.",
            "Ou bien tu as trouvé la substance, ou bien tu **écris pourquoi il n'y en a pas**. "
            "*Un « je n'ai rien trouvé » documenté vaut mieux qu'un silence.*",
        ))

    # ── TÂCHE 2 — LA LICENCE, AVANT d'écrire une ligne. ───────────────────────────────────────
    if verdict == "INSPIRE_ONLY":
        t.append(Tache(
            _id(), "🔴 NE COPIER AUCUNE LIGNE — licence absente ou copyleft",
            "**49 % des repos moissonnés n'ont AUCUNE licence.** Pas de licence = **tous droits "
            "réservés**. Un copyleft (GPL) **contaminerait tout notre dépôt**. "
            "*Ce n'est pas de la prudence : c'est le droit.*",
            "On garde le **bénéfice de l'idée** sans le **risque juridique**.",
            "Comprendre le comportement, **fermer leur code**, puis le **réécrire de zéro** dans "
            "notre style. *Ne pas regarder leur code pendant qu'on écrit le nôtre.*",
            "**Aucun bloc de leur code dans notre dépôt.** Jamais. Et un test qui prouve que "
            "**notre** implémentation reproduit **leur** comportement.",
        ))
    else:
        t.append(Tache(
            _id(), "Vérifier la licence dans le fichier `LICENSE` lui-même",
            "Le champ SPDX de l'API GitHub **ment parfois** (détection heuristique). "
            "*Suspecter son propre outil avant le code d'autrui.*",
            "Le droit de réutiliser, **établi**, pas supposé.",
            "Ouvrir le fichier `LICENSE` à la racine du repo et **le lire**.",
            "Si le fichier `LICENSE` **contredit** l'API, **l'API a tort** — et on suit le "
            "fichier. En cas de doute : **INTOUCHABLE** (deny-by-default).",
        ))

    # ── TÂCHE 3..n — PORTER, avec le test dans le MÊME mouvement. ─────────────────────────────
    for tr in trous:
        cible, comment, test = OU_CA_SE_BRANCHE.get(
            tr, ("*(à déterminer)*", "*(à déterminer)*", "*(obligatoire)*"))
        probleme, usage = NOS_TROUS.get(tr, ("—", "—"))
        t.append(Tache(
            _id(), "Porter `%s`" % tr,
            "**Notre trou mesuré :** %s" % probleme,
            usage,
            "**Où :** %s<br>**Comment :** %s<br>**Test (même mouvement) :** %s"
            % (cible, comment, test),
            "Le module **ET** son test existent. 🔒 *Règle CLAUDE.md : un nouveau fichier dans "
            "`src/` **sans test** = **ÉCHEC BLOQUANT**. Ils se créent ensemble, jamais l'un "
            "sans l'autre.*",
        ))

    # ── TÂCHE n+1 — BRANCHER. *Sinon le module est mort-né.* ──────────────────────────────────
    t.append(Tache(
        _id(), "🔌 BRANCHER dans `noyau_unique.decider()`",
        "***La maladie de ce projet, trouvée 18 fois : une capacité présente, un chaînon "
        "manquant, personne qui se plaint.*** Constat de Flo, vérifié : **22 modules livrés, "
        "3 branchés.** Et les pires : le **plancher d'edge à ZÉRO** dans le chemin live · les "
        "**frais par défaut à 0.0** · **7 garde-fous anti-overfit avec zéro appelant**.",
        "Sans cette tâche, **tout le reste ne sert à rien**. Un module que `decider()` n'appelle "
        "pas est un module **MORT** — et il donnera l'illusion rassurante d'être protégé.",
        "1) ajouter le champ au `Contexte` · 2) ajouter la **porte** (ou étendre une porte "
        "existante) · 3) `None` / non mesurable → **REFUS**, jamais un défaut permissif.",
        "`python tools/audit_cablage_cli.py` **voit** le nouveau garde **dans** la porte. "
        "🔒 C'est un audit **AST**, pas un grep — *un grep lit les docstrings et se fait "
        "berner par un commentaire.*",
    ))

    # ── TÂCHE n+2 — MESURER, et accepter le verdict. ──────────────────────────────────────────
    t.append(Tache(
        _id(), "📏 MESURER — et accepter le verdict, même mauvais",
        "Parce que **~600 idées ont été mesurées et UNE SEULE a survécu** (le carry). "
        "*Le taux de base est écrasant.* Une idée non mesurée **chez nous** ne vaut rien — "
        "et une idée qu'on refuse de mesurer est une idée qu'on protège.",
        "Un chiffre **traçable au ledger**, qu'on peut publier sans rougir.",
        "```\noutils de test\\TOUT-VERIFIER.cmd\nLANCER-TOUT.cmd\n```",
        "L'edge net **après** frais + spread + slippage + impact **bat un dépôt passif dans "
        "HLP** (mesuré : **−0,01 % APR**), le **CASH**, et le **buy-and-hold**. "
        "🚩 **Si le chiffre est mauvais, on le publie quand même.** *Attends-toi à un échec : "
        "ce ne sera pas une défaite, ce sera une mesure.*",
    ))
    return t


# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LE DOSSIER MARKDOWN — *le livrable que Flo a demandé.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
_ORDRE = {v: i for i, v in enumerate(
    ("COPY_ADAPTED", "PORT_BEHAVIOR", "COPY_DIRECT", "DEFERRED_WITH_PLAN",
     "INSPIRE_ONLY", "SKIP_WITH_REASON"))}

# 🤖 L'EN-TÊTE POUR L'AGENT — *ce que quelqu'un qui arrive froid DOIT savoir avant d'agir.*
_BRIEFING = """
> ## 🤖 À lire avant d'agir — *ce fichier est un ordre de mission, pas un résumé*
>
> ### Les règles dures du projet (non négociables)
>
> | | |
> |---|---|
> | 🔴 **Aucune exécution réelle** | 0 ordre · 0 argent · 0 clé privée · 0 signature · 0 dépôt/retrait. **Paper-only, read-only.** |
> | 🔴 **Aucune donnée fabriquée** | donnée manquante / trop vieille / contradictoire → `NO_TRADE` ou `INSUFFICIENT_DATA`. **Jamais un zéro silencieux.** |
> | 🔴 **Aucun module sans test** | un nouveau fichier dans `src/` sans test = **ÉCHEC BLOQUANT**. Ils se créent **ensemble**. |
> | 🔴 **Rien ne bypasse le noyau** | toute idée repasse par `decision_engine/noyau_unique.py` → **PaperIntent** ou **NO_TRADE** → PaperLedger. |
> | 🔴 **Ne rien supprimer brutalement** | un `move`, jamais un `delete`. |
>
> ### La maladie de ce projet — *tu vas la reproduire si tu ne la connais pas*
>
> **« Une capacité présente, un chaînon manquant, et personne qui se plaint. »**
> Trouvée **18 fois**. Ses formes : le plancher d'edge à **zéro** dans le chemin live · les frais
> par défaut à **0.0** · **22 modules livrés, 3 branchés** · 7 garde-fous anti-overfit avec **zéro
> appelant** · l'APR affiché qui était le **brut** (coûts vérifiés à la porte, **jamais soustraits
> du chiffre**) · le noyau qui ne vérifiait **qu'une jambe sur deux**.
>
> 👉 **Un module qui n'est pas appelé par `decider()` est un module MORT.** Vérifie-le avec
> `tools/audit_cablage_cli.py` (**AST**, pas un grep — *un grep lit les docstrings*).
>
> ### Ce qui est déjà MESURÉ et MORT — *ne le re-litige pas*
>
> - **copy-trading** : **−7,97 bps** même à coût **ZÉRO** (24 133 signaux OOS). Le leader est **contrarien**, pas informé.
> - **market making** : **0/29** même à **100 % de fill** (la borne la plus généreuse). Et **HLP — le MM *payé* par le protocole, et liquidateur — rend −0,01 % APR.**
> - funding perp↔perp : **0/120** · lead-lag BTC→alts : **0/66** · cointégration : **0** sur 208 j · le mempool : le prix court **contre** le leader **avant** son fill.
>
> ### Ce qui VIT
>
> - **le carry delta-neutre** : PURR **+7,09 %** · HYPE **+4,47 %** APR (après frais **et** slippage 4 jambes). *La seule chose positive sur ~600 idées.*
> - 🎯 **#530 les liquidations** — **la dernière piste non mesurée**. *Le liquidé ne choisit pas de vendre : il est **vendu**.*
>
> ### Le benchmark qui juge tout
>
> **Si une idée ne bat pas un dépôt passif dans HLP, elle est dominée.** Le CASH et le
> buy-and-hold sont les deux autres juges.
>
> ---
"""


def dossier_md(entrees: Sequence[Mapping[str, Any]]) -> str:  # noqa: C901
    """Le `.md` **entièrement détaillé** : quoi, pourquoi, comment, et ce qu'on ne sait pas."""
    e = sorted(entrees, key=lambda x: (_ORDRE.get(str(x.get("verdict")), 9),
                                       -float(x.get("score") or 0)))
    gardes = [x for x in e if str(x.get("verdict")) != "SKIP_WITH_REASON"]
    jetes = [x for x in e if str(x.get("verdict")) == "SKIP_WITH_REASON"]

    md: list[str] = [
        "# 🌾 moisson-fini — *ce qu'on garde, POURQUOI, OÙ le brancher, et ce qu'on ignore*",
        "",
        "> **Un repo bien classé n'est pas une idée qui marche.**",
        "> C'est un repo dont on peut **prouver** qu'il mérite vingt minutes de lecture.",
        "",
        _BRIEFING,
        "",
        "## Le tableau de bord",
        "",
        "| | nombre |",
        "|---|---|",
        "| **retenus** | **%d** |" % len(gardes),
        "| écartés (avec motif) | %d |" % len(jetes),
        "",
        "| verdict | ce que ça autorise | n |",
        "|---|---|---|",
        "| `COPY_ADAPTED` | licence permissive → on **réécrit** pour notre archi | %d |"
        % sum(1 for x in e if x.get("verdict") == "COPY_ADAPTED"),
        "| `PORT_BEHAVIOR` | on reproduit le **comportement**, **avec un test** | %d |"
        % sum(1 for x in e if x.get("verdict") == "PORT_BEHAVIOR"),
        "| `DEFERRED_WITH_PLAN` | bon, mais **son code n'a pas encore été lu** | %d |"
        % sum(1 for x in e if x.get("verdict") == "DEFERRED_WITH_PLAN"),
        "| `INSPIRE_ONLY` | 🔴 licence absente/copyleft → **on LIT, on ne copie JAMAIS** | %d |"
        % sum(1 for x in e if x.get("verdict") == "INSPIRE_ONLY"),
        "| `SKIP_WITH_REASON` | ne comble aucun trou, ou **il ment** | %d |" % len(jetes),
        "",
        "---",
        "",
        "# ✅ LES RETENUS",
        "",
    ]

    if not gardes:
        md += ["> ⚪ **Aucun repo retenu.** *Ce n'est pas une panne : le corpus n'a rien donné.*",
               "> Un état vide honnête vaut mieux qu'une liste remplie pour faire joli.", ""]

    # 🔒 LE REGISTRE DE TOUTES LES TÂCHES — *aucune ne doit pouvoir se perdre.*
    toutes_les_taches: list[tuple[str, Tache]] = []

    for i_repo, x in enumerate(gardes):
        nom = str(x.get("repo"))
        sig = x.get("signaux") or {}
        inst = x.get("installation") or {}
        stat, droit = statut_licence(x.get("licence"))

        md += [
            "## `%s`" % nom,
            "",
            "**Verdict : `%s`** · score de substance **%.1f** · %s⭐"
            % (x.get("verdict"), float(x.get("score") or 0), x.get("etoiles") or 0),
            "",
            "🔗 https://github.com/%s" % nom,
            "",
            "### Pourquoi on le garde",
            "",
            str(x.get("pourquoi") or "—"),
            "",
        ]

        # 🔑 CE QU'IL RÉPARE **CHEZ NOUS** — le seul critère qui compte.
        trous = list(x.get("trous_combles") or [])
        if trous:
            md += ["### 🔑 Le trou de NOTRE bot qu'il comble", ""]
            for t in trous:
                probleme, usage = NOS_TROUS.get(t, ("—", "—"))
                md += ["**`%s`**" % t, "",
                       "- **Notre problème mesuré :** %s" % probleme,
                       "- **Ce qu'on en ferait :** %s" % usage, ""]

        # LA PREUVE — jamais un score sans sa preuve.
        md += ["### La preuve (extraits **réels** de son README)", ""]
        formules = sig.get("formules") or {}
        if formules:
            md.append("**Formules posées** — *citer un nom est gratuit ; poser une formule "
                      "veut dire qu'on a calculé :*")
            md.append("")
            for k, preuves in formules.items():
                md.append("- `%s` → « …%s… »" % (k, str(preuves[0])[:120]))
            md.append("")
        aveux = sig.get("aveux_de_limite") or []
        if aveux:
            md += ["**🔑 Aveux de limite** — *dans un corpus où tout le monde promet de l'alpha, "
                   "**avouer une limite est la seule signature possible de l'honnêteté** :*", ""]
            md += ["- « …%s… »" % str(a)[:130] for a in aveux[:3]]
            md.append("")
        chiffres = sig.get("chiffres_verifiables") or []
        if chiffres:
            md += ["**Chiffres vérifiables** — *un chiffre précis est une prise :*", ""]
            md += ["- « …%s… »" % str(c)[:110] for c in chiffres[:3]]
            md.append("")

        # LA LICENCE — ce qu'on a le DROIT de faire.
        md += ["### Licence : **%s**" % (x.get("licence") or "aucune"), "", droit, ""]

        # L'INSTALLATION.
        md += [
            "### Comment l'installer",
            "",
            "```bash",
            "git clone https://github.com/%s" % nom,
            "cd %s" % nom.split("/")[-1],
            str(inst.get("commande") or "# ⚠️ aucun manifeste trouvé — voir la note"),
            "```",
            "",
            "| | |",
            "|---|---|",
            "| gestionnaire | `%s` |" % (inst.get("gestionnaire") or "INCONNU"),
            "| langage | %s |" % (inst.get("langage") or "—"),
            "| point d'entrée | `%s` |" % (inst.get("point_d_entree") or "—"),
        ]
        if inst.get("note"):
            md += ["", "> %s" % inst["note"]]
        md.append("")

        # 🔑🔑 COMMENT LE BRANCHER **CHEZ NOUS** — *une idée sans point d'ancrage est une
        #      distraction.* La règle CLAUDE.md : **pas de module sans test ET plan de câblage.**
        if trous:
            md += ["### 🔌 Comment le brancher dans NOTRE bot", ""]
            for t in trous:
                cible, comment, test = OU_CA_SE_BRANCHE.get(
                    t, ("*(à déterminer)*", "*(à déterminer)*", "*(obligatoire)*"))
                md += [
                    "**`%s`**" % t, "",
                    "| | |", "|---|---|",
                    "| **où** | %s |" % cible,
                    "| **comment** | %s |" % comment,
                    "| **test obligatoire** | %s |" % test,
                    "",
                ]
            md += [
                "> 🔒 **Et ensuite, quoi qu'il arrive :** l'idée repasse par "
                "`noyau_unique.decider()` — frais réels, plancher net 30 bps, disjoncteurs de "
                "session, `only_per_side`, VPIN, contraintes d'exchange, **jambe spot**.",
                "> ***Aucun repo externe ne bypasse le noyau, le ledger, ou le no-real-trade.***",
                "",
            ]

        # 🔑 LES LIGNES À LIRE — le vrai livrable.
        lectures = list(x.get("lectures") or [])
        if lectures:
            md += ["### 🔑 Les lignes à ouvrir",
                   "",
                   "*8 passes de tri sur 5 617 repos → 3 idées. "
                   "20 min à lire le code d'UN repo → **5 bugs** dans notre simu.*",
                   "***Trier ne remplacera jamais lire.***",
                   ""]
            for lec in lectures[:8]:
                md += ["- **[`%s:%s`](https://github.com/%s/blob/HEAD/%s#L%s)** — %s"
                       % (lec.get("fichier"), lec.get("ligne"), nom,
                          lec.get("fichier"), lec.get("ligne"), lec.get("pourquoi")),
                       "  ```",
                       "  %s" % lec.get("code"),
                       "  ```"]
            md.append("")

        # 📋 LE PLAN D'ACTION — *chaque tâche porte son POURQUOI et son APPORT.*
        taches = plan_d_action(nom, str(x.get("verdict")), trous, lectures,
                               prefixe="T%d" % (i_repo + 1))
        toutes_les_taches.extend((nom, t) for t in taches)
        if taches:
            md += ["### 📋 Le plan d'action — **%d tâches, aucune optionnelle**" % len(taches),
                   ""]
            for t in taches:
                md += t.md()

        # 🚩 CE QU'ON NE PEUT PAS PROUVER.
        reserves = list(x.get("reserves") or [])
        md += ["### 🚩 Ce que je ne peux **pas** prouver", ""]
        if reserves:
            md += ["- %s" % r for r in reserves]
        md += [
            "- **Qu'il gagne de l'argent.** Sur 222 repos Hyperliquid moissonnés, "
            "**probablement zéro** publie un PnL vérifiable on-chain.",
            "- **Que son code marche.** On l'a **lu**, jamais **exécuté** — et on ne "
            "l'exécutera pas.",
            "- **Qu'il nous servira.** Il comble un trou *sur le papier*. "
            "*Une idée non mesurée chez nous ne vaut rien.*",
            "",
            "---",
            "",
        ]

    # LES ÉCARTÉS — *on dit pourquoi. Un rejet muet est un rejet inauditable.*
    md += ["", "# 🔴 LES ÉCARTÉS — et **pourquoi**", "",
           "*Un rejet sans motif est un rejet qu'on ne peut pas contester — donc pas corriger.*",
           "", "| repo | motif |", "|---|---|"]
    for x in jetes[:80]:
        md.append("| `%s` | %s |" % (x.get("repo"), str(x.get("pourquoi") or "—")[:150]))
    if len(jetes) > 80:
        md.append("| … | *(+%d autres, voir le JSON)* |" % (len(jetes) - 80))

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 🔒 LA CHECKLIST GLOBALE — *aucune tâche ne peut se perdre.*
    #
    # Flo : *« il ne faudra laisser aucune tâche de côté, aucun détail oublié »*.
    #
    # Elle est **générée depuis le même registre** que les fiches. Si une tâche apparaît dans
    # une fiche mais pas ici, c'est un **bug du générateur** — pas un oubli humain.
    # ***Une liste tenue à la main finit toujours par diverger.***
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    md += [
        "",
        "---",
        "",
        "# ✅ LA CHECKLIST — **%d tâches. Aucune optionnelle.**" % len(toutes_les_taches),
        "",
        "> Cette liste est **générée depuis le même registre** que les fiches ci-dessus.",
        "> *Si une tâche apparaît dans une fiche mais pas ici, c'est un **bug du générateur** —*",
        "> *pas un oubli humain. **Une liste tenue à la main finit toujours par diverger.***",
        "",
        "**L'ordre compte.** Ne pas porter avant d'avoir lu. Ne pas mesurer avant d'avoir branché.",
        "",
    ]
    if not toutes_les_taches:
        md += ["> ⚪ **Aucune tâche.** *Le corpus n'a rien donné qui mérite du travail.*",
               "> Ce n'est pas un échec de l'outil : c'est une mesure.", ""]
    else:
        courant = ""
        for repo_nom, t in toutes_les_taches:
            if repo_nom != courant:
                courant = repo_nom
                md += ["", "### `%s`" % repo_nom, ""]
            md.append("- [ ] **`%s`** — %s" % (t.id, t.titre))
            md.append("  - *pourquoi :* %s" % t.pourquoi)
            md.append("  - *apport :* %s" % t.apport)
            md.append("  - 🔒 *fini quand :* %s" % t.critere)
        md.append("")

    md += [
        "",
        "---",
        "",
        "## 🚩 Ce que ce fichier n'est pas",
        "",
        "- **Ce n'est pas une promesse de PnL.** *Aucun de ces repos n'a été mesuré chez nous.* "
        "Sur ~600 idées mesurées, **une seule** a survécu.",
        "- **Ce n'est pas une autorisation de copier.** Vérifier la licence **à chaque fois** — "
        "49 % des repos n'en ont **aucune**, et *pas de licence = tous droits réservés*.",
        "- **Ce n'est pas un raccourci.** ***Trier ne remplacera jamais lire.***",
        "- **Ce n'est pas exhaustif.** Ce qui n'a pas été trouvé n'est pas ce qui n'existe pas. "
        "*Un filtre trop étroit rate en silence.*",
        "",
        "## 🔒 Sécurité",
        "",
        "**0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**",
        "**Aucun clone. Aucun code téléchargé n'est exécuté. Jamais.**",
        "",
    ]
    return "\n".join(md)


__all__ = [
    "COPYLEFT", "NOS_TROUS", "PERMISSIVES", "TROUS_CONCEPTS", "VERDICTS",
    "Fiche", "Installation",
    "classer", "dossier_md", "installation", "statut_licence",
]
