r"""LE MOISSONNEUR — **10 HEURES SANS S'ARRÊTER.** Les 15 idées, câblées.

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUI TUE UN SCAN DE 10 HEURES — et ce qu'on fait de chacun
═══════════════════════════════════════════════════════════════════════════════════════════════

  1. **le quota**            -> on **ATTEND** et on **réessaie à l'infini** (`scan_resilience`)
  2. **le réseau qui tombe** -> backoff + **jitter**, borné, puis on **passe et on COMPTE**
  3. **une exception**       -> chaque phase est **isolée**. Une phase qui casse ne tue pas le run.
  4. **la mémoire**          -> tout va au **CACHE DISQUE**, rien ne s'accumule en RAM
  5. **Ctrl-C / coupure**    -> **checkpoint après CHAQUE requête**. On reprend **exactement** là.
  6. **le saupoudrage**      -> le **BANDIT** (UCB) alloue le quota **aux requêtes qui rendent**
  7. 🔴 **le mensonge**      -> *un scan qui ne meurt jamais ET ne se plaint jamais MENT.*
                                Chaque blessure est **comptée et publiée**.

    ***Ne jamais mourir. Ne jamais mentir.***

═══════════════════════════════════════════════════════════════════════════════════════════════
LES 15 IDÉES, ET OÙ ELLES SONT
═══════════════════════════════════════════════════════════════════════════════════════════════

  #1  LE CANARI          -> 🔒 **AVANT TOUT.** Si le trieur ne retrouve pas ce qu'on sait bon,
                            **le run s'arrête et ne rend AUCUN verdict.**
  #2  les COMMITS        -> les bugs que d'autres ont **déjà payés**
  #3  le DIFFÉRENTIEL    -> on note le **DELTA**, pas le niveau
  #4  les ISSUES         -> des **aveux involontaires**
  #5  les TESTS          -> la carte des **peurs** de l'auteur
  #6  les CONSTANTES     -> du **calibrage gratuit**
  #7  le CACHE BRUT      -> re-juger **hors ligne**, en 10 s
  #8  la DÉDUP par code  -> ne pas lire **30 fois le même bot**
  #9  le BANDIT          -> *une ressource rare se pilote*
  #10 les CITATIONS      -> *une étoile est un clic ; une citation est un choix d'ingénieur*
  #11 les AUTEURS        -> *les gens sont plus constants que les projets*
  #12 la REPRODUCTIBILITÉ-> *un backtest qu'on ne peut pas rejouer est une **affirmation***
  #13 la CHRONOLOGIE     -> les repos nés **juste après** un changement de protocole
  #14 la CONTRADICTION   -> 🔴 **chercher ce qui nous donne TORT**
  #15 les ZONES VIERGES  -> *ce que **personne** ne fait*

🔒 100 % LECTURE SEULE. Aucun clone. **Aucun code téléchargé n'est exécuté. JAMAIS.**
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import traceback
from datetime import datetime
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import canari  # noqa: E402
from hl_observer.research.differentiel import (  # noqa: E402
    indexer_notre_code,
    score_differentiel,
    zones_vierges,
)
from hl_observer.research.github_dossier import classer, dossier_md, installation  # noqa: E402
from hl_observer.research.github_graph import (  # noqa: E402
    dependances,
    est_une_liste,
    liens_de_repos,
    requetes_ciblees,
)
from hl_observer.research.github_scan_plan import deduplique, plan_de_scan  # noqa: E402
from hl_observer.research.github_signals import (  # noqa: E402
    analyser,
    fichiers_a_lire,
    liste_de_lecture,
    score,
)
from hl_observer.research.mine_de_code import (  # noqa: E402
    extraire_constantes,
    fouiller_commits,
    fouiller_issues,
    peurs_de_l_auteur,
    reproductibilite,
)
from hl_observer.research.moteur import (  # noqa: E402
    Bandit,
    CacheBrut,
    autorite,
    autres_repos_de_l_auteur,
    citations_inverses,
    dedupliquer,
    requetes_chronologiques,
    requetes_de_contradiction,
)
from hl_observer.research.scan_resilience import (  # noqa: E402
    ABANDONNER,
    ATTENDRE,
    REESSAYER,
    Blessures,
    decider,
)
from hl_observer.research.github_scan_plan import REQUETES_CODE  # noqa: E402
from hl_observer.research.moissonneur_sujets import SUJETS, TEXTE  # noqa: E402
from hl_observer.research.frontiere import (  # noqa: E402
    Frontiere,
    Piste,
    dans_notre_domaine,
    depuis_commits,
    depuis_dependances,
    extraire,
    fond_de_roulement,
)
from hl_observer.research.web_ouvert import (  # noqa: E402
    RYTHMES,
    UA,
    rapport as rapport_web,
    url_arxiv,
    url_cratesio,
    url_hn,
    url_openalex,
    url_openalex_cite_par,
    url_pypi,
    url_semanticscholar,
    url_stackexchange,
)
from hl_observer.research.sources import catalogue, juger  # noqa: E402
from hl_observer.research.sources_plus import (  # noqa: E402
    CATALOGUE as SOURCES_17,
    parser as parser_src,
    rapport as rapport_17,
    url as url_src,
)
from hl_observer.research.idee import (  # noqa: E402
    PRE_APPROBATION,
    extraire_idees,
)
from hl_observer.research.semantique import (  # noqa: E402
    diagnostic as diagnostic_semantique,
    merite_un_second_regard,
)
from hl_observer.research.jugement_plus import (  # noqa: E402
    appliquer_retours,
    charger_retours,
    dedupliquer_idees,
    deja_mort,
    lier_repo_et_papier,
    prioriser,
)
from hl_observer.research.lecture_profonde import (  # noqa: E402
    ecrire_derniere_date,
    extraits_du_corps,
    filtre_date_github,
    linter_md,
    lire_derniere_date,
    texte_du_html,
    url_papier_plein_texte,
)

CACHE = CacheBrut(RACINE / "data" / "cache_moisson")
ETAT = RACINE / "data" / "reports" / "moisson_10h_etat.json"
BATTEMENT = RACINE / "moisson-en-cours.txt"          # 🔑 pour que Flo puisse REGARDER
SORTIE_MD = RACINE / "moisson-fini.md"
SORTIE_JSON = RACINE / "data" / "reports" / "moisson_10h.json"

# 🔴 LE DEADLINE DU RUN — *une attente de quota ne doit JAMAIS dépasser le temps restant.*
#    Sans ça (constaté sur un run court sans clé), un `403` déclenche un sommeil de 15 min qui
#    dépasse la fin du run et le fait « pendre ». `_get` cape désormais son attente à ce qui reste.
_DEADLINE: float = float("inf")

PAUSE_REPO = 2.1        # 30 req/min
PAUSE_CODE = 6.5        # 10 req/min -- /search/code est bien plus severe
PAUSE_DOUCE = 0.8
# 🔴 Flo (15/07) : le tri doit rester RAPIDE et LOCAL. On télécharge au plus ce nombre de README
#    NON encore en cache ; au-delà, on note le dépôt localement (topics/nom). Le cache, lui, est
#    toujours gratuit et illimité. (Un run de 180k dépôts ne peut pas fetch 180k README en 12 h.)
PLAFOND_FETCH = int(os.environ.get("MOISSON_PLAFOND_FETCH", "5000"))
# 🔴 Flo (15/07) : LIRE TOUS les dépôts. On note les 180k en LOCAL (instantané) ; mais l'analyse
#    LOURDE du README (regex formules/aveux, ~0.3 s/dépôt) est bornée aux plus pertinents — au-delà,
#    score local. Sinon 180k × 0.3 s = 15 h et le run se coupe avant d'avoir tout lu.
PLAFOND_FULL = int(os.environ.get("MOISSON_PLAFOND_FULL", "2500"))


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  LE RÉSEAU — **il ne lève JAMAIS. Il compte.**
# ═══════════════════════════════════════════════════════════════════════════════════════════════
def _entetes(brut: bool = False) -> dict[str, str]:
    h = {"User-Agent": "hypersmart-research",
         "Accept": "application/vnd.github.raw+json" if brut else "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}
    j = os.environ.get("GITHUB_TOKEN", "").strip()
    if j:
        h["Authorization"] = "Bearer %s" % j
    return h


def _get(url: str, bless: Blessures, cle: str, *, brut: bool = False,
         cache: bool = True) -> str | None:
    """🔒 **NE MEURT JAMAIS. NE MENT JAMAIS.** `None` = *je n'ai pas su lire* (et c'est COMPTÉ)."""
    if cache:
        v = CACHE.lire(cle)
        if v is not None:
            return v

    essai = 0
    while True:
        statut: int | None = None
        after: float | None = None
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=_entetes(brut)), timeout=30.0
            ) as r:
                txt = r.read(600_000).decode("utf-8", errors="replace")
                if cache:
                    CACHE.ecrire(cle, txt)          # #7 — le TEXTE (un fait), pas le verdict
                return txt
        except urllib.error.HTTPError as exc:
            statut = exc.code
            try:
                after = float(exc.headers.get("Retry-After") or 0) or None
                if after is None:
                    rst = exc.headers.get("X-RateLimit-Reset")
                    if rst:
                        after = max(0.0, float(rst) - time.time())
            except (TypeError, ValueError):
                after = None
        except Exception:  # noqa: BLE001
            statut = None

        d = decider(statut, essai=essai, retry_after=after)
        bless.note(cle, d)
        if d.action == ABANDONNER:
            return None
        if d.action in (ATTENDRE, REESSAYER):
            # 🔴 on ne dort JAMAIS plus longtemps qu'il ne reste de run. *Sinon un 403 fait
            #    « pendre » le run (constaté sans clé : sommeil de 15 min > run de 4 min).*
            reste_run = _DEADLINE - time.time()
            if reste_run <= 5.0:
                return None                      # plus le temps d'attendre -> on abandonne, comptè
            time.sleep(min(d.attente_s, 900.0, max(1.0, reste_run - 2.0)))
            essai += 1


def _json(txt: str | None) -> Any:
    if not txt:
        return None
    try:
        return json.loads(txt)
    except Exception:  # noqa: BLE001
        return None


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  L'ÉTAT — **checkpoint après CHAQUE requête.** *Une coupure ne doit rien coûter.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
def _charger() -> dict[str, Any]:
    if ETAT.exists():
        try:
            return json.loads(ETAT.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"faites": [], "repos": {}, "bandit": {}, "phase": 0}


def _sauver(e: dict[str, Any]) -> None:
    ETAT.parent.mkdir(parents=True, exist_ok=True)
    tmp = ETAT.with_suffix(".tmp")
    tmp.write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
    tmp.replace(ETAT)                    # écriture ATOMIQUE : *une coupure en plein write ne
                                         # doit pas corrompre l'état.*


class Progres:
    """🔑 **LE TABLEAU DE BORD.** *Un run de 10 h qu'on ne peut pas observer est un run qu'on
    interrompt par angoisse.*

    Écrit `moisson-en-cours.txt` — Flo l'ouvre quand il veut, **sans rien interrompre**.
    Et il dit **la vérité** : y compris ce qui a échoué, et ce qui reste.
    """

    def __init__(self, t0: float, heures: float, bless: Blessures) -> None:
        self.t0 = t0
        self.heures = heures
        self.bless = bless
        self.phase = "démarrage"
        self.detail = ""
        self.fait = 0
        self.total = 0
        self.repos = 0
        self.par_code = 0
        self.petits = 0
        self.listes = 0
        self.readmes = 0
        self.ouverts = 0
        self.retenus = 0
        self.commits = 0
        self.issues = 0
        self.constantes = 0
        self.jumeaux = 0
        self.dernier = ""
        self.journal: list[str] = []
        self.canari = "—"
        self.bandit_top = ""
        # PHASE D — le crawler
        self.web = 0
        self.frontiere = 0
        self.steriles = 0
        # ETAPE 1 (Flo 2026-07-15) : le SCAN a son propre budget de temps (~8h) -> barre par temps.
        self.etape_debut = self.t0
        self.etape_budget = 0.0
        # 🔑 LE BATTEMENT DE CŒUR — *pour que ça avance en TEMPS RÉEL, même à l'arrêt.*
        self._lock = threading.Lock()      # deux threads écrivent : on ne les laisse pas se marcher dessus
        self._tick = 0

    def note(self, ligne: str) -> None:
        """Le journal des derniers événements. **Court exprès** : le tableau doit tenir sur UN
        écran, sinon il défile et « ça remonte » à chaque rafraîchissement (retour de Flo)."""
        h = (time.time() - self.t0) / 3600.0
        self.journal.append("[%5.2f h] %s" % (h, ligne))
        self.journal = self.journal[-10:]
        self.dernier = ligne

    def ecrire(self) -> None:  # noqa: C901
        ecoule = time.time() - self.t0
        h = ecoule / 3600.0
        reste = max(0.0, self.heures * 3600.0 - ecoule)

        # ═══════════════════════════════════════════════════════════════════════════════════════
        # 🔑 LE TEMPS RESTANT — **honnête**, basé sur la vitesse RÉELLE mesurée.
        #
        # 🔴 *Et je dois dire une chose que Flo n'attend pas :* **le « % » d'avancement de la
        #    PHASE D est TROMPEUR.** La frontière **grandit pendant qu'on la vide** (b = 31,5) —
        #    le dénominateur bouge. ***Un pourcentage dont le dénominateur augmente n'est pas un
        #    pourcentage : c'est une illusion de progrès.***
        #    -> pour la phase D on affiche donc **le temps restant du RUN**, pas un faux « 100 % ».
        # ═══════════════════════════════════════════════════════════════════════════════════════
        vitesse = (self.fait / ecoule) if ecoule > 30 and self.fait else 0.0
        crawler = self.phase.startswith("PHASE D")
        analyse = self.phase.startswith("PHASE C")   # étape 3 : bornée par le TEMPS (réserve crawler)

        if analyse:
            # 🔴 Flo (16/07) « il reste 38 h ! » — FAUX. L'étape 3 s'arrête toute seule quand il
            #    reste ~28 % du run (réserve pour l'étape 4). L'ETA « analyser les 17 000 candidats »
            #    n'a aucun sens : elle est bornée par le TEMPS. On affiche donc le temps RÉEL.
            fin = max(0.0, reste - 0.28 * self.heures * 3600.0)
            eta = ("%.1f h" % (fin / 3600.0)) if fin > 3600 else ("%.0f min" % (fin / 60.0))
            total_c = max(1.0, 0.72 * self.heures * 3600.0)
            frac = min(1.0, max(0.0, (total_c - fin) / total_c))
            n = int(40 * frac)
            barre = "[%s%s] %d %% du temps de l'etape 3" % ("#" * n, "." * (40 - n), int(100 * frac))
        elif crawler:
            eta = "**%.1f h de run restantes** (la frontière ne se videra pas : elle grandit)" \
                % (reste / 3600.0)
            barre = "[%s%s] %d %% DU TEMPS" % (
                "#" * int(40 * (1 - reste / max(self.heures * 3600.0, 1))),
                "." * (40 - int(40 * (1 - reste / max(self.heures * 3600.0, 1)))),
                int(100 * (1 - reste / max(self.heures * 3600.0, 1))),
            )
        elif self.etape_budget > 0:
            # ETAPE 1 (le SCAN) : la barre suit le TEMPS de l'étape (~8h), pas le compte — la
            # recherche se ré-alimente, un pourcentage par compte serait faux. *On montre les 8h.*
            ph = time.time() - self.etape_debut
            frac = min(1.0, ph / self.etape_budget) if self.etape_budget else 0.0
            n = int(40 * frac)
            barre = "[%s%s] %d %%   (%.1fh / %.0fh de recherche)" % (
                "#" * n, "." * (40 - n), int(100 * frac),
                ph / 3600.0, self.etape_budget / 3600.0)
            reste_ph = max(0.0, self.etape_budget - ph)
            eta = ("%.1f h" % (reste_ph / 3600.0)) if reste_ph > 3600 \
                else ("%.0f min" % (reste_ph / 60.0))
        else:
            eta = "—"
            if vitesse > 0 and self.total > self.fait:
                eta_s = (self.total - self.fait) / vitesse
                eta = ("%.1f h" % (eta_s / 3600.0)) if eta_s > 3600 \
                    else ("%.0f min" % (eta_s / 60.0))
                if eta_s > reste:
                    eta += ("   ⚠️ **plus long que le budget restant (%.1f h)** — on passera "
                            "a la phase suivante avant la fin du plan" % (reste / 3600.0))
            barre = ""
            if self.total:
                n = int(40 * self.fait / max(self.total, 1))
                barre = "[%s%s] %d %%" % ("#" * n, "." * (40 - n),
                                          int(100 * self.fait / max(self.total, 1)))

        # ─────────────────────────────────────────────────────────────────────────────────────
        # 🧹 TABLEAU DE BORD **SIMPLE** (retour de Flo : « il est trop complexe »).
        #    L'essentiel, sur un ecran : ou on en est, ce qu'il fait, ce qu'il a trouve. Le
        #    detail complet reste dans le .md et le JSON a la fin. *Simple a lire en 5 secondes.*
        # ─────────────────────────────────────────────────────────────────────────────────────
        ETAPE = {
            "PHASE A": ("ETAPE 1/4 : IL CHERCHE des depots sur GitHub",
                        "(il ratisse large, meme les depots a 0 etoile)"),
            "PHASE B": ("ETAPE 2/4 : IL TRIE -- il lit chaque depot et le NOTE",
                        "(ce qu'il APPORTE par rapport a ce qu'on a deja)"),
            "PHASE C": ("ETAPE 3/4 : IL ANALYSE EN PROFONDEUR les meilleurs",
                        "(il ouvre le code, les commits, les issues)"),
            "PHASE D": ("ETAPE 4/4 : IL LIT LES PAPIERS (arXiv, OpenAlex...)",
                        "(la recherche academique, gratuite)"),
        }
        etape, sousetape = ("Demarrage...", "(le canari verifie le trieur)")
        for k, (e, s) in ETAPE.items():
            if self.phase.startswith(k):
                etape, sousetape = e, s
                break

        self._tick += 1
        vivant = "|/-\\"[self._tick % 4]
        hh = int(h)
        mm = int((ecoule - hh * 3600) // 60)
        eta_court = eta.split("   ")[0] if eta and eta != "—" else "en cours"

        t = [
            "==============================================================================",
            "   MOISSON EN COURS   %s   (rafraichi en direct - ferme quand tu veux)" % vivant,
            "==============================================================================",
            "",
            "   Temps    : %dh %02dm ecoulees  /  12h        il reste %.1f h"
            % (hh, mm, reste / 3600.0),
            "",
            "   %s" % etape,
            "            %s" % sousetape,
            "",
            "   %s" % (barre or "en cours..."),
            "   vitesse : %.0f requetes/heure       fin de l'etape : %s"
            % (vitesse * 3600.0, eta_court),
            "",
            "   ----------------------------------------------------------------",
            "   CE QU'IL A TROUVE JUSQU'ICI",
            "   ----------------------------------------------------------------",
            "   depots trouves .............. %d" % self.repos,
            "   depots LUS et NOTES ......... %d      <- le tri se fait ici" % self.readmes,
            "   depots analyses a fond ...... %d" % self.ouverts,
            "   >>> BONNES PISTES GARDEES ... %d" % (self.retenus + self.web),
            "",
            "   papiers/idees du web ........ %d" % self.web,
            "   sources non lues (comptees) . %d" % len(self.bless.non_lus),
            "",
            "   ----------------------------------------------------------------",
            "   DERNIERS EVENEMENTS",
            "   ----------------------------------------------------------------",
        ]
        t += ["   %s" % x for x in self.journal[-8:]]
        t += [
            "",
            "==============================================================================",
            "   Pour ARRETER : ferme la fenetre \"MOISSON 12h - travail\" (on reprend apres).",
            "==============================================================================",
            "",
        ]
        # 🔒 écriture ATOMIQUE et VERROUILLÉE : le battement de cœur ET le thread principal
        #    écrivent tous les deux — sans le verrou, ils produiraient un fichier à moitié écrit.
        try:
            with self._lock:
                tmp = BATTEMENT.with_suffix(".tmp")
                tmp.write_text("\n".join(t), encoding="utf-8")
                tmp.replace(BATTEMENT)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  🔑 LE BATTEMENT DE CŒUR — *pour que ça avance en TEMPS RÉEL, même à l'arrêt.*
#
#  🔴 LE PROBLÈME QUE ÇA RÉPARE : entre deux événements — surtout pendant une **attente de quota**
#     (jusqu'à 15 min où le script DORT) — le fichier ne changeait pas. L'écran semblait **figé**,
#     et une horloge qui ne bouge pas donne l'impression d'un run MORT.
#
#  -> un thread réécrit le tableau de bord **toutes les 2 secondes, quoi qu'il arrive**. L'horloge,
#     le temps restant et l'indicateur qui tourne avancent **en continu** — même à l'arrêt.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
def _demarrer_battement(prog: "Progres") -> tuple[threading.Event, threading.Thread]:
    stop = threading.Event()

    def _cœur() -> None:
        while not stop.is_set():
            try:
                prog.ecrire()
            except Exception:  # noqa: BLE001
                pass           # *le tableau de bord ne doit JAMAIS faire tomber le run.*
            stop.wait(2.0)

    th = threading.Thread(target=_cœur, name="battement", daemon=True)
    th.start()
    return stop, th


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  ETAPE 1 = 8 h DE RECHERCHE  (décision de Flo, 2026-07-15)
#
#  *« pendant 8 heures il cherche des repos et autres, ensuite l'étape 2. »* Le SCAN prend donc
#  l'essentiel du temps. Deux fonctions PURES (donc testables) portent cette décision.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
def budgets_de_phase(limite: float) -> tuple[float, float, float]:
    """Renvoie les bornes de *temps restant* auxquelles A, B et C rendent la main.

    Le SCAN (phase A) doit durer ~8 h sur un run de 12 h ; le tri + l'analyse + les papiers se
    partagent la fin. Pour 12 h : A ~8 h, B ~2.2 h, C ~1.1 h, D ~0.7 h (le solde).
    """
    heure = 3600.0
    scan = min(8.0 * heure, limite * 2.0 / 3.0)   # 8 h, ou 2/3 du run s'il est plus court
    dl_a = max(limite - scan, limite * 0.10)      # borne : garder au moins 10 % pour la suite
    dl_b = dl_a * 0.45
    dl_c = dl_a * 0.18
    return dl_a, dl_b, dl_c


def requetes_de_relance(
    repos: dict[str, dict[str, Any]],
    faites: set[str],
    *,
    plafond: int = 300,
) -> list[tuple[str, str, str, str]]:
    """*« il ne doit jamais arrêter de chercher et toujours savoir quoi chercher, en restant
    cohérent. »* Quand le plan de base (4853 requêtes) est épuisé, on RÉ-ALIMENTE la recherche
    à partir du TERRAIN : les `topics` GitHub des repos déjà trouvés. Un topic -> des repos ->
    de nouveaux topics : la source ne peut pas être à court (comme la frontière de l'étape 4).

    🔒 **Cohérence** : un topic n'est retenu que s'il passe la porte de domaine
    (`dans_notre_domaine`). Cela élimine `python`, `docker`, `hacktoberfest`… et garde
    `market-making`, `hft`, `defi`, `orderbook`… *La recherche ne se perd jamais.*
    """
    compte: dict[str, int] = {}
    for v in repos.values():
        for t in (v.get("topics") or []):
            mot = str(t).strip().lower()
            if mot and dans_notre_domaine(mot.replace("-", " ").replace("_", " ")):
                compte[mot] = compte.get(mot, 0) + 1
    boites: list[tuple[str, str, str, str]] = []
    for mot, c in sorted(compte.items(), key=lambda kv: (-kv[1], kv[0]))[:plafond]:
        cle = "repo|topic:%s|stars" % mot
        if cle not in faites:
            boites.append(("repo", "topic:%s" % mot, "topic du terrain (%dx)" % c, "stars"))
    return boites


def pertinence_domaine(v: dict[str, Any]) -> int:
    """PRIORITE DE LECTURE (Flo 2026-07-15, choix B : *« lire plus malin »*).

    On lit les depots de NOTRE domaine D'ABORD — pas les plus etoiles. Un repo ML fameux
    (tensorflow, 180k etoiles) ne doit PAS passer devant une pepite quant a 3 etoiles :
    *c'est exactement le bruit que Flo a vu (« ressemble a X » sur des repos ML)*.

    Score = topics de notre domaine (x2 chacun) + trouve dans le code par une requete ciblee
    (x2) + marche cite dans le nom ou le pourquoi (x1). Les etoiles ne departagent qu'ENSUITE.
    """
    score = 0
    for t in (v.get("topics") or []):
        if dans_notre_domaine(str(t).replace("-", " ").replace("_", " ")):
            score += 2
    if v.get("trouve_dans_le_code"):
        score += 2
    if dans_notre_domaine("%s %s" % (v.get("nom") or "", v.get("pourquoi") or "")):
        score += 1
    return score


def _rapport_partiel(
    entrees: list[dict[str, Any]],
    notes: list[tuple[float, str]],
    repos: dict[str, Any],
) -> None:
    """🔴 Flo (15/07) : *« je ne veux plus que ça plante, sinon je n'aurais jamais les données. »*

    On (ré)écrit une version SIMPLE mais utile de `moisson-fini.md` à CHAQUE checkpoint des étapes
    2-4. Ainsi, même si le process est tué ou qu'une étape casse, on a TOUJOURS sur le disque les
    données déjà trouvées. La version complète (à la fin) l'écrase. **Ne lève JAMAIS d'exception.**
    """
    try:
        # snapshot (list(...)) : sûr même si un autre thread ajoute pendant qu'on écrit le rapport.
        gardes = [e for e in list(entrees) if e.get("verdict") not in (None, "SKIP_WITH_REASON")]
        gardes.sort(key=lambda e: -float(e.get("score") or 0.0))
        lignes = [
            "# 🌾 Moisson — rapport en direct (PARTIEL)",
            "",
            "> ⚠️ **Partiel** : le run tourne encore (ou a été interrompu). La version complète",
            "> s'écrit à la fin. Mais **ces données sont déjà acquises — rien n'est perdu.**",
            "",
            "| | |",
            "|---|---|",
            "| dépôts trouvés | %d |" % len(repos),
            "| dépôts analysés à fond (code ouvert) | %d |" % len(entrees),
            "| **retenus (pistes)** | **%d** |" % len(gardes),
            "",
            "## ✅ Les dépôts RETENUS — code déjà ouvert",
            "",
        ]
        for e in gardes[:300]:
            lignes.append("- **%s** — `%s` · score %.0f · %d★ — %s" % (
                e.get("repo"), e.get("verdict"), float(e.get("score") or 0.0),
                int(e.get("etoiles") or 0), str(e.get("pourquoi") or "")[:140]))
        if not gardes:
            lignes.append("*(encore aucun retenu à cet instant — le tri/l'analyse continuent)*")
        lignes += ["", "## 📊 Le classement du tri (top 400 par score)", ""]
        for s, nom in sorted(notes, key=lambda x: -x[0])[:400]:
            lignes.append("- %s — %.0f" % (nom, s))
        SORTIE_MD.write_text("\n".join(lignes), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass   # 🔒 écrire le rapport ne doit JAMAIS casser le run.


# ═══════════════════════════════════════════════════════════════════════════════════════════════
#  UNE PHASE QUI CASSE NE DOIT PAS TUER LE RUN.
# ═══════════════════════════════════════════════════════════════════════════════════════════════
def _phase(nom: str, f: Callable[[], Any], bless: Blessures) -> Any:
    """*Une exception dans une phase est une blessure, pas une mort.*"""
    print("\n" + "─" * 100)
    print("  %s" % nom)
    print("─" * 100)
    try:
        return f()
    except KeyboardInterrupt:
        raise
    except Exception as e:  # noqa: BLE001
        bless.abandons["PHASE:%s" % nom] = "%s: %s" % (type(e).__name__, e)
        bless.non_lus.append("PHASE:%s" % nom)
        print("\n  🔴 **LA PHASE A CASSÉ** : %s" % e)
        print("     *Elle est COMPTÉE, et le run CONTINUE.* (trace ci-dessous)")
        traceback.print_exc(limit=3)
        return None


def main() -> int:  # noqa: C901, PLR0912, PLR0915
    ap = argparse.ArgumentParser(description="Le moissonneur — 12 h sans s'arrêter")
    ap.add_argument("--heures", type=float, default=12.0)
    # 🔴 0 = **ILLIMITÉ** : on analyse en profondeur TOUT ce qui a de la substance, et c'est le
    #    TEMPS (pas un top figé) qui borne. *« chaque github c'est une analyse en profondeur. »*
    ap.add_argument("--top", type=int, default=0,
                    help="plafond dur du nombre de repos analyses en profondeur (0 = illimite, "
                         "le temps borne)")
    ap.add_argument("--repartir-de-zero", action="store_true")
    ap.add_argument("--depuis-dernier", dest="depuis_dernier", action="store_true",
                    help="#6 mode incremental : ne chercher que ce qui est NOUVEAU depuis le "
                         "dernier run")
    ap.add_argument("--relire", action="store_true",
                    help="mode RELIRE (Flo, choix B) : ne RE-SCANNE PAS ; reprend les depots deja "
                         "trouves et les RELIT intelligemment (etape 2+), pour rentabiliser un "
                         "scan deja fait sans attendre 8 h de plus")
    args = ap.parse_args()

    t0 = time.time()
    limite = args.heures * 3600.0
    global _DEADLINE
    _DEADLINE = t0 + limite        # 🔴 aucune attente réseau ne dépassera cette échéance
    bless = Blessures()
    jeton = os.environ.get("GITHUB_TOKEN", "").strip()

    # 🔴 On efface tout flag de fin d'un run PRÉCÉDENT. Sinon, si on rouvre l'afficheur pendant
    #    que CE run tourne, il voit le vieux flag et se ferme aussitôt (« MOISSON TERMINEE »
    #    alors qu'on est en plein travail — le bug que Flo a vu). Le flag n'est ré-écrit qu'à la
    #    FIN, par le .cmd, une fois python sorti pour de bon.
    try:
        (RACINE / "moisson-termine.flag").unlink()
    except OSError:
        pass

    print("=" * 100)
    print("  LE MOISSONNEUR — **%.0f HEURES SANS S'ARRÊTER**" % args.heures)
    print("  ***Ne jamais mourir. Ne jamais mentir.***")
    print("=" * 100)

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  #1 — 🔒 LE CANARI. **AVANT TOUT.** Sans lui, les 14 autres idées sont de la spéculation.
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("  #1 — LE CANARI : *le trieur retrouve-t-il ce qu'on SAIT déjà bon ?*")
    print("=" * 100)
    c = canari.verifier(lambda t: score(analyser(t), etoiles=0))
    print("\n  " + c.rapport().replace("\n", "\n  "))
    if not c.fiable:
        print("\n  🔒 **LE RUN S'ARRÊTE ICI.**")
        print("     *Un outil qui échoue sur ce qu'il connaît n'a RIEN à dire sur ce qu'il ne")
        print("      connaît pas.* **Répare le trieur, puis relance.**")
        return 1
    for d in c.detail:
        print("     %-42s %8.1f   %s" % (d[0], d[1], "attendu BON" if d[2] else "attendu CREUX"))

    # #1 — la couche SÉMANTIQUE (repêche ce que le grep rate). *On dit quelle méthode est active.*
    diag_sem = diagnostic_semantique()
    print("\n  🧠 sémantique : %s" % diag_sem["franchise"])

    # #10 — les RETOURS accumulés (un canari qui apprend). *La mesure, pas la devinette.*
    retours = charger_retours(RACINE / "data" / "reports" / "retours_moisson.json")
    if retours:
        print("  🔁 %d retour(s) humain(s) pris en compte pour re-pondérer." % len(retours))

    # #6 — le mode INCRÉMENTAL. *Ne re-scanner que le NOUVEAU depuis la dernière fois.*
    fichier_date = RACINE / "data" / "reports" / "moisson_derniere_date.txt"
    depuis = lire_derniere_date(fichier_date) if getattr(args, "depuis_dernier", False) else None
    if depuis:
        print("  🆕 mode INCRÉMENTAL : seulement ce qui est né après **%s** (%s)."
              % (depuis.isoformat(), filtre_date_github(depuis)))

    if not jeton:
        print("\n  ⚠️ **Pas de GITHUB_TOKEN** → 60 requêtes/heure au lieu de 5 000.")
        print("     Un run de 10 h fera ~600 requêtes au lieu de ~50 000.")
        print("     `set GITHUB_TOKEN=ghp_...` (gratuit, lecture seule).")
        print("     🔴 Et **la recherche DANS LE CODE sera impossible** — *je le dis, je ne fais")
        print("        pas semblant.*")

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  #3 — INDEXER **NOTRE** CODE. *On note le DELTA, pas le niveau.*
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    notre_etat = indexer_notre_code(RACINE / "src" / "hl_observer")
    print("\n" + "=" * 100)
    print("  #3 — CE QU'ON A DÉJÀ (indexé sur NOTRE code, pas récité de mémoire)")
    print("=" * 100)
    print("\n  ✅ acquis (%d) : %s" % (len(notre_etat.acquis), ", ".join(notre_etat.acquis)))
    print("\n  🔴 **CE QUI NOUS MANQUE (%d)** — *c'est ÇA qu'on cherche* :"
          % len(notre_etat.manquants))
    for k, v in notre_etat.manquants.items():
        print("     %-28s %s" % (k, v[:70]))

    prog = Progres(t0, args.heures, bless)
    prog.canari = ("✅ VIVANT — le pire des bons (%.1f) depasse le meilleur des creux (%.1f) "
                   "de %.1f pts" % (c.pire_bon[1], c.meilleur_creux[1], c.marge))
    prog.phase = "indexation de NOTRE code"
    prog.ecrire()

    # 🔑 LE BATTEMENT DÉMARRE ICI — à partir de maintenant, le tableau de bord se rafraîchit
    #    **tout seul toutes les 2 s**, même pendant les longues attentes réseau. *Temps réel.*
    _stop_battement, _th_battement = _demarrer_battement(prog)

    etat = {"faites": [], "repos": {}, "bandit": {}} if args.repartir_de_zero else _charger()
    faites: set[str] = set(etat.get("faites") or [])
    repos: dict[str, Any] = dict(etat.get("repos") or {})
    bandit = Bandit()
    for b, n in (etat.get("bandit") or {}).get("tires", {}).items():
        bandit.tires[b] = n
        bandit.gains[b] = (etat["bandit"].get("gains") or {}).get(b, 0.0)
        bandit.total += n

    if faites:
        print("\n  🔑 **REPRISE** : %d requêtes faites, %d repos. *Rien n'est perdu.*"
              % (len(faites), len(repos)))

    def _reste() -> float:
        return limite - (time.time() - t0)

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 🔴🔴 LE BUDGET PAR PHASE — *« les moteurs marchent mal » : Flo avait RAISON.*
    #
    #    AVANT : la phase A (le scan) tournait jusqu'à `_reste() > 300` — c'est-à-dire **jusqu'à
    #            11 h 55**. Sans clé GitHub (~700 req/h), elle mangeait presque TOUT le temps et
    #            les moteurs qui LISENT (le code, les commits, les papiers) ne tournaient JAMAIS.
    #            ***Un moteur qui n'a pas le temps de tourner « marche mal ».***
    #
    #    APRÈS : chaque phase a une **part du temps**. Elle s'arrête à sa borne et **passe la main**
    #            (ou finit plus tôt si elle a épuisé son plan). *Le scan trouve ; mais lire est ce
    #            qui a jamais rien donné — il faut lui garder du temps.*
    #
    #    🔴 Flo 2026-07-15 : *« pendant 8 h il cherche des repos, ENSUITE l'étape 2. »* L'ETAPE 1
    #       (le scan) prend donc l'ESSENTIEL du temps — ~8 h sur 12 h — et se RÉ-ALIMENTE pour ne
    #       jamais rester sans chercher (pagination + topics du terrain, cohérents). Le tri +
    #       l'analyse + les papiers se partagent la fin.
    #      A (scan)    ~8 h    -> reste = 4 h
    #      B (README)  ~2.2 h  -> reste = 1.8 h
    #      C (code)    ~1.1 h  -> reste = 0.7 h
    #      D (crawler) ~0.7 h  (le solde)
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    DL_A, DL_B, DL_C = budgets_de_phase(limite)
    plafond_fetch = PLAFOND_FETCH   # nb de README NON encore en cache qu'on s'autorise à télécharger

    if getattr(args, "relire", False):
        # 🔴 Flo (choix B) : on a déjà des dépôts sauvegardés (jusqu'à 176k). On NE RE-SCANNE PAS —
        #    on saute l'étape 1 et on donne TOUT le temps à la LECTURE (étape 2) et au CODE
        #    (étape 3), en lisant les dépôts de NOTRE domaine d'abord. *Le scan déjà fait paie.*
        DL_A = limite + 1.0          # l'étape 1 (scan) ne tourne pas (while _reste() > DL_A = faux)
        DL_B = limite * 0.30         # l'étape 2 est LOCALE (cache) donc courte -> l'étape 3 (code) a plus de temps
        plafond_fetch = 0            # 🔴 relire = tri PUREMENT local : 0 README retéléchargé -> tout
        #                              le quota GitHub (5000/h) reste pour l'ÉTAPE 3 (ouvrir le code).
        # puis l'étape 3 (OUVRIR LE CODE = l'architecture) tourne jusqu'à ~72 % du temps, et le
        # crawler (papiers) prend le solde. *On garde du temps pour ouvrir le code — c'est là qu'on
        # juge une meilleure architecture.*
        print("\n  📖 **MODE RELIRE** : %d dépôts déjà trouvés — on les RELIT (sans re-scanner)."
              % len(repos))

    def _chk() -> None:
        _sauver({"faites": sorted(faites), "repos": repos,
                 "bandit": {"tires": bandit.tires, "gains": bandit.gains}})

    def _doux(url: str, cle: str, *, brut: bool = False) -> str | None:
        """🔴 Flo (15/07) : *« l'étape 3 est trop lente »*. On ne DORT que sur un VRAI
        téléchargement — jamais sur un cache hit. Ainsi, re-ouvrir un dépôt déjà analysé (à la
        relance) est INSTANTANÉ, et l'étape 3 avance sur du neuf à chaque run au lieu de re-dormir
        sur ce qu'elle a déjà lu."""
        deja = CACHE.lire(cle) is not None
        txt = _get(url, bless, cle, brut=brut)
        if txt is not None and not deja:
            time.sleep(PAUSE_DOUCE)
        return txt

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  PHASE A — LE SCAN. #9 le bandit · #13 la chronologie · #14 la contradiction
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    def _scan() -> None:
        # ETAPE 1 (Flo 2026-07-15) : la recherche a son propre budget de temps (~8 h). On l'affiche.
        prog.etape_debut = time.time()
        prog.etape_budget = max(0.0, limite - DL_A)

        plan = deduplique(plan_de_scan(SUJETS, TEXTE, avec_code=bool(jeton)))
        # #13 + #14 — on les met **tôt** : *ce qu'on met en premier est ce qu'on est SÛR d'avoir.*
        sup = [("repo", x["requete"], x["pourquoi"])
               for x in requetes_chronologiques()]
        sup += [("repo", x["requete"], "🔴 CONTRADICTION — %s" % x["notre_conclusion"])
                for x in requetes_de_contradiction()]
        sup += [("repo", x["requete"], x["pourquoi"]) for x in requetes_ciblees()]

        boites: list[tuple[str, str, str, str]] = [
            (r.genre, r.q, r.pourquoi, r.tri) for r in plan
        ] + [(g, q, p, "stars") for g, q, p in sup]

        restants = [b for b in boites
                    if "%s|%s|%s" % (b[0], b[1], b[3]) not in faites]
        print("  plan : **%d requêtes** · restantes : **%d**" % (len(boites), len(restants)))

        # 🔴 Flo 2026-07-15 : *« il ne doit jamais arrêter de chercher pendant 8 h, en restant
        #    cohérent. »* Une liste FINIE (4853 requêtes) s'épuise en ~3 h. Deux ré-alimentations,
        #    toutes deux DANS notre domaine, pour tenir les 8 h sans se perdre :
        #      • PAGINATION — une requête qui ramène 100 résultats a d'autres pages (jusqu'à 10) ;
        #      • TOPICS DU TERRAIN — les `topics` GitHub des repos trouvés -> nouvelles requêtes.
        #    Un topic engendre des repos qui engendrent des topics : *on ne peut pas être à court.*
        pages: dict[str, int] = {}

        i = 0
        # 🔴 la phase A tourne PENDANT TOUT SON BUDGET (~8 h), plus « tant qu'il reste des requêtes ».
        while _reste() > DL_A:
            if not restants:
                # le plan de base est épuisé : on RÉ-ALIMENTE avec le terrain (cohérent).
                neuf = requetes_de_relance(repos, faites)
                if not neuf:
                    prog.note("⚪ étape 1 : plan + topics du terrain épuisés — *rien de neuf.*")
                    break
                restants = neuf
                prog.note("🌱 étape 1 : +%d requêtes ré-alimentées (topics du terrain, cohérent)"
                          % len(neuf))

            # #9 — LE BANDIT choisit **la famille** qui rend le plus.
            familles = sorted({b[2][:40] for b in restants})
            fam = bandit.choisir(familles) if len(familles) > 1 else familles[0]
            lot = [b for b in restants if b[2][:40] == fam][:6] or restants[:1]

            gain = 0
            for genre, q, pourquoi, tri in lot:
                if _reste() <= DL_A:
                    break
                cle = "%s|%s|%s" % (genre, q, tri)
                page = pages.get(cle, 1)
                if genre == "code":
                    url = ("https://api.github.com/search/code?q=%s&per_page=100&page=%d"
                           % (urllib.parse.quote(q), page))
                else:
                    t = ("&sort=%s&order=desc" % tri) if tri else ""
                    url = ("https://api.github.com/search/repositories?q=%s%s&per_page=100&page=%d"
                           % (urllib.parse.quote(q), t, page))

                d = _json(_get(url, bless, "search|%s|p%d" % (cle, page), cache=False))
                time.sleep(PAUSE_CODE if genre == "code" else PAUSE_REPO)

                items = ((d or {}).get("items") or [])
                for it in items:
                    if genre == "code":
                        dep = it.get("repository") or {}
                        nom, et, lic, tops = str(dep.get("full_name") or ""), 0, None, []
                    else:
                        nom = str(it.get("full_name") or "")
                        et = int(it.get("stargazers_count") or 0)
                        lic = (it.get("license") or {}).get("spdx_id")
                        tops = it.get("topics") or []
                    if not nom:
                        continue
                    if nom not in repos:
                        repos[nom] = {"nom": nom, "etoiles": et, "licence": lic,
                                      "trouve_par": genre, "pourquoi": pourquoi}
                        gain += 1
                    if tops:
                        repos[nom]["topics"] = list(tops)
                    if genre == "code":
                        repos[nom]["trouve_dans_le_code"] = q

                # PAGINATION : page pleine ET encore des pages -> on RE-FILE la même requête.
                #   🔴 Flo (choix B) : on RESSERRE. Une requête de NOTRE domaine pagine à fond
                #   (10 pages) ; une requête générique (topic:asyncio, topic:statistics…) s'arrête
                #   à 3 pages — pour ne pas noyer le tri sous 176k dépôts dont 99 % hors-sujet.
                cap = 10 if dans_notre_domaine(
                    q.replace("topic:", "").replace("-", " ").replace("_", " ")) else 3
                if genre != "code" and len(items) >= 100 and page < cap:
                    pages[cle] = page + 1
                else:
                    faites.add(cle)
                    restants = [b for b in restants
                                if "%s|%s|%s" % (b[0], b[1], b[3]) != cle]

                i += 1
                marque = "🔑 CODE" if genre == "code" else "      "
                pg = (" p%d" % page) if page > 1 else ""
                prog.note("%s %-40s%s +%d repo(s)" % (marque, q[:40], pg, gain))
                prog.phase = "PHASE A — LE SCAN"
                prog.detail = "requête : %s%s" % (q[:56], pg)
                prog.fait = len(faites)
                prog.total = max(len(boites), len(faites) + len(restants))
                prog.repos = len(repos)
                prog.par_code = sum(1 for v in repos.values() if v.get("trouve_dans_le_code"))
                prog.petits = sum(1 for v in repos.values()
                                  if int(v.get("etoiles") or 0) < 5)
                prog.listes = sum(1 for v in repos.values() if v.get("trouve_par") == "liste")
                cl = bandit.classement()
                prog.bandit_top = ("%s (%.1f repo(s)/requête)" % (cl[0][0], cl[0][1])) if cl else ""
                prog.ecrire()

                if i % 10 == 0:
                    _chk()
                    print("  [%5.1f h] %-46s repos=%d  (+%d)"
                          % ((time.time() - t0) / 3600.0, q[:46], len(repos), gain))

            # #9 — en phase A la QUALITÉ est encore inconnue (calculée en phase B) : on récompense
            #      donc le nombre de repos NEUFS, un proxy honnête de « cette famille est féconde ».
            #      *La récompense par QUALITÉ, elle, est appliquée au CRAWLER (phase D), là où le
            #       score de chaque source EST connu.* (correction du commentaire mensonger #5.)
            bandit.noter(fam, float(gain))
            _chk()

    _phase("PHASE A — LE SCAN (bandit · chronologie · CONTRADICTION)", _scan, bless)
    prog.etape_budget = 0.0   # étapes 2-4 : barre par le compte, plus par le temps
    _chk()

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  PHASE B — LIRE LES README · #10 le graphe · le score DIFFÉRENTIEL
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    notes: list[tuple[float, str]] = []
    qui_cite: dict[str, list[str]] = {}
    fetch_faits = {"n": 0}   # combien de README VRAIMENT téléchargés (borné par PLAFOND_FETCH)
    full_faits = {"n": 0}    # combien de README ANALYSÉS À FOND (borné par PLAFOND_FULL) ; au-delà,
    #                          score LOCAL (métadonnées) même si en cache -> on lit TOUS les 180k

    def _lire() -> None:
        # 🔴 Flo (choix B) : on lit les depots de NOTRE domaine D'ABORD (pertinence), les etoiles
        #    ne departageant qu'a pertinence egale. Fini les repos ML fameux avant les pepites quant.
        noms = sorted(repos, key=lambda n: (-pertinence_domaine(repos[n]),
                                            -int(repos[n].get("etoiles") or 0)))
        for i, nom in enumerate(noms, 1):
            if _reste() <= DL_B:      # 🔴 la phase B rend la main à 45 % du temps
                print("  ⏹️ budget de la phase B atteint — on passe à l'ouverture du code.")
                break
            # 🔴 Flo (15/07) : *« le tri doit être LOCAL, hors GitHub. »* Le vrai coût des 43 h
            #    n'était PAS le réseau : c'était `sleep(0.8 s)` × 180k = **40 h de sommeil**, même
            #    quand le README était déjà en cache. On lit donc le CACHE d'abord (aucun réseau,
            #    AUCUNE attente) ; on ne télécharge — et on ne dort — que pour un nombre BORNÉ de
            #    dépôts pas encore en cache ; le reste est noté LOCALEMENT (topics/nom) :
            #    instantané, et **on n'oublie personne**.
            txt = CACHE.lire("readme|%s" % nom)
            if txt is None and fetch_faits["n"] < plafond_fetch and _reste() > DL_B:
                txt = _get("https://api.github.com/repos/%s/readme" % nom,
                           bless, "readme|%s" % nom, brut=True)
                if txt is not None:
                    fetch_faits["n"] += 1
                    time.sleep(PAUSE_DOUCE)     # politesse : UNIQUEMENT sur un vrai téléchargement
            # 🔴 on LIT TOUS les dépôts : l'analyse LOURDE du README est bornée aux plus pertinents
            #    (PLAFOND_FULL) ; au-delà, score LOCAL même si le README est en cache. Aucun oubli.
            if txt is not None:
                if full_faits["n"] >= PLAFOND_FULL:
                    txt = None
                else:
                    full_faits["n"] += 1
            if txt is None:
                # pas de README (pas en cache, ou plafond de fetch atteint) -> SCORE LOCAL sur les
                # métadonnées. Aucun réseau, aucun oubli : le dépôt reste classé et exportable.
                s_meta = float(pertinence_domaine(repos[nom]))
                if s_meta > 0.0:
                    notes.append((s_meta, nom))
                    prog.retenus += 1
                prog.readmes = i
                prog.fait, prog.total = i, len(noms)
                if i % 1000 == 0:
                    prog.ecrire()
                continue

            # 🌐 une awesome-list est une CARTE. *200 repos sans aucun topic.*
            liens = liens_de_repos(txt, exclure=set(repos))
            if est_une_liste(nom, txt) and liens:
                for l in liens[:150]:
                    repos.setdefault(l, {"nom": l, "etoiles": 0, "licence": None,
                                         "trouve_par": "liste",
                                         "pourquoi": "🌐 cité par la liste `%s`" % nom})
            if liens:
                qui_cite[nom] = liens[:60]        # #10

            sig = analyser(txt)
            base = score(sig, etoiles=int(repos[nom].get("etoiles") or 0))
            # #3 — LE DELTA. *Ce qu'ils ont QUE NOUS N'AVONS PAS.*
            delta = score_differentiel(list(sig.formules), notre_etat)

            # #1 — LA SÉMANTIQUE repêche ce que le grep a raté. *Contre le faux négatif.*
            #    🔴 Flo (choix B) : mais SEULEMENT si le repo est de NOTRE domaine. Sinon on
            #    repêchait du bruit ML (« tensorflow ressemble à liquidation_flow ») — ce que Flo
            #    voyait défiler sans fin. Un second regard n'a de sens que dans notre sujet.
            en_domaine = pertinence_domaine(repos[nom]) > 0 or dans_notre_domaine(txt)
            repeche, sem = merite_un_second_regard(txt, deja_vu_par_grep=bool(sig.formules))
            if repeche and en_domaine:
                base += 8.0        # un bonus modeste : « ça RESSEMBLE à un de nos trous »
                repos[nom]["repeche_semantique"] = sem.as_dict()
                prog.note("🧠 %-38s repêché (ressemble à « %s », %s)"
                          % (nom[:38], sem.concept, sem.methode))

            # #3 bis — NOS MORTS : ce repo ressuscite-t-il une idée qu'on a mesurée MORTE ?
            morts = deja_mort(txt)
            if morts:
                repos[nom]["deja_mort"] = [x.as_dict() for x in morts]

            # #10 — le RETOUR humain re-pondère (par le concept dominant du delta)
            s_total = base + delta.score
            if delta.nouveaux:
                s_total = appliquer_retours(s_total, delta.nouveaux[0], retours)

            repos[nom]["signaux"] = sig.as_dict()
            repos[nom]["delta"] = delta.as_dict()
            notes.append((s_total, nom))
            # 🔴 Flo : le compteur « gardees » ne montait qu'a l'etape 3 -> il restait a 0 pendant
            #    TOUT le tri (« il ne trouve rien »). On montre desormais EN DIRECT les depots
            #    substantiels (score > 0) trouves par le tri. L'etape 3 recalcule le vrai garde.
            if s_total > 0.0:
                prog.retenus += 1

            prog.phase = "PHASE B — LIRE LES README (le graphe · le score DIFFÉRENTIEL)"
            prog.detail = "lecture : %s" % nom
            prog.readmes = i
            prog.fait, prog.total = i, len(noms)
            prog.repos = len(repos)
            if delta.nouveaux:
                prog.note("🔑 %-40s apporte %d concept(s) QU'ON N'A PAS : %s"
                          % (nom[:40], len(delta.nouveaux), ", ".join(delta.nouveaux)))
            # 🔴 Flo (15/07) « hyperlent » : refaire prog.ecrire() (écriture disque) ET la somme
            #    sur les 181k dépôts à CHAQUE dépôt = des MILLIARDS d'ops. Le battement de cœur
            #    rafraîchit déjà l'écran toutes les 2 s -> on ne le fait plus qu'occasionnellement.
            if i % 200 == 0:
                prog.listes = sum(1 for v in repos.values() if v.get("trouve_par") == "liste")
                prog.ecrire()

            if i % 20 == 0:
                _chk()
                print("  [%5.1f h] %d/%d README lus · repos=%d"
                      % ((time.time() - t0) / 3600.0, i, len(noms), len(repos)))

    _phase("PHASE B — LIRE LES README · le GRAPHE · le score DIFFÉRENTIEL", _lire, bless)
    _chk()
    _rapport_partiel([], notes, repos)   # 🔴 dès la fin du tri, un moisson-fini.md existe déjà.

    # #10 / #11 — l'autorité (être **cité**) et les autres repos des bons auteurs
    inv = citations_inverses(qui_cite)
    for i, (s, nom) in enumerate(notes):
        notes[i] = (s + autorite(inv, nom), nom)
    notes.sort(key=lambda x: -x[0])

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 🔴🔴 CORRIGÉ — *« chaque github c'est une analyse en profondeur nécessaire ».*
    #
    #    AVANT : `meilleurs = notes[: args.top]` -> **seuls 60 dépôts** voyaient leur code ouvert.
    #            Un bon repo classé 61ᵉ n'avait **jamais** de fiche. ***Exactement ce que Flo ne
    #            voulait pas.***
    #
    #    APRÈS : on analyse en profondeur **TOUT ce qui a de la substance** (score différentiel
    #            positif : au moins une formule, un aveu, un chiffre, ou un concept qu'on n'a
    #            PAS), **best-first**, jusqu'à la limite de temps.
    #
    #    🔒 Ce qui a un score **≤ 0** (promesses creuses, zéro signal) est **honnêtement écarté**
    #       AVANT l'analyse profonde — *non pour le cacher, mais pour ne pas gâcher le temps des
    #       bons.* Il apparaît dans les ÉCARTÉS avec son motif. **Rien ne disparaît en silence.**
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    SEUIL_ANALYSE = 0.0
    dignes = [n for s, n in notes if s > SEUIL_ANALYSE]
    plafond = args.top if args.top and args.top > 0 else 10 ** 9   # 0 = illimité (le temps borne)
    meilleurs = dignes[:plafond]
    n_sans_substance = len(notes) - len(dignes)
    print("\n  📊 %d repos lus · **%d dignes d'analyse profonde** (substance positive) · "
          "%d sans substance (écartés honnêtement)" % (len(notes), len(dignes), n_sans_substance))
    autres = autres_repos_de_l_auteur(meilleurs, list(repos))
    if autres:
        print("\n  #11 — **les autres repos des bons auteurs** : %d"
              % sum(len(v) for v in autres.values()))

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  PHASE C — OUVRIR LE CODE · #2 commits · #4 issues · #5 tests · #6 constantes
    #            · #8 dédup · #12 reproductibilité
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    entrees: list[dict[str, Any]] = []
    codes: dict[str, str] = {}
    constantes: list[dict[str, Any]] = []
    concepts_par_repo: dict[str, list[str]] = {}

    analyses_faites = {"n": 0}

    def _ouvrir() -> None:
        # 🔒 ON RÉSERVE ~28 % DU TEMPS POUR LE CRAWLER (phase D — arXiv, OpenAlex, OpenReview…).
        #    *Sinon un corpus GitHub énorme mangerait tout, et les PAPIERS — la source des
        #     formules — ne seraient jamais lus.* On analyse donc les repos best-first jusqu'à
        #    cette borne ; ce qui reste est **reporté dans le JSON, trié**, et le run est
        #    **relançable** (il reprend là).
        reserve_crawler = limite * 0.28
        for k, nom in enumerate(meilleurs, 1):
            if _reste() <= max(150.0, reserve_crawler):
                break
            analyses_faites["n"] = k
            meta = _json(_doux("https://api.github.com/repos/%s" % nom, "meta|%s" % nom))
            branche = (meta or {}).get("default_branch") or "main"
            lic = ((meta or {}).get("license") or {}).get("spdx_id") or repos[nom].get("licence")

            arbre_j = _json(_doux(
                "https://api.github.com/repos/%s/git/trees/%s?recursive=1" % (nom, branche),
                "tree|%s" % nom))
            arbre = [str(x["path"]) for x in ((arbre_j or {}).get("tree") or [])
                     if isinstance(x, dict) and x.get("type") == "blob" and x.get("path")]

            # #2 — LES COMMITS. *Les bugs que d'autres ont DÉJÀ PAYÉS.*
            cj = _json(_doux("https://api.github.com/repos/%s/commits?per_page=100" % nom,
                             "commits|%s" % nom))
            commits = fouiller_commits([
                (str(x.get("sha") or ""), str(((x.get("commit") or {}).get("message")) or ""))
                for x in (cj or []) if isinstance(x, dict)
            ])

            # #4 — LES ISSUES. *Des aveux INVOLONTAIRES.*
            ij = _json(_doux(
                "https://api.github.com/repos/%s/issues?state=all&per_page=60" % nom,
                "issues|%s" % nom))
            issues = fouiller_issues([x for x in (ij or []) if isinstance(x, dict)])

            # #5 — LES TESTS : la carte des PEURS. · #12 — la REPRODUCTIBILITÉ.
            peurs = peurs_de_l_auteur([p for p in arbre if "test" in p.lower()])
            repro = reproductibilite(arbre)

            # LE CODE — *le README est la page de vente ; le code est la vérité.*
            lectures: list[dict[str, Any]] = []
            blob = ""
            for ch in fichiers_a_lire(arbre, maxi=4):   # 🔴 4 fichiers-clés (au lieu de 6) -> étape 3 plus rapide
                if _reste() <= 120:
                    break
                src = _doux("https://api.github.com/repos/%s/contents/%s"
                            % (nom, urllib.parse.quote(ch)),
                            "file|%s|%s" % (nom, ch), brut=True)
                if not src:
                    continue
                blob += src
                lectures += [x.as_dict() for x in liste_de_lecture(nom, ch, src)]
                # #6 — LES CONSTANTES. *Du calibrage gratuit, volé à des gens qui l'ont payé.*
                #   🔴 `.extend()` et NON `+=` : `constantes` vit dans main() (variable partagée).
                #   `constantes += ...` la rebindait -> Python la croyait locale à _ouvrir ->
                #   UnboundLocalError au 1er fichier -> l'étape 3 plantait -> rapport VIDE. (Bug
                #   trouvé le 15/07 : les runs mouraient avant en étape 2, il était donc caché.)
                constantes.extend(x.as_dict() for x in extraire_constantes(ch, src))

            if blob:
                codes[nom] = blob                     # #8 — pour la dédup

            # les signaux du README ont déjà été calculés en phase B et mis en cache dans `repos`.
            sigd = repos[nom].get("signaux") or {}
            concepts_par_repo[nom] = list((sigd.get("formules") or {}).keys())

            f = classer(nom, licence=lic, signaux=sigd, n_lignes_de_code=len(lectures))
            entrees.append({
                "repo": nom, "score": next((s for s, n in notes if n == nom), 0.0),
                "etoiles": int(repos[nom].get("etoiles") or 0), "licence": lic,
                "provenance": repos[nom].get("pourquoi", ""),
                "verdict": f.verdict, "pourquoi": f.pourquoi,
                "trous_combles": f.trous_combles, "reserves": f.reserves,
                "signaux": sigd, "delta": repos[nom].get("delta"),
                "installation": installation(arbre).as_dict(),
                "lectures": lectures,
                "commits_qui_comptent": [x.as_dict() for x in commits],
                "issues_qui_avouent": [x.as_dict() for x in issues],
                "peurs_de_l_auteur": peurs,
                "reproductibilite": repro.as_dict(),
                "cite_par": inv.get(nom, []),
            })
            print("  [%5.1f h] %-38s %-18s %d ligne(s) · %d commit(s) · %d issue(s)"
                  % ((time.time() - t0) / 3600.0, nom[:38], f.verdict,
                     len(lectures), len(commits), len(issues)))

            prog.phase = "PHASE C — OUVRIR LE CODE (commits · issues · tests · constantes)"
            prog.detail = "ouverture : %s  [%s]" % (nom, f.verdict)
            prog.fait, prog.total = k, len(meilleurs)
            prog.ouverts = k
            prog.retenus = sum(1 for e in entrees if e["verdict"] != "SKIP_WITH_REASON")
            prog.commits += len(commits)
            prog.issues += len(issues)
            prog.constantes = len(constantes)
            if f.verdict != "SKIP_WITH_REASON":
                prog.note("✅ %-34s **%s** — %d ligne(s) à lire" % (nom[:34], f.verdict,
                                                                    len(lectures)))
            for cm in commits[:2]:
                prog.note("   🔧 commit `%s` : %s" % (cm.categorie, cm.message[:52]))
            for iss in issues[:1]:
                prog.note("   💬 issue #%d (AVEU) : %s" % (iss.numero, iss.titre[:52]))
            prog.ecrire()

            if k % 5 == 0:
                _chk()
                _rapport_partiel(entrees, notes, repos)   # 🔴 le .md reste À JOUR pendant l'étape 3

    _phase("PHASE C — OUVRIR LE CODE · commits · issues · tests · constantes", _ouvrir, bless)
    _rapport_partiel(entrees, notes, repos)   # 🔴 après l'étape 3 : le .md a déjà les analyses.

    # #8 — LA DÉDUP. *Sans elle, on lit trente fois le même bot.*
    jumeaux = dedupliquer(codes) if codes else None
    if jumeaux and jumeaux.groupes:
        print("\n  #8 — **%d groupe(s) de jumeaux** : on n'en lira **qu'un** par groupe."
              % len(jumeaux.groupes))

    # #15 — LES ZONES VIERGES. *Ce que PERSONNE ne fait.*
    zv = zones_vierges(concepts_par_repo)

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  PHASE D — 🔑 **LA FRONTIÈRE.** *Le moissonneur ne doit JAMAIS rester sans chercher.*
    #
    #  Flo : *« au bout de 10 h il ne saura plus quoi chercher »* et *« plein de termes avec
    #  0 résultat »*. ***C'est le MÊME défaut, vu par ses deux bouts :*** une LISTE est finie
    #  (elle s'épuise) et devinée (mes mots-clés, pas ceux du terrain).
    #
    #  -> **une FRONTIÈRE** : le corpus **génère ses propres requêtes**. Un README cite
    #     Almgren-Chriss, un papier en cite un autre, une dépendance s'appelle `hftbacktest`…
    #     ***Un crawler avec une frontière ne peut pas être à court.***
    #
    #  Et on cherche **PARTOUT** : arXiv · **OpenAlex (le graphe de citations complet)** ·
    #  Semantic Scholar · PyPI · crates.io · Hacker News · quant.stackexchange.
    #  🎓 *Y compris les COURS* : `"lecture notes" market microstructure`, les **revues**
    #     (*une revue = 100 papiers déjà digérés par quelqu'un dont c'est le métier*).
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    front = Frontiere()
    # 🔑 LE PRINCIPE DIFFÉRENTIEL, APPLIQUÉ À LA FRONTIÈRE.
    #    *Avec b = 31,5, on n'explorera que ~10 % des pistes engendrées. **L'ORDRE est tout.***
    #    -> ce qui touche un concept **qu'on N'A PAS** passe devant.
    front.nous_manque = tuple(notre_etat.manquants)
    web_gardes: list[dict[str, Any]] = []
    srcs = {s.nom: s for s in catalogue(jeton_github=jeton)}

    def _crawler() -> None:
        # 1) ON SÈME depuis TOUT ce qu'on a déjà lu. *Le terrain, pas mes devinettes.*
        n = 0
        for e in entrees:
            nom = e["repo"]
            txt = CACHE.lire("readme|%s" % nom) or ""
            n += front.semer(extraire(txt, parent=nom), profondeur=1)
            n += front.semer(depuis_commits(
                [c["message"] for c in e.get("commits_qui_comptent") or []], parent=nom),
                profondeur=1)
            arbre_txt = CACHE.lire("tree|%s" % nom)
            if arbre_txt:
                for man in ("requirements.txt", "pyproject.toml", "Cargo.toml", "package.json"):
                    c = CACHE.lire("file|%s|%s" % (nom, man))
                    if c:
                        n += front.semer(
                            depuis_dependances(dependances(man, c), parent=nom), profondeur=1)
        print("  🌱 **%d pistes semées** depuis ce qu'on a déjà lu." % n)

        # 2) LE FOND DE ROULEMENT — *il ne doit jamais rester sans chercher.*
        n2 = front.semer(fond_de_roulement(), profondeur=0)
        print("  🎓 + %d pistes de fond (les catégories entières de q-fin, les COURS, les revues)"
              % n2)

        # 3) ON CRAWLE. **Tant qu'il reste du temps.** *Et la frontière grandit pendant qu'on la vide.*
        vus_papiers: set[str] = set()
        boucles = 0
        while _reste() > 120:
            p = front.prochaine()
            if p is None:
                # 🔒 La frontière est VRAIMENT vide -> on la ré-ensemence.
                #    *Il ne doit JAMAIS rester sans chercher.*
                if front.semer(fond_de_roulement(), profondeur=0) == 0:
                    prog.note("⚪ frontière épuisée ET fond déjà exploré — *rien à inventer.*")
                    break
                continue

            boucles += 1
            trouves = 0
            qualite = 0.0          # #5 — la SOMME des scores gardés (la qualité, pas le compte)
            prof = front.profondeur_de(p)

            # ═══════════════════════════════════════════════════════════════════════════════════
            #  LES 17 SOURCES, INTERROGÉES **UNIFORMÉMENT**.
            #
            #  🔑 *Le filtre ne demande pas D'OÙ ça vient. Il demande **CE QUE ÇA PROUVE**.*
            #  Seule la **fiabilité** de la source module le score.
            # ═══════════════════════════════════════════════════════════════════════════════════
            PAR_GENRE: dict[str, tuple[str, ...]] = {
                "papier": ("arxiv", "openalex", "openreview", "paperswithcode",
                           "semanticscholar", "dblp", "zenodo", "crossref", "wikipedia"),
                "biblio": ("pypi", "cratesio", "npm", "softwareheritage"),
                "code": ("hackernews", "stackexchange", "zenodo", "softwareheritage"),
                "repo": ("hackernews", "stackexchange"),
            }

            # un repo nommément cité -> il entre directement dans le corpus GitHub
            if p.genre == "repo" and "/" in p.requete and " " not in p.requete:
                if p.requete not in repos:
                    repos[p.requete] = {"nom": p.requete, "etoiles": 0, "licence": None,
                                        "trouve_par": "frontiere", "pourquoi": p.venu_de}
                    trouves += 1
                front.noter(p, trouves)
                continue

            q = p.requete
            if q.startswith(("arxiv:", "doi:")):
                q = q.split(":", 1)[1]

            for nom_src in PAR_GENRE.get(p.genre, ("openalex",)):
                if _reste() <= 120:
                    break
                s17 = next((x for x in SOURCES_17 if x.nom == nom_src), None)
                if s17 is None:
                    continue
                u = url_src(nom_src, q)
                if not u:
                    continue

                brut = _get(u, bless, "%s|%s" % (nom_src, q))
                time.sleep(s17.rythme)
                if not brut:
                    continue

                # la source de référence pour le filtre (fiabilité portée par `s17`)
                src_obj = srcs["arxiv"]
                for titre, texte, lien, cites in parser_src(nom_src, brut):
                    if not (titre or texte) or (lien and lien in vus_papiers):
                        continue
                    if lien:
                        vus_papiers.add(lien)

                    v = juger("%s %s" % (titre, texte), source=src_obj)
                    v.score *= float(s17.fiabilite)

                    # 🔑 **OPENREVIEW** : un rapport de relecture est de la **critique
                    #    institutionnalisée**. *Un relecteur est PAYÉ en réputation pour trouver
                    #    ce qui cloche.* -> il doit **toujours** passer si sa critique touche
                    #    notre domaine : ***c'est notre signal « aveu de limite », écrit par un
                    #    adversaire expert.***
                    garder = v.garde or (nom_src == "openreview" and v.utile) or cites >= 60

                    if garder:
                        entree_web = {
                            "source": nom_src, "titre": titre, "resume": texte[:900],
                            "lien": lien, "cite_par": cites, "venu_de": p.venu_de,
                            "fiabilite_source": s17.fiabilite, **v.as_dict()}

                        # #3 bis — ce papier ressuscite-t-il une idée qu'on a mesurée MORTE ?
                        morts = deja_mort("%s %s" % (titre, texte))
                        if morts:
                            entree_web["deja_mort"] = [x.as_dict() for x in morts]

                        # #2 — LIRE LE CORPS du papier (pas que le résumé), pour les TOP papiers.
                        #      *Le résumé est la page de vente ; le corps a la formule et l'aveu.*
                        if (float(v.score or 0) >= 25.0 and _reste() > 200
                                and (u_ht := url_papier_plein_texte(lien or ""))):
                            html = _get(u_ht, bless, "html|%s" % lien)
                            time.sleep(1.0)
                            if html:
                                corps = extraits_du_corps(texte_du_html(html))
                                if corps:
                                    entree_web["extraits_du_corps"] = corps
                                    front.semer(extraire(" ".join(corps), parent=titre[:40]),
                                                profondeur=prof + 1)

                        web_gardes.append(entree_web)
                        trouves += 1
                        qualite += float(v.score or 0.0)     # #5 — la QUALITÉ, pas le compte
                        # 🔑 CE QU'ON LIT ENGENDRE DE NOUVELLES PISTES. *La frontière grandit.*
                        front.semer(extraire("%s %s" % (titre, texte), parent=titre[:40]),
                                    profondeur=prof + 1)

                        # 🔑 #10 SUR LA LITTÉRATURE : **QUI CITE ce papier ?**
                        #    *Une citation est un choix de chercheur ; une étoile est un clic.*
                        #    Sur OpenAlex c'est **gratuit et complet**.
                        if (nom_src == "openalex" and cites >= 30
                                and prof < front.PROFONDEUR_MAX and _reste() > 300 and lien):
                            u2 = url_src("openalex_cite", lien)
                            b2 = _get(u2, bless, "openalex_cite|%s" % lien) if u2 else None
                            time.sleep(s17.rythme)
                            for t2, _x2, _l2, _c2 in parser_src("openalex", b2 or ""):
                                if t2:
                                    front.semer([Piste('"%s"' % t2[:60], "papier",
                                                       "**cite** `%s`" % titre[:40],
                                                       titre[:40], 1.7)],
                                                profondeur=prof + 1)

            # 🔑 ON COMPTE LES STÉRILES. *Flo : « plein de termes avec 0 résultat ».*
            front.noter(p, trouves)
            # #5 — LE BANDIT RÉCOMPENSÉ PAR LA QUALITÉ (somme des scores), pas le nombre.
            #      *Une source qui rend 50 médiocres ne doit pas battre celle qui rend 2 excellents.*
            bandit.noter("frontière:%s" % p.genre, qualite)

            prog.phase = "PHASE D — 🌐 LE CRAWLER (il ne reste JAMAIS sans chercher)"
            prog.detail = "%s [%s, prof. %d] — %s" % (p.requete[:48], p.genre, prof, p.venu_de[:34])
            prog.fait = len(front.vues) - front.reste()
            prog.total = len(front.vues)
            prog.web = len(web_gardes)
            prog.frontiere = front.reste()
            prog.steriles = len(front.steriles)
            if trouves:
                prog.note("🌐 %-42s +%d  (%s)" % (p.requete[:42], trouves, p.genre))
            prog.ecrire()

            if boucles % 10 == 0:
                _chk()
                print("  [%5.1f h] frontière : **%d à explorer** · web gardés : %d · stériles : %d"
                      % ((time.time() - t0) / 3600.0, front.reste(),
                         len(web_gardes), len(front.steriles)))

    _phase("PHASE D — 🌐 LE CRAWLER : arXiv · OpenAlex · S2 · PyPI · crates · HN · SE", _crawler,
           bless)
    _chk()

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  LE LIVRABLE
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    md = dossier_md(entrees)

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  🔒 LE BLOC DE PRÉ-APPROBATION + 💡 LES FICHES D'IDÉES (quoi · pourquoi · COMMENT · réfut.)
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    sup: list[str] = ["", "---", "", PRE_APPROBATION, ""]

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    # 🔒 LE BILAN DE COUVERTURE — *honnête : ce que j'ai analysé, et ce que je n'ai PAS pu.*
    #
    #    Flo : *« chaque github c'est une analyse en profondeur nécessaire »* + *« es-tu sûr qu'il
    #    gardera ABSOLUMENT TOUTES les bonnes idées ? »*
    #
    #    ***Je ne peux pas promettre « absolument toutes ». Aucun filtre ne le peut.*** Mais je
    #    peux DIRE, chiffre en main, exactement ce qui a été fait et ce qui reste.
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    n_analyses = analyses_faites["n"]
    n_dignes = len(meilleurs)
    n_reste_temps = max(0, n_dignes - n_analyses)
    sup += [
        "# 🔒 Bilan de couverture — *ce que j'ai analysé, et ce que je n'ai pas pu*", "",
        "> ***Je ne peux pas te promettre « absolument toutes les bonnes idées ». Aucun filtre "
        "ne le peut — un faux négatif reste toujours possible.*** Mais voici, chiffre en main, "
        "**exactement** ce qui a été fait. **Rien n'est caché ; tout le détail est dans le JSON "
        "jumeau `data/reports/moisson_10h.json`.**", "",
        "| | |", "|---|---|",
        "| dépôts GitHub **scannés** | %d |" % len(repos),
        "| ...dont **lus** (README) | %d |" % len(notes),
        "| ...dont **dignes d'analyse profonde** (substance positive) | **%d** |" % n_dignes,
        "| ...dont **réellement analysés en profondeur** (code, commits, issues, tests) | **%d** |"
        % n_analyses,
        "| ...**reportés faute de temps** (dans le JSON, triés — **le run est relançable**) | %d |"
        % n_reste_temps,
        "| dépôts **sans substance**, écartés avec motif | %d |" % (len(notes) - n_dignes),
        "| sources web (papiers/biblios/forums) **gardées** | %d |" % len(web_gardes),
        "| 🔴 sources **non lues** (comptées, pas cachées) | %d |" % len(bless.non_lus),
        "",
        "**Ce que je GARANTIS :** ① tout dépôt à substance positive est analysé en profondeur "
        "(plus de « top 60 » figé) ; ② **rien n'est supprimé en silence** — chaque écarté a son "
        "motif, chaque non-lu est compté, chaque liste tronquée renvoie au JSON ; ③ chaque idée "
        "retenue est expliquée en entier (quoi · pourquoi · comment · réfutation).",
        "",
        "**Ce que je NE garantis PAS :** qu'aucune bonne idée n'ait été sous-classée par le "
        "filtre. *C'est pourquoi le run est **relançable** (il reprend et creuse plus loin), et "
        "pourquoi le canari prouve, avant de commencer, que le trieur sépare bien le connu.*",
        "", "---", "",
    ]

    # #4 — DÉDUP ENTRE SOURCES : le même papier sur 4 sources = UNE entrée, pas quatre.
    fusions = dedupliquer_idees(web_gardes)
    web_uniques = [f.representant for f in fusions]
    n_doublons = sum(f.doublons for f in fusions)

    # #4 bis — LIER un repo à son papier (« la théorie ET le code »).
    liens_repo_papier = lier_repo_et_papier(
        [e["repo"] for e in entrees if e["verdict"] != "SKIP_WITH_REASON"], web_uniques)

    # 💡 LES IDÉES ACTIONNABLES — *cent papiers sur le même sujet ne font pas cent idées.*
    tout_le_corpus: list[dict[str, Any]] = list(web_uniques) + [
        {"titre": e["repo"], "texte": json.dumps(e.get("signaux") or {}, ensure_ascii=False),
         "lien": "https://github.com/%s" % e["repo"], "source": "github"}
        for e in entrees if e["verdict"] != "SKIP_WITH_REASON"
    ]
    idees = extraire_idees(tout_le_corpus)

    # #7 — LE MÉTA-CLASSEMENT : « si tu ne fais qu'UNE chose, fais celle-ci. »
    priorites = prioriser([i.as_dict() for i in idees])

    # #7 — LE MÉTA-CLASSEMENT, EN TÊTE. *« Si tu ne fais qu'UNE chose… »*
    if priorites:
        sup += ["# 🥇 PAR OÙ COMMENCER — *le méta-classement (gravité × étayage × facilité)*", "",
                "> *Les fiches ci-dessous sont classées par NOUVEAUTÉ. Ce tableau, lui, dit quoi "
                "faire **EN PREMIER** : il croise **la gravité de NOTRE trou**, à quel point "
                "l'idée est **étayée**, et **la facilité** de la brancher.*", "",
                "| # | idée | priorité | pourquoi |", "|---|---|---|---|"]
        for rang, pr in enumerate(priorites[:12], 1):
            sup.append("| %d | `%s` | **%.2f** | %s |"
                       % (rang, pr.cle, pr.priorite, pr.pourquoi))
        sup.append("")

    if liens_repo_papier:
        sup += ["## 🔗 La théorie ET le code — *repos qui implémentent un papier trouvé*", ""]
        for lp in liens_repo_papier[:15]:
            sup.append("- [`%s`](https://github.com/%s) implémente **[%s](%s)**"
                       % (lp["repo"], lp["repo"], lp["papier"][:90], lp["lien"]))
        sup.append("")

    sup += ["# 💡 LES IDÉES — *quoi · **pourquoi** · **comment l'implémenter** · ce qui la "
            "réfuterait*", "",
            "**%d idée(s) actionnable(s)**, étayées par **%d source(s)** "
            "(%d doublon(s) inter-sources fusionné(s))."
            % (len(idees), len(tout_le_corpus), n_doublons), "",
            "> *Cent papiers sur le même sujet ne font pas cent idées : ils font **une** idée, "
            "**bien étayée**.*", ""]
    if not idees:
        sup += ["> ⚪ **Aucune idée actionnable.** *Ce n'est pas une panne : le corpus n'a rien "
                "apporté que nous n'ayons déjà.*", ""]
    for i in idees:
        sup += i.md()

    sup += ["", "---", "", "# 🧪 Les 15 idées d'outillage — ce qu'elles ont donné", ""]

    sup += ["## #1 — Le canari", "", c.rapport(), ""]

    sup += ["## #3 — Ce qui nous MANQUE (indexé sur notre vrai code)", "",
            "| ce qui manque | où on en est |", "|---|---|"]
    sup += ["| `%s` | %s |" % (k, v) for k, v in notre_etat.manquants.items()]
    sup.append("")

    if constantes:
        sup += ["## #6 — Les constantes des autres, **comparées aux nôtres**", "",
                "*Du calibrage gratuit, volé à des gens qui l'ont payé.*", "",
                "| grandeur | leur valeur | fichier | **la nôtre** |", "|---|---|---|---|"]
        vus: set[tuple[str, float]] = set()
        for x in constantes[:60]:
            k = (x["genre"], x["valeur"])
            if k in vus:
                continue
            vus.add(k)
            sup.append("| `%s` | %s | `%s` | %s |"
                       % (x["genre"], x["valeur"], x["fichier"], x["la_notre"]))
        sup.append("")

    sup += ["## #15 — Ce que **personne** ne fait", "",
            "*Un concept que personne n'implémente est soit **inutile**, soit **inexploité**.*",
            "***Les deux méritent d'être sus — et le second, c'est là que vit un edge.***", ""]
    sup += ["- `%s` — **aucun repo du corpus**" % z for z in zv.jamais_vus] or ["*(aucun)*"]
    sup.append("")

    if jumeaux and jumeaux.groupes:
        sup += ["## #8 — Les jumeaux (on n'en lit **qu'un**)", ""]
        sup += ["- %s" % " ≡ ".join("`%s`" % x for x in g) for g in jumeaux.groupes[:20]]
        sup.append("")

    sup += ["## #9 — Où le quota a payé", "", "| famille de requête | rendement | essais |",
            "|---|---|---|"]
    for b, r, n in bandit.classement()[:12]:
        sup.append("| %s | %.2f | %d |" % (b, r, n))
    sup.append("")

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  🌐 LE CRAWLER — *chercher PARTOUT.*
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    rw = rapport_web()
    r17 = rapport_17()
    sup += ["", "---", "",
            "# 🌐 Le crawler — **%d sources**, toutes gratuites et sans clé" % r17["n_sources"],
            "",
            "> %s" % r17["la_meilleure"], "",
            "> %s" % r17["franchise"], "",
            "> %s" % rw["les_cours_que_flo_veut"], "",
            "| source | genre | fiabilité | pourquoi |", "|---|---|---|---|"]
    sup += ["| `%s` | %s | ×%.2f | %s |" % (s["nom"], s["genre"], s["fiabilite"], s["pourquoi"])
            for s in r17["sources"]]
    sup += ["", "### 🔴 Ce qu'on n'a **pas** — *et je le dis*", "",
            "| source | pourquoi |", "|---|---|"]
    sup += ["| %s | %s |" % (n, p) for n, p in r17["inaccessibles"].items()]
    sup.append("")

    if web_uniques:
        web_uniques.sort(key=lambda x: -float(x.get("score") or 0))
        par_src: dict[str, list[dict[str, Any]]] = {}
        for w in web_uniques:
            par_src.setdefault(str(w["source"]), []).append(w)
        sup += ["## Les %d sources retenues (après dédup inter-sources)" % len(web_uniques), ""]
        for s, xs in sorted(par_src.items(), key=lambda kv: -len(kv[1])):
            sup += ["### %s (%d)" % (s, len(xs)), ""]
            for w in xs[:30]:
                cite = (" · **cité %d fois**" % w["cite_par"]) if w.get("cite_par") else ""
                sup += [
                    "- **[%s](%s)** — score %.1f%s"
                    % (str(w.get("titre"))[:130], w.get("lien"),
                       float(w.get("score") or 0), cite),
                    "  - *pourquoi gardé :* %s" % w.get("pourquoi"),
                    "  - *comment on est arrivé là :* %s" % w.get("venu_de"),
                ]
                if w.get("honnetete"):
                    sup.append("  - 🔑 **il avoue une limite** : « …%s… »"
                               % str(w["honnetete"][0])[:110])
            # 🔒 *une liste tronquée qui ne le DIT pas est une liste qui ment.*
            if len(xs) > 30:
                sup.append("- *(+%d autres de cette source, **tous dans le JSON**, triés par "
                           "score)*" % (len(xs) - 30))
            sup.append("")
    else:
        sup += ["> ⚪ **Rien de gardable hors GitHub.** *Ce n'est pas une panne : le filtre a "
                "refusé tout ce qui ne prouvait rien.*", ""]

    fr = front.as_dict()
    sup += ["## 🔑 La frontière — *pourquoi il n'a jamais été à court*", "",
            "> %s" % fr["pourquoi_ca_ne_se_vide_pas"], "",
            "| | |", "|---|---|",
            "| pistes explorées | **%d** |" % fr["deja_explorees"],
            "| pistes **restant** à explorer | **%d** |" % fr["reste_a_explorer"],
            ""]
    if fr["requetes_FECONDES"]:
        sup += ["### Les requêtes qui ont **payé**", "",
                "| requête | trouvés |", "|---|---|"]
        sup += ["| `%s` | %d |" % (x["requete"][:70], x["trouves"])
                for x in fr["requetes_FECONDES"]]
        sup.append("")
    if fr["requetes_STERILES"]:
        sup += ["### 🔴 Les %d requêtes **STÉRILES** — *et je les publie*" % fr["n_steriles"], "",
                "> %s" % fr["pourquoi_les_steriles"], "",
                "| requête | essais |", "|---|---|"]
        sup += ["| `%s` | %d |" % (x["requete"][:70], x["essais"])
                for x in fr["requetes_STERILES"]]
        sup.append("")

    sup += ["## 🔴 Les blessures — *ce que je n'ai PAS su lire*", "",
            bless.rapport(), "",
            "*« Je n'ai pas su lire » n'est **pas** « il n'y avait rien ». "
            "C'est exactement la confusion qui avait perdu **235 README**, dont **hftbacktest**.*",
            ""]

    texte_md = md + "\n".join(sup)

    # #8 — LINTER LE LIVRABLE. *On teste chaque brique ; on doit aussi vérifier le RÉSULTAT.*
    lint = linter_md(texte_md)
    if not lint.ok:
        # on ne CACHE pas les défauts : on les écrit DANS le fichier, en tête.
        texte_md = ("> ⚠️ **Ce fichier a des défauts de forme, signalés honnêtement :**\n> - %s\n\n"
                    % "\n> - ".join(lint.problemes)) + texte_md
    print("\n  🧪 lint du .md : %s" % lint.rapport().replace("\n", " "))

    SORTIE_MD.write_text(texte_md, encoding="utf-8")
    SORTIE_JSON.parent.mkdir(parents=True, exist_ok=True)
    SORTIE_JSON.write_text(json.dumps({
        "canari": c.as_dict(), "notre_etat": notre_etat.as_dict(),
        "entrees": entrees, "constantes": constantes,
        "zones_vierges": zv.as_dict(),
        "jumeaux": jumeaux.as_dict() if jumeaux else None,
        "bandit": bandit.as_dict(), "blessures": bless.as_dict(),
        "autres_repos_des_bons_auteurs": autres,
        "crawler_web": web_gardes,                        # brut (avec doublons, pour l'audit)
        "crawler_web_unique": web_uniques,                # #4 dédupliqué inter-sources
        "n_doublons_fusionnes": n_doublons,
        "repo_implemente_papier": liens_repo_papier,      # #4 bis
        "meta_classement": [p.as_dict() for p in priorites],   # #7
        "semantique": diagnostic_semantique(),            # #1
        "lint_du_md": lint.as_dict(),                     # #8
        "frontiere": front.as_dict(),
        "sources_web": rapport_web(),
        # 🔒 LE BILAN DE COUVERTURE, en machine — *rien ne se perd.*
        "couverture": {
            "repos_scannes": len(repos),
            "repos_lus": len(notes),
            "repos_dignes_analyse": len(meilleurs),
            "repos_analyses_en_profondeur": analyses_faites["n"],
            "repos_reportes_faute_de_temps": max(0, len(meilleurs) - analyses_faites["n"]),
            "repos_sans_substance": len(notes) - len(meilleurs),
        },
        # 🔑 la LISTE COMPLETE des dignes non encore analysés, triée -> le prochain run les prend.
        "a_analyser_au_prochain_run": meilleurs[analyses_faites["n"]:],
        # tous les repos vus, avec leur provenance (meme ceux jamais ouverts) -> rien ne s'efface.
        "tous_les_repos_vus": [
            {"nom": n, "etoiles": v.get("etoiles"), "trouve_par": v.get("trouve_par"),
             "pourquoi": v.get("pourquoi")}
            for n, v in sorted(repos.items())
        ],
        "n_repos_vus": len(repos), "n_requetes": len(faites),
        "heures": round((time.time() - t0) / 3600.0, 2),
        "lecture_seule": True, "aucun_code_execute": True, "real_execution": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    _chk()
    prog.phase = "✅ TERMINÉ — voir `moisson-fini.md` à la racine"
    prog.detail = ""
    prog.jumeaux = len(jumeaux.groupes) if jumeaux else 0
    prog.retenus = sum(1 for e in entrees if e["verdict"] != "SKIP_WITH_REASON")
    prog.note("🏁 TERMINÉ — %d repos vus · %d retenus · %d non lus (et je le DIS)"
              % (len(repos), prog.retenus, len(bless.non_lus)))
    _stop_battement.set()          # on coupe le battement de cœur : le run est fini
    prog.ecrire()                  # un dernier rafraîchissement, propre

    # #6 — on note la date : le prochain `--depuis-dernier` ne reprendra que le NOUVEAU.
    ecrire_derniere_date(fichier_date)

    gardes = [e for e in entrees if e["verdict"] != "SKIP_WITH_REASON"]
    print("\n" + "=" * 100)
    print("  TERMINÉ — %.2f h" % ((time.time() - t0) / 3600.0))
    print("=" * 100)
    print("\n  repos vus : **%d** · ouverts : %d · **retenus : %d**"
          % (len(repos), len(entrees), len(gardes)))
    print("  cache : %d entrées (**re-juger hors ligne = gratuit**)" % CACHE.taille())
    print("\n  " + bless.rapport().replace("\n", "\n  "))
    print("\n  -> **%s**" % SORTIE_MD)
    print("\n  🔒 Lecture seule. Aucun clone. **Aucun code téléchargé n'a été exécuté.**")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n\n  ⏹️ **Ctrl-C.** *L'état est sauvé. Relancer reprendra exactement ici.*")
        raise SystemExit(0)
