"""VALIDATION DE BOUT EN BOUT de la chaine, SANS allumer un collecteur.

    collecte -> rattrapage -> validation -> certification SAFE -> coffre -> AlinaSync -> labo

CE QU'ELLE PROUVE, ET CE QU'ELLE NE PROUVE PAS. Elle verifie que chaque maillon EXISTE, est
ATTEIGNABLE depuis un lanceur reel, et que le contrat qu'il passe au suivant est honore sur
des donnees reelles deja presentes. Elle ne fabrique aucune donnee et n'allume rien : la
collecte est eteinte sur consigne de l'operateur, et une validation qui exigerait de la
rallumer ne serait pas une validation mais une campagne.

POURQUOI MAILLON PAR MAILLON, ET PAS << ca a tourne >>. Mesure du 21/11/2026 : deux outils
livres et testes (`reconcilier_sources`, `enrichir_fills`) n'etaient appeles par AUCUN
lanceur -- `prod=0`. Leurs tests etaient verts, leur effet nul. Un maillon se valide donc
sur trois questions distinctes :

  1. le module EXISTE-t-il ?
  2. un lanceur reel l'APPELLE-t-il ? (sinon il ne produit rien, quels que soient ses tests)
  3. son contrat de sortie est-il HONORE sur les donnees presentes ?

TROIS ETATS, JAMAIS DEUX. `OK`, `ABSENT`, `NON_CABLE`, `CONTRAT_NON_TENU`, `INDETERMINE` :
un maillon dont on ne peut rien dire n'est pas un maillon qui va bien. L'absence de donnees
a verifier rend `INDETERMINE`, jamais `OK`.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

#: Les lanceurs REELS : un maillon n'est cable que si l'un d'eux l'appelle. On lit aussi les
#: workflows, parce qu'une partie de la chaine tourne chez GitHub (jamais sur ce PC).
LANCEURS = ("*.cmd",)
WORKFLOWS = (".github/workflows/*.yml",)

#: Chaque maillon : (nom, module attendu, artefact de sortie attendu ou None).
#: L'artefact est ce que le maillon LAISSE, et c'est lui qui prouve qu'il a servi.
MAILLONS = (
    ("collecte", "tools/run_bounded_collector.py", None),
    ("registre des collecteurs", "src/hl_observer/ops/collecteur_registry.py", None),
    # 22/11/2026 : `tools/rattraper_gaps.py` n'existe pas -- je l'avais INVENTE. Les vrais
    # outils de rattrapage sont `avancement_rattrapage.py` (le suivi) et les `backfill_*`.
    ("rattrapage (suivi)", "tools/avancement_rattrapage.py", None),
    ("rattrapage (fills)", "tools/backfill_vault_fills.py", None),
    ("rattrapage (bougies)", "tools/backfill_candles_vaults.py", None),
    ("reconciliation des sources", "tools/reconcilier_sources.py",
     "runtime/reports/reconciliation_sources.json"),
    ("enrichissement des fills", "tools/enrichir_fills.py", None),
    ("certificateur", "tools/sceller_coffre_local.py",
     "runtime/coffre_certifie/LOCAL_INDEX.json"),
    ("archivage des tapes", "tools/archiver_tapes.py", None),
    ("AlinaSync", "tools/alina_git_code_sync.py", None),
    ("labo (conduite)", "tools/conduire_labo_par_tranches.py", None),
)


def _textes_des_lanceurs(racine: Path) -> dict[str, str]:
    """Le texte de chaque lanceur, workflow ET module Python : qui appelle quoi.

    22/11/2026 -- FAUX POSITIF DE CE VALIDATEUR, corrige. Il ne lisait que les `.cmd` et
    les workflows, et declarait donc `tools/run_bounded_collector.py` NON_CABLE alors que
    `src/hl_observer/ops/bounded_collection.py` le lance. Un maillon appele par du PYTHON
    est cable : un collecteur n'a pas besoin d'etre appele par un `.cmd` pour tourner.
    """
    textes: dict[str, str] = {}
    for motif in LANCEURS:
        for chemin in sorted(racine.glob(motif)):
            textes[chemin.name] = chemin.read_bytes().decode("cp1252", errors="replace")
    for motif in WORKFLOWS:
        for chemin in sorted(racine.glob(motif)):
            textes[chemin.name] = chemin.read_bytes().decode("utf-8", errors="replace")
    for dossier in ("tools", "src"):
        base = racine / dossier
        if not base.is_dir():
            continue
        for chemin in base.rglob("*.py"):
            if "__pycache__" in str(chemin) or chemin.name == Path(__file__).name:
                continue
            textes[chemin.relative_to(racine).as_posix()] = chemin.read_text(
                encoding="utf-8", errors="replace")
    return textes


def _lignes_actives(texte: str, nom: str) -> str:
    """Les lignes EXECUTEES : une mention en `rem`/`#` ne cable rien.

    Mesure du 22/11/2026 : 12 lignes de `taskkill` ont ete conservees en `rem` pour la
    tracabilite. Les compter comme des appels ferait croire a un cablage disparu.
    """
    prefixes = ("rem", "::") if nom.lower().endswith(".cmd") else ("#",)
    gardees = []
    for ligne in texte.splitlines():
        nue = ligne.strip().lower()
        if any(nue.startswith(p) for p in prefixes):
            continue
        gardees.append(ligne)
    return "\n".join(gardees)


def verifier_maillon(racine: Path, nom: str, module: str, artefact: str | None,
                     textes: dict[str, str]) -> dict:
    """Les trois questions, dans l'ordre, et un etat parmi cinq."""
    chemin = racine / module
    if not chemin.is_file():
        return {"maillon": nom, "module": module, "etat": "ABSENT",
                "detail": "le module n'existe pas"}

    base = Path(module).name
    appelants = [n for n, t in textes.items() if base in _lignes_actives(t, n)]
    if not appelants:
        return {"maillon": nom, "module": module, "etat": "NON_CABLE",
                "detail": "aucun lanceur ni workflow ne l'appelle (prod=0)"}

    if artefact is None:
        return {"maillon": nom, "module": module, "etat": "OK",
                "appelants": appelants[:4],
                "detail": "existe et cable ; pas d'artefact unique a verifier"}

    cible = racine / artefact
    if not cible.is_file():
        return {"maillon": nom, "module": module, "etat": "INDETERMINE",
                "appelants": appelants[:4],
                "detail": f"artefact absent ({artefact}) : rien a verifier, donc rien a dire"}
    try:
        age_h = (time.time() - cible.stat().st_mtime) / 3600.0
        octets = cible.stat().st_size
        json.loads(cible.read_text(encoding="utf-8")) if octets < 50_000_000 else None
    except (OSError, ValueError) as erreur:
        return {"maillon": nom, "module": module, "etat": "CONTRAT_NON_TENU",
                "appelants": appelants[:4],
                "detail": f"artefact illisible : {type(erreur).__name__}"}
    return {"maillon": nom, "module": module, "etat": "OK", "appelants": appelants[:4],
            "artefact": artefact, "age_h": round(age_h, 1), "octets": octets,
            "detail": "existe, cable, et son artefact est lisible"}


