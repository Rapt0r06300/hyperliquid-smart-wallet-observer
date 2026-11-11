"""Matrice de couverture : type de donnée → producteur → certificateur → coffre → laboratoire.

Construite à partir du RÉEL : registre des flux, règles du certificateur, index du coffre LOCAL,
fichiers présents dans les dossiers de collecte et les sessions archivées, index du magasin de
ticks. Écrit ``runtime/reports/copy_vault_quant_lab/couverture/MATRICE_COUVERTURE.{md,json}``.

Verdict par type : ``OK`` · ``MANQUANT`` · ``NON TESTÉ`` · ``INCOMPATIBLE`` ·
``HORS PÉRIMÈTRE JUSTIFIÉ``. Tout fichier de collecte absent du registre sort en ``MANQUANT``
(flux inconnu). Hors ligne, lecture seule : aucun collecteur n'est lancé.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
for chemin in (RACINE / "src", RACINE / "tools"):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

from hl_observer.datasets import coffre_certifie as C  # noqa: E402
from hl_observer.datasets import couverture_donnees as R  # noqa: E402

SORTIE = Path("runtime") / "reports" / "copy_vault_quant_lab" / "couverture"
DOSSIERS = (Path("runtime") / "data", Path("runtime") / "research_lab" / "data", Path("runtime") / "history")


def _rubans_presents(root: Path) -> dict[str, dict[str, int]]:
    """Rubans vus dans les dossiers de collecte et les sessions archivées : {nom logique: stats}."""
    vus: dict[str, dict[str, int]] = {}
    dossiers = [root / d for d in DOSSIERS]
    archive = root / "runtime" / "archive"
    if archive.is_dir():
        dossiers += sorted(d for d in archive.iterdir() if d.is_dir())
    for dossier in dossiers:
        if not dossier.is_dir():
            continue
        for fichier in dossier.iterdir():
            nom = fichier.name
            if not fichier.is_file() or not (nom.endswith(".jsonl") or nom.endswith(".jsonl.gz")):
                continue
            logique = nom[:-3] if nom.endswith(".gz") else nom
            for connu in R.flux_par_fichier():          # rotation horodatée -> nom du ruban actif
                tronc = connu[:-6]
                if logique.startswith(tronc + "_") and logique[len(tronc) + 1:-6].isdigit():
                    logique = connu
            ligne = vus.setdefault(logique, {"exemplaires": 0, "octets": 0})
            ligne["exemplaires"] += 1
            ligne["octets"] += fichier.stat().st_size
    return vus


def _coffre(root: Path) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    """(par famille, par nom de ruban) : shards et lignes déposés d'après l'index du coffre LOCAL."""
    try:
        index = json.loads((root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    par_famille: dict[str, dict[str, int]] = {}
    par_ruban: dict[str, dict[str, int]] = {}
    for shard in index.get("shards", []):
        famille = str(shard.get("famille"))
        for table, cle in ((par_famille, famille),
                           (par_ruban, Path(str(shard.get("shard"))).name.split("__", 1)[-1].split("__")[0]
                            .replace(".jsonl.gz", ""))):
            ligne = table.setdefault(cle, {"shards": 0, "lignes": 0})
            ligne["shards"] += 1
            ligne["lignes"] += int(shard.get("deposes") or 0)
    return par_famille, par_ruban


def _familles_safe(root: Path) -> dict[str, int] | None:
    """Shards par famille dans le catalogue SAFE-cloud (celui qu'AlinaSync restaure) ; ``None`` si absent."""
    index = root / "catalog" / "DATA_INDEX.json"
    if not index.is_file():
        return None
    try:
        from partitioned_data_index import select_index_rows
        _meta, rows = select_index_rows(index, lambda _row: True)
    except Exception:  # catalogue illisible : on le dit, on n'invente rien
        return None
    compte: dict[str, int] = {}
    for row in rows:
        famille = str(row.get("family"))
        compte[famille] = compte.get(famille, 0) + 1
    return dict(sorted(compte.items()))


def construire(root: Path, *, avec_safe: bool = False) -> dict[str, Any]:
    root = Path(root).resolve()
    presents = _rubans_presents(root)
    par_famille, par_ruban = _coffre(root)
    lignes: list[dict[str, Any]] = []
    for flux in R.FLUX:
        emis = presents.get(flux.fichier)
        detecte = C.detecter_famille(flux.fichier)
        motif = C.motif_non_certifie(flux.fichier)
        tronc = flux.fichier[:-6]
        correspondants = [v for k, v in par_ruban.items()
                          if k == tronc or (k.startswith(tronc + "_") and k[len(tronc) + 1:].isdigit())]
        depot = ({"shards": sum(v["shards"] for v in correspondants), "lignes": sum(v["lignes"] for v in correspondants)}
                 if correspondants else None)
        ligne: dict[str, Any] = {
            "type": flux.contenu, "fichier": flux.fichier, "dossier": flux.dossier, "producteur": flux.producteur,
            "emis": bool(emis), "exemplaires": (emis or {}).get("exemplaires", 0),
            "octets": (emis or {}).get("octets", 0),
            "detecte": bool(detecte) or flux.fichier == "vault_episodes.jsonl",   # reconnu par son contenu
            "famille": flux.famille, "regle": "certifie" if flux.famille else f"ecarte:{motif[0] if motif else '?'}",
            "au_coffre_shards": (depot or {}).get("shards", 0), "au_coffre_lignes": (depot or {}).get("lignes", 0),
            "labo": flux.labo, "usage": flux.usage,
        }
        if flux.famille is None:
            ligne["verdict"] = "HORS PÉRIMÈTRE JUSTIFIÉ" if motif else "MANQUANT"
            ligne["explication"] = motif[1] if motif else "ni règle de certification ni motif d'exclusion"
        elif not ligne["detecte"]:
            ligne["verdict"], ligne["explication"] = "MANQUANT", "le certificateur ne reconnaît pas ce fichier"
        elif not emis:
            ligne["verdict"] = "NON TESTÉ"
            ligne["explication"] = "aucun exemplaire sur ce PC (flux produit par une lane GitHub ou un outil non lancé)"
        elif not ligne["au_coffre_shards"]:
            ligne["verdict"] = "MANQUANT"
            ligne["explication"] = "émis et reconnu, mais rien au coffre : relancer le Certificateur"
        else:
            ligne["verdict"] = "OK"
            ligne["explication"] = {
                R.CONSOMME: "certifié, au coffre, consommé par le labo",
                R.DISPONIBLE: "certifié et au coffre ; disponible pour le labo, pas encore exploité par un calcul",
                R.AUXILIAIRE: "certifié et au coffre ; volontairement auxiliaire",
            }[flux.labo]
        lignes.append(ligne)
    connus = set(R.flux_par_fichier())
    for nom, stats in sorted(presents.items()):
        if nom not in connus:
            lignes.append({
                "type": "NON RÉPERTORIÉ", "fichier": nom, "dossier": "?", "producteur": "?", "emis": True,
                "exemplaires": stats["exemplaires"], "octets": stats["octets"], "detecte": bool(C.detecter_famille(nom)),
                "famille": None, "regle": "aucune", "au_coffre_shards": 0, "au_coffre_lignes": 0, "labo": "?",
                "usage": "", "verdict": "MANQUANT",
                "explication": "fichier de collecte absent du registre de couverture : à répertorier",
            })
    try:
        ticks = json.loads((root / "runtime" / "coffre_certifie" / "MARKET_TICKS_INDEX.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ticks = None
    usage_familles = R.usage_par_famille()
    safe = _familles_safe(root) if avec_safe else None
    familles = []
    for famille, v in sorted(par_famille.items()):
        equivalents = R.EQUIVALENT_SAFE.get(famille)
        ligne_famille: dict[str, Any] = {
            "famille": famille, "shards": v["shards"], "lignes": v["lignes"],
            "labo": usage_familles.get(famille, "NON DÉCLARÉ"),
            "equivalent_safe": list(equivalents) if equivalents is not None else None,
            "portee": ("NON DÉCLARÉE" if equivalents is None
                       else "LOCAL SEUL (exploratoire, jamais PROVEN)" if not equivalents
                       else "LOCAL + équivalent SAFE"),
        }
        if safe is not None and equivalents:
            ligne_famille["shards_safe"] = {nom: safe.get(nom, 0) for nom in equivalents}
        familles.append(ligne_famille)
    compte: dict[str, int] = {}
    for ligne in lignes:
        compte[ligne["verdict"]] = compte.get(ligne["verdict"], 0) + 1
    return {
        "schema": "hypersmart.copy_vault_couverture_donnees.v1", "verdicts": dict(sorted(compte.items())),
        "types": lignes, "familles_au_coffre": familles, "magasin_ticks": ticks,
        "catalogue_safe": safe,
        "familles_sans_usage_labo": [f["famille"] for f in familles if f["labo"] == "NON DÉCLARÉ"],
        "read_only": True, "real_execution": False,
    }


def rendre(matrice: dict[str, Any]) -> str:
    oui = lambda v: "oui" if v else "non"   # noqa: E731
    lignes = ["# Matrice de couverture des données — collecteurs → certificateur → coffre → labo", "",
              f"- Verdicts : {json.dumps(matrice['verdicts'], ensure_ascii=False)}",
              f"- Familles au coffre sans usage labo déclaré : {matrice['familles_sans_usage_labo'] or 'aucune'}", "",
              "| Verdict | Fichier | Contenu | Producteur | Émis | Détecté | Règle | Au coffre (shards / lignes) | Labo |",
              "|---|---|---|---|---|---|---|---|---|"]
    ordre = {"MANQUANT": 0, "INCOMPATIBLE": 1, "NON TESTÉ": 2, "OK": 3, "HORS PÉRIMÈTRE JUSTIFIÉ": 4}
    for l in sorted(matrice["types"], key=lambda x: (ordre.get(x["verdict"], 9), x["fichier"])):
        lignes.append(
            f"| **{l['verdict']}** | `{l['fichier']}` | {l['type']} | `{l['producteur']}` | {oui(l['emis'])} "
            f"({l['exemplaires']}) | {oui(l['detecte'])} | {l['famille'] or l['regle']} | "
            f"{l['au_coffre_shards']} / {l['au_coffre_lignes']:,} | {l['labo']} — {l['usage']} |")
    lignes += ["", "## Familles au coffre LOCAL — et leur équivalent SAFE-cloud (restauré par AlinaSync)", "",
               "| Famille | Shards | Lignes | Usage labo | Portée | Équivalent SAFE (shards au catalogue) |",
               "|---|---|---|---|---|---|"]
    for f in matrice["familles_au_coffre"]:
        safe = f.get("shards_safe")
        equivalent = (", ".join(f"{nom} ({n:,})" for nom, n in safe.items()) if safe
                      else ", ".join(f.get("equivalent_safe") or []) or "—")
        lignes.append(f"| {f['famille']} | {f['shards']} | {f['lignes']:,} | {f['labo']} | {f['portee']} | {equivalent} |")
    lignes += ["", "AlinaSync ne lit ni n'écrit le coffre LOCAL : il restaure le corpus SAFE (`runtime/recovery/full`) et "
               "rapatrie les rubans des lanes GitHub dans `runtime/data`, où le Certificateur les prend comme les autres. "
               "Une famille « LOCAL SEUL » n'a aucune contrepartie cloud : perdue si ce PC est perdu."]
    ticks = matrice["magasin_ticks"]
    lignes += ["", "## Magasin de ticks natifs (vérifié et référencé en place, non recopié)", ""]
    if not ticks or not ticks.get("present"):
        lignes.append("- aucun index : lancer `python tools/verifier_store_ticks.py`.")
    else:
        lignes.append(
            f"- {ticks['shards_verifies']:,} shard(s) vérifié(s) ({ticks['octets_verifies'] / 1e9:.2f} Go) · "
            f"anomalies : {ticks['anomalies']} · "
            + ("vérification complète" if ticks["complet"] else f"{ticks['dossiers_restants']} dossier(s) restant(s)")
            + f" · rubans en cours non immuables : {ticks['rubans_en_cours']:,} ({ticks['octets_en_cours'] / 1e9:.2f} Go)")
        lignes += ["", "| Source | Canal | Shards vérifiés | Go | Anomalies | En cours |", "|---|---|---|---|---|---|"]
        for f in ticks["par_flux"]:
            lignes.append(f"| {f['source']} | {f['canal']} | {f['shards_verifies']:,} | {f['octets'] / 1e9:.2f} | "
                          f"{f['anomalies']} | {f['rubans_en_cours']} |")
    lignes.append("")
    return "\n".join(lignes)


def _sortie_utf8() -> None:
    """Affichage robuste : jamais de plantage sur une console ou un journal non UTF-8."""
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _sortie_utf8()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--safe", action="store_true",
                   help="compte aussi les shards du catalogue SAFE (lit tout l'index : ~1 min)")
    args = p.parse_args(argv)
    root = Path(args.root).resolve()
    matrice = construire(root, avec_safe=args.safe)
    sortie = root / SORTIE
    sortie.mkdir(parents=True, exist_ok=True)
    (sortie / "MATRICE_COUVERTURE.json").write_text(json.dumps(matrice, ensure_ascii=False, indent=1), encoding="utf-8")
    (sortie / "MATRICE_COUVERTURE.md").write_text(rendre(matrice), encoding="utf-8")
    print(f"[couverture] {json.dumps(matrice['verdicts'], ensure_ascii=False)} -> {sortie / 'MATRICE_COUVERTURE.md'}")
    for ligne in matrice["types"]:
        if ligne["verdict"] in ("MANQUANT", "INCOMPATIBLE"):
            print(f"   [{ligne['verdict']}] {ligne['fichier']} : {ligne['explication']}")
    return 3 if any(l["verdict"] in ("MANQUANT", "INCOMPATIBLE") for l in matrice["types"]) else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
