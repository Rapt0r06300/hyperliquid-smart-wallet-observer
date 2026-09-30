#!/usr/bin/env python3
"""MOISSONNEUR GITHUB — trouver et TRIER des centaines de repos, sans en lire un seul (2026-07-12).

POURQUOI CET OUTIL EXISTE
-------------------------
Flo veut 200+ repos. Les chercher a la main est absurde : 39 repos avaient deja ete clones,
et le tri honnete a donne : ~15 Polymarket (mauvais marche), 3 Solana (mauvaise chaine),
2 qui promettent des choses IMPOSSIBLES sur Hyperliquid, et la meilleure idee de toute la
bibliotheque etait DEJA dans notre code, debranchee.

Le goulot n'est pas de TROUVER des repos. C'est de ne pas se noyer dedans.

Cet outil moissonne l'API GitHub par sujets, et applique AUTOMATIQUEMENT les deux protocoles
qui nous ont evite des pieges reels aujourd'hui :

  1. LICENCE (tache X-05)
     MIT/Apache/BSD/ISC -> ADAPTABLE (avec attribution)
     GPL/AGPL           -> IDEE SEULEMENT (copier forcerait TOUT HyperSmart en GPL)
     aucune licence     -> INTOUCHABLE (defaut = tous droits reserves)

  2. CREDIBILITE (tache X-06)
     Deux cas REELS trouves aujourd'hui :
       - un repo au titre parfait : 0 etoile, 4 commits, pas de licence, et une strategie
         partiellement IMPOSSIBLE (« short spot » sur HL, sans emprunt)
       - un autre promettant du « maker rebate mining » : la doc officielle HL dit qu'il n'y
         a AUCUN rebate.
     => Un repo qui EXISTE n'est pas une preuve que la strategie MARCHE.
        Notre bot existe aussi, et il perd de l'argent.

L'outil NE JUGE PAS l'idee (c'est notre travail). Il ecarte le bruit et met en tete ce qui
merite qu'un humain y passe une heure.

    python tools/moissonner_github.py                 # sujets par defaut
    python tools/moissonner_github.py --sujets hyperliquid-bot,market-maker,arbitrage
    python tools/moissonner_github.py --pages 4       # ~120 repos par sujet

Sortie : data/reports/github_moisson.json + un tableau trie a l'ecran.

LECTURE SEULE. API publique GitHub. Aucun clone, aucun code execute, aucun ordre. JAMAIS.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SORTIE = ROOT / "data" / "reports" / "github_moisson.json"
API = "https://api.github.com/search/repositories"

# =============================================================================================
# STRATEGIE DE RECHERCHE — refondue apres la 1re moisson (2026-07-12)
#
# OBSTACLE DUR : l'API de recherche GitHub PLAFONNE A 1000 RESULTATS PAR REQUETE.
# Chercher plus longtemps sur la meme requete ne rend RIEN de plus. Les pages > 34 sont vides.
#
# LA PARADE : PARTITIONNER. On decoupe chaque requete par TRANCHES D'ETOILES. Chaque tranche
# a son propre quota de 1000. `topic:market-making stars:10..50` et `topic:market-making
# stars:>1000` sont deux requetes DIFFERENTES pour GitHub -> 2000 resultats accessibles au lieu
# de 1000. Avec 5 tranches, on multiplie la couverture par 5.
#
# ET ON CHERCHE AUSSI EN TEXTE LIBRE : beaucoup de repos excellents n'ont AUCUN topic
# (l'auteur n'a jamais pris la peine d'en mettre). Les chercher par topic seul, c'est les rater.
# =============================================================================================

SUJETS_DEFAUT = [
    # --- notre venue
    "hyperliquid", "hyperliquid-bot", "hyperliquid-sdk", "perp-dex", "perpetual-futures",
    "perpetuals", "dydx", "gmx", "drift-protocol",
    # --- les strategies qui nous concernent
    "funding-rate-arbitrage", "funding-rate", "basis-trading", "delta-neutral",
    "market-neutral", "statistical-arbitrage", "pairs-trading", "cointegration",
    "triangular-arbitrage", "cross-exchange-arbitrage", "crypto-arbitrage",
    # --- market making et microstructure
    "market-making", "market-maker", "market-maker-bot", "avellaneda-stoikov",
    "market-microstructure", "order-book", "orderbook", "orderflow", "order-flow-imbalance",
    "limit-order-book", "matching-engine", "queue-position",
    # --- haute frequence et execution
    "high-frequency-trading", "hft", "low-latency-trading", "algorithmic-trading",
    "execution-algorithms", "smart-order-routing", "vwap", "twap",
    # --- validation, la ou on a le plus peche
    "backtesting", "backtesting-engine", "backtest", "walk-forward",
    "quantitative-finance", "quantitative-trading", "quant", "alpha-research",
    # --- le flux pre-execution
    "mev", "mempool", "front-running", "liquidation-bot", "liquidations",
]

# Recherches en TEXTE LIBRE : attrape les repos sans topic (la majorite des petits projets).
REQUETES_TEXTE = [
    "hyperliquid market maker", "hyperliquid arbitrage", "hyperliquid funding",
    "hyperliquid liquidation", "hyperliquid mempool", "hyperliquid node",
    "perpetual funding arbitrage bot", "delta neutral funding bot",
    "queue position backtest", "adverse selection market making",
    "limit order book simulator", "market impact model crypto",
    "orderbook imbalance signal", "maker taker fee optimizer",
    "cash and carry crypto", "basis trade perpetual",
]

# TRANCHES D'ETOILES : chacune a son propre quota de 1000 chez GitHub.
# On ignore < 5 etoiles : 49 repos ecartes pour « personne ne l'a jamais utilise » a la 1re moisson.
TRANCHES_ETOILES = ["5..20", "21..60", "61..200", "201..800", ">800"]

LICENCES_ADAPTABLES = {"mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc", "unlicense",
                       "mpl-2.0", "0bsd"}
LICENCES_CONTAMINANTES = {"gpl-2.0", "gpl-3.0", "agpl-3.0", "lgpl-2.1", "lgpl-3.0"}


@dataclass
class Repo:
    nom: str
    url: str
    description: str
    etoiles: int
    forks: int
    langage: str
    licence: str
    pousse_le: str
    sujets: list[str] = field(default_factory=list)

    # --- verdicts calcules
    @property
    def statut_licence(self) -> str:
        lic = (self.licence or "").lower()
        if not lic or lic in {"none", "other"}:
            return "INTOUCHABLE"          # defaut = tous droits reserves
        if lic in LICENCES_CONTAMINANTES:
            return "IDEE_SEULEMENT"       # GPL : copier = tout HyperSmart passe en GPL
        if lic in LICENCES_ADAPTABLES:
            return "ADAPTABLE"
        return "A_VERIFIER"

    @property
    def mois_depuis_maj(self) -> float:
        try:
            d = datetime.fromisoformat(self.pousse_le.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return 999.0
        return (datetime.now(timezone.utc) - d).days / 30.44

    @property
    def drapeaux(self) -> list[str]:
        """Les signaux qui ont FAIT PERDRE DU TEMPS aujourd'hui. On les leve automatiquement."""
        d = []
        texte = ("%s %s" % (self.nom, self.description or "")).lower()
        if self.etoiles == 0 and self.forks == 0:
            d.append("PERSONNE_NE_L_A_JAMAIS_UTILISE")
        if self.mois_depuis_maj > 18:
            d.append("ABANDONNE_%.0f_MOIS" % self.mois_depuis_maj)
        if self.statut_licence == "INTOUCHABLE":
            d.append("AUCUNE_LICENCE")
        # affirmations IMPOSSIBLES sur Hyperliquid (verifiees contre la doc officielle)
        if "rebate" in texte and "hyperliquid" in texte:
            d.append("PROMET_DES_REBATES_QUI_N_EXISTENT_PAS_SUR_HL")
        if "polymarket" in texte or "prediction market" in texte or "kalshi" in texte:
            d.append("MAUVAIS_MARCHE_prediction_markets")
        if "solana" in texte and ("copy" in texte or "mirror" in texte):
            d.append("MAUVAISE_CHAINE_ET_ZONE_MORTE_copy_trading")
        if "guaranteed" in texte or "risk-free" in texte or "100% profit" in texte:
            d.append("PROMESSE_DE_GAIN_MENSONGERE")

        # ANOMALIE FORKS >> ETOILES (ajoutee apres la 1re moisson reelle, 2026-07-12)
        #
        # Reperee sur du VRAI : taprwhiz/hyperliquid-ai-agent = 141 etoiles, 1122 FORKS (x8).
        #                       SigmaTradeLabs/hyperliquid-trading-bot = 3 etoiles, 846 FORKS (x282).
        #
        # Un outil qu'on trouve BON, on le STAR (1 clic, ca dit « utile »).
        # Un outil qu'on FORK massivement sans le star, c'est qu'on ne l'admire pas : on
        # l'EXECUTE. Ferme a airdrop, arnaque, devoir de cours, ou bot a inscriptions.
        # Le ratio est un detecteur de bruit BEAUCOUP plus fiable que le nombre d'etoiles.
        if self.forks > max(30, self.etoiles * 3):
            d.append("FORKS_x%.0f_LES_ETOILES_ANOMALIE" % (self.forks / max(self.etoiles, 1)))
        return d

    @property
    def priorite(self) -> float:
        """Ce qui merite qu'un HUMAIN y passe une heure. Ce n'est PAS un score de qualite d'idee."""
        if any(f.startswith(("MAUVAIS_MARCHE", "MAUVAISE_CHAINE", "PROMESSE_DE_GAIN")) for f in self.drapeaux):
            return 0.0
        p = 0.0
        p += min(self.etoiles, 5000) ** 0.5          # adoption reelle, plafonnee
        p += min(self.forks, 1000) ** 0.5 * 2.0      # forker = avoir voulu s'en servir
        if self.statut_licence == "ADAPTABLE":
            p *= 1.5                                  # on peut VRAIMENT s'en servir
        elif self.statut_licence == "INTOUCHABLE":
            p *= 0.3
        if self.mois_depuis_maj > 24:
            p *= 0.4
        if "hyperliquid" in ("%s %s" % (self.nom, self.description or "")).lower():
            p *= 2.0                                  # notre venue
        return p

    def as_dict(self) -> dict:
        return {
            "nom": self.nom, "url": self.url, "description": self.description,
            "etoiles": self.etoiles, "forks": self.forks, "langage": self.langage,
            "licence": self.licence, "statut_licence": self.statut_licence,
            "mois_depuis_maj": round(self.mois_depuis_maj, 1),
            "drapeaux": self.drapeaux, "priorite": round(self.priorite, 1),
            "sujets": self.sujets,
        }