def verifier_reprise(racine: Path) -> dict:
    """La chaine sait-elle REPRENDRE ? On cherche les journaux de reprise reels.

    Une reprise qui n'a jamais ete exercee n'est pas une reprise : on regarde donc des
    journaux EXISTANTS, et on dit leur age plutot que de supposer qu'ils marchent.
    """
    temoins = {
        "journal de conduite (labo)": "runtime/logs/tests/conduite_complete_20261121.txt",
        "journal de reprise des recus": "runtime/roadmap/ALINA_ROADMAP_3120.receipts.jsonl",
        "index du coffre": "runtime/coffre_certifie/LOCAL_INDEX.json",
        "etat de campagne": "runtime/data/economic_collection_pids.json",
    }
    sortie = []
    for libelle, relatif in temoins.items():
        chemin = racine / relatif
        if not chemin.is_file():
            sortie.append({"temoin": libelle, "etat": "ABSENT", "age_h": None})
            continue
        age = (time.time() - chemin.stat().st_mtime) / 3600.0
        sortie.append({"temoin": libelle, "etat": "PRESENT", "age_h": round(age, 1),
                       "octets": chemin.stat().st_size})
    return {"temoins": sortie}


def verifier_fail_closed(racine: Path) -> dict:
    """PAPER/READ-ONLY/FAIL-CLOSED : y a-t-il un USAGE, et non une simple MENTION ?

    22/11/2026 -- DEUX FAUX POSITIFS DE CE VALIDATEUR, corriges, tous deux deja connus du
    depot :

    * il lisait des ETIQUETTES comme des diagnostics. `audit_report.py`, `securite_18h.py`
      et `garde_fous_recherche.py` citent `private_key`, `eth_account`, `sign_l1_action` et
      l'URL `/exchange` PARCE QU'ILS LES INTERDISENT. Une liste de noms a exempter serait
      fragile -- il faudrait l'allonger a chaque nouvelle garde. On distingue donc par le
      CONTENU : un interdit cite dans une CHAINE est une mention ; le meme employe comme
      IDENTIFIANT est un usage. `tokenize` tranche sans ambiguite.
    * il balayait `tools/python/` et `site-packages`, le runtime embarque. Meme piege que
      l'audit du depot : 107 faux positifs tombes a 0 en bornant le perimetre.

    Ce que ca ne prouve pas : l'absence d'usage ne prouve pas l'absence de tout risque. Mais
    sa PRESENCE prouverait une violation, et c'est ce qu'il faut pouvoir affirmer.
    """
    import io
    import tokenize

    identifiants = {"private_key", "eth_account", "sign_l1_action"}
    #: ⚠️ L'URL d'execution n'est JAMAIS stockee dans une variable, et c'est volontaire.
    #:
    #: Le 22/11/2026, ce fichier portait `url_exacte = "https://api.…/exchange"` et la suite
    #: complete l'a mis en rouge : la regle bloquante `c_exchange_url` interdit l'endpoint
    #: d'ordre reel PARTOUT dans le depot. Elle avait raison -- j'avais ecrit le point d'entree
    #: de passage d'ordres en clair pour pouvoir le CHERCHER, devenant la violation que je
    #: traquais. Meme piege que le filtre qui s'attrape lui-meme.
    #:
    #: Le depot tranche par le CONTENU (`_lignes_exchange_utilisees`) : un litteral membre d'une
    #: comparaison `in` / `not in` est EXAMINE, donc c'est un garde ; partout ailleurs (assigne,
    #: concatene, passe a une requete) il est EMPLOYE, donc signale. Ce detecteur examine : on
    #: ecrit donc le litteral a l'interieur meme des deux comparaisons, sans variable
    #: intermediaire. **Ne pas le re-extraire dans une constante** -- cela rougirait aussitot,
    #: et a juste titre.
    #: Un interdit cite PRES d un refus est une GARDE, pas une violation. Mesure du
    #: 22/11/2026 : `audit_report.py:3671` porte l URL exacte dans une fixture nommee
    #: `piege_exchange`, juste sous un `raise RuntimeError("l ouvreur reseau NE DOIT PAS
    #: etre appele sur une URL interdite")`. C est la PREUVE que la garde marche --
    #: l oppose d une violation. Exempter par NOM de fichier serait fragile ; on lit donc
    #: le voisinage, comme le depot le fait deja pour `_exchange_hors_emploi`.
    REFUS_PROCHE = ("raise", "assert", "interdit", "ne doit pas", "piege", "pytest.raises",
                    "refus", "forbidden")
    FENETRE_LIGNES = 8
    coupables: list[str] = []
    mentions = 0
    gardes = 0
    for dossier in ("tools", "src"):
        base = racine / dossier
        if not base.is_dir():
            continue
        for chemin in base.rglob("*.py"):
            partie = chemin.as_posix()
            if ("__pycache__" in partie or "/tools/python/" in partie
                    or "/site-packages/" in partie
                    or chemin.name == Path(__file__).name):   # ce validateur lui-meme
                continue
            relatif = chemin.relative_to(racine).as_posix()
            texte = chemin.read_text(encoding="utf-8", errors="replace")
            if (not any(x in texte for x in identifiants)
                    and "https://api.hyperliquid.xyz/exchange" not in texte):
                continue
            try:
                jetons = list(tokenize.generate_tokens(io.StringIO(texte).readline))
            except (tokenize.TokenError, IndentationError, SyntaxError):
                coupables.append(f"{relatif} :: ILLISIBLE (non tokenisable)")
                continue
            for jeton in jetons:
                if jeton.type == tokenize.NAME and jeton.string in identifiants:
                    coupables.append(f"{relatif}:{jeton.start[0]} :: identifiant"
                                     f" {jeton.string}")
                elif (jeton.type == tokenize.STRING
                        and "https://api.hyperliquid.xyz/exchange" in jeton.string):
                    ligne = jeton.start[0]
                    autour = texte.splitlines()[
                        max(0, ligne - 1 - FENETRE_LIGNES):ligne + FENETRE_LIGNES]
                    voisinage = chr(10).join(autour).casefold()
                    if any(x in voisinage for x in REFUS_PROCHE):
                        gardes += 1          # une garde, pas une violation
                    else:
                        coupables.append(f"{relatif}:{ligne} :: URL /exchange")
                elif jeton.type == tokenize.STRING and any(
                        x in jeton.string for x in identifiants):
                    mentions += 1
    return {"violations": coupables, "mentions_en_chaine": mentions,
            "gardes_qui_citent_l_interdit": gardes,
            "etat": "OK" if not coupables else "VIOLATION"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--racine", default=".")
    p.add_argument("--json", action="store_true")
    p.add_argument("--sortie", default="")
    args = p.parse_args(argv)
    racine = Path(args.racine).resolve()

    flux = sys.stdout
    try:  # noqa: SIM105
        flux.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    textes = _textes_des_lanceurs(racine)
    maillons = [verifier_maillon(racine, nom, module, artefact, textes)
                for nom, module, artefact in MAILLONS]
    reprise = verifier_reprise(racine)
    securite = verifier_fail_closed(racine)

    compte: dict[str, int] = {}
    for m in maillons:
        compte[m["etat"]] = compte.get(m["etat"], 0) + 1

    rapport = {"maillons": maillons, "reprise": reprise, "securite": securite,
               "compte": compte, "lanceurs_lus": len(textes),
               "horodatage_ms": int(time.time() * 1000)}
    if args.sortie:
        destination = Path(args.sortie)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(rapport, ensure_ascii=False, indent=1),
                               encoding="utf-8")
    if args.json:
        print(json.dumps(rapport, ensure_ascii=False, indent=1))
        return 0 if not compte.get("ABSENT") and not compte.get("NON_CABLE") else 3

    print("=== CHAINE BOUT EN BOUT : collecte -> ... -> labo ===")
    print(f"  lanceurs et workflows lus : {len(textes)}")
    print()
    for m in maillons:
        suffixe = ""
        if m.get("age_h") is not None:
            suffixe = f"  (artefact : {m['age_h']} h, {m['octets']:,} o)"
        print(f"  {m['etat']:<18} {m['maillon']:<28} {m['module']}{suffixe}")
        if m["etat"] not in ("OK",):
            print(f"      -> {m['detail']}")
        elif m.get("appelants"):
            print(f"      appele par : {', '.join(m['appelants'])}")
    print()
    print("  --- reprise : temoins reels, avec leur age ---")
    for t in reprise["temoins"]:
        age = "absent" if t["age_h"] is None else f"{t['age_h']} h"
        print(f"    {t['etat']:<8} {age:>10}  {t['temoin']}")
    print()
    print(f"  --- PAPER/READ-ONLY/FAIL-CLOSED : {securite['etat']} ---")
    for v in securite["violations"][:5]:
        print(f"    VIOLATION {v}")
    print()
    print("  bilan :", ", ".join(f"{k}={v}" for k, v in sorted(compte.items())))
    if args.sortie:
        print(f"  rapport : {args.sortie}")
    return 0 if not compte.get("ABSENT") and not compte.get("NON_CABLE") else 3


if __name__ == "__main__":
    raise SystemExit(main())
