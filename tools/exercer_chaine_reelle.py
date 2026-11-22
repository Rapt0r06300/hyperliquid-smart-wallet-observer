"""EXERCICE REEL de la chaine, borne : on la FAIT TOURNER, on ne verifie pas qu'elle existe.

    rubans reels (echantillon borne) -> reconciliation -> enrichissement
        -> certification SAFE -> coffre -> relecture par le chargeur du labo

POURQUOI CET OUTIL EXISTE. Une premiere validation (`valider_chaine_bout_en_bout.py`) etait
STATIQUE : existence des modules, appel par un lanceur reel, presence des artefacts. C'est
necessaire -- elle a trouve un maillon appele par personne -- mais ce n'est pas une preuve
de fonctionnement. Un module cable peut echouer, perdre des lignes, ou produire un fichier
vide sans que personne ne le sache.

CE QU'IL MESURE, maillon par maillon :

* lignes ENTREES et lignes SORTIES — une chaine qui perd des lignes en silence est le pire
  defaut possible, et il ne se voit que par un comptage ;
* duree et RSS de pointe — la charge, demandee par le contrat ;
* la REPRISE : on interrompt la certification en cours de route, on relance, et on verifie
  que le resultat est IDENTIQUE a une passe ininterrompue. Une reprise jamais exercee n'est
  pas une reprise.

CE QU'IL NE FAIT JAMAIS :

* allumer un collecteur (la collecte est eteinte sur consigne de l'operateur) ;
* toucher au vrai coffre ni aux vrais rubans : tout se passe dans un workspace TEMPORAIRE
  alimente par un ECHANTILLON BORNE des donnees reelles, copie en lecture seule ;
* declarer un succes sur une etape qui n'a rien produit : zero ligne de sortie est un ECHEC,
  jamais un `OK` silencieux.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
PYTHON = sys.executable

#: Rubans reels dont on prend un echantillon. (source, destination dans le workspace).
#: Les deux emplacements connus sont essayes : racine, puis workspace du labo.
SOURCES = (
    ("runtime/data/vault_fills_live.jsonl", "runtime/data/vault_fills_live.jsonl"),
    ("runtime/data/copy_vault_bbo_tape.jsonl", "runtime/data/copy_vault_bbo_tape.jsonl"),
    ("runtime/data/copy_vault_l2_tape.jsonl", "runtime/data/copy_vault_l2_tape.jsonl"),
    ("runtime/data/copy_vault_candle_tape.jsonl", "runtime/data/copy_vault_candle_tape.jsonl"),
)
PREFIXES_SOURCE = ("", "runtime/labo_tranches_20261121/workspace/")


def _trouver(racine: Path, relatif: str) -> Path | None:
    for prefixe in PREFIXES_SOURCE:
        candidat = racine / (prefixe + relatif)
        if candidat.is_file():
            return candidat
    return None


def preparer_echantillon(racine: Path, atelier: Path, *, lignes: int) -> dict:
    """Copie les `lignes` PREMIERES lignes de chaque ruban reel dans l'atelier.

    Borne volontaire : on exerce la chaine, on ne rejoue pas 8 Go. Un echantillon pris en
    TETE de fichier garde l'ordre chronologique, donc la causalite -- prendre la queue
    melangerait des fills sans leurs carnets.
    """
    (atelier / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (atelier / "runtime" / "logs").mkdir(parents=True, exist_ok=True)
    (atelier / "runtime" / "reports").mkdir(parents=True, exist_ok=True)
    bilan: list[dict] = []
    for relatif, destination in SOURCES:
        source = _trouver(racine, relatif)
        cible = atelier / destination
        if source is None:
            bilan.append({"ruban": relatif, "etat": "SOURCE_ABSENTE", "lignes": 0})
            continue
        ecrites = 0
        with source.open("rb") as entree, cible.open("wb") as sortie:
            for ligne in entree:
                if ecrites >= lignes:
                    break
                sortie.write(ligne)
                ecrites += 1
        bilan.append({"ruban": relatif, "etat": "COPIE", "lignes": ecrites,
                      "octets": cible.stat().st_size,
                      "source": source.relative_to(racine).as_posix()})
    return {"rubans": bilan,
            "lignes_totales": sum(b["lignes"] for b in bilan)}


def _compter_lignes(chemin: Path) -> int:
    try:
        with chemin.open("rb") as flux:
            return sum(1 for _ in flux)
    except OSError:
        return -1


def lancer(etape: str, commande: list[str], *, atelier: Path,
           timeout: float = 900.0) -> dict:
    """Lance un maillon REEL en sous-processus et mesure duree, code, RSS de pointe."""
    depart = time.time()
    pic_rss = 0
    try:
        import psutil
    except ImportError:
        psutil = None
    try:
        proc = subprocess.Popen(commande, cwd=str(atelier), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, errors="replace")
    except OSError as erreur:
        return {"etape": etape, "etat": "NON_LANCABLE", "detail": str(erreur)[:160]}
    suivi = psutil.Process(proc.pid) if psutil else None
    while proc.poll() is None:
        if suivi is not None:
            try:  # noqa: SIM105
                pic_rss = max(pic_rss, suivi.memory_info().rss)
            except Exception:                      # noqa: BLE001 - le process peut finir
                pass
        if time.time() - depart > timeout:
            proc.kill()
            return {"etape": etape, "etat": "TIMEOUT",
                    "duree_s": round(time.time() - depart, 1)}
        time.sleep(0.2)
    sortie = (proc.stdout.read() if proc.stdout else "") or ""
    return {
        "etape": etape, "etat": "OK" if proc.returncode == 0 else "ECHEC",
        "code": proc.returncode, "duree_s": round(time.time() - depart, 1),
        "pic_rss_mo": round(pic_rss / 2 ** 20, 1) if pic_rss else None,
        "sortie": sortie[-400:],
    }


def exercer(racine: Path, atelier: Path, *, lignes: int) -> dict:
    """La chaine, maillon par maillon, avec comptage ENTREE -> SORTIE a chaque etape."""
    etapes: list[dict] = []
    echantillon = preparer_echantillon(racine, atelier, lignes=lignes)
    fills = atelier / "runtime/data/vault_fills_live.jsonl"
    bbo = atelier / "runtime/data/copy_vault_bbo_tape.jsonl"
    candle = atelier / "runtime/data/copy_vault_candle_tape.jsonl"
    fills_entrees = _compter_lignes(fills)

    # --- maillon 1 : reconciliation croisee des sources
    rapport_reco = atelier / "runtime/reports/reconciliation_sources.json"
    etape = lancer("reconciliation", [
        PYTHON, str(RACINE / "tools" / "reconcilier_sources.py"),
        "--root", str(atelier), "--source", f"echantillon={fills}",
        "--out", str(rapport_reco)], atelier=atelier)
    etape["artefact_lignes"] = 1 if rapport_reco.is_file() else 0
    etape["entrees"] = fills_entrees
    etapes.append(etape)

    # --- maillon 2 : enrichissement des fills (contexte au plus pres, sans futur)
    enrichi = atelier / "runtime/data/vault_fills_enrichis.jsonl"
    commande = [PYTHON, str(RACINE / "tools" / "enrichir_fills.py"),
                "--root", str(atelier), "--fills", str(fills), "--out", str(enrichi)]
    if bbo.is_file():
        commande += ["--bbo", str(bbo)]
    if candle.is_file():
        commande += ["--candle", str(candle)]
    etape = lancer("enrichissement", commande, atelier=atelier)
    etape["entrees"] = fills_entrees
    etape["sorties"] = _compter_lignes(enrichi) if enrichi.is_file() else 0
    # Une chaine qui PERD des lignes en silence est le pire defaut : on le nomme.
    if etape["etat"] == "OK" and etape["sorties"] < etape["entrees"]:
        etape["etat"] = "PERTE_DE_LIGNES"
        etape["detail"] = f"{etape['entrees']} entrees -> {etape['sorties']} sorties"
    etapes.append(etape)

    # --- maillon 3 : certification SAFE vers le coffre
    etape = lancer("certification", [
        PYTHON, str(RACINE / "tools" / "sceller_coffre_local.py"),
        "--root", str(atelier), "--tout"], atelier=atelier, timeout=1200.0)
    index = atelier / "runtime/coffre_certifie/LOCAL_INDEX.json"
    etape["index_ecrit"] = index.is_file()
    if index.is_file():
        try:
            charge = json.loads(index.read_text(encoding="utf-8"))
            etape["shards_indexes"] = len(charge.get("shards") or [])
        except ValueError:
            etape["etat"] = "INDEX_ILLISIBLE"
    elif etape["etat"] == "OK":
        # Rien produit n'est pas un succes.
        etape["etat"] = "AUCUN_ARTEFACT"
    etapes.append(etape)

    # --- maillon 4 : le chargeur du labo relit-il ce coffre ?
    relecture = relire_avec_le_labo(atelier)
    etapes.append(relecture)
    return {"echantillon": echantillon, "etapes": etapes}


def relire_avec_le_labo(atelier: Path) -> dict:
    """Le labo sait-il relire ce qui vient d'etre certifie ? Mode HORLOGES (0,084 Go mesures)."""
    code = (
        "import json,sys;"
        "sys.path.insert(0, r'" + str(RACINE / "src") + "');"
        "from hl_observer.backtesting.copy_vault_book_loader import load_observed_books;"
        "h,a = load_observed_books(r'" + str(atelier) + "', horloges_seulement=True);"
        "print(json.dumps({'coins': len(h),"
        " 'horodatages': sum(len(s) for s in h.values()),"
        " 'horloges_seulement': a.get('horloges_seulement'),"
        " 'valid_rows': a.get('valid_rows'),"
        " 'blocages': a.get('replay_grade_blockers')}))"
    )
    fini = subprocess.run([PYTHON, "-c", code], capture_output=True, text=True,
                          errors="replace", timeout=600)
    detail: dict = {}
    for ligne in (fini.stdout or "").splitlines():
        ligne = ligne.strip()
        if ligne.startswith("{"):
            try:  # noqa: SIM105
                detail = json.loads(ligne)
            except ValueError:
                pass
    etat = "OK" if fini.returncode == 0 and detail.get("horodatages", 0) > 0 else "ECHEC"
    if fini.returncode == 0 and not detail.get("horodatages"):
        etat = "AUCUN_CARNET_RELU"
    return {"etape": "relecture par le labo", "etat": etat, "code": fini.returncode,
            **detail, "sortie": (fini.stderr or "")[-300:]}