# LIMITE DE DEBIT — corrigee apres le 1er lancement reel (2026-07-12).
#
# L'API de RECHERCHE GitHub est bien plus stricte que l'API normale :
#     sans token :  10 requetes / minute
#     avec token :  30 requetes / minute
#
# Ma 1re version dormait 2,5 s -> 24 req/min -> 403 des le 6e sujet. Et pire : sur un 403,
# elle RENDAIT UNE LISTE VIDE et passait a la suite -> la page etait PERDUE en silence.
# Une donnee perdue en silence, c'est exactement ce qu'on traque dans ce projet.
#
# Se faire limiter = MOINS de donnees, pas plus. On respecte, et on REESSAYE.
PAUSE_SANS_TOKEN = 7.0     # ~8,5 req/min, sous la barre des 10
PAUSE_AVEC_TOKEN = 2.5     # ~24 req/min, sous la barre des 30
ESSAIS_MAX = 4


def _entetes() -> dict:
    """Un token GitHub triple le debit. Optionnel : GITHUB_TOKEN dans l'environnement.

    LECTURE SEULE : un token `public_repo` en lecture suffit. Aucun droit d'ecriture requis.
    """
    h = {"Accept": "application/vnd.github+json", "User-Agent": "hypersmart-research"}
    jeton = os.environ.get("GITHUB_TOKEN", "").strip()
    if jeton:
        h["Authorization"] = "Bearer %s" % jeton
    return h


