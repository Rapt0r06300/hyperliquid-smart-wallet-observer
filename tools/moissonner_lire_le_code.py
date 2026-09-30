r"""PHASE 3 — **LIRE LE CODE.** *Le README est du marketing ; le code est la vérité.*

═══════════════════════════════════════════════════════════════════════════════════════════════
LE CHIFFRE QUI JUSTIFIE CETTE PHASE
═══════════════════════════════════════════════════════════════════════════════════════════════

    **8 passes de tri** sur **5 617 repos**              ->  **3 idées**
    **20 minutes** à lire le code d'**UN SEUL** repo     ->  **5 bugs** dans notre simu

        (hftbacktest : fill « 10 % du flux » **inventé** · double comptage des fills ·
         rejet d'ordre jamais modélisé · latence = un **triplet**, pas un nombre ·
         `order.maker` déduit de l'exécution, pas de l'intention)

    ***TRIER NE REMPLACERA JAMAIS LIRE.***

Le moissonneur savait **classer**. Il ne savait pas **ouvrir un fichier**. Il s'arrêtait au
README — c'est-à-dire à la **page de vente**.

    *Une capacité présente (on avait les repos), un chaînon manquant (on ne lisait pas le code),
    personne qui se plaint.* **Encore.**

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUE CETTE PHASE PRODUIT
═══════════════════════════════════════════════════════════════════════════════════════════════

Pas un classement. **UNE LISTE DE LECTURE** :

    repo · fichier · **ligne** · le code · **pourquoi ça nous concerne**

C'est le seul livrable qui a jamais produit quelque chose dans ce projet.

🔒 100 % LECTURE SEULE. Aucun clone. **Aucun code téléchargé n'est exécuté. Jamais.**
   On lit du texte. On ne lance rien.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research.github_signals import (  # noqa: E402
    analyser,
    fichiers_a_lire,
    liste_de_lecture,
    score,
)

MOISSON = RACINE / "data" / "reports" / "github_concepts.json"
SORTIE_JSON = RACINE / "data" / "reports" / "github_liste_de_lecture.json"
SORTIE_MD = RACINE / "data" / "reports" / "LISTE_DE_LECTURE.md"

PAUSE = 0.8               # on respecte la source : se faire bannir = MOINS de donnees, pas plus
MAX_OCTETS = 400_000      # au-dela, ce n'est plus du code : c'est de la donnee


def _entetes(brut: bool = False) -> dict[str, str]:
    h = {
        "User-Agent": "hypersmart-research",
        "Accept": "application/vnd.github.raw+json" if brut else "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    jeton = os.environ.get("GITHUB_TOKEN", "").strip()
    if jeton:
        h["Authorization"] = "Bearer %s" % jeton
    return h


def _get(url: str, *, brut: bool = False) -> str | None:
    """`None` = **je n'ai pas su lire**. *Jamais une chaine vide qui ferait croire a un fichier vide.*"""
    try:
        req = urllib.request.Request(url, headers=_entetes(brut))
        with urllib.request.urlopen(req, timeout=25.0) as r:
            data = r.read(MAX_OCTETS)
            return data.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            time.sleep(15.0)
        return None
    except Exception:  # noqa: BLE001
        return None


def _readme(repo: str) -> str | None:
    """🔴 Par l'**API** — elle resout nom + extension + branche.

    C'est le bug qui avait perdu **235 repos EN SILENCE**, dont **hftbacktest (4 270 etoiles,
    notre cible n°1)**, backtrader (22 413) et zipline (19 967).
    L'ancienne version ne tentait que `README.md` sur `main`/`master`.
    """
    return _get("https://api.github.com/repos/%s/readme" % repo, brut=True)


def _arbre(repo: str) -> list[str]:
    """Les chemins des fichiers du repo. **On ne clone pas** : on lit l'index."""
    meta = _get("https://api.github.com/repos/%s" % repo)
    if not meta:
        return []
    try:
        branche = json.loads(meta).get("default_branch") or "main"
    except Exception:  # noqa: BLE001
        branche = "main"

    t = _get("https://api.github.com/repos/%s/git/trees/%s?recursive=1" % (repo, branche))
    if not t:
        return []
    try:
        arbre = json.loads(t).get("tree") or []
    except Exception:  # noqa: BLE001
        return []
    return [str(n.get("path")) for n in arbre
            if isinstance(n, dict) and n.get("type") == "blob" and n.get("path")]


def _fichier(repo: str, chemin: str) -> str | None:
    return _get("https://api.github.com/repos/%s/contents/%s" % (repo, chemin), brut=True)