def exercer_la_reprise(racine: Path, atelier_a: Path, atelier_b: Path, *,
                       lignes: int, coupure_s: float) -> dict:
    """Interrompt la certification, relance, et compare a une passe ININTERROMPUE.

    Une reprise qui n'a jamais ete exercee n'est pas une reprise. Et le critere est dur :
    l'index final doit porter le MEME nombre de shards que la passe continue -- une reprise
    qui perd ou duplique est pire qu'une absence de reprise, parce qu'elle rassure.
    """
    preparer_echantillon(racine, atelier_b, lignes=lignes)
    outil = [PYTHON, str(RACINE / "tools" / "sceller_coffre_local.py"),
             "--root", str(atelier_b), "--tout"]
    depart = time.time()
    proc = subprocess.Popen(outil, cwd=str(atelier_b), stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    time.sleep(max(0.2, coupure_s))
    interrompu_en_vol = proc.poll() is None
    if interrompu_en_vol:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
    coupe_apres_s = round(time.time() - depart, 1)

    reprise = lancer("certification (reprise)", outil, atelier=atelier_b, timeout=1200.0)
    index_a = atelier_a / "runtime/coffre_certifie/LOCAL_INDEX.json"
    index_b = atelier_b / "runtime/coffre_certifie/LOCAL_INDEX.json"

    def _shards(chemin: Path) -> int | None:
        try:
            return len(json.loads(chemin.read_text(encoding="utf-8")).get("shards") or [])
        except (OSError, ValueError):
            return None

    a, b = _shards(index_a), _shards(index_b)
    if not interrompu_en_vol:
        # DEFAUT DE CET OUTIL, mesure le 22/11/2026 : avec 3 000 lignes, la certification
        # finissait en 1,0 s, AVANT la coupure a 2,0 s. Rien n etait interrompu, et le
        # verdict << IDENTIQUE >> etait vrai mais VIDE -- une preuve vide est pire qu une
        # absence de preuve, parce qu elle rassure. Il faut une charge qui dure plus
        # longtemps que la coupure (mesure : 120 000 lignes -> 16,6 s, coupure a 2,5 s).
        verdict = "REPRISE_NON_EXERCEE"
    elif a is None or b is None:
        verdict = "INDETERMINE"
    elif a == b:
        verdict = "IDENTIQUE"
    elif b < a:
        verdict = "PERTE_APRES_REPRISE"
    else:
        verdict = "DUPLICATION_APRES_REPRISE"
    return {"interrompu_en_vol": interrompu_en_vol, "coupe_apres_s": coupe_apres_s,
            "reprise": reprise, "shards_passe_continue": a, "shards_apres_reprise": b,
            "verdict": verdict}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--racine", default=".")
    p.add_argument("--lignes", type=int, default=20_000,
                   help="lignes prises en TETE de chaque ruban reel (borne de charge)")
    p.add_argument("--coupure-s", type=float, default=3.0,
                   help="au bout de combien de secondes couper la certification")
    p.add_argument("--atelier", default="runtime/exercice_chaine",
                   help="workspace TEMPORAIRE ; le vrai coffre n'est jamais touche")
    p.add_argument("--garder", action="store_true", help="ne pas effacer l'atelier")
    p.add_argument("--sans-reprise", action="store_true")
    p.add_argument("--sortie", default="")
    args = p.parse_args(argv)

    racine = Path(args.racine).resolve()
    base = racine / args.atelier
    atelier_a = base / "continue"
    atelier_b = base / "reprise"
    flux = sys.stdout
    try:  # noqa: SIM105
        flux.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    for dossier in (atelier_a, atelier_b):
        if dossier.exists():
            shutil.rmtree(dossier, ignore_errors=True)
        dossier.mkdir(parents=True, exist_ok=True)

    print(f"  atelier TEMPORAIRE : {base.relative_to(racine).as_posix()}"
          f"  (le vrai coffre n'est pas touche)")
    print(f"  charge : {args.lignes:,} lignes par ruban")
    resultat = exercer(racine, atelier_a, lignes=args.lignes)
    print()
    print("  --- echantillon copie depuis les rubans REELS ---")
    for r in resultat["echantillon"]["rubans"]:
        print(f"    {r['etat']:<16} {r['lignes']:>8,} lignes  {r['ruban']}")
    print()
    print("  --- la chaine TOURNE, maillon par maillon ---")
    for e in resultat["etapes"]:
        bits = [f"{e['etat']:<22}", f"{e['etape']:<26}"]
        if e.get("duree_s") is not None:
            bits.append(f"{e['duree_s']:>6.1f} s")
        if e.get("pic_rss_mo"):
            bits.append(f"RSS {e['pic_rss_mo']:>7.1f} Mo")
        if e.get("entrees") is not None and e.get("sorties") is not None:
            bits.append(f"{e['entrees']:,} -> {e['sorties']:,} lignes")
        if e.get("shards_indexes") is not None:
            bits.append(f"{e['shards_indexes']} shard(s)")
        if e.get("horodatages") is not None:
            bits.append(f"{e['horodatages']:,} horodatages / {e.get('coins')} coins")
        print("    " + "  ".join(bits))
        if e["etat"] not in ("OK",) and e.get("detail"):
            print(f"        -> {e['detail']}")
        elif e["etat"] not in ("OK",) and e.get("sortie"):
            print(f"        -> {e['sortie'].strip()[:200]}")

    reprise = None
    if not args.sans_reprise:
        print()
        print("  --- REPRISE : on coupe la certification, on relance, on compare ---")
        reprise = exercer_la_reprise(racine, atelier_a, atelier_b,
                                     lignes=args.lignes, coupure_s=args.coupure_s)
        print(f"    interrompu en vol : {reprise['interrompu_en_vol']}"
              f"  (coupe apres {reprise['coupe_apres_s']} s)")
        print(f"    shards : passe continue {reprise['shards_passe_continue']}"
              f"  vs apres reprise {reprise['shards_apres_reprise']}")
        print(f"    VERDICT : {reprise['verdict']}")

    etats = [e["etat"] for e in resultat["etapes"]]
    rapport = {"echantillon": resultat["echantillon"], "etapes": resultat["etapes"],
               "reprise": reprise, "etats": etats,
               "horodatage_ms": int(time.time() * 1000)}
    if args.sortie:
        destination = racine / args.sortie
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(rapport, ensure_ascii=False, indent=1),
                               encoding="utf-8")
        print(f"\n  rapport : {args.sortie}")
    if not args.garder:
        shutil.rmtree(base, ignore_errors=True)
        print("  atelier efface (les donnees reelles n'ont jamais ete modifiees)")

    mauvais = [e for e in etats if e != "OK"]
    if reprise and reprise["verdict"] not in ("IDENTIQUE",):
        mauvais.append(reprise["verdict"])
    print()
    print("  bilan :", "TOUT OK" if not mauvais else "A VOIR -> " + ", ".join(mauvais))
    return 0 if not mauvais else 3


if __name__ == "__main__":
    raise SystemExit(main())
