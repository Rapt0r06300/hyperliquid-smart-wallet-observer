"""L'ETAT REEL de la collecte, a QUATRE niveaux qu'il ne faut jamais confondre.

    processus vivant  !=  collecte fonctionnelle  !=  donnees fraiches  !=  certifiables

Un processus actif qui ne collecte plus ne doit JAMAIS etre marque OK. C'est la regle que
cet outil applique, et chaque niveau est mesure separement.

CE QUI L'A RENDU NECESSAIRE, mesures du 22/11/2026 sur le vrai lanceur en `--status` :

* `runtime/data/economic_collection_pids.json` listait **20 workers avec leurs PID** alors
  que l'identification par ligne de commande en trouvait **0 vivant**. Le fichier decrivait
  une campagne morte depuis 10,2 h. Un watchdog qui s'y fierait croirait tout sain -- ou
  tuerait ces PID, desormais recycles par d'autres processus.
* L'ecran affichait `Lease valide: ?` **pour toujours** : il lisait `d.get("lease_valid")`,
  une clef qui n'existe pas dans ce fichier. Le bail y vit sous `lease`, avec
  `expires_at_ms`. Un homonyme de clef decidait donc la mesure -- et rendait `?` au lieu
  de dire que le bail etait expire depuis dix heures.
* Le fichier annonce `pids: 20` et `demarres_et_verifies: 19` : une incoherence interne que
  personne ne regardait.

AUCUN ARRET, AUCUNE ECRITURE dans les rubans : cet outil lit et rend un verdict.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))

import collecteurs_balayage as balayage  # noqa: E402

ETAT_CAMPAGNE = "runtime/data/economic_collection_pids.json"

#: Rubans dont la FRAICHEUR dit si la collecte produit encore, et pas seulement si des
#: processus respirent. Un ruban qui n'a pas grandi depuis une heure est un signal, meme si
#: vingt processus sont vivants.
#:
#: PERIME 22/11/2026 -- la liste contenait `copy_vault_bbo_tape.jsonl` et
#:   `copy_vault_trades_tape.jsonl`. Le premier est ecrit par un TELECHARGEUR des lanes cloud
#:   (`telecharger_l2_lanes_github.py`), pas par un collecteur local ; le second n'est ecrit par
#:   PERSONNE (absent du registre `couverture_donnees.FLUX`). L'ecran criait donc
#:   RUBANS_ABSENTS en permanence, y compris sept minutes apres un demarrage ou le BBO et les
#:   trades s'ecrivaient bel et bien -- sous leur vrai nom, `*_lane.jsonl`. Un homonyme
#:   (tape / lane) decidait la mesure. Chaque ruban ci-dessous a desormais pour producteur un
#:   collecteur LOCAL du registre ; `tests/test_etat_collecte_incoherence.py` le garde.
RUBANS_SURVEILLES = (
    "runtime/data/vault_fills_live.jsonl",
    "runtime/data/copy_vault_bbo_lane.jsonl",
    "runtime/data/copy_vault_l2_tape.jsonl",
    "runtime/data/copy_vault_trades_lane.jsonl",
)

#: Au-dela, un ruban est dit PERIME. Choisi sur le pire cas mesure : les fills arrivent par
#: lots de 4 h (`collecteur_flux_par_lot`), donc un seuil plus court crierait au loup entre
#: deux passes. 5 h laisse une marge sans masquer une panne.
AGE_RUBAN_PERIME_S = 5 * 3600.0


def validite_du_bail(etat: dict, *, maintenant_ms: int | None = None) -> dict:
    """Le bail est-il encore valide ? Lu sous `lease.expires_at_ms`, PAS `lease_valid`.

    `lease_valid` appartient a un AUTRE schema (`bounded_collection`) : le chercher ici
    rendait `?` pour toujours, donc << je ne sais pas >> affiche comme un etat normal.
    """
    ms = int(time.time() * 1000) if maintenant_ms is None else int(maintenant_ms)
    bail = etat.get("lease")
    if not isinstance(bail, dict):
        return {"valide": None, "motif": "BAIL_ABSENT", "reste_s": None, "lease_id": None}
    expire = bail.get("expires_at_ms")
    if not isinstance(expire, int):
        return {"valide": None, "motif": "EXPIRATION_ILLISIBLE", "reste_s": None,
                "lease_id": bail.get("lease_id")}
    reste_s = (expire - ms) / 1000.0
    return {
        "valide": reste_s > 0,
        "motif": "VALIDE" if reste_s > 0 else "EXPIRE",
        "reste_s": round(reste_s, 1),
        "lease_id": bail.get("lease_id"),
        "emis_il_y_a_s": (round((ms - bail["issued_at_ms"]) / 1000.0, 1)
                          if isinstance(bail.get("issued_at_ms"), int) else None),
    }


def workers_reellement_vivants(etat: dict, *, processus, racine) -> dict:
    """Croise les PID DECLARES avec leur identite REELLE.

    C'est la mesure qui separe << vingt workers listes >> de << vingt workers vivants >>.
    Chaque PID refuse l'est avec un motif : un `.pid` perime ne doit pas devenir un OK.
    """
    declares = etat.get("pids")
    if not isinstance(declares, dict):
        return {"declares": 0, "vivants": [], "morts": [], "motif": "PIDS_ABSENTS"}
    vivants: list[dict] = []
    morts: list[dict] = []
    for nom, pid in sorted(declares.items()):
        verdict = balayage.identifier_pid(pid, processus=processus, racine=racine)
        ligne = {"famille": str(nom), "pid": verdict.get("pid"),
                 "motif": verdict["motif"]}
        (vivants if verdict["identifie"] else morts).append(ligne)
    return {"declares": len(declares), "vivants": vivants, "morts": morts, "motif": None}


def fraicheur_des_rubans(racine, *, rubans=RUBANS_SURVEILLES,
                         maintenant: float | None = None) -> list[dict]:
    """Age et taille de chaque ruban surveille. `age_s=None` quand le ruban est absent.

    L'absence et la perime sont DISTINGUEES : << ce flux n'existe pas >> et << ce flux ne
    bouge plus >> n'appellent pas la meme action.
    """
    now = time.time() if maintenant is None else float(maintenant)
    sortie: list[dict] = []
    for relatif in rubans:
        chemin = Path(racine) / relatif
        try:
            stat = chemin.stat()
        except OSError:
            sortie.append({"ruban": relatif, "age_s": None, "octets": None,
                           "etat": "ABSENT"})
            continue
        age = now - stat.st_mtime
        sortie.append({
            "ruban": relatif, "age_s": round(age, 1), "octets": stat.st_size,
            "etat": "PERIME" if age > AGE_RUBAN_PERIME_S else "FRAIS",
        })
    return sortie


def verdict_global(*, bail: dict, workers: dict, rubans: list[dict],
                   identifies_par_commande: int) -> dict:
    """Le verdict a QUATRE niveaux, chacun mesure a part.

    On ne remonte jamais un niveau sur la foi d'un autre : des processus vivants ne
    prouvent pas que les donnees arrivent, et des donnees fraiches ne prouvent pas
    qu'elles sont certifiables.
    """
    vivants = len(workers.get("vivants") or [])
    morts = len(workers.get("morts") or [])
    frais = [r for r in rubans if r["etat"] == "FRAIS"]
    perimes = [r for r in rubans if r["etat"] == "PERIME"]
    absents = [r for r in rubans if r["etat"] == "ABSENT"]

    if identifies_par_commande == 0 and vivants == 0:
        processus = "AUCUN"
    elif identifies_par_commande > 0:
        processus = "VIVANTS"
    else:
        processus = "DECLARES_MAIS_INTROUVABLES"

    if processus == "AUCUN":
        collecte = "ARRETEE"
    elif frais:
        collecte = "PRODUIT"
    else:
        # Le cas que la mission interdit de marquer OK : ca respire, ca ne collecte plus.
        collecte = "PROCESSUS_VIVANTS_MAIS_AUCUNE_DONNEE_FRAICHE"

    alertes: list[str] = []
    if morts and vivants == 0 and morts > 0:
        alertes.append(f"ETAT_PERIME: {morts} worker(s) declare(s) introuvable(s)")
    if bail.get("valide") is False:
        alertes.append(f"BAIL_EXPIRE depuis {-1 * (bail.get('reste_s') or 0):.0f} s")
    if bail.get("valide") is None:
        alertes.append(f"BAIL_INDETERMINE: {bail.get('motif')}")
    if perimes:
        alertes.append("RUBANS_PERIMES: " + ", ".join(r["ruban"] for r in perimes))
    if absents:
        alertes.append("RUBANS_ABSENTS: " + ", ".join(r["ruban"] for r in absents))

    return {
        "processus": processus,
        "collecte": collecte,
        "workers_declares": workers.get("declares", 0),
        "workers_vivants": vivants,
        "workers_morts": morts,
        "identifies_par_commande": identifies_par_commande,
        "rubans_frais": len(frais), "rubans_perimes": len(perimes),
        "rubans_absents": len(absents),
        "bail": bail.get("motif"),
        "alertes": alertes,
    }


def incoherence_interne(etat: dict) -> str | None:
    """Le fichier d'etat se contredit-il lui-meme ? Rend l'alerte, ou None.

    Invariant du schema : chaque nom de `pids` est soit DEMARRE ET VERIFIE par ce lancement,
    soit REUTILISE (deja vivant, repris). On compare des ENSEMBLES de noms, pas des longueurs :
    deux longueurs egales peuvent cacher deux noms differents, et deux longueurs inegales sont
    normales des qu'un collecteur est reutilise.

    Champs absents ou d'un autre type -> None : on ne declare pas incoherent ce qu'on n'a pas
    su lire (l'alerte de lecture est ailleurs).
    """
    pids, verifies = etat.get("pids"), etat.get("demarres_et_verifies")
    if not isinstance(pids, dict) or not isinstance(verifies, list):
        return None
    reutilises = etat.get("reutilises")
    reutilises = reutilises if isinstance(reutilises, list) else []
    connus = {str(n) for n in verifies} | {str(n) for n in reutilises}
    declares = {str(n) for n in pids}
    sans_statut = sorted(declares - connus)          # un PID que rien n'a verifie ni repris
    sans_pid = sorted(connus - declares)             # annonce demarre/repris, mais aucun PID
    if not sans_statut and not sans_pid:
        return None
    morceaux = []
    if sans_statut:
        morceaux.append("PID ni verifie ni reutilise : " + ", ".join(sans_statut))
    if sans_pid:
        morceaux.append("annonce sans PID : " + ", ".join(sans_pid))
    return (f"ETAT_INCOHERENT: pids={len(declares)}, demarres_et_verifies={len(verifies)},"
            f" reutilises={len(reutilises)} ; " + " ; ".join(morceaux))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--racine", default=".")
    p.add_argument("--etat", default=ETAT_CAMPAGNE)
    p.add_argument("--json", action="store_true", help="sortie machine")
    args = p.parse_args(argv)

    racine = Path(args.racine).resolve()
    flux = sys.stdout
    try:  # noqa: SIM105
        flux.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    chemin_etat = racine / args.etat
    try:
        etat = json.loads(chemin_etat.read_text(encoding="utf-8"))
        age_etat_s = time.time() - chemin_etat.stat().st_mtime
    except (OSError, ValueError):
        etat, age_etat_s = {}, None

    processus = balayage.lister_processus_detailles()
    identifies = balayage.pids_collecteurs_a_tuer(
        [(x["pid"], x["cmdline"]) for x in processus],
        self_pid=os.getpid(), racine=str(racine))
    bail = validite_du_bail(etat)
    workers = workers_reellement_vivants(etat, processus=processus, racine=str(racine))
    rubans = fraicheur_des_rubans(racine)
    verdict = verdict_global(bail=bail, workers=workers, rubans=rubans,
                             identifies_par_commande=len(identifies))
    verdict["age_fichier_etat_s"] = None if age_etat_s is None else round(age_etat_s, 1)
    # Incoherence interne du fichier, que personne ne regardait.
    # PERIME 22/11/2026 -- l ancienne regle comparait deux LONGUEURS (`pids` contre
    #   `demarres_et_verifies`) et ignorait `reutilises`. Un collecteur deja vivant, repris tel
    #   quel par le superviseur, est un etat LEGITIME : il a un PID sans figurer parmi les
    #   « demarres ». Mesure du jour : 20 pids = 19 demarres + 1 reutilise (`userfills-poll`),
    #   et l ecran criait ETAT_INCOHERENT sur un etat sain. Ancienne regle, conservee :
    #     if len(declares_verifies) != len(etat["pids"]): alerte
    incoherence = incoherence_interne(etat)
    if incoherence:
        verdict["alertes"].append(incoherence)

    if args.json:
        print(json.dumps({"verdict": verdict, "bail": bail, "rubans": rubans,
                          "workers": workers}, ensure_ascii=False, indent=1))
        return 0

    print("  --- ETAT REEL DE LA COLLECTE (4 niveaux distincts) ---")
    print(f"  processus          : {verdict['processus']}"
          f"  ({verdict['identifies_par_commande']} identifie(s) par leur commande)")
    print(f"  collecte           : {verdict['collecte']}")
    print(f"  workers declares   : {verdict['workers_declares']}"
          f"  vivants {verdict['workers_vivants']}  INTROUVABLES {verdict['workers_morts']}")
    age = verdict["age_fichier_etat_s"]
    print(f"  fichier d'etat     : {'age inconnu' if age is None else f'{age / 3600:.1f} h'}")
    print(f"  bail               : {bail['motif']}"
          + (f"  (reste {bail['reste_s']:.0f} s)" if bail.get("reste_s") is not None else ""))
    for r in rubans:
        age_txt = "absent" if r["age_s"] is None else f"{r['age_s'] / 60:.0f} min"
        print(f"    {r['etat']:<7} {age_txt:>10}  {r['ruban']}")
    for alerte in verdict["alertes"]:
        print(f"  ALERTE             : {alerte}")
    if not verdict["alertes"]:
        print("  aucune alerte")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
