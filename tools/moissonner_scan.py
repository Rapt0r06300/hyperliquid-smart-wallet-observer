r"""LE SCAN v5 — *chercher DANS LE CODE, descendre a ZERO etoile, et faire tomber le plafond.*

═══════════════════════════════════════════════════════════════════════════════════════════════
LES 5 DEFAUTS DU SCAN, ET CE QU'ILS COUTAIENT
═══════════════════════════════════════════════════════════════════════════════════════════════

  🔴 **1. IL S'INTERDISAIT LES REPOS SOUS 5 ETOILES.**  *Le plus ironique.*
        `TRANCHES_ETOILES = ["5..20", ...]`   # « On ignore < 5 etoiles »
        Or la moisson a **MESURE** que les 4 repos les plus **exactement sur cible** avaient
        **1, 2, 3 et 3 etoiles.**
        ***Le scan ecartait a l'entree exactement le profil qu'on a mesure comme le meilleur.***
        (Meme prejuge que le tri -- il vivait aussi dans le scan. **19e forme de la maladie.**)

  🔴 **2. LE PLAFOND DE 1 000 N'ETAIT FRANCHI QUE x5.**
        Les tranches d'etoiles donnent 5 000 resultats. La **partition par DATE** en donne
        **autant qu'on veut** : `created:2024-01-01..2024-03-31` a **son propre quota de 1 000**.
        6 ans x 4 trimestres = **24 tranches = 24 000 resultats** par sujet.

  🔴 **3. IL NE CHERCHAIT JAMAIS DANS LE CODE.**  🔑 *La vraie reponse a « chercher partout ».*
        `/search/code` regarde **A L'INTERIEUR des fichiers**. Elle trouve un repo **sans topic,
        sans etoile, dont le README ne dit rien**, mais dont le CODE contient `qty_ahead`.
        ***Le README est la page de vente. Le code est la verite.***

  🔴 **4. `sort=stars` RE-COMMETTAIT LE DEFAUT 1 A CHAQUE REQUETE.**
        Avec un plafond a 1 000, trier par etoiles = ne voir **que les gros**.

  🔴 **5. AUCUNE REPRISE.** Un scan de 3 h qui meurt sur le quota perdait **tout**.
        -> etat sur disque. **Ctrl-C, coupure, quota : on reprend ou on s'etait arrete.**

🔒 100 % LECTURE SEULE. Aucun clone. Aucun code execute. Aucun ordre reel.
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
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research.github_scan_plan import (  # noqa: E402
    deduplique,
    plan_de_scan,
    resume,
)

SORTIE = RACINE / "data" / "reports" / "github_moisson.json"
ETAT = RACINE / "data" / "reports" / "scan_etat.json"      # 🔑 la REPRISE

API_REPOS = "https://api.github.com/search/repositories"
API_CODE = "https://api.github.com/search/code"

# Les vraies limites GitHub. *Se faire bannir = MOINS de donnees, pas plus.*
PAUSE_REPOS = 2.1        # 30 req/min avec token
PAUSE_CODE = 6.5         # 10 req/min avec token -- /search/code est bien plus severe

# Repris du scan v4 (les sujets ne changent pas ; c'est la STRATEGIE qui change).
SUJETS = [
    "hyperliquid", "hyperliquid-bot", "hyperliquid-sdk", "perp-dex", "perpetual-futures",
    "perpetuals", "dydx", "gmx", "drift-protocol",
    "funding-rate-arbitrage", "funding-rate", "basis-trading", "delta-neutral",
    "market-neutral", "statistical-arbitrage", "pairs-trading", "cointegration",
    "triangular-arbitrage", "cross-exchange-arbitrage", "crypto-arbitrage",
    "market-making", "market-maker", "market-maker-bot", "avellaneda-stoikov",
    "market-microstructure", "order-book", "orderbook", "orderflow", "order-flow-imbalance",
    "limit-order-book", "matching-engine", "queue-position",
    "high-frequency-trading", "hft", "low-latency-trading", "algorithmic-trading",
    "execution-algorithms", "smart-order-routing", "vwap", "twap",
    "backtesting", "backtesting-engine", "backtest", "walk-forward",
    "quantitative-finance", "quantitative-trading", "quant", "alpha-research",
    "mev", "mempool", "front-running", "liquidation-bot", "liquidations",
]
TEXTE = [
    "hyperliquid market maker", "hyperliquid arbitrage", "hyperliquid funding",
    "hyperliquid liquidation", "hyperliquid mempool", "hyperliquid node",
    "perpetual funding arbitrage bot", "delta neutral funding bot",
    "queue position backtest", "adverse selection market making",
    "limit order book simulator", "market impact model crypto",
    "orderbook imbalance signal", "maker taker fee optimizer",
    "cash and carry crypto", "basis trade perpetual",
    "awesome quant", "awesome market making",     # 🌐 les CARTES AU TRESOR
]


def _entetes() -> dict[str, str]:
    h = {"User-Agent": "hypersmart-research",
         "Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}
    j = os.environ.get("GITHUB_TOKEN", "").strip()
    if j:
        h["Authorization"] = "Bearer %s" % j
    return h


def _appel(url: str) -> dict[str, Any] | None:
    """`None` = **je n'ai pas su lire**. On respecte le 429 : *se faire bannir = moins de donnees.*"""
    for essai in range(3):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=_entetes()), timeout=30.0
            ) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                attente = 30.0 * (essai + 1)
                print("     ⏳ quota (%d) -> pause %.0f s" % (exc.code, attente))
                time.sleep(attente)
                continue
            if exc.code == 422:
                return {}          # requete refusee par GitHub (syntaxe) -> **on le dit, on passe**
            return None
        except Exception:  # noqa: BLE001
            time.sleep(3.0)
    return None