def _pause() -> float:
    return PAUSE_AVEC_TOKEN if os.environ.get("GITHUB_TOKEN", "").strip() else PAUSE_SANS_TOKEN


def _chercher(requete: str, page: int) -> list[Repo]:
    """`requete` est une requete GitHub COMPLETE (topic:x stars:a..b, ou du texte libre)."""
    q = urllib.parse.urlencode({
        "q": requete, "sort": "stars", "order": "desc",
        "per_page": 100, "page": page,       # 100 = le MAXIMUM autorise (on prenait 30 : 3x moins)
    })
    req = urllib.request.Request("%s?%s" % (API, q), headers=_entetes())

    # BUG CORRIGE (2026-07-12) -- UNE ERREUR DANS LE CODE QUI GERE LES ERREURS.
    #
    # En renommant le parametre `sujet` -> `requete`, j'avais laisse `sujet` dans les messages
    # d'erreur. Resultat : au 1er 403, le gestionnaire d'exception plantait lui-meme sur un
    # NameError -> le backoff ne s'executait JAMAIS -> le programme mourait au 3e appel.
    #
    # LE PIRE ENDROIT POSSIBLE POUR UN BUG : le chemin qui n'est emprunte QUE quand ca va mal.
    # Il ne se voit pas tant que tout va bien, et il frappe exactement quand on a besoin de lui.
    data = None
    for essai in range(1, ESSAIS_MAX + 1):
        try:
            with urllib.request.urlopen(req, timeout=25.0) as r:
                data = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                # GITHUB NOUS DIT EXACTEMENT QUAND REESSAYER. On arrete de deviner.
                #
                #   Retry-After          : secondes a attendre (le plus fiable)
                #   X-RateLimit-Reset    : timestamp unix du reset du quota
                #
                # Deviner avec un backoff exponentiel, c'est attendre trop (on perd du temps)
                # ou pas assez (on se refait jeter). La source nous donne la reponse : on la LIT.
                attente = None
                try:
                    h = exc.headers
                    if h.get("Retry-After"):
                        attente = float(h["Retry-After"]) + 1.0
                    elif h.get("X-RateLimit-Reset"):
                        attente = max(0.0, float(h["X-RateLimit-Reset"]) - time.time()) + 1.0
                except (TypeError, ValueError, AttributeError):
                    attente = None
                if attente is None:
                    attente = 25.0 * (2 ** (essai - 1))    # repli : 25s, 50s, 100s, 200s
                attente = min(attente, 90.0)               # jamais plus de 90 s d'un coup

                print("    [!] quota GitHub epuise (%s) - attente %.0f s (dit par GitHub), "
                      "essai %d/%d  [%s]"
                      % (exc.code, attente, essai, ESSAIS_MAX, requete[:34]))
                time.sleep(attente)
                continue
            print("    [!] HTTP %s - page ABANDONNEE  [%s p%d]" % (exc.code, requete[:40], page))
            return []
        except Exception as exc:  # noqa: BLE001
            print("    [!] %s: %s  [%s p%d]" % (type(exc).__name__, exc, requete[:40], page))
            time.sleep(5.0)
            continue

    if data is None:
        print("    [!] PERDUE apres %d essais  [%s p%d]" % (ESSAIS_MAX, requete[:40], page))
        return []

    out = []
    for it in data.get("items") or []:
        lic = ((it.get("license") or {}) or {}).get("key") or ""
        out.append(Repo(
            nom=str(it.get("full_name") or ""),
            url=str(it.get("html_url") or ""),
            description=str(it.get("description") or "")[:180],
            etoiles=int(it.get("stargazers_count") or 0),
            forks=int(it.get("forks_count") or 0),
            langage=str(it.get("language") or "?"),
            licence=lic,
            pousse_le=str(it.get("pushed_at") or ""),
            sujets=list(it.get("topics") or []),
        ))
    return out