def main() -> int:  # noqa: C901
    ap = argparse.ArgumentParser(description="PHASE 3 — lire le CODE des meilleurs repos.")
    ap.add_argument("--top", type=int, default=15,
                    help="combien de repos on ouvre VRAIMENT (defaut 15)")
    ap.add_argument("--fichiers", type=int, default=8,
                    help="combien de fichiers par repo (defaut 8)")
    args = ap.parse_args()

    print("=" * 100)
    print("  PHASE 3 — **LIRE LE CODE.** *Le README est du marketing ; le code est la verite.*")
    print("=" * 100)
    print("\n  8 passes de tri sur 5 617 repos  ->  **3 idees**")
    print("  20 min a lire le code d'UN repo   ->  **5 bugs** dans notre simu")
    print("  ***Trier ne remplacera jamais lire.***")

    if not os.environ.get("GITHUB_TOKEN", "").strip():
        print("\n  ⚠️ **Pas de GITHUB_TOKEN** -> quota 60 requetes/heure. Cette phase en consomme")
        print("     ~3 par repo. **Elle s'arretera vite, et elle le DIRA.**")
        print("     `set GITHUB_TOKEN=ghp_...` (lecture seule) -> 5 000/h.")

    if not MOISSON.exists():
        print("\n  🔴 `%s` absent. Lancer d'abord la moisson." % MOISSON.name)
        print("     ***Etat vide honnete.*** Je n'invente pas une liste de repos.")
        return 1

    try:
        brut = json.loads(MOISSON.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print("\n  🔴 moisson illisible : %s" % e)
        return 1

    repos = brut.get("trouvailles") or brut.get("repos") or brut
    if not isinstance(repos, list):
        print("\n  🔴 format de moisson inattendu. **Je ne devine pas.**")
        return 1

    noms = [str(r.get("nom")) for r in repos if isinstance(r, dict) and r.get("nom")]
    print("\n  repos dans la moisson : **%d**" % len(noms))

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  ETAPE A — RE-NOTER SUR LA **SUBSTANCE**, pas sur le bavardage.
    #
    #  🔴 L'ancien score comptait les CONCEPTS MENTIONNES. Mesure : n_concepts=0 -> 15 etoiles
    #     mediane ; n_concepts=12 -> **5 etoiles**. ***ANTI-CORRELE.***
    #     Le champion recitait le catalogue du metier. **Le grep mesurait la VERBOSITE.**
    #
    #  -> on note desormais : FORMULES posees · **AVEUX DE LIMITE** · CHIFFRES verifiables.
    #     *Dans un corpus ou tout le monde promet de l'alpha, l'aveu est le seul signal vrai.*
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    print("\n" + "─" * 100)
    print("  A. RE-NOTER SUR LA SUBSTANCE (formules · **aveux de limite** · chiffres)")
    print("─" * 100)

    etoiles = {str(r.get("nom")): int(r.get("etoiles") or 0)
               for r in repos if isinstance(r, dict)}
    notes: list[tuple[float, str, Any]] = []
    introuvables: list[str] = []

    # on ne re-lit pas 5 617 README : on part des mieux places de l'ancien tri, elargi.
    candidats = noms[: max(args.top * 6, 60)]
    for i, nom in enumerate(candidats, 1):
        txt = _readme(nom)
        if txt is None:
            introuvables.append(nom)
            time.sleep(PAUSE)
            continue
        sig = analyser(txt)
        notes.append((score(sig, etoiles=etoiles.get(nom, 0)), nom, sig))
        if i % 10 == 0:
            print("     %d/%d..." % (i, len(candidats)))
        time.sleep(PAUSE)

    notes.sort(key=lambda x: -x[0])

    if introuvables:
        print("\n  🔴 **%d README NON LUS** — et je le DIS au lieu de les compter comme vides :"
              % len(introuvables))
        for n in introuvables[:10]:
            print("       %s" % n)
        print("     *C'est exactement l'erreur qui avait perdu hftbacktest en silence.*")

    print("\n  %-44s %8s  %s" % ("repo", "score", "pourquoi"))
    for s, nom, sig in notes[: args.top]:
        raisons = []
        if sig.n_formules:
            raisons.append("%d formule(s)" % sig.n_formules)
        if sig.aveux:
            raisons.append("**%d AVEU(X)**" % len(sig.aveux))
        if sig.chiffres:
            raisons.append("%d chiffre(s)" % len(sig.chiffres))
        if sig.promesses_creuses:
            raisons.append("🚩 promesses creuses")
        print("  %-44s %8.1f  %s" % (nom[:44], s, " · ".join(raisons) or "—"))

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  ETAPE B — 🔑 **OUVRIR LES FICHIERS.** C'est ici que tout se joue.
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    print("\n" + "─" * 100)
    print("  B. **OUVRIR LE CODE** des %d meilleurs — *la seule etape qui ait jamais rien donne*"
          % args.top)
    print("─" * 100)

    lectures: list[dict[str, Any]] = []
    for s, nom, _sig in notes[: args.top]:
        arbre = _arbre(nom)
        time.sleep(PAUSE)
        if not arbre:
            print("\n  %-40s ⚪ arbre illisible -> **aucun fichier ouvert** (je ne fais pas semblant)"
                  % nom)
            continue

        cibles = fichiers_a_lire(arbre, maxi=args.fichiers)
        if not cibles:
            print("\n  %-40s ⚪ aucun fichier dont le CHEMIN annonce nos sujets" % nom)
            continue

        print("\n  %s  (score %.1f) — %d fichier(s) ouvert(s)" % (nom, s, len(cibles)))
        for ch in cibles:
            src = _fichier(nom, ch)
            time.sleep(PAUSE)
            if src is None:
                continue
            for lec in liste_de_lecture(nom, ch, src):
                lectures.append(lec.as_dict())
                print("     %s:%d  [%s]" % (ch, lec.ligne, lec.pourquoi))
                print("        %s" % lec.code[:110])

    # ═══════════════════════════════════════════════════════════════════════════════════════════
    #  LE LIVRABLE
    # ═══════════════════════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 100)
    print("  LA LISTE DE LECTURE")
    print("=" * 100)
    print("\n  **%d ligne(s) de code a lire**, dans %d repo(s)."
          % (len(lectures), len({x["repo"] for x in lectures})))

    if not lectures:
        print("\n  ⚪ **Rien a lire.** Ce n'est pas une panne : le corpus n'a rien donne.")
        print("     *Un etat vide honnete vaut mieux qu'une liste remplie pour faire joli.*")

    SORTIE_JSON.parent.mkdir(parents=True, exist_ok=True)
    SORTIE_JSON.write_text(json.dumps({
        "classement_par_substance": [
            {"repo": n, "score": s, **sg.as_dict()} for s, n, sg in notes[: args.top]
        ],
        "readme_non_lus": introuvables,
        "liste_de_lecture": lectures,
        "note": ("Le score mesure ce qui merite d'etre LU, pas la qualite d'une idee. "
                 "TRIER NE REMPLACERA JAMAIS LIRE."),
        "lecture_seule": True, "aucun_code_execute": True, "real_execution": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    md = [
        "# Liste de lecture — *ce qu'il faut OUVRIR*",
        "",
        "> **8 passes de tri sur 5 617 repos → 3 idées.**",
        "> **20 minutes à lire le code d'UN repo → 5 bugs dans notre simu.**",
        ">",
        "> ***Trier ne remplacera jamais lire.***",
        "",
        "## Le classement — par **substance**, jamais par bavardage",
        "",
        "*(formules posées · **aveux de limite** · chiffres vérifiables — les étoiles pèsent peu :",
        "les 4 repos les plus exactement sur cible avaient 1, 2, 3 et 3 étoiles)*",
        "",
        "| repo | score | formules | aveux | chiffres |",
        "|---|---|---|---|---|",
    ]
    for s, n, sg in notes[: args.top]:
        md.append("| [%s](https://github.com/%s) | %.1f | %d | **%d** | %d |"
                  % (n, n, s, sg.n_formules, len(sg.aveux), len(sg.chiffres)))
    md += ["", "## 🔑 Les lignes à lire", ""]
    par_repo: dict[str, list[dict[str, Any]]] = {}
    for x in lectures:
        par_repo.setdefault(x["repo"], []).append(x)
    for r, xs in par_repo.items():
        md += ["### [%s](https://github.com/%s)" % (r, r), ""]
        for x in xs:
            md += ["- **`%s:%d`** — %s" % (x["fichier"], x["ligne"], x["pourquoi"]),
                   "  ```", "  %s" % x["code"], "  ```"]
        md.append("")
    if introuvables:
        md += ["## 🔴 README non lus (%d)" % len(introuvables), "",
               "*Je les signale au lieu de les compter comme vides — c'est l'erreur qui avait*",
               "*perdu **hftbacktest** (4 270⭐, notre cible n°1) **en silence**.*", ""]
        md += ["- `%s`" % n for n in introuvables]
    md += ["", "---", "", "*Lecture seule. Aucun clone. **Aucun code téléchargé n'est exécuté.***", ""]
    SORTIE_MD.write_text("\n".join(md), encoding="utf-8")

    print("\n  -> %s" % SORTIE_MD)
    print("  -> %s" % SORTIE_JSON)
    print("\n  🔒 Lecture seule. Aucun clone. **Aucun code telecharge n'a ete execute.**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
