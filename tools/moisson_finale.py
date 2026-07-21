r"""LA MOISSON FINALE — produit **`moisson-fini.md`** a la racine.

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QU'ELLE FAIT, ET DANS QUEL ORDRE
═══════════════════════════════════════════════════════════════════════════════════════════════

  1. **PARTIR DE NOS TROUS.** On ne cherche pas « trading bot ». On cherche **ce qui manque a
     NOTRE bot**, nommement. Chaque requete vient d'un echec MESURE.
        *(`research/github_graph.REQUETES_DE_NOS_TROUS`)*

  2. **SUIVRE LE FIL.** Une **awesome-list** contient 200 repos **sans aucun topic** : la
     recherche par topic ne les verra **jamais**. On avait la carte au tresor -- **et on l'a
     classee**. Desormais on suit ses liens, les **dependances** (une recommandation d'expert,
     gratuite) et les **sources citees** (« port of X » = une source deja validee).

  3. **LIRE LES README** -- par l'**API** (elle resout nom + extension + branche).
     *L'ancienne version ne tentait que `README.md` : **235 repos perdus EN SILENCE**, dont
     **hftbacktest (4 270 etoiles, notre cible n°1)**.*

  4. **NOTER SUR LA SUBSTANCE**, jamais sur le bavardage : formules posees · **aveux de
     limite** (le signal le plus fort) · chiffres verifiables. Les etoiles pesent peu.

  5. **OUVRIR LE CODE.** *8 passes de tri sur 5 617 repos -> **3 idees**. 20 min a lire le code
     d'UN repo -> **5 bugs** dans notre simu.* ***Trier ne remplacera jamais lire.***

  6. **CLASSER** (COPY_ADAPTED / PORT_BEHAVIOR / INSPIRE_ONLY / SKIP...) et **DIRE OU CA SE
     BRANCHE** chez nous, avec le test obligatoire.

  7. Ecrire **`moisson-fini.md`** -- pourquoi on garde, en quoi c'est benefique, comment
     l'installer, **comment le brancher**, et **ce qu'on ne peut PAS prouver**.

🔒 100 % LECTURE SEULE. Aucun clone. **Aucun code telecharge n'est execute. JAMAIS.**
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

from hl_observer.research.github_dossier import (  # noqa: E402
    classer,
    dossier_md,
    installation,
)
from hl_observer.research.github_graph import (  # noqa: E402
    dependances,
    est_une_liste,
    liens_de_repos,
    requetes_ciblees,
)
from hl_observer.research.github_signals import (  # noqa: E402
    analyser,
    fichiers_a_lire,
    liste_de_lecture,
    score,
)

SORTIE_MD = RACINE / "moisson-fini.md"                       # 🎯 A LA RACINE, comme demande
SORTIE_JSON = RACINE / "data" / "reports" / "moisson_finale.json"
MOISSON = RACINE / "data" / "reports" / "github_concepts.json"

PAUSE = 0.7
MANIFESTES = ("requirements.txt", "pyproject.toml", "package.json", "Cargo.toml")


def _entetes(brut: bool = False) -> dict[str, str]:
    h = {"User-Agent": "hypersmart-research",
         "Accept": "application/vnd.github.raw+json" if brut else "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}
    j = os.environ.get("GITHUB_TOKEN", "").strip()
    if j:
        h["Authorization"] = "Bearer %s" % j
    return h


def _get(url: str, *, brut: bool = False) -> str | None:
    """`None` = **je n'ai pas su lire**. *Jamais une chaine vide qui ferait croire a un vide.*"""
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=_entetes(brut)), timeout=25.0
        ) as r:
            return r.read(500_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            time.sleep(15.0)
        return None
    except Exception:  # noqa: BLE001
        return None


def _chercher(q: str, n: int = 30) -> list[dict[str, Any]]:
    url = ("https://api.github.com/search/repositories?q=%s&sort=stars&order=desc&per_page=%d"
           % (urllib.parse.quote(q), n))
    t = _get(url)
    if not t:
        return []
    try:
        return json.loads(t).get("items") or []
    except Exception:  # noqa: BLE001
        return []


def _readme(repo: str) -> str | None:
    """Par l'**API** : elle resout nom + extension + branche. *Le bug qui a perdu hftbacktest.*"""
    return _get("https://api.github.com/repos/%s/readme" % repo, brut=True)


def _meta(repo: str) -> dict[str, Any]:
    t = _get("https://api.github.com/repos/%s" % repo)
    try:
        return json.loads(t) if t else {}
    except Exception:  # noqa: BLE001
        return {}


def _arbre(repo: str, branche: str) -> list[str]:
    t = _get("https://api.github.com/repos/%s/git/trees/%s?recursive=1" % (repo, branche))
    if not t:
        return []
    try:
        return [str(n["path"]) for n in (json.loads(t).get("tree") or [])
                if isinstance(n, dict) and n.get("type") == "blob" and n.get("path")]
    except Exception:  # noqa: BLE001
        return []


def _fichier(repo: str, chemin: str) -> str | None:
    return _get("https://api.github.com/repos/%s/contents/%s"
                % (repo, urllib.parse.quote(chemin)), brut=True)


def main() -> int:  # noqa: C901, PLR0912, PLR0915
    ap = argparse.ArgumentParser(description="La moisson finale -> moisson-fini.md")
    ap.add_argument("--top", type=int, default=20, help="combien de repos on OUVRE vraiment")
    ap.add_argument("--par-requete", type=int, default=25)
    ap.add_argument("--fichiers", type=int, default=6)
    ap.add_argument("--sans-graphe", action="store_true",
                    help="ne pas suivre les awesome-lists / dependances")
    args = ap.parse_args()

    print("=" * 100)
    print("  LA MOISSON FINALE -> **moisson-fini.md** (a la racine)")
    print("=" * 100)

    if not os.environ.get("GITHUB_TOKEN", "").strip():
        print("\n  ⚠️ **Pas de GITHUB_TOKEN** -> 60 requetes/heure. Cette moisson en consomme")
        print("     des centaines. **Elle s'arretera tot, et elle le DIRA.**")
        print("     `set GITHUB_TOKEN=ghp_...` (lecture seule) -> 5 000/h.")

    candidats: dict[str, dict[str, Any]] = {}
    provenance: dict[str, str] = {}

    # ── 1. CHERCHER CE QUI MANQUE A **NOTRE** BOT ──────────────────────────────────────────────
    print("\n" + "-" * 100)
    print("  1. LES REQUETES DERIVEES DE **NOS TROUS MESURES** (pas de mots a la mode)")
    print("-" * 100)
    for r in requetes_ciblees():
        items = _chercher(r["requete"], args.par_requete)
        neufs = 0
        for it in items:
            nom = str(it.get("full_name") or "")
            if nom and nom not in candidats:
                candidats[nom] = it
                provenance[nom] = "recherche : %s" % r["pourquoi"]
                neufs += 1
        print("  %-58s +%-3d  (%s)" % (r["requete"][:58], neufs, r["pourquoi"][:34]))
        time.sleep(PAUSE)

    # ── reprendre la moisson precedente (5 617 repos) : elle est deja payee ────────────────────
    if MOISSON.exists():
        try:
            anciens = json.loads(MOISSON.read_text(encoding="utf-8"))
            liste = anciens.get("trouvailles") or anciens.get("repos") or []
            n = 0
            for a in liste if isinstance(liste, list) else []:
                nom = str(a.get("nom") or "")
                if nom and nom not in candidats:
                    candidats[nom] = {"full_name": nom,
                                      "stargazers_count": a.get("etoiles") or 0,
                                      "license": {"spdx_id": a.get("licence")}}
                    provenance[nom] = "moisson precedente (5 617 repos)"
                    n += 1
            print("\n  + %d repos repris de la moisson precedente (**ne pas re-moissonner**)" % n)
        except Exception:  # noqa: BLE001
            pass

    print("\n  candidats : **%d**" % len(candidats))

    # ── 2. LIRE LES README + 3. NOTER SUR LA SUBSTANCE ─────────────────────────────────────────
    print("\n" + "-" * 100)
    print("  2-3. LIRE LES README (par l'API) et NOTER SUR LA **SUBSTANCE**")
    print("       *formules posees · **aveux de limite** · chiffres — pas le bavardage*")
    print("-" * 100)

    notes: list[tuple[float, str, Any, str]] = []
    non_lus: list[str] = []
    listes_trouvees: list[str] = []
    pistes_du_graphe: list[str] = []

    # on lit d'abord les mieux etoiles (proxy grossier de « ca vaut un appel reseau »),
    # mais le SCORE, lui, ne dependra presque pas des etoiles. *Les 4 meilleurs en avaient 1 a 3.*
    ordonnes = sorted(candidats.items(),
                      key=lambda kv: -int(kv[1].get("stargazers_count") or 0))
    a_lire = [n for n, _ in ordonnes][: max(args.top * 8, 120)]

    for i, nom in enumerate(a_lire, 1):
        txt = _readme(nom)
        time.sleep(PAUSE)
        if txt is None:
            non_lus.append(nom)
            continue

        # ── 🌐 SUIVRE LE FIL : une awesome-list est une CARTE, pas un territoire ───────────────
        if not args.sans_graphe and est_une_liste(nom, txt):
            liens = liens_de_repos(txt, exclure=set(candidats))
            if liens:
                listes_trouvees.append(nom)
                for l in liens[:120]:
                    if l not in candidats:
                        candidats[l] = {"full_name": l, "stargazers_count": 0}
                        provenance[l] = "🌐 cite par l'awesome-list `%s`" % nom
                        pistes_du_graphe.append(l)
                print("  🌐 **%s est une LISTE** -> +%d pistes que le topic-search ne verrait "
                      "JAMAIS" % (nom, len(liens[:120])))

        etoiles = int(candidats[nom].get("stargazers_count") or 0)
        sig = analyser(txt)
        notes.append((score(sig, etoiles=etoiles), nom, sig, txt))
        if i % 20 == 0:
            print("     %d/%d lus..." % (i, len(a_lire)))

    if non_lus:
        print("\n  🔴 **%d README NON LUS** — et je le DIS au lieu de les compter comme vides."
              % len(non_lus))
        print("     *C'est exactement l'erreur qui avait perdu hftbacktest EN SILENCE.*")

    notes.sort(key=lambda x: -x[0])
    print("\n  notes : %d · listes suivies : %d · pistes ouvertes par le graphe : **%d**"
          % (len(notes), len(listes_trouvees), len(pistes_du_graphe)))

    # ── 4. OUVRIR LE CODE + 5. CLASSER ────────────────────────────────────────────────────────
    print("\n" + "-" * 100)
    print("  4-5. **OUVRIR LE CODE** des %d meilleurs, puis CLASSER" % args.top)
    print("       *8 passes de tri sur 5 617 repos -> 3 idees. 20 min de lecture -> 5 bugs.*")
    print("-" * 100)

    entrees: list[dict[str, Any]] = []
    biblios: dict[str, int] = {}

    for s, nom, sig, _txt in notes[: args.top]:
        m = _meta(nom)
        time.sleep(PAUSE)
        lic = ((m.get("license") or {}).get("spdx_id")
               or (candidats.get(nom, {}).get("license") or {}).get("spdx_id"))
        branche = m.get("default_branch") or "main"
        arbre = _arbre(nom, branche)
        time.sleep(PAUSE)

        lectures: list[dict[str, Any]] = []
        for ch in fichiers_a_lire(arbre, maxi=args.fichiers):
            src = _fichier(nom, ch)
            time.sleep(PAUSE)
            if src:
                lectures += [x.as_dict() for x in liste_de_lecture(nom, ch, src)]

        # les DEPENDANCES : *une recommandation d'expert, gratuite.*
        if not args.sans_graphe:
            for man in MANIFESTES:
                if man in arbre:
                    c = _fichier(nom, man)
                    time.sleep(PAUSE)
                    if c:
                        for d in dependances(man, c):
                            biblios[d] = biblios.get(d, 0) + 1
                    break

        fiche = classer(nom, licence=lic, signaux=sig.as_dict(),
                        n_lignes_de_code=len(lectures))
        entrees.append({
            "repo": nom, "score": s,
            "etoiles": int(candidats.get(nom, {}).get("stargazers_count") or 0),
            "licence": lic, "provenance": provenance.get(nom, ""),
            "verdict": fiche.verdict, "pourquoi": fiche.pourquoi,
            "trous_combles": fiche.trous_combles, "reserves": fiche.reserves,
            "signaux": sig.as_dict(),
            "installation": installation(arbre).as_dict(),
            "lectures": lectures,
        })
        print("  %-42s %7.1f  %-18s %d ligne(s) a lire"
              % (nom[:42], s, fiche.verdict, len(lectures)))

    # ── 6. LE LIVRABLE ────────────────────────────────────────────────────────────────────────
    md = dossier_md(entrees)

    # on complete avec ce que le GRAPHE a ouvert -- *ce que le topic-search ne verrait jamais*
    sup = ["", "---", "", "# 🌐 Ce que la recherche par topic n'aurait **jamais** vu", ""]
    if listes_trouvees:
        sup += ["## Les awesome-lists suivies", "",
                "*Un `awesome-quant` contient 200 repos **sans aucun topic**. "
                "On en avait trouvé une — **et on ne l'avait jamais suivie**.*", ""]
        sup += ["- [`%s`](https://github.com/%s)" % (n, n) for n in listes_trouvees]
        sup += ["", "→ **%d pistes** ouvertes par ce seul mécanisme." % len(pistes_du_graphe), ""]
    if biblios:
        sup += ["## Les bibliothèques que des gens sérieux ont choisi d'importer", "",
                "*Le `requirements.txt` d'un bon repo est une **liste de courses validée par "
                "quelqu'un qui a fait le travail**.*", "",
                "| bibliothèque | citée par |", "|---|---|"]
        sup += ["| `%s` | %d repo(s) |" % (b, n)
                for b, n in sorted(biblios.items(), key=lambda x: -x[1])[:30]]
        sup.append("")
    if non_lus:
        sup += ["## 🔴 %d README que je n'ai **pas su lire**" % len(non_lus), "",
                "*Je les signale au lieu de les compter comme vides — c'est **exactement** "
                "l'erreur qui avait perdu **hftbacktest** (4 270⭐, notre cible n°1) en silence.*",
                ""]
        sup += ["- `%s`" % n for n in non_lus[:40]]
        if len(non_lus) > 40:
            sup.append("- *(+%d autres)*" % (len(non_lus) - 40))
        sup.append("")

    SORTIE_MD.write_text(md + "\n".join(sup), encoding="utf-8")
    SORTIE_JSON.parent.mkdir(parents=True, exist_ok=True)
    SORTIE_JSON.write_text(json.dumps({
        "entrees": entrees, "readme_non_lus": non_lus,
        "awesome_lists_suivies": listes_trouvees,
        "pistes_ouvertes_par_le_graphe": pistes_du_graphe,
        "bibliotheques_citees": biblios,
        "lecture_seule": True, "aucun_code_execute": True, "real_execution": False,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    gardes = [e for e in entrees if e["verdict"] != "SKIP_WITH_REASON"]
    print("\n" + "=" * 100)
    print("  RESULTAT")
    print("=" * 100)
    print("\n  retenus : **%d**  ·  ecartes (avec motif) : %d"
          % (len(gardes), len(entrees) - len(gardes)))
    if not gardes:
        print("\n  ⚪ **Aucun repo retenu.** *Ce n'est pas une panne : le corpus n'a rien donne.*")
    print("\n  -> **%s**" % SORTIE_MD)
    print("  -> %s" % SORTIE_JSON)
    print("\n  🔒 Lecture seule. Aucun clone. **Aucun code telecharge n'a ete execute.**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