def _plan_de_recherche(sujets: list[str]) -> list[tuple[str, str]]:
    """Construit le plan : (etiquette, requete GitHub complete).

    BUG CORRIGE (2026-07-12) -- MON PLAN COMMENCAIT PAR LE DESERT.
    ---------------------------------------------------------------
    Ma 1re version attaquait par la tranche `stars:>800`, en croyant que « les gros repos =
    les plus fertiles ». FAUX, et l'inverse de la verite :

        topic:hyperliquid       stars:>800   ->   4 repos
        topic:hyperliquid-bot   stars:>800   ->   0
        topic:perp-dex          stars:>800   ->   0

    Les repos a plus de 800 etoiles sont les plus RARES. Un budget de 5 min (~42 requetes)
    etait entierement brule sur des tranches VIDES, sans jamais atteindre les fertiles.

    ET J'AVAIS SUR-CONCU. La partition par etoiles ne sert QU'A depasser le plafond de 1000
    resultats de GitHub. C'est un RAFFINEMENT, pas la strategie principale : une requete
    simple `topic:X` triee par etoiles rend deja les 300 meilleurs en 3 pages.

    NOUVEAU PLAN, du plus rentable au moins rentable :
      1. requete SIMPLE par sujet    -> les 300 meilleurs de chaque topic. Le gros du butin.
      2. texte libre                 -> les repos SANS topic (la majorite des petits projets).
      3. tranches d'etoiles BASSES   -> creuser sous les 300 premiers, la ou il y a du monde.

    Si le budget expire, on a deja pris le meilleur — au lieu d'avoir laboure le desert.
    """
    plan: list[tuple[str, str]] = []

    # 1) LE PLUS RENTABLE : une requete simple par sujet, triee par etoiles.
    #    3 pages x 100 = les 300 meilleurs repos du topic. C'est la que tout se joue.
    for s in sujets:
        plan.append(("topic:%s" % s, "topic:%s" % s))

    # 2) TEXTE LIBRE : attrape les repos qui n'ont AUCUN topic (tres frequent).
    for t in REQUETES_TEXTE:
        plan.append(("texte: %s" % t, t))

    # 3) CREUSER PLUS BAS : les tranches d'etoiles, des PLUS PEUPLEES aux plus rares.
    #    Utile seulement pour les gros topics (>1000 resultats) et si le budget le permet.
    for tranche in TRANCHES_ETOILES:            # 5..20 d'abord (le plus peuple)
        for s in sujets:
            plan.append(("topic:%s [%s]" % (s, tranche), "topic:%s stars:%s" % (s, tranche)))

    return plan