def _charger_etat() -> dict[str, Any]:
    """🔑 **LA REPRISE.** *Un scan de 3 h qui meurt sur le quota ne doit pas tout perdre.*"""
    if ETAT.exists():
        try:
            return json.loads(ETAT.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"faites": [], "repos": {}}


def _sauver(etat: dict[str, Any]) -> None:
    ETAT.parent.mkdir(parents=True, exist_ok=True)
    ETAT.write_text(json.dumps(etat, ensure_ascii=False), encoding="utf-8")


def main() -> int:  # noqa: C901, PLR0912, PLR0915
    ap = argparse.ArgumentParser(description="LE SCAN v5 — code + zero etoile + partition dates")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--sans-code", action="store_true",
                    help="sauter la recherche DANS LE CODE (elle exige un token)")
    ap.add_argument("--sans-dates", action="store_true")
    ap.add_argument("--repartir-de-zero", action="store_true",
                    help="ignorer l'etat precedent (par defaut : ON REPREND)")
    args = ap.parse_args()

    jeton = os.environ.get("GITHUB_TOKEN", "").strip()

    print("=" * 100)
    print("  LE SCAN v5 — *chercher DANS LE CODE, descendre a ZERO etoile, faire tomber le plafond*")
    print("=" * 100)

    avec_code = not args.sans_code
    if avec_code and not jeton:
        print("\n  🔴 **`/search/code` EXIGE un token GitHub.** Sans lui, elle est **IMPOSSIBLE**.")
        print("     *Je ne fais pas semblant de chercher dans le code : je le desactive et je le dis.*")
        print("     `set GITHUB_TOKEN=ghp_...` (lecture seule, 5 min a creer) -> et le scan")
        print("     cherchera **dans la verite** au lieu de la page de vente.")
        avec_code = False
    if not jeton:
        print("\n  ⚠️ sans token : **60 requetes/heure** au lieu de 5 000. Le scan sera **bref**.")

    plan = deduplique(plan_de_scan(SUJETS, TEXTE,
                                   avec_code=avec_code, avec_dates=not args.sans_dates))
    r = resume(plan)
    print("\n  plan : **%d requetes** (%d dans le CODE · %d sur les repos)"
          % (r["n_requetes"], r["n_code"], r["n_repo"]))
    print("  %s" % r["plafond_contourne"])
    print("  budget demande : **%.0f min** (le plan complet en prendrait %.0f)"
          % (args.minutes, r["minutes_estimees"]))

    etat = {"faites": [], "repos": {}} if args.repartir_de_zero else _charger_etat()
    faites: set[str] = set(etat.get("faites") or [])
    repos: dict[str, Any] = dict(etat.get("repos") or {})
    if faites:
        print("\n  🔑 **REPRISE** : %d requetes deja faites, %d repos deja trouves."
              % (len(faites), len(repos)))
        print("     *Un scan de 3 h qui meurt sur le quota ne doit pas tout perdre.*")

    debut = time.time()
    limite = args.minutes * 60.0
    n_neufs = 0
    arrete = False

    try:
        for i, req in enumerate(plan, 1):
            cle = "%s|%s|%s" % (req.genre, req.q, req.tri)
            if cle in faites:
                continue
            if time.time() - debut > limite:
                print("\n  ⏹️ **budget de temps atteint.** *On trie et on ecrit ce qu'on a.*")
                print("     Relancer reprendra **exactement ici** (%d/%d)." % (i, len(plan)))
                arrete = True
                break

            if req.genre == "code":
                url = ("%s?q=%s&per_page=100"
                       % (API_CODE, urllib.parse.quote(req.q)))
            else:
                tri = ("&sort=%s&order=desc" % req.tri) if req.tri else ""
                url = ("%s?q=%s%s&per_page=100"
                       % (API_REPOS, urllib.parse.quote(req.q), tri))

            d = _appel(url)
            time.sleep(PAUSE_CODE if req.genre == "code" else PAUSE_REPOS)

            if d is None:
                continue                      # echec reseau -> **on ne marque PAS comme faite**

            neufs = 0
            for it in (d.get("items") or []):
                if req.genre == "code":
                    dep = (it.get("repository") or {})
                    nom = str(dep.get("full_name") or "")
                    etoiles = 0
                    lic = None
                else:
                    nom = str(it.get("full_name") or "")
                    etoiles = int(it.get("stargazers_count") or 0)
                    lic = (it.get("license") or {}).get("spdx_id")
                if not nom:
                    continue
                if nom not in repos:
                    repos[nom] = {
                        "nom": nom, "etoiles": etoiles, "licence": lic,
                        "trouve_par": req.genre,
                        "pourquoi": req.pourquoi,
                    }
                    neufs += 1
                    n_neufs += 1
                elif req.genre == "code":
                    # 🔑 trouve DANS LE CODE : c'est un signal FORT. On le note.
                    repos[nom]["trouve_dans_le_code"] = req.q

            faites.add(cle)
            if neufs or req.genre == "code":
                marque = "🔑 CODE" if req.genre == "code" else "      "
                print("  %s %-52s +%-4d  (total %d)" % (marque, req.q[:52], neufs, len(repos)))

            if i % 25 == 0:
                _sauver({"faites": sorted(faites), "repos": repos})

    except KeyboardInterrupt:
        print("\n\n  ⏹️ **Ctrl-C.** *On trie et on ecrit ce qui a ete recolte.* Rien n'est perdu.")
        arrete = True

    _sauver({"faites": sorted(faites), "repos": repos})

    # ── LE RESULTAT ───────────────────────────────────────────────────────────────────────────
    par_code = [v for v in repos.values() if v.get("trouve_dans_le_code")]
    petits = [v for v in repos.values() if int(v.get("etoiles") or 0) < 5]

    print("\n" + "=" * 100)
    print("  RESULTAT")
    print("=" * 100)
    print("\n  repos : **%d**  (+%d ce coup-ci)" % (len(repos), n_neufs))
    print("  requetes faites : %d / %d%s"
          % (len(faites), len(plan), "  ⏸️ **reprenable**" if arrete else ""))
    print("\n  🔑 trouves **DANS LE CODE** (sans topic, sans etoile, README muet) : **%d**"
          % len(par_code))
    print("     *Le README est la page de vente. Le code est la verite.*")
    print("\n  🔑 repos a **moins de 5 etoiles** : **%d**" % len(petits))
    print("     ***L'ancien scan les EXCLUAIT TOUS.*** Or les 4 repos les plus exactement sur")
    print("     cible avaient **1, 2, 3 et 3 etoiles**.")

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps({
        "trouvailles": sorted(repos.values(), key=lambda x: -int(x.get("etoiles") or 0)),
        "n_total": len(repos),
        "n_trouves_dans_le_code": len(par_code),
        "n_sous_5_etoiles": len(petits),
        "requetes_faites": len(faites),
        "requetes_au_plan": len(plan),
        "reprenable": arrete,
        "lecture_seule": True, "real_execution": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n  -> %s" % SORTIE)
    print("  -> %s  *(l'etat : relancer REPREND ici)*" % ETAT)
    print("\n  🔒 Lecture seule. Aucun clone. Aucun code execute.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