def main() -> int:
    ap = argparse.ArgumentParser(description="Moissonner et TRIER des repos GitHub.")
    ap.add_argument("--sujets", type=str, default="", help="liste separee par des virgules")
    ap.add_argument("--pages", type=int, default=3, help="pages de 100 repos par requete")
    ap.add_argument("--minutes", type=float, default=5.0,
                    help="BUDGET DE TEMPS : cherche sans s'arreter jusque-la (defaut 5 min)")
    ap.add_argument("--sans-concepts", action="store_true",
                    help="s'arreter apres la phase 1 (ne pas grepper les README)")
    ap.add_argument("--phase2-seule", action="store_true",
                    help="SAUTER la moisson, grepper les README deja recoltes")
    ap.add_argument("--min-concepts", type=int, default=3,
                    help="phase 2 : seuil pour meriter une lecture humaine (defaut 3)")
    args = ap.parse_args()

    # --- phase 2 seule : on saute tout le ratissage
    if args.phase2_seule:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import moissonner_concepts as mc   # noqa: PLC0415
        sys.argv = ["moissonner_concepts", "--min-concepts", str(args.min_concepts)]
        return mc.main()

    sujets = [s.strip() for s in args.sujets.split(",") if s.strip()] or SUJETS_DEFAUT
    plan = _plan_de_recherche(sujets)
    avec_jeton = bool(os.environ.get("GITHUB_TOKEN", "").strip())
    budget = max(0.5, args.minutes) * 60.0

    print("\n" + "=" * 88)
    print("  MOISSONNEUR GITHUB — recherche EN CONTINU pendant %.0f minutes" % args.minutes)
    print("  %d sujets x %d tranches d'etoiles + %d requetes en texte libre = %d requetes possibles"
          % (len(sujets), len(TRANCHES_ETOILES), len(REQUETES_TEXTE), len(plan)))
    print("  100 repos par page, %d pages -> jusqu'a %d repos par requete."
          % (args.pages, args.pages * 100))
    print()
    print("  POURQUOI DES TRANCHES D'ETOILES : l'API GitHub PLAFONNE a 1000 resultats par")
    print("  requete. Chercher plus longtemps sur la meme requete ne rend RIEN de plus.")
    print("  En partitionnant (stars:5..20, 21..60, ...), chaque tranche a son propre quota.")
    print()
    # --- L'ARITHMETIQUE, EN FACE. Aucune fausse promesse sur ce que le budget peut faire.
    req_possibles = int(budget / _pause())
    print("  Debit : %s - %.1f s entre requetes"
          % ("AVEC token (30 req/min)" if avec_jeton else "SANS token (10 req/min)", _pause()))
    print("  En %.0f min : ~%d requetes sur les %d du plan (%.0f pct du plan)."
          % (args.minutes, req_possibles, len(plan),
             100.0 * req_possibles / max(1, len(plan))))
    if not avec_jeton:
        print()
        print("  >>> SANS TOKEN, le plan COMPLET prendrait %.0f min. AVEC un token : %.0f min."
              % (len(plan) * PAUSE_SANS_TOKEN / 60.0, len(plan) * PAUSE_AVEC_TOKEN / 60.0))
        print("  >>> Un token GitHub en LECTURE SEULE triple le debit (10 -> 30 req/min).")
        print("  >>>   1. github.com/settings/tokens  (aucune permission a cocher)")
        print("  >>>   2. set GITHUB_TOKEN=ghp_xxxxx")
        print("  >>>   3. relancer")
        print()
    print("  Ctrl-C a tout moment : on trie et on ecrit ce qui a ete recolte.")
    print("=" * 88 + "\n")

    vus: dict[str, Repo] = {}
    t0 = time.monotonic()
    n_req = 0
    epuisees = 0

    try:
        for etiquette, requete in plan:
            if time.monotonic() - t0 >= budget:
                print("\n  [budget de %.0f min atteint — on s'arrete proprement]" % args.minutes)
                break
            n0 = len(vus)
            for page in range(1, args.pages + 1):
                if time.monotonic() - t0 >= budget:
                    break
                lot = _chercher(requete, page)
                n_req += 1
                for r in lot:
                    if r.nom and r.nom not in vus:
                        vus[r.nom] = r
                time.sleep(_pause())
                if len(lot) < 100:      # page incomplete = requete EPUISEE, inutile d'insister
                    epuisees += 1
                    break
            gain = len(vus) - n0
            reste = max(0.0, budget - (time.monotonic() - t0))
            print("  %-34s +%-4d (total %4d)   reste %4.1f min"
                  % (etiquette[:34], gain, len(vus), reste / 60.0))
    except KeyboardInterrupt:
        print("\n  [interrompu — on trie et on ecrit ce qui a ete recolte]")

    ecoule = (time.monotonic() - t0) / 60.0
    print("\n  %d requetes en %.1f min — %d repos uniques (%d requetes epuisees)"
          % (n_req, ecoule, len(vus), epuisees))

    repos = sorted(vus.values(), key=lambda r: -r.priorite)
    retenus = [r for r in repos if r.priorite > 0]
    ecartes = [r for r in repos if r.priorite == 0]

    print("\n" + "-" * 84)
    print("  %d repos uniques — %d a examiner, %d ecartes automatiquement"
          % (len(repos), len(retenus), len(ecartes)))
    print("-" * 84 + "\n")

    print("  %-42s %6s %6s %-16s %s" % ("repo", "etoil.", "forks", "licence", "drapeaux"))
    print("  %-42s %6s %6s %-16s %s" % ("-" * 42, "-" * 6, "-" * 6, "-" * 16, "-" * 20))
    for r in retenus[:40]:
        print("  %-42s %6d %6d %-16s %s"
              % (r.nom[:42], r.etoiles, r.forks, r.statut_licence,
                 ",".join(r.drapeaux)[:30] or "-"))

    if ecartes:
        print("\n  ECARTES AUTOMATIQUEMENT (%d) — motifs :" % len(ecartes))
        motifs: dict[str, int] = {}
        for r in ecartes:
            for f in r.drapeaux:
                cle = f.split("_")[0] + "_" + (f.split("_")[1] if "_" in f else "")
                motifs[cle] = motifs.get(cle, 0) + 1
        for m, n in sorted(motifs.items(), key=lambda x: -x[1]):
            print("      %-40s %d" % (m, n))

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps([r.as_dict() for r in repos], indent=2, ensure_ascii=False),
                      encoding="utf-8")
    print("\n  rapport : %s\n" % SORTIE.relative_to(ROOT))

    # =========================================================================================
    # PHASE 2 — enchainee DANS LE MEME POINT D'ENTREE (fusion demandee par Flo, 2026-07-12).
    #
    # Avant : deux .cmd et deux scripts. Une demi-fusion, c'est PIRE que rien — deux points
    # d'entree, et personne ne sait lequel fait foi. C'est exactement la pathologie qu'on
    # traque dans ce projet : deux chemins qui se contredisent.
    #
    # Desormais : ratisser PUIS lire-sans-lire, en une seule commande. `--sans-concepts`
    # pour s'arreter apres la phase 1.
    # =========================================================================================
    if not args.sans_concepts:
        print("\n" + "#" * 88)
        print("  PHASE 2 / 2 — LIRE SANS LIRE : grep des README sur les concepts MANQUANTS")
        print("#" * 88)
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import moissonner_concepts as mc   # noqa: PLC0415
            sys.argv = ["moissonner_concepts", "--min-concepts", str(args.min_concepts)]
            mc.main()
        except Exception as exc:  # noqa: BLE001
            print("\n  [!] Phase 2 impossible : %s: %s" % (type(exc).__name__, exc))
            print("      La phase 1 est SAUVEGARDEE. Relance avec --phase2-seule.\n")

    print("  " + "-" * 80)
    print("  RAPPEL : un repo bien classe ici n'est PAS une idee qui marche.")
    print("  C'est un repo qui MERITE QU'UN HUMAIN Y PASSE UNE HEURE.")
    print("  Le jugement de l'idee reste notre travail — et il se fait par la MESURE.")
    print("  " + "-" * 80 + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Interrompu.\n")
        sys.exit(130)
